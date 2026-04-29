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
    """chat() 已构造一次 LoopContext 实例作为 Phase 2.2/2.3 注入锚点。

    本切片不要求实例被传给 helper（Phase 2.2/2.3 才迁移）；仅验证
    构造调用确实存在，且字段从模块级 client / MODEL_NAME /
    MAX_LOOP_ITERATIONS 取值——这样后续 sub-slice 把 helper 改吃
    loop_ctx 时，调用点不需要再加构造代码。
    """

    import inspect

    from agent import core

    src = inspect.getsource(core.chat)
    assert "LoopContext(" in src, (
        "chat() 必须显式构造 LoopContext 作为 Phase 2.2/2.3 注入锚点"
    )
    assert "client=client" in src and "model_name=MODEL_NAME" in src and (
        "max_loop_iterations=MAX_LOOP_ITERATIONS" in src
    ), "LoopContext 必须从模块级运行时常量取值，避免引入新的隐式默认值"
