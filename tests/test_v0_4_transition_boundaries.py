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

    outcomes = {
        kind: tool_result_transition(kind)
        for kind in ToolResultTransitionKind
    }

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
        assert outcome.clear_pending_tool is True
        assert outcome.advance_step is False
        assert outcome.clear_pending_user_input is False


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
