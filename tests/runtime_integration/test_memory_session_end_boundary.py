"""Post-Memory hardening tests for legacy session-end memory boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

RAW_MEMORY = "RAW_SESSION_MEMORY_CONTENT_SHOULD_NOT_PERSIST"


class _DummyState:
    def __init__(self, messages: list[dict] | None = None) -> None:
        self.conversation = SimpleNamespace(messages=list(messages or []))
        self.task = SimpleNamespace(current_plan=None)


def test_u0_resolve_memory_root_does_not_silently_fallback_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Unconfigured legacy memory root resolver must fail closed, not HOME."""
    monkeypatch.delenv("MEMORY_STORE_ROOT", raising=False)
    monkeypatch.delenv("MEMORY_ROOT", raising=False)
    fake_home = tmp_path / "fake-home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    from agent.memory import _resolve_memory_root

    assert _resolve_memory_root() is None
    assert not (fake_home / ".my-first-agent" / "memory").exists()


def test_session_finalize_freezes_legacy_extraction_without_pending_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Normal quit must not call legacy extraction or create raw pending files."""
    import agent.session as session

    memory_root = tmp_path / "memory"
    monkeypatch.setenv("MEMORY_STORE_ROOT", str(memory_root))
    monkeypatch.setattr(
        "agent.core.get_state",
        lambda: _DummyState([{"role": "user", "content": RAW_MEMORY}]),
    )
    monkeypatch.setattr("agent.core.client", object())
    monkeypatch.setattr(session, "save_session_snapshot", lambda _messages: None)
    monkeypatch.setattr(session, "save_checkpoint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session, "_record_session_end", lambda **_kwargs: None)

    def fail_legacy_extraction(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("legacy session-end extraction must remain frozen")

    monkeypatch.setattr(session, "extract_memories_from_session", fail_legacy_extraction)

    summary = session.finalize_session()

    assert summary["decision"] in {"skipped", "deferred"}
    assert summary["reason"] == "legacy_session_end_extraction_disabled"
    assert not (memory_root / "_pending").exists()
    assert RAW_MEMORY not in json.dumps(summary, ensure_ascii=False)


def test_double_interrupt_freezes_legacy_extraction_without_pending_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ctrl+C x2 must share the same frozen boundary as normal quit."""
    import agent.session as session

    memory_root = tmp_path / "memory"
    monkeypatch.setenv("MEMORY_STORE_ROOT", str(memory_root))
    monkeypatch.setattr(
        "agent.core.get_state",
        lambda: _DummyState([{"role": "user", "content": RAW_MEMORY}]),
    )
    monkeypatch.setattr("agent.core.client", object())
    monkeypatch.setattr(session, "save_session_snapshot", lambda _messages: None)
    monkeypatch.setattr(session, "save_checkpoint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session, "_record_session_end", lambda **_kwargs: None)

    def fail_legacy_extraction(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("legacy session-end extraction must remain frozen")

    monkeypatch.setattr(session, "extract_memories_from_session", fail_legacy_extraction)

    summary = session.handle_double_interrupt()

    assert summary["decision"] in {"skipped", "deferred"}
    assert summary["reason"] == "legacy_session_end_extraction_disabled"
    assert not (memory_root / "_pending").exists()
    assert RAW_MEMORY not in json.dumps(summary, ensure_ascii=False)


def test_legacy_extract_summary_uses_safe_root_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Legacy helper summaries must not expose raw filesystem root paths."""
    from agent.memory import extract_memories_from_session
    from agent.memory_fs_store import FilesystemMemoryStore

    root = tmp_path / "durable-memory"
    store = FilesystemMemoryStore(root_dir=root)

    summary = extract_memories_from_session([], None, None, store=store)
    serialized = json.dumps(summary, ensure_ascii=False, default=str)

    assert "store_root" not in summary
    assert summary["root_redacted"] is True
    assert summary["root_hash"].startswith("memroot:")
    assert summary["path_hash"].startswith("path:")
    assert summary["root_kind"] in {"tmp", "absolute", "relative", "home", "unknown"}
    assert str(root) not in serialized


def test_legacy_t1_pending_does_not_write_home_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """T1 pending persistence cannot use HOME as an implicit durable root."""
    monkeypatch.delenv("MEMORY_STORE_ROOT", raising=False)
    monkeypatch.delenv("MEMORY_ROOT", raising=False)
    fake_home = tmp_path / "fake-home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    from agent.memory import _persist_t1_pending_proposals

    with pytest.raises(RuntimeError, match="durable_memory_root_not_configured"):
        _persist_t1_pending_proposals([
            {
                "content": RAW_MEMORY,
                "evidence": "raw evidence",
                "confidence": 0.95,
                "importance": 4,
                "rationale": "test",
                "memory_type": "episodic",
                "source_type": "agent_suggested",
                "governance_route": "T1",
                "approval_status": "pending",
                "scope": "user",
                "source": "session_end_extraction",
                "created_at": "2026-06-09T00:00:00Z",
            }
        ])

    assert not (fake_home / ".my-first-agent" / "memory" / "_pending").exists()


def test_pending_review_helpers_do_not_fallback_home_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Review/read helpers must not discover pending proposals from HOME by default."""
    monkeypatch.delenv("MEMORY_STORE_ROOT", raising=False)
    monkeypatch.delenv("MEMORY_ROOT", raising=False)
    fake_home = tmp_path / "fake-home"
    home_pending = fake_home / ".my-first-agent" / "memory" / "_pending"
    home_pending.mkdir(parents=True)
    (home_pending / "t1_home.json").write_text(
        json.dumps({
            "content": RAW_MEMORY,
            "approval_status": "pending",
            "created_at": "2026-06-09T00:00:00Z",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    from agent.memory_review import count_pending_proposals, list_pending_proposals

    assert list_pending_proposals(memory_root=None) == []
    assert count_pending_proposals(memory_root=None) == 0


def test_pending_dispatch_helpers_do_not_write_home_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Emergence/consolidation pending dispatch must be explicit-root only."""
    monkeypatch.delenv("MEMORY_STORE_ROOT", raising=False)
    monkeypatch.delenv("MEMORY_ROOT", raising=False)
    fake_home = tmp_path / "fake-home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    from agent.memory_consolidation import ConsolidationCandidate, ConsolidationType
    from agent.memory_consolidation_review import (
        dispatch_consolidation_candidates_to_pending_review,
    )
    from agent.memory_emergence import (
        ProceduralCandidate,
        dispatch_procedural_candidates_to_pending_review,
    )

    procedural = ProceduralCandidate(
        content="[行为约束] 先查日志",
        memory_type="procedural",
        source_evidence=("ev1", "ev2", "ev3"),
        correction_pattern="先查日志",
        correction_type="process_order",
        scope="debugging",
        confidence=0.8,
        governance_route="T1",
        evidence_summary="三条 evidence 都指向先查日志",
        created_at="2026-06-09T00:00:00Z",
    )
    consolidation = ConsolidationCandidate(
        content="用户偏好 pytest",
        memory_type="semantic",
        source_evidence=("ep1", "ep2", "ep3"),
        consolidation_type=ConsolidationType.PATTERN_DETECTION,
        confidence=0.85,
        governance_route="T1",
        evidence_summary="三条 episodic evidence 都指向 pytest 偏好",
        created_at="2026-06-09T00:00:00Z",
    )

    procedural_result = dispatch_procedural_candidates_to_pending_review([procedural])
    consolidation_result = dispatch_consolidation_candidates_to_pending_review(
        [consolidation],
    )

    assert procedural_result.dispatched == 0
    assert consolidation_result.dispatched == 0
    assert procedural_result.warnings == ("durable_memory_root_not_configured",)
    assert consolidation_result.warnings == ("durable_memory_root_not_configured",)
    assert not (fake_home / ".my-first-agent" / "memory" / "_pending").exists()


def test_memory_maintenance_cli_requires_explicit_root_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Maintenance CLI must not choose HOME as an implicit filesystem root."""
    monkeypatch.delenv("MEMORY_STORE_ROOT", raising=False)
    monkeypatch.delenv("MEMORY_ROOT", raising=False)
    fake_home = tmp_path / "fake-home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    from agent.memory_maintenance_cli import _memory_root_arg

    with pytest.raises(SystemExit, match="MEMORY_STORE_ROOT"):
        _memory_root_arg(None)
    assert not (fake_home / ".my-first-agent" / "memory").exists()
