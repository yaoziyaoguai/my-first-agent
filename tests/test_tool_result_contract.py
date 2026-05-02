"""Tool result / error contract characterization tests.

本文件只锁当前 ToolResult 现状：工具执行结果仍是字符串或 Anthropic 可接受
block list，错误分类仍依赖 tool_executor 的前缀表。它暴露的是 production gap，
不是最终架构。后续如果引入结构化 ToolResult，应先更新这些 characterization tests。
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace


def _load_builtin_tools() -> None:
    """显式注册内置工具，避免测试依赖 core.py 或测试顺序。"""

    importlib.import_module("agent.tools")


def test_success_result_is_currently_model_visible_string() -> None:
    """成功结果当前会被规范化成 model-visible 字符串。

    这条测试保护 Action -> Observation 的最小现状：即使工具返回 dict，
    registry 也会把它转成字符串，保证后续 `tool_result.content` 可被模型消费。
    这不是最终 ToolResult 设计；它是后续结构化迁移前的基线。
    """

    from agent.tool_registry import TOOL_REGISTRY, execute_tool, register_tool
    from agent.tool_executor import _classify_tool_outcome

    @register_tool(
        name="contract_dict_tool",
        description="returns a dict for normalization characterization",
        parameters={},
        confirmation="never",
    )
    def _contract_dict_tool() -> dict[str, bool]:
        return {"ok": True}

    try:
        result = execute_tool("contract_dict_tool", {})
    finally:
        TOOL_REGISTRY.pop("contract_dict_tool", None)

    assert result == "{'ok': True}"
    assert _classify_tool_outcome(result) == (
        "executed",
        "tool.completed",
        "执行完成。",
    )


def test_unknown_tool_is_failure_like_string_not_success() -> None:
    """未知工具当前返回字符串，并由前缀表归类为 failed。

    这保护 tool-use hallucination 的最小防线：模型调用不存在的工具时，
    runtime 不能把它误报为执行成功；后续可以改成结构化 failure，但不能回退成 success。
    """

    from agent.tool_registry import execute_tool
    from agent.tool_executor import _classify_tool_outcome

    result = execute_tool("totally_unknown_contract_tool", {})

    assert isinstance(result, str)
    assert result == "工具 'totally_unknown_contract_tool' 不在允许列表中"
    assert _classify_tool_outcome(result)[0] == "failed"


def test_missing_required_argument_is_failure_like_string() -> None:
    """参数缺失当前通过 execute_tool 的异常兜底转成 failed 字符串。

    这是现状 characterization：项目还没有独立 ToolValidation layer，
    所以 Python 函数签名错误会在执行入口被捕获为字符串。后续若引入 schema
    validation，应把这个 failure 前移到 validation seam，而不是让异常冒泡。
    """

    _load_builtin_tools()

    from agent.tool_registry import execute_tool
    from agent.tool_executor import _classify_tool_outcome

    result = execute_tool("calculate", {})

    assert isinstance(result, str)
    assert result.startswith("[工具 calculate 执行异常] TypeError:")
    assert _classify_tool_outcome(result)[0] == "failed"


def test_rejected_by_check_prefix_is_not_classified_as_success() -> None:
    """工具内部 safety/pre-hook 拒绝不能被误判为 success。

    `拒绝执行：` 是当前 file/shell safety guard 的重要边界：用户可能已经确认
    工具调用，但工具内部仍可拒绝危险输入。这个 outcome 必须和 success、policy
    denial、user rejection 分开。
    """

    from agent.tool_registry import TOOL_REGISTRY, execute_tool, register_tool
    from agent.tool_executor import _classify_tool_outcome

    @register_tool(
        name="contract_rejected_tool",
        description="always rejected by pre_execute",
        parameters={},
        confirmation="never",
        pre_execute=lambda _name, _input, _context: "拒绝执行：contract guard",
    )
    def _contract_rejected_tool() -> str:
        return "should not run"

    try:
        result = execute_tool("contract_rejected_tool", {})
    finally:
        TOOL_REGISTRY.pop("contract_rejected_tool", None)

    assert result == "拒绝执行：contract guard"
    assert _classify_tool_outcome(result) == (
        "rejected_by_check",
        "tool.rejected",
        "已被工具内部安全检查拒绝。",
    )


def test_append_tool_result_message_shape_is_stable() -> None:
    """tool_result 写回 messages 的结构是当前 Observation 边界。

    Anthropic API 要求 assistant tool_use 后续有对应 user/tool_result。
    这条测试不执行工具，只锁 `append_tool_result` 的消息形状，防止后续重构
    把 tool_result 写成普通文本或丢掉 tool_use_id。
    """

    from agent.conversation_events import append_tool_result

    messages: list[dict] = []
    append_tool_result(messages, "toolu_contract", "contract result")

    assert messages == [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_contract",
                    "content": "contract result",
                }
            ],
        }
    ]


def test_current_tool_error_contract_is_prefix_based() -> None:
    """当前 error/result contract 仍散落在前缀表里。

    这条测试有意锁住 production gap：tool_executor 通过字符串前缀判断 failed /
    rejected，而不是读取结构化 ToolResult。未来迁移到结构化 contract 时，应更新
    这条测试和前缀 inventory，而不是继续扩大字符串判断。
    """

    from agent.tool_executor import TOOL_FAILURE_PREFIXES, TOOL_REJECTION_PREFIXES

    expected_failure_prefixes = {
        "错误：",
        "读取超时：",
        "HTTP 错误：",
        "读取失败：",
        "执行超时：",
        "[工具 ",
        "[安装失败]",
        "[更新失败]",
        "工具 '",
    }

    assert set(TOOL_FAILURE_PREFIXES) == expected_failure_prefixes
    assert TOOL_REJECTION_PREFIXES == ("拒绝执行：",)


def test_existing_output_size_policies_are_tool_local_characterization(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """输出大小策略当前分散在具体工具内。

    read_file 用大文件概览，run_shell 用 5000 字符截断；这说明项目已有
    output budget 意识，但还没有统一 ToolResult output policy。测试只锁现状，
    不要求本轮抽象。
    """

    from agent.tools.file_ops import FILE_CONTENT_LIMIT, read_file
    import agent.tools.shell as shell_tool

    large_file = tmp_path / "large.txt"
    large_file.write_text("x" * (FILE_CONTENT_LIMIT + 1), encoding="utf-8")

    read_result = read_file(str(large_file))
    assert "[读取成功 - 文件较大，以下为概览]" in read_result
    assert f"总字符数: {FILE_CONTENT_LIMIT + 1}" in read_result

    def _fake_run(*_args, **_kwargs):
        return SimpleNamespace(stdout="y" * 6000, stderr="", returncode=0)

    monkeypatch.setattr(shell_tool.subprocess, "run", _fake_run)
    shell_result = shell_tool.run_shell("echo contract-output")

    assert "[退出码: 0]" in shell_result
    assert "输出过长，已截断" in shell_result
    assert "共 6009 字符" in shell_result
