"""Post-Memory hardening tests for L2 inline extraction boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

RAW_L2_TEXT = "RAW_L2_TRANSCRIPT_SHOULD_NOT_LOG_OR_WRITE_HOME"


def _state(messages: list[dict] | None = None) -> SimpleNamespace:
    return SimpleNamespace(conversation=SimpleNamespace(messages=list(messages or [])))


def test_l2_inline_without_durable_root_is_explicitly_skipped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Unconfigured L2 inline must not construct a store, write HOME, or fail silently."""
    import agent.core as core

    monkeypatch.delenv("MEMORY_STORE_ROOT", raising=False)
    monkeypatch.delenv("MEMORY_ROOT", raising=False)
    fake_home = tmp_path / "fake-home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    def fail_store_construction(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("core.py must not construct FilesystemMemoryStore directly")

    monkeypatch.setattr(
        "agent.memory_fs_store.FilesystemMemoryStore",
        fail_store_construction,
    )

    summary = core._maybe_run_l2_inline(
        _state([{"role": "user", "content": RAW_L2_TEXT}]),
    )

    assert summary["decision"] in {"skipped", "deferred"}
    assert summary["reason"] == "durable_memory_root_not_configured"
    assert summary["redacted"] is True
    assert RAW_L2_TEXT not in json.dumps(summary, ensure_ascii=False)
    assert not (fake_home / ".my-first-agent" / "memory").exists()


def test_l2_inline_with_configured_root_is_deferred_without_store_or_pending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Configured automatic L2 must stay deferred and must not enter write paths."""
    import agent.core as core

    root = tmp_path / "memory"
    monkeypatch.setenv("MEMORY_STORE_ROOT", str(root))
    evidence_events: list[dict] = []
    store_constructions: list[dict] = []
    extraction_calls: list[dict] = []

    def fail_store_construction(*args, **kwargs):  # noqa: ANN002, ANN003
        store_constructions.append({"args": args, "kwargs": kwargs})
        raise AssertionError("automatic L2 must not construct standalone store")

    def fail_extraction(*args, **kwargs):  # noqa: ANN002, ANN003
        extraction_calls.append({"args": args, "kwargs": kwargs})
        raise AssertionError("automatic L2 must not execute extraction/write path")

    def record_evidence(**kwargs):
        evidence_events.append(kwargs)

    monkeypatch.setattr(
        "agent.memory_fs_store.FilesystemMemoryStore",
        fail_store_construction,
    )
    monkeypatch.setattr("agent.memory_l2.run_l2_inline_extraction", fail_extraction)
    monkeypatch.setattr("agent.evidence_recorder.record_memory_evidence", record_evidence)

    summary = core._maybe_run_l2_inline(
        _state([{"role": "user", "content": RAW_L2_TEXT}]),
    )

    assert summary["decision"] in {"skipped", "deferred"}
    assert summary["reason"] == "l2_inline_automatic_path_deferred"
    assert summary["redacted"] is True
    assert summary["total_proposals"] == 0
    assert summary["t1_pending"] == 0
    assert summary["t2_auto_retained"] == 0
    assert summary.get("root_hash")
    assert summary.get("path_kind")
    assert "store_root" not in summary
    assert not store_constructions
    assert not extraction_calls
    assert not root.exists()
    assert not (root / "_pending").exists()

    serialized = json.dumps(
        {"summary": summary, "evidence": evidence_events},
        ensure_ascii=False,
        default=str,
    )
    assert RAW_L2_TEXT not in serialized
    assert str(root) not in serialized


def test_filesystem_store_fail_closed_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """FilesystemMemoryStore itself must not restore HOME fallback."""
    monkeypatch.delenv("MEMORY_STORE_ROOT", raising=False)
    monkeypatch.delenv("MEMORY_ROOT", raising=False)
    from agent.memory_fs_store import FilesystemMemoryStore

    with pytest.raises(ValueError, match="MEMORY_STORE_ROOT"):
        FilesystemMemoryStore()
