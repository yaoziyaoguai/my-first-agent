"""RED guardrails for Sub-agent v0 parent decision semantics."""

from __future__ import annotations

from dataclasses import replace

import pytest

from agent.subagent_system.adjudication import adjudicate_result
from agent.subagent_system.result import SubAgentAuditRecord, SubAgentResult


def _ok_result() -> SubAgentResult:
    audit = SubAgentAuditRecord(
        subagent_name="test",
        delegation_id="delegation",
        parent_trace_id="parent",
        execution_mode="local_fake",
        status="ok",
        stop_reason="task_completed",
        iterations_used=1,
        max_iterations=1,
        tools_requested=(),
        tools_denied=(),
        tools_executed=(),
        memory_proposals_count=0,
        warnings=(),
        confidence=0.9,
        elapsed_ms=1,
        revision_count=0,
        trace_event_count=0,
    )
    return SubAgentResult(
        status="ok",
        summary="SAFE SUMMARY",
        artifacts=(),
        tool_requests=(),
        memory_proposals=(),
        confidence=0.9,
        warnings=(),
        audit=audit,
        handoff_back="handoff",
        clarification_question=None,
        trace_events=(),
        stop_reason="task_completed",
    )


@pytest.mark.xfail(strict=True, reason="Old adjudication auto-accept remains before U6")
def test_child_result_first_enters_parent_decision_pending_not_auto_accept() -> None:
    request = type("Request", (), {"max_revisions": 0, "task": "task"})()

    decision = adjudicate_result(_ok_result(), request, revision_count=0)

    assert decision.action == "parent_decision.pending"


@pytest.mark.xfail(strict=True, reason="V0 parent_decision.applied contract not implemented yet")
def test_parent_decision_applied_is_explicit_and_display_only_is_not_adoption() -> None:
    from agent.runtime_integration import subagent_action

    pending = subagent_action.create_subagent_v0_parent_decision_pending(_ok_result())
    applied = subagent_action.apply_subagent_v0_parent_decision(
        pending,
        decision_type="display_only",
    )

    assert pending.status == "pending"
    assert applied.status == "applied"
    assert applied.decision_type == "display_only"
    assert applied.adopted is False
    assert applied.evidence_event == "subagent.parent_decision.applied"


@pytest.mark.xfail(strict=True, reason="Display-only mutation guards not implemented yet")
def test_display_only_does_not_mutate_parent_owned_state() -> None:
    from agent.runtime_integration import subagent_action

    parent_state = {
        "memory": (),
        "checkpoint": {},
        "context": {"items": ()},
        "prompt": "parent prompt",
        "messages": (),
    }
    before = replace if False else repr(parent_state)

    subagent_action.display_subagent_v0_safe_summary(
        parent_state=parent_state,
        safe_summary="safe",
        decision_type="display_only",
    )

    assert repr(parent_state) == before


@pytest.mark.xfail(strict=True, reason="V0 path does not yet bypass old auto-accept helper")
def test_old_adjudication_auto_accept_helper_is_not_used_by_v0_production_path() -> None:
    from agent.runtime_integration import subagent_action

    source = subagent_action.describe_subagent_v0_parent_decision_path()

    assert "adjudicate_result(" not in source
    assert "accept_result" not in source
    assert "parent_decision.pending" in source
