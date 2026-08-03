"""Memory Product gate：conversation A remember → conversation B recall。

候选 reference task（见 roadmap）：在 conversation A 明确 remember 一条项目约定，
在 conversation B 的同 workspace/profile 下正确召回。证据：approval preview、store
revision、BudgetReport 的 source selection，以及召回内容进入下一 ContextPack 且 untrusted。
"""

from __future__ import annotations

from pathlib import Path

from agent.memory.contracts import ProviderTrustProfile
from agent.memory.source import MemoryContextSource
from agent.memory.store import MemoryStore
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ContextQuery,
    ContextSourceLimits,
    ConversationState,
    SubmitMessage,
)

SCOPE = "scope-digest-1"
PROFILE = ProviderTrustProfile("ops-profile", "openai_compatible", "https://provider.example")


def _store_path(tmp_path: Path) -> Path:
    directory = tmp_path / "memory"
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory / "store.json"


def test_conversation_a_remember_is_recalled_in_conversation_b(tmp_path: Path) -> None:
    path = _store_path(tmp_path)
    # Conversation A：operator 批准的 remember。
    store_a = MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    record = store_a.remember("The project deploy command is `pyc ship` for staging.")
    assert store_a.revision == 1

    # Conversation B：独立加载同一 store，召回。
    store_b = MemoryStore.load(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    source = MemoryContextSource(store_b)
    snapshot = source.snapshot(
        ContextQuery(
            conversation_id="b",
            run_id="b",
            user_text="how do I deploy to staging",
            workspace_scope_digest=SCOPE,
            source_limits=ContextSourceLimits(max_tokens=10_000, max_items=8),
        )
    )

    assert snapshot.candidates
    assert snapshot.candidates[0].candidate_id == record.record_id
    assert "pyc ship" in snapshot.candidates[0].content
    assert snapshot.candidates[0].provenance["approved"] is True


def test_memory_candidate_appears_as_untrusted_context_under_budget(tmp_path: Path) -> None:
    path = _store_path(tmp_path)
    store = MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    store.remember("the release token is CANARY before ship")

    source = MemoryContextSource(store)
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        sources=(source,),
        workspace_scope_digest=SCOPE,
    )
    state = ConversationState.new("c1")
    action = SubmitMessage(
        conversation_id="c1",
        action_seq=1,
        expected_revision=0,
        run_id="r1",
        message="CANARY release",
    )
    pack = manager.build(state, action, tools=())

    blob = repr([list(message.content) for message in pack.messages])
    assert "CANARY" in blob
    assert "untrusted" in blob
    assert pack.budget.source_digests
    assert any(
        "CANARY" in (block.get("text", "") if isinstance(block, dict) else "")
        for message in pack.messages
        for block in message.content
    )


def test_no_memory_configured_reproduces_baseline_behavior(tmp_path: Path) -> None:
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
    )
    state = ConversationState.new("c1")
    action = SubmitMessage(
        conversation_id="c1", action_seq=1, expected_revision=0, run_id="r1", message="hello"
    )
    pack = manager.build(state, action, tools=())
    assert pack.budget.source_digests == ()


def test_rank_and_projection_preserve_recency_and_digest_evidence(tmp_path: Path) -> None:
    """A9: equal-score candidates must tie-break by updated_at descending then record_id."""
    from agent.memory.source import MemoryContextSource
    from agent.runtime.contracts import ContextQuery, ContextSourceLimits

    path = _store_path(tmp_path)
    store = MemoryStore.create(path, workspace_scope_digest=SCOPE, profile=PROFILE)
    # two records with same content (same score) but different recency
    store.remember("shared keyword alpha")
    r2 = store.remember("shared keyword beta")
    source = MemoryContextSource(store)
    snapshot = source.snapshot(
        ContextQuery(
            conversation_id="c",
            run_id="r",
            user_text="shared keyword",
            workspace_scope_digest=SCOPE,
            source_limits=ContextSourceLimits(max_tokens=10_000, max_items=8),
        )
    )
    assert len(snapshot.candidates) == 2
    # both have score > 0
    # tie-break: updated_at desc → r2 (newer) first
    assert snapshot.candidates[0].candidate_id == r2.record_id
