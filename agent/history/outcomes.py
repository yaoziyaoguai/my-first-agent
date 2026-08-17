"""从 canonical checkpoint 只读派生 outcome；不创建第二本账。"""

from __future__ import annotations

from agent.history.contracts import HistoryOutcome
from agent.runtime.contracts import (
    ConversationState,
    EvidenceOracleKind,
    GoalStatus,
    RunStatus,
)


def project_outcome(state: ConversationState) -> HistoryOutcome:
    goal = state.goal
    if goal is not None and goal.status is GoalStatus.VERIFIED_DONE:
        claimed = (
            set(state.completion_claim.criterion_evidence_refs)
            if state.completion_claim is not None
            else set()
        )
        if any(
            record.evidence_id in claimed
            and record.passed
            and record.oracle_kind is EvidenceOracleKind.USER_CONFIRMATION
            for record in state.evidence_records
        ):
            return HistoryOutcome.USER_CONFIRMED_ACCEPTANCE
        return HistoryOutcome.VERIFIED_DELIVERY
    if goal is not None and goal.status is GoalStatus.BLOCKED:
        return HistoryOutcome.BLOCKED
    if goal is not None and goal.status is GoalStatus.CANCELLED:
        return HistoryOutcome.CANCELLED
    if (
        state.last_safe_result is not None
        and state.last_safe_result.status is RunStatus.FAILED_FATAL
    ):
        return HistoryOutcome.FAILED
    return HistoryOutcome.ACCEPTANCE_UNKNOWN
