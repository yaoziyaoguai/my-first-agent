from __future__ import annotations

from agent.state import create_agent_state
from agent.task_review import (
    HumanTakeoverAction,
    build_task_progress_review,
    parse_human_takeover_decision,
    record_task_progress_review_evidence,
)


def _plan() -> dict:
    return {
        "goal": "repo-governed improvement task",
        "steps": [
            {"step_id": "s1", "title": "inspect", "description": "d", "step_type": "read"},
            {"step_id": "s2", "title": "patch", "description": "d", "step_type": "edit"},
        ],
    }


def test_progress_review_exposes_current_step_and_blocking_reason():
    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_tool_confirmation"
    state.task.current_plan = _plan()
    state.task.current_step_index = 1
    state.task.pending_tool = {
        "tool_use_id": "toolu_write",
        "tool": "write_file",
        "input": {"path": "x"},
    }
    state.task.tool_execution_log = {
        "toolu_read": {
            "tool": "read_file",
            "input": {"path": "README.md"},
            "result": "ok",
            "status": "executed",
            "step_index": 0,
        }
    }

    review = build_task_progress_review(state)

    assert review.lifecycle == "waiting"
    assert review.progress_percent == 50.0
    assert review.completed_steps == 1
    assert review.total_steps == 2
    assert review.current_step_index == 1
    assert review.current_step_title == "patch"
    assert review.blocking_reason == "tool_confirmation:write_file"
    assert review.tool_attempted_count == 1
    assert review.takeover_available is True
    assert "Blocking reason: tool_confirmation:write_file" in review.review_text


def test_human_takeover_decision_is_structured_and_side_effect_free():
    state = create_agent_state(system_prompt="test")
    state.task.status = "running"
    state.task.current_plan = _plan()
    review = build_task_progress_review(state)

    continue_decision = parse_human_takeover_decision("continue", review=review)
    assert continue_decision.action is HumanTakeoverAction.CONTINUE
    assert continue_decision.allowed is True

    takeover_decision = parse_human_takeover_decision("takeover", review=review)
    assert takeover_decision.action is HumanTakeoverAction.TAKEOVER
    assert takeover_decision.allowed is False
    assert state.task.status == "running"

    stop_decision = parse_human_takeover_decision("stop", review=review)
    assert stop_decision.action is HumanTakeoverAction.STOP
    assert stop_decision.allowed is True
    assert state.task.status == "running"


def test_progress_review_evidence_is_safe_summary_only():
    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_user_input"
    state.task.current_plan = _plan()
    state.task.pending_user_input_request = {
        "awaiting_kind": "request_user_input",
        "question": "secret project detail?",
    }
    review = build_task_progress_review(state)
    calls: list[dict] = []

    def fake_record_evidence(**kwargs):
        calls.append(kwargs)
        return kwargs

    envelope = record_task_progress_review_evidence(
        review,
        record_evidence_fn=fake_record_evidence,
    )

    assert envelope["subsystem"] == "task"
    assert envelope["operation"] == "task_progress.review_summary"
    assert envelope["content_persisted"] is False
    assert envelope["metadata"]["has_blocking_reason"] is True
    assert envelope["metadata"]["takeover_available"] is True
    assert "secret project detail" not in str(envelope)
    assert calls == [envelope]
