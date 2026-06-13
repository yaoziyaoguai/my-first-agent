"""GE-1 Phase C: policy rejection 与 evidence trace Golden E2E。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

FIXTURE_DIR = Path(__file__).with_name("fixtures")


def _assert_golden(name: str, actual: dict) -> None:
    path = FIXTURE_DIR / name
    assert path.is_file(), f"missing golden fixture: {path}"
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert actual == expected


def _run_skill_policy_rejection(monkeypatch: pytest.MonkeyPatch):
    import agent.tool_runtime_mediator as mediator_module
    from agent import logger
    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
    from agent.state import create_agent_state
    from agent.tool_runtime_mediator import ToolRuntimeMediator

    monkeypatch.setattr(logger, "log_event", lambda *args, **kwargs: None)

    def _must_not_execute(*args, **kwargs):
        raise AssertionError("policy-rejected tool must not execute")

    monkeypatch.setattr(mediator_module, "execute_single_tool", _must_not_execute)

    state = create_agent_state(system_prompt="golden-policy")
    state.task.status = "running"
    dispatcher = build_phase1_dispatcher()
    messages: list[dict] = []
    mediator = ToolRuntimeMediator(
        dispatcher,
        state=state,
        turn_state=SimpleNamespace(on_display_event=None, round_tool_traces=[]),
        turn_context={},
        messages=messages,
        skill_allowed_tools=frozenset({"demo.write_demo_note"}),
    )
    block = SimpleNamespace(
        name="demo.echo_task_summary",
        input={"marker": "golden-input-must-not-enter-evidence"},
        id="ge1-policy-blocked",
    )
    result = mediator.mediate(block)
    return dispatcher, state, messages, result


def test_ge1_b3_policy_rejection_emits_evidence_without_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不在 active skill allowlist 的工具被拒绝，且不进入执行阶段。"""
    from agent.runtime_integration.schema import RuntimeActionType
    from agent.tool_executor import FORCE_STOP

    dispatcher, state, messages, result = _run_skill_policy_rejection(monkeypatch)
    gate_events = [
        event
        for event in dispatcher.action_log
        if event.action_type == RuntimeActionType.TOOL_GATE
    ]
    invoke_events = [
        event
        for event in dispatcher.action_log
        if event.action_type == RuntimeActionType.TOOL_INVOKE
    ]
    gate_event = gate_events[-1]

    actual = {
        "mediator_result": result,
        "force_stop": FORCE_STOP,
        "gate_event": {
            "action_type": str(gate_event.action_type),
            "status": gate_event.status,
            "decision": gate_event.evidence.get("decision"),
            "policy_path": gate_event.evidence.get("policy_path"),
            "execution_suppressed": gate_event.evidence.get("execution_suppressed"),
        },
        "tool_invoke_event_count": len(invoke_events),
        "execution_log_status": state.task.tool_execution_log[
            "ge1-policy-blocked"
        ]["status"],
        "tool_result_message_count": len(messages),
        "tool_result_message": {
            "type": messages[0]["content"][0]["type"],
            "has_policy_reason": "tool not in active skill allowed_tools"
            in messages[0]["content"][0]["content"],
            "raw_input_marker_present": "golden-input-must-not-enter-evidence"
            in messages[0]["content"][0]["content"],
        },
    }
    _assert_golden("policy_rejected.json", actual)


def test_ge1_b4_runtime_action_event_reconstructs_safe_evidence_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """action_log 可投影为 JSON-safe trace，且不持久化原始 tool input。"""
    from agent.runtime_integration.schema import RuntimeActionType

    dispatcher, _, _, _ = _run_skill_policy_rejection(monkeypatch)

    class _Sink:
        def __init__(self) -> None:
            self.events: list[dict] = []

        def append(self, event: dict) -> None:
            self.events.append(event)

    sink = _Sink()
    flushed = dispatcher.flush_to_event_log(sink)
    events_by_type = {event["action_type"]: event for event in sink.events}
    gate_trace = events_by_type[RuntimeActionType.TOOL_GATE.value]
    tool_result_trace = events_by_type[RuntimeActionType.TOOL_RESULT.value]
    required_event_fields = (
        "event_id",
        "action_id",
        "action_type",
        "source",
        "status",
        "evidence",
        "parent_trace_id",
        "timestamp",
    )
    serialized = json.dumps(sink.events, ensure_ascii=False, sort_keys=True)

    actual = {
        "trace_kind": "direct_dispatcher_policy_receipt",
        "flushed_event_count": flushed,
        "event_types": [event["action_type"] for event in sink.events],
        "all_events_have_required_fields": all(
            all(key in event for key in required_event_fields)
            for event in sink.events
        ),
        "gate_trace": {
            "action_type": gate_trace["action_type"],
            "status": gate_trace["status"],
            "handler_name": gate_trace["evidence"].get("handler_name"),
            "evidence_level": gate_trace["evidence"].get("evidence_level"),
            "execution_suppressed": gate_trace["evidence"].get(
                "execution_suppressed"
            ),
        },
        "tool_result_trace": {
            "action_type": tool_result_trace["action_type"],
            "status": tool_result_trace["status"],
            "handler_name": tool_result_trace["evidence"].get("handler_name"),
            "evidence_level": tool_result_trace["evidence"].get("evidence_level"),
            "disposition": tool_result_trace["evidence"].get("disposition"),
            "execution_status": tool_result_trace["evidence"].get(
                "execution_status"
            ),
            "no_tool_invocation": tool_result_trace["evidence"].get(
                "no_tool_invocation"
            ),
            "external_side_effects": tool_result_trace["evidence"].get(
                "external_side_effects"
            ),
            "read_only_operation": tool_result_trace["evidence"].get(
                "read_only_operation"
            ),
            "no_memory_side_effects": tool_result_trace["evidence"].get(
                "no_memory_side_effects"
            ),
            "result_original_size": tool_result_trace["evidence"].get(
                "result_original_size"
            ),
            "result_was_redacted": tool_result_trace["evidence"].get(
                "result_was_redacted"
            ),
            "result_was_truncated": tool_result_trace["evidence"].get(
                "result_was_truncated"
            ),
        },
        "raw_input_marker_persisted": "golden-input-must-not-enter-evidence"
        in serialized,
        "claims_real_provider_e2e": False,
    }
    _assert_golden("evidence_trace.json", actual)
