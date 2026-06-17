"""S2 governed task orchestration skeleton.

This module is a thin coordination layer over the existing runtime spine:
legacy Plan state, transition rules, checkpoint actions, and the S2 governed
task state projection. It deliberately does not generate plans, execute tools,
or write checkpoints; callers keep those responsibilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.plan_schema import Plan
from agent.task_runtime import is_current_step_completed
from agent.task_state_model import GovernedTaskState, build_governed_task_state
from agent.transitions import (
    CheckpointAction,
    TaskTransitionRequest,
    TaskTransitionResult,
    TransitionEvent,
    advance_current_step_if_needed,
    apply_task_transition,
    validate_task_transition,
)


@dataclass(frozen=True, slots=True)
class TaskOrchestrationResult:
    """Result of one orchestration skeleton operation."""

    transition: TaskTransitionResult
    snapshot: GovernedTaskState

    @property
    def allowed(self) -> bool:
        return self.transition.allowed

    @property
    def checkpoint_action(self) -> CheckpointAction:
        return self.transition.checkpoint_action


def receive_governed_task(
    state: Any,
    *,
    user_goal: str,
    plan_payload: dict[str, Any],
    owner: str = "task_orchestration.receive_governed_task",
) -> TaskOrchestrationResult:
    """Receive a planned task and enter the existing plan-confirmation path.

    The planner/model remains outside this function. S2-G03 only needs the
    orchestration skeleton from "a plan exists" to resumable execution.
    """

    request = TaskTransitionRequest(
        event=TransitionEvent.PLAN_GENERATED,
        owner=owner,
        expected_from_status="idle",
    )
    preflight = validate_task_transition(state, request)
    if not preflight.allowed:
        return _result(preflight, state)

    # Validate before mutating state so a malformed plan cannot leave partial
    # task state behind.
    plan = Plan.model_validate(plan_payload)
    state.task.user_goal = user_goal
    state.task.current_plan = plan.model_dump()
    state.task.current_step_index = 0

    transition = apply_task_transition(state, request, preflight=preflight)
    return _result(transition, state)


def accept_governed_plan(
    state: Any,
    *,
    owner: str = "task_orchestration.accept_governed_plan",
) -> TaskOrchestrationResult:
    """Move an accepted plan into the running state via the transition table."""

    request = TaskTransitionRequest(
        event=TransitionEvent.USER_ACCEPTED,
        owner=owner,
        expected_from_status="awaiting_plan_confirmation",
    )
    transition = apply_task_transition(state, request)
    return _result(transition, state)


def advance_governed_task_if_ready(
    state: Any,
    *,
    owner: str = "task_orchestration.advance_governed_task_if_ready",
) -> TaskOrchestrationResult:
    """Advance the current step only after governed completion evidence exists."""

    if state.task.current_plan and not is_current_step_completed(state):
        return _result(
            TaskTransitionResult(
                allowed=False,
                reason="current step has no passing mark_step_complete evidence",
                previous_status=state.task.status,
                next_status=None,
                event=TransitionEvent.STEP_ADVANCED,
                owner=owner,
                checkpoint_action=CheckpointAction.NONE,
            ),
            state,
        )

    transition = advance_current_step_if_needed(state, owner=owner)
    return _result(transition, state)


def resume_governed_task(state: Any) -> GovernedTaskState:
    """Project a loaded checkpoint state back into the S2 task model."""

    return build_governed_task_state(state)


def _result(
    transition: TaskTransitionResult,
    state: Any,
) -> TaskOrchestrationResult:
    return TaskOrchestrationResult(
        transition=transition,
        snapshot=build_governed_task_state(state),
    )
