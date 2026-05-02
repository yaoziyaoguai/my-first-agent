"""Second-round realistic dogfooding smoke coverage.

这些测试把第二轮 dogfooding 中已经确认可复现、且不依赖真实 LLM/secret
的路径固化下来：多步骤读写、Ask User free-text 恢复、tool failure、
checkpoint/resume、MCP local fixture、以及多确认压力。

边界说明：
- 这里是 tests-only smoke harness，不是新功能入口；
- 使用 FakeAnthropicClient 和本地 fixture，避免真实外部 LLM、token MCP
  server、真实 sessions/runs/logs；
- sandbox 文件只写到项目内 workspace/self_dogfood_* 临时目录，并在测试
  finally 中删除；
- runtime/checkpoint/TUI/MCP 生产语义不在本文件重写，只通过现有 public
  entrypoints 观察。
"""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import uuid

from tests.conftest import (
    FakeAnthropicClient,
    FakeResponse,
    FakeToolUseBlock,
    meta_complete_response,
    text_response,
    tool_use_response,
)
from tests.test_complex_scenarios import _plan_response, _tool_use_resp
from tests.test_main_loop import _planner_no_plan_response


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT_ROOT / "workspace"
MCP_FIXTURE_SERVER = PROJECT_ROOT / "tests" / "fixtures" / "minimal_mcp_stdio_server.py"


def _noop(*args, **kwargs):
    return None


def _patch_runtime_artifact_sinks(monkeypatch, checkpoint_path: Path | None = None) -> None:
    """把 dogfooding smoke 的持久化边界重定向到 no-op 或 tmp checkpoint。

    第二轮 dogfooding 的目标是验证 runtime flow，而不是读取/写入真实
    agent_log.jsonl、sessions、runs 或开发者本地 checkpoint。因此测试只在
    明确需要 checkpoint/resume evidence 时把 CHECKPOINT_PATH 指到 tmp_path；
    其他观测日志和 session snapshot 都 patch 成 no-op。
    """

    from agent import checkpoint
    import agent.logger as legacy_logger
    import agent.runtime_observer as runtime_observer

    monkeypatch.setattr(legacy_logger, "log_event", _noop)
    monkeypatch.setattr(legacy_logger, "save_session_snapshot", _noop)
    monkeypatch.setattr(runtime_observer, "log_event", _noop)
    monkeypatch.setattr(runtime_observer, "log_resolution", _noop)
    monkeypatch.setattr(runtime_observer, "log_transition", _noop)
    monkeypatch.setattr(runtime_observer, "log_action", _noop, raising=False)

    for module_name, module in list(sys.modules.items()):
        if module_name.startswith("agent") and hasattr(module, "log_event"):
            monkeypatch.setattr(module, "log_event", _noop, raising=False)

    if checkpoint_path is None:
        monkeypatch.setattr(checkpoint, "save_checkpoint", _noop)
        monkeypatch.setattr(checkpoint, "clear_checkpoint", _noop)
        save_func = _noop
        clear_func = _noop
    else:
        monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", checkpoint_path)
        save_func = checkpoint.save_checkpoint
        clear_func = checkpoint.clear_checkpoint

    for module_name in (
        "agent.response_handlers",
        "agent.tool_executor",
        "agent.task_runtime",
        "agent.confirm_handlers",
        "agent.session",
    ):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        if hasattr(module, "save_checkpoint"):
            monkeypatch.setattr(module, "save_checkpoint", save_func)
        if hasattr(module, "clear_checkpoint"):
            monkeypatch.setattr(module, "clear_checkpoint", clear_func)


def _reset_runtime(monkeypatch, fake: FakeAnthropicClient, checkpoint_path: Path | None = None):
    """安装 fake provider 和隔离状态，复用真实 core.chat 主入口。

    这不是 mock runtime：测试仍走 core.chat、tool_executor、tool_registry、
    checkpoint load/save 等真实路径；fake 的只有 LLM provider 输出和日志落盘。
    """

    from agent import core
    from agent.state import create_agent_state
    import agent.tools  # noqa: F401 - 注册默认工具

    _patch_runtime_artifact_sinks(monkeypatch, checkpoint_path)
    state = create_agent_state(
        "second dogfooding smoke system prompt",
        model_name="test-model",
        review_enabled=False,
        max_recent_messages=6,
    )
    monkeypatch.setattr(core, "state", state)
    monkeypatch.setattr(core, "client", fake)
    if hasattr(core, "log_runtime_event"):
        monkeypatch.setattr(core, "log_runtime_event", _noop)
    return state


def _tool_results(state) -> list[dict]:
    """收集 conversation.messages 中的 tool_result，检查配对和失败映射。"""

    results: list[dict] = []
    for message in state.conversation.messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                results.append({
                    "tool_use_id": block.get("tool_use_id"),
                    "content": str(block.get("content", "")),
                })
    return results


def _drive_confirmations(max_turns: int = 16) -> list[str]:
    """用用户确认 y 推进 pending plan/step/tool，记录交互频率 evidence。

    本 helper 只模拟用户连续确认，不改变 confirmation policy；它帮助 smoke
    测试判断多步任务有没有卡在 pending 状态或重复执行工具。
    """

    from agent import core

    statuses: list[str] = []
    for _ in range(max_turns):
        status = core.state.task.status
        statuses.append(status)
        if status not in {
            "awaiting_plan_confirmation",
            "awaiting_step_confirmation",
            "awaiting_tool_confirmation",
        }:
            return statuses
        core.chat("y")
    raise AssertionError(f"confirmation flow exceeded {max_turns} turns: {statuses}")


def _make_workspace_sandbox() -> tuple[Path, Path]:
    """创建项目内临时 sandbox，返回 (relative_path, absolute_path)。"""

    rel = Path("workspace") / f"second_dogfood_{uuid.uuid4().hex[:10]}"
    abs_path = PROJECT_ROOT / rel
    abs_path.mkdir(parents=True, exist_ok=True)
    return rel, abs_path


def test_second_round_multistep_read_write_readback_smoke(monkeypatch):
    """真实多步骤读写 smoke：read_file -> write_file -> read_file。

    保护边界：
    - planning/confirmation 仍由 runtime 负责；
    - write_file 仍必须走项目根 path safety 和工具确认；
    - tool_result 必须回到 conversation，而不是只靠 stdout 文案。
    """

    sandbox_rel, sandbox_abs = _make_workspace_sandbox()
    summary_rel = sandbox_rel / "path_safety_summary.txt"
    try:
        fake = FakeAnthropicClient([
            _plan_response([
                ("s1", "读取小模块", "read"),
                ("s2", "写 summary", "write"),
                ("s3", "读回确认", "read"),
            ]),
            tool_use_response(
                "read_file",
                {"path": "agent/tools/path_safety.py"},
                tool_id="dogfood_read_module",
            ),
            meta_complete_response(summary="已理解 path safety 职责", outstanding="无"),
            tool_use_response(
                "write_file",
                {
                    "path": summary_rel.as_posix(),
                    "content": "path_safety 负责项目根边界判断。\n",
                },
                tool_id="dogfood_write_summary",
            ),
            meta_complete_response(summary="已写入 summary", outstanding="无"),
            tool_use_response(
                "read_file",
                {"path": summary_rel.as_posix()},
                tool_id="dogfood_read_back",
            ),
            meta_complete_response(summary="已读回确认", outstanding="无"),
        ])
        state = _reset_runtime(monkeypatch, fake)

        from agent import core

        core.chat("请读取一个小型非敏感模块，解释职责，然后写 sandbox summary。")
        statuses = _drive_confirmations()

        assert "awaiting_tool_confirmation" in statuses
        assert (PROJECT_ROOT / summary_rel).read_text(encoding="utf-8") == (
            "path_safety 负责项目根边界判断。\n"
        )
        assert len(_tool_results(state)) >= 3
        assert state.task.status == "idle"
    finally:
        shutil.rmtree(sandbox_abs, ignore_errors=True)


def test_second_round_ask_user_free_text_resumes_from_temp_checkpoint(monkeypatch, tmp_path):
    """Ask User + Other/free-text 必须能经 checkpoint 恢复后继续执行。

    这保护 request_user_input 的真实 runtime contract：模型必须用工具进入
    pending_user_input，用户 free-text 回复后才能恢复；input backend 不能用
    print 伪造等待，也不能绕过 confirmation 直接写文件。
    """

    sandbox_rel, sandbox_abs = _make_workspace_sandbox()
    target_rel = sandbox_rel / "ask_user_target.txt"
    checkpoint_path = tmp_path / "checkpoint.json"
    try:
        ask_response = FakeResponse(
            content=[
                FakeToolUseBlock(
                    id="dogfood_ask",
                    name="request_user_input",
                    input={
                        "question": "请提供要处理的 sandbox 路径，或选择 Other/free-text。",
                        "why_needed": "用户没有给路径，继续执行会猜路径。",
                        "options": ["workspace/<sandbox>/summary.txt", "Other/free-text"],
                    },
                )
            ],
            stop_reason="tool_use",
        )
        fake = FakeAnthropicClient([
            _planner_no_plan_response(),
            ask_response,
            tool_use_response(
                "write_file",
                {"path": target_rel.as_posix(), "content": "ask user resumed\n"},
                tool_id="dogfood_ask_write",
            ),
            text_response("已按用户提供路径写入。"),
        ])
        state = _reset_runtime(monkeypatch, fake, checkpoint_path)

        from agent import core
        from agent.checkpoint import load_checkpoint_to_state
        from agent.state import create_agent_state

        core.chat("请帮我处理一个文件，但我没有告诉你路径。")
        assert state.task.status == "awaiting_user_input"
        assert state.task.pending_user_input_request["options"][-1] == "Other/free-text"
        assert checkpoint_path.exists()

        restored = create_agent_state("restored", model_name="test-model", review_enabled=False)
        assert load_checkpoint_to_state(restored)
        assert restored.task.status == "awaiting_user_input"

        monkeypatch.setattr(core, "state", restored)
        core.chat(f"Other/free-text: {target_rel.as_posix()}")
        assert restored.task.status == "awaiting_tool_confirmation"

        core.chat("y")
        assert (PROJECT_ROOT / target_rel).read_text(encoding="utf-8") == "ask user resumed\n"
        assert restored.task.status == "idle"
    finally:
        shutil.rmtree(sandbox_abs, ignore_errors=True)


def test_second_round_tool_failure_recovery_keeps_tool_result_contract(monkeypatch):
    """不存在文件的 read_file failure 必须保留 legacy ToolResult failure 语义。

    这个 smoke 不是要“修复”失败，而是确认失败能被 runtime 继续总结：失败
    tool_result 要写回 conversation，且不会产生无关文件 diff。
    """

    sandbox_rel, sandbox_abs = _make_workspace_sandbox()
    missing_rel = sandbox_rel / "does_not_exist.txt"
    try:
        fake = FakeAnthropicClient([
            _planner_no_plan_response(),
            tool_use_response("read_file", {"path": missing_rel.as_posix()}, tool_id="dogfood_missing"),
            text_response("失败原因：文件不存在。安全下一步是请用户确认路径。"),
        ])
        state = _reset_runtime(monkeypatch, fake)

        from agent import core

        core.chat("请读取一个不存在的 sandbox 文件，解释失败原因，不要修改文件。")

        failures = _tool_results(state)
        assert any("不存在" in item["content"] for item in failures)
        assert state.task.status == "idle"
        assert not any(sandbox_abs.iterdir())
    finally:
        shutil.rmtree(sandbox_abs, ignore_errors=True)


def test_second_round_mcp_local_fixture_remains_explicit_opt_in(monkeypatch):
    """MCP local fixture 覆盖 list_tools/call_tool/失败映射和 base registry 边界。

    MCP client 可以 list/call，但 MCP tools 不能自动进入默认工具集；只有显式
    register_mcp_tools 后才允许通过 registry 执行，且仍保留 confirmation policy。
    """

    _patch_runtime_artifact_sinks(monkeypatch)

    from agent.mcp import MCPServerConfig, register_mcp_tools
    from agent.mcp_stdio import StdioMCPClient
    from agent.tool_registry import (
        TOOL_REGISTRY,
        execute_tool,
        get_tool_definitions,
        needs_tool_confirmation,
    )
    import agent.tools  # noqa: F401

    client = StdioMCPClient(timeout_seconds=5)
    server = MCPServerConfig(
        name="local_fixture",
        command=sys.executable,
        args=(str(MCP_FIXTURE_SERVER),),
        enabled=True,
    )

    assert "mcp__local_fixture__echo" not in {
        tool["name"] for tool in get_tool_definitions()
    }

    initialize_result = client.initialize(server)
    tools = client.list_tools(server)
    registered = register_mcp_tools([server], client)
    try:
        assert initialize_result["serverInfo"]["name"] == "minimal-local-mcp"
        assert [tool.name for tool in tools] == ["echo"]
        assert registered == ("mcp__local_fixture__echo",)
        assert needs_tool_confirmation("mcp__local_fixture__echo", {"message": "hi"}) is True
        assert execute_tool("mcp__local_fixture__echo", {"message": "hi"}) == "echo: hi"
        assert client.call_tool(
            server,
            "missing",
            {},
        ).to_legacy_tool_result(
            server_name="local_fixture",
            tool_name="missing",
        ).startswith("错误：MCP 工具")
    finally:
        for name in registered:
            TOOL_REGISTRY.pop(name, None)


def test_second_round_confirmation_pressure_has_no_duplicate_tool_results(monkeypatch):
    """多步 always-confirm 工具会有多次确认，但不能重复执行或漏 tool_result。

    第二轮 dogfooding 发现的 P3 级 UX 摩擦是“确认频率可能偏碎”；本测试不把
    它修成新策略，只保护现有策略下更重要的安全语义：每次确认只执行一次，
    tool_use/tool_result 一一对应，避免为降低交互频率而绕过 confirmation。
    """

    calls = {"count": 0}

    def pressure_tool(**kwargs):
        calls["count"] += 1
        return f"pressure ok {calls['count']}"

    from agent.tool_registry import TOOL_REGISTRY, register_tool

    register_tool(
        name="dogfood_pressure_tool",
        description="second-round dogfooding pressure tool",
        parameters={"arg": {"type": "string", "description": "arg"}},
        confirmation="always",
    )(pressure_tool)
    try:
        fake = FakeAnthropicClient([
            _plan_response([
                ("s1", "读", "read"),
                ("s2", "分析", "analyze"),
                ("s3", "写", "write"),
                ("s4", "验证", "read"),
            ]),
            _tool_use_resp("dogfood_pressure_tool", "dogfood_pressure_1", arg="a"),
            meta_complete_response(summary="s1", outstanding="无"),
            _tool_use_resp("dogfood_pressure_tool", "dogfood_pressure_2", arg="b"),
            meta_complete_response(summary="s2", outstanding="无"),
            _tool_use_resp("dogfood_pressure_tool", "dogfood_pressure_3", arg="c"),
            meta_complete_response(summary="s3", outstanding="无"),
            _tool_use_resp("dogfood_pressure_tool", "dogfood_pressure_4", arg="d"),
            meta_complete_response(summary="s4", outstanding="无"),
        ])
        state = _reset_runtime(monkeypatch, fake)

        from agent import core

        core.chat("设计一个 4 步小任务，观察 Ask User / confirmation 是否过碎。")
        statuses = _drive_confirmations()

        result_ids = [item["tool_use_id"] for item in _tool_results(state)]
        assert statuses.count("awaiting_tool_confirmation") == 4
        assert calls["count"] == 4
        assert result_ids == [
            "dogfood_pressure_1",
            "dogfood_pressure_2",
            "dogfood_pressure_3",
            "dogfood_pressure_4",
        ]
        assert state.task.status == "idle"
    finally:
        TOOL_REGISTRY.pop("dogfood_pressure_tool", None)
