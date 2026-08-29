"""Startup state 的纯只读投影；不调用 Provider、Tool 或 checkpoint mutation。"""

from __future__ import annotations

from dataclasses import dataclass

from agent.continuity.sessions import StartupDisposition, WorkspaceSession
from agent.runtime.contracts import (
    ActiveRunStatus,
    ContinuationPhase,
    ConversationState,
    ExecutionAuthorityClass,
    GoalStatus,
)

# 017 native：sandbox 恢复分类的 closed 单值（Docker 时代的 bundle_review/
# base_drift 已随方向重做删除，不做 compatibility 映射）。cleanup_unknown
# 由 teardown 路径直接暴露，不进 startup 投影。
SANDBOX_RECOVERY_KINDS = frozenset({"execution_unknown"})


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
    # 017：sandbox 旅程的恢复分类（无则 None）；普通状态不受影响。
    sandbox_recovery: str | None = None
    # 018：browser user takeover pending；等待 /browser-done 或 /cancel。
    browser_takeover_pending: bool = False


def sandbox_recovery_kind(state: ConversationState) -> str | None:
    """从 durable raw facts 只读分类 native sandbox 恢复状态。

    closed 单值 ``execution_unknown``：EXECUTING 的 ISOLATED_SANDBOX intent
    需要 resume 后 read-back 解决，不得盲目重放。
    """

    goal = state.goal
    if goal is None:
        return None
    active_run = state.active_run
    if active_run is not None:
        record = active_run.executing_intent
        if (
            active_run.phase is ContinuationPhase.EXECUTING
            and record is not None
            and record.execution_authority is ExecutionAuthorityClass.ISOLATED_SANDBOX
        ):
            return "execution_unknown"
    return None


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
        sandbox_recovery=(
            sandbox_recovery_kind(state) if state is not None else None
        ),
        browser_takeover_pending=(
            state.browser_takeover_pending is not None if state is not None else False
        ),
    )
