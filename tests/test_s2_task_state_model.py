from __future__ import annotations

from agent.state import create_agent_state
from agent.task_state_model import (
    GovernedStepStatus,
    GovernedTaskLifecycle,
    build_governed_task_state,
)
from config import STEP_COMPLETION_THRESHOLD


def _plan(step_count: int = 2) -> dict:
    return {
        "goal": "repo-governed improvement task",
        "steps": [
            {
                "step_id": f"step-{index + 1}",
                "title": f"step {index + 1}",
                "description": "demo",
                "step_type": "report",
            }
            for index in range(step_count)
        ],
    }


def _state(*, status: str = "running", step_count: int = 2, step_index: int = 0):
    state = create_agent_state(system_prompt="test")
    state.task.user_goal = "audit and repair one focused gap"
    state.task.current_plan = _plan(step_count)
    state.task.current_step_index = step_index
    state.task.status = status
    return state


def _mark_current_step_complete(state, *, score: int = STEP_COMPLETION_THRESHOLD) -> None:
    state.task.tool_execution_log["meta-step"] = {
        "tool": "mark_step_complete",
        "input": {
            "completion_score": score,
            "summary": "done",
            "outstanding": "none",
        },
        "step_index": state.task.current_step_index,
    }


def test_running_task_projects_current_step_and_progress():
    state = _state(status="running", step_count=3, step_index=1)

    snapshot = build_governed_task_state(state)

    assert snapshot.lifecycle is GovernedTaskLifecycle.RUNNING
    assert snapshot.raw_status == "running"
    assert snapshot.plan_goal == "repo-governed improvement task"
    assert snapshot.progress.completed_steps == 1
    assert snapshot.progress.total_steps == 3
    assert snapshot.progress.current_step_index == 1
    assert snapshot.progress.percent == 33.33
    assert snapshot.current_step is not None
    assert snapshot.current_step.step_id == "step-2"
    assert snapshot.current_step.status is GovernedStepStatus.ACTIVE
    assert [step.status for step in snapshot.steps] == [
        GovernedStepStatus.COMPLETED,
        GovernedStepStatus.ACTIVE,
        GovernedStepStatus.PENDING,
    ]
    assert snapshot.resumable is True


def test_step_completion_evidence_projects_completed_current_step():
    state = _state(status="running", step_count=2, step_index=0)
    _mark_current_step_complete(state)

    snapshot = build_governed_task_state(state)

    assert snapshot.current_step is not None
    assert snapshot.current_step.status is GovernedStepStatus.COMPLETED
    assert snapshot.current_step.completion_score == STEP_COMPLETION_THRESHOLD
    assert snapshot.current_step.completion_summary == "done"
    assert snapshot.current_step.outstanding == "none"
    assert snapshot.progress.completed_steps == 1
    assert snapshot.progress.percent == 50.0


def test_waiting_states_expose_blocking_reason_and_step_status():
    state = _state(status="awaiting_tool_confirmation", step_count=2, step_index=0)
    state.task.pending_tool = {
        "tool_use_id": "toolu_1",
        "tool": "write_file",
        "input": {"path": "x"},
    }

    snapshot = build_governed_task_state(state)

    assert snapshot.lifecycle is GovernedTaskLifecycle.WAITING
    assert snapshot.current_step is not None
    assert snapshot.current_step.status is GovernedStepStatus.AWAITING_TOOL
    assert snapshot.blocking_reason == "tool_confirmation:write_file"
    assert snapshot.resumable is True


def test_failed_and_done_states_have_terminal_semantics():
    failed = _state(status="failed", step_count=2, step_index=1)
    failed.task.last_error = "provider stopped"

    failed_snapshot = build_governed_task_state(failed)

    assert failed_snapshot.lifecycle is GovernedTaskLifecycle.FAILED
    assert failed_snapshot.current_step is not None
    assert failed_snapshot.current_step.status is GovernedStepStatus.FAILED
    assert failed_snapshot.failure_reason == "provider stopped"
    assert failed_snapshot.resumable is False

    done = _state(status="done", step_count=2, step_index=1)

    done_snapshot = build_governed_task_state(done)

    assert done_snapshot.lifecycle is GovernedTaskLifecycle.DONE
    assert done_snapshot.progress.completed_steps == 2
    assert done_snapshot.progress.percent == 100.0
    assert {step.status for step in done_snapshot.steps} == {
        GovernedStepStatus.COMPLETED,
    }
    assert done_snapshot.resumable is False


def test_checkpoint_resume_preserves_governed_task_snapshot(tmp_path):
    from agent.checkpoint import load_checkpoint_to_state, save_checkpoint

    checkpoint_path = tmp_path / "checkpoint.json"
    src = _state(status="awaiting_user_input", step_count=2, step_index=1)
    src.task.pending_user_input_request = {
        "awaiting_kind": "request_user_input",
        "question": "which file should be audited?",
    }

    before = build_governed_task_state(src)
    save_checkpoint(src, source="tests.s2.task_state_model", path=checkpoint_path)

    dst = create_agent_state(system_prompt="test")
    assert load_checkpoint_to_state(dst, path=checkpoint_path)
    after = build_governed_task_state(dst)

    assert after == before
    assert after.lifecycle is GovernedTaskLifecycle.WAITING
    assert after.blocking_reason == "user_input:request_user_input"
