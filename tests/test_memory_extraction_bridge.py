"""Phase 5 — Extraction Bridge 测试。

覆盖 proposal_to_candidate / proposal_to_decision /
proposal_to_confirmation_request / resolve_and_store /
batch_resolve_and_store。
"""

from __future__ import annotations

from agent.memory_confirmation import MemoryConfirmationChoice
from agent.memory_contracts import (
    MemoryDecisionType,
    MemoryScope,
    MemorySensitivity,
    MemorySource,
)
from agent.memory_extraction import MemoryCandidateProposal, SuggestedAction
from agent.memory_extraction_bridge import (
    _derive_candidate_id,
    batch_resolve_and_store,
    proposal_to_candidate,
    proposal_to_confirmation_request,
    proposal_to_decision,
    resolve_and_store,
)
from agent.memory_store import InMemoryMemoryStore

# ═══════════════════════════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _proposal(
    memory_type: str = "semantic",
    content: str = "用户偏好 Python",
    suggested_action: SuggestedAction = SuggestedAction.PROPOSE,
    importance: int = 7,
    confidence: float = 0.85,
    evidence: str = "user: 我喜欢 Python",
    rationale: str = "明确的偏好声明",
) -> MemoryCandidateProposal:
    return MemoryCandidateProposal(
        memory_type=memory_type,
        content=content,
        evidence=evidence,
        importance=importance,
        confidence=confidence,
        requires_confirmation=True,
        suggested_action=suggested_action,
        rationale=rationale,
    )


def _ignore_proposal() -> MemoryCandidateProposal:
    return _proposal(suggested_action=SuggestedAction.IGNORE)


# ═══════════════════════════════════════════════════════════════════════════════
# proposal_to_candidate
# ═══════════════════════════════════════════════════════════════════════════════


class TestProposalToCandidate:
    def test_maps_content_and_type(self) -> None:
        p = _proposal(memory_type="semantic", content="用户偏好简洁回答")
        c = proposal_to_candidate(p)
        assert c.content == "用户偏好简洁回答"
        assert c.proposed_type == "semantic"

    def test_derives_stable_id_from_content(self) -> None:
        p = _proposal(content="用户偏好简洁回答")
        c1 = proposal_to_candidate(p)
        c2 = proposal_to_candidate(p)
        assert c1.id == c2.id
        assert c1.id.startswith("extraction:")

    def test_source_is_external_provider(self) -> None:
        c = proposal_to_candidate(_proposal())
        assert c.source == MemorySource.EXTERNAL_PROVIDER

    def test_source_event_is_evidence(self) -> None:
        p = _proposal(evidence="user: 明确说了偏好")
        c = proposal_to_candidate(p)
        assert c.source_event == "user: 明确说了偏好"

    def test_scope_defaults_user_for_semantic(self) -> None:
        c = proposal_to_candidate(_proposal(memory_type="semantic"))
        assert c.scope == MemoryScope.USER

    def test_scope_defaults_project_for_procedural(self) -> None:
        c = proposal_to_candidate(_proposal(memory_type="procedural"))
        assert c.scope == MemoryScope.PROJECT

    def test_scope_can_be_overridden(self) -> None:
        c = proposal_to_candidate(_proposal(), scope=MemoryScope.REPO)
        assert c.scope == MemoryScope.REPO

    def test_sensitivity_defaults_low_for_semantic(self) -> None:
        c = proposal_to_candidate(_proposal(memory_type="semantic"))
        assert c.sensitivity == MemorySensitivity.LOW

    def test_sensitivity_defaults_medium_for_procedural(self) -> None:
        c = proposal_to_candidate(_proposal(memory_type="procedural"))
        assert c.sensitivity == MemorySensitivity.MEDIUM

    def test_confidence_preserved(self) -> None:
        c = proposal_to_candidate(_proposal(confidence=0.92))
        assert c.confidence == 0.92

    def test_metadata_contains_memory_type_and_source_type(self) -> None:
        c = proposal_to_candidate(_proposal(memory_type="episodic"))
        assert c.metadata["memory_type"] == "episodic"
        assert c.metadata["source_type"] == "llm_extraction"

    def test_metadata_contains_importance_and_suggested_action(self) -> None:
        c = proposal_to_candidate(
            _proposal(importance=8, suggested_action=SuggestedAction.AUTO_RETAIN_CANDIDATE)
        )
        assert c.metadata["importance"] == 8
        assert c.metadata["suggested_action"] == "auto_retain_candidate"

    def test_stability_is_proposed(self) -> None:
        c = proposal_to_candidate(_proposal())
        assert c.stability == "proposed"

    def test_derive_candidate_id_is_deterministic(self) -> None:
        id1 = _derive_candidate_id("hello world")
        id2 = _derive_candidate_id("hello world")
        assert id1 == id2

    def test_derive_candidate_id_differs_for_different_content(self) -> None:
        id1 = _derive_candidate_id("hello")
        id2 = _derive_candidate_id("world")
        assert id1 != id2


# ═══════════════════════════════════════════════════════════════════════════════
# proposal_to_decision
# ═══════════════════════════════════════════════════════════════════════════════


class TestProposalToDecision:
    def test_produce_retain_decision(self) -> None:
        d = proposal_to_decision(_proposal())
        assert d is not None
        assert d.decision_type == MemoryDecisionType.RETAIN
        assert d.action == "retain"

    def test_always_requires_confirmation(self) -> None:
        # even AUTO_RETAIN_CANDIDATE → requires_user_confirmation=True
        d = proposal_to_decision(
            _proposal(suggested_action=SuggestedAction.AUTO_RETAIN_CANDIDATE)
        )
        assert d is not None
        assert d.requires_user_confirmation is True

    def test_propose_also_requires_confirmation(self) -> None:
        d = proposal_to_decision(_proposal(suggested_action=SuggestedAction.PROPOSE))
        assert d is not None
        assert d.requires_user_confirmation is True

    def test_ignore_returns_none(self) -> None:
        d = proposal_to_decision(_ignore_proposal())
        assert d is None

    def test_target_candidate_set(self) -> None:
        d = proposal_to_decision(_proposal(content="独特内容"))
        assert d is not None
        assert d.target_candidate is not None
        assert d.target_candidate.content == "独特内容"

    def test_reason_includes_rationale(self) -> None:
        p = _proposal(rationale="用户明确表达了 Python 偏好")
        d = proposal_to_decision(p)
        assert d is not None
        assert "Python 偏好" in d.reason


# ═══════════════════════════════════════════════════════════════════════════════
# proposal_to_confirmation_request
# ═══════════════════════════════════════════════════════════════════════════════


class TestProposalToConfirmationRequest:
    def test_generates_request_with_question(self) -> None:
        req = proposal_to_confirmation_request(_proposal())
        assert req is not None
        assert len(req.question) > 0
        assert "长期记住" in req.question or "保留" in req.question or "记住" in req.question

    def test_generates_request_with_preview(self) -> None:
        req = proposal_to_confirmation_request(
            _proposal(content="用户偏好 Python")
        )
        assert req is not None
        assert "Python" in req.preview

    def test_has_accept_option(self) -> None:
        req = proposal_to_confirmation_request(_proposal())
        assert req is not None
        choices = [o.choice for o in req.options]
        assert MemoryConfirmationChoice.ACCEPT in choices

    def test_ignores_returns_none(self) -> None:
        req = proposal_to_confirmation_request(_ignore_proposal())
        assert req is None

    def test_episodic_proposal_generates_request(self) -> None:
        req = proposal_to_confirmation_request(
            _proposal(memory_type="episodic", content="上次修复了内存泄漏")
        )
        assert req is not None

    def test_procedural_proposal_generates_request(self) -> None:
        req = proposal_to_confirmation_request(
            _proposal(memory_type="procedural", content="必须先检查锁策略")
        )
        assert req is not None

    def test_empty_proposals_list_no_error(self) -> None:
        # All IGNORE proposals → all None
        results = [
            proposal_to_confirmation_request(_ignore_proposal()),
            proposal_to_confirmation_request(_ignore_proposal()),
        ]
        assert results == [None, None]


# ═══════════════════════════════════════════════════════════════════════════════
# resolve_and_store
# ═══════════════════════════════════════════════════════════════════════════════


class TestResolveAndStore:
    def test_accept_writes_to_store(self) -> None:
        store = InMemoryMemoryStore()
        req = proposal_to_confirmation_request(_proposal())
        result = resolve_and_store(req, MemoryConfirmationChoice.ACCEPT, store)
        assert result is not None
        assert len(store.list_records()) == 1

    def test_reject_does_not_write(self) -> None:
        store = InMemoryMemoryStore()
        req = proposal_to_confirmation_request(_proposal())
        result = resolve_and_store(req, MemoryConfirmationChoice.REJECT, store)
        assert result is None
        assert len(store.list_records()) == 0

    def test_session_only_does_not_write(self) -> None:
        store = InMemoryMemoryStore()
        req = proposal_to_confirmation_request(_proposal())
        result = resolve_and_store(req, MemoryConfirmationChoice.SESSION_ONLY, store)
        assert result is None
        assert len(store.list_records()) == 0

    def test_edit_and_accept_writes_edited_content(self) -> None:
        store = InMemoryMemoryStore()
        p = _proposal(content="用户偏好简洁回答")
        req = proposal_to_confirmation_request(p)
        result = resolve_and_store(
            req,
            MemoryConfirmationChoice.EDIT_AND_ACCEPT,
            store,
            free_text="用户偏好简洁但完整的回答",
        )
        assert result is not None
        records = store.list_records()
        assert len(records) == 1
        assert records[0].content == "用户偏好简洁但完整的回答"

    def test_multiple_accepts_create_multiple_records(self) -> None:
        store = InMemoryMemoryStore()
        for content in ("偏好 A", "偏好 B", "偏好 C"):
            p = _proposal(content=content)
            req = proposal_to_confirmation_request(p)
            resolve_and_store(req, MemoryConfirmationChoice.ACCEPT, store)
        assert len(store.list_records()) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# batch_resolve_and_store
# ═══════════════════════════════════════════════════════════════════════════════


class TestBatchResolveAndStore:
    def test_batch_mixed_accept_and_reject(self) -> None:
        store = InMemoryMemoryStore()
        requests = [
            proposal_to_confirmation_request(_proposal(content="偏好 A")),
            proposal_to_confirmation_request(_proposal(content="偏好 B")),
            proposal_to_confirmation_request(_proposal(content="偏好 C")),
        ]
        choices = {
            0: MemoryConfirmationChoice.ACCEPT,
            1: MemoryConfirmationChoice.REJECT,
            2: MemoryConfirmationChoice.ACCEPT,
        }
        results = batch_resolve_and_store(requests, choices, store)
        # index 1 rejected → None
        assert results[0] is not None
        assert results[1] is None
        assert results[2] is not None
        assert len(store.list_records()) == 2

    def test_batch_with_none_requests(self) -> None:
        store = InMemoryMemoryStore()
        requests = [
            proposal_to_confirmation_request(_proposal(content="偏好 A")),
            proposal_to_confirmation_request(_ignore_proposal()),  # None
            proposal_to_confirmation_request(_proposal(content="偏好 B")),
        ]
        choices = {
            0: MemoryConfirmationChoice.ACCEPT,
            2: MemoryConfirmationChoice.ACCEPT,
        }
        results = batch_resolve_and_store(requests, choices, store)
        assert results[0] is not None
        assert results[1] is None  # IGNORE
        assert results[2] is not None
        assert len(store.list_records()) == 2

    def test_batch_missing_choice_returns_none(self) -> None:
        store = InMemoryMemoryStore()
        requests = [proposal_to_confirmation_request(_proposal())]
        results = batch_resolve_and_store(requests, {}, store)
        assert results[0] is None
        assert len(store.list_records()) == 0

    def test_batch_with_edit(self) -> None:
        store = InMemoryMemoryStore()
        requests = [
            proposal_to_confirmation_request(_proposal(content="原始内容")),
        ]
        choices = {0: MemoryConfirmationChoice.EDIT_AND_ACCEPT}
        free_texts = {0: "修改后的内容"}
        results = batch_resolve_and_store(requests, choices, store, free_texts=free_texts)
        assert results[0] is not None
        records = store.list_records()
        assert records[0].content == "修改后的内容"


# ═══════════════════════════════════════════════════════════════════════════════
# 不写 filesystem
# ═══════════════════════════════════════════════════════════════════════════════


class TestBridgeNoFilesystemWrite:
    """bridge 测试使用 InMemoryMemoryStore，不写真实文件。"""

    def test_store_is_inmemory(self) -> None:
        store = InMemoryMemoryStore()
        req = proposal_to_confirmation_request(_proposal())
        result = resolve_and_store(req, MemoryConfirmationChoice.ACCEPT, store)
        assert result is not None
        # InMemoryMemoryStore 无文件系统副作用
        assert not hasattr(store, "root_dir")
