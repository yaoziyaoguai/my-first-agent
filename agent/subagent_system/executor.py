"""L0 bounded local SubAgent executor."""

from __future__ import annotations

import time

from agent.subagent_system.result import SubAgentAuditRecord, SubAgentResult
from agent.subagent_system.trace import make_trace_event


def execute_local(context_package: object, *, delegation_id: str = "delegation-local") -> SubAgentResult:
    """Execute deterministic L0 delegation.

    该 executor 不调用 provider、不执行工具、不 spawn 外部进程。它只把 packaged
    context 转换成结构化 SubAgentResult，供 Parent adjudication。
    """

    started = time.monotonic()
    task = getattr(context_package, "task", "")
    max_iterations = int(getattr(context_package, "max_iterations", 1))
    parent_trace_id = getattr(getattr(context_package, "request", None), "parent_trace_id", "")
    subagent_name = getattr(getattr(context_package, "descriptor", None), "name", "unknown")
    execution_mode = getattr(context_package, "execution_mode", "local_fake")

    status, stop_reason, summary, confidence, warnings, clarification = _deterministic_outcome(
        task,
        max_iterations,
    )
    iterations_used = max_iterations if stop_reason == "max_iterations_exceeded" else 1
    trace_events = (
        make_trace_event(
            "result_returned",
            delegation_id=delegation_id,
            parent_trace_id=parent_trace_id,
            data={"status": status, "stop_reason": stop_reason},
        ),
    )
    audit = SubAgentAuditRecord(
        subagent_name=subagent_name,
        delegation_id=delegation_id,
        parent_trace_id=parent_trace_id,
        execution_mode=execution_mode,
        status=status,
        stop_reason=stop_reason,
        iterations_used=iterations_used,
        max_iterations=max_iterations,
        tools_requested=("read_file",) if status == "ok" else (),
        tools_denied=(),
        tools_executed=(),
        memory_proposals_count=0,
        warnings=warnings,
        confidence=confidence,
        elapsed_ms=max(1, int((time.monotonic() - started) * 1000)),
        revision_count=0,
        trace_event_count=len(trace_events),
    )
    return SubAgentResult(
        status=status,
        summary=summary,
        artifacts=(),
        tool_requests=(),
        memory_proposals=(),
        confidence=confidence,
        warnings=warnings,
        audit=audit,
        handoff_back="Parent must adjudicate this L0 result.",
        clarification_question=clarification,
        trace_events=trace_events,
        stop_reason=stop_reason,
    )


def _deterministic_outcome(
    task: str,
    max_iterations: int,
) -> tuple[str, str, str, float, tuple[str, ...], str | None]:
    lowered = task.lower()
    if "loop until max" in lowered:
        return (
            "max_iterations_exceeded",
            "max_iterations_exceeded",
            "Reached max_iterations and returned a best-effort deterministic summary.",
            0.5,
            ("max_iterations reached",),
            None,
        )
    if "needs clarification" in lowered:
        return (
            "needs_clarification",
            "needs_clarification",
            "Task needs clarification before deterministic review can continue.",
            0.3,
            ("task underspecified",),
            "Please clarify the SubAgent task.",
        )
    if "shell" in lowered or "external process" in lowered:
        return (
            "policy_blocked",
            "policy_blocked",
            "Blocked by L0 policy: no shell or external process execution.",
            0.9,
            ("shell/external process is forbidden in L0",),
            None,
        )
    return (
        "ok",
        "task_completed",
        f"deterministic L0 summary after 1/{max_iterations} iterations.",
        0.8,
        (),
        None,
    )

