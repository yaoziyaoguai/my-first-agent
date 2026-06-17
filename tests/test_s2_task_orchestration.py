from __future__ import annotations

from agent.state import create_agent_state
from agent.task_orchestration import (
    accept_governed_plan,
    advance_governed_task_if_ready,
    receive_governed_task,
    resume_governed_task,
)
from agent.task_state_model import GovernedStepStatus, GovernedTaskLifecycle
from agent.transitions import CheckpointAction
from config import STEP_COMPLETION_THRESHOLD


def _plan(step_count: int = 2) -> dict:
    return {
        "goal": "repo-governed improvement task",
        "thinking": "audit, patch, verify",
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


def _mark_current_step_complete(state, *, tool_use_id: str) -> None:
    state.task.tool_execution_log[tool_use_id] = {
        "tool": "mark_step_complete",
        "input": {
            "completion_score": STEP_COMPLETION_THRESHOLD,
            "summary": "done",
            "outstanding": "none",
        },
        "step_index": state.task.current_step_index,
    }


def test_s2_reference_task_walks_plan_checkpoint_resume_done(tmp_path):
    from agent.checkpoint import clear_checkpoint, load_checkpoint_to_state, save_checkpoint

    checkpoint_path = tmp_path / "checkpoint.json"
    state = create_agent_state(system_prompt="test")

    received = receive_governed_task(
        state,
        user_goal="repair one focused S2 gap",
        plan_payload=_plan(),
    )
    assert received.allowed is True
    assert received.checkpoint_action is CheckpointAction.SAVE
    assert received.snapshot.lifecycle is GovernedTaskLifecycle.WAITING
    assert received.snapshot.blocking_reason == "plan_confirmation"
    save_checkpoint(state, source="tests.s2.orchestration.received", path=checkpoint_path)

    resumed = create_agent_state(system_prompt="test")
    assert load_checkpoint_to_state(resumed, path=checkpoint_path)
    resumed_snapshot = resume_governed_task(resumed)
    assert resumed_snapshot == received.snapshot

    accepted = accept_governed_plan(resumed)
    assert accepted.allowed is True
    assert accepted.checkpoint_action is CheckpointAction.SAVE
    assert accepted.snapshot.lifecycle is GovernedTaskLifecycle.RUNNING
    assert accepted.snapshot.current_step is not None
    assert accepted.snapshot.current_step.status is GovernedStepStatus.ACTIVE

    _mark_current_step_complete(resumed, tool_use_id="meta-step-1")
    advanced = advance_governed_task_if_ready(resumed)
    assert advanced.allowed is True
    assert advanced.checkpoint_action is CheckpointAction.SAVE
    assert advanced.snapshot.lifecycle is GovernedTaskLifecycle.RUNNING
    assert advanced.snapshot.progress.current_step_index == 1
    assert advanced.snapshot.progress.completed_steps == 1
    save_checkpoint(resumed, source="tests.s2.orchestration.step1", path=checkpoint_path)

    resumed_again = create_agent_state(system_prompt="test")
    assert load_checkpoint_to_state(resumed_again, path=checkpoint_path)
    assert resume_governed_task(resumed_again).progress.current_step_index == 1

    _mark_current_step_complete(resumed_again, tool_use_id="meta-step-2")
    completed = advance_governed_task_if_ready(resumed_again)
    assert completed.allowed is True
    assert completed.checkpoint_action is CheckpointAction.CLEAR
    assert completed.snapshot.lifecycle is GovernedTaskLifecycle.DONE
    assert completed.snapshot.progress.completed_steps == 2
    assert completed.snapshot.progress.percent == 100.0
    clear_checkpoint(path=checkpoint_path)


def test_orchestration_does_not_advance_without_completion_evidence():
    state = create_agent_state(system_prompt="test")
    assert receive_governed_task(
        state,
        user_goal="repair one focused S2 gap",
        plan_payload=_plan(),
    ).allowed
    assert accept_governed_plan(state).allowed

    before_step = state.task.current_step_index
    denied = advance_governed_task_if_ready(state)

    assert denied.allowed is False
    assert denied.checkpoint_action is CheckpointAction.NONE
    assert denied.snapshot.lifecycle is GovernedTaskLifecycle.RUNNING
    assert state.task.current_step_index == before_step


def test_receive_governed_task_denied_does_not_overwrite_active_task():
    state = create_agent_state(system_prompt="test")
    state.task.status = "running"
    state.task.user_goal = "existing"
    state.task.current_plan = _plan()

    denied = receive_governed_task(
        state,
        user_goal="new task",
        plan_payload=_plan(step_count=1),
    )

    assert denied.allowed is False
    assert state.task.status == "running"
    assert state.task.user_goal == "existing"
    assert len(state.task.current_plan["steps"]) == 2
