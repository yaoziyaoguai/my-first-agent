"""Memory v0 evidence schema / safe summary helpers.

这些测试只覆盖 U2a 的 schema/helper 行为，不要求 runtime 生命周期已经接线。
"""

from __future__ import annotations

import json


def _serialized(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def test_u2a_memory_event_taxonomy_matches_v0_plan() -> None:
    from agent.evidence_recorder import (
        MEMORY_EVENT_TYPES_RESERVED,
        MEMORY_EVENT_TYPES_V0,
    )

    required = {
        "memory.recall.requested",
        "memory.recall.completed",
        "memory.recall.skipped",
        "memory.recall.failed",
        "memory.proposed",
        "memory.proposal_surfaced",
        "memory.proposal_skipped",
        "memory.proposal_deferred",
        "memory.proposal_expired",
        "memory.proposal_failed",
        "memory.approved",
        "memory.rejected",
        "memory.policy_blocked",
        "memory.sensitive_blocked",
        "memory.redacted",
        "memory.committed",
        "memory.updated",
        "memory.deleted",
        "memory.delete_requested",
        "memory.commit_failed",
        "memory.update_failed",
        "memory.delete_failed",
        "memory.backend_selected",
        "memory.backend_warning",
        "memory.reference_saved",
        "memory.reference_checked",
        "memory.reference_mismatch",
        "memory.restored",
        "memory.restore_skipped",
        "memory.summary_created",
        "memory.summary_updated",
        "memory.summary_cleared",
        "memory.summary_redacted",
        "memory.summary_restored",
        "memory.child_request_received",
        "memory.child_request_deferred",
        "memory.child_request_rejected",
    }

    assert required.issubset(MEMORY_EVENT_TYPES_V0)
    assert "memory.child_proposal_created" not in MEMORY_EVENT_TYPES_V0
    assert "memory.child_proposal_created" in MEMORY_EVENT_TYPES_RESERVED


def test_u2a_memory_id_hash_is_stable_and_does_not_expose_raw_id() -> None:
    from agent.evidence_recorder import hash_memory_identifier

    raw_id = "memory:fake:raw-record-id"
    first = hash_memory_identifier(raw_id)
    second = hash_memory_identifier(raw_id)

    assert first == second
    assert first.startswith("memid:")
    assert raw_id not in first
    assert "raw-record-id" not in first


def test_u2a_safe_metadata_redacts_forbidden_fields_and_hashes_ids() -> None:
    from agent.evidence_recorder import build_memory_evidence_metadata

    raw_record_id = "memory:fake:raw-record-id"
    raw_memory_id = "memory:fake:raw-memory-id"
    metadata = build_memory_evidence_metadata(
        event_type="memory.deleted",
        operation="delete",
        decision="allowed",
        source_type="explicit_user",
        record_id=raw_record_id,
        memory_id=raw_memory_id,
        raw_fields={
            "content": "RAW MEMORY TEXT SHOULD NOT LOG",
            "user_prompt": "RAW USER PROMPT SHOULD NOT LOG",
            "assistant_prompt": "RAW ASSISTANT PROMPT SHOULD NOT LOG",
            "tool_result": "RAW TOOL RESULT SHOULD NOT LOG",
            "file_content": "RAW FILE CONTENT SHOULD NOT LOG",
            "record_id": raw_record_id,
            "memory_id": raw_memory_id,
            "key": "raw_child_key",
            "value_preview": "RAW CHILD PAYLOAD SHOULD NOT LOG",
            "path": "/Users/jinkun.wang/work_space/my-first-agent/private.txt",
            "api_key": "OPENAI_API_KEY=sk-test-secret-1234567890",
        },
    )
    serialized = _serialized(metadata)

    assert metadata["event_type"] == "memory.deleted"
    assert metadata["memory_id_hash"].startswith("memid:")
    assert metadata["record_id_hash"].startswith("memid:")
    assert metadata["redacted"] is True
    assert metadata["sensitive_category_detected"] is True

    forbidden_values = (
        "RAW MEMORY TEXT SHOULD NOT LOG",
        "RAW USER PROMPT SHOULD NOT LOG",
        "RAW ASSISTANT PROMPT SHOULD NOT LOG",
        "RAW TOOL RESULT SHOULD NOT LOG",
        "RAW FILE CONTENT SHOULD NOT LOG",
        "RAW CHILD PAYLOAD SHOULD NOT LOG",
        "/Users/jinkun.wang/work_space/my-first-agent/private.txt",
        "OPENAI_API_KEY=sk-test-secret-1234567890",
        raw_record_id,
        raw_memory_id,
        "raw_child_key",
        "value_preview",
    )
    for forbidden in forbidden_values:
        assert forbidden not in serialized


def test_u2a_child_payload_uses_hashes_not_raw_key_or_preview() -> None:
    from agent.evidence_recorder import build_memory_evidence_metadata

    metadata = build_memory_evidence_metadata(
        event_type="memory.child_request_received",
        operation="propose",
        source_type="child_agent",
        decision="blocked",
        child_payload="RAW CHILD PAYLOAD SHOULD NOT LOG",
        child_key="raw_child_key",
        count=1,
        reason="child_memory_deferred",
    )
    serialized = _serialized(metadata)

    assert metadata["child_payload_hash"].startswith("mempayload:")
    assert metadata["key_hash"].startswith("memkey:")
    assert metadata["redacted"] is True
    assert "RAW CHILD PAYLOAD SHOULD NOT LOG" not in serialized
    assert "raw_child_key" not in serialized
    assert "value_preview" not in serialized


def test_u2a_record_memory_evidence_uses_existing_evidence_recorder(monkeypatch) -> None:
    from agent import evidence_recorder

    calls: list[dict] = []

    def fake_record_evidence(**kwargs):
        calls.append(kwargs)
        return {"data": {"metadata": kwargs.get("metadata", {})}}

    monkeypatch.setattr(evidence_recorder, "record_evidence", fake_record_evidence)

    envelope = evidence_recorder.record_memory_evidence(
        event_type="memory.recall.completed",
        operation="recall",
        phase="end",
        status="success",
        source_type="explicit_user",
        decision="allowed",
        count=2,
        memory_id="memory:fake:raw-recall-id",
        raw_fields={"content": "RAW MEMORY TEXT SHOULD NOT LOG"},
    )

    assert calls
    call = calls[0]
    assert call["subsystem"] == "memory"
    assert call["operation"] == "recall.completed"
    assert call["metadata"]["event_type"] == "memory.recall.completed"
    assert call["metadata"]["memory_id_hash"].startswith("memid:")
    assert "RAW MEMORY TEXT SHOULD NOT LOG" not in _serialized(envelope)
