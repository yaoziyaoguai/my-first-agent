"""Memory v0 checkpoint / MemoryStore consistency tests."""

from __future__ import annotations

import json


def test_u4_checkpoint_saves_memory_reference_not_raw_records(tmp_path) -> None:
    from agent.checkpoint import save_checkpoint
    from agent.memory_runtime import build_memory_store_reference
    from agent.state import create_agent_state

    checkpoint_path = tmp_path / "checkpoint.json"
    state = create_agent_state(system_prompt="test")
    state.memory.long_term_notes = ["RAW MEMORY TEXT SHOULD NOT LOG"]
    state.memory.memory_store_reference = build_memory_store_reference(
        backend="filesystem",
        namespace="default",
        root_kind="test_tmp",
        root="/tmp/test-memory-root",
        record_ids=("memory:fake:raw-record-id",),
        record_count=1,
    )

    save_checkpoint(state, path=checkpoint_path)

    data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    serialized = json.dumps(data, ensure_ascii=False, sort_keys=True)

    assert data["memory"]["long_term_notes"] == []
    ref = data["memory"]["memory_store_reference"]
    assert ref["backend"] == "filesystem"
    assert ref["root_kind"] == "test_tmp"
    assert ref["record_count"] == 1
    assert "root_hash" in ref
    assert "last_seen_ids_hash" in ref
    assert "RAW MEMORY TEXT SHOULD NOT LOG" not in serialized
    assert "memory:fake:raw-record-id" not in serialized
    assert "/tmp/test-memory-root" not in serialized


def test_u4_resume_restores_memory_reference_and_records_checked_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    from agent.checkpoint import load_checkpoint_to_state, save_checkpoint
    from agent.memory_runtime import build_memory_store_reference
    from agent.state import create_agent_state

    calls: list[dict] = []
    monkeypatch.setattr(
        "agent.evidence_recorder.record_evidence",
        lambda **kwargs: calls.append(kwargs) or {"data": {"metadata": kwargs.get("metadata", {})}},
    )

    checkpoint_path = tmp_path / "checkpoint.json"
    src = create_agent_state(system_prompt="test")
    src.memory.memory_store_reference = build_memory_store_reference(
        backend="in_memory",
        namespace="default",
        root_kind="session",
        record_count=0,
    )
    save_checkpoint(src, path=checkpoint_path)

    dst = create_agent_state(system_prompt="test")
    assert load_checkpoint_to_state(dst, path=checkpoint_path)

    assert dst.memory.memory_store_reference["backend"] == "in_memory"
    memory_events = [
        call for call in calls
        if call.get("subsystem") == "memory"
        and call.get("metadata", {}).get("event_type") == "memory.reference_checked"
    ]
    assert memory_events


def test_u4_resume_detects_reference_mismatch_without_overwriting_memory_store(
    tmp_path,
    monkeypatch,
) -> None:
    from agent.checkpoint import load_checkpoint_to_state
    from agent.state import create_agent_state

    calls: list[dict] = []
    monkeypatch.setattr(
        "agent.evidence_recorder.record_evidence",
        lambda **kwargs: calls.append(kwargs) or {"data": {"metadata": kwargs.get("metadata", {})}},
    )

    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint = {
        "meta": {"schema_version": "checkpoint.v1"},
        "task": {"status": "running"},
        "memory": {
            "working_summary": None,
            "long_term_notes": [
                {"id": "memory:fake:raw-record-id", "content": "RAW MEMORY TEXT SHOULD NOT LOG"},
            ],
            "memory_store_reference": {
                "backend": "filesystem",
                "namespace": "default",
                "root_kind": "configured",
                "root_hash": "memroot:old",
                "store_revision": "rev-old",
                "record_count": 7,
                "last_seen_ids_hash": "memids:old",
            },
        },
        "conversation": {"messages": []},
    }
    checkpoint_path.write_text(json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8")

    dst = create_agent_state(system_prompt="test")
    assert load_checkpoint_to_state(dst, path=checkpoint_path)

    assert dst.memory.long_term_notes == []
    serialized_state = json.dumps(dst.memory.__dict__, ensure_ascii=False, sort_keys=True)
    assert "RAW MEMORY TEXT SHOULD NOT LOG" not in serialized_state
    assert "memory:fake:raw-record-id" not in serialized_state
    event_types = [call.get("metadata", {}).get("event_type") for call in calls]
    assert "memory.reference_mismatch" in event_types
    assert "memory.restore_skipped" in event_types
