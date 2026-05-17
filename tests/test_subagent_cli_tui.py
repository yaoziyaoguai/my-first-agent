"""SubAgent Phase 17: CLI/TUI visibility tests."""

from __future__ import annotations

from agent.subagent_system.descriptor import SubAgentDescriptor
from agent.subagent_system.presentation import (
    format_adjudication,
    format_available_subagents,
    format_delegation_result,
    format_delegation_status,
    format_subagent_audit,
    format_trace_events,
)
from agent.subagent_system.result import ParentAdjudicationResult, SubAgentAuditRecord
from agent.subagent_system.trace import make_trace_event


def _audit() -> SubAgentAuditRecord:
    return SubAgentAuditRecord(
        subagent_name="reviewer",
        delegation_id="delegation-1",
        parent_trace_id="trace-1",
        execution_mode="local_fake",
        status="ok",
        stop_reason="task_completed",
        iterations_used=1,
        max_iterations=1,
        tools_requested=("read_file",),
        tools_denied=(),
        tools_executed=(),
        memory_proposals_count=0,
        warnings=(),
        confidence=0.8,
        elapsed_ms=1,
        revision_count=0,
        trace_event_count=1,
    )


def test_presentation_formats_available_subagents_without_runtime_logic() -> None:
    """presentation 只展示 descriptor，不导入 executor/runtime。"""

    output = format_available_subagents((
        SubAgentDescriptor(name="reviewer", description="Review", role="reviewer"),
    ))

    assert "reviewer" in output
    assert "local_fake" in output


def test_presentation_formats_status_audit_adjudication_and_trace() -> None:
    """CLI/TUI 展示 parent-visible 状态，不触发 delegation。"""

    audit = _audit()
    status = format_delegation_status("running", "local_fake", "review")
    result = format_delegation_result("ok", "task_completed", "summary")
    audit_text = format_subagent_audit(audit)
    adjudication = format_adjudication(ParentAdjudicationResult.accept("ok", merged_summary="summary"))
    trace = format_trace_events((
        make_trace_event(
            "delegation_started",
            delegation_id="delegation-1",
            parent_trace_id="trace-1",
        ),
    ))

    assert "running" in status
    assert "task_completed" in result
    assert "tools_requested=read_file" in audit_text
    assert "accept_result" in adjudication
    assert "delegation_started" in trace

