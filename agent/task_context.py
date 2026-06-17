"""Task-level context package for S2 governed work."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent.context_builder import build_execution_messages
from agent.task_state_model import GovernedTaskState, build_governed_task_state


@dataclass(frozen=True, slots=True)
class TaskMemoryBoundary:
    """Safe memory boundary metadata for one task context package."""

    task_scope_id: str
    has_working_summary: bool
    has_memory_store_reference: bool
    pending_retain_proposals: int
    pending_user_input_kind: str | None


@dataclass(frozen=True, slots=True)
class TaskContextPackage:
    """Provider-facing task context plus state and memory boundary metadata."""

    task: GovernedTaskState
    model_messages: tuple[dict[str, Any], ...]
    memory_boundary: TaskMemoryBoundary
    provider_callable: bool
    provider_callable_issues: tuple[str, ...]


RecordEvidenceFn = Callable[..., dict[str, Any]]


def build_task_execution_context(state: Any) -> TaskContextPackage:
    """Build the S2 task-level execution context without mutating state."""

    model_messages = tuple(build_execution_messages(state))
    issues = tuple(_provider_callable_issues(model_messages))
    return TaskContextPackage(
        task=build_governed_task_state(state),
        model_messages=model_messages,
        memory_boundary=_build_memory_boundary(state),
        provider_callable=not issues,
        provider_callable_issues=issues,
    )


def record_task_memory_boundary_evidence(
    package: TaskContextPackage,
    *,
    operation: str = "task_context.build_execution_context",
    record_evidence_fn: RecordEvidenceFn | None = None,
) -> dict[str, Any]:
    """Record safe evidence that memory access stayed task-scoped."""

    if record_evidence_fn is None:
        from agent.evidence_recorder import record_evidence as record_evidence_fn

    return record_evidence_fn(
        subsystem="memory",
        operation=operation,
        phase="summary",
        status="ok" if package.provider_callable else "blocked",
        reason_code="" if package.provider_callable else "provider_context_invalid",
        safe_summary="task memory boundary projected for governed task context",
        content_persisted=False,
        content_redacted=False,
        sensitive=False,
        metadata={
            "task_scope_id": package.memory_boundary.task_scope_id,
            "task_lifecycle": package.task.lifecycle.value,
            "has_working_summary": package.memory_boundary.has_working_summary,
            "has_memory_store_reference": (
                package.memory_boundary.has_memory_store_reference
            ),
            "pending_retain_proposals": (
                package.memory_boundary.pending_retain_proposals
            ),
            "pending_user_input_kind": (
                package.memory_boundary.pending_user_input_kind
            ),
            "provider_callable": package.provider_callable,
            "provider_callable_issue_count": len(package.provider_callable_issues),
        },
    )


def _build_memory_boundary(state: Any) -> TaskMemoryBoundary:
    task = state.task
    memory = state.memory
    pending = getattr(task, "pending_user_input_request", None) or {}
    return TaskMemoryBoundary(
        task_scope_id=_task_scope_id(state),
        has_working_summary=bool(getattr(memory, "working_summary", None)),
        has_memory_store_reference=bool(
            getattr(memory, "memory_store_reference", None)
        ),
        pending_retain_proposals=len(
            getattr(task, "pending_retain_proposals", []) or []
        ),
        pending_user_input_kind=pending.get("awaiting_kind"),
    )


def _task_scope_id(state: Any) -> str:
    task = state.task
    memory = state.memory
    plan = getattr(task, "current_plan", None)
    plan_goal = plan.get("goal", "") if isinstance(plan, dict) else ""
    raw = "|".join([
        str(getattr(memory, "session_id", "") or ""),
        str(getattr(task, "user_goal", "") or ""),
        str(plan_goal or ""),
    ])
    return "task-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _provider_callable_issues(messages: tuple[dict[str, Any], ...]) -> list[str]:
    issues: list[str] = []
    for message_index, message in enumerate(messages):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block_index, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_result":
                continue
            if "content" not in block:
                issues.append(
                    f"message[{message_index}].content[{block_index}] "
                    "tool_result missing content"
                )
    return issues
