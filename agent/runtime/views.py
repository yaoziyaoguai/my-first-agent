"""从 authoritative state 生成所有 surface 共用的只读 Goal 投影。"""

from __future__ import annotations

from dataclasses import dataclass

from agent.runtime.contracts import (
    ActiveRunStatus,
    ContinuationPhase,
    ConversationState,
    GoalStatus,
)


@dataclass(frozen=True, slots=True)
class GoalView:
    conversation_id: str
    goal_id: str | None
    goal_revision: int | None
    status: str
    interaction_state: str
    user_outcome: str | None
    progress_summary: str | None
    next_step: str | None
    blocker: str | None
    safe_attempts: tuple[str, ...]
    resume_condition: str | None
    criteria_total: int
    criteria_verified: int
    legal_actions: tuple[str, ...]


def project_goal_view(state: ConversationState) -> GoalView:
    """纯投影；不得触发 Runtime、Provider、Tool 或持久化。"""

    goal = state.goal
    if goal is None:
        return GoalView(
            conversation_id=state.conversation_id,
            goal_id=None,
            goal_revision=None,
            status=state.interaction_state.value,
            interaction_state=state.interaction_state.value,
            user_outcome=None,
            progress_summary=None,
            next_step=None,
            blocker=None,
            safe_attempts=(),
            resume_condition=None,
            criteria_total=0,
            criteria_verified=0,
            legal_actions=("submit",) if state.active_run is None else _run_actions(state),
        )

    passed_criteria = {
        record.criterion_id
        for record in state.evidence_records
        if record.goal_id == goal.goal_id
        and record.goal_revision == goal.revision
        and record.passed
    }
    blocker, safe_attempts, resume_condition = _blocked_details(state)
    return GoalView(
        conversation_id=state.conversation_id,
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        status=goal.status.value,
        interaction_state=state.interaction_state.value,
        user_outcome=goal.user_outcome,
        progress_summary=goal.progress_summary,
        next_step=goal.next_step,
        blocker=blocker,
        safe_attempts=safe_attempts,
        resume_condition=resume_condition,
        criteria_total=len(goal.admitted_criteria),
        criteria_verified=len(
            {
                criterion.criterion_id
                for criterion in goal.admitted_criteria
                if criterion.criterion_id in passed_criteria
            }
        ),
        legal_actions=_goal_actions(state),
    )


def _run_actions(state: ConversationState) -> tuple[str, ...]:
    active = state.active_run
    if active is None:
        return ("submit",)
    if active.status is ActiveRunStatus.AWAITING_APPROVAL:
        return ("approve", "reject")
    if active.status is ActiveRunStatus.AWAITING_DISCLOSURE:
        return ("ack_provider",)
    if (
        active.status is ActiveRunStatus.AWAITING_RECOVERY
        or active.phase is ContinuationPhase.EXECUTING
    ):
        return ("mark_succeeded", "mark_failed")
    return ("resume", "cancel")


def _goal_actions(state: ConversationState) -> tuple[str, ...]:
    goal = state.goal
    if goal is None or goal.status in {GoalStatus.CANCELLED, GoalStatus.VERIFIED_DONE}:
        return ()
    active = state.active_run
    if active is not None and (
        active.status is ActiveRunStatus.AWAITING_RECOVERY
        or active.phase is ContinuationPhase.EXECUTING
    ):
        return ("mark_succeeded", "mark_failed")
    if goal.status in {GoalStatus.PAUSED, GoalStatus.BLOCKED}:
        return ("resume_goal", "correct_goal", "cancel_goal")
    return ("pause_goal", "correct_goal", "cancel_goal")


def _blocked_details(
    state: ConversationState,
) -> tuple[str | None, tuple[str, ...], str | None]:
    for fact in reversed(state.facts):
        if fact.content.get("code") != "blocked_claim":
            continue
        blocker = fact.content.get("blocker")
        attempts = fact.content.get("safe_attempts")
        resume = fact.content.get("resume_condition")
        return (
            blocker if isinstance(blocker, str) else None,
            tuple(item for item in attempts if isinstance(item, str))
            if isinstance(attempts, list)
            else (),
            resume if isinstance(resume, str) else None,
        )
    return None, (), None
