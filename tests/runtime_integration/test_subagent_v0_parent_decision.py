"""RED guardrails for Sub-agent v0 parent decision semantics."""

from __future__ import annotations

import pytest

from agent.subagent_system.result import SubAgentAuditRecord, SubAgentResult
from tests.runtime_integration.subagent_v0_contract_helpers import route_v0


def _forbid_legacy_adjudication(monkeypatch: pytest.MonkeyPatch, message: str) -> None:
    import agent.subagent_system.adjudication as adjudication
    import agent.subagent_system.delegation as delegation

    def forbidden_adjudicate(*_args: object, **_kwargs: object) -> object:
        raise AssertionError(message)

    monkeypatch.setattr(adjudication, "adjudicate_result", forbidden_adjudicate)
    monkeypatch.setattr(delegation, "adjudicate_result", forbidden_adjudicate)


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


def test_v0_child_result_first_enters_parent_decision_pending_not_legacy_auto_accept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_legacy_adjudication(
        monkeypatch,
        "v0 production path called legacy auto-accept adjudication",
    )

    result = route_v0(payload={"child_result": _ok_result()})

    assert result.payload["parent_decision_status"] == "pending"
    assert result.payload["adopted"] is False
    assert result.evidence["event"] == "subagent.parent_decision.pending"


def test_parent_decision_applied_is_explicit_and_display_only_is_not_adoption() -> None:
    result = route_v0(payload={
        "child_result": _ok_result(),
        "parent_decision": {"decision_type": "display_only"},
    })

    assert result.payload["parent_decision_status"] == "applied"
    assert result.payload["decision_type"] == "display_only"
    assert result.payload["adopted"] is False
    assert "subagent.parent_decision.applied" in result.evidence["lifecycle_events"]


def test_display_only_does_not_mutate_parent_owned_state() -> None:
    parent_state = {
        "memory": (),
        "checkpoint": {},
        "context": {"items": ()},
        "prompt": "parent prompt",
        "messages": (),
    }
    before = repr(parent_state)

    result = route_v0(payload={
        "child_result": _ok_result(),
        "parent_state": parent_state,
        "parent_decision": {"decision_type": "display_only"},
    })

    assert repr(parent_state) == before
    assert result.evidence["memory_mutated"] is False
    assert result.evidence["checkpoint_mutated"] is False
    assert result.evidence["context_mutated"] is False
    assert result.evidence["prompt_mutated"] is False
    assert result.evidence["messages_mutated"] is False


def test_old_adjudication_auto_accept_helper_is_not_used_by_v0_production_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_legacy_adjudication(monkeypatch, "legacy adjudicate_result was called")

    result = route_v0(payload={"child_result": _ok_result()})

    assert result.payload["parent_decision_status"] == "pending"
    assert result.evidence["legacy_adjudication_called"] is False


def test_can_emit_parent_action_false_prevents_direct_parent_action() -> None:
    result = route_v0(payload={
        "profile_capabilities": {"can_emit_parent_action": False},
        "child_result": {
            "parent_action": {"type": "memory.write", "content": "RAW_PARENT_ACTION"}
        },
    })

    assert result.status in {"failed", "policy_blocked", "success"}
    assert result.evidence["can_emit_parent_action"] is False
    assert result.evidence["direct_parent_action_emitted"] is False
    assert result.payload["parent_decision_status"] != "pending"
    assert "RAW_PARENT_ACTION" not in repr(result.evidence)
