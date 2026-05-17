"""Parent adapter for one L0 SubAgent delegation."""

from __future__ import annotations

from agent.subagent_system.adjudication import adjudicate_result
from agent.subagent_system.context import build_context_package
from agent.subagent_system.executor import execute_local
from agent.subagent_system.result import SubAgentAuditRecord, SubAgentResult, SubAgentRun
from agent.subagent_system.trace import make_trace_event


def delegate_once(request: object, registry: object) -> SubAgentRun:
    """Run one parent-controlled L0 delegation.

    这是 adapter，不是主 Agent loop。调用方显式传入 request/registry；本函数不读取
    real sessions/runs，不调用 provider，不执行工具。
    """

    delegation_id = f"{getattr(request, 'parent_trace_id', 'trace')}:subagent"
    descriptor = _find_descriptor(request, registry)
    if descriptor is None:
        result = _missing_descriptor_result(request, delegation_id)
        adjudication = adjudicate_result(result, request, revision_count=0)
        return SubAgentRun(
            delegation_id=delegation_id,
            state="failed",
            request=request,
            descriptor=None,
            context_package=None,
            result=result,
            adjudication=adjudication,
            revision_count=0,
        )

    started = make_trace_event(
        "delegation_started",
        delegation_id=delegation_id,
        parent_trace_id=getattr(request, "parent_trace_id", ""),
        data={"role": getattr(request, "role", "")},
    )
    context_package = build_context_package(request=request, descriptor=descriptor, tool_snapshots=())
    packaged = make_trace_event(
        "context_packaged",
        delegation_id=delegation_id,
        parent_trace_id=getattr(request, "parent_trace_id", ""),
        data={"subagent": getattr(descriptor, "name", "")},
    )
    result = execute_local(context_package, delegation_id=delegation_id)
    result = _with_trace_prefix(result, (started, packaged))
    adjudication = adjudicate_result(result, request, revision_count=0)
    adjudicated = make_trace_event(
        "result_adjudicated",
        delegation_id=delegation_id,
        parent_trace_id=getattr(request, "parent_trace_id", ""),
        data={"action": adjudication.action},
    )
    result = _with_trace_suffix(result, (adjudicated,))
    return SubAgentRun(
        delegation_id=delegation_id,
        state="completed",
        request=request,
        descriptor=descriptor,
        context_package=context_package,
        result=result,
        adjudication=adjudication,
        revision_count=0,
    )


def _find_descriptor(request: object, registry: object) -> object | None:
    find_by_role = getattr(registry, "find_by_role", None)
    if callable(find_by_role):
        matches = find_by_role(getattr(request, "role", ""))
        return matches[0] if matches else None
    return None


def _missing_descriptor_result(request: object, delegation_id: str) -> SubAgentResult:
    audit = SubAgentAuditRecord(
        subagent_name="unknown",
        delegation_id=delegation_id,
        parent_trace_id=getattr(request, "parent_trace_id", ""),
        execution_mode=getattr(request, "execution_mode", "local_fake"),
        status="error",
        stop_reason="error",
        iterations_used=0,
        max_iterations=getattr(request, "max_iterations", 1),
        tools_requested=(),
        tools_denied=(),
        tools_executed=(),
        memory_proposals_count=0,
        warnings=("descriptor not found",),
        confidence=0.0,
        elapsed_ms=1,
        revision_count=0,
        trace_event_count=1,
    )
    event = make_trace_event(
        "delegation_failed",
        delegation_id=delegation_id,
        parent_trace_id=getattr(request, "parent_trace_id", ""),
        data={"reason": "descriptor_not_found"},
    )
    return SubAgentResult(
        status="error",
        summary="SubAgent descriptor not found.",
        artifacts=(),
        tool_requests=(),
        memory_proposals=(),
        confidence=0.0,
        warnings=("descriptor not found",),
        audit=audit,
        handoff_back="Parent should handle missing descriptor.",
        clarification_question=None,
        trace_events=(event,),
        stop_reason="error",
    )


def _with_trace_prefix(result: SubAgentResult, prefix: tuple[object, ...]) -> SubAgentResult:
    return _replace_trace(result, prefix + result.trace_events)


def _with_trace_suffix(result: SubAgentResult, suffix: tuple[object, ...]) -> SubAgentResult:
    return _replace_trace(result, result.trace_events + suffix)


def _replace_trace(result: SubAgentResult, trace_events: tuple[object, ...]) -> SubAgentResult:
    audit = SubAgentAuditRecord(
        subagent_name=result.audit.subagent_name,
        delegation_id=result.audit.delegation_id,
        parent_trace_id=result.audit.parent_trace_id,
        execution_mode=result.audit.execution_mode,
        status=result.audit.status,
        stop_reason=result.audit.stop_reason,
        iterations_used=result.audit.iterations_used,
        max_iterations=result.audit.max_iterations,
        tools_requested=result.audit.tools_requested,
        tools_denied=result.audit.tools_denied,
        tools_executed=result.audit.tools_executed,
        memory_proposals_count=result.audit.memory_proposals_count,
        warnings=result.audit.warnings,
        confidence=result.audit.confidence,
        elapsed_ms=result.audit.elapsed_ms,
        revision_count=result.audit.revision_count,
        trace_event_count=len(trace_events),
    )
    return SubAgentResult(
        status=result.status,
        summary=result.summary,
        artifacts=result.artifacts,
        tool_requests=result.tool_requests,
        memory_proposals=result.memory_proposals,
        confidence=result.confidence,
        warnings=result.warnings,
        audit=audit,
        handoff_back=result.handoff_back,
        clarification_question=result.clarification_question,
        trace_events=trace_events,
        stop_reason=result.stop_reason,
    )

