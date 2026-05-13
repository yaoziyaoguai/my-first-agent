"""Phase 6 ConsolidationCandidate domain model 的确定性测试。

测试范围：
- ConsolidationCandidate 字段校验
- ConsolidationType 枚举
- to_memory_operation_intent_for_review() 转换函数
- 不测试：consolidation engine、runtime integration、store 写入、真实 LLM
"""

import pytest

from agent.memory_consolidation import (
    ConsolidationCandidate,
    ConsolidationType,
    to_memory_operation_intent_for_review,
)
from agent.memory_extraction import SuggestedAction


# ── helpers ──────────────────────────────────────────────────────────────────

def _valid_candidate(**overrides) -> ConsolidationCandidate:
    defaults = {
        "content": "用户偏好使用 pytest 作为 Python 测试框架",
        "memory_type": "semantic",
        "source_evidence": (
            "episodic:abc123",
            "episodic:def456",
            "episodic:ghi789",
        ),
        "consolidation_type": ConsolidationType.PATTERN_DETECTION,
        "confidence": 0.85,
        "governance_route": "T1",
        "evidence_summary": "3 条 episodic 均涉及 pytest 偏好",
        "created_at": "2026-05-13T10:00:00Z",
    }
    defaults.update(overrides)
    return ConsolidationCandidate(**defaults)


# ── ConsolidationType enum ───────────────────────────────────────────────────


class TestConsolidationTypeEnum:
    def test_all_values_present(self):
        """所有 RFC §6.3 + §D.3 定义的 consolidation 类型均存在。"""
        values = set(ConsolidationType)
        assert values == {
            ConsolidationType.PATTERN_DETECTION,
            ConsolidationType.MERGE,
            ConsolidationType.ABSTRACTION,
            ConsolidationType.CLARIFICATION_NEEDED,
            ConsolidationType.PREFERENCE_EVOLVED,
        }

    def test_each_type_creates_valid_candidate(self):
        """每种 consolidation_type 均可创建有效 candidate。"""
        for ctype in ConsolidationType:
            candidate = _valid_candidate(consolidation_type=ctype)
            assert candidate.consolidation_type == ctype


# ── 正常构造 ──────────────────────────────────────────────────────────────────


class TestValidCandidate:
    def test_all_fields_stored(self):
        """正常构造时所有字段正确存储。"""
        c = _valid_candidate()
        assert c.content == "用户偏好使用 pytest 作为 Python 测试框架"
        assert c.memory_type == "semantic"
        assert c.source_evidence == (
            "episodic:abc123",
            "episodic:def456",
            "episodic:ghi789",
        )
        assert c.consolidation_type == ConsolidationType.PATTERN_DETECTION
        assert c.confidence == 0.85
        assert c.governance_route == "T1"
        assert c.evidence_summary == "3 条 episodic 均涉及 pytest 偏好"
        assert c.created_at == "2026-05-13T10:00:00Z"

    def test_minimal_source_evidence(self):
        """source_evidence 最小 2 条即可通过。"""
        c = _valid_candidate(
            source_evidence=("episodic:001", "episodic:002"),
        )
        assert len(c.source_evidence) == 2

    def test_boundary_confidence_zero(self):
        """confidence=0.0 可通过。"""
        c = _valid_candidate(confidence=0.0)
        assert c.confidence == 0.0

    def test_boundary_confidence_one(self):
        """confidence=1.0 可通过。"""
        c = _valid_candidate(confidence=1.0)
        assert c.confidence == 1.0

    def test_frozen_immutable(self):
        """ConsolidationCandidate 是 frozen dataclass，赋值应抛出异常。"""
        from dataclasses import FrozenInstanceError

        c = _valid_candidate()
        with pytest.raises(FrozenInstanceError):
            c.content = "new"  # type: ignore[misc]


# ── memory_type 校验 ─────────────────────────────────────────────────────────


class TestMemoryTypeValidation:
    def test_must_be_semantic(self):
        """memory_type 非 'semantic' 时抛出 ValueError。"""
        with pytest.raises(ValueError, match="memory_type"):
            _valid_candidate(memory_type="episodic")

    def test_procedural_rejected(self):
        """memory_type='procedural' 被拒绝（consolidation 只产出 semantic，RFC §6.5）。"""
        with pytest.raises(ValueError, match="memory_type"):
            _valid_candidate(memory_type="procedural")

    def test_arbitrary_string_rejected(self):
        """任意非 semantic 字符串被拒绝。"""
        with pytest.raises(ValueError, match="memory_type"):
            _valid_candidate(memory_type="knowledge")


# ── source_evidence 校验 ──────────────────────────────────────────────────────


class TestSourceEvidenceValidation:
    def test_empty_tuple_rejected(self):
        """source_evidence 为空时抛出 ValueError。"""
        with pytest.raises(ValueError, match="source_evidence"):
            _valid_candidate(source_evidence=())

    def test_single_element_rejected(self):
        """source_evidence 仅 1 条时抛出 ValueError。"""
        with pytest.raises(ValueError, match="source_evidence"):
            _valid_candidate(source_evidence=("episodic:001",))

    def test_empty_string_entry_rejected(self):
        """source_evidence 中含空字符串时抛出 ValueError。"""
        with pytest.raises(ValueError, match="source_evidence"):
            _valid_candidate(source_evidence=("episodic:001", "   "))


# ── confidence 校验 ─────────────────────────────────────────────────────────


class TestConfidenceValidation:
    def test_negative_rejected(self):
        """confidence < 0.0 时抛出 ValueError。"""
        with pytest.raises(ValueError, match="confidence"):
            _valid_candidate(confidence=-0.1)

    def test_above_one_rejected(self):
        """confidence > 1.0 时抛出 ValueError。"""
        with pytest.raises(ValueError, match="confidence"):
            _valid_candidate(confidence=1.01)


# ── governance_route 校验 ─────────────────────────────────────────────────────


class TestGovernanceValidation:
    def test_must_be_t1(self):
        """governance_route 非 'T1' 时抛出 ValueError。"""
        with pytest.raises(ValueError, match="governance_route"):
            _valid_candidate(governance_route="T2")

    def test_t3_rejected(self):
        """governance_route='T3' 被拒绝。"""
        with pytest.raises(ValueError, match="governance_route"):
            _valid_candidate(governance_route="T3")

    def test_arbitrary_string_rejected(self):
        """任意非 T1 字符串被拒绝。"""
        with pytest.raises(ValueError, match="governance_route"):
            _valid_candidate(governance_route="auto_retain")


# ── 必填字段校验 ──────────────────────────────────────────────────────────────


class TestRequiredFields:
    def test_empty_content_rejected(self):
        """content 为空时抛出 ValueError。"""
        with pytest.raises(ValueError, match="content"):
            _valid_candidate(content="")

    def test_whitespace_content_rejected(self):
        """content 全空白时抛出 ValueError。"""
        with pytest.raises(ValueError, match="content"):
            _valid_candidate(content="   ")

    def test_empty_evidence_summary_rejected(self):
        """evidence_summary 为空时抛出 ValueError。"""
        with pytest.raises(ValueError, match="evidence_summary"):
            _valid_candidate(evidence_summary="")

    def test_empty_created_at_rejected(self):
        """created_at 为空时抛出 ValueError。"""
        with pytest.raises(ValueError, match="created_at"):
            _valid_candidate(created_at="")


# ── to_memory_operation_intent_for_review 转换 ────────────────────────────────


class TestConversionToProposal:
    def test_produces_valid_proposal(self):
        """转换结果可构造为有效的 MemoryCandidateProposal。"""
        c = _valid_candidate()
        proposal = to_memory_operation_intent_for_review(c)
        # 不抛异常 = 通过 proposal.__post_init__
        assert proposal.memory_type == "semantic"

    def test_preserves_content(self):
        """转换后 content 保持一致。"""
        c = _valid_candidate()
        proposal = to_memory_operation_intent_for_review(c)
        assert proposal.content == c.content

    def test_preserves_confidence(self):
        """转换后 confidence 保持一致。"""
        c = _valid_candidate(confidence=0.72)
        proposal = to_memory_operation_intent_for_review(c)
        assert proposal.confidence == 0.72

    def test_preserves_source_evidence_in_rationale(self):
        """source_evidence 通过 rationale 字段传递到 proposal。"""
        evidence = ("episodic:aa", "episodic:bb", "episodic:cc")
        c = _valid_candidate(source_evidence=evidence)
        proposal = to_memory_operation_intent_for_review(c)
        assert "episodic:aa" in proposal.rationale
        assert "episodic:bb" in proposal.rationale
        assert "episodic:cc" in proposal.rationale

    def test_enforces_t1_governance(self):
        """转换后 requires_confirmation=True，suggested_action=PROPOSE（T1 强制）。"""
        c = _valid_candidate(governance_route="T1")
        proposal = to_memory_operation_intent_for_review(c)
        assert proposal.requires_confirmation is True
        assert proposal.suggested_action == SuggestedAction.PROPOSE

    def test_never_auto_retain(self):
        """转换结果绝不使用 AUTO_RETAIN_CANDIDATE（T2 路径不做）。"""
        c = _valid_candidate()
        proposal = to_memory_operation_intent_for_review(c)
        assert proposal.suggested_action != SuggestedAction.AUTO_RETAIN_CANDIDATE

    def test_no_side_effects(self):
        """转换函数不写 store，不产生 side effect。"""
        c = _valid_candidate()
        proposal = to_memory_operation_intent_for_review(c)
        # 多次调用结果一致（幂等）
        proposal2 = to_memory_operation_intent_for_review(c)
        assert proposal.content == proposal2.content
        assert proposal.confidence == proposal2.confidence
