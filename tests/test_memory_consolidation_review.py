"""Phase 6 Consolidation T1 Pending Review Dispatch 测试。

这些测试验证 RFC Phase 6 consolidation candidate 进入 T1 pending review bridge
的显式人工治理闭环，不验证真实 semantic consolidation quality，不允许自动 approve。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.memory_consolidation import ConsolidationCandidate, ConsolidationType
from agent.memory_consolidation_review import (
    ConsolidationPendingDispatchResult,
    _compute_proposal_identity,
    dispatch_consolidation_candidates_to_pending_review,
)
from agent.memory_review import (
    accept_pending_proposal,
    edit_and_accept_pending_proposal,
    list_pending_proposals,
    reject_pending_proposal,
    skip_pending_proposal,
)
from agent.memory_store import MemoryStoreApplyStatus

# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_candidate(**overrides):
    """构造合法的 ConsolidationCandidate，便于测试只 override 被关注的字段。"""
    defaults = {
        "content": "用户偏好 pytest 测试框架",
        "memory_type": "semantic",
        "source_evidence": ("ep_001", "ep_002", "ep_003"),
        "consolidation_type": ConsolidationType.PATTERN_DETECTION,
        "confidence": 0.85,
        "governance_route": "T1",
        "evidence_summary": "用户在过去 3 个 session 中明确使用 pytest",
        "created_at": "2026-05-13T10:00:00Z",
    }
    defaults.update(overrides)
    return ConsolidationCandidate(**defaults)


def _read_pending_json(filepath: Path) -> dict:
    """读取 pending JSON 文件内容。"""
    return json.loads(filepath.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Dispatch 单个 candidate
# ═══════════════════════════════════════════════════════════════════════════════


class TestDispatchSingle:
    """验证 dispatch_consolidation_candidates_to_pending_review 的基础行为。"""

    def test_dispatches_single_candidate_creates_pending_json(self, tmp_path: Path):
        """dispatch 单个合法 candidate 会在 _pending/ 生成 JSON 文件。"""
        candidate = _make_candidate()
        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        assert result.dispatched == 1
        assert result.skipped_invalid == 0
        assert result.skipped_duplicate == 0
        assert len(result.proposal_filepaths) == 1

        filepath = result.proposal_filepaths[0]
        assert filepath.exists()
        assert filepath.name.startswith("t1_")
        assert filepath.name.endswith(".json")

    def test_dispatched_json_memory_type_semantic(self, tmp_path: Path):
        """pending JSON 中 memory_type 必须为 semantic。"""
        candidate = _make_candidate()
        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        data = _read_pending_json(result.proposal_filepaths[0])
        assert data["memory_type"] == "semantic"

    def test_dispatched_json_approval_status_pending(self, tmp_path: Path):
        """pending JSON 中 approval_status 必须为 pending。"""
        candidate = _make_candidate()
        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        data = _read_pending_json(result.proposal_filepaths[0])
        assert data["approval_status"] == "pending"

    def test_dispatched_json_governance_route_t1(self, tmp_path: Path):
        """pending JSON 中 governance_route 必须为 T1。"""
        candidate = _make_candidate()
        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        data = _read_pending_json(result.proposal_filepaths[0])
        assert data["governance_route"] == "T1"

    def test_dispatched_json_preserves_confidence(self, tmp_path: Path):
        """pending JSON 必须保留 confidence。"""
        candidate = _make_candidate(confidence=0.73)
        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        data = _read_pending_json(result.proposal_filepaths[0])
        assert data["confidence"] == 0.73

    def test_dispatched_json_preserves_source_evidence(self, tmp_path: Path):
        """pending JSON 必须保留 source_evidence（record id 列表）。"""
        candidate = _make_candidate(
            source_evidence=("ep_001", "ep_005", "ep_012"),
        )
        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        data = _read_pending_json(result.proposal_filepaths[0])
        assert data["source_evidence"] == ["ep_001", "ep_005", "ep_012"]

    def test_dispatched_json_preserves_consolidation_type(self, tmp_path: Path):
        """pending JSON 必须保留 consolidation_type。"""
        candidate = _make_candidate(
            consolidation_type=ConsolidationType.MERGE,
        )
        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        data = _read_pending_json(result.proposal_filepaths[0])
        assert data["consolidation_type"] == "merge"

    def test_dispatched_json_preserves_preference_evolved_type(self, tmp_path: Path):
        """preference_evolved 仍只进入 T1 pending review，不直接写 store。

        这些测试验证 RFC 中 preference_evolved 的最小 deterministic foundation：
        它属于 semantic consolidation 的演化候选，不是 procedural memory，
        不允许 silent retain，也不能绕过 T1 pending review。
        """
        candidate = _make_candidate(
            consolidation_type=ConsolidationType.PREFERENCE_EVOLVED,
            source_evidence=("pref_old", "pref_new_a", "pref_new_b"),
            confidence=0.74,
        )
        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        data = _read_pending_json(result.proposal_filepaths[0])
        assert data["memory_type"] == "semantic"
        assert data["governance_route"] == "T1"
        assert data["approval_status"] == "pending"
        assert data["consolidation_type"] == "preference_evolved"
        assert data["source_evidence"] == ["pref_old", "pref_new_a", "pref_new_b"]
        assert data["confidence"] == 0.74
        assert not (tmp_path / "semantic").exists()
        assert not (tmp_path / "procedural").exists()

    def test_dispatched_json_preserves_evidence_summary(self, tmp_path: Path):
        """pending JSON 必须保留 evidence_summary。"""
        candidate = _make_candidate(
            evidence_summary="3 次用户偏好表达高度一致",
        )
        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        data = _read_pending_json(result.proposal_filepaths[0])
        assert data["evidence_summary"] == "3 次用户偏好表达高度一致"

    def test_dispatched_json_includes_proposal_id(self, tmp_path: Path):
        """pending JSON 必须包含 proposal_id 用于去重。"""
        candidate = _make_candidate()
        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        data = _read_pending_json(result.proposal_filepaths[0])
        assert "proposal_id" in data
        assert data["proposal_id"].startswith("consolidation_")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Dispatch 校验边界
# ═══════════════════════════════════════════════════════════════════════════════


class TestDispatchValidation:
    """验证 dispatch 前置校验规则。"""

    def test_source_evidence_lt_3_skipped(self, tmp_path: Path):
        """source_evidence 少于 3 条时跳过并 warning（RFC §D.1 N≥3）。"""
        candidate = _make_candidate(source_evidence=("ep_001", "ep_002"))
        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        assert result.dispatched == 0
        assert result.skipped_invalid == 1
        assert len(result.warnings) == 1
        assert "N≥3" in result.warnings[0]

    def test_non_semantic_candidate_skipped(self, tmp_path: Path):
        """非 semantic candidate 不允许 dispatch。

        ConsolidationCandidate.__post_init__ 阻止构造非 semantic 实例，
        但在 fail-closed 测试中需要绕过校验，直接用 object.__setattr__。
        本测试验证 dispatch 层的 defense-in-depth 校验能捕获异常 state。
        """
        candidate = _make_candidate()
        object.__setattr__(candidate, "memory_type", "procedural")
        object.__setattr__(candidate, "governance_route", "T1")

        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        assert result.skipped_invalid == 1
        assert "procedural" in result.warnings[0]

    def test_non_t1_candidate_skipped(self, tmp_path: Path):
        """非 T1 governance_route 的 candidate 不允许 dispatch。"""
        candidate = _make_candidate()
        object.__setattr__(candidate, "governance_route", "T2")

        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        assert result.skipped_invalid == 1
        assert "T2" in result.warnings[0]

    def test_empty_content_candidate_skipped(self, tmp_path: Path):
        """content 为空的 candidate 不允许 dispatch。"""
        candidate = _make_candidate()
        object.__setattr__(candidate, "content", "   ")

        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        assert result.skipped_invalid == 1
        assert "content" in result.warnings[0].lower()

    def test_mixed_valid_and_invalid(self, tmp_path: Path):
        """混合合法/非法 candidate 时，合法的不受影响。"""
        good = _make_candidate()
        bad_n2 = _make_candidate(
            content="两条证据",
            source_evidence=("ep_001", "ep_002"),
        )
        result = dispatch_consolidation_candidates_to_pending_review(
            [good, bad_n2], memory_root=tmp_path,
        )

        assert result.dispatched == 1
        assert result.skipped_invalid == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Identity / 去重
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdentity:
    """验证 proposal identity 计算和确定性。"""

    def test_same_candidate_same_identity(self):
        """相同 candidate 产生相同 identity（幂等）。"""
        c = _make_candidate()
        id1 = _compute_proposal_identity(c)
        id2 = _compute_proposal_identity(c)
        assert id1 == id2

    def test_different_content_different_identity(self):
        """不同 content 产生不同 identity。"""
        c1 = _make_candidate(content="用户偏好 pytest")
        c2 = _make_candidate(content="用户偏好 unittest")
        assert _compute_proposal_identity(c1) != _compute_proposal_identity(c2)

    def test_different_evidence_different_identity(self):
        """不同 source_evidence 产生不同 identity。"""
        c1 = _make_candidate(source_evidence=("ep_001", "ep_002", "ep_003"))
        c2 = _make_candidate(source_evidence=("ep_004", "ep_005", "ep_006"))
        assert _compute_proposal_identity(c1) != _compute_proposal_identity(c2)

    def test_different_type_different_identity(self):
        """不同 consolidation_type 产生不同 identity。"""
        c1 = _make_candidate(consolidation_type=ConsolidationType.PATTERN_DETECTION)
        c2 = _make_candidate(consolidation_type=ConsolidationType.MERGE)
        assert _compute_proposal_identity(c1) != _compute_proposal_identity(c2)

    def test_evidence_order_independent(self):
        """source_evidence 顺序不影响 identity（排序后再 hash）。"""
        c1 = _make_candidate(source_evidence=("ep_003", "ep_001", "ep_002"))
        c2 = _make_candidate(source_evidence=("ep_001", "ep_002", "ep_003"))
        assert _compute_proposal_identity(c1) == _compute_proposal_identity(c2)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 去重 dispatch
# ═══════════════════════════════════════════════════════════════════════════════


class TestDedup:
    """验证重复 dispatch 不产生重复 pending 文件。"""

    def test_duplicate_dispatch_skipped(self, tmp_path: Path):
        """同一 candidate 两次 dispatch 只产生一个 pending 文件。"""
        candidate = _make_candidate()

        r1 = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )
        assert r1.dispatched == 1

        r2 = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )
        assert r2.dispatched == 0
        assert r2.skipped_duplicate == 1

        # 只有 1 个 t1_*.json 文件
        pending_files = list((tmp_path / "_pending").glob("t1_*.json"))
        assert len(pending_files) == 1

    def test_duplicate_across_batches(self, tmp_path: Path):
        """跨批次 dispatch 相同 candidate 不重复写入。"""
        c1 = _make_candidate(content="用户偏好 pytest")
        c2 = _make_candidate(content="代码风格偏好 black")

        # 第一批
        r1 = dispatch_consolidation_candidates_to_pending_review(
            [c1], memory_root=tmp_path,
        )
        assert r1.dispatched == 1

        # 第二批：包含 c1（重复）和 c2（新）
        r2 = dispatch_consolidation_candidates_to_pending_review(
            [c1, c2], memory_root=tmp_path,
        )
        assert r2.dispatched == 1  # 只有 c2
        assert r2.skipped_duplicate == 1  # c1 重复

        pending_files = list((tmp_path / "_pending").glob("t1_*.json"))
        assert len(pending_files) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Malformed 不崩溃
# ═══════════════════════════════════════════════════════════════════════════════


class TestMalformedResilience:
    """验证损坏数据不导致整个 dispatch 崩溃。"""

    def test_corrupt_pending_file_does_not_block_dispatch(self, tmp_path: Path):
        """_pending/ 中存在损坏 JSON 时新 dispatch 不受影响。"""
        pending_dir = tmp_path / "_pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        # 写入损坏 JSON
        (pending_dir / "t1_corrupt.json").write_text("{not valid json!!", encoding="utf-8")

        candidate = _make_candidate()
        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        assert result.dispatched == 1

    def test_dispatch_survives_bad_candidate_in_list(self, tmp_path: Path):
        """列表中包含无效 candidate 时 dispatch 继续处理其余 candidate。

        无效 candidate 绕过 __post_init__ 校验构造（N=1），验证 dispatch 层 fail-closed。
        """
        good1 = _make_candidate(content="用户偏好 pytest")
        # 构造 N=1 的无效 candidate：先构造合法实例，再 mutate
        bad = _make_candidate(content="bad")
        object.__setattr__(bad, "source_evidence", ("ep_001",))  # N=1，无效
        good2 = _make_candidate(content="代码风格偏好 black")

        result = dispatch_consolidation_candidates_to_pending_review(
            [good1, bad, good2], memory_root=tmp_path,
        )

        assert result.dispatched == 2
        assert result.skipped_invalid == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Review CLI — list consolidation proposal
# ═══════════════════════════════════════════════════════════════════════════════


class TestReviewCLIList:
    """验证现有 review CLI 能列出 consolidation pending proposal。"""

    def test_review_lists_consolidation_proposal(self, tmp_path: Path):
        """dispatch 后 review memory 能列出 consolidation proposal。"""
        candidate = _make_candidate()
        dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        proposals = list_pending_proposals(memory_root=str(tmp_path))
        assert len(proposals) == 1
        assert proposals[0].memory_type == "semantic"
        assert proposals[0].source_type == "consolidation"
        assert proposals[0].governance_route == "T1"

    def test_review_proposal_has_consolidation_metadata(self, tmp_path: Path):
        """list 出的 consolidation proposal 带有 consolidation 特有字段。"""
        candidate = _make_candidate(
            consolidation_type=ConsolidationType.PATTERN_DETECTION,
            source_evidence=("ep_001", "ep_002", "ep_003"),
        )
        dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        proposals = list_pending_proposals(memory_root=str(tmp_path))
        p = proposals[0]
        assert p.consolidation_type == "pattern_detection"
        assert len(p.source_evidence) == 3
        assert "ep_001" in p.source_evidence

    def test_review_proposal_mixed_with_regular_t1(self, tmp_path: Path):
        """consolidation proposal 与常规 T1 proposal 混合时都能被列出。"""
        # 写入常规 T1 proposal（模拟 session-end extraction）
        pending_dir = tmp_path / "_pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / "t1_regular.json").write_text(json.dumps({
            "content": "用户提过喜欢 CLI",
            "evidence": "用户消息",
            "confidence": 0.85,
            "importance": 3,
            "rationale": "repeated",
            "memory_type": "episodic",
            "source_type": "agent_suggested",
            "governance_route": "T1",
            "approval_status": "pending",
            "scope": "user",
            "source": "session_end_extraction",
            "created_at": "2026-05-12T10:00:00Z",
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        # dispatch consolidation
        candidate = _make_candidate()
        dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        proposals = list_pending_proposals(memory_root=str(tmp_path))
        assert len(proposals) == 2
        types = {p.source_type for p in proposals}
        assert "agent_suggested" in types
        assert "consolidation" in types


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Review CLI — accept
# ═══════════════════════════════════════════════════════════════════════════════


class TestReviewCLIAccept:
    """验证 accept consolidation proposal 后写入正式 semantic record。"""

    def test_accept_writes_to_store(self, tmp_path: Path):
        """accept consolidation proposal 后 store 中可见 semantic record。"""
        candidate = _make_candidate(content="用户偏好 pytest 为主要测试框架")
        dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        proposals = list_pending_proposals(memory_root=str(tmp_path))
        store = _make_fs_store(tmp_path / "store")
        result = accept_pending_proposal(proposals[0], store)

        assert result.status is MemoryStoreApplyStatus.APPLIED
        assert result.record is not None
        assert result.record.memory_type == "semantic"
        assert "pytest" in result.record.content
        # 验证 source_summary 包含 consolidation metadata
        assert "source_evidence=" in result.record.source_summary
        assert "pattern_detection" in result.record.source_summary

    def test_accept_archives_pending_file(self, tmp_path: Path):
        """accept 后 pending 文件被归档到 archived/accepted/。"""
        candidate = _make_candidate()
        dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        proposals = list_pending_proposals(memory_root=str(tmp_path))
        original_path = proposals[0].filepath
        store = _make_fs_store(tmp_path / "store")

        accept_pending_proposal(proposals[0], store)

        # 原 pending 文件不再存在
        assert not original_path.exists()
        # 归档目录中存在
        archived_dir = tmp_path / "_pending" / "archived" / "accepted"
        assert archived_dir.exists()
        archived_files = list(archived_dir.glob("*.json"))
        assert len(archived_files) == 1

    def test_accept_preserves_confidence_in_record(self, tmp_path: Path):
        """accept 后正式 record 保留 confidence。"""
        candidate = _make_candidate(confidence=0.77)
        dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        proposals = list_pending_proposals(memory_root=str(tmp_path))
        store = _make_fs_store(tmp_path / "store")
        result = accept_pending_proposal(proposals[0], store)

        assert result.record is not None
        # confidence 在 metadata 中
        assert result.record.metadata.get("confidence") == 0.77

    def test_accept_preserves_source_evidence_in_source_summary(self, tmp_path: Path):
        """accept 后 source_evidence 编码在 source_summary 中保留。"""
        candidate = _make_candidate(
            source_evidence=("ep_a1", "ep_b2", "ep_c3"),
        )
        dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        proposals = list_pending_proposals(memory_root=str(tmp_path))
        store = _make_fs_store(tmp_path / "store")
        result = accept_pending_proposal(proposals[0], store)

        assert "ep_a1" in result.record.source_summary
        assert "ep_b2" in result.record.source_summary
        assert "ep_c3" in result.record.source_summary

    def test_accept_preserves_consolidation_type_in_source_summary(self, tmp_path: Path):
        """accept 后 consolidation_type 编码在 source_summary 中保留。"""
        candidate = _make_candidate(
            consolidation_type=ConsolidationType.MERGE,
        )
        dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        proposals = list_pending_proposals(memory_root=str(tmp_path))
        store = _make_fs_store(tmp_path / "store")
        result = accept_pending_proposal(proposals[0], store)

        assert "[consolidation:merge]" in result.record.source_summary

    def test_accept_preserves_preference_evolved_metadata(self, tmp_path: Path):
        """accept 后 preference_evolved 作为 semantic record 写入并保留 metadata。"""
        candidate = _make_candidate(
            consolidation_type=ConsolidationType.PREFERENCE_EVOLVED,
            source_evidence=("pref_old", "pref_new_a", "pref_new_b"),
            content="用户测试框架偏好从 unittest 演进为 pytest",
        )
        dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        proposals = list_pending_proposals(memory_root=str(tmp_path))
        store = _make_fs_store(tmp_path / "store")
        result = accept_pending_proposal(proposals[0], store)

        assert result.record is not None
        assert result.record.memory_type == "semantic"
        assert "[consolidation:preference_evolved]" in result.record.source_summary
        assert "pref_old" in result.record.source_summary
        assert "pref_new_a" in result.record.source_summary
        assert "pref_new_b" in result.record.source_summary


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Review CLI — reject
# ═══════════════════════════════════════════════════════════════════════════════


class TestReviewCLIReject:
    """验证 reject 不写入正式 memory store。"""

    def test_reject_does_not_write_to_store(self, tmp_path: Path):
        """reject consolidation proposal 后 store 中无对应 record。"""
        candidate = _make_candidate()
        dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        proposals = list_pending_proposals(memory_root=str(tmp_path))
        store = _make_fs_store(tmp_path / "store")

        # reject 不应抛出异常
        reject_pending_proposal(proposals[0])

        # store 为空（未写入）
        records = store.list_records()
        assert len(records) == 0

    def test_reject_archives_pending_file(self, tmp_path: Path):
        """reject 后 pending 文件归档到 archived/rejected/。"""
        candidate = _make_candidate()
        dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        proposals = list_pending_proposals(memory_root=str(tmp_path))
        original_path = proposals[0].filepath

        reject_pending_proposal(proposals[0])

        assert not original_path.exists()
        archived_dir = tmp_path / "_pending" / "archived" / "rejected"
        assert archived_dir.exists()


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Review CLI — edit-and-accept
# ═══════════════════════════════════════════════════════════════════════════════


class TestReviewCLIEdit:
    """验证 edit-and-accept 使用编辑后的 content 写入。"""

    def test_edit_and_accept_uses_edited_content(self, tmp_path: Path):
        """edit-and-accept 后 record content 是编辑后的内容。"""
        candidate = _make_candidate(content="用户偏好 pytest")
        dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        proposals = list_pending_proposals(memory_root=str(tmp_path))
        store = _make_fs_store(tmp_path / "store")
        result = edit_and_accept_pending_proposal(
            proposals[0], "用户强烈偏好 pytest，尤其是 fixture 机制", store,
        )

        assert result.status is MemoryStoreApplyStatus.APPLIED
        assert "强烈偏好" in result.record.content
        assert "fixture" in result.record.content

    def test_edit_and_accept_preserves_consolidation_metadata(self, tmp_path: Path):
        """edit-and-accept 后仍保留 consolidation metadata 在 source_summary 中。"""
        candidate = _make_candidate(
            consolidation_type=ConsolidationType.ABSTRACTION,
        )
        dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        proposals = list_pending_proposals(memory_root=str(tmp_path))
        store = _make_fs_store(tmp_path / "store")
        result = edit_and_accept_pending_proposal(
            proposals[0], "编辑后的语义内容", store,
        )

        assert "[consolidation:abstraction]" in result.record.source_summary

    def test_edit_rejects_empty_content(self, tmp_path: Path):
        """edit-and-accept 时编辑后 content 为空抛出 ValueError。"""
        candidate = _make_candidate()
        dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        proposals = list_pending_proposals(memory_root=str(tmp_path))
        store = _make_fs_store(tmp_path / "store")

        with pytest.raises(ValueError, match="不能为空"):
            edit_and_accept_pending_proposal(proposals[0], "   ", store)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Review CLI — skip
# ═══════════════════════════════════════════════════════════════════════════════


class TestReviewCLISkip:
    """验证 skip 保持 pending 状态。"""

    def test_skip_keeps_pending_file(self, tmp_path: Path):
        """skip 后 pending 文件仍存在。"""
        candidate = _make_candidate()
        dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        proposals = list_pending_proposals(memory_root=str(tmp_path))
        original_path = proposals[0].filepath

        skip_pending_proposal(proposals[0])

        # skip 不修改文件，仍为 pending
        assert original_path.exists()
        # 再次列出仍可见
        still_pending = list_pending_proposals(memory_root=str(tmp_path))
        assert len(still_pending) == 1

    def test_skip_does_not_write_to_store(self, tmp_path: Path):
        """skip 后不写入 store。"""
        candidate = _make_candidate()
        dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        proposals = list_pending_proposals(memory_root=str(tmp_path))
        store = _make_fs_store(tmp_path / "store")

        skip_pending_proposal(proposals[0])

        records = store.list_records()
        assert len(records) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 11. 不调用 LLM / 不读 env / 不接 runtime
# ═══════════════════════════════════════════════════════════════════════════════


class TestNoLLMOrRuntime:
    """验证 consolidation review module 不调用 LLM / 不接 runtime。"""

    def test_module_does_not_import_llm(self):
        """AST 级验证不 import anthropic 或 LLM 相关模块。"""
        import ast
        from pathlib import Path

        src = Path("agent/memory_consolidation_review.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "anthropic" not in alias.name.lower(), (
                        f"禁止 import LLM 模块: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert "anthropic" not in node.module.lower(), (
                    f"禁止 import LLM 模块: {node.module}"
                )

    def test_module_does_not_import_store_write(self):
        """验证不 import store 写相关模块。"""
        import ast
        from pathlib import Path

        src = Path("agent/memory_consolidation_review.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "memory_fs_store" not in node.module, (
                    "dispatch 模块不应 import FS store"
                )

    def test_does_not_call_llm(self, tmp_path: Path):
        """dispatch 时不对真实 LLM 做网络调用（无 monkeypatch 也能运行）。"""
        candidate = _make_candidate()
        # 无 monkeypatch，直接调用不应触发 HTTP 请求
        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )
        assert result.dispatched == 1

    def test_does_not_read_env(self, monkeypatch, tmp_path: Path):
        """dispatch 不读取 .env 文件。"""
        # 移除所有环境变量，验证仍能正常运行
        import os
        for key in list(os.environ.keys()):
            if key.startswith("MEMORY_"):
                monkeypatch.delenv(key, raising=False)

        candidate = _make_candidate()
        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )
        assert result.dispatched == 1

    def test_does_not_read_agent_log(self, tmp_path: Path):
        """dispatch 不读取 agent_log.jsonl。"""
        # 创建 agent_log.jsonl 包含 mock 数据
        log_path = tmp_path / "agent_log.jsonl"
        log_path.write_text('{"event": "test"}\n', encoding="utf-8")

        # 在父目录执行 dispatch，不依赖 agent_log
        candidate = _make_candidate()
        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path / "memory",
        )
        assert result.dispatched == 1  # 不因 log 文件存在/不存在而崩溃


# ═══════════════════════════════════════════════════════════════════════════════
# 12. ConsolidationPendingDispatchResult
# ═══════════════════════════════════════════════════════════════════════════════


class TestDispatchResult:
    """验证 ConsolidationPendingDispatchResult dataclass 行为。"""

    def test_result_is_frozen(self):
        """result 应是 frozen dataclass（不可变）。"""
        r = ConsolidationPendingDispatchResult(
            dispatched=0,
            skipped_duplicate=0,
            skipped_invalid=0,
            warnings=(),
            proposal_filepaths=(),
        )
        with pytest.raises(Exception):  # noqa: B017 - frozen-dataclass setattr rejection
            r.dispatched = 5  # type: ignore

    def test_result_fields_accessible(self, tmp_path: Path):
        """正常 dispatch 后 result 字段正确。"""
        candidate = _make_candidate()
        result = dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path,
        )

        assert result.dispatched == 1
        assert result.skipped_duplicate == 0
        assert result.skipped_invalid == 0
        assert len(result.warnings) == 0
        assert len(result.proposal_filepaths) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 13. 不自动 approve / 不自动写 store
# ═══════════════════════════════════════════════════════════════════════════════


class TestNoAutoRetain:
    """验证 dispatch 不自动 approve，不自动写 store。"""

    def test_dispatch_does_not_write_store(self, tmp_path: Path):
        """dispatch 后 store 中无新 record——必须经 human accept。"""
        candidate = _make_candidate()
        store_root = tmp_path / "memory_store"
        store_root.mkdir(parents=True, exist_ok=True)

        # dispatch 使用独立 memory_root
        dispatch_consolidation_candidates_to_pending_review(
            [candidate], memory_root=tmp_path / "pending_root",
        )

        # store 目录未被写入
        from agent.memory_fs_store import FilesystemMemoryStore
        store = FilesystemMemoryStore(root_dir=store_root)
        records = store.list_records()
        assert len(records) == 0

    def test_dispatch_approval_status_always_pending(self, tmp_path: Path):
        """所有 dispatch 的 pending JSON approval_status 均为 pending。"""
        candidates = [
            _make_candidate(content="偏好 A"),
            _make_candidate(content="偏好 B"),
        ]
        result = dispatch_consolidation_candidates_to_pending_review(
            candidates, memory_root=tmp_path,
        )

        for fp in result.proposal_filepaths:
            data = _read_pending_json(fp)
            assert data["approval_status"] == "pending", (
                f"approval_status 必须为 pending，实际: {data['approval_status']}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_fs_store(root: Path):
    """创建指向测试 tmp_path 的 FilesystemMemoryStore。"""
    from agent.memory_fs_store import FilesystemMemoryStore
    return FilesystemMemoryStore(root_dir=root)
