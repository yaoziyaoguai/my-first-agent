"""SubAgent Phase 11: Parent Adjudication / Result Merge tests."""

from __future__ import annotations

from agent.subagent_system.adjudication import adjudicate_result
from agent.subagent_system.request import SubAgentRequest
from agent.subagent_system.result import SubAgentAuditRecord, SubAgentResult


def _result(status: str = "ok", confidence: float = 0.8) -> SubAgentResult:
    audit = SubAgentAuditRecord(
        subagent_name="reviewer",
        delegation_id="delegation-1",
        parent_trace_id="trace-1",
        execution_mode="local_fake",
        status=status,
        stop_reason="task_completed" if status == "ok" else status,
        iterations_used=1,
        max_iterations=1,
        tools_requested=(),
        tools_denied=(),
        tools_executed=(),
        memory_proposals_count=0,
        warnings=(),
        confidence=confidence,
        elapsed_ms=1,
        revision_count=0,
        trace_event_count=0,
    )
    return SubAgentResult(
        status=status,
        summary="summary",
        artifacts=(),
        tool_requests=(),
        memory_proposals=(),
        confidence=confidence,
        warnings=(),
        audit=audit,
        handoff_back="decide",
        clarification_question="Clarify?" if status == "needs_clarification" else None,
        trace_events=(),
        stop_reason=audit.stop_reason,
    )


def _request(max_revisions: int = 1) -> SubAgentRequest:
    return SubAgentRequest(
        task="Review",
        role="reviewer",
        allowed_tools=("read_file",),
        parent_trace_id="trace-1",
        delegation_reason="review",
        max_revisions=max_revisions,
    )


def test_adjudication_accepts_high_confidence_ok_result() -> None:
    """Parent 显式 accept；没有 silent auto merge。"""

    decision = adjudicate_result(_result(), _request(), revision_count=0)

    assert decision.action == "accept_result"
    assert decision.merged_summary == "summary"


def test_adjudication_rejects_error_result() -> None:
    """error result 必须由 Parent 显式 reject。"""

    decision = adjudicate_result(_result(status="error"), _request(), revision_count=0)

    assert decision.action == "reject_result"
    assert "error" in decision.reason


def test_adjudication_requests_revision_for_low_confidence_within_bound() -> None:
    """revision loop 受 max_revisions 约束。"""

    decision = adjudicate_result(
        _result(confidence=0.2), _request(max_revisions=1), revision_count=0
    )

    assert decision.action == "request_revision"
    assert decision.revised_request is not None


def test_adjudication_asks_user_for_confirmation_or_clarification() -> None:
    """Ask User 是 human-control boundary，不能被 SubAgent 绕过。"""

    confirmation = adjudicate_result(
        _result(status="needs_confirmation"), _request(), revision_count=0
    )
    clarification = adjudicate_result(
        _result(status="needs_clarification"), _request(), revision_count=0
    )

    assert confirmation.action == "ask_user"
    assert clarification.action == "ask_user"
    assert confirmation.user_question
    assert clarification.user_question == "Clarify?"

