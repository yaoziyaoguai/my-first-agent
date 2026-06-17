from __future__ import annotations

from agent.conversation_events import append_tool_result
from agent.state import create_agent_state
from agent.task_context import build_task_execution_context
from agent.task_tool_contract import (
    build_governed_tool_contract_report,
    record_tool_contract_evidence,
)


def _state_with_tool_logs():
    state = create_agent_state(system_prompt="test")
    state.task.status = "running"
    state.task.current_step_index = 0
    state.task.current_plan = {
        "goal": "repo-governed improvement task",
        "steps": [
            {
                "step_id": "step-1",
                "title": "inspect",
                "description": "inspect files",
                "step_type": "read",
            }
        ],
    }
    state.task.tool_execution_log = {
        "toolu_read": {
            "tool": "read_file",
            "input": {"path": "README.md"},
            "result": "ok",
            "status": "executed",
            "step_index": 0,
        },
        "toolu_blocked": {
            "tool": "write_file",
            "input": {"path": "/etc/passwd"},
            "result": "blocked",
            "status": "blocked_by_policy",
            "step_index": 0,
        },
        "meta_step": {
            "tool": "mark_step_complete",
            "input": {"completion_score": 90},
            "result": "",
            "status": "meta_recorded",
            "step_index": 0,
        },
    }
    append_tool_result(state.conversation.messages, "toolu_read", "ok")
    append_tool_result(state.conversation.messages, "toolu_blocked", "blocked")
    return state


def test_governed_tool_contract_report_summarizes_tool_decisions():
    state = _state_with_tool_logs()
    package = build_task_execution_context(state)

    report = build_governed_tool_contract_report(
        state,
        context_package=package,
    )

    assert report.audit_ready is True
    assert report.attempted_count == 3
    assert report.executed_count == 1
    assert report.blocked_count == 1
    assert report.meta_count == 1
    assert report.contract_violations == ()
    decisions = {call.tool_use_id: call.policy_decision for call in report.calls}
    assert decisions == {
        "toolu_read": "allowed",
        "toolu_blocked": "rejected",
        "meta_step": "control",
    }


def test_governed_tool_contract_flags_bypass_shaped_log_entries():
    state = create_agent_state(system_prompt="test")
    state.task.status = "running"
    state.task.current_plan = {
        "goal": "g",
        "steps": [{"step_id": "s1", "title": "s", "description": "d", "step_type": "read"}],
    }
    state.task.tool_execution_log = {
        "toolu_unknown": {
            "tool": "mystery_tool",
            "status": "mystery",
            "step_index": 0,
        }
    }

    report = build_governed_tool_contract_report(state)

    assert report.audit_ready is False
    assert report.provider_callable is True
    assert report.contract_violations == (
        "toolu_unknown: unknown tool status 'mystery'",
        "toolu_unknown: non-meta tool missing result",
    )


def test_tool_contract_evidence_is_safe_summary_only():
    state = _state_with_tool_logs()
    report = build_governed_tool_contract_report(state)
    calls: list[dict] = []

    def fake_record_evidence(**kwargs):
        calls.append(kwargs)
        return kwargs

    envelope = record_tool_contract_evidence(
        report,
        record_evidence_fn=fake_record_evidence,
    )

    assert envelope["subsystem"] == "tool"
    assert envelope["operation"] == "task_tool_contract.summary"
    assert envelope["status"] == "ok"
    assert envelope["content_persisted"] is False
    assert envelope["metadata"]["attempted_count"] == 3
    assert envelope["metadata"]["executed_count"] == 1
    assert envelope["metadata"]["blocked_count"] == 1
    assert "README.md" not in str(envelope)
    assert calls == [envelope]
