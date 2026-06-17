"""Human-visible task progress and takeover seam for S2."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from agent.task_context import TaskContextPackage, build_task_execution_context
from agent.task_tool_contract import (
    GovernedToolContractReport,
    build_governed_tool_contract_report,
)


class HumanTakeoverAction(str, Enum):
    """Human review actions supported by the S2 minimum seam."""

    CONTINUE = "continue"
    STOP = "stop"
    TAKEOVER = "takeover"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class TaskProgressReview:
    """Safe progress snapshot for human review/takeover surfaces."""

    lifecycle: str
    progress_percent: float
    completed_steps: int
    total_steps: int
    current_step_index: int | None
    current_step_title: str | None
    blocking_reason: str | None
    failure_reason: str | None
    tool_attempted_count: int
    tool_blocked_count: int
    takeover_available: bool
    review_text: str


@dataclass(frozen=True, slots=True)
class HumanTakeoverDecision:
    """Parsed human takeover intent; callers decide how to apply it."""

    action: HumanTakeoverAction
    allowed: bool
    reason: str


RecordEvidenceFn = Callable[..., dict[str, Any]]


def build_task_progress_review(
    state: Any,
    *,
    context_package: TaskContextPackage | None = None,
    tool_report: GovernedToolContractReport | None = None,
) -> TaskProgressReview:
    """Build a human-visible progress snapshot without mutating runtime state."""

    package = context_package or build_task_execution_context(state)
    report = tool_report or build_governed_tool_contract_report(
        state,
        context_package=package,
    )
    task = package.task
    current_step = task.current_step
    progress = task.progress
    takeover_available = bool(task.blocking_reason or task.failure_reason)
    review_text = _render_review_text(
        lifecycle=task.lifecycle.value,
        progress_percent=progress.percent,
        completed_steps=progress.completed_steps,
        total_steps=progress.total_steps,
        current_step_title=current_step.title if current_step else None,
        blocking_reason=task.blocking_reason,
        failure_reason=task.failure_reason,
        tool_attempted_count=report.attempted_count,
        tool_blocked_count=report.blocked_count,
        takeover_available=takeover_available,
    )
    return TaskProgressReview(
        lifecycle=task.lifecycle.value,
        progress_percent=progress.percent,
        completed_steps=progress.completed_steps,
        total_steps=progress.total_steps,
        current_step_index=progress.current_step_index,
        current_step_title=current_step.title if current_step else None,
        blocking_reason=task.blocking_reason,
        failure_reason=task.failure_reason,
        tool_attempted_count=report.attempted_count,
        tool_blocked_count=report.blocked_count,
        takeover_available=takeover_available,
        review_text=review_text,
    )


def parse_human_takeover_decision(
    user_text: str,
    *,
    review: TaskProgressReview,
) -> HumanTakeoverDecision:
    """Parse human review intent without applying side effects."""

    text = (user_text or "").strip().lower()
    if text in {"continue", "c", "继续", "1"}:
        return HumanTakeoverDecision(
            action=HumanTakeoverAction.CONTINUE,
            allowed=True,
            reason="human chose to continue governed task",
        )
    if text in {"stop", "s", "停止", "取消", "2"}:
        return HumanTakeoverDecision(
            action=HumanTakeoverAction.STOP,
            allowed=True,
            reason="human chose to stop governed task",
        )
    if text in {"takeover", "take over", "接管", "人工接管", "3"}:
        return HumanTakeoverDecision(
            action=HumanTakeoverAction.TAKEOVER,
            allowed=review.takeover_available,
            reason=(
                "human takeover accepted at blocking/failure seam"
                if review.takeover_available
                else "takeover requires a visible blocking or failure reason"
            ),
        )
    return HumanTakeoverDecision(
        action=HumanTakeoverAction.INVALID,
        allowed=False,
        reason="unknown human takeover command",
    )


def record_task_progress_review_evidence(
    review: TaskProgressReview,
    *,
    operation: str = "task_progress.review_summary",
    record_evidence_fn: RecordEvidenceFn | None = None,
) -> dict[str, Any]:
    """Record safe evidence that progress was visible to a human reviewer."""

    if record_evidence_fn is None:
        from agent.evidence_recorder import record_evidence as record_evidence_fn

    return record_evidence_fn(
        subsystem="task",
        operation=operation,
        phase="summary",
        status="ok",
        safe_summary="task progress review snapshot projected",
        content_persisted=False,
        content_redacted=False,
        sensitive=False,
        metadata={
            "lifecycle": review.lifecycle,
            "progress_percent": review.progress_percent,
            "completed_steps": review.completed_steps,
            "total_steps": review.total_steps,
            "has_blocking_reason": bool(review.blocking_reason),
            "has_failure_reason": bool(review.failure_reason),
            "tool_attempted_count": review.tool_attempted_count,
            "tool_blocked_count": review.tool_blocked_count,
            "takeover_available": review.takeover_available,
        },
    )


def _render_review_text(
    *,
    lifecycle: str,
    progress_percent: float,
    completed_steps: int,
    total_steps: int,
    current_step_title: str | None,
    blocking_reason: str | None,
    failure_reason: str | None,
    tool_attempted_count: int,
    tool_blocked_count: int,
    takeover_available: bool,
) -> str:
    lines = [
        f"Task status: {lifecycle}",
        f"Progress: {completed_steps}/{total_steps} ({progress_percent:.2f}%)",
    ]
    if current_step_title:
        lines.append(f"Current step: {current_step_title}")
    if blocking_reason:
        lines.append(f"Blocking reason: {blocking_reason}")
    if failure_reason:
        lines.append(f"Failure reason: {failure_reason}")
    lines.append(f"Tools: attempted={tool_attempted_count}, blocked={tool_blocked_count}")
    lines.append(
        "Human takeover: available"
        if takeover_available
        else "Human takeover: not currently needed"
    )
    return "\n".join(lines)
