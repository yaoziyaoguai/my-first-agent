"""Memory v0 lifecycle evidence wiring tests."""

from __future__ import annotations

import json


def _serialized(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _memory_evidence_only(evidence: dict) -> dict:
    result = {}
    for key, value in evidence.items():
        if not key.startswith("memory_"):
            continue
        result[key] = dict(value) if hasattr(value, "items") else value
    return result


def test_u2b_default_memory_runtime_logger_records_safe_lifecycle_evidence(monkeypatch) -> None:
    from agent import evidence_recorder
    from agent.memory_confirmation import MemoryConfirmationChoice
    from agent.memory_runtime import MemoryEvaluationAction, MemoryRuntime
    from agent.memory_store import InMemoryMemoryStore

    calls: list[dict] = []

    def fake_record_evidence(**kwargs):
        calls.append(kwargs)
        return {"data": {"metadata": kwargs.get("metadata", {})}}

    monkeypatch.setattr(evidence_recorder, "record_evidence", fake_record_evidence)

    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    result = runtime.evaluate_user_text("remember that RAW MEMORY TEXT SHOULD NOT LOG")
    assert result.action is MemoryEvaluationAction.CONFIRMATION_REQUIRED
    runtime.resolve_confirmation(result.candidate_id, MemoryConfirmationChoice.ACCEPT)

    event_types = [call["metadata"]["event_type"] for call in calls]
    assert "memory.proposed" in event_types
    assert "memory.approved" in event_types
    serialized = _serialized(calls)
    assert "RAW MEMORY TEXT SHOULD NOT LOG" not in serialized
    assert result.candidate_id not in serialized


def test_u2b_blocked_memory_records_sensitive_blocked_without_secret(monkeypatch) -> None:
    from agent import evidence_recorder
    from agent.memory_runtime import MemoryRuntime
    from agent.memory_store import InMemoryMemoryStore

    calls: list[dict] = []
    monkeypatch.setattr(
        evidence_recorder,
        "record_evidence",
        lambda **kwargs: calls.append(kwargs) or {"data": {"metadata": kwargs.get("metadata", {})}},
    )

    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    runtime.evaluate_user_text("remember that my api key is sk-test-secret-1234567890")

    event_types = [call["metadata"]["event_type"] for call in calls]
    assert "memory.sensitive_blocked" in event_types
    serialized = _serialized(calls)
    assert "sk-test-secret-1234567890" not in serialized
    assert "api key is" not in serialized


def test_u2b_recall_handler_evidence_contains_requested_and_completed_safe_metadata() -> None:
    from agent.runtime_integration import (
        ActionHandlerRegistry,
        RuntimeActionDispatcher,
        RuntimeActionType,
    )
    from agent.runtime_integration.memory_recall import MemoryRecallHandler
    from agent.runtime_integration.schema import RuntimeActionRequest
    from tests.runtime_integration.test_memory_recall_l3 import (
        _approved_record,
        _make_store_with_records,
    )

    store = _make_store_with_records(
        _approved_record("memory:fake:raw-recall-id", "RAW MEMORY TEXT SHOULD NOT LOG"),
    )
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.MEMORY_RECALL, MemoryRecallHandler(store=store))
    dispatcher = RuntimeActionDispatcher(registry=registry)

    result = dispatcher.route(RuntimeActionRequest(
        action_type=RuntimeActionType.MEMORY_RECALL,
        source="test",
        parent_trace_id="",
        payload={},
    ))

    evidence = dict(result.evidence)
    assert evidence["memory_recall_requested"]["event_type"] == "memory.recall.requested"
    assert evidence["memory_recall_completed"]["event_type"] == "memory.recall.completed"
    assert evidence["memory_recall_completed"]["count"] == 1
    serialized = _serialized(_memory_evidence_only(evidence))
    assert "RAW MEMORY TEXT SHOULD NOT LOG" not in serialized
    assert "memory:fake:raw-recall-id" not in serialized


def test_recall_handler_exception_emits_memory_recall_failed_safe_evidence() -> None:
    from agent.runtime_integration import (
        ActionHandlerRegistry,
        RuntimeActionDispatcher,
        RuntimeActionType,
    )
    from agent.runtime_integration.memory_recall import MemoryRecallHandler
    from agent.runtime_integration.schema import RuntimeActionRequest

    class BrokenStore:
        def list_records(self):
            raise RuntimeError("RAW MEMORY TEXT SHOULD NOT LOG")

    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.MEMORY_RECALL, MemoryRecallHandler(store=BrokenStore()))
    dispatcher = RuntimeActionDispatcher(registry=registry)

    result = dispatcher.route(RuntimeActionRequest(
        action_type=RuntimeActionType.MEMORY_RECALL,
        source="test",
        parent_trace_id="",
        payload={},
    ))

    evidence = dict(result.evidence)
    assert result.status == "failed"
    assert evidence["memory_recall_requested"]["event_type"] == "memory.recall.requested"
    assert evidence["memory_recall_failed"]["event_type"] == "memory.recall.failed"
    assert evidence["memory_recall_failed"]["reason"] == "snapshot_build_failed"
    serialized = _serialized(_memory_evidence_only(evidence))
    assert "RAW MEMORY TEXT SHOULD NOT LOG" not in serialized


def test_u2b_forget_handler_hashes_record_id_and_records_delete_events() -> None:
    from agent.memory_runtime import MemoryRuntime
    from agent.memory_store import InMemoryMemoryStore
    from agent.runtime_integration import (
        ActionHandlerRegistry,
        RuntimeActionDispatcher,
        RuntimeActionType,
    )
    from agent.runtime_integration.memory_forget import MemoryForgetHandler
    from agent.runtime_integration.schema import RuntimeActionRequest

    raw_record_id = "memory:fake:raw-delete-id"
    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.MEMORY_FORGET, MemoryForgetHandler(memory_runtime=runtime))
    dispatcher = RuntimeActionDispatcher(registry=registry)

    result = dispatcher.route(RuntimeActionRequest(
        action_type=RuntimeActionType.MEMORY_FORGET,
        source="test",
        parent_trace_id="",
        payload={"record_id": raw_record_id},
    ))

    evidence = dict(result.evidence)
    assert evidence["memory_delete_requested"]["event_type"] == "memory.delete_requested"
    assert evidence["memory_delete_completed"]["event_type"] in {
        "memory.deleted",
        "memory.delete_failed",
    }
    serialized = _serialized(_memory_evidence_only(evidence))
    assert raw_record_id not in serialized
    assert "record_id_hash" in serialized


def test_update_not_found_emits_memory_update_failed_safe_evidence(monkeypatch) -> None:
    from agent import evidence_recorder
    from agent.memory_confirmation import MemoryConfirmationChoice
    from agent.memory_runtime import MemoryEvaluationAction, MemoryRuntime
    from agent.memory_store import InMemoryMemoryStore

    calls: list[dict] = []
    monkeypatch.setattr(
        evidence_recorder,
        "record_evidence",
        lambda **kwargs: calls.append(kwargs) or {"data": {"metadata": kwargs.get("metadata", {})}},
    )
    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    pending = runtime.evaluate_user_text("update memory: RAW MEMORY TEXT SHOULD NOT LOG")
    result = runtime.resolve_confirmation(
        pending.candidate_id,
        MemoryConfirmationChoice.ACCEPT,
    )

    assert result.action is MemoryEvaluationAction.REJECTED
    assert any(
        call.get("metadata", {}).get("event_type") == "memory.update_failed"
        and call.get("metadata", {}).get("reason") == "record_not_found"
        for call in calls
    )
    serialized = _serialized(calls)
    assert "RAW MEMORY TEXT SHOULD NOT LOG" not in serialized
    assert pending.candidate_id not in serialized


def test_u9_turn_end_no_action_records_proposal_skipped_evidence() -> None:
    from agent.runtime_integration import (
        ActionHandlerRegistry,
        RuntimeActionDispatcher,
        RuntimeActionType,
    )
    from agent.runtime_integration.memory_hook import MemoryTurnEndProposalHandler
    from agent.runtime_integration.schema import RuntimeActionRequest

    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
        MemoryTurnEndProposalHandler(),
    )
    dispatcher = RuntimeActionDispatcher(registry=registry)

    result = dispatcher.route(RuntimeActionRequest(
        action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
        source="test",
        parent_trace_id="",
        payload={
            "user_message": "今天天气不错",
            "assistant_response": "是的。",
        },
    ))

    evidence = dict(result.evidence)
    assert result.payload["disposition"] == "no_action"
    assert evidence["memory_proposal_skipped"]["event_type"] == "memory.proposal_skipped"
    assert evidence["memory_proposal_skipped"]["decision"] == "skipped"
    assert "memory_proposal_deferred" not in evidence
    serialized = _serialized(_memory_evidence_only(evidence))
    assert "今天天气不错" not in serialized
    assert "是的。" not in serialized


def test_u9_turn_end_pending_review_records_proposal_deferred_without_raw_candidate() -> None:
    from agent.runtime_integration import (
        ActionHandlerRegistry,
        RuntimeActionDispatcher,
        RuntimeActionType,
    )
    from agent.runtime_integration.memory_hook import MemoryTurnEndProposalHandler
    from agent.runtime_integration.schema import RuntimeActionRequest

    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
        MemoryTurnEndProposalHandler(),
    )
    dispatcher = RuntimeActionDispatcher(registry=registry)

    raw_memory_text = "RAW MEMORY TEXT SHOULD NOT LOG"
    result = dispatcher.route(RuntimeActionRequest(
        action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
        source="test",
        parent_trace_id="",
        payload={
            "user_message": f"remember that {raw_memory_text}",
            "assistant_response": "ok",
        },
    ))

    evidence = dict(result.evidence)
    assert result.payload["disposition"] == "proposed"
    assert result.payload["proposal_id"]
    assert result.payload["proposal_preview"]
    assert evidence["memory_proposed"]["event_type"] == "memory.proposed"
    assert evidence["memory_proposal_deferred"]["event_type"] == (
        "memory.proposal_deferred"
    )
    assert evidence["memory_proposal_deferred"]["decision"] == "deferred"
    assert "memory_proposal_skipped" not in evidence

    serialized = _serialized(_memory_evidence_only(evidence))
    assert raw_memory_text not in serialized
    assert result.payload["proposal_id"] not in serialized
    assert result.payload["proposal_preview"] not in serialized
    assert "proposal_id" not in serialized
    assert "proposal_preview" not in serialized
    assert "memory_id_hash" in serialized
