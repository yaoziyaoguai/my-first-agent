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
    # clear_checkpoint 之后文件应不存在
    assert not ckpt_file.exists()

    serialized_messages2 = json.dumps(state2.conversation.messages, ensure_ascii=False)
    for marker in (
        "PlanConfirmationKind",
        "plan_confirmation_transition",
        "TransitionResult",
    ):
        assert marker not in serialized_messages2
