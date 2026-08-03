from __future__ import annotations

from pathlib import Path

from agent.memory.contracts import ProviderTrustProfile
from agent.memory.source import MemoryContextSource
from agent.memory.store import MemoryStore
from agent.runtime.contracts import ContextQuery, ContextSourceLimits

SCOPE = "scope-digest-1"
PROFILE = ProviderTrustProfile("ops-profile", "openai_compatible", "https://provider.example")


def _query(text: str, scope: str = SCOPE) -> ContextQuery:
    return ContextQuery(
        conversation_id="c1",
        run_id="r1",
        user_text=text,
        workspace_scope_digest=scope,
        source_limits=ContextSourceLimits(max_tokens=10_000, max_items=8),
    )


def _store_with(tmp_path: Path, *records: str) -> MemoryStore:
    path = tmp_path / "memory"
    path.mkdir(mode=0o700, exist_ok=True)
    store = MemoryStore.create(path / "store.json", workspace_scope_digest=SCOPE, profile=PROFILE)
    for content in records:
        store.remember(content)
    return store


def test_lexical_match_ranks_relevant_record_first(tmp_path: Path) -> None:
    store = _store_with(tmp_path, "the build uses pyc", "favorite color is blue")
    source = MemoryContextSource(store)

    snapshot = source.snapshot(_query("pyc build"))

    assert snapshot.candidates
    assert "pyc" in snapshot.candidates[0].content
    assert snapshot.source_name == "memory"
    assert snapshot.snapshot_digest


def test_empty_query_returns_no_candidates(tmp_path: Path) -> None:
    store = _store_with(tmp_path, "something remembered")
    source = MemoryContextSource(store)

    snapshot = source.snapshot(_query(""))

    assert snapshot.candidates == ()


def test_cross_scope_records_excluded(tmp_path: Path) -> None:
    store = _store_with(tmp_path, "scoped secret")
    source = MemoryContextSource(store)

    snapshot = source.snapshot(_query("scoped", scope="other-scope"))
    assert snapshot.candidates == ()


def test_same_snapshot_is_deterministic(tmp_path: Path) -> None:
    store = _store_with(tmp_path, "deterministic record one", "deterministic record two")
    source = MemoryContextSource(store)

    first = source.snapshot(_query("deterministic"))
    second = source.snapshot(_query("deterministic"))
    assert first.snapshot_digest == second.snapshot_digest
    assert [c.candidate_id for c in first.candidates] == [c.candidate_id for c in second.candidates]
