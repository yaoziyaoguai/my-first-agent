"""Startup state 的纯只读投影；不调用 Provider、Tool 或 checkpoint mutation。"""

from __future__ import annotations

from dataclasses import dataclass

from agent.continuity.sessions import StartupDisposition, WorkspaceSession
from agent.runtime.contracts import ActiveRunStatus, GoalStatus


@dataclass(frozen=True, slots=True)
class RestartProjection:
    disposition: StartupDisposition
    conversation_id: str | None
    goal_id: str | None
    goal_revision: int | None
    goal_status: GoalStatus | None
    active_run_status: ActiveRunStatus | None
    user_outcome: str | None
    progress_summary: str | None
    next_step: str | None
    required_action: str | None


def project_restart(session: WorkspaceSession) -> RestartProjection:
    snapshot = session.snapshot
    state = snapshot.state if snapshot is not None else None
    goal = state.goal if state is not None else None
    active_run = state.active_run if state is not None else None
    required_action = {
        StartupDisposition.SELECT_REQUIRED: "select_goal",
        StartupDisposition.NEEDS_AUTHORITY: "grant_authority",
        StartupDisposition.RECOVERY_REQUIRED: "resolve_unknown_tool_outcome",
    }.get(session.disposition)
    if required_action is None and goal is not None:
        if (
            goal.status in {GoalStatus.PAUSED, GoalStatus.BLOCKED}
            and active_run is None
        ):
            required_action = "resume_goal"
        elif active_run is not None and active_run.status in {
            ActiveRunStatus.PAUSED_LIMIT,
            ActiveRunStatus.PAUSED_RETRYABLE,
        }:
            required_action = "resume"
    return RestartProjection(
        disposition=session.disposition,
        conversation_id=state.conversation_id if state is not None else None,
        goal_id=goal.goal_id if goal is not None else None,
        goal_revision=goal.revision if goal is not None else None,
        goal_status=goal.status if goal is not None else None,
        active_run_status=active_run.status if active_run is not None else None,
        user_outcome=goal.user_outcome if goal is not None else None,
        progress_summary=goal.progress_summary if goal is not None else None,
        next_step=goal.next_step if goal is not None else None,
        required_action=required_action,
    )
