"""Governed task state model derived from the legacy runtime state.

S2-G02 的目标不是替换 S1 legacy Plan，也不是新增 durable task ledger。
本模块把现有 TaskState/current_plan/tool_execution_log 派生成可观测契约：
task lifecycle、step status、progress、failure、resume、done 语义在这里集中定义。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from config import STEP_COMPLETION_THRESHOLD


class GovernedTaskLifecycle(str, Enum):
    """Task-level lifecycle exposed to S2 orchestration and review surfaces."""

    IDLE = "idle"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING = "waiting"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INCONSISTENT = "inconsistent"


class GovernedStepStatus(str, Enum):
    """Step-level status derived without mutating legacy Plan schema."""

    PENDING = "pending"
    ACTIVE = "active"
    AWAITING_HUMAN = "awaiting_human"
    AWAITING_TOOL = "awaiting_tool"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class GovernedStepState:
    """Observable state for one plan step."""

    index: int
    step_id: str | None
    title: str
    step_type: str | None
    status: GovernedStepStatus
    completion_score: int | None = None
    completion_summary: str | None = None
    outstanding: str | None = None


@dataclass(frozen=True, slots=True)
class GovernedTaskProgress:
    """Progress contract independent from UI wording."""

    completed_steps: int
    total_steps: int
    current_step_index: int | None

    @property
    def percent(self) -> float:
        if self.total_steps <= 0:
            return 100.0 if self.completed_steps > 0 else 0.0
        return round((self.completed_steps / self.total_steps) * 100, 2)


@dataclass(frozen=True, slots=True)
class GovernedTaskState:
    """Task snapshot safe to expose to progress, checkpoint, and evidence code."""

    lifecycle: GovernedTaskLifecycle
    raw_status: str
    user_goal: str | None
    plan_goal: str | None
    progress: GovernedTaskProgress
    steps: tuple[GovernedStepState, ...]
    current_step: GovernedStepState | None
    blocking_reason: str | None
    failure_reason: str | None
    resumable: bool


_PLANNING_STATUSES = {"planning", "awaiting_plan_confirmation"}
_RUNNING_STATUSES = {"running"}
_HUMAN_WAIT_STATUSES = {
    "awaiting_plan_confirmation",
    "awaiting_step_confirmation",
    "awaiting_user_input",
    "awaiting_feedback_intent",
    "awaiting_resume_choice",
    "awaiting_interrupt_choice",
}
_TOOL_WAIT_STATUSES = {"awaiting_tool_confirmation"}


def build_governed_task_state(state: Any) -> GovernedTaskState:
    """Build the S2 governed task state snapshot from an AgentState-like object."""

    task = state.task
    raw_status = str(getattr(task, "status", "idle") or "idle")
    current_plan = getattr(task, "current_plan", None)
    current_step_index = _coerce_step_index(getattr(task, "current_step_index", 0))
    plan_steps = _extract_plan_steps(current_plan)
    lifecycle = _derive_lifecycle(raw_status, current_plan, current_step_index, plan_steps)
    latest_completion = _latest_step_completion(task, current_step_index)

    step_states = tuple(
        _build_step_state(
            raw_step=raw_step,
            index=index,
            current_step_index=current_step_index,
            raw_status=raw_status,
            lifecycle=lifecycle,
            latest_completion=latest_completion if index == current_step_index else None,
        )
        for index, raw_step in enumerate(plan_steps)
    )
    current_step = (
        step_states[current_step_index]
        if 0 <= current_step_index < len(step_states)
        else None
    )
    completed_steps = _count_completed_steps(
        lifecycle=lifecycle,
        current_step_index=current_step_index,
        total_steps=len(step_states),
        current_step=current_step,
    )

    return GovernedTaskState(
        lifecycle=lifecycle,
        raw_status=raw_status,
        user_goal=getattr(task, "user_goal", None),
        plan_goal=_extract_plan_goal(current_plan),
        progress=GovernedTaskProgress(
            completed_steps=completed_steps,
            total_steps=len(step_states),
            current_step_index=(
                current_step_index
                if 0 <= current_step_index < len(step_states)
                else None
            ),
        ),
        steps=step_states,
        current_step=current_step,
        blocking_reason=_blocking_reason(raw_status, task),
        failure_reason=_failure_reason(raw_status, task),
        resumable=_is_resumable(raw_status),
    )


def _derive_lifecycle(
    raw_status: str,
    current_plan: Any,
    current_step_index: int,
    plan_steps: list[dict[str, Any]],
) -> GovernedTaskLifecycle:
    if raw_status == "done":
        return GovernedTaskLifecycle.DONE
    if raw_status == "failed":
        return GovernedTaskLifecycle.FAILED
    if raw_status == "cancelled":
        return GovernedTaskLifecycle.CANCELLED
    if raw_status in _TOOL_WAIT_STATUSES or raw_status in _HUMAN_WAIT_STATUSES:
        return GovernedTaskLifecycle.WAITING
    if raw_status in _PLANNING_STATUSES:
        return GovernedTaskLifecycle.PLANNING
    if raw_status in _RUNNING_STATUSES:
        if current_plan is None or 0 <= current_step_index < len(plan_steps):
            return GovernedTaskLifecycle.RUNNING
        return GovernedTaskLifecycle.INCONSISTENT
    if raw_status == "idle":
        return GovernedTaskLifecycle.IDLE
    return GovernedTaskLifecycle.INCONSISTENT


def _build_step_state(
    *,
    raw_step: dict[str, Any],
    index: int,
    current_step_index: int,
    raw_status: str,
    lifecycle: GovernedTaskLifecycle,
    latest_completion: dict[str, Any] | None,
) -> GovernedStepState:
    status = _derive_step_status(
        index=index,
        current_step_index=current_step_index,
        raw_status=raw_status,
        lifecycle=lifecycle,
        latest_completion=latest_completion,
    )
    return GovernedStepState(
        index=index,
        step_id=_string_or_none(raw_step.get("step_id") or raw_step.get("node_id")),
        title=str(
            raw_step.get("title")
            or raw_step.get("action_type")
            or raw_step.get("target")
            or f"step {index + 1}"
        ),
        step_type=_string_or_none(raw_step.get("step_type") or raw_step.get("action_type")),
        status=status,
        completion_score=(
            latest_completion.get("completion_score")
            if latest_completion is not None
            and isinstance(latest_completion.get("completion_score"), int)
            else None
        ),
        completion_summary=(
            _string_or_none(latest_completion.get("summary"))
            if latest_completion is not None
            else None
        ),
        outstanding=(
            _string_or_none(latest_completion.get("outstanding"))
            if latest_completion is not None
            else None
        ),
    )


def _derive_step_status(
    *,
    index: int,
    current_step_index: int,
    raw_status: str,
    lifecycle: GovernedTaskLifecycle,
    latest_completion: dict[str, Any] | None,
) -> GovernedStepStatus:
    if lifecycle is GovernedTaskLifecycle.DONE:
        return GovernedStepStatus.COMPLETED
    if lifecycle is GovernedTaskLifecycle.FAILED and index == current_step_index:
        return GovernedStepStatus.FAILED
    if lifecycle is GovernedTaskLifecycle.CANCELLED and index == current_step_index:
        return GovernedStepStatus.CANCELLED
    if index < current_step_index:
        return GovernedStepStatus.COMPLETED
    if index > current_step_index:
        return GovernedStepStatus.PENDING
    if _completion_meets_threshold(latest_completion):
        return GovernedStepStatus.COMPLETED
    if raw_status in _TOOL_WAIT_STATUSES:
        return GovernedStepStatus.AWAITING_TOOL
    if raw_status in _HUMAN_WAIT_STATUSES:
        return GovernedStepStatus.AWAITING_HUMAN
    return GovernedStepStatus.ACTIVE


def _count_completed_steps(
    *,
    lifecycle: GovernedTaskLifecycle,
    current_step_index: int,
    total_steps: int,
    current_step: GovernedStepState | None,
) -> int:
    if total_steps <= 0:
        return 1 if lifecycle is GovernedTaskLifecycle.DONE else 0
    if lifecycle is GovernedTaskLifecycle.DONE:
        return total_steps
    completed = min(max(current_step_index, 0), total_steps)
    if current_step and current_step.status is GovernedStepStatus.COMPLETED:
        completed += 1
    return min(completed, total_steps)


def _latest_step_completion(task: Any, current_step_index: int) -> dict[str, Any] | None:
    latest = None
    for entry in getattr(task, "tool_execution_log", {}).values():
        if not isinstance(entry, dict):
            continue
        if entry.get("tool") != "mark_step_complete":
            continue
        if entry.get("step_index") != current_step_index:
            continue
        payload = entry.get("input")
        if isinstance(payload, dict):
            latest = payload
    return latest


def _completion_meets_threshold(completion: dict[str, Any] | None) -> bool:
    if completion is None:
        return False
    score = completion.get("completion_score")
    return isinstance(score, int) and score >= STEP_COMPLETION_THRESHOLD


def _extract_plan_steps(current_plan: Any) -> list[dict[str, Any]]:
    if not isinstance(current_plan, dict):
        return []
    steps = current_plan.get("steps")
    if isinstance(steps, list):
        return [step for step in steps if isinstance(step, dict)]
    nodes = current_plan.get("nodes")
    if isinstance(nodes, list):
        return [node for node in nodes if isinstance(node, dict)]
    return []


def _extract_plan_goal(current_plan: Any) -> str | None:
    if not isinstance(current_plan, dict):
        return None
    return _string_or_none(current_plan.get("goal") or current_plan.get("plan_id"))


def _blocking_reason(raw_status: str, task: Any) -> str | None:
    if raw_status == "awaiting_plan_confirmation":
        return "plan_confirmation"
    if raw_status == "awaiting_step_confirmation":
        return "step_confirmation"
    if raw_status == "awaiting_tool_confirmation":
        pending_tool = getattr(task, "pending_tool", None) or {}
        tool_name = pending_tool.get("tool")
        return f"tool_confirmation:{tool_name}" if tool_name else "tool_confirmation"
    if raw_status in {"awaiting_user_input", "awaiting_feedback_intent"}:
        pending = getattr(task, "pending_user_input_request", None) or {}
        awaiting_kind = pending.get("awaiting_kind")
        return f"user_input:{awaiting_kind}" if awaiting_kind else "user_input"
    if raw_status == "awaiting_resume_choice":
        return "resume_choice"
    if raw_status == "awaiting_interrupt_choice":
        return "interrupt_choice"
    return None


def _failure_reason(raw_status: str, task: Any) -> str | None:
    if raw_status != "failed":
        return None
    return _string_or_none(getattr(task, "last_error", None)) or "task_failed"


def _is_resumable(raw_status: str) -> bool:
    return raw_status not in {"idle", "done", "failed", "cancelled"}


def _coerce_step_index(value: Any) -> int:
    return value if isinstance(value, int) else 0


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
