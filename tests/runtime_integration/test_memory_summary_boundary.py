"""Memory v0 working_summary scratchpad boundary tests."""

from __future__ import annotations

import json


def _serialized(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def test_u5_working_summary_helper_records_safe_lifecycle_evidence(monkeypatch) -> None:
    from agent import evidence_recorder
    from agent.memory import set_working_summary_scratchpad
    from agent.state import create_agent_state

    calls: list[dict] = []
    monkeypatch.setattr(
        evidence_recorder,
        "record_evidence",
        lambda **kwargs: calls.append(kwargs)
        or {"data": {"metadata": kwargs.get("metadata", {})}},
    )

    state = create_agent_state(system_prompt="test")
    set_working_summary_scratchpad(
        state,
        "用户完成了扫描，api_key=sk-test-secret-1234567890",
        reason="test_create",
    )
    set_working_summary_scratchpad(state, "用户完成了复核", reason="test_update")
    set_working_summary_scratchpad(state, None, reason="test_clear")

    event_types = [
        call["metadata"]["event_type"]
        for call in calls
        if call.get("subsystem") == "memory"
    ]
    assert "memory.summary_redacted" in event_types
    assert "memory.summary_created" in event_types
    assert "memory.summary_updated" in event_types
    assert "memory.summary_cleared" in event_types
    assert state.memory.working_summary is None

    serialized = _serialized(calls)
    assert "sk-test-secret-1234567890" not in serialized
    assert "api_key=sk-test-secret-1234567890" not in serialized


def test_u5_checkpoint_restores_working_summary_with_safe_restore_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    from agent import evidence_recorder
    from agent.checkpoint import load_checkpoint_to_state, save_checkpoint
    from agent.state import create_agent_state

    calls: list[dict] = []
    monkeypatch.setattr(
        evidence_recorder,
        "record_evidence",
        lambda **kwargs: calls.append(kwargs)
        or {"data": {"metadata": kwargs.get("metadata", {})}},
    )

    checkpoint_path = tmp_path / "checkpoint.json"
    src = create_agent_state(system_prompt="test")
    src.memory.working_summary = (
        "上一轮已经分析完日志，token=sk-test-secret-1234567890"
    )
    save_checkpoint(src, path=checkpoint_path)

    on_disk = checkpoint_path.read_text(encoding="utf-8")
    assert "sk-test-secret-1234567890" not in on_disk
    assert "token=sk-test-secret-1234567890" not in on_disk

    dst = create_agent_state(system_prompt="test")
    assert load_checkpoint_to_state(dst, path=checkpoint_path)
    assert dst.memory.working_summary is not None
    assert "sk-test-secret-1234567890" not in dst.memory.working_summary
    assert "[REDACTED" in dst.memory.working_summary

    event_types = [
        call["metadata"]["event_type"]
        for call in calls
        if call.get("subsystem") == "memory"
    ]
    assert "memory.summary_restored" in event_types
    serialized = _serialized(calls)
    assert "sk-test-secret-1234567890" not in serialized
    assert "token=sk-test-secret-1234567890" not in serialized


def test_u5_working_summary_remains_hidden_scratchpad_not_memory_record() -> None:
    from agent.context_builder import build_execution_messages
    from agent.memory_runtime import MemoryRuntime
    from agent.memory_store import InMemoryMemoryStore
    from agent.state import create_agent_state

    state = create_agent_state(system_prompt="")
    state.memory.working_summary = "hidden scratchpad context"

    messages = build_execution_messages(state)
    assert any("hidden scratchpad context" in str(msg) for msg in messages)

    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    records = runtime.list_records()
    assert records == ()
    assert "hidden scratchpad context" not in str(records)
