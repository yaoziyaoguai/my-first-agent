"""v0.4 第一阶段 transition boundary 防漂移测试。

这些测试不是为了宣布 Runtime 已经完成事件驱动重构，而是先把迁移前的边界钉住：
轻量事件命名不能写入 checkpoint，health/logs 这类维护命令不能改任务执行态，
CLI status line 不能把内部 dict/dataclass 原样打给用户。
"""

from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError, dataclass, fields
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_runtime_event_kind_names_match_v0_4_prep_scope() -> None:
    """守护 v0.4 命名入口：事件名是候选词汇，不是完整状态机实现声明。

    这里用 enum 值保护测试/文档共享的最小词表，避免后续迁移时又在不同文件里
    发明一套名字，导致 transition boundary 无法稳定讨论。
    """
    from agent.runtime_events import RuntimeEventKind

    assert {kind.value for kind in RuntimeEventKind} == {
        "user_input",
        "model_output",
        "tool_result",
        "policy_denial",
        "user_rejection",
        "checkpoint_resume",
        "health_command",
        "logs_command",
    }


def test_transition_result_is_frozen_and_checkpoint_neutral() -> None:
    """TransitionResult 只是未来 transition 层草案，不能变成可变持久状态容器。

    frozen + 基础字段让它适合作为 handler 返回值草案；如果未来有人把
    DisplayEvent / RuntimeEvent / InputIntent / CommandResult 塞进来，这条边界
    应先失败，而不是等 checkpoint 被污染后再排查。
    """
    from agent.runtime_events import TransitionOutcome, TransitionResult

    outcome = TransitionResult(
        next_status="awaiting_user_input",
        should_checkpoint=True,
        clear_pending_user_input=True,
        advance_step=False,
        display_events=("user_input.requested",),
        reason="request_user_input",
        notes=("v0.4 naming draft",),
    )

    with pytest.raises(FrozenInstanceError):
        outcome.next_status = "running"  # type: ignore[misc]

    assert outcome.display_events == ("user_input.requested",)
    for field in fields(outcome):
        value = getattr(outcome, field.name)
        assert not value.__class__.__name__.endswith("Event")
        assert value.__class__.__name__ not in {"InputIntent", "CommandResult"}
    assert TransitionOutcome is TransitionResult


def test_command_event_transition_is_noop_for_health_and_logs() -> None:
    """HealthCommand / LogsCommand 是本轮落地的最小 command event slice。

    它们可以产生用户可见输出，但必须返回 no-op TransitionResult：不切 status、
    不清 pending、不推进 step、不触发 checkpoint。这个测试守护的是状态边界，
    不是靠 health/logs 输出文字做关键词判断。
    """
    from agent.runtime_events import RuntimeEventKind, command_event_transition

    for kind in (RuntimeEventKind.HEALTH_COMMAND, RuntimeEventKind.LOGS_COMMAND):
        outcome = command_event_transition(kind)
        assert outcome.next_status is None
        assert outcome.should_checkpoint is False
        assert outcome.clear_pending_tool is False
        assert outcome.clear_pending_user_input is False
        assert outcome.advance_step is False
        assert outcome.reason == kind.value
        assert outcome.display_events


def test_command_event_transition_rejects_business_events() -> None:
    """no-op command slice 只能接维护命令，不能吞掉业务事件。

    如果 ToolResult / UserInput 也被映射成 no-op，后续迁移会把真实状态变化
    悄悄丢掉，所以这里先把入口收窄。
    """
    from agent.runtime_events import RuntimeEventKind, command_event_transition

    with pytest.raises(ValueError):
        command_event_transition(RuntimeEventKind.TOOL_RESULT)


def test_tool_result_transition_kinds_keep_tool_outcomes_distinct() -> None:
    """ToolResult -> TransitionResult 的词汇必须先区分四类工具结局。

    这是 v0.4 ToolResult 切片的入口测试：我们不靠「文案里有没有拒绝/失败」
    这种自然语言关键词来判断状态，而是让 policy denial、user rejection、
    tool failure、tool success 各自有稳定 transition kind 和 display event。
    """
    from agent.runtime_events import ToolResultTransitionKind, tool_result_transition

    outcomes = {kind: tool_result_transition(kind) for kind in ToolResultTransitionKind}

    assert outcomes[ToolResultTransitionKind.TOOL_SUCCESS].display_events == (
        "tool.completed",
    )
    assert outcomes[ToolResultTransitionKind.TOOL_FAILURE].display_events == (
        "tool.failed",
    )
    assert outcomes[ToolResultTransitionKind.POLICY_DENIAL].display_events == (
        "tool.rejected",
    )
    assert outcomes[ToolResultTransitionKind.USER_REJECTION].display_events == (
        "tool.user_rejected",
    )
    assert len({outcome.reason for outcome in outcomes.values()}) == 4

    for outcome in outcomes.values():
        assert outcome.should_checkpoint is True
        assert outcome.advance_step is False
        assert outcome.clear_pending_user_input is False
    assert outcomes[ToolResultTransitionKind.POLICY_DENIAL].clear_pending_tool is True
    assert outcomes[ToolResultTransitionKind.USER_REJECTION].clear_pending_tool is True
    assert outcomes[ToolResultTransitionKind.TOOL_FAILURE].clear_pending_tool is False
    assert outcomes[ToolResultTransitionKind.TOOL_SUCCESS].clear_pending_tool is False

    pending_failure = tool_result_transition(
        ToolResultTransitionKind.TOOL_FAILURE,
        from_pending_tool=True,
    )
    assert pending_failure.clear_pending_tool is True


def test_tool_failure_transition_real_path_keeps_protocol_and_masks_secrets(
    tmp_path,
    monkeypatch,
) -> None:
    """tool failure 是本轮 ToolFailure -> TransitionResult 最小切片。

    这里走真实 `execute_single_tool()` 路径：失败应写现有 tool_result 协议事实、
    emit `tool.failed`、checkpoint durable state，但不能推进 step、不能把
    TransitionResult 写进 messages/checkpoint，也不能把 token/api key 原样放进
    失败提示。
    """
    from agent import checkpoint
    import agent.tool_executor as te
    from agent.conversation_events import has_tool_result
    from agent.state import create_agent_state

    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", checkpoint_path)
    monkeypatch.setattr(te, "needs_tool_confirmation", lambda name, inp: False)
    monkeypatch.setattr(
        te,
        "execute_tool",
        lambda name, inp, context=None: "错误：远端返回 token=raw-secret-value",
    )

    state = create_agent_state(system_prompt="test")
    state.task.current_step_index = 3
    state.task.pending_tool = {
        "tool_use_id": "other_pending",
        "tool": "write_file",
        "input": {"path": "workspace/other.txt"},
    }
    state.conversation.messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_failure",
                    "name": "read_file",
                    "input": {"path": "missing.txt"},
                }
            ],
        }
    ]
    captured: list[object] = []
    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_runtime_event=None,
        on_display_event=captured.append,
    )
    block = SimpleNamespace(
        id="toolu_failure",
        name="read_file",
        input={"path": "missing.txt", "api_key": "sk-ant-direct-secret"},
    )

    assert te.execute_single_tool(
        block,
        state=state,
        turn_state=turn_state,
        turn_context={},
        messages=state.conversation.messages,
    ) is None

    entry = state.task.tool_execution_log["toolu_failure"]
    assert entry["status"] == "failed"
    assert state.task.current_step_index == 3
    assert state.task.pending_tool["tool_use_id"] == "other_pending"
    assert has_tool_result(state.conversation.messages, "toolu_failure")
    assert any(getattr(ev, "event_type", "") == "tool.failed" for ev in captured)
    assert not any(getattr(ev, "event_type", "") == "tool.rejected" for ev in captured)
    assert not any(
        getattr(ev, "event_type", "") == "tool.user_rejected" for ev in captured
    )

    serialized_messages = json.dumps(state.conversation.messages, ensure_ascii=False)
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    serialized_checkpoint = json.dumps(payload, ensure_ascii=False)
    for marker in ("TransitionResult", "RuntimeEventKind", "ToolResultTransitionKind"):
        assert marker not in serialized_messages
        assert marker not in serialized_checkpoint
    for secret in ("raw-secret-value", "sk-ant-direct-secret"):
        assert secret not in serialized_messages
        assert secret not in serialized_checkpoint


def test_pending_tool_failure_transition_clears_pending_after_confirmed_execution(
    tmp_path,
    monkeypatch,
) -> None:
    """确认后的 tool failure 仍按既有 confirmation 边界清 pending_tool。

    这条测试守护 v0.4 的迁移边界：failure transition 能表达
    `from_pending_tool=True` 的清理意图，但 `tool_result` message 和 checkpoint
    仍由现有 handler 落地，不能为了抽象提前重写整条 tool success/failure 流程。
    """
    from agent import checkpoint
    import agent.confirm_handlers as ch
    from agent.confirm_handlers import ConfirmationContext
    import agent.tool_executor as te
    from agent.conversation_events import has_tool_result
    from agent.state import create_agent_state

    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", checkpoint_path)
    monkeypatch.setattr(
        te,
        "execute_tool",
        lambda name, inp, context=None: "错误：写入失败 password=raw-password",
    )

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_tool_confirmation"
    state.task.current_step_index = 2
    state.task.pending_tool = {
        "tool_use_id": "toolu_pending_failure",
        "tool": "write_file",
        "input": {"path": "workspace/fail.txt", "content": "sk-ant-pending-secret"},
    }
    state.conversation.messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_pending_failure",
                    "name": "write_file",
                    "input": {"path": "workspace/fail.txt"},
                }
            ],
        }
    ]
    captured: list[object] = []
    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_runtime_event=None,
        on_display_event=captured.append,
    )
    ctx = ConfirmationContext(
        state=state,
        turn_state=turn_state,
        client=None,
        model_name="test-model",
        continue_fn=lambda ts: "continued",
    )

    assert ch.handle_tool_confirmation("y", ctx) == "continued"

    assert state.task.pending_tool is None
    assert state.task.status == "running"
    assert state.task.current_step_index == 2
    assert state.task.tool_execution_log["toolu_pending_failure"]["status"] == "failed"
    assert has_tool_result(state.conversation.messages, "toolu_pending_failure")
    assert any(getattr(ev, "event_type", "") == "tool.failed" for ev in captured)
    assert not any(getattr(ev, "event_type", "") == "tool.completed" for ev in captured)

    serialized_messages = json.dumps(state.conversation.messages, ensure_ascii=False)
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    serialized_checkpoint = json.dumps(payload, ensure_ascii=False)
    for marker in ("TransitionResult", "RuntimeEventKind", "ToolResultTransitionKind"):
        assert marker not in serialized_messages
        assert marker not in serialized_checkpoint
    for secret in ("raw-password", "sk-ant-pending-secret"):
        assert secret not in serialized_messages
        assert secret not in serialized_checkpoint


def test_policy_denial_transition_is_applied_without_persisting_runtime_objects(
    tmp_path,
    monkeypatch,
) -> None:
    """policy denial 是本轮 ToolResult 最小切片之一。

    测试真实 `execute_single_tool()` 路径，而不是只测 helper：安全策略拒绝应
    clear pending 语义、写现有 tool_result 协议事实、emit `tool.rejected`，
    但 RuntimeEvent / TransitionResult / ToolResultTransitionKind 不能进入
    checkpoint 或 messages。
    """
    from agent import checkpoint
    import agent.tool_executor as te
    from agent.conversation_events import has_tool_result
    from agent.state import create_agent_state

    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", checkpoint_path)
    monkeypatch.setattr(te, "needs_tool_confirmation", lambda name, inp: "block")

    state = create_agent_state(system_prompt="test")
    state.conversation.messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_policy",
                    "name": "read_file",
                    "input": {"path": ".env"},
                }
            ],
        }
    ]
    captured: list[object] = []
    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_runtime_event=None,
        on_display_event=captured.append,
    )
    block = SimpleNamespace(id="toolu_policy", name="read_file", input={"path": ".env"})

    result = te.execute_single_tool(
        block,
        state=state,
        turn_state=turn_state,
        turn_context={},
        messages=state.conversation.messages,
    )

    assert result == te.FORCE_STOP
    assert state.task.pending_tool is None
    assert state.task.tool_execution_log["toolu_policy"]["status"] == "blocked_by_policy"
    assert has_tool_result(state.conversation.messages, "toolu_policy")
    assert any(getattr(ev, "event_type", "") == "tool.rejected" for ev in captured)

    serialized_messages = json.dumps(state.conversation.messages, ensure_ascii=False)
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    serialized_checkpoint = json.dumps(payload, ensure_ascii=False)
    for marker in ("TransitionResult", "RuntimeEventKind", "ToolResultTransitionKind"):
        assert marker not in serialized_messages
        assert marker not in serialized_checkpoint


def test_user_rejection_transition_clears_pending_and_keeps_protocol_messages(
    tmp_path,
    monkeypatch,
) -> None:
    """user rejection 是本轮 ToolResult 最小切片之一。

    用户拒绝和 policy denial 必须走不同 display event / control event，但都不能
    把 TransitionResult 写进 messages 或 checkpoint。这里测真实 confirmation
    handler，守住 pending_tool 只在明确拒绝路径清理的边界。
    """
    from agent import checkpoint
    import agent.confirm_handlers as ch
    from agent.confirm_handlers import ConfirmationContext
    from agent.conversation_events import has_tool_result
    from agent.state import create_agent_state

    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", checkpoint_path)

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_tool_confirmation"
    state.task.pending_tool = {
        "tool_use_id": "toolu_user_reject",
        "tool": "write_file",
        "input": {"path": "workspace/demo.txt", "content": "hello"},
    }
    state.conversation.messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_user_reject",
                    "name": "write_file",
                    "input": {"path": "workspace/demo.txt", "content": "hello"},
                }
            ],
        }
    ]
    captured: list[object] = []
    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_runtime_event=None,
        on_display_event=captured.append,
    )
    ctx = ConfirmationContext(
        state=state,
        turn_state=turn_state,
        client=None,
        model_name="test-model",
        continue_fn=lambda ts: "continued",
    )

    assert ch.handle_tool_confirmation("n", ctx) == "continued"

    assert state.task.pending_tool is None
    assert state.task.status == "running"
    assert has_tool_result(state.conversation.messages, "toolu_user_reject")
    assert any(getattr(ev, "event_type", "") == "tool.user_rejected" for ev in captured)
    assert not any(getattr(ev, "event_type", "") == "tool.rejected" for ev in captured)

    serialized_messages = json.dumps(state.conversation.messages, ensure_ascii=False)
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    serialized_checkpoint = json.dumps(payload, ensure_ascii=False)
    for marker in ("TransitionResult", "RuntimeEventKind", "ToolResultTransitionKind"):
        assert marker not in serialized_messages
        assert marker not in serialized_checkpoint
    assert "用户拒绝执行工具" in serialized_messages
    assert "policy_denial" not in serialized_messages


def test_runtime_transition_result_not_written_to_checkpoint_or_messages(
    tmp_path,
    monkeypatch,
) -> None:
    """RuntimeEvent / TransitionResult 是临时决策对象，不应进入 checkpoint/messages。

    这里不把对象塞进 state 再要求 checkpoint 兜底，因为那会纵容调用方污染
    TaskState。正确边界是：正常 save_checkpoint 的 durable schema 中根本没有
    runtime event/result 字段，conversation.messages 也只保存真实对话事实。
    """
    from agent import checkpoint
    from agent.runtime_events import RuntimeEventKind, command_event_transition
    from agent.state import create_agent_state

    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", checkpoint_path)

    state = create_agent_state(system_prompt="test")
    state.conversation.messages = [{"role": "user", "content": "hello"}]
    outcome = command_event_transition(RuntimeEventKind.HEALTH_COMMAND)
    checkpoint.save_checkpoint(state, source="tests.v0_4.command_noop")

    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False)
    assert set(payload.keys()) == {"meta", "task", "memory", "conversation"}
    assert "RuntimeEventKind" not in serialized
    assert "TransitionResult" not in serialized
    assert "health_command" not in serialized
    assert outcome.reason not in serialized
    assert payload["conversation"]["messages"] == [{"role": "user", "content": "hello"}]


def test_runtime_events_module_has_no_persistence_or_ui_dependencies() -> None:
    """命名草案不能反向依赖 checkpoint / DisplayEvent / CommandResult。

    这是 v0.4 前置测试：先允许建立词汇，再逐步迁移一个最小 transition slice。
    如果一开始就 import 持久化或 UI 层，后续会很难判断状态变化到底归谁负责。
    """
    source = (REPO_ROOT / "agent" / "runtime_events.py").read_text(encoding="utf-8")

    forbidden_import_markers = [
        "from agent.checkpoint",
        "import agent.checkpoint",
        "from agent.display_events",
        "import agent.display_events",
        "from agent.input_intents",
        "import agent.input_intents",
        "conversation.messages.append",
    ]
    leaked = [marker for marker in forbidden_import_markers if marker in source]
    assert not leaked, f"runtime_events.py 不能拥有持久化/UI/协议对象依赖：{leaked}"


def test_health_and_logs_commands_do_not_mutate_task_execution_state(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """health/logs 是维护命令，不是 TaskState transition。

    v0.4 迁移前先锁住这条边界：HealthCommand / LogsCommand 可以输出诊断信息，
    但不能推进 current_step、清 pending_tool、写 pending_user_input_request 或改变
    runtime status。这里不用自然语言关键词判断状态，只比对 TaskState 快照。
    """
    import main as main_module
    from agent import core
    from agent import checkpoint
    from agent.state import create_agent_state
    import agent.health_check as health_check
    import agent.log_viewer as log_viewer

    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", checkpoint_path)
    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_tool_confirmation"
    state.task.current_step_index = 2
    state.task.current_plan = {"steps": [{"title": "a"}, {"title": "b"}]}
    state.task.pending_tool = {
        "tool_use_id": "T1",
        "tool": "write_file",
        "input": {"path": "workspace/demo.txt"},
    }
    state.task.pending_user_input_request = None
    monkeypatch.setattr(core, "state", state)
    monkeypatch.setattr(
        health_check,
        "collect_health_results",
        lambda: {"workspace_lint": {"status": "pass", "message": "ok"}},
    )
    monkeypatch.setattr(log_viewer, "render_logs", lambda **kwargs: "Runtime logs\nok")

    before = copy.deepcopy(state.task.__dict__)

    assert main_module.main(["health"]) == 0
    assert main_module.main(["health", "--json"]) == 0
    assert main_module.main(["logs", "--tail", "1"]) == 0

    assert state.task.__dict__ == before
    assert not checkpoint_path.exists(), "health/logs command 不应触发 task checkpoint"
    out = capsys.readouterr().out
    assert "Runtime logs" in out


def test_status_line_masks_structured_internal_objects() -> None:
    """status line 只能展示摘要字段，不能 raw dump dict/dataclass 内部对象。

    这是 v0.4 transition boundary 的 UI 侧防线：即便调用方误把结构化对象塞进
    summary，renderer 也只做安全投影，不能让 pending_tool input 或 dataclass repr
    暴露到用户输出，更不能靠问号/关键词猜状态。
    """
    from agent.cli_renderer import render_status_line

    @dataclass(frozen=True)
    class _InternalStep:
        api_key: str

    out = render_status_line(
        {
            "status": "running",
            "current_step_index": 1,
            "plan_total_steps": 2,
            "current_step_title": {"title": "raw", "api_key": "sk-ant-secret"},
            "pending_tool_name": _InternalStep(api_key="sk-ant-secret"),
            "message_count": 3,
        }
    )

    assert "state=executing tool/model" in out
    assert "status=running" in out
    assert "structured value" in out
    assert "sk-ant-secret" not in out
    assert "api_key" not in out
    assert "_InternalStep" not in out
    assert "{" not in out and "}" not in out


def test_v0_4_prep_doc_records_started_boundary_work_without_claiming_runtime_rewrite() -> None:
    """v0.4 prep 文档要记录工程入口，但不能把准备工作说成已完成重构。

    这条测试守护 Roadmap 边界：当前只开始 transition boundary tests 与命名草案，
    不允许文档漂移成“已经 full event-driven / LangGraph / full Textual”。
    """
    text = (REPO_ROOT / "docs" / "V0_4_EVENT_TRANSITION_PREP.md").read_text(
        encoding="utf-8"
    )
    lower = text.lower()

    required = [
        "agent/runtime_events.py",
        "transition boundary tests",
        "HealthCommand",
        "LogsCommand",
        "command event slice",
        "model output",
        "tool result",
        "user confirmation/rejection",
        "core.py",
        "RuntimeEvent",
        "DisplayEvent",
        "checkpoint/schema",
    ]
    missing = [term for term in required if term.lower() not in lower]
    assert not missing, f"v0.4 prep 文档缺少第一阶段工程入口：{missing}"

    for forbidden in ["LangGraph", "sub-agent", "Reflect", "full Textual"]:
        hits = [idx for idx in range(len(text)) if text.lower().startswith(forbidden.lower(), idx)]
        assert hits, f"v0.4 prep 文档必须保留 {forbidden} 非目标边界"
        assert any(
            marker in text[max(0, idx - 80): idx + len(forbidden) + 80]
            for idx in hits
            for marker in ["Do not", "not implemented", "不是", "不做", "不引入"]
        ), f"{forbidden} 出现时必须带非目标边界"


# v0.4 Phase 1 slice 4 · ToolSuccess transition 边界
# 中文学习边界：
# - 这一组测试覆盖 ToolFailure slice 已经形成的 TransitionResult 边界**镜像
#   到 ToolSuccess 成功路径**。它们验证：success outcome 的 display event
#   现在通过 transition.display_events 输出（而不是裸 display_event_type
#   fallback），但 tool_result 消息写入 / checkpoint schema / 工具实际执行
#   / 用户确认逻辑 / ModelOutput 分类 / core loop 仍然完全不变。
# - 任何把 TransitionResult / RuntimeEventKind / ToolResultTransitionKind
#   写进 messages 或 checkpoint 的回归都应在这里立即失败。
# - 失败注入 / 拒绝注入仍由既有 slice 的测试覆盖；这里专注 success 的
#   "现在也走 transition" 这一条窄边界，避免把 slice 4 扩成大重构。


def test_tool_outcome_transition_distinguishes_success_failure_rejected_by_check() -> None:
    """slice 4 入口契约：success / failure / rejected_by_check 必须各有去向。

    ``rejected_by_check``（工具内部安全检查拒绝）刻意**不**进 transition——
    它在 fallback 上走 raw display_event_type='tool.rejected'，与 policy
    denial / user rejection 的语义切片保持区分；如果未来有人"顺手"把它
    并进 success，本测试应立刻失败。
    """

    from agent.runtime_events import ToolResultTransitionKind
    from agent.tool_executor import _tool_outcome_transition

    success = _tool_outcome_transition("executed", from_pending_tool=False)
    failure = _tool_outcome_transition("failed", from_pending_tool=False)
    rejected_by_check = _tool_outcome_transition(
        "rejected_by_check", from_pending_tool=False
    )

    assert success is not None
    assert success.reason == ToolResultTransitionKind.TOOL_SUCCESS.value
    assert success.display_events == ("tool.completed",)
    assert success.should_checkpoint is True
    assert success.clear_pending_tool is False
    assert success.advance_step is False

    assert failure is not None
    assert failure.reason == ToolResultTransitionKind.TOOL_FAILURE.value

    # rejected_by_check **必须** 落到 None，让调用方走 raw display_event_type
    # fallback（"tool.rejected"），保留与 policy denial / user rejection 的
    # 语义切片区分；不能被未来 slice 顺手并入 success。
    assert rejected_by_check is None


def test_tool_success_transition_real_path_keeps_protocol_unchanged(
    tmp_path,
    monkeypatch,
) -> None:
    """slice 4 真实路径：execute_single_tool 成功路径现在走 transition。

    模拟边界：
    - 用 monkeypatch 让 execute_tool 直接返回成功字符串，避免真的访问文件
      系统；needs_tool_confirmation 也强制 False，绕过用户确认 UI。
    - 关注的不变量：tool_result 消息照常写入、checkpoint 照常持久化、
      pending_tool 不被本函数改动、display event 是 tool.completed（且
      事实上来自 transition.display_events 而不再是 raw fallback）。
    - 持久化里**不应**出现任何 TransitionResult / RuntimeEventKind /
      ToolResultTransitionKind 字面量——transition 是 Runtime 临时决策
      草案，不允许污染 messages 或 checkpoint。
    """

    from agent import checkpoint
    import agent.tool_executor as te
    from agent.conversation_events import has_tool_result
    from agent.state import create_agent_state

    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", checkpoint_path)
    monkeypatch.setattr(te, "needs_tool_confirmation", lambda name, inp: False)
    monkeypatch.setattr(
        te,
        "execute_tool",
        lambda name, inp, context=None: "成功读取 5 行内容",
    )

    state = create_agent_state(system_prompt="test")
    state.task.current_step_index = 1
    # pending_tool 与本次成功调用无关；用来证明 success 路径 **不** 误清
    # 不属于自己的 pending（这是 slice 4 与 slice 3 ToolFailure 的对称约束）。
    state.task.pending_tool = {
        "tool_use_id": "unrelated_pending",
        "tool": "write_file",
        "input": {"path": "workspace/other.txt"},
    }
    state.conversation.messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_success",
                    "name": "read_file",
                    "input": {"path": "README.md"},
                }
            ],
        }
    ]
    captured: list[object] = []
    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_runtime_event=None,
        on_display_event=captured.append,
    )
    block = SimpleNamespace(
        id="toolu_success",
        name="read_file",
        input={"path": "README.md"},
    )

    assert te.execute_single_tool(
        block,
        state=state,
        turn_state=turn_state,
        turn_context={},
        messages=state.conversation.messages,
    ) is None

    entry = state.task.tool_execution_log["toolu_success"]
    assert entry["status"] == "executed"
    assert entry["result"] == "成功读取 5 行内容"
    # success 路径不脱敏 input；保持 v0.3 既有 durable 行为（slice 4 不扩边界）。
    assert entry["input"] == {"path": "README.md"}
    assert state.task.current_step_index == 1
    assert state.task.pending_tool == {
        "tool_use_id": "unrelated_pending",
        "tool": "write_file",
        "input": {"path": "workspace/other.txt"},
    }
    assert has_tool_result(state.conversation.messages, "toolu_success")
    # display event 必须是 tool.completed，而且**只**有一条 tool 状态事件
    # （不应同时 emit failed / rejected / user_rejected）。
    completed_events = [
        ev for ev in captured if getattr(ev, "event_type", "") == "tool.completed"
    ]
    assert len(completed_events) == 1
    for forbidden in ("tool.failed", "tool.rejected", "tool.user_rejected"):
        assert not any(
            getattr(ev, "event_type", "") == forbidden for ev in captured
        ), f"success 路径不应 emit {forbidden}"

    # checkpoint 持久化对照：transition 草案对象绝不能进 durable state。
    serialized_messages = json.dumps(state.conversation.messages, ensure_ascii=False)
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    serialized_checkpoint = json.dumps(payload, ensure_ascii=False)
    for marker in ("TransitionResult", "RuntimeEventKind", "ToolResultTransitionKind"):
        assert marker not in serialized_messages
        assert marker not in serialized_checkpoint


def test_pending_tool_success_transition_real_path_after_confirmed_execution(
    tmp_path,
    monkeypatch,
) -> None:
    """用户确认后成功执行：execute_pending_tool 也走 ToolSuccess transition。

    模拟边界：
    - 用户输入 'y' 接受 confirmation；execute_tool 被 monkeypatch 成功；
      handler 在外层负责清 pending_tool（slice 4 **不**把这个清理动作搬进
      execute_pending_tool，避免和 slice 6 用户确认迁移交叉）。
    - 不应 emit tool.failed / tool.rejected / tool.user_rejected；
    - tool_result 协议事实由 execute_pending_tool 内的 append_tool_result
      照原样写入；TransitionResult 不能进 messages / checkpoint。
    """

    from agent import checkpoint
    import agent.confirm_handlers as ch
    from agent.confirm_handlers import ConfirmationContext
    import agent.tool_executor as te
    from agent.conversation_events import has_tool_result
    from agent.state import create_agent_state

    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", checkpoint_path)
    monkeypatch.setattr(
        te,
        "execute_tool",
        lambda name, inp, context=None: "成功写入 42 字节",
    )

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_tool_confirmation"
    state.task.current_step_index = 2
    state.task.pending_tool = {
        "tool_use_id": "toolu_pending_success",
        "tool": "write_file",
        "input": {"path": "workspace/ok.txt", "content": "hello"},
    }
    state.conversation.messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_pending_success",
                    "name": "write_file",
                    "input": {"path": "workspace/ok.txt"},
                }
            ],
        }
    ]
    captured: list[object] = []
    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_runtime_event=None,
        on_display_event=captured.append,
    )
    ctx = ConfirmationContext(
        state=state,
        turn_state=turn_state,
        client=None,
        model_name="test-model",
        continue_fn=lambda ts: "continued",
    )

    assert ch.handle_tool_confirmation("y", ctx) == "continued"

    # 既有契约（不属于本 slice）：handler 在外层清 pending、置 status=running。
    assert state.task.pending_tool is None
    assert state.task.status == "running"
    assert state.task.current_step_index == 2
    assert (
        state.task.tool_execution_log["toolu_pending_success"]["status"] == "executed"
    )
    assert has_tool_result(state.conversation.messages, "toolu_pending_success")

    # slice 4 真正钉住的边界：display event 现在来自 transition.display_events，
    # 不再是裸 fallback；同时不能掉进 failed / rejected 的语义桶。
    completed_events = [
        ev for ev in captured if getattr(ev, "event_type", "") == "tool.completed"
    ]
    assert len(completed_events) >= 1
    for forbidden in ("tool.failed", "tool.rejected", "tool.user_rejected"):
        assert not any(
            getattr(ev, "event_type", "") == forbidden for ev in captured
        ), f"pending success 路径不应 emit {forbidden}"

    serialized_messages = json.dumps(state.conversation.messages, ensure_ascii=False)
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    serialized_checkpoint = json.dumps(payload, ensure_ascii=False)
    for marker in ("TransitionResult", "RuntimeEventKind", "ToolResultTransitionKind"):
        assert marker not in serialized_messages
        assert marker not in serialized_checkpoint


def test_rejected_by_check_real_path_still_uses_fallback_display_event(
    tmp_path,
    monkeypatch,
) -> None:
    """rejected_by_check 不能被 slice 4 误归为 success。

    模拟边界：让 execute_tool 返回工具内部安全检查拒绝的固定前缀
    "拒绝执行：..."（参见 _classify_tool_outcome 里 TOOL_INTERNAL_REJECT_PREFIX
    的语义）。它**不**进 TransitionResult，display event 仍走 raw
    "tool.rejected" fallback；如果未来有人把 rejected_by_check 并进 success
    transition，本测试会立刻失败——避免 slice 4 把一个本应单独治理的
    安全语义偷偷合并掉。
    """

    from agent import checkpoint
    import agent.tool_executor as te
    from agent.state import create_agent_state

    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", checkpoint_path)
    monkeypatch.setattr(te, "needs_tool_confirmation", lambda name, inp: False)
    monkeypatch.setattr(
        te,
        "execute_tool",
        lambda name, inp, context=None: "拒绝执行：路径不在白名单",
    )

    state = create_agent_state(system_prompt="test")
    state.conversation.messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_internal_reject",
                    "name": "read_file",
                    "input": {"path": "/etc/passwd"},
                }
            ],
        }
    ]
    captured: list[object] = []
    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_runtime_event=None,
        on_display_event=captured.append,
    )
    block = SimpleNamespace(
        id="toolu_internal_reject",
        name="read_file",
        input={"path": "/etc/passwd"},
    )

    te.execute_single_tool(
        block,
        state=state,
        turn_state=turn_state,
        turn_context={},
        messages=state.conversation.messages,
    )

    entry = state.task.tool_execution_log["toolu_internal_reject"]
    assert entry["status"] == "rejected_by_check"
    # display event 必须是 fallback 'tool.rejected'，**不**是 'tool.completed'。
    assert any(
        getattr(ev, "event_type", "") == "tool.rejected" for ev in captured
    )
    assert not any(
        getattr(ev, "event_type", "") == "tool.completed" for ev in captured
    )


# v0.4 Phase 1 slice 5 · ModelOutput 分类集中
# 中文学习边界：
# - 这一组测试覆盖 stop_reason 分类的边界。它们验证：classify_model_output
#   是纯函数、4 类标签必须存在、UNKNOWN 不能被静默并入其他类别、core.py
#   dispatch 仍正确路由到对应 handler。
# - slice 5 **只**做"是哪一种模型输出"的分类边界，**不**接管 handler 内部
#   的 state mutation / messages 写入 / checkpoint / consecutive_* 计数器，
#   也**不**做 core.py 主循环瘦身（那归 Phase 2）。
# - 任何把分类标签写进 messages / checkpoint 或让 UNKNOWN 静默 fallback
#   到 end_turn 的回归都应在这里立即失败。


def test_model_output_kind_enum_covers_known_dispatch_branches() -> None:
    """ModelOutputKind 必须显式覆盖 core.py 当前 dispatcher 的 4 类结果。

    模拟边界：如果未来有人新增分支但忘记加 enum，本测试会立刻失败；
    反过来如果有人删枚举想让 dispatch 缩减成 3 类，也会在这里被钉住。
    """

    from agent.runtime_events import ModelOutputKind

    assert {kind.value for kind in ModelOutputKind} == {
        "end_turn",
        "tool_use",
        "max_tokens",
        "unknown",
    }


def test_classify_model_output_is_pure_and_total() -> None:
    """classify_model_output 必须是纯函数并对未知输入显式返回 UNKNOWN。

    模拟边界：
    - 已知的 3 个 stop_reason 各自映射到独立 kind；
    - ``None`` / 空串 / 大小写变体 / SDK 未来新增字段一律 UNKNOWN，
      **不能**被静默归入 end_turn / tool_use / max_tokens——这是
      slice 5 的核心防回归点。
    """

    from agent.runtime_events import ModelOutputKind, classify_model_output

    assert classify_model_output("end_turn") is ModelOutputKind.END_TURN
    assert classify_model_output("tool_use") is ModelOutputKind.TOOL_USE
    assert classify_model_output("max_tokens") is ModelOutputKind.MAX_TOKENS

    for unknown in (None, "", "End_Turn", "stop_sequence", "refusal", "future_value"):
        assert classify_model_output(unknown) is ModelOutputKind.UNKNOWN, (
            f"未知 stop_reason {unknown!r} 不能被静默并入已知类别"
        )


def test_classify_model_output_does_not_touch_state_or_messages() -> None:
    """分类是纯计算：不能读写 state、messages、checkpoint、RuntimeEvent。

    模拟边界：通过给定一个明显不该被改动的 sentinel state，确认分类前后
    deepcopy 等价；如果未来有人在 classifier 里偷偷改 task / conversation，
    本测试立刻失败。
    """

    from agent.runtime_events import classify_model_output
    from agent.state import create_agent_state

    state = create_agent_state(system_prompt="test")
    snapshot_before = copy.deepcopy(
        {
            "status": state.task.status,
            "current_step_index": state.task.current_step_index,
            "messages_len": len(state.conversation.messages),
        }
    )

    for stop_reason in (None, "end_turn", "tool_use", "max_tokens", "weird"):
        classify_model_output(stop_reason)

    snapshot_after = {
        "status": state.task.status,
        "current_step_index": state.task.current_step_index,
        "messages_len": len(state.conversation.messages),
    }
    assert snapshot_before == snapshot_after


def test_core_dispatch_uses_classifier_and_routes_handlers_correctly() -> None:
    """core.py 必须通过 classify_model_output 分派，而不是再用 inline 字符串比较。

    模拟边界：
    - 这是 source-level 契约测试。``_run_main_loop`` 是定义在 ``chat()``
      内部的闭包，state 通过闭包捕获，从外部直接调用不可行——所以这里
      不再尝试单独调度循环（真实 dispatch 行为已被 723 全量测试覆盖），
      转为在源码层面钉死"分类层确实被使用"。
    - 任何把 ``classify_model_output`` 调用回退成 ``response.stop_reason
      == "..."`` inline 比较的回归都会立刻失败。
    - UNKNOWN 分支的显式注释/标识也必须保留，避免未来有人把 fallback
      路径删掉让未知 stop_reason 静默被吸收到已知类别。
    """

    import agent.core as core
    from agent.runtime_events import ModelOutputKind, classify_model_output

    # 1. core 必须实际 import 分类符号（而不是只放在文档里）。
    assert core.classify_model_output is classify_model_output
    assert core.ModelOutputKind is ModelOutputKind

    source = Path(core.__file__).read_text(encoding="utf-8")

    # 2. 分类调用必须出现在源码中。
    assert "classify_model_output(response.stop_reason)" in source

    # 3. 4 类标签必须各自在 dispatch 中显式比较一次。
    for kind_name in ("MAX_TOKENS", "END_TURN", "TOOL_USE"):
        assert f"ModelOutputKind.{kind_name}" in source, (
            f"core dispatch 必须按 ModelOutputKind.{kind_name} 路由"
        )

    # 4. UNKNOWN 必须有显式 fallback（保留 "[系统] 未知的 stop_reason" 文案）。
    assert "未知的 stop_reason" in source
    assert "意外的响应" in source

    # 5. 旧的 inline 比较模式不能再出现在 _run_main_loop 范围内——
    #    以函数边界粗略截取做静态检查，避免误伤其它注释。
    loop_marker = "def _run_main_loop"
    loop_start = source.index(loop_marker)
    # 取后续 200 行内的内容做断言；core.py 该函数当前 ~120 行。
    loop_segment = source[loop_start: loop_start + 8000]
    for forbidden in (
        'response.stop_reason == "max_tokens"',
        'response.stop_reason == "end_turn"',
        'response.stop_reason == "tool_use"',
    ):
        assert forbidden not in loop_segment, (
            f"_run_main_loop 已迁移到 ModelOutputKind 分派，不应再出现 {forbidden}"
        )


def test_core_dispatch_unknown_stop_reason_handled_via_explicit_fallback() -> None:
    """未知 stop_reason 必须走显式 UNKNOWN fallback，不能被静默吸收。

    模拟边界：
    - 同样是 source-level 契约：UNKNOWN 分支必须留有可识别的标记（注释
      或显式枚举引用），让未来"顺手简化"四类分支为三类的回归立刻失败。
    - 行为级别的"未知 stop_reason 不会进入 end_turn / tool_use /
      max_tokens handler"由 classify_model_output 纯函数测试 +
      上一条 source-level 测试共同保证。
    """

    import agent.core as core

    source = Path(core.__file__).read_text(encoding="utf-8")
    # 必须保留对 UNKNOWN 的语义承诺：要么显式枚举引用，要么注释里写明。
    assert (
        "ModelOutputKind.UNKNOWN" in source
        or "UNKNOWN：未知 stop_reason" in source
    ), "core.py 必须显式承认 UNKNOWN 分支存在，不能让未知 stop_reason 静默"


def test_classify_model_output_does_not_leak_into_durable_state(
    tmp_path,
    monkeypatch,
) -> None:
    """分类标签不能被写进 messages 或 checkpoint。

    模拟边界：跑一个 tool_use 真实路径，再 dump checkpoint+messages 找
    "ModelOutputKind" / "classify_model_output" 字面量，确保分类层只是
    Runtime 内部决策，不会泄漏到 durable state。
    """

    from agent import checkpoint
    import agent.tool_executor as te
    from agent.state import create_agent_state

    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", checkpoint_path)
    monkeypatch.setattr(te, "needs_tool_confirmation", lambda name, inp: False)
    monkeypatch.setattr(te, "execute_tool", lambda name, inp, context=None: "ok")

    state = create_agent_state(system_prompt="test")
    state.conversation.messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_classify",
                    "name": "read_file",
                    "input": {"path": "README.md"},
                }
            ],
        }
    ]
    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_runtime_event=None,
        on_display_event=lambda ev: None,
    )
    block = SimpleNamespace(
        id="toolu_classify",
        name="read_file",
        input={"path": "README.md"},
    )
    te.execute_single_tool(
        block,
        state=state,
        turn_state=turn_state,
        turn_context={},
        messages=state.conversation.messages,
    )

    serialized_messages = json.dumps(state.conversation.messages, ensure_ascii=False)
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    serialized_checkpoint = json.dumps(payload, ensure_ascii=False)
    for marker in ("ModelOutputKind", "classify_model_output"):
        assert marker not in serialized_messages
        assert marker not in serialized_checkpoint


# ---------------------------------------------------------------------------
# v0.4 Phase 1 slice 6（plan 子切片）· plan confirmation transition 边界测试
# ---------------------------------------------------------------------------
# 中文学习边界：本组测试钉死的「真实回归点」
# - PLAN_ACCEPTED 必须明确表达 next_status="running" + should_checkpoint=True，
#   防止后续有人把 plan accept 改成不 checkpoint（resume 时会丢任务）。
# - PLAN_REJECTED 必须明确表达 should_checkpoint=False（即将 reset_task /
#   clear_checkpoint），防止后续有人在拒绝路径上反向 save_checkpoint，
#   把已经清掉的 task 状态又落盘（resume 时会"复活幽灵任务"）。
# - 纯函数性：plan_confirmation_transition 不读 state、不写 messages、不动
#   checkpoint；这是 v0.4 transition 边界的硬约束。
# - 不覆盖 step / tool / user_input / feedback_intent confirmation——这些
#   slice 6 后续小步才做，本组测试不能错误覆盖它们的语义。
# - source-level 契约：handle_plan_confirmation 的 accept / reject 路径必须
#   真正调用 plan_confirmation_transition；这一条防止有人「绕过 transition
#   层」直接回到 inline `state.task.status = "running"` 的旧写法。

def test_plan_confirmation_kind_covers_only_plan_outcomes():
    """枚举只覆盖 plan 的两类终结意图，不应混入 step/tool/user_input。"""

    from agent.runtime_events import PlanConfirmationKind

    values = {member.value for member in PlanConfirmationKind}
    assert values == {"plan_accepted", "plan_rejected"}


def test_plan_confirmation_transition_accept_intent_marks_checkpoint_and_running():
    """接受 plan 必须表达 next_status=running + should_checkpoint=True。"""

    from agent.runtime_events import (
        PlanConfirmationKind,
        plan_confirmation_transition,
    )

    result = plan_confirmation_transition(PlanConfirmationKind.PLAN_ACCEPTED)
    assert result.next_status == "running"
    assert result.should_checkpoint is True
    assert result.clear_pending_tool is False
    assert result.clear_pending_user_input is False
    assert result.advance_step is False
    assert "plan.accepted" in result.display_events


def test_plan_confirmation_transition_reject_intent_does_not_checkpoint():
    """拒绝 plan 必须表达 should_checkpoint=False，避免幽灵 checkpoint。"""

    from agent.runtime_events import (
        PlanConfirmationKind,
        plan_confirmation_transition,
    )

    result = plan_confirmation_transition(PlanConfirmationKind.PLAN_REJECTED)
    # 关键：拒绝路径不能再 checkpoint，因为 handler 紧接着会 reset_task +
    # clear_checkpoint；如果 transition 反过来要求 checkpoint，会让已清空
    # 的 task 状态又被落盘，resume 时复活已取消的任务。
    assert result.should_checkpoint is False
    assert result.next_status is None
    assert "plan.rejected" in result.display_events


def test_plan_confirmation_transition_rejects_unknown_kinds():
    """未知 kind 必须显式失败，避免下游静默走 default 分支误判。"""

    import pytest

    from agent.runtime_events import plan_confirmation_transition

    class _Foreign:
        value = "step_accepted"  # 故意伪装成另一类 confirmation 的 kind

    with pytest.raises(ValueError):
        plan_confirmation_transition(_Foreign())


def test_plan_confirmation_transition_is_pure_function():
    """transition 工厂不读 state、不写 messages、不动 checkpoint；纯函数。

    fake/mock 边界说明：本测试不实例化真实 TaskState；纯靠 'before/after
    返回值相等' 来检测隐性副作用。如果未来 transition helper 偷偷开始读
    全局 module-level 状态或调 logger / checkpoint，就会破坏这一条断言。
    """

    from agent.runtime_events import (
        PlanConfirmationKind,
        plan_confirmation_transition,
    )

    a1 = plan_confirmation_transition(PlanConfirmationKind.PLAN_ACCEPTED)
    a2 = plan_confirmation_transition(PlanConfirmationKind.PLAN_ACCEPTED)
    r1 = plan_confirmation_transition(PlanConfirmationKind.PLAN_REJECTED)
    r2 = plan_confirmation_transition(PlanConfirmationKind.PLAN_REJECTED)
    assert a1 == a2
    assert r1 == r2
    assert a1 != r1


def test_handle_plan_confirmation_source_actually_routes_through_transition():
    """source-level 契约：handler 不允许绕过 transition 层回到 inline 写法。

    背景：confirm_handlers 是 chat() 间接调用的产物，handler 直接独立
    单元测试需要构造大量 ConfirmationContext / continue_fn / turn_state；
    现有 tests/test_complex_scenarios.py / tests/test_feedback_intent_flow.py
    已经从端到端层面覆盖了 plan 接受 / 拒绝的真实行为（status / messages
    / checkpoint 全部通过其他测试守住）。这里补一条 source-level 契约，
    专门钉「handler 真的调用了 plan_confirmation_transition」，防止后续
    有人重构时把 transition 调用删掉，让边界命名形同虚设。
    """

    import inspect

    from agent import confirm_handlers

    src = inspect.getsource(confirm_handlers.handle_plan_confirmation)
    assert "plan_confirmation_transition" in src, (
        "handle_plan_confirmation 必须通过 plan_confirmation_transition 表达"
        "Runtime 意图，禁止回到 inline status 赋值的旧写法。"
    )
    assert "PlanConfirmationKind.PLAN_ACCEPTED" in src
    assert "PlanConfirmationKind.PLAN_REJECTED" in src
    # 不允许 step / tool / user_input / feedback_intent 的 *Kind 出现在 plan handler 里。
    forbidden = (
        "StepConfirmationKind",
        "ToolConfirmationKind",
        "UserInputConfirmationKind",
        "FeedbackIntentKind",
    )
    for name in forbidden:
        assert name not in src, (
            f"plan handler 不应越界使用 {name}；slice 6 plan 子切片只覆盖 plan。"
        )


def test_plan_confirmation_transition_does_not_leak_into_messages_or_checkpoint(tmp_path, monkeypatch):
    """durable state 不应包含 PlanConfirmationKind / plan_confirmation_transition 字面量。

    通过端到端调用 handle_plan_confirmation 的接受 / 拒绝路径，序列化
    messages 与 checkpoint 后扫描 transition 层符号，确认它们只是 Runtime
    内部命名，没有泄漏成持久化字段。这条防止后续重构「不小心 dump 了
    TransitionResult」。
    """

    import json
    from types import SimpleNamespace

    from agent import checkpoint as checkpoint_mod
    from agent import confirm_handlers as ch
    from agent.state import create_agent_state

    ckpt_file = tmp_path / "state.json"
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_PATH", ckpt_file)

    # ----- accept 路径 -----
    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_plan_confirmation"
    state.task.current_plan = [{"step": 1, "description": "do x"}]

    def _continue(_ts):
        return "continued"

    ctx = ch.ConfirmationContext(
        state=state,
        turn_state=SimpleNamespace(),
        client=None, model_name="x", continue_fn=_continue,
    )
    ch.handle_plan_confirmation("y", ctx)
    assert state.task.status == "running"

    # 中文学习边界（accept 路径硬约束）：
    # plan_confirmation_transition(PLAN_ACCEPTED) 显式承诺
    # should_checkpoint=True；handler 必须真的把这次接受落盘，否则 resume
    # 时会丢失"用户已经批准 plan"这一关键事实，下次启动会要求用户重新确认
    # 同一份 plan，破坏 v0.4 transition 边界承诺。
    # 这条断言钉死「accept → 真实 checkpoint 文件存在」，未来如果有人把
    # save_checkpoint 调用从 handler 中误删，会立刻在这里失败。
    assert ckpt_file.exists(), (
        "plan accepted 路径必须真实写入 checkpoint 文件；"
        "如果 handler 删掉 save_checkpoint 调用，resume 会丢任务。"
    )

    serialized_messages = json.dumps(state.conversation.messages, ensure_ascii=False)
    if ckpt_file.exists():
        serialized_ckpt = ckpt_file.read_text(encoding="utf-8")
    else:
        serialized_ckpt = ""

    for marker in (
        "PlanConfirmationKind",
        "plan_confirmation_transition",
        "TransitionResult",
    ):
        assert marker not in serialized_messages, (
            f"transition 内部符号 {marker} 不应出现在 durable messages 里"
        )
        assert marker not in serialized_ckpt, (
            f"transition 内部符号 {marker} 不应出现在 checkpoint 里"
        )

    # ----- reject 路径 -----
    state2 = create_agent_state(system_prompt="test")
    state2.task.status = "awaiting_plan_confirmation"
    state2.task.current_plan = [{"step": 1, "description": "do y"}]
    ctx2 = ch.ConfirmationContext(
        state=state2,
        turn_state=SimpleNamespace(),
        client=None, model_name="x", continue_fn=_continue,
    )
    out = ch.handle_plan_confirmation("n", ctx2)
    assert "已取消" in out
    # reset_task 之后 task 应回到初始状态
    assert state2.task.status == "idle"
    # 中文学习边界（reject 路径硬约束）：
    # plan_confirmation_transition(PLAN_REJECTED) 显式承诺
    # should_checkpoint=False；handler 紧接着 reset_task + clear_checkpoint，
    # 因此 checkpoint 文件必须**不存在**。如果未来有人在 reject 路径上
    # 反向加 save_checkpoint，已被清空的 task 状态会被落盘 → resume 会
    # 复活幽灵任务。这条断言钉死「reject → checkpoint 必须不存在」。
    assert not ckpt_file.exists(), (
        "plan rejected 路径不应残留 checkpoint 文件；"
        "如果 handler 在拒绝路径上误调 save_checkpoint，resume 会复活幽灵任务。"
    )

    serialized_messages2 = json.dumps(state2.conversation.messages, ensure_ascii=False)
    for marker in (
        "PlanConfirmationKind",
        "plan_confirmation_transition",
        "TransitionResult",
    ):
        assert marker not in serialized_messages2


# ---------------------------------------------------------------------------
# v0.4 Phase 1 slice 6-b（step 子切片）· step confirmation transition 边界测试
# ---------------------------------------------------------------------------
# 中文学习边界：本组测试钉死的「真实回归点」
# - STEP_ACCEPTED_CONTINUE 必须 should_checkpoint=True；防止有人改成
#   False 导致中间步用户已批准但 resume 时丢失批准状态。
# - STEP_ACCEPTED_TASK_DONE 必须 should_checkpoint=False；防止有人误改
#   成 True 导致已完成 task 又被落盘 → resume 复活已结束的任务。
# - STEP_REJECTED 必须 should_checkpoint=False；防止反向 save 让已停止任务复活。
# - 这三类必须独立于 plan / tool / user_input / feedback_intent kind；
#   source-level 契约钉住 step handler 不越界使用其他 *Kind。
# - 端到端真实 handler 调用：accept (continue) / accept (done) / reject 三条路径，
#   断言真实 checkpoint 文件存在性 + state 字段值 + transition 字面量不泄漏 durable。

def test_step_confirmation_kind_covers_only_step_outcomes():
    """枚举只覆盖 step 的三类终结意图，不应混入 plan/tool/user_input/feedback。"""

    from agent.runtime_events import StepConfirmationKind

    values = {member.value for member in StepConfirmationKind}
    assert values == {"step_accepted_continue", "step_accepted_task_done", "step_rejected"}


def test_step_confirmation_accept_continue_marks_checkpoint():
    """中间步 accept 必须 should_checkpoint=True；否则 resume 丢批准状态。"""

    from agent.runtime_events import (
        StepConfirmationKind,
        step_confirmation_transition,
    )

    result = step_confirmation_transition(StepConfirmationKind.STEP_ACCEPTED_CONTINUE)
    assert result.should_checkpoint is True
    assert result.advance_step is True
    assert "step.accepted" in result.display_events


def test_step_confirmation_accept_task_done_does_not_checkpoint():
    """最后一步 accept = 任务自然完成，必须 should_checkpoint=False。

    回归点：如果有人把这个改成 True，已 done 的 task 会被落盘，下次启动
    会"复活"已经完成的任务。
    """

    from agent.runtime_events import (
        StepConfirmationKind,
        step_confirmation_transition,
    )

    result = step_confirmation_transition(StepConfirmationKind.STEP_ACCEPTED_TASK_DONE)
    assert result.should_checkpoint is False
    assert "step.task_done" in result.display_events


def test_step_confirmation_reject_does_not_checkpoint():
    """reject 必须 should_checkpoint=False；防止反向 save 复活停止任务。"""

    from agent.runtime_events import (
        StepConfirmationKind,
        step_confirmation_transition,
    )

    result = step_confirmation_transition(StepConfirmationKind.STEP_REJECTED)
    assert result.should_checkpoint is False
    assert "step.rejected" in result.display_events


def test_step_confirmation_transition_rejects_unknown_kinds():
    """未知 kind 必须显式失败，禁止下游静默走 default。"""

    import pytest

    from agent.runtime_events import step_confirmation_transition

    class _Foreign:
        value = "plan_accepted"  # 故意伪装成 plan kind

    with pytest.raises(ValueError):
        step_confirmation_transition(_Foreign())


def test_step_confirmation_transition_is_pure_function():
    """transition 工厂为纯函数；同输入恒等输出。

    fake/mock 边界：本测试不构造 TaskState；纯靠返回值相等检测隐性副作用。
    如果未来 helper 偷偷依赖全局状态或 logger，这条会失败。
    """

    from agent.runtime_events import (
        StepConfirmationKind,
        step_confirmation_transition,
    )

    a = step_confirmation_transition(StepConfirmationKind.STEP_ACCEPTED_CONTINUE)
    b = step_confirmation_transition(StepConfirmationKind.STEP_ACCEPTED_CONTINUE)
    c = step_confirmation_transition(StepConfirmationKind.STEP_ACCEPTED_TASK_DONE)
    d = step_confirmation_transition(StepConfirmationKind.STEP_REJECTED)
    assert a == b
    assert a != c
    assert a != d
    assert c != d


def test_handle_step_confirmation_source_actually_routes_through_transition():
    """source-level 契约：step handler 必须真正调用 transition，禁止跨边界 *Kind。"""

    import inspect

    from agent import confirm_handlers

    src = inspect.getsource(confirm_handlers.handle_step_confirmation)
    assert "step_confirmation_transition" in src
    assert "STEP_ACCEPTED_CONTINUE" in src
    assert "STEP_ACCEPTED_TASK_DONE" in src
    assert "STEP_REJECTED" in src
    forbidden = (
        "PlanConfirmationKind",
        "ToolConfirmationKind",
        "UserInputConfirmationKind",
        "FeedbackIntentKind",
    )
    for name in forbidden:
        assert name not in src, (
            f"step handler 不应越界使用 {name}；slice 6-b step 子切片只覆盖 step。"
        )


def test_step_confirmation_transition_does_not_leak_durable(tmp_path, monkeypatch):
    """端到端：调用真实 handler 三条路径，断言 durable state 无 transition 字面量。

    fake/mock 边界说明：用 monkeypatch 把 CHECKPOINT_PATH 重定向到 tmp_path，
    让真实 save_checkpoint / clear_checkpoint 真实写入临时文件——**不**
    mock 这两个函数本身。advance_current_step_if_needed 走真实实现。
    """

    import json
    from types import SimpleNamespace

    from agent import checkpoint as checkpoint_mod
    from agent import confirm_handlers as ch
    from agent.state import create_agent_state

    ckpt_file = tmp_path / "state.json"
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_PATH", ckpt_file)

    def _continue(_ts):
        return "continued"

    def _new_state_with_two_steps():
        s = create_agent_state(system_prompt="test")
        s.task.status = "awaiting_step_confirmation"
        s.task.user_goal = "demo"
        s.task.current_plan = {
            "goal": "demo",
            "steps": [
                {
                    "step_id": "step-1",
                    "title": "first",
                    "description": "first",
                    "step_type": "report",
                },
                {
                    "step_id": "step-2",
                    "title": "second",
                    "description": "second",
                    "step_type": "report",
                },
            ],
        }
        s.task.current_step_index = 0
        return s

    def _scan_no_leak(serialized: str) -> None:
        for marker in (
            "StepConfirmationKind",
            "step_confirmation_transition",
            "TransitionResult",
        ):
            assert marker not in serialized, (
                f"transition 内部符号 {marker} 不应出现在 durable state 里"
            )

    # ----- accept_continue：还有下一步 -----
    state_a = _new_state_with_two_steps()
    ctx_a = ch.ConfirmationContext(
        state=state_a,
        turn_state=SimpleNamespace(),
        client=None,
        model_name="x",
        continue_fn=_continue,
    )
    out_a = ch.handle_step_confirmation("y", ctx_a)
    # advance_current_step_if_needed 应该把 index 推进到 1，status 仍 running
    assert state_a.task.current_step_index == 1
    assert state_a.task.status == "running"
    assert out_a == "continued"
    # 中间步 accept 必须真实落盘
    assert ckpt_file.exists(), (
        "step accept (continue) 路径必须真实写入 checkpoint；"
        "如果 handler 删掉 save_checkpoint 调用，resume 会丢"
        "「用户已批准 step」状态。"
    )
    _scan_no_leak(json.dumps(state_a.conversation.messages, ensure_ascii=False))
    _scan_no_leak(ckpt_file.read_text(encoding="utf-8"))

    # 清理 ckpt 文件准备下一条
    ckpt_file.unlink()

    # ----- accept_task_done：最后一步 -----
    state_b = create_agent_state(system_prompt="test")
    state_b.task.status = "awaiting_step_confirmation"
    state_b.task.user_goal = "demo"
    state_b.task.current_plan = {
        "goal": "demo",
        "steps": [
            {
                "step_id": "step-1",
                "title": "only",
                "description": "only",
                "step_type": "report",
            },
        ],
    }
    state_b.task.current_step_index = 0
    ctx_b = ch.ConfirmationContext(
        state=state_b,
        turn_state=SimpleNamespace(),
        client=None,
        model_name="x",
        continue_fn=_continue,
    )
    out_b = ch.handle_step_confirmation("y", ctx_b)
    assert "任务已完成" in out_b
    # reset_task 之后 task 应回 idle
    assert state_b.task.status == "idle"
    # 任务自然完成必须不落盘
    assert not ckpt_file.exists(), (
        "step accept (task_done) 路径不应残留 checkpoint；"
        "如果 handler 在终态路径上误调 save_checkpoint，resume 会复活已完成任务。"
    )
    _scan_no_leak(json.dumps(state_b.conversation.messages, ensure_ascii=False))

    # ----- reject -----
    state_c = _new_state_with_two_steps()
    ctx_c = ch.ConfirmationContext(
        state=state_c,
        turn_state=SimpleNamespace(),
        client=None,
        model_name="x",
        continue_fn=_continue,
    )
    out_c = ch.handle_step_confirmation("n", ctx_c)
    assert "已停止" in out_c
    assert state_c.task.status == "idle"
    assert not ckpt_file.exists(), (
        "step reject 路径不应残留 checkpoint；"
        "如果误调 save_checkpoint，已停止任务会在 resume 时复活。"
    )
    _scan_no_leak(json.dumps(state_c.conversation.messages, ensure_ascii=False))


# ---------------------------------------------------------------------------
# v0.4 Phase 1 slice 6-c 准备 · tool confirmation pending_tool single source 契约
# ---------------------------------------------------------------------------
# 中文学习边界：本测试钉死的「真实回归点」
# - tool accept 路径成功执行后，pending_tool 必须由 handler 清掉。
#   handler 的 L458 一直承担这个 single source of truth，不能漂移到
#   transition 自动 mutate。后续做 tool confirmation transition 时，
#   transition 字段（如 clear_pending_tool）只能表达 intent，
#   handler 仍是实际清理的执行方。这一条防止 slice 6-c 把清理职责
#   错位到 transition layer 引起静默漏清或重复清理。
# - 异常路径必须保留 pending_tool 以便人工排查；这是 handler 故意保留
#   的真实排查需求，不能因为 transition 模板"看起来对称"就强行清掉。
#
# fake/mock 边界：本测试用 monkeypatch 把 execute_pending_tool 替换成
# 一个最小 fake，模拟「工具成功执行 → handler 走到 L458」与「工具抛
# 异常 → handler 走到 L443 except 分支」两条真实路径。fake 不替代
# handler 的清理职责，仅替代 tool 实际 IO，因为本测试要测的是 handler
# 的清理契约，不是 tool 是否真的能跑。

def test_tool_accept_success_path_clears_pending_tool_via_handler(tmp_path, monkeypatch):
    """tool accept 成功执行后，pending_tool 必须为 None（由 handler 清理）。"""

    from types import SimpleNamespace

    from agent import checkpoint as checkpoint_mod
    from agent import confirm_handlers as ch
    from agent.state import create_agent_state

    ckpt_file = tmp_path / "state.json"
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_PATH", ckpt_file)

    # fake：模拟工具成功执行，不动 pending_tool。这样如果 handler 不清，
    # pending_tool 会留在 state 里被本测试断言抓到。
    def _fake_execute_pending_tool(*, state, turn_state, messages, pending):
        # 模拟工具产生 tool_result（真实 execute_pending_tool 也会写）
        from agent.conversation_events import append_tool_result
        append_tool_result(messages, pending["tool_use_id"], "ok")

    monkeypatch.setattr(ch, "execute_pending_tool", _fake_execute_pending_tool)

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_tool_confirmation"
    state.task.pending_tool = {
        "tool": "read_file",
        "tool_use_id": "toolu_test_accept",
        "input": {"path": "x"},
    }

    def _continue(_ts):
        return "continued"

    ctx = ch.ConfirmationContext(
        state=state,
        turn_state=SimpleNamespace(on_display_event=lambda _e: None),
        client=None,
        model_name="x",
        continue_fn=_continue,
    )
    out = ch.handle_tool_confirmation("y", ctx)
    assert out == "continued"

    # 核心契约：accept 成功路径，pending_tool 必须被 handler 清。
    assert state.task.pending_tool is None, (
        "tool accept 成功后 pending_tool 必须由 handler 清理；"
        "如果清理职责漂移到 transition 自动 mutate 或漏掉，"
        "下一轮 awaiting_tool_confirmation 会复用旧 pending_tool 数据。"
    )
    assert state.task.status == "running"
    assert ckpt_file.exists(), "tool accept 成功路径必须真实写入 checkpoint"


def test_tool_accept_exception_path_keeps_pending_tool_for_inspection(tmp_path, monkeypatch):
    """tool accept 但执行抛异常时，pending_tool 必须保留以便人工排查。

    这是 handler L444 注释明确的真实排查需求；transition 模板对称化时
    不能因为「accept 路径都该清」就把这条排查路径改坏。
    """

    from types import SimpleNamespace

    from agent import checkpoint as checkpoint_mod
    from agent import confirm_handlers as ch
    from agent.state import create_agent_state

    ckpt_file = tmp_path / "state.json"
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_PATH", ckpt_file)

    def _fake_raises(*, state, turn_state, messages, pending):
        raise RuntimeError("tool execution failed for testing")

    monkeypatch.setattr(ch, "execute_pending_tool", _fake_raises)

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_tool_confirmation"
    pending_payload = {
        "tool": "read_file",
        "tool_use_id": "toolu_test_exc",
        "input": {"path": "x"},
    }
    state.task.pending_tool = dict(pending_payload)

    def _continue(_ts):
        return "continued"

    ctx = ch.ConfirmationContext(
        state=state,
        turn_state=SimpleNamespace(on_display_event=lambda _e: None),
        client=None,
        model_name="x",
        continue_fn=_continue,
    )
    out = ch.handle_tool_confirmation("y", ctx)
    assert out == "continued"

    # 核心契约：异常路径必须保留 pending_tool。
    assert state.task.pending_tool is not None, (
        "tool accept 但执行抛异常时，pending_tool 必须保留以便排查；"
        "如果被错误清掉，用户/开发者无法知道当时在试图执行什么工具。"
    )
    assert state.task.pending_tool["tool_use_id"] == pending_payload["tool_use_id"]
    assert state.task.status == "running"


def test_tool_reject_path_clears_pending_tool_via_transition_intent(tmp_path, monkeypatch):
    """tool reject 路径：清理由 handler 读 transition.clear_pending_tool 触发。

    钉死 USER_REJECTION transition 的 clear_pending_tool=True 契约不会
    在后续 slice 6-c 重命名为 ToolConfirmationKind 时被破坏。
    """

    from types import SimpleNamespace

    from agent import checkpoint as checkpoint_mod
    from agent import confirm_handlers as ch
    from agent.state import create_agent_state

    ckpt_file = tmp_path / "state.json"
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_PATH", ckpt_file)

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_tool_confirmation"
    state.task.pending_tool = {
        "tool": "read_file",
        "tool_use_id": "toolu_test_reject",
        "input": {"path": "x"},
    }

    def _continue(_ts):
        return "continued"

    ctx = ch.ConfirmationContext(
        state=state,
        turn_state=SimpleNamespace(on_display_event=lambda _e: None),
        client=None,
        model_name="x",
        continue_fn=_continue,
    )
    out = ch.handle_tool_confirmation("n", ctx)
    assert out == "continued"

    # reject 路径 pending_tool 必须清掉（transition.clear_pending_tool=True
    # → handler 显式清）。
    assert state.task.pending_tool is None, (
        "tool reject 后 pending_tool 必须清；这条契约由 USER_REJECTION "
        "transition 的 clear_pending_tool=True 表达 intent，"
        "handler 实际执行清理。"
    )
    assert state.task.status == "running"


# ---------------------------------------------------------------------------
# v0.4 Phase 1 slice 6-c（tool 子切片）· tool confirmation transition 边界测试
# ---------------------------------------------------------------------------
# 中文学习边界：本组测试钉死的「真实回归点」
# - TOOL_ACCEPTED_SUCCESS: should_checkpoint=True + clear_pending_tool=True，
#   防止后续重构把 success 路径改成不清 pending（旧 pending 数据复用 bug）。
# - TOOL_ACCEPTED_FAILED: should_checkpoint=True + clear_pending_tool=False，
#   防止 transition 模板对称化时把异常路径的 pending_tool 也清掉，破坏
#   confirm_handlers L444 注释明确的人工排查需求。
# - 新枚举只覆盖 accept 两种结局；reject 路径仍走 ToolResultTransitionKind
#   (USER_REJECTION)，这是 v0.1 已存在的 ToolResult 词汇边界，本切片不
#   合并以保留语义层次（ToolResult vs ToolConfirmation）。
# - source-level 契约：handler 真正调用 tool_confirmation_transition 而
#   不是回到 inline state.task.status="running" 的旧写法。

def test_tool_confirmation_kind_covers_only_tool_accept_outcomes():
    """枚举只覆盖 tool accept 的两种结局，不混入 plan/step/user_input/feedback。"""

    from agent.runtime_events import ToolConfirmationKind

    values = {member.value for member in ToolConfirmationKind}
    assert values == {"tool_accepted_success", "tool_accepted_failed"}


def test_tool_confirmation_accept_success_clears_pending_and_checkpoints():
    """成功路径 transition 必须 should_checkpoint=True + clear_pending_tool=True。"""

    from agent.runtime_events import (
        ToolConfirmationKind,
        tool_confirmation_transition,
    )

    result = tool_confirmation_transition(ToolConfirmationKind.TOOL_ACCEPTED_SUCCESS)
    assert result.should_checkpoint is True
    assert result.clear_pending_tool is True
    assert result.next_status == "running"
    assert "tool.accepted" in result.display_events


def test_tool_confirmation_accept_failed_keeps_pending_but_checkpoints():
    """异常路径必须 should_checkpoint=True 但 clear_pending_tool=False。

    回归点：如果有人对称化把 failed 路径也设为 clear_pending_tool=True，
    人工就再也无法看到「当时在试图执行什么工具」，破坏排查能力。
    """

    from agent.runtime_events import (
        ToolConfirmationKind,
        tool_confirmation_transition,
    )

    result = tool_confirmation_transition(ToolConfirmationKind.TOOL_ACCEPTED_FAILED)
    assert result.should_checkpoint is True
    assert result.clear_pending_tool is False, (
        "异常路径必须保留 pending_tool 以便人工排查"
    )
    assert result.next_status == "running"
    assert "tool.accepted_failed" in result.display_events


def test_tool_confirmation_transition_rejects_unknown_kinds():
    """未知 kind（如 reject 形式的伪枚举）必须显式失败。"""

    import pytest

    from agent.runtime_events import tool_confirmation_transition

    class _Foreign:
        value = "tool_rejected_by_user"  # 故意：reject 不在 ToolConfirmationKind 范围

    with pytest.raises(ValueError):
        tool_confirmation_transition(_Foreign())


def test_tool_confirmation_transition_is_pure_function():
    """transition 工厂为纯函数；同输入恒等输出。"""

    from agent.runtime_events import (
        ToolConfirmationKind,
        tool_confirmation_transition,
    )

    a = tool_confirmation_transition(ToolConfirmationKind.TOOL_ACCEPTED_SUCCESS)
    b = tool_confirmation_transition(ToolConfirmationKind.TOOL_ACCEPTED_SUCCESS)
    c = tool_confirmation_transition(ToolConfirmationKind.TOOL_ACCEPTED_FAILED)
    assert a == b
    assert a != c


def test_handle_tool_confirmation_source_actually_routes_through_transition():
    """source-level 契约：tool handler 必须真正调用 tool_confirmation_transition。

    钉点 1：accept 两条路径都用 ToolConfirmationKind 枚举。
    钉点 2：reject 路径仍用 ToolResultTransitionKind.USER_REJECTION（保留
            ToolResult vs ToolConfirmation 的语义边界）。
    钉点 3：禁止越界使用 plan/step/user_input/feedback_intent 的 *Kind。
    """

    import inspect

    from agent import confirm_handlers

    src = inspect.getsource(confirm_handlers.handle_tool_confirmation)
    assert "tool_confirmation_transition" in src
    assert "TOOL_ACCEPTED_SUCCESS" in src
    assert "TOOL_ACCEPTED_FAILED" in src
    # reject 路径仍归 ToolResult 词汇
    assert "USER_REJECTION" in src
    # 禁止越界使用其他 confirmation 的 *Kind
    forbidden = (
        "PlanConfirmationKind",
        "StepConfirmationKind",
        "UserInputConfirmationKind",
        "FeedbackIntentKind",
    )
    for name in forbidden:
        assert name not in src, (
            f"tool handler 不应越界使用 {name}；slice 6-c 只覆盖 tool。"
        )


def test_tool_confirmation_transition_does_not_leak_durable(tmp_path, monkeypatch):
    """端到端：accept success / accept failed 两条路径，durable state 无 transition 字面量。

    fake/mock 边界：monkeypatch execute_pending_tool 模拟成功 / 抛异常两条
    路径；所有 state mutation / save_checkpoint / clear pending_tool 走
    handler 真实代码。
    """

    import json
    from types import SimpleNamespace

    from agent import checkpoint as checkpoint_mod
    from agent import confirm_handlers as ch
    from agent.state import create_agent_state

    ckpt_file = tmp_path / "state.json"
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_PATH", ckpt_file)

    def _scan_no_leak(serialized: str) -> None:
        for marker in (
            "ToolConfirmationKind",
            "tool_confirmation_transition",
            "TransitionResult",
        ):
            assert marker not in serialized, (
                f"transition 内部符号 {marker} 不应出现在 durable state 里"
            )

    def _continue(_ts):
        return "continued"

    # ----- accept success -----
    def _fake_ok(*, state, turn_state, messages, pending):
        from agent.conversation_events import append_tool_result
        append_tool_result(messages, pending["tool_use_id"], "ok")

    monkeypatch.setattr(ch, "execute_pending_tool", _fake_ok)

    state_a = create_agent_state(system_prompt="test")
    state_a.task.status = "awaiting_tool_confirmation"
    state_a.task.pending_tool = {
        "tool": "read_file",
        "tool_use_id": "toolu_a",
        "input": {"path": "x"},
    }
    ctx_a = ch.ConfirmationContext(
        state=state_a,
        turn_state=SimpleNamespace(on_display_event=lambda _e: None),
        client=None,
        model_name="x",
        continue_fn=_continue,
    )
    ch.handle_tool_confirmation("y", ctx_a)
    # success 契约不变（与 stage B 测试一致）
    assert state_a.task.pending_tool is None
    assert ckpt_file.exists()
    _scan_no_leak(json.dumps(state_a.conversation.messages, ensure_ascii=False))
    _scan_no_leak(ckpt_file.read_text(encoding="utf-8"))
    ckpt_file.unlink()

    # ----- accept failed -----
    def _fake_raises(*, state, turn_state, messages, pending):
        raise RuntimeError("boom")

    monkeypatch.setattr(ch, "execute_pending_tool", _fake_raises)

    state_b = create_agent_state(system_prompt="test")
    state_b.task.status = "awaiting_tool_confirmation"
    state_b.task.pending_tool = {
        "tool": "read_file",
        "tool_use_id": "toolu_b",
        "input": {"path": "x"},
    }
    ctx_b = ch.ConfirmationContext(
        state=state_b,
        turn_state=SimpleNamespace(on_display_event=lambda _e: None),
        client=None,
        model_name="x",
        continue_fn=_continue,
    )
    ch.handle_tool_confirmation("y", ctx_b)
    # failed 契约：pending_tool 保留，但仍 checkpoint
    assert state_b.task.pending_tool is not None
    assert ckpt_file.exists(), (
        "failed 路径 should_checkpoint=True，必须真实写入 checkpoint"
    )
    _scan_no_leak(json.dumps(state_b.conversation.messages, ensure_ascii=False))
    _scan_no_leak(ckpt_file.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# v0.4 Phase 1 slice 6-d · user_input confirmation 复用契约（不新增 Kind）
#
# 设计原则（与 docs/V0_4_EVENT_TRANSITION_PREP.md §4 第四个 confirmation slice 对齐）：
#
#   handle_user_input_step 在 v0.3 已经被 apply_user_replied_transition
#   （agent/transitions.py）抽空成 3 行 dispatcher：
#       resolve_user_input → empty 防御 → apply_user_replied_transition → continue/reply
#   它不像 plan/step/tool 那样 inline 写 status / pending / save_checkpoint。
#
#   因此 v0.4 slice 6-d 的"正确做法"是 **复用 v0.3 已有的 transition 边界**，
#   而不是再加一个 UserInputConfirmationKind 把已经抽好的层包第二层。
#
#   本 slice 不修改 confirm_handlers、不修改 runtime_events、不修改 transitions；
#   只在测试层钉两条契约，保证未来任何"v0.4 化"重构不会偷偷把 inline mutation
#   塞回 handle_user_input_step（这是真实回归风险，过去 v0.3 之前正是这种长函数）。
#
# 契约 1：handler 必须委托给 apply_user_replied_transition；
# 契约 2：handler 不允许直接 mutate pending_user_input_request / state.task.status
#         （reset_task 损坏态分支例外，已用 not state.task.current_plan 守门）。
#
# 模拟边界说明：本块测试**全部是 source-level 静态扫描**，不构造 fake state、
# 不替换 transition 函数；这是为了：
#   - 避免和 tests/test_user_replied_transition.py 已经端到端覆盖的 6 条
#     transition 行为测试重复（那些是行为契约，这里是结构契约）；
#   - 避免引入"测试本身能 mock 掉的边界"——一个能被 monkeypatch 的契约不是契约。
# ---------------------------------------------------------------------------


def test_user_input_handler_routes_through_apply_user_replied_transition():
    """钉死 handle_user_input_step 必须委托 v0.3 transition，不允许 inline 复刻。

    这条测试守的真实 bug：未来某次"统一 v0.4 vocabulary"的重构可能把
    apply_user_replied_transition 的 import 删掉、把 append/clear/save 三件套
    inline 回 handler，理由听起来都很合理（"减少跨模块跳转"/"和 plan/step/tool
    保持对称"）。一旦发生，handler 就重新承担状态机职责，v0.3 的边界收益归零。
    """
    import inspect
    from agent import confirm_handlers as ch

    src = inspect.getsource(ch.handle_user_input_step)
    assert "apply_user_replied_transition" in src, (
        "handle_user_input_step 必须委托给 apply_user_replied_transition；"
        "如有意去掉，请先把 v0.3 transition 边界的迁移路径写进 "
        "docs/V0_4_EVENT_TRANSITION_PREP.md 并加替代契约测试。"
    )
    assert "resolve_user_input" in src, (
        "handle_user_input_step 必须先经过 resolve_user_input 输入解析层；"
        "跳过它会让 empty_user_input 防御失效，空回复会污染 transition。"
    )


def test_user_input_handler_does_not_inline_mutate_pending_or_status():
    """钉死 handler 不允许直接 mutate pending_user_input_request / task.status。

    真实历史教训：confirm_handlers 早期版本里曾经有
        state.task.pending_user_input_request = None
        state.task.status = "running"
    直接散在 handler 各处。每加一条触发路径就要复刻一次，最后形成"清 pending 与
    保存 checkpoint 顺序不一致"的诡异 bug。v0.3 把它们集中到 transitions.py
    后该问题消失。本测试守住"集中"这件事不被悄悄回滚。

    例外：
      - 文件顶层 import / 类型声明里出现的字符串不在 handler 函数体内，不算违规；
      - reset_task 损坏态分支允许出现（已由 `not current_plan and not pending`
        守门），那是 v0.3 之前就存在的损坏态收尾，不是状态机推进。
    """
    import inspect
    from agent import confirm_handlers as ch

    src = inspect.getsource(ch.handle_user_input_step)
    forbidden_pending = "state.task.pending_user_input_request ="
    forbidden_status = 'state.task.status = "'
    assert forbidden_pending not in src, (
        "handle_user_input_step 不允许直接清/设 pending_user_input_request；"
        "这件事应当通过 apply_user_replied_transition 完成。"
    )
    assert forbidden_status not in src, (
        "handle_user_input_step 不允许直接写 state.task.status；"
        "状态推进是 transitions.py 的职责。"
    )


def test_user_input_handler_keeps_empty_input_guard_before_transition():
    """空输入防御必须在 transition 调用之前。

    真实 bug：如果先调 apply_user_replied_transition、再判 empty，那么空回复
    会先把 pending 清掉、把 step 推进掉，再回头返回"请输入有效内容"——用户看
    到的是同一个错误提示，但底层状态已经不可恢复。
    """
    import inspect
    from agent import confirm_handlers as ch

    src = inspect.getsource(ch.handle_user_input_step)
    empty_idx = src.find("EMPTY_USER_INPUT")
    transition_idx = src.find("apply_user_replied_transition(")
    assert empty_idx != -1 and transition_idx != -1, (
        "handler 源码必须同时引用 EMPTY_USER_INPUT 与 apply_user_replied_transition"
    )
    assert empty_idx < transition_idx, (
        "empty 防御必须出现在 apply_user_replied_transition 调用之前；"
        "顺序反了会让空回复污染 transition 状态。"
    )


def test_user_input_slice_does_not_introduce_new_confirmation_kind():
    """钉死本 slice 不把 user_input 包成新的 *ConfirmationKind。

    这是一条架构契约：v0.4 Phase 1 slice 6-d 显式选择"复用 v0.3 transition"
    而不是"新增 vocabulary"。如果未来真的需要新增（例如要把 user_input 接入
    runtime cancel / generation abort 的统一事件流），必须先在
    docs/V0_4_EVENT_TRANSITION_PREP.md 写明动机、再删掉本测试，而不是悄悄加。
    """
    from agent import runtime_events as re

    forbidden = [
        "UserInputConfirmationKind",
        "USER_INPUT_ACCEPTED",
        "USER_INPUT_REJECTED",
        "user_input_confirmation_transition",
    ]
    for name in forbidden:
        assert not hasattr(re, name), (
            f"runtime_events 不应导出 {name}；slice 6-d 选择复用"
            f" apply_user_replied_transition，不新增并行 vocabulary。"
            f"如确需，请先更新 docs/V0_4_EVENT_TRANSITION_PREP.md。"
        )


# ---------------------------------------------------------------------------
# v0.4 Phase 1 slice 6-d 之后 / slice 6-e（feedback_intent）契约前置层
#
# 本块是 feedback_intent transition 迁移的"前置安全网"，不是迁移本身：
#
#   feedback_intent 是 confirm_handlers 中最后一个仍持有 inline state mutation
#   且唯一在 confirm 内调 LLM 的 handler。它涉及四条路径：
#     1) "1" as_feedback     —— 写 plan_feedback control event + 调 generate_plan
#     2) "2" as_new_task     —— reset_task + clear_checkpoint + start_planning_fn
#     3) "3" cancel          —— 仅恢复 origin_status + save_checkpoint，无 messages
#     4) 任意其它输入 ambiguous —— 状态/pending/messages 三者必须全不变，仅 emit
#
#   tests/test_feedback_intent_flow.py 已经用全 chat() 驱动覆盖了行为契约。
#   本块提供四条**结构契约**，专门针对未来"v0.4 化"重构最可能踩坏的不变量：
#     - cancel 路径不允许悄悄写 messages（即使被 transition 包了也不行）；
#     - as_new_task 路径 reset_task 调用必须**先于** start_planning_fn；
#     - ambiguous 路径不允许调 save_checkpoint / 不允许进入 transition；
#     - as_feedback 路径源码层禁止把 revised_goal 写回 state.task.user_goal。
#
#   全部尽量用直接 unit 调用（不绕全 chat）+ 调用顺序 spy + 源码静态扫描，
#   原因：契约要钉住的是"什么不能发生"，全链路 driver 容易在被告 transition
#   重构后被同样的重构"顺便"重写绿。结构契约更难被同步绕过。
# ---------------------------------------------------------------------------


def _make_feedback_intent_ctx(*, choice: str, monkeypatch, with_planning_fn=True):
    """构造 awaiting_feedback_intent 状态下的最小 ConfirmationContext。

    模拟边界说明：
    - 直接调 handle_feedback_intent_choice，不走 chat()，避免和 flow 测试重复；
    - generate_plan 被替换为返回 None 的 fake，避免真的调 LLM——本块不验证
      LLM 行为，只验证 mutation 与调用顺序契约；
    - start_planning_fn 用 spy lambda 记录调用顺序而不实际触发新 planner。
    """
    from agent import confirm_handlers as ch
    from agent.checkpoint import CHECKPOINT_PATH as _orig_path  # noqa: F401
    from agent import confirm_handlers as _ch_mod
    from agent.state import create_agent_state
    from types import SimpleNamespace

    state = create_agent_state(system_prompt="test")
    state.task.user_goal = "原始目标 keep me safe"
    state.task.current_plan = {
        "goal": "p",
        "steps": [
            {"step_id": 1, "title": "s", "description": "d", "step_type": "report"}
        ],
    }
    state.task.status = "awaiting_feedback_intent"
    state.task.pending_user_input_request = {
        "awaiting_kind": "feedback_intent",
        "origin_status": "awaiting_step_confirmation",
        "pending_feedback_text": "请把第二步改成先分析",
        "question": "Q",
        "options": ["1", "2", "3"],
    }

    call_log: list[str] = []

    def _fake_generate_plan(*_a, **_kw):
        call_log.append("generate_plan")
        return None

    monkeypatch.setattr(_ch_mod, "generate_plan", _fake_generate_plan)

    def _spy_start_planning(text, ts):
        call_log.append(f"start_planning_fn:{text}")
        return ""

    ctx = ch.ConfirmationContext(
        state=state,
        turn_state=SimpleNamespace(on_runtime_event=lambda _e: call_log.append("emit")),
        client=None,
        model_name="x",
        continue_fn=lambda _ts: "",
        start_planning_fn=_spy_start_planning if with_planning_fn else None,
    )
    # spy reset_task 的调用顺序——通过 monkeypatch state 实例方法
    orig_reset = state.reset_task

    def _spy_reset():
        call_log.append("reset_task")
        return orig_reset()

    state.reset_task = _spy_reset  # type: ignore[method-assign]
    return ch, state, ctx, call_log, choice


def test_feedback_intent_cancel_does_not_write_messages_or_call_planner(
    monkeypatch, tmp_path
):
    """钉死 cancel ("3") 路径：不允许写 messages、不允许调 planner / start_planning_fn。

    真实回归风险：未来 transition 迁移如果把 cancel 也归到统一的 'restore +
    checkpoint' transition 里，可能顺手 append 一条 control event "用户取消了
    反馈意图"——看起来很合理，但破坏 docs/P1_TOPIC_SWITCH_PLAN.md §3 红线
    "cancel = 完全无副作用"，并让 messages 残留一条永远无法撤销的取消记录。
    """
    from agent import checkpoint as ckmod

    ckpt_file = tmp_path / "ckpt.json"
    monkeypatch.setattr(ckmod, "CHECKPOINT_PATH", ckpt_file)

    ch, state, ctx, call_log, _ = _make_feedback_intent_ctx(
        choice="3", monkeypatch=monkeypatch
    )
    before_msgs_len = len(state.conversation.messages)
    before_goal = state.task.user_goal

    ch.handle_feedback_intent_choice("3", ctx)

    assert state.task.status == "awaiting_step_confirmation", (
        "cancel 必须恢复 origin_status"
    )
    assert state.task.pending_user_input_request is None, "cancel 必须清 pending"
    assert state.task.user_goal == before_goal, "cancel 不允许动 user_goal"
    assert len(state.conversation.messages) == before_msgs_len, (
        "cancel 路径不允许 append 任何 control event；这是 P1 §3 红线。"
    )
    assert "generate_plan" not in call_log, "cancel 路径不允许调 LLM planner"
    assert not any(c.startswith("start_planning_fn") for c in call_log), (
        "cancel 路径不允许调 start_planning_fn——那是 as_new_task 路径"
    )


def test_feedback_intent_as_new_task_reset_strictly_precedes_start_planning(
    monkeypatch, tmp_path
):
    """钉死 as_new_task ("2") 路径：reset_task 调用必须**严格先于** start_planning_fn。

    真实回归风险：调用顺序反了会让 start_planning_fn 看到旧 user_goal +
    旧 current_plan，新 plan 可能被旧上下文污染（与 chat() 正常新任务入口不
    同构），破坏 hardcore #6 'user_goal 不膨胀' 不变量。
    """
    from agent import checkpoint as ckmod

    ckpt_file = tmp_path / "ckpt.json"
    monkeypatch.setattr(ckmod, "CHECKPOINT_PATH", ckpt_file)

    ch, state, ctx, call_log, _ = _make_feedback_intent_ctx(
        choice="2", monkeypatch=monkeypatch
    )
    ch.handle_feedback_intent_choice("2", ctx)

    reset_idx = call_log.index("reset_task")
    plan_idx = next(
        i for i, c in enumerate(call_log) if c.startswith("start_planning_fn:")
    )
    assert reset_idx < plan_idx, (
        f"as_new_task 必须先 reset_task 再 start_planning_fn；"
        f"当前调用顺序：{call_log}"
    )
    # start_planning_fn 必须收到 pending_feedback_text 原文，不能被旧 goal 污染
    assert "start_planning_fn:请把第二步改成先分析" in call_log


def test_feedback_intent_as_new_task_without_start_planning_fn_falls_back_safely(
    monkeypatch, tmp_path
):
    """钉死 as_new_task 注入未生效时的安全降级：仍要 reset + clear，不允许悄悄成功。

    真实回归风险：如果未来把这条防御挪到 transition 层，可能漏写"返回提示串"，
    用户看到空字符串以为新任务已经开始，但其实 planner 没启动 → 沉默丢失任务。
    """
    from agent import checkpoint as ckmod

    ckpt_file = tmp_path / "ckpt.json"
    monkeypatch.setattr(ckmod, "CHECKPOINT_PATH", ckpt_file)

    ch, state, ctx, call_log, _ = _make_feedback_intent_ctx(
        choice="2", monkeypatch=monkeypatch, with_planning_fn=False
    )
    reply = ch.handle_feedback_intent_choice("2", ctx)
    assert reply == "请重新输入你的新任务。", (
        "start_planning_fn 注入失败必须显式提示用户重发，不允许返回空串"
    )
    assert "reset_task" in call_log
    assert not any(c.startswith("start_planning_fn") for c in call_log)


def test_feedback_intent_ambiguous_does_not_save_checkpoint_or_mutate_state(
    monkeypatch, tmp_path
):
    """钉死 ambiguous 路径：不允许 save_checkpoint，不允许 mutate state/pending/messages。

    真实回归风险：transition 迁移最危险的统一动作是"任何 confirm 路径结束都
    save_checkpoint"。一旦 ambiguous 路径也被卷入，会把"未决意图"持久化，
    导致下次 resume 状态机从一个本不该存在的中间态恢复。
    """
    from agent import checkpoint as ckmod

    ckpt_file = tmp_path / "ckpt.json"
    monkeypatch.setattr(ckmod, "CHECKPOINT_PATH", ckpt_file)

    ch, state, ctx, call_log, _ = _make_feedback_intent_ctx(
        choice="ambiguous", monkeypatch=monkeypatch
    )
    snap_status = state.task.status
    snap_pending = dict(state.task.pending_user_input_request or {})
    snap_msgs_len = len(state.conversation.messages)
    snap_goal = state.task.user_goal

    ch.handle_feedback_intent_choice("请把第二步改成先分析", ctx)

    assert state.task.status == snap_status
    assert dict(state.task.pending_user_input_request or {}) == snap_pending
    assert len(state.conversation.messages) == snap_msgs_len
    assert state.task.user_goal == snap_goal
    assert not ckpt_file.exists(), (
        "ambiguous 路径不允许写 checkpoint——未决意图不能被持久化"
    )
    assert "generate_plan" not in call_log
    assert not any(c.startswith("start_planning_fn") for c in call_log)
    assert "reset_task" not in call_log
    assert call_log == ["emit"], (
        f"ambiguous 路径只允许 emit feedback_intent_requested 一个动作；"
        f"实际：{call_log}"
    )


def test_feedback_intent_as_feedback_handler_source_does_not_write_revised_goal_back():
    """钉死 as_feedback ("1") 路径源码层：revised_goal 仅作 planner 输入，不允许回写 user_goal。

    真实回归风险：未来 transition 迁移如果把 'feedback 等同于 new task' 当作
    简化点，可能把 revised_goal 也赋回 state.task.user_goal——结果就是用户
    每提一次反馈，user_goal 就被增长一段"补充意见"，违反 hardcore #6
    'user_goal 忠实记录用户最初任务' 不变量。

    这条用源码静态扫描而不是 runtime 行为：runtime 测试容易在重构里被同步
    重写，源码契约更难被绕过。
    """
    import inspect
    from agent import confirm_handlers as ch

    src = inspect.getsource(ch.handle_feedback_intent_choice)
    forbidden_patterns = [
        "state.task.user_goal = revised_goal",
        "state.task.user_goal=revised_goal",
        "state.task.user_goal = f\"{state.task.user_goal}",
        "state.task.user_goal += ",
    ]
    for pat in forbidden_patterns:
        assert pat not in src, (
            f"handle_feedback_intent_choice 不允许把 revised_goal / "
            f"反馈文本回写 state.task.user_goal；命中禁止模式：{pat}。"
            f"详见 hardcore #6 与 commit c252795 的不变量。"
        )
    assert "revised_goal = (" in src or "revised_goal = f" in src, (
        "as_feedback 路径必须显式构造 revised_goal 局部变量，否则边界不清晰"
    )


# ---------------------------------------------------------------------------
# v0.4 Phase 1 slice 6-e · feedback_intent confirmation transition（收口切片）
#
# 这是 user-confirmation 系列最后一个 transition slice，也是 slice 6 中**最危险**
# 的一块。前置契约层（slice 6-d 之后的 5 条 contract pin）已经把"什么不能发生"
# 钉死；本 slice 只把 4 条路径的 Runtime 意图通过 FeedbackIntentKind +
# feedback_intent_transition 表达出来，handler 的所有真实 mutation / LLM 调用
# / messages 写入 / start_planning_fn 反向回调 **完全不变**。
#
# 本块测试聚焦 transition 工厂的**意图契约**（不是行为契约——后者已在前置层
# 钉死）。每一条路径的 should_checkpoint / clear_pending_user_input /
# next_status 都精确钉死，防止未来"统一动作"重构悄悄改这些布尔。
# ---------------------------------------------------------------------------


def test_feedback_intent_kind_enum_covers_exactly_four_paths():
    """钉死 FeedbackIntentKind 仅有 4 个值。

    AS_FEEDBACK / AS_NEW_TASK / CANCELLED / AMBIGUOUS 是产品级语义，对应
    awaiting_feedback_intent 子状态的 4 条出口。新增第 5 个值意味着引入新
    路径（例如 'DEFER'），必须先在 docs/V0_4_EVENT_TRANSITION_PREP.md 写
    迁移路径再加；删除任意一个意味着合并语义边界，会破坏 P1 §3 红线。
    """
    from agent.runtime_events import FeedbackIntentKind

    assert {k.value for k in FeedbackIntentKind} == {
        "as_feedback",
        "as_new_task",
        "cancelled",
        "ambiguous",
    }


def test_feedback_intent_as_feedback_transition_intent():
    """as_feedback 意图：should_checkpoint=True + clear_pending=True + next=plan_confirmation。

    handler 调 generate_plan 成功后会重新进入 plan 确认；transition 把 next_status
    显式钉成 'awaiting_plan_confirmation'，防止未来重构把它和 cancel 路径合并。
    """
    from agent.runtime_events import (
        FeedbackIntentKind,
        feedback_intent_transition,
    )

    t = feedback_intent_transition(FeedbackIntentKind.AS_FEEDBACK)
    assert t.next_status == "awaiting_plan_confirmation"
    assert t.should_checkpoint is True
    assert t.clear_pending_user_input is True
    assert t.clear_pending_tool is False
    assert t.advance_step is False


def test_feedback_intent_as_new_task_transition_intent():
    """as_new_task 意图：should_checkpoint=False（由 clear_checkpoint + start_planning_fn 接管）。

    next_status=None 是契约：transition 不预设新任务的 status，由 start_planning_fn
    内部决定，避免把"新任务的初始 status"和"旧任务的终态"混在一个值里。
    """
    from agent.runtime_events import (
        FeedbackIntentKind,
        feedback_intent_transition,
    )

    t = feedback_intent_transition(FeedbackIntentKind.AS_NEW_TASK)
    assert t.next_status is None
    assert t.should_checkpoint is False
    assert t.clear_pending_user_input is True


def test_feedback_intent_cancelled_transition_intent():
    """cancel 意图：should_checkpoint=True（origin_status 必须落盘）+ clear_pending=True。

    next_status=None：transition 不替 handler 决定 origin_status 的具体值
    （由 pending['origin_status'] 决定，可能是 awaiting_plan/step_confirmation）；
    handler 自己回填。
    """
    from agent.runtime_events import (
        FeedbackIntentKind,
        feedback_intent_transition,
    )

    t = feedback_intent_transition(FeedbackIntentKind.CANCELLED)
    assert t.next_status is None
    assert t.should_checkpoint is True
    assert t.clear_pending_user_input is True


def test_feedback_intent_ambiguous_transition_intent_is_critical_no_op():
    """AMBIGUOUS 意图：should_checkpoint=False + clear_pending=False + next=None。

    **这是 slice 6-e 最关键的契约**。AMBIGUOUS 路径的 transition 必须是
    "三个 False"——任何一个变 True 都会让未决意图被持久化或被悄悄推进，
    破坏 docs/P1_TOPIC_SWITCH_PLAN.md §3 反 heuristic 红线。前置契约层
    test_feedback_intent_ambiguous_does_not_save_checkpoint_or_mutate_state
    钉了"行为不能发生"，这条钉"意图层不能宣告"。
    """
    from agent.runtime_events import (
        FeedbackIntentKind,
        feedback_intent_transition,
    )

    t = feedback_intent_transition(FeedbackIntentKind.AMBIGUOUS)
    assert t.next_status is None
    assert t.should_checkpoint is False, (
        "AMBIGUOUS 不允许 should_checkpoint=True：未决意图禁止持久化"
    )
    assert t.clear_pending_user_input is False, (
        "AMBIGUOUS 不允许清 pending：用户还没决定，pending 必须保留以再次发问"
    )
    assert t.advance_step is False
    assert t.clear_pending_tool is False


def test_feedback_intent_transition_rejects_unknown_kind():
    """未知 kind 必须显式 ValueError，不允许静默兜底。

    模拟边界：构造一个名字像 feedback intent 但实际是 plan kind 的伪装对象，
    确保工厂不会通过 `==` 字符串巧合匹配通过——它必须严格按 enum 身份匹配。
    """
    from agent.runtime_events import (
        FeedbackIntentKind,
        PlanConfirmationKind,
        feedback_intent_transition,
    )
    import pytest

    with pytest.raises(ValueError, match="unsupported feedback intent kind"):
        feedback_intent_transition(PlanConfirmationKind.PLAN_ACCEPTED)  # type: ignore[arg-type]
    # 4 个合法 kind 全过；防止"循环里漏一个"的回归
    for k in FeedbackIntentKind:
        feedback_intent_transition(k)


def test_feedback_intent_handler_routes_through_transition_factory_for_all_four_paths():
    """钉死 handler 4 条路径都通过 feedback_intent_transition 声明意图。

    源码静态扫描：守住未来"transition 看起来多余，删掉省事"的回归。一旦某
    条路径丢了 transition 调用，未来重构把"统一动作"加回来时，就缺少意图
    层断言（assert not should_checkpoint 等）的保护，AMBIGUOUS 路径会第一
    个被穿透。
    """
    import inspect
    from agent import confirm_handlers as ch

    src = inspect.getsource(ch.handle_feedback_intent_choice)
    # 多行换行兼容：仅断言 'feedback_intent_transition(' 出现至少 4 次 + 4 个 kind 名
    assert src.count("feedback_intent_transition(") >= 4, (
        "handler 必须为 4 条路径都调用 feedback_intent_transition()"
    )
    for kind_name in (
        "FeedbackIntentKind.AS_FEEDBACK",
        "FeedbackIntentKind.AS_NEW_TASK",
        "FeedbackIntentKind.CANCELLED",
        "FeedbackIntentKind.AMBIGUOUS",
    ):
        assert kind_name in src, (
            f"handler 必须显式引用 {kind_name}（不允许字符串别名或动态 lookup 绕过）"
        )
    # 关键 assert 必须留在 handler 中作为 in-source 契约护栏
    assert "assert not ambiguous_transition.should_checkpoint" in src, (
        "handler 必须保留 'AMBIGUOUS 不写 checkpoint' 的 in-source assert"
    )


# ---------------------------------------------------------------------------
# v0.4 Phase 2a 设计审计落地为防回归契约
#
# Phase 2a 设计审计发现：_run_main_loop 已在 core.py 模块级（agent/core.py:408），
# Phase 2a 名义上的"提到模块级"工作已被早期 baseline commit 实质完成。
# 本块测试不是为新增功能服务的，而是为了在未来 Phase 2 dependency-injection
# slice 中守住"不能把 _run_main_loop 退化回 chat() 闭包"。
#
# 历史教训：early v0.4 之前 _run_main_loop 是 chat() 内部 def，只能从 chat()
# 调用，外部测试不可达；那一波抽到模块级是 c2abd80/f6a1539 baseline 时期就做
# 完的隐性收益。如果未来重构以"减少模块级符号"为由把它塞回 chat()，会让所有
# Phase 2 dependency-injection 切片的入口失效。
# ---------------------------------------------------------------------------


def test_run_main_loop_is_module_level_not_chat_closure():
    """钉死 _run_main_loop 必须是 core.py 模块级函数，不允许退化为 chat() 闭包。

    模拟边界：本测试只查模块属性 + 函数 qualname，不调 _run_main_loop（避免
    引入 client/model fixture）。它守住的是"模块级入口存在"这件事，是 Phase 2
    dependency-injection 切片的前置条件。
    """
    from agent import core

    assert hasattr(core, "_run_main_loop"), (
        "agent.core 必须导出 _run_main_loop 模块级符号；"
        "如果它被收回 chat() 闭包，Phase 2 dependency-injection 入口会失效"
    )
    fn = core._run_main_loop
    assert callable(fn)
    # qualname 不带 'chat.' 前缀 = 模块级；带前缀 = 闭包
    assert "." not in fn.__qualname__, (
        f"_run_main_loop.__qualname__={fn.__qualname__!r}；"
        "出现 '.' 说明它退化为某函数的内部嵌套定义，违反 Phase 2a 前置条件"
    )


def test_chat_module_does_not_use_nonlocal_for_loop_helpers():
    """钉死 core.py 不依赖 nonlocal 把 loop helpers 封进 chat()。

    nonlocal 关键字在 core.py 出现就意味着至少有一层闭包在共享可变状态；
    这正是 Phase 2 dependency-injection 切片需要先排除的耦合形式。
    本测试只读源码（不调任何函数），确保未来引入闭包时立刻失败。
    """
    import inspect
    from agent import core

    src = inspect.getsource(core)
    assert "nonlocal " not in src, (
        "agent/core.py 不允许出现 nonlocal；如需共享可变状态，请走 "
        "Phase 2 LoopContext dataclass 注入路径而不是闭包"
    )


# ========================================================================
# Phase 2.1：LoopContext dependency-injection 锚点边界
# ------------------------------------------------------------------------
# 这一组测试钉死 v0.4 Phase 2.1 切片的契约：
#   1) LoopContext 已存在且字段拓扑符合预期（client / model_name /
#      max_loop_iterations，且 frozen + 构造期 validate）；
#   2) chat() 内部已构造一次 LoopContext 实例（Phase 2.2/2.3 会把它接到
#      helper signature；本切片只钉"已经有锚点"）；
#   3) LoopContext 不允许 leak 到 durable layer（checkpoint/state/
#      conversation/transitions），防止 Phase 2.x 任意切片把运行时依赖
#      混进 schema；
#   4) LoopContext.__repr__ 不允许把 client（可能内嵌 api_key）打印出来；
#   5) LoopContext 字段名禁止包含 durable 字段（messages/task/status/
#      pending_*）——这是字段级别的 schema-vs-runtime 分层守卫。
# 任何后续 sub-slice 想"顺手把 state / messages 塞进 LoopContext"都会被
# 第 5 条立刻拦下，避免 dependency-injection 字段慢慢退化成 god-object。
# ========================================================================


def test_loop_context_module_defines_frozen_dataclass_with_expected_fields():
    """LoopContext 字段拓扑契约。"""

    import dataclasses

    from agent.loop_context import LoopContext

    assert dataclasses.is_dataclass(LoopContext)
    # frozen=True：禁止 helper 偷偷 mutate 注入实例
    assert LoopContext.__dataclass_params__.frozen is True

    field_names = {f.name for f in dataclasses.fields(LoopContext)}
    assert field_names == {"client", "model_name", "max_loop_iterations"}, (
        f"LoopContext 字段集合漂移：{field_names}；"
        "新增字段必须先评估是否属于 runtime dependency"
    )


def test_loop_context_post_init_rejects_invalid_inputs():
    """构造期校验：空 model / 非正循环上限 / None client 必须 fail-fast。"""

    from agent.loop_context import LoopContext

    sentinel_client = object()  # 非 None 即可，本测试不调任何 client 方法

    with pytest.raises(ValueError):
        LoopContext(client=sentinel_client, model_name="", max_loop_iterations=10)
    with pytest.raises(ValueError):
        LoopContext(client=sentinel_client, model_name="m", max_loop_iterations=0)
    with pytest.raises(ValueError):
        LoopContext(client=None, model_name="m", max_loop_iterations=10)

    # 合法构造不应抛
    ctx = LoopContext(
        client=sentinel_client, model_name="claude-sonnet-test", max_loop_iterations=7
    )
    assert ctx.model_name == "claude-sonnet-test"
    assert ctx.max_loop_iterations == 7


def test_loop_context_repr_does_not_leak_client_object():
    """__repr__ 不允许把 client 字段打印出来。

    SDK 实例可能在 ``__repr__`` 中包含 ``api_key='sk-...'`` 风格的字段；
    LoopContext 已用 ``repr=False`` 标记 client，这里通过断言 repr 字符串
    不包含 ``client=`` 来钉死该约束。如果未来有人改成 ``repr=True``，
    本测试会立刻失败。
    """

    from agent.loop_context import LoopContext

    class _FakeClientWithSecret:
        def __repr__(self) -> str:  # pragma: no cover - 仅为 leak 探针
            return "FakeClient(api_key='sk-leak-MUST-NOT-APPEAR')"

    ctx = LoopContext(
        client=_FakeClientWithSecret(),
        model_name="claude-sonnet-test",
        max_loop_iterations=10,
    )
    rendered = repr(ctx)
    assert "client=" not in rendered, (
        f"LoopContext.__repr__ 不允许暴露 client 字段：{rendered}"
    )
    assert "sk-leak-MUST-NOT-APPEAR" not in rendered, (
        f"LoopContext.__repr__ 把 client repr 内容泄漏出来了：{rendered}"
    )


def test_loop_context_field_names_exclude_durable_state():
    """LoopContext 字段名禁止与 durable state 字段重名。

    durable state（messages / task / status / pending_*）是
    ``checkpoint.json`` schema 的一部分；它们必须留在 ``agent.state``，
    不允许通过 LoopContext 偷渡进 runtime dependency layer。
    """

    import dataclasses

    from agent.loop_context import LoopContext

    forbidden_substrings = (
        "messages",
        "task",
        "status",
        "pending",
        "checkpoint",
        "summary",
        "memory",
        "conversation",
    )
    field_names = [f.name for f in dataclasses.fields(LoopContext)]
    for name in field_names:
        for forbidden in forbidden_substrings:
            assert forbidden not in name.lower(), (
                f"LoopContext 字段 {name} 含禁用子串 {forbidden}："
                "durable state 不允许进 runtime dependency container"
            )


def test_loop_context_not_imported_by_durable_layers():
    """LoopContext 不允许被 checkpoint / state / transitions 层 import。

    这条件同时反向证明 LoopContext 没有写入 checkpoint.json：如果未来
    有人在 ``agent/checkpoint.py`` 里 ``from agent.loop_context import
    LoopContext`` 想 serialize 它，本测试立刻失败。
    """

    import inspect

    from agent import checkpoint as checkpoint_mod
    from agent import state as state_mod
    from agent import transitions as transitions_mod

    for mod, label in (
        (checkpoint_mod, "agent/checkpoint.py"),
        (state_mod, "agent/state.py"),
        (transitions_mod, "agent/transitions.py"),
    ):
        src = inspect.getsource(mod)
        assert "LoopContext" not in src, (
            f"{label} 不允许引用 LoopContext：runtime dependency "
            "禁止进入 durable layer 或状态机本体"
        )


def test_chat_constructs_loop_context_instance_at_module_level_anchor():
    """LoopContext 构造点（v0.5 第一小步起在 _build_loop_context 工厂）从
    模块级运行时常量取值。

    历史：v0.4 Phase 2.1 时构造直接写在 chat() 函数体内；v0.5 Phase 3
    第一小步把构造抽到 _build_loop_context() 工厂，chat() 改为调用
    `_build_loop_context(client)`。

    本测试**不弱化**——契约本质从未改变：
      - 构造点仍存在；
      - client / MODEL_NAME / MAX_LOOP_ITERATIONS 仍是 SSOT 默认值；
      - 没有引入隐式新默认值。
    只是把"构造点位置"从 chat() src 改成 helper src，因为 chat() src
    内现在只有 `_build_loop_context(client)` 一行调用（这是抽 helper
    的目的），原"chat() src 必须出现 LoopContext(...)"成为过时约束。
    """

    import inspect

    from agent import core

    helper_src = inspect.getsource(core._build_loop_context)
    assert "LoopContext(" in helper_src, (
        "_build_loop_context 必须显式构造 LoopContext 作为 SSOT 锚点"
    )
    assert "client=client" in helper_src, (
        "helper 必须把入参 client_obj 透传到 LoopContext.client"
        "（实际写法：client=client_obj 也可，下行兼容判断）"
    ) or "client=client_obj" in helper_src
    assert (
        "model_name=MODEL_NAME" in helper_src
        or "model_name: str = MODEL_NAME" in helper_src
    ), "helper 默认 model_name 必须是模块常量 MODEL_NAME"
    assert (
        "max_loop_iterations=MAX_LOOP_ITERATIONS" in helper_src
        or "max_loop_iterations: int = MAX_LOOP_ITERATIONS" in helper_src
    ), "helper 默认 max_loop_iterations 必须是模块常量 MAX_LOOP_ITERATIONS"

    # 同时检查 chat() 仍然显式调用 helper（不绕过 SSOT），并且
    # 显式传入 MODEL_NAME / MAX_LOOP_ITERATIONS（保证 monkeypatch 生效）
    chat_src = inspect.getsource(core.chat)
    assert "_build_loop_context(" in chat_src, (
        "chat() 必须通过 _build_loop_context(...) 走 SSOT 工厂构造"
    )
    assert "model_name=MODEL_NAME" in chat_src, (
        "chat() 必须显式传 model_name=MODEL_NAME（让 monkeypatch 生效）"
    )
    assert "max_loop_iterations=MAX_LOOP_ITERATIONS" in chat_src, (
        "chat() 必须显式传 max_loop_iterations=MAX_LOOP_ITERATIONS"
        "（让 monkeypatch.setattr(core, 'MAX_LOOP_ITERATIONS', N) 生效）"
    )


# ========================================================================
# Phase 2.2-a：planning helpers 接受 LoopContext 注入边界
# ------------------------------------------------------------------------
# 这一组测试钉死 v0.4 Phase 2.2-a 切片的契约：
#   1) _run_planning_phase 与 _start_planning_for_handler 签名包含 loop_ctx；
#   2) chat() 把构造好的 _loop_ctx 传给两个 helper 的所有调用点（直接调用
#      + 通过 ConfirmationContext.start_planning_fn 间接调用）；
#   3) helpers 不再隐式引用 module-level client / MODEL_NAME；planner 调用
#      读取 loop_ctx 字段——这是"运行时依赖显式化"的实质边界；
#   4) durable state 仍走 module-level state 单例：messages / task /
#      current_plan / save_checkpoint 都不通过 loop_ctx 传递，避免
#      LoopContext 退化为 god-object；
#   5) Phase 2.2-c (主循环 / _call_model 吃 loop_ctx) **本轮不能擅自做**：
#      _run_main_loop 签名必须仍只吃 turn_state，把"分阶段迁移"钉死。
# 任何后续切片想"顺手把 state / messages / save_checkpoint 也走 loop_ctx"
# 都会被第 4 条立刻拦下。
# ========================================================================


def test_planning_phase_signature_accepts_loop_context():
    """_run_planning_phase 与 _start_planning_for_handler 签名契约。"""

    import inspect

    from agent import core
    from agent.loop_context import LoopContext

    for fn_name in ("_run_planning_phase", "_start_planning_for_handler"):
        fn = getattr(core, fn_name)
        sig = inspect.signature(fn)
        assert "loop_ctx" in sig.parameters, (
            f"{fn_name} 必须接收 loop_ctx 参数（Phase 2.2-a 契约）"
        )
        annotation = sig.parameters["loop_ctx"].annotation
        assert annotation is LoopContext, (
            f"{fn_name}.loop_ctx 必须明确标注 LoopContext 类型，"
            f"实际：{annotation!r}；禁止用 Any 或字符串前向引用绕过类型边界"
        )


def test_planning_phase_no_longer_reads_module_level_client_or_model_name():
    """_run_planning_phase 不允许再隐式引用 module-level client / MODEL_NAME。

    这一条是 Phase 2.2-a 的实质成果钉子：注入 loop_ctx 但函数体仍读
    ``client`` / ``MODEL_NAME`` 等于"形迁移、神不迁移"，依赖注入名存实亡。
    用 source-level 扫描挡住这种伪迁移。
    """

    import inspect

    from agent import core

    src = inspect.getsource(core._run_planning_phase)
    # planner 调用必须从 loop_ctx 取
    assert "loop_ctx.client" in src and "loop_ctx.model_name" in src, (
        "_run_planning_phase 必须从 loop_ctx 读取 client / model_name；"
        "Phase 2.2-a 不允许形式注入而函数体不用"
    )
    # 函数体不允许出现裸 client 或 MODEL_NAME 引用（非 docstring）
    # 简化：扫描 generate_plan 调用行不允许直接出现 ', client,' / ', MODEL_NAME,'
    forbidden_patterns = ("generate_plan(\n        user_input,\n        client",)
    for pat in forbidden_patterns:
        assert pat not in src, (
            f"_run_planning_phase 仍在隐式引用 module-level client：{pat!r}"
        )


def test_chat_passes_loop_ctx_to_planning_helpers_at_all_call_sites():
    """chat()、confirmation context、planning result helper 都必须透传 loop_ctx。

    当前规划相关调用点：
    - chat() 直接调 _run_planning_phase(user_input, turn_state, _loop_ctx)
    - _build_confirmation_context.start_planning_fn lambda 调
      _start_planning_for_handler(inp, ts, loop_ctx)
    - chat() 与 _start_planning_for_handler 都把 plan_result 交给
      _handle_planning_phase_result；该 helper 负责 ok -> _run_main_loop。
    新增 planning 入口必须同步进入同一个 helper，避免两个入口分叉。

    v0.5 第二小步注意：start_planning_fn lambda 已从 chat() 内迁到
    _build_confirmation_context helper 内，参数名也从闭包变量
    ``_loop_ctx`` 变成 helper 形参 ``loop_ctx``——契约本质（透传未污染
    的 LoopContext）未变。
    """

    import inspect

    from agent import core

    chat_src = inspect.getsource(core.chat)
    context_src = inspect.getsource(core._build_confirmation_context)
    handler_src = inspect.getsource(core._start_planning_for_handler)
    result_src = inspect.getsource(core._handle_planning_phase_result)
    assert "_run_planning_phase(user_input, turn_state, _loop_ctx)" in chat_src, (
        "chat() 直接调用 _run_planning_phase 时必须传 _loop_ctx"
    )
    assert "_start_planning_for_handler(" in context_src and "loop_ctx" in context_src, (
        "_build_confirmation_context.start_planning_fn lambda 必须透传 loop_ctx 到"
        " _start_planning_for_handler"
    )
    assert (
        "return _handle_planning_phase_result(plan_result, turn_state, _loop_ctx)"
        in chat_src
    ), "chat() 的 planning result 必须交给共享 helper，禁止复制三分支"
    assert (
        "return _handle_planning_phase_result(plan_result, turn_state, loop_ctx)"
        in handler_src
    ), "_start_planning_for_handler 必须复用共享 helper，禁止复制三分支"
    assert "return _run_main_loop(turn_state, loop_ctx)" in result_src, (
        "_handle_planning_phase_result 的 ok 分支必须透传同一个 loop_ctx 到主循环"
    )


def test_chat_routes_new_turn_compression_through_single_helper():
    """第二刀 helper extraction 只收口 compression + checkpoint sync 时机。

    这个 characterization 保护 Architecture Debt 治理边界：`chat()` 仍决定何时
    进入真正的新一轮对话，helper 只复用同一个 loop_ctx 执行历史压缩与 active
    task checkpoint 同步。它不能顺手改 Ask User、TUI contract、checkpoint
    schema，也不能借机处理 XFAIL-1 topic switch 或 XFAIL-2 Esc cancel。
    """

    import inspect

    from agent import core

    chat_src = inspect.getsource(core.chat)
    helper_src = inspect.getsource(core._compress_history_and_sync_checkpoint)

    assert "_compress_history_and_sync_checkpoint(_loop_ctx)" in chat_src, (
        "chat() 的新一轮对话压缩必须进入共享 helper，避免继续膨胀主入口"
    )
    assert "compress_history(" in helper_src, (
        "_compress_history_and_sync_checkpoint 必须保留历史压缩职责"
    )
    assert "loop_ctx.client" in helper_src, (
        "compression helper 必须复用 chat() 单源构造的 LoopContext client"
    )
    assert "_save_checkpoint(state)" in helper_src, (
        "active task 压缩后必须仍立即同步 checkpoint，避免 summary/checkpoint 漂移"
    )
    forbidden = (
        "request_user_input",
        "pending_user_input_request",
        "plan_confirmation_requested",
        "display_event",
        "Textual",
        "cancel",
        "topic",
    )
    for token in forbidden:
        assert token not in helper_src, (
            "_compress_history_and_sync_checkpoint 不能越界处理 Ask User/TUI/"
            f"XFAIL 语义：{token}"
        )


def test_planning_helpers_do_not_smuggle_durable_state_through_loop_ctx():
    """LoopContext 字段集合保持 runtime-only，禁止承载 durable state。

    Phase 2.2-a 易出的 anti-pattern 是"我顺手把 state 也塞进 LoopContext"
    让 helper 签名变短。这条测试与 Phase 2.1 字段守卫互为冗余：
    Phase 2.1 守 LoopContext 字段名拓扑，本条守"planning helpers 不依赖
    LoopContext 字段集合的扩展"——即使有人偷偷加字段，planning helpers
    也不能读它。
    """

    import inspect

    from agent import core

    for fn_name in (
        "_run_planning_phase",
        "_start_planning_for_handler",
        "_handle_planning_phase_result",
    ):
        src = inspect.getsource(getattr(core, fn_name))
        for forbidden in ("loop_ctx.state", "loop_ctx.task", "loop_ctx.messages",
                          "loop_ctx.checkpoint", "loop_ctx.conversation",
                          "loop_ctx.pending"):
            assert forbidden not in src, (
                f"{fn_name} 不允许通过 loop_ctx 访问 durable state：{forbidden}"
            )


def test_main_loop_signature_phase_2_2_b_handoff_only():
    """_run_main_loop 签名契约（Phase 2.2-b 后）。

    Phase 2.2-a 阶段本测试名为 ``..._unchanged_phase_2_2_a_does_not_overreach``，
    要求签名仅 ``turn_state``。Phase 2.2-b 必须让 ``_run_main_loop`` 显式接受
    ``loop_ctx``，否则 ``_call_model`` 吃 LoopContext 时只能在主循环内重建实例
    （SSOT 双源 hack）。本测试**不是为了通过率而被放宽**——而是把"不应该越界"
    的边界上移到"必须只有 turn_state + loop_ctx，禁止再塞其他参数"：
    - ❌ 不允许加 ``state`` / ``task`` / ``messages`` / ``checkpoint_file`` 参数；
    - ❌ 不允许加 ``client`` / ``model_name`` 直接参数（必须经 loop_ctx）；
    - ❌ 不允许加 ``confirmation_ctx`` / ``response_ctx`` 等聚合容器；
    确保 Phase 2.2-c 之后的越界被同样精确拦截。
    """

    import inspect

    from agent import core
    from agent.loop_context import LoopContext

    sig = inspect.signature(core._run_main_loop)
    params = list(sig.parameters.keys())
    assert params == ["turn_state", "loop_ctx"], (
        f"_run_main_loop 签名必须严格是 (turn_state, loop_ctx)；当前：{params}。"
        "增加任何额外参数都属于范围爬升（durable state 应通过模块级 state "
        "单例访问，runtime dep 应通过 loop_ctx 访问，per-turn 应通过 turn_state 访问）"
    )
    loop_ctx_annotation = sig.parameters["loop_ctx"].annotation
    assert loop_ctx_annotation is LoopContext, (
        f"_run_main_loop.loop_ctx 必须明确标注 LoopContext 类型，"
        f"实际：{loop_ctx_annotation!r}"
    )


def test_loop_context_construction_precedes_confirmation_context_in_chat():
    """chat() 内 _loop_ctx 必须先于 ConfirmationContext 构造。

    因为 ConfirmationContext.start_planning_fn lambda 闭包捕获 _loop_ctx；
    顺序颠倒会触发 NameError。Source-level 扫描钉住相对顺序，避免后续
    refactor 不小心把 _loop_ctx 构造下移。

    v0.5 Phase 3 第一/第二小步：chat() 内构造行从字面 `_loop_ctx = LoopContext(`
    改为 `_loop_ctx = _build_loop_context(client)`，confirmation_ctx 从字面
    `confirmation_ctx = ConfirmationContext(` 改为 `confirmation_ctx =
    _build_confirmation_context(`。本测试随之改为扫描 helper 调用——契约本质
    （必须先构造 _loop_ctx 才能传给 _build_confirmation_context）未变。
    """

    import inspect

    from agent import core

    chat_src = inspect.getsource(core.chat)
    loop_ctx_pos = chat_src.find("_loop_ctx = _build_loop_context(")
    confirm_ctx_pos = chat_src.find("confirmation_ctx = _build_confirmation_context(")
    assert loop_ctx_pos != -1 and confirm_ctx_pos != -1, (
        "chat() 必须同时构造 _loop_ctx（通过 _build_loop_context 工厂）和 "
        "confirmation_ctx（通过 _build_confirmation_context 工厂）"
    )
    assert loop_ctx_pos < confirm_ctx_pos, (
        "_loop_ctx 必须先于 ConfirmationContext 构造（_build_confirmation_context "
        "需要 loop_ctx 作为入参）"
    )


# ========================================================================
# Phase 2.2-b：main-loop -> _call_model LoopContext handoff 边界
# ------------------------------------------------------------------------
# 这一组测试钉死 Phase 2.2-b 的 SSOT 修复契约：
#   1) _call_model 签名包含 loop_ctx 且类型标注必须是 LoopContext；
#   2) _call_model 函数体真正读 loop_ctx.client / loop_ctx.model_name
#      （防形迁移神不迁移）；
#   3) chat() 4 个 _run_main_loop 调用点全部传 _loop_ctx；
#      _start_planning_for_handler 调用点传上层收到的 loop_ctx；
#   4) **_run_main_loop 函数体绝不允许出现 LoopContext(...) 构造调用**
#      ——这是本切片存在的根因，必须用 source-level 扫描钉死；
#   5) chat() 仍然只有一个 _loop_ctx 构造点（agent/core.py 全文 LoopContext(...)
#      只能出现 1 次，加上 loop_context.py 的定义点也只能出现在 LoopContext
#      class 定义本身，不能在任何 helper 内部）；
#   6) _run_main_loop 函数体不允许直接读 loop_ctx 字段——它只转发；
#      Phase 2.2-c 才考虑让主循环自己消费 max_loop_iterations。
# 任何后续切片想"顺手把 max_loop_iterations 也用上 / 顺手在主循环内构造
# LoopContext"都会被第 4/6 条立刻拦下。
# ========================================================================


def test_call_model_signature_accepts_loop_context():
    """_call_model 签名契约。"""

    import inspect

    from agent import core
    from agent.loop_context import LoopContext

    sig = inspect.signature(core._call_model)
    params = list(sig.parameters.keys())
    assert params == ["turn_state", "loop_ctx"], (
        f"_call_model 签名必须严格是 (turn_state, loop_ctx)；当前：{params}。"
        "禁止加 messages / state / system_prompt 参数（前两者属 durable state，"
        "system_prompt 应通过 turn_state 传递）"
    )
    annotation = sig.parameters["loop_ctx"].annotation
    assert annotation is LoopContext, (
        f"_call_model.loop_ctx 必须标注 LoopContext，实际：{annotation!r}"
    )


def test_call_model_no_longer_reads_module_level_client_or_model_name():
    """_call_model 函数体必须从 loop_ctx 读 client / model_name。

    Phase 2.2-b 的实质成果：源码层防"形迁移神不迁移"。
    """

    import inspect

    from agent import core

    src = inspect.getsource(core._call_model)
    assert "loop_ctx.client.messages.stream" in src, (
        "_call_model 必须用 loop_ctx.client 调 stream，"
        "不允许继续用 module-level client"
    )
    assert "model=loop_ctx.model_name" in src, (
        "_call_model stream 调用必须用 loop_ctx.model_name，"
        "不允许继续用 module-level MODEL_NAME"
    )
    # 反向：函数体不应再出现裸 client.messages.stream 或 model=MODEL_NAME
    forbidden_patterns = (
        "with client.messages.stream(",
        "model=MODEL_NAME,",
    )
    for pat in forbidden_patterns:
        assert pat not in src, (
            f"_call_model 仍隐式引用 module-level：{pat!r}"
        )


def test_run_main_loop_does_not_construct_loop_context():
    """_run_main_loop 函数体绝不允许出现 LoopContext(...) 构造调用。

    这是本切片存在的根因——避免 SSOT 双源。如果未来有人偷懒在主循环内
    直接 ``LoopContext(client=..., model_name=...)`` 重建实例，会让 chat()
    层修改 client / model_name 时主循环拿到旧值。本测试用 source-level
    扫描钉死。
    """

    import inspect

    from agent import core

    src = inspect.getsource(core._run_main_loop)
    assert "LoopContext(" not in src, (
        "_run_main_loop 函数体禁止构造 LoopContext；"
        "必须由上层 chat() 单源构造并透传"
    )


def test_chat_remains_unique_loop_context_construction_site_in_core():
    """agent/core.py 全文只能有一个 LoopContext(...) 构造点（在 chat() 内）。

    这条比上一条更广——上一条只防 _run_main_loop；本条防整个 core.py 的
    任何 helper 偷偷构造 LoopContext。Phase 2.2-c 之后任何新增 helper 想
    吃 loop_ctx 都必须从 chat() 透传，不能就地构造。
    """

    import inspect

    from agent import core

    src = inspect.getsource(core)
    construction_count = src.count("LoopContext(")
    assert construction_count == 1, (
        f"agent/core.py 中 LoopContext(...) 构造调用必须恰好 1 次（chat() 内），"
        f"实际：{construction_count} 次。SSOT 单源是 Phase 2.2-b 修复的核心契约"
    )


def test_run_main_loop_consumes_only_max_loop_iterations_from_loop_ctx():
    """_run_main_loop 函数体只允许消费 loop_ctx.max_loop_iterations。

    Phase 2.2-b 阶段本测试名为 ``..._does_not_consume_loop_ctx_fields_directly``，
    要求主循环完全不消费 loop_ctx 字段（只转发）。Phase 2.2-c 让循环兜底次数
    成为 LoopContext 一等公民后，本测试**升级**为精确白名单：
    - ✅ 允许：``loop_ctx.max_loop_iterations``（Phase 2.2-c 消费）；
    - ❌ 禁止：``loop_ctx.client`` / ``loop_ctx.model_name``——这些必须
      只在 ``_call_model`` 边界消费，主循环不得绕过 ``_call_model`` 直接
      触碰 LLM provider 细节。

    本测试**不是为了通过率而被弱化**——拦截能力等价提升：
    - 旧版本可挡住"主循环顺手用任何字段"；
    - 新版本可挡住"主循环顺手用 client/model_name 调 stream"或"主循环
      顺手用 LoopContext 未来新增的任何非 max_loop_iterations 字段"。
    用 AST 跳过 docstring 字符串匹配干扰。
    """

    import ast
    import inspect

    from agent import core

    src = inspect.getsource(core._run_main_loop)
    tree = ast.parse(src)
    func_def = tree.body[0]
    assert isinstance(func_def, ast.FunctionDef)
    body_nodes = func_def.body
    if (
        body_nodes
        and isinstance(body_nodes[0], ast.Expr)
        and isinstance(body_nodes[0].value, ast.Constant)
        and isinstance(body_nodes[0].value.value, str)
    ):
        body_nodes = body_nodes[1:]

    allowed = {"max_loop_iterations"}
    # 显式列出禁用集合作为 docstring/审计参考（client/model_name 必须在
    # _call_model 边界消费）；下面用 "not in allowed" 即可判断 illegal，
    # 因此本变量只起文档作用，不参与判断。
    forbidden = {"client", "model_name"}  # noqa: F841 -- 文档变量，参与 review 阅读
    consumed: list[str] = []
    illegal: list[str] = []
    for node in body_nodes:
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Attribute)
                and isinstance(sub.value, ast.Name)
                and sub.value.id == "loop_ctx"
            ):
                consumed.append(sub.attr)
                if sub.attr not in allowed:
                    illegal.append(sub.attr)
    assert illegal == [], (
        f"_run_main_loop 函数体只允许消费 {allowed}；非法消费：{illegal}。"
        "client / model_name 必须在 _call_model 边界消费，主循环不得绕过"
    )
    assert "max_loop_iterations" in consumed, (
        "Phase 2.2-c 后 _run_main_loop 必须真正消费 loop_ctx.max_loop_iterations，"
        "否则等于形迁移神不迁移（继续读 module-level MAX_LOOP_ITERATIONS）"
    )


def test_chat_passes_loop_ctx_to_main_loop_at_all_call_sites():
    """chat() / _build_confirmation_context / planning result helper 都透传 loop_ctx。

    当前调用点（共 4 处）：
    - _build_confirmation_context.continue_fn lambda：_run_main_loop(ts, loop_ctx)
    - chat() awaiting/running 分支：_run_main_loop(turn_state, _loop_ctx)
    - _handle_planning_phase_result 兜底：_run_main_loop(turn_state, loop_ctx)
      （chat() 新任务与 _start_planning_for_handler 都先进入该 helper）
    任何新增 _run_main_loop 调用点都必须同步加参数。

    v0.5 第二小步注意：原 ConfirmationContext.continue_fn lambda 已从
    chat() 内迁到 _build_confirmation_context helper 内，因此 chat() 内
    的 _run_main_loop 直接调用次数从 3 减为 2，第 3 处出现在 helper 内。
    v0.6.2 后第一刀 helper extraction 再把 planning result 兜底主循环从
    chat()/handler 两处收口到 _handle_planning_phase_result。
    """

    import inspect

    from agent import core

    chat_src = inspect.getsource(core.chat)
    context_src = inspect.getsource(core._build_confirmation_context)
    result_src = inspect.getsource(core._handle_planning_phase_result)

    # chat() 仍保留 awaiting/running 分支的直接调用；新任务兜底由 helper 接管。
    chat_call_count = chat_src.count("_run_main_loop(")
    assert chat_call_count >= 1, (
        f"chat() 至少应有 1 处直接 _run_main_loop 调用，实际：{chat_call_count}"
    )
    # _build_confirmation_context helper 必须有 1 处（continue_fn lambda）
    assert context_src.count("_run_main_loop(") >= 1, (
        "_build_confirmation_context.continue_fn lambda 必须调用 _run_main_loop"
    )
    # chat() 中所有 _run_main_loop 调用都必须传 _loop_ctx
    assert chat_src.count("_loop_ctx") >= chat_src.count("_run_main_loop("), (
        "chat() 中所有 _run_main_loop 调用都必须传 _loop_ctx"
    )
    # helper 中 _run_main_loop 调用必须传 loop_ctx 形参
    assert "loop_ctx" in context_src, (
        "_build_confirmation_context 必须把 loop_ctx 透传给 _run_main_loop lambda"
    )

    # planning result helper 应有 1 处调用并传 loop_ctx。
    assert "_run_main_loop(turn_state, loop_ctx)" in result_src, (
        "_handle_planning_phase_result 调用 _run_main_loop 必须传上层 loop_ctx"
    )


# ========================================================================
# Phase 2.2-c：MAX_LOOP_ITERATIONS 通过 LoopContext 注入
# ------------------------------------------------------------------------
# 这一组测试钉死 Phase 2.2-c 的契约：循环兜底次数从模块级常量隐式引用
# 升级为 LoopContext 一等公民，由 chat() 单源构造、_run_main_loop 显式消费。
#
# 设计选择：
# - 模块级 MAX_LOOP_ITERATIONS = 50 **保留**作为默认值来源——chat() 构造
#   LoopContext 时引用它，运行时实际读取走 loop_ctx.max_loop_iterations；
# - 现有 from agent.core import MAX_LOOP_ITERATIONS 测试导入仍可用
#   （test_bug_hunting / test_runtime_error_recovery 等），向后兼容；
# - 主循环函数体禁止再裸引用 MAX_LOOP_ITERATIONS：必须强制走 loop_ctx，
#   否则迁移名存实亡（chat() 改 LoopContext.max_loop_iterations 时主循环
#   仍走 50）。
# ========================================================================


def test_run_main_loop_no_longer_reads_module_level_max_loop_iterations():
    """_run_main_loop 函数体禁止裸引用 MAX_LOOP_ITERATIONS。

    Phase 2.2-c 的实质成果：循环上限的真值来源**只**通过 loop_ctx，
    模块级常量退化为"chat() 构造 LoopContext 时使用的默认值"。如果主循环
    仍读 MAX_LOOP_ITERATIONS，等于双源——chat() 改 loop_ctx.max_loop_iterations
    时主循环仍按 module-level 50 跑。

    用 AST 检查跳过 docstring 干扰（docstring 会用文本提到该常量名作为
    "不应做的事"的说明）。只查实际 ast.Name 引用。
    """

    import ast
    import inspect

    from agent import core

    src = inspect.getsource(core._run_main_loop)
    tree = ast.parse(src)
    func_def = tree.body[0]
    assert isinstance(func_def, ast.FunctionDef)
    body_nodes = func_def.body
    if (
        body_nodes
        and isinstance(body_nodes[0], ast.Expr)
        and isinstance(body_nodes[0].value, ast.Constant)
        and isinstance(body_nodes[0].value.value, str)
    ):
        body_nodes = body_nodes[1:]

    bad: list[ast.AST] = []
    for node in body_nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id == "MAX_LOOP_ITERATIONS":
                bad.append(sub)
    assert not bad, (
        "_run_main_loop 函数体禁止裸引用 MAX_LOOP_ITERATIONS；"
        "Phase 2.2-c 后必须通过 loop_ctx.max_loop_iterations 访问"
    )


def test_module_level_max_loop_iterations_still_exported_for_chat_default():
    """模块级 MAX_LOOP_ITERATIONS 必须保留为 chat() LoopContext 默认值来源。

    这是向后兼容契约：现有测试（test_bug_hunting / test_runtime_error_recovery）
    依赖 ``from agent.core import MAX_LOOP_ITERATIONS`` 拿默认值用作上限计算
    或健康检查 (== 50)。如果 Phase 2.2-c 顺手把这个常量删掉，会破坏这些测试。
    保留常量也让 chat() 构造 LoopContext 时有显式默认值来源。
    """

    from agent import core

    assert hasattr(core, "MAX_LOOP_ITERATIONS"), (
        "agent/core.py 必须保留 MAX_LOOP_ITERATIONS 模块级常量作为 LoopContext "
        "默认值来源；删除会破坏 test_bug_hunting / test_runtime_error_recovery"
    )
    assert isinstance(core.MAX_LOOP_ITERATIONS, int), (
        "MAX_LOOP_ITERATIONS 必须是 int（chat() 直接传给 LoopContext 构造）"
    )
    assert core.MAX_LOOP_ITERATIONS > 0, (
        "MAX_LOOP_ITERATIONS 必须正（LoopContext.__post_init__ 也会校验）"
    )


def test_chat_loop_context_max_loop_iterations_equals_module_default():
    """LoopContext 构造点 max_loop_iterations 必须等于模块级常量。

    防止有人 Phase 2.2-c 后偷偷把构造改成硬编码 ``max_loop_iterations=100``，
    那样 module-level 常量就成了"看起来是默认值但 runtime 不用"的死代码——
    比单源更糟糕（视觉默认值与实际默认值不一致）。

    v0.5 Phase 3 第一小步：构造点从 chat() 内字面调用搬到
    _build_loop_context() helper，本测试随之扫描 helper src——
    契约本质（默认值必须是模块常量）未变。
    """

    import inspect

    from agent import core

    helper_src = inspect.getsource(core._build_loop_context)
    assert (
        "max_loop_iterations=MAX_LOOP_ITERATIONS" in helper_src
        or "max_loop_iterations: int = MAX_LOOP_ITERATIONS" in helper_src
    ), (
        "_build_loop_context 默认 max_loop_iterations 必须取自模块常量 "
        "MAX_LOOP_ITERATIONS（保持视觉与运行时真值一致）"
    )


# ============================================================================
# Phase 2.3：handler dependency boundary guard（AST 级，非脆弱字符串扫描）
# ----------------------------------------------------------------------------
# 这一节只做一件事：用 ast 解析 agent/confirm_handlers.py，确认它没有
# 直接 import 或实例化 LoopContext。换句话说，confirm_handlers 必须保持
# 对 LoopContext 类型零知识，runtime dependency 只通过 ConfirmationContext
# 注入的 callable（continue_fn / start_planning_fn）以闭包方式间接消费。
#
# 为什么不用 source.count("LoopContext") == 0：
#   - 字符串扫描会被 docstring / 注释中合理引用 LoopContext 的中文学习型
#     注释误伤；架构注释本身是有价值的，不应被测试钉死；
#   - 字符串扫描也分不清"import 一次类型用于注解"与"在 handler 体内构造一个
#     新 LoopContext 重建 SSOT"——前者其实是危险的（暗示直接耦合），后者
#     是绝对禁止的——但本测试通过 AST 区分得很清楚。
#
# 为什么 confirm_handlers 必须对 LoopContext 零知识：
#   - SSOT：LoopContext 唯一构造点是 chat()（已被
#     test_chat_remains_unique_loop_context_construction_site_in_core 钉死）；
#   - handler 一旦自己 import LoopContext，就有可能在某条分支里"为了图方便"
#     重新构造一个对象，使得 monkeypatch / DI / 测试 fixture 注入的真值源
#     被绕过——这正是 v0.4 Phase 2 整个迁移要消除的隐患；
#   - handler 的运行时依赖应该是「函数引用」(callable boundary)，不是
#     「数据容器对象」。函数引用天然单源、天然可重写、天然不会被反序列化
#     "拷贝"。
#
# 这条测试不禁止什么（避免变成实现细节冻结）：
#   - 不禁止 confirm_handlers 中的中文 docstring / 注释提到 LoopContext；
#   - 不禁止未来给 handler 函数加除 LoopContext 之外的其它类型 hint；
#   - 不禁止合理 helper 抽取、函数改名、参数顺序调整；
#   - 不禁止测试文件构造 LoopContext（test fixture 当然可以）；
#   - 不禁止 core.py / loop_context.py 内部正常引用 LoopContext。
#
# 触发 bug 场景（这条测试能发现的真实回退）：
#   - 未来有人把 ConfirmationContext.client/model_name 改成
#     ConfirmationContext.loop_ctx，并顺手在 confirm_handlers 顶部
#     `from agent.loop_context import LoopContext`：本测试立刻报警；
#   - 未来有人在 handle_feedback_intent_choice 里"为了在没有
#     start_planning_fn 时降级补救"而 `LoopContext(client=..., model_name=...)`
#     重新构造：本测试立刻报警，强制走"先注入再使用"的边界。
# ============================================================================


def test_confirm_handlers_must_not_import_or_construct_loop_context():
    """AST 级守卫：agent/confirm_handlers.py 不得 import 或实例化 LoopContext。

    通过 ast.parse 精确区分 import 和 call，避免字符串扫描对 docstring 的
    误伤。保护的架构边界：runtime dependency 只通过 callable boundary 注入，
    不通过 handler 直接持有 LoopContext 引用。

    注：本测试不禁止 confirm_handlers 在注释/docstring 中提到 LoopContext
    名字（架构说明本身是有价值的）。
    """

    import ast
    import inspect

    from agent import confirm_handlers

    src = inspect.getsource(confirm_handlers)
    tree = ast.parse(src)

    bad_imports: list[str] = []
    bad_calls: list[str] = []

    for node in ast.walk(tree):
        # 1) 禁止 `from agent.loop_context import LoopContext`
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.endswith("loop_context") or mod == "agent.loop_context":
                for alias in node.names:
                    if alias.name == "LoopContext":
                        bad_imports.append(
                            f"from {mod} import {alias.name} (line {node.lineno})"
                        )
        # 2) 禁止 `import agent.loop_context` 形式（哪怕未直接用 LoopContext，
        #    也意味着 handler 知道这个模块的存在——这本身就是耦合泄漏）
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "loop_context" in alias.name:
                    bad_imports.append(
                        f"import {alias.name} (line {node.lineno})"
                    )
        # 3) 禁止任何 `LoopContext(...)` 字面构造（无论是否经 import）
        if isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name == "LoopContext":
                bad_calls.append(f"LoopContext(...) at line {node.lineno}")

    assert not bad_imports, (
        "confirm_handlers.py 不得 import LoopContext——runtime dependency 必须"
        f"通过 callable boundary 注入：{bad_imports}"
    )
    assert not bad_calls, (
        "confirm_handlers.py 不得调用 LoopContext(...)——SSOT 唯一构造点是 "
        f"agent/core.py:chat()：{bad_calls}"
    )


# ============================================================
# v0.5 Phase 3 第一小步 · _build_loop_context 工厂边界守卫
# ============================================================


def test_build_loop_context_returns_loop_context_with_expected_fields():
    """_build_loop_context() 必须返回 LoopContext 且 3 字段语义不变。

    防回归契约：v0.5 Phase 3 第一小步把字面 LoopContext(...) 调用抽到
    helper 工厂。helper 必须满足：
      - 返回类型是 LoopContext（不是 dict / SimpleNamespace 等替身）；
      - client 直接透传（不做 wrap）；
      - 默认 model_name 等于模块常量 MODEL_NAME；
      - 默认 max_loop_iterations 等于模块常量 MAX_LOOP_ITERATIONS；
      - 不偷偷加额外字段（messages / task / plan / pending_tool 等
        durable state 永不混进 LoopContext）。

    这条测试**不**依赖 LoopContext 内部字段顺序或私有实现，仅断言公共
    契约——属"行为中性 helper"应该被钉住的最小契约。
    """
    from agent import core
    from agent.core import _build_loop_context, MAX_LOOP_ITERATIONS, MODEL_NAME
    from agent.loop_context import LoopContext

    sentinel_client = object()
    ctx = _build_loop_context(sentinel_client)

    assert isinstance(ctx, LoopContext)
    assert ctx.client is sentinel_client
    assert ctx.model_name == MODEL_NAME
    assert ctx.max_loop_iterations == MAX_LOOP_ITERATIONS

    # LoopContext 字段集必须仍然只有 3 个 runtime dependency；
    # 任何 durable state 名（messages / task / plan / pending_tool 等）
    # 都不允许出现在 dataclass 字段中（防"helper 顺手把状态塞进去"）。
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(ctx)}
    forbidden = {
        "messages", "task", "plan", "current_step_index",
        "pending_tool", "pending_user_input_request",
        "working_summary", "checkpoint_data", "tool_traces",
    }
    assert not (field_names & forbidden), (
        f"LoopContext 字段被污染——出现 durable state 名 "
        f"{field_names & forbidden}；LoopContext 必须严格只装 runtime "
        "dependency（client / model_name / max_loop_iterations）。"
    )

    # 同时复用 core 模块名空间避免 unused import 警告
    assert hasattr(core, "_build_loop_context")


def test_build_loop_context_kwargs_override_defaults_without_module_mutation():
    """helper 接收 kwarg override 时，模块常量保持不变（无副作用）。

    这条防止有人未来"偷懒"用全局可变状态实现 override（例如改写
    agent.core.MODEL_NAME）。helper 必须是纯函数：override 走 kwarg，
    不改任何模块级状态。
    """
    from agent import core
    from agent.core import _build_loop_context

    before_model = core.MODEL_NAME
    before_max = core.MAX_LOOP_ITERATIONS

    ctx = _build_loop_context(
        object(), model_name="override-model", max_loop_iterations=999
    )
    assert ctx.model_name == "override-model"
    assert ctx.max_loop_iterations == 999

    # 模块常量必须未被 helper 改写
    assert core.MODEL_NAME == before_model
    assert core.MAX_LOOP_ITERATIONS == before_max


# ============================================================
# v0.5 Phase 3 第二小步 · _build_confirmation_context 工厂边界守卫
# ============================================================


def test_build_confirmation_context_returns_confirmation_context_with_expected_fields():
    """_build_confirmation_context() 必须返回 ConfirmationContext 且字段语义正确。

    防回归契约：v0.5 第二小步把字面 ConfirmationContext(...) 抽到 helper。
    helper 必须满足：
      - 返回类型是 ConfirmationContext（不是替身 dict / Namespace）；
      - state / turn_state 直接透传（不做 wrap）；
      - client / model_name 取自 loop_ctx（与 v0.4 Phase 2.2-b 让 _call_model
        走 loop_ctx 的方向一致）；
      - continue_fn 是 callable，调用时把 ts 转给主循环；
      - start_planning_fn 是 callable，调用时把 inp/ts 转给 planning helper；
      - 不偷偷加额外字段（messages / task / plan / current_step_index 等
        durable state 永不混进 ConfirmationContext）。

    测试用真实 LoopContext + sentinel state/turn_state，验证字段绑定，
    不实际触发主循环（避免引入测试副作用）。
    """
    from agent import core
    from agent.core import _build_confirmation_context, _build_loop_context
    from agent.confirm_handlers import ConfirmationContext

    sentinel_client = object()
    sentinel_state = object()
    sentinel_turn_state = object()
    loop_ctx = _build_loop_context(
        sentinel_client, model_name="test-model", max_loop_iterations=7
    )

    ctx = _build_confirmation_context(
        state=sentinel_state, turn_state=sentinel_turn_state, loop_ctx=loop_ctx
    )

    assert isinstance(ctx, ConfirmationContext)
    assert ctx.state is sentinel_state
    assert ctx.turn_state is sentinel_turn_state
    assert ctx.client is sentinel_client, (
        "client 必须从 loop_ctx 透传（与 _call_model 走 loop_ctx 方向一致）"
    )
    assert ctx.model_name == "test-model", (
        "model_name 必须从 loop_ctx 透传"
    )
    assert callable(ctx.continue_fn), "continue_fn 必须是 callable"
    assert callable(ctx.start_planning_fn), "start_planning_fn 必须是 callable"

    # ConfirmationContext 字段集严格对齐：禁止 helper 顺手把 durable state
    # （messages / task / plan / pending_*）塞进 ConfirmationContext。
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(ctx)}
    forbidden = {
        "messages", "task", "plan", "current_step_index",
        "pending_tool", "pending_user_input_request",
        "working_summary", "checkpoint_data", "tool_traces",
    }
    assert not (field_names & forbidden), (
        f"ConfirmationContext 字段被污染——出现 durable state 名 "
        f"{field_names & forbidden}；ConfirmationContext 必须严格只装 handler "
        "dependency（state/turn_state/client/model_name/continue_fn/start_planning_fn）。"
    )

    # 用 core 模块名空间避免 unused import
    assert hasattr(core, "_build_confirmation_context")


def test_chat_remains_unique_confirmation_context_construction_site_in_core():
    """agent/core.py 全文只能有一个 ConfirmationContext(...) 字面构造点
    （在 _build_confirmation_context helper 内）。

    与 LoopContext SSOT 测试同模式：防止 chat() 之外的任何 helper 偷偷
    重建 ConfirmationContext，绕过 helper 工厂。
    """
    import inspect

    from agent import core

    src = inspect.getsource(core)
    construction_count = src.count("ConfirmationContext(")
    assert construction_count == 1, (
        f"agent/core.py 中 ConfirmationContext(...) 字面构造调用必须恰好 1 次"
        f"（在 _build_confirmation_context helper 内），实际：{construction_count} 次。"
        "SSOT 单源是 v0.5 第二小步的核心契约"
    )

    # 同时检查 chat() 通过 helper 调用（不绕过 SSOT）
    chat_src = inspect.getsource(core.chat)
    assert "_build_confirmation_context(" in chat_src, (
        "chat() 必须通过 _build_confirmation_context(...) 工厂构造 ConfirmationContext"
    )


def test_build_confirmation_context_lambdas_capture_loop_ctx_not_rebuild():
    """helper 内 continue_fn / start_planning_fn lambda 必须闭包捕获
    传入的 loop_ctx，而不是在 lambda 体里重建 LoopContext。

    防止有人未来"为了灵活性"把 lambda 改成 ``lambda ts: _run_main_loop(
    ts, _build_loop_context(client))`` 之类的写法——那会破坏 SSOT
    （每次 lambda 调用产生一个新 LoopContext），也会破坏 monkeypatch 行为。

    本测试用 AST 解析 helper 体，断言 lambda 内不包含对 _build_loop_context
    或 LoopContext 的调用。
    """
    import ast
    import inspect

    from agent import core

    src = inspect.getsource(core._build_confirmation_context)
    tree = ast.parse(src)
    func_def = tree.body[0]
    assert isinstance(func_def, ast.FunctionDef)

    forbidden_names = {"_build_loop_context", "LoopContext"}
    bad_calls: list[str] = []
    for node in ast.walk(func_def):
        if isinstance(node, ast.Lambda):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    func = sub.func
                    if isinstance(func, ast.Name) and func.id in forbidden_names:
                        bad_calls.append(func.id)
    assert not bad_calls, (
        f"_build_confirmation_context 的 lambda 内禁止调用 "
        f"{forbidden_names}——必须闭包捕获传入的 loop_ctx，不得重建。"
        f"实际发现：{bad_calls}"
    )
