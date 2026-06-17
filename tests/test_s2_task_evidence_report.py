from __future__ import annotations

from agent.state import create_agent_state
from agent.task_evidence_report import (
    build_task_evidence_report,
    record_task_evidence_report,
)
from config import STEP_COMPLETION_THRESHOLD


def _plan() -> dict:
    return {
        "goal": "repo-governed improvement task",
        "thinking": "inspect, patch, verify",
        "steps": [
            {
                "step_id": "s1",
                "title": "inspect",
                "description": "inspect docs and code",
                "step_type": "read",
            },
        ],
    }


def _state_with_tool_evidence():
    state = create_agent_state(system_prompt="test")
    state.memory.session_id = "s2-evidence-session"
    state.task.status = "running"
    state.task.user_goal = "repair one S2 gap"
    state.task.current_plan = _plan()
    state.task.tool_execution_log = {
        "tool-read": {
            "tool": "read_file",
            "status": "executed",
            "input": {"path": "docs/current/S2_GOAL_GAP.md"},
            "result": "raw tool output that should not be persisted in evidence",
            "step_index": 0,
        },
        "meta-complete": {
            "tool": "mark_step_complete",
            "status": "meta_recorded",
            "input": {
                "completion_score": STEP_COMPLETION_THRESHOLD,
                "summary": "inspected",
                "outstanding": "none",
            },
            "step_index": 0,
        },
    }
    state.conversation.messages = [
        {"role": "user", "content": "raw user request should not be in report"},
        {"role": "assistant", "content": "raw model answer should not be in report"},
    ]
    return state


def test_task_evidence_report_is_replay_ready_without_full_body_persistence():
    report = build_task_evidence_report(_state_with_tool_evidence())

    assert report.replay_ready is True
    assert report.provider_callable is True
    assert report.tool_attempted_count == 2
    assert report.tool_executed_count == 1
    assert report.lifecycle == "running"
    assert "TD-001" in report.known_debt_refs
    assert "raw tool output" not in str(report)
    assert "raw model answer" not in str(report)
    assert "task.progress:1/1" in report.evidence_events
    assert "tools.executed:1" in report.evidence_events


def test_task_evidence_report_tracks_td004_when_blocked_tool_exists():
    state = _state_with_tool_evidence()
    state.task.tool_execution_log["tool-blocked"] = {
        "tool": "write_file",
        "status": "blocked_by_policy",
        "input": {"path": "unsafe"},
        "result": "blocked before write",
        "step_index": 0,
    }

    report = build_task_evidence_report(state)

    assert "TD-004" in report.known_debt_refs
    assert report.tool_blocked_count == 1


def test_task_evidence_report_records_safe_metadata_only():
    calls: list[dict] = []

    def fake_record_evidence(**kwargs):
        calls.append(kwargs)
        return kwargs

    report = build_task_evidence_report(_state_with_tool_evidence())
    envelope = record_task_evidence_report(
        report,
        record_evidence_fn=fake_record_evidence,
    )

    assert envelope["status"] == "ok"
    assert envelope["content_persisted"] is False
    assert envelope["metadata"]["replay_ready"] is True
    assert envelope["metadata"]["known_debt_refs"] == ["TD-001"]
    assert "raw tool output" not in str(envelope)
    assert "raw user request" not in str(envelope)
    assert calls == [envelope]
