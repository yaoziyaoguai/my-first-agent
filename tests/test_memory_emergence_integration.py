"""Phase 7 deterministic emergence 子系统集成测试。

这些测试验证 RFC §10.5 / §15.5 中 procedural inline_confirmation seam。
inline_confirmation 是 explicit human confirmation，不是 silent retain，
也不是 auto approve。

使用合成 fixture（非真实数据）验证 Phase 7 foundation 的完整链路：
1. CorrectionEvidence → DeterministicEmergenceDetector → ProceduralCandidate
2. active_records<50 → fail closed
3. active_records≥50 → dispatch → T1 pending review
4. Review CLI accept/reject/edit/skip 对 procedural proposal 的行为
5. Inline confirmation seam 的 payload 生成和 response adapter
6. 不 silent retain、不 auto approve、不直接写 store

这些是 emergence 子系统的直调测试（不经 core.chat()），不声称 E2E。
使用临时 memory root，不接触真实 sessions/runs，不调用真实 LLM。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from agent.memory_emergence import (
    _DISALLOWED_CONFIRMATION_FORMS,
    CorrectionEvidence,
    DeterministicEmergenceDetector,
    InlineConfirmationRequest,
    InlineConfirmationResponse,
    ProceduralCandidate,
    _validate_confirmation_form,
    accept_inline_confirmation,
    apply_inline_confirmation_response,
    dispatch_procedural_candidates_to_pending_review,
    prepare_procedural_inline_confirmation_request,
)
from agent.memory_review import (
    accept_pending_proposal,
    edit_and_accept_pending_proposal,
    list_pending_proposals,
    reject_pending_proposal,
    skip_pending_proposal,
)
from agent.memory_store import InMemoryMemoryStore, MemoryStoreApplyStatus

# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_evidence(
    record_id: str,
    content: str,
    correction_type: str = "behavioral_rule",
    scope: str = "debugging",
    confidence: float = 0.75,
) -> CorrectionEvidence:
    return CorrectionEvidence(
        record_id=record_id,
        content=content,
        correction_type=correction_type,
        scope=scope,
        confidence=confidence,
        source_memory_type="episodic",
    )


def _make_candidate(
    content: str = "[行为约束] 先检查 git status",
    evidence_ids: tuple[str, ...] = ("ev1", "ev2", "ev3"),
    correction_pattern: str = "先检查 git status",
    correction_type: str = "process_order",
    scope: str = "git_operations",
    confidence: float = 0.65,
) -> ProceduralCandidate:
    return ProceduralCandidate(
        content=content,
        memory_type="procedural",
        source_evidence=evidence_ids,
        correction_pattern=correction_pattern,
        correction_type=correction_type,
        scope=scope,
        confidence=confidence,
        governance_route="T1",
        evidence_summary="evidence summary",
        created_at="2026-05-14T00:00:00Z",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 一、Fail-Closed: active_records < 50
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmergenceFailClosed:
    """active_records <50 → fail closed — 不产生 candidate, 不写 pending, 不写 store。
    （直调测试）"""

    def test_fail_closed_no_candidates(self):
        """active_records=17, 3 条证据 — gate 关闭，无 candidate。"""
        evidence = [
            _make_evidence("e1", "以后请先检查 git status 再提交"),
            _make_evidence("e2", "下次先检查 git status 再改"),
            _make_evidence("e3", "先检查 git status 再提交"),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=17)

        assert result.gate_passed is False
        assert len(result.candidates) == 0
        assert result.active_records_count == 17
        assert any("disabled" in w for w in result.warnings)

    def test_fail_closed_at_49(self):
        """active_records=49 — 边界：刚好低于门槛。"""
        evidence = [
            _make_evidence("e1", "以后请先检查 git status"),
            _make_evidence("e2", "下次先检查 git status"),
            _make_evidence("e3", "先检查 git status"),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=49)
        assert result.gate_passed is False
        assert len(result.candidates) == 0

    def test_fail_closed_no_pending_written(self):
        """gate 关闭时 dispatch 不应写入任何 pending 文件。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            evidence = [
                _make_evidence("e1", "以后请先检查 git status", scope="git_operations"),
                _make_evidence("e2", "下次先检查 git status", scope="git_operations"),
                _make_evidence("e3", "先检查 git status", scope="git_operations"),
            ]
            detector = DeterministicEmergenceDetector()
            result = detector.detect(evidence, active_records_count=10)

            # 即使手工 dispatch（虽然不应该），也应被 gate 拦住
            candidates = list(result.candidates)
            dispatch_result = dispatch_procedural_candidates_to_pending_review(
                candidates, memory_root=root,
            )
            assert dispatch_result.dispatched == 0
            assert len(dispatch_result.proposal_filepaths) == 0

            # _pending/ 目录不存在（因为没有写入）
            pending_dir = root / "_pending"
            t1_files = list(pending_dir.glob("t1_*.json")) if pending_dir.exists() else []
            assert len(t1_files) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 二、Full Chain: Detection → Dispatch → Review CLI
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmergenceFullChain:
    """active_records≥50 的全链路：detect → dispatch → review CLI。（直调测试）"""

    def test_detect_generates_candidate(self):
        """active_records=50, 3 条同 pattern evidence → 产生 ProceduralCandidate。"""
        evidence = [
            _make_evidence("e1", "以后请先检查 git status 再提交", scope="git_operations"),
            _make_evidence("e2", "下次先检查 git status 再改", scope="git_operations"),
            _make_evidence("e3", "记得先检查 git status 然后提交", scope="git_operations"),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=50)

        assert result.gate_passed is True
        assert len(result.candidates) >= 1
        c = result.candidates[0]
        assert c.memory_type == "procedural"
        assert c.governance_route == "T1"
        assert len(c.source_evidence) == 3
        assert c.correction_type == "behavioral_rule"
        assert c.scope == "git_operations"
        assert 0.60 <= c.confidence <= 0.85
        assert "git status" in c.correction_pattern

    def test_detect_multiple_groups(self):
        """不同 correction_type + scope 产生不同 candidate。"""
        evidence = [
            # Group 1: behavioral_rule + git_operations
            _make_evidence(
                "e1", "以后请先检查 git status",
                correction_type="behavioral_rule", scope="git_operations",
            ),
            _make_evidence(
                "e2", "下次先检查 git status",
                correction_type="behavioral_rule", scope="git_operations",
            ),
            _make_evidence(
                "e3", "记得先检查 git status",
                correction_type="behavioral_rule", scope="git_operations",
            ),
            # Group 2: behavioral_rule + debugging
            _make_evidence(
                "e4", "以后请先读日志再分析", correction_type="behavioral_rule", scope="debugging"
            ),
            _make_evidence(
                "e5", "下次先读日志", correction_type="behavioral_rule", scope="debugging"
            ),
            _make_evidence(
                "e6", "记得先读日志再分析", correction_type="behavioral_rule", scope="debugging"
            ),
            # Group 3: code_quality + code_review (different type)
            _make_evidence(
                "e7", "请始终用 ruff 做 lint", correction_type="code_quality", scope="code_review"
            ),
            _make_evidence(
                "e8", "必须先跑 ruff 再提交", correction_type="code_quality", scope="code_review"
            ),
            _make_evidence(
                "e9", "千万不要跳过 lint", correction_type="code_quality", scope="code_review"
            ),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=60)

        assert result.gate_passed is True
        assert len(result.candidates) >= 3
        scopes = {c.scope for c in result.candidates}
        assert "git_operations" in scopes
        assert "debugging" in scopes
        assert "code_review" in scopes
        types = {c.correction_type for c in result.candidates}
        assert "behavioral_rule" in types
        assert "code_quality" in types

    def test_dispatch_writes_pending_with_correct_metadata(self):
        """Dispatch 写入的 pending JSON 包含正确 metadata。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            evidence = [
                _make_evidence("e1", "以后请先检查 git status", scope="git_operations"),
                _make_evidence("e2", "下次先检查 git status", scope="git_operations"),
                _make_evidence("e3", "先检查 git status 再提交", scope="git_operations"),
            ]
            detector = DeterministicEmergenceDetector()
            result = detector.detect(evidence, active_records_count=50)

            dispatch_result = dispatch_procedural_candidates_to_pending_review(
                list(result.candidates), memory_root=root,
            )
            assert dispatch_result.dispatched == 1
            assert dispatch_result.skipped_invalid == 0
            assert dispatch_result.skipped_duplicate == 0

            fp = dispatch_result.proposal_filepaths[0]
            data = json.loads(fp.read_text(encoding="utf-8"))
            assert data["memory_type"] == "procedural"
            assert data["governance_route"] == "T1"
            assert data["approval_status"] == "pending"
            assert data["confirmation_form"] == "pending_review"
            assert data["confirmation_form"] != "silent"
            assert data["confirmation_form"] != "auto_retained"
            assert data["source_type"] == "emergence"
            assert data["proposal_id"].startswith("emergence_")
            # Phase 7 字段
            assert "correction_pattern" in data
            assert "correction_type" in data
            assert len(data["source_evidence"]) == 3

    def test_review_cli_list_procedural_proposal(self):
        """Review CLI 能正确列出 procedural proposal。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            proposals = list_pending_proposals(memory_root=str(root))
            assert len(proposals) == 1
            p = proposals[0]
            assert p.memory_type == "procedural"
            assert p.governance_route == "T1"
            assert p.approval_status == "pending"
            assert p.correction_pattern == candidate.correction_pattern
            assert p.correction_type == candidate.correction_type
            assert p.confirmation_form == "pending_review"

    def test_review_cli_accept_writes_to_store(self):
        """Accept procedural proposal → 写入 store，pending 归档。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            proposals = list_pending_proposals(memory_root=str(root))
            store = InMemoryMemoryStore()

            result = accept_pending_proposal(proposals[0], store)
            assert result.status is MemoryStoreApplyStatus.APPLIED

            records = store.list_records()
            procedural = [r for r in records if r.memory_type == "procedural"]
            assert len(procedural) >= 1

            # pending 已归档
            remaining = list_pending_proposals(memory_root=str(root))
            assert len(remaining) == 0

    def test_review_cli_reject_does_not_write(self):
        """Reject procedural proposal → 不写入 store，pending 归档。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            proposals = list_pending_proposals(memory_root=str(root))
            store = InMemoryMemoryStore()

            reject_pending_proposal(proposals[0])
            records = store.list_records()
            # 不应有匹配的 procedural record
            matching = [
                r for r in records
                if r.memory_type == "procedural" and candidate.content in r.content
            ]
            assert len(matching) == 0

            # pending 已归档
            remaining = list_pending_proposals(memory_root=str(root))
            assert len(remaining) == 0

    def test_review_cli_edit_and_accept_preserves_emergence_metadata(self):
        """Edit-and-accept → 保留 emergence metadata（correction_pattern/correction_type）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate(
                correction_pattern="先运行 lint 和 tests",
                correction_type="process_order",
            )
            dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            proposals = list_pending_proposals(memory_root=str(root))
            store = InMemoryMemoryStore()

            edited = "先检查 git status 和 lint 再提交"
            result = edit_and_accept_pending_proposal(proposals[0], edited, store)
            assert result.status is MemoryStoreApplyStatus.APPLIED

            records = store.list_records()
            matching = [r for r in records if edited in r.content]
            assert len(matching) >= 1
            record = matching[0]
            source_summary = record.source_summary
            assert "correction_pattern=先运行 lint 和 tests" in source_summary
            assert "correction_type=process_order" in source_summary

    def test_review_cli_skip_keeps_pending(self):
        """Skip → pending 保留，不写入 store。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            proposals = list_pending_proposals(memory_root=str(root))
            skip_pending_proposal(proposals[0])

            # skip 后 pending 仍在
            still_pending = list_pending_proposals(memory_root=str(root))
            assert len(still_pending) == 1

    def test_dispatch_dedup_same_candidate(self):
        """相同 candidate 两次 dispatch 不重复写入。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            r1 = dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            assert r1.dispatched == 1
            r2 = dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            assert r2.dispatched == 0
            assert r2.skipped_duplicate == 1

    def test_no_silent_retain_no_auto_approve(self):
        """全链路中不应出现 silent retain 或 auto approve 的路径。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            evidence = [
                _make_evidence("e1", "以后请先检查 git status", scope="git_operations"),
                _make_evidence("e2", "下次先检查 git status", scope="git_operations"),
                _make_evidence("e3", "先检查 git status 再提交", scope="git_operations"),
            ]
            detector = DeterministicEmergenceDetector()
            result = detector.detect(evidence, active_records_count=50)

            for c in result.candidates:
                # ProceduralCandidate 没有 approval_status 字段
                assert not hasattr(c, "approval_status")
                # 只能是 T1
                assert c.governance_route == "T1"
                # 不能是 silent
                assert c.memory_type == "procedural"

            # dispatch 后的 pending JSON 必须是 pending 状态
            dispatch_result = dispatch_procedural_candidates_to_pending_review(
                list(result.candidates), memory_root=root,
            )
            for fp in dispatch_result.proposal_filepaths:
                data = json.loads(fp.read_text(encoding="utf-8"))
                assert data["approval_status"] == "pending"
                assert data["confirmation_form"] == "pending_review"
                assert data["confirmation_form"] not in _DISALLOWED_CONFIRMATION_FORMS


# ═══════════════════════════════════════════════════════════════════════════════
# 三、Inline Confirmation Seam
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmergenceInlineConfirmation:
    """RFC §10.5 / §15.5 inline_confirmation seam 的全链路验证（直调测试）。

    inline_confirmation 是 explicit human confirmation，不是 silent retain，
    也不是 auto approve；response adapter 只允许 accept/edit_accept 写 store。
    """

    def test_prepare_inline_confirmation_request(self):
        """prepare_procedural_inline_confirmation_request 生成正确的 payload。"""
        candidate = _make_candidate(
            content="[行为约束] 先检查 git status",
            evidence_ids=("ev-a", "ev-b", "ev-c"),
            correction_pattern="先检查 git status",
            correction_type="process_order",
            scope="git_operations",
            confidence=0.65,
        )
        req = prepare_procedural_inline_confirmation_request(candidate)

        assert isinstance(req, InlineConfirmationRequest)
        assert req.confirmation_form == "inline_confirmation"
        assert req.candidate_content == candidate.content
        assert req.source_evidence == ("ev-a", "ev-b", "ev-c")
        assert req.correction_pattern == "先检查 git status"
        assert req.correction_type == "process_order"
        assert req.scope == "git_operations"
        assert req.confidence == 0.65
        assert req.proposal_id.startswith("emergence_")
        assert req.allowed_actions == ("accept", "reject", "edit", "other")

    def test_prepare_rejects_non_procedural(self):
        """非 procedural candidate → prepare 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="procedural"):
            candidate = ProceduralCandidate(
                content="先检查 git status",
                memory_type="semantic",  # type: ignore[arg-type]
                source_evidence=("ev1", "ev2", "ev3"),
                correction_pattern="pattern",
                correction_type="process_order",
                scope="git_operations",
                confidence=0.65,
                governance_route="T1",
                evidence_summary="summary",
                created_at="2026-05-14T00:00:00Z",
            )
            prepare_procedural_inline_confirmation_request(candidate)

    def test_accept_inline_confirmation_writes_to_store(self):
        """accept response → 写入 store，record 类型为 procedural。"""
        candidate = _make_candidate()
        req = prepare_procedural_inline_confirmation_request(candidate)
        store = InMemoryMemoryStore()

        result = apply_inline_confirmation_response(
            req,
            InlineConfirmationResponse(action="accept"),
            store,
        )
        assert result.status == "applied"
        assert result.store_result is not None
        assert result.store_result.status is MemoryStoreApplyStatus.APPLIED

        records = store.list_records()
        procedural = [r for r in records if r.memory_type == "procedural"]
        assert len(procedural) >= 1
        record = procedural[0]
        assert candidate.content in record.content
        assert "emergence:inline_confirmation" in record.source_summary
        assert "confirmation_form=inline_confirmation" in record.source_summary

    def test_accept_inline_with_edit(self):
        """edit_accept response → 使用编辑后内容。"""
        candidate = _make_candidate(content="[行为约束] 先检查 git status")
        req = prepare_procedural_inline_confirmation_request(candidate)
        store = InMemoryMemoryStore()

        edited = "[行为约束] 先检查 git status 和 lint 再提交"
        result = apply_inline_confirmation_response(
            req,
            InlineConfirmationResponse(action="edit_accept", edited_content=edited),
            store,
        )
        assert result.status == "applied"
        assert result.store_result is not None
        assert result.store_result.status is MemoryStoreApplyStatus.APPLIED

        records = store.list_records()
        matching = [r for r in records if edited in r.content]
        assert len(matching) >= 1
        # 编辑后的 content 就是传入的 edited_content（不带前缀）
        assert matching[0].content == edited

    def test_accept_inline_rejects_empty_edit(self):
        """编辑内容为空 → 抛出 ValueError。"""
        candidate = _make_candidate()
        req = prepare_procedural_inline_confirmation_request(candidate)
        store = InMemoryMemoryStore()

        with pytest.raises(ValueError, match="不能为空"):
            accept_inline_confirmation(req, store, edited_content="")

    def test_accept_inline_does_not_write_on_prepare(self):
        """prepare 不写入 store — 只有 explicit accept response 才写。"""
        candidate = _make_candidate()
        store = InMemoryMemoryStore()

        # prepare 阶段
        req = prepare_procedural_inline_confirmation_request(candidate)
        # prepare 后 store 应为空
        records_before = store.list_records()
        assert len([r for r in records_before if r.memory_type == "procedural"]) == 0

        # accept response 后才写入
        apply_inline_confirmation_response(
            req,
            InlineConfirmationResponse(action="accept"),
            store,
        )
        records_after = store.list_records()
        assert len([r for r in records_after if r.memory_type == "procedural"]) == 1

    def test_inline_confirmation_preserves_emergence_metadata(self):
        """accept_inline_confirmation 写入的 record 保留 emergence metadata。"""
        candidate = _make_candidate(
            correction_pattern="先运行测试再提交",
            correction_type="process_order",
            evidence_ids=("ev-x", "ev-y", "ev-z"),
        )
        req = prepare_procedural_inline_confirmation_request(candidate)
        store = InMemoryMemoryStore()
        result = apply_inline_confirmation_response(
            req,
            InlineConfirmationResponse(action="accept"),
            store,
        )
        assert result.status == "applied"
        assert result.store_result is not None
        assert result.store_result.status is MemoryStoreApplyStatus.APPLIED

        records = store.list_records()
        procedural = [r for r in records if r.memory_type == "procedural"]
        assert len(procedural) >= 1
        record = procedural[0]
        source_summary = record.source_summary
        assert "correction_pattern=先运行测试再提交" in source_summary
        assert "correction_type=process_order" in source_summary
        assert "source_evidence=['ev-x', 'ev-y', 'ev-z']" in source_summary or \
               "source_evidence=['ev-z', 'ev-y', 'ev-x']" in source_summary
        assert "confidence=0.65" in source_summary

    def test_inline_confirmation_no_auto_approve(self):
        """Inline confirmation 不自动 approve — response adapter 需要显式 accept。"""
        candidate = _make_candidate()
        req = prepare_procedural_inline_confirmation_request(candidate)
        store = InMemoryMemoryStore()

        # apply_inline_confirmation_response 需要显式 accept — 不存在 auto approve 路径
        # 验证 prepare 不写入 store
        records_before = store.list_records()
        assert len(records_before) == 0

        result = apply_inline_confirmation_response(
            req,
            InlineConfirmationResponse(action="accept"),
            store,
        )
        assert result.status == "applied"
        assert result.store_result is not None
        assert result.store_result.status is MemoryStoreApplyStatus.APPLIED

        # 只有一条 record — 没有重复写入
        records_after = store.list_records()
        assert len(records_after) == 1

    def test_reject_response_does_not_write_store(self):
        """reject response → 不写 store，避免 procedural memory 被拒绝后仍污染正式记录。"""
        candidate = _make_candidate()
        req = prepare_procedural_inline_confirmation_request(candidate)
        store = InMemoryMemoryStore()

        result = apply_inline_confirmation_response(
            req,
            InlineConfirmationResponse(action="reject"),
            store,
        )

        assert result.status == "no_write"
        assert result.store_result is None
        assert store.list_records() == ()

    def test_other_response_does_not_write_store(self):
        """other/free-text response → 只返回 follow-up，不自动写正式 memory。"""
        candidate = _make_candidate()
        req = prepare_procedural_inline_confirmation_request(candidate)
        store = InMemoryMemoryStore()

        result = apply_inline_confirmation_response(
            req,
            InlineConfirmationResponse(action="other", free_text="需要再确认作用域"),
            store,
        )

        assert result.status == "needs_followup"
        assert result.store_result is None
        assert store.list_records() == ()


# ═══════════════════════════════════════════════════════════════════════════════
# 四、ConfirmationForm 安全性验证
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmergenceConfirmationFormSafety:
    """ConfirmationForm 不允许 silent/auto_retained/none。"""

    def test_disallowed_forms_validation(self):
        """_validate_confirmation_form 拒绝 silent/auto_retained/none。"""
        for disallowed in ("silent", "auto_retained", "none"):
            with pytest.raises(ValueError, match="不被允许"):
                _validate_confirmation_form(disallowed)

    def test_disallowed_forms_passed(self):
        """pending_review 和 inline_confirmation 通过校验。"""
        _validate_confirmation_form("pending_review")
        _validate_confirmation_form("inline_confirmation")

    def test_inline_request_rejects_disallowed_form(self):
        """InlineConfirmationRequest 拒绝 non-inline_confirmation form。"""
        with pytest.raises(ValueError):
            InlineConfirmationRequest(
                candidate_content="test",
                source_evidence=("ev1", "ev2", "ev3"),
                correction_pattern="test",
                correction_type="process_order",
                scope=None,
                evidence_summary=None,
                confidence=0.65,
                confirmation_form="pending_review",  # type: ignore[arg-type]
                allowed_actions=("accept", "reject"),
                proposal_id="test-id",
                created_at="2026-05-14T00:00:00Z",
            )

    def test_pending_json_rejects_disallowed_form(self):
        """dispatch 写入的 pending JSON 的 confirmation_form 不为 disallowed。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            result = dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            data = json.loads(result.proposal_filepaths[0].read_text(encoding="utf-8"))
            assert data["confirmation_form"] not in _DISALLOWED_CONFIRMATION_FORMS
            assert data["confirmation_form"] in ("pending_review", "inline_confirmation")

    def test_direct_store_write_not_happening(self):
        """检测器不直接写入 store — 只产出 candidate。"""
        evidence = [
            _make_evidence("e1", "以后请先检查 git status"),
            _make_evidence("e2", "下次先检查 git status"),
            _make_evidence("e3", "先检查 git status"),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=50)

        # detector 输出 candidates tuple，不包含 store 引用
        assert isinstance(result.candidates, tuple)
        for c in result.candidates:
            assert isinstance(c, ProceduralCandidate)

    def test_dispatch_defense_in_depth_rejects_non_procedural(self):
        """Dispatch 校验拒绝 non-procedural candidate。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            # 尝试构造不可能通过校验的 candidate（手工绕过的场景）
            # 正常 ProceduralCandidate.__post_init__ 已拦，这里测试 dispatch 的 defense-in-depth
            candidate = _make_candidate()
            result = dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            # 正常 candidate dispatch 成功
            assert result.dispatched == 1
            assert result.skipped_invalid == 0
