"""Task-level evidence depth report for S2."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent.task_context import TaskContextPackage, build_task_execution_context
from agent.task_review import TaskProgressReview, build_task_progress_review
from agent.task_tool_contract import (
    GovernedToolContractReport,
    build_governed_tool_contract_report,
)


@dataclass(frozen=True, slots=True)
class TaskEvidenceReport:
    """Safe, reviewable task-level evidence summary.

    This report is intentionally not full-fidelity model replay. It records
    enough structure for human review while keeping TD-001/TD-004 as explicit
    debt instead of silently persisting raw request/response/tool bodies.
    """

    task_scope_id: str
    lifecycle: str
    progress_percent: float
    provider_callable: bool
    tool_attempted_count: int
    tool_executed_count: int
    tool_blocked_count: int
    tool_failed_count: int
    evidence_events: tuple[str, ...]
    known_debt_refs: tuple[str, ...]
    replay_ready: bool


RecordEvidenceFn = Callable[..., dict[str, Any]]


def build_task_evidence_report(
    state: Any,
    *,
    context_package: TaskContextPackage | None = None,
    tool_report: GovernedToolContractReport | None = None,
    progress_review: TaskProgressReview | None = None,
) -> TaskEvidenceReport:
    """Build a safe task-level evidence report without mutating state."""

    package = context_package or build_task_execution_context(state)
    tools = tool_report or build_governed_tool_contract_report(
        state,
        context_package=package,
    )
    review = progress_review or build_task_progress_review(
        state,
        context_package=package,
        tool_report=tools,
    )
    events = _evidence_events(
        package,
        tools,
        review,
        delegation_count=len(getattr(state.task, "delegation_log", ()) or ()),
    )
    debt_refs = _known_debt_refs(tools)
    replay_ready = (
        package.provider_callable
        and tools.audit_ready
        and bool(events)
        and review.total_steps > 0
    )
    return TaskEvidenceReport(
        task_scope_id=package.memory_boundary.task_scope_id,
        lifecycle=review.lifecycle,
        progress_percent=review.progress_percent,
        provider_callable=package.provider_callable,
        tool_attempted_count=tools.attempted_count,
        tool_executed_count=tools.executed_count,
        tool_blocked_count=tools.blocked_count,
        tool_failed_count=tools.failed_count,
        evidence_events=events,
        known_debt_refs=debt_refs,
        replay_ready=replay_ready,
    )


def record_task_evidence_report(
    report: TaskEvidenceReport,
    *,
    operation: str = "task_evidence.report",
    record_evidence_fn: RecordEvidenceFn | None = None,
) -> dict[str, Any]:
    """Record safe task-level evidence metadata."""

    if record_evidence_fn is None:
        from agent.evidence_recorder import record_evidence as record_evidence_fn

    return record_evidence_fn(
        subsystem="task",
        operation=operation,
        phase="summary",
        status="ok" if report.replay_ready else "blocked",
        reason_code="" if report.replay_ready else "task_evidence_incomplete",
        safe_summary="task-level evidence report projected for human replay",
        content_persisted=False,
        content_redacted=False,
        sensitive=False,
        metadata={
            "task_scope_id": report.task_scope_id,
            "lifecycle": report.lifecycle,
            "progress_percent": report.progress_percent,
            "provider_callable": report.provider_callable,
            "tool_attempted_count": report.tool_attempted_count,
            "tool_executed_count": report.tool_executed_count,
            "tool_blocked_count": report.tool_blocked_count,
            "tool_failed_count": report.tool_failed_count,
            "evidence_event_count": len(report.evidence_events),
            "known_debt_refs": list(report.known_debt_refs),
            "replay_ready": report.replay_ready,
        },
    )


def _evidence_events(
    package: TaskContextPackage,
    tools: GovernedToolContractReport,
    review: TaskProgressReview,
    *,
    delegation_count: int = 0,
) -> tuple[str, ...]:
    events = [
        f"task.lifecycle:{package.task.lifecycle.value}",
        f"task.progress:{review.completed_steps}/{review.total_steps}",
        f"context.provider_callable:{package.provider_callable}",
        f"tools.attempted:{tools.attempted_count}",
        f"tools.executed:{tools.executed_count}",
        f"tools.blocked:{tools.blocked_count}",
    ]
    if review.blocking_reason:
        events.append("task.blocking_reason:present")
    if review.failure_reason:
        events.append("task.failure_reason:present")
    # S3-G05: 呈现 extension（SubAgent 委派）证据计数，使 evidence report 可复盘 extension 决策。
    if delegation_count > 0:
        events.append(f"extensions.delegations:{delegation_count}")
    return tuple(events)


def _known_debt_refs(tools: GovernedToolContractReport) -> tuple[str, ...]:
    refs = ["TD-001"]
    if any(call.status == "blocked_by_policy" for call in tools.calls):
        refs.append("TD-004")
    return tuple(refs)
