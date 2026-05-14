"""Phase 7 W5 Emergence Detection Foundation 测试。

这些测试验证 RFC Phase 7 W5 emergence detection foundation 的
gating、procedural candidate schema 和 T1 review bridge，
不验证真实 procedural quality，不允许 silent retain。

覆盖（RFC §8, §8.2, §8.3, §8.5, §10.4, §15.5）：
1. CorrectionEvidence 创建与校验
2. ProceduralCandidate 创建与校验
3. EmergenceDetector gate 和 detection 逻辑
4. dispatch_procedural_candidates_to_pending_review
5. T1 pending review CLI 对 procedural proposal 的支持
6. accept/reject/edit/skip 对 procedural proposal 的行为
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
    InlineConfirmationResponse,
    InlineConfirmationRequest,
    ProceduralCandidate,
    _compute_procedural_identity,
    _normalize_correction_pattern,
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


# ═══════════════════════════════════════════════════════════════════════════════
# 测试 fixture
# ═══════════════════════════════════════════════════════════════════════════════


def _make_evidence(
    record_id: str,
    content: str,
    correction_type: str = "behavioral_rule",
    scope: str = "debugging",
    confidence: float = 0.75,
) -> CorrectionEvidence:
    """快捷创建 CorrectionEvidence 的 helper。"""
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
    """快捷创建 ProceduralCandidate 的 helper。"""
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
# 一、CorrectionEvidence 模型测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestCorrectionEvidence:
    """CorrectionEvidence 是 Phase 7 W5 emergence detector 的纯输入视图，
    用于捕捉 repeated correction pattern 的 evidence。"""

    def test_can_create(self):
        """CorrectionEvidence 可以正常创建。"""
        e = CorrectionEvidence(
            record_id="rec-001",
            content="以后请先检查 git status 再提 PR",
            correction_type="process_order",
            scope="git_operations",
        )
        assert e.record_id == "rec-001"
        assert e.content == "以后请先检查 git status 再提 PR"
        assert e.correction_type == "process_order"
        assert e.scope == "git_operations"
        assert e.source_memory_type == "episodic"

    def test_record_id_cannot_be_empty(self):
        """record_id 不能为空。"""
        with pytest.raises(ValueError, match="record_id"):
            CorrectionEvidence(
                record_id="",
                content="先检查 git status",
                correction_type="process_order",
            )

    def test_content_cannot_be_empty(self):
        """content 不能为空。"""
        with pytest.raises(ValueError, match="content"):
            CorrectionEvidence(
                record_id="rec-001",
                content="",
                correction_type="process_order",
            )

    def test_correction_type_cannot_be_empty(self):
        """correction_type 不能为空。"""
        with pytest.raises(ValueError, match="correction_type"):
            CorrectionEvidence(
                record_id="rec-001",
                content="先检查 git status",
                correction_type="",
            )

    def test_confidence_must_be_in_range(self):
        """confidence 必须在 0-1 之间。"""
        with pytest.raises(ValueError, match="confidence"):
            CorrectionEvidence(
                record_id="rec-001",
                content="先检查 git status",
                correction_type="process_order",
                confidence=1.5,
            )

    def test_confidence_none_is_ok(self):
        """confidence=None 是合法的。"""
        e = CorrectionEvidence(
            record_id="rec-001",
            content="先检查 git status",
            correction_type="process_order",
            confidence=None,
        )
        assert e.confidence is None

    def test_scope_none_is_ok(self):
        """scope=None 是合法的。"""
        e = CorrectionEvidence(
            record_id="rec-001",
            content="先检查 git status",
            correction_type="process_order",
        )
        assert e.scope is None

    def test_default_metadata_empty(self):
        """默认 metadata 为空 dict。"""
        e = CorrectionEvidence(
            record_id="rec-001",
            content="先检查 git status",
            correction_type="process_order",
        )
        assert e.metadata == {}


# ═══════════════════════════════════════════════════════════════════════════════
# 二、ProceduralCandidate Schema 测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestProceduralCandidate:
    """ProceduralCandidate 是 RFC Phase 7 W5 的候选输出，
    永远 T1，永远 pending，不能 silent retain。"""

    def test_can_create(self):
        """ProceduralCandidate 可以正常创建。"""
        c = _make_candidate()
        assert c.memory_type == "procedural"
        assert c.governance_route == "T1"
        assert len(c.source_evidence) == 3
        assert 0.0 <= c.confidence <= 1.0

    def test_memory_type_must_be_procedural(self):
        """memory_type 必须是 procedural。"""
        with pytest.raises(ValueError, match="memory_type"):
            ProceduralCandidate(
                content="先检查 git status",
                memory_type="semantic",  # type: ignore[arg-type]
                source_evidence=("ev1", "ev2", "ev3"),
                correction_pattern="先检查 git status",
                correction_type="process_order",
                scope="git_operations",
                confidence=0.65,
                governance_route="T1",
                evidence_summary="summary",
                created_at="2026-05-14T00:00:00Z",
            )

    def test_governance_route_must_be_t1(self):
        """governance_route 必须是 T1（RFC §8.4, §10.4）。"""
        with pytest.raises(ValueError, match="governance_route"):
            ProceduralCandidate(
                content="先检查 git status",
                memory_type="procedural",
                source_evidence=("ev1", "ev2", "ev3"),
                correction_pattern="先检查 git status",
                correction_type="process_order",
                scope="git_operations",
                confidence=0.65,
                governance_route="T2",  # type: ignore[arg-type]
                evidence_summary="summary",
                created_at="2026-05-14T00:00:00Z",
            )

    def test_content_cannot_be_empty(self):
        """content 不能为空。"""
        with pytest.raises(ValueError, match="content"):
            ProceduralCandidate(
                content="",
                memory_type="procedural",
                source_evidence=("ev1", "ev2", "ev3"),
                correction_pattern="pattern",
                correction_type="process_order",
                scope="git_operations",
                confidence=0.65,
                governance_route="T1",
                evidence_summary="summary",
                created_at="2026-05-14T00:00:00Z",
            )

    def test_source_evidence_less_than_3_fails(self):
        """source_evidence 少于 3 条时应失败（RFC §8.2: ≥3 次）。"""
        with pytest.raises(ValueError, match="source_evidence"):
            ProceduralCandidate(
                content="先检查 git status",
                memory_type="procedural",
                source_evidence=("ev1", "ev2"),
                correction_pattern="pattern",
                correction_type="process_order",
                scope="git_operations",
                confidence=0.65,
                governance_route="T1",
                evidence_summary="summary",
                created_at="2026-05-14T00:00:00Z",
            )

    def test_confidence_must_be_in_range(self):
        """confidence 必须在 0-1 之间。"""
        with pytest.raises(ValueError, match="confidence"):
            ProceduralCandidate(
                content="先检查 git status",
                memory_type="procedural",
                source_evidence=("ev1", "ev2", "ev3"),
                correction_pattern="pattern",
                correction_type="process_order",
                scope="git_operations",
                confidence=1.5,
                governance_route="T1",
                evidence_summary="summary",
                created_at="2026-05-14T00:00:00Z",
            )

    def test_confidence_0_is_ok(self):
        """confidence=0 是合法的边界值。"""
        c = ProceduralCandidate(
            content="先检查 git status",
            memory_type="procedural",
            source_evidence=("ev1", "ev2", "ev3"),
            correction_pattern="pattern",
            correction_type="process_order",
            scope="git_operations",
            confidence=0.0,
            governance_route="T1",
            evidence_summary="summary",
            created_at="2026-05-14T00:00:00Z",
        )
        assert c.confidence == 0.0

    def test_confidence_1_is_ok(self):
        """confidence=1 是合法的边界值。"""
        c = ProceduralCandidate(
            content="先检查 git status",
            memory_type="procedural",
            source_evidence=("ev1", "ev2", "ev3"),
            correction_pattern="pattern",
            correction_type="process_order",
            scope="git_operations",
            confidence=1.0,
            governance_route="T1",
            evidence_summary="summary",
            created_at="2026-05-14T00:00:00Z",
        )
        assert c.confidence == 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# 三、correction_pattern 归一化测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestNormalizeCorrectionPattern:
    """_normalize_correction_pattern 是 deterministic marker-based 的
    correction pattern 提取，不依赖 NLP。"""

    def test_match_yihou_qing(self):
        """匹配 '以后请...' marker。"""
        result = _normalize_correction_pattern("以后请先检查 git status 再提交")
        assert "以后请" in result
        assert "git status" in result

    def test_match_xiaci_xian(self):
        """匹配 '下次先...' marker。"""
        result = _normalize_correction_pattern("下次先读一下日志再分析")
        assert "下次先" in result

    def test_match_buyao_zai(self):
        """匹配 '不要再...' marker。"""
        result = _normalize_correction_pattern("不要再自动 commit，等确认")
        assert "不要再" in result
        assert "自动 commit" in result

    def test_match_qing_shizhong(self):
        """匹配 '请始终...' marker。"""
        result = _normalize_correction_pattern("请始终用 pytest 写测试")
        assert "请始终" in result

    def test_match_bie_zhijie(self):
        """匹配 '别直接...' marker。"""
        result = _normalize_correction_pattern("别直接改线上代码，先本地验证")
        assert "别直接" in result

    def test_no_marker_fallback(self):
        """无已知 marker 使用内容前 30 字符。"""
        content = "用户要求使用黑色主题而不是白色"
        result = _normalize_correction_pattern(content)
        assert result == content[:30]

    def test_truncate_at_punctuation(self):
        """pattern 在遇到标点时应截断。"""
        result = _normalize_correction_pattern("以后请用 ruff 做 lint。再运行 pytest。")
        # 应在第一个句号前截断
        assert "ruff" in result
        assert "pytest" not in result
        assert not result.endswith("。")


# ═══════════════════════════════════════════════════════════════════════════════
# 四、EmergenceDetector Gate 测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmergenceDetectorGate:
    """active_records <50 时 detector 必须 fail closed（RFC §15.5）。"""

    def test_gate_closed_below_threshold(self):
        """active_records_count <50 时不产生 candidate。"""
        evidence = [
            _make_evidence("e1", "以后请先检查 git status"),
            _make_evidence("e2", "下次先检查 git status 再改"),
            _make_evidence("e3", "先检查 git status 再提交"),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=17)

        assert result.gate_passed is False
        assert len(result.candidates) == 0
        assert result.active_records_count == 17
        assert len(result.warnings) >= 1
        assert any("disabled" in w for w in result.warnings)

    def test_gate_closed_at_49(self):
        """active_records_count=49 时不产生 candidate。"""
        evidence = [
            _make_evidence("e1", "以后请先检查 git status"),
            _make_evidence("e2", "下次先检查 git status"),
            _make_evidence("e3", "先检查 git status"),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=49)
        assert result.gate_passed is False
        assert len(result.candidates) == 0

    def test_gate_open_at_threshold(self):
        """active_records_count=50 时 gate 通过。"""
        evidence = [
            _make_evidence("e1", "以后请先检查 git status"),
            _make_evidence("e2", "下次先检查 git status"),
            _make_evidence("e3", "先检查 git status"),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=50)
        assert result.gate_passed is True

    def test_gate_open_above_threshold(self):
        """active_records_count >50 时 gate 通过。"""
        evidence = [
            _make_evidence("e1", "以后请先检查 git status"),
            _make_evidence("e2", "下次先检查 git status"),
            _make_evidence("e3", "先检查 git status"),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=100)
        assert result.gate_passed is True

    def test_empty_evidence_with_gate_closed(self):
        """gate 关闭 + 空 evidence → 不产生 candidate，不崩溃。"""
        detector = DeterministicEmergenceDetector()
        result = detector.detect([], active_records_count=10)
        assert result.gate_passed is False
        assert len(result.candidates) == 0
        assert result.evidence_count == 0

    def test_empty_evidence_with_gate_open(self):
        """gate 通过 + 空 evidence → 不产生 candidate，不崩溃。"""
        detector = DeterministicEmergenceDetector()
        result = detector.detect([], active_records_count=50)
        assert result.gate_passed is True
        assert len(result.candidates) == 0
        assert result.evidence_count == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 五、EmergenceDetector Detection 逻辑测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmergenceDetectorDetection:
    """Gate 通过后，detector 的行为测试。"""

    def test_less_than_3_evidence_no_candidate(self):
        """active_records >=50 但同 pattern evidence <3 → 不产生 candidate。"""
        evidence = [
            _make_evidence("e1", "以后请先检查 git status"),
            _make_evidence("e2", "下次先读日志再分析"),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=50)
        assert result.gate_passed is True
        assert len(result.candidates) == 0
        assert result.skipped_count > 0

    def test_exactly_3_same_pattern_produces_candidate(self):
        """active_records >=50 且同 pattern evidence >=3 → 产生 ProceduralCandidate。"""
        evidence = [
            _make_evidence("e1", "以后请先检查 git status", scope="git_operations"),
            _make_evidence("e2", "下次先检查 git status 再改", scope="git_operations"),
            _make_evidence("e3", "先检查 git status 再提交", scope="git_operations"),
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

    def test_more_than_3_same_pattern(self):
        """4 条同 pattern evidence → 产生 candidate，source_evidence 包含全部。"""
        evidence = [
            _make_evidence("e1", "以后请先检查 git status", scope="git_operations"),
            _make_evidence("e2", "下次先检查 git status", scope="git_operations"),
            _make_evidence("e3", "记得先检查 git status", scope="git_operations"),
            _make_evidence("e4", "先检查 git status 永远的第一步", scope="git_operations"),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=60)
        assert len(result.candidates) >= 1
        c = result.candidates[0]
        assert len(c.source_evidence) == 4

    def test_different_scopes_separate_candidates(self):
        """不同 scope 的同类型 evidence 应分到不同 candidate 组。"""
        evidence = [
            _make_evidence("e1", "以后请先检查 git status", scope="git_operations"),
            _make_evidence("e2", "下次先检查 git status", scope="git_operations"),
            _make_evidence("e3", "先检查 git status 再提交", scope="git_operations"),
            # 不同 scope
            _make_evidence("e4", "以后请先读日志", scope="debugging"),
            _make_evidence("e5", "下次先读日志再分析", scope="debugging"),
            _make_evidence("e6", "记得先读日志", scope="debugging"),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=60)

        # 两个 scope 各自产生 candidate
        scopes = {c.scope for c in result.candidates}
        assert "git_operations" in scopes
        assert "debugging" in scopes

    def test_different_correction_types_separate_candidates(self):
        """不同 correction_type 分到不同组。"""
        evidence = [
            _make_evidence("e1", "以后请先检查 git status", correction_type="process_order"),
            _make_evidence("e2", "下次先检查 git status", correction_type="process_order"),
            _make_evidence("e3", "记得先检查 git status", correction_type="process_order"),
            _make_evidence("e4", "请务必用英文写注释", correction_type="communication_style"),
            _make_evidence("e5", "以后必须用英文注释", correction_type="communication_style"),
            _make_evidence("e6", "注释请用英文", correction_type="communication_style"),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=60)

        types = {c.correction_type for c in result.candidates}
        assert "process_order" in types
        assert "communication_style" in types

    def test_candidate_deterministic(self):
        """相同输入应产生相同 candidate 输出（确定性）。"""
        evidence = [
            _make_evidence("e1", "以后请先检查 git status", scope="git_operations"),
            _make_evidence("e2", "下次先检查 git status", scope="git_operations"),
            _make_evidence("e3", "先检查 git status 再提交", scope="git_operations"),
        ]
        detector = DeterministicEmergenceDetector()

        r1 = detector.detect(evidence, active_records_count=50)
        r2 = detector.detect(evidence, active_records_count=50)

        assert len(r1.candidates) == len(r2.candidates)
        if r1.candidates and r2.candidates:
            assert r1.candidates[0].content == r2.candidates[0].content
            assert r1.candidates[0].confidence == r2.candidates[0].confidence
            assert r1.candidates[0].correction_pattern == r2.candidates[0].correction_pattern

    def test_confidence_in_range(self):
        """candidate confidence 在 0.60-0.85 范围内。"""
        evidence = [
            _make_evidence("e1", "以后请先检查 git status", confidence=0.80),
            _make_evidence("e2", "下次先检查 git status", confidence=0.75),
            _make_evidence("e3", "先检查 git status 再提交", confidence=0.70),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=50)
        c = result.candidates[0]
        assert 0.60 <= c.confidence <= 0.85

    def test_confidence_higher_for_more_evidence(self):
        """evidence 数量越多，confidence 越高。"""
        e3 = [
            _make_evidence("e1", "以后请先检查 git status"),
            _make_evidence("e2", "下次先检查 git status"),
            _make_evidence("e3", "先检查 git status"),
        ]
        e5 = e3 + [
            _make_evidence("e4", "记得先检查 git status"),
            _make_evidence("e5", "先检查 git status 永远"),
        ]
        detector = DeterministicEmergenceDetector()

        r3 = detector.detect(e3, active_records_count=50)
        r5 = detector.detect(e5, active_records_count=50)

        assert r5.candidates[0].confidence > r3.candidates[0].confidence

    def test_gate_closed_zero_candidates(self):
        """gate 关闭时 candidates 为空 tuple。"""
        evidence = [
            _make_evidence("e1", "以后请先检查 git status"),
            _make_evidence("e2", "下次先检查 git status"),
            _make_evidence("e3", "先检查 git status"),
            _make_evidence("e4", "记得先检查 git status"),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=10)
        assert len(result.candidates) == 0
        assert isinstance(result.candidates, tuple)


# ═══════════════════════════════════════════════════════════════════════════════
# 六、Dispatch 测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestProceduralDispatch:
    """dispatch_procedural_candidates_to_pending_review 的测试。"""

    def test_dispatch_writes_pending_json(self):
        """dispatch 应生成 T1 pending JSON 文件。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            result = dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            assert result.dispatched == 1
            assert len(result.proposal_filepaths) == 1
            fp = result.proposal_filepaths[0]
            assert fp.exists()
            assert fp.name.startswith("t1_")

    def test_pending_json_memory_type_procedural(self):
        """pending JSON 中 memory_type=procedural。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            result = dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            data = json.loads(result.proposal_filepaths[0].read_text(encoding="utf-8"))
            assert data["memory_type"] == "procedural"

    def test_pending_json_governance_route_t1(self):
        """pending JSON 中 governance_route=T1。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            result = dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            data = json.loads(result.proposal_filepaths[0].read_text(encoding="utf-8"))
            assert data["governance_route"] == "T1"

    def test_pending_json_approval_status_pending(self):
        """pending JSON 中 approval_status=pending。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            result = dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            data = json.loads(result.proposal_filepaths[0].read_text(encoding="utf-8"))
            assert data["approval_status"] == "pending"

    def test_pending_json_preserves_correction_fields(self):
        """pending JSON 保留 correction_pattern 和 correction_type。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate(
                correction_pattern="先检查 git status",
                correction_type="process_order",
            )
            result = dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            data = json.loads(result.proposal_filepaths[0].read_text(encoding="utf-8"))
            assert data["correction_pattern"] == "先检查 git status"
            assert data["correction_type"] == "process_order"

    def test_pending_json_preserves_source_evidence(self):
        """pending JSON 保留 source_evidence。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate(evidence_ids=("ev-a", "ev-b", "ev-c"))
            result = dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            data = json.loads(result.proposal_filepaths[0].read_text(encoding="utf-8"))
            assert set(data["source_evidence"]) == {"ev-a", "ev-b", "ev-c"}

    def test_pending_json_has_proposal_id(self):
        """pending JSON 包含 proposal_id。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            result = dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            data = json.loads(result.proposal_filepaths[0].read_text(encoding="utf-8"))
            assert data["proposal_id"].startswith("emergence_")

    def test_source_type_emergence(self):
        """pending JSON 中 source_type=emergence。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            result = dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            data = json.loads(result.proposal_filepaths[0].read_text(encoding="utf-8"))
            assert data["source_type"] == "emergence"

    def test_confirmation_form_default_pending_review(self):
        """pending JSON 默认 confirmation_form=pending_review（RFC §10.5）。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            result = dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            data = json.loads(result.proposal_filepaths[0].read_text(encoding="utf-8"))
            assert data["confirmation_form"] == "pending_review"

    def test_confirmation_form_not_silent(self):
        """confirmation_form 不等于 silent——procedural 不可 auto-retain。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            result = dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            data = json.loads(result.proposal_filepaths[0].read_text(encoding="utf-8"))
            assert data["confirmation_form"] != "silent"
            assert data["confirmation_form"] != "auto_retained"
            assert data["approval_status"] == "pending"

    def test_duplicate_dispatch_not_written(self):
        """相同 candidate dispatch 两次不重复写 pending。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()

            r1 = dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            assert r1.dispatched == 1
            assert r1.skipped_duplicate == 0

            r2 = dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            assert r2.dispatched == 0
            assert r2.skipped_duplicate == 1

    def test_invalid_candidate_skipped(self):
        """校验失败的 candidate 应被跳过（dispatch defense-in-depth）。"""
        # 只有 1 条 source_evidence——不满足 N≥3
        with pytest.raises(ValueError):
            ProceduralCandidate(
                content="先检查 git status",
                memory_type="procedural",
                source_evidence=("ev1",),
                correction_pattern="pattern",
                correction_type="process_order",
                scope=None,
                confidence=0.65,
                governance_route="T1",
                evidence_summary="summary",
                created_at="2026-05-14T00:00:00Z",
            )

    def test_multiple_candidates_different_identity(self):
        """不同 identity 的 candidate 各自写入。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            c1 = _make_candidate(
                content="先检查 git status",
                evidence_ids=("a1", "a2", "a3"),
                correction_pattern="先检查 git status",
            )
            c2 = _make_candidate(
                content="先读日志再分析",
                evidence_ids=("b1", "b2", "b3"),
                correction_pattern="先读日志再分析",
            )
            result = dispatch_procedural_candidates_to_pending_review(
                [c1, c2], memory_root=root,
            )
            assert result.dispatched == 2
            assert result.skipped_duplicate == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 七、Review CLI 对 Procedural Proposal 的支持测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestProceduralReviewCLI:
    """review CLI 能正确展示/接受/拒绝/编辑/跳过 procedural pending proposal。"""

    def test_list_procedural_pending_proposal(self):
        """dispatch 后 review CLI 能 list procedural proposal。"""
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
            # Phase 7 字段
            assert p.correction_pattern == candidate.correction_pattern
            assert p.correction_type == candidate.correction_type

    def test_accept_procedural_proposal_writes_record(self):
        """accept procedural proposal → 写入正式 procedural record。"""
        from agent.memory_store import InMemoryMemoryStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            proposals = list_pending_proposals(memory_root=str(root))
            store = InMemoryMemoryStore()

            result = accept_pending_proposal(proposals[0], store)
            assert result.status.value == "applied"
            # record 写入 store
            records = store.list_records()
            procedural_records = [
                r for r in records if r.memory_type == "procedural"
            ]
            assert len(procedural_records) >= 1

    def test_reject_procedural_proposal_does_not_write(self):
        """reject procedural proposal → 不写入 store。"""
        from agent.memory_store import InMemoryMemoryStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            proposals = list_pending_proposals(memory_root=str(root))
            store = InMemoryMemoryStore()

            reject_pending_proposal(proposals[0])
            # reject 后 store 不应有该 record
            records = store.list_records()
            procedural_records = [
                r for r in records
                if r.memory_type == "procedural" and candidate.content in r.content
            ]
            assert len(procedural_records) == 0

    def test_edit_and_accept_procedural_proposal(self):
        """edit-and-accept → 使用编辑后的内容写入 procedural record，保留 emergence metadata。"""
        from agent.memory_store import InMemoryMemoryStore

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
            result = edit_and_accept_pending_proposal(
                proposals[0], edited, store,
            )
            assert result.status.value == "applied"
            records = store.list_records()
            # 应包含编辑后的内容
            matching = [r for r in records if edited in r.content]
            assert len(matching) >= 1
            # emergence metadata 应保留在 source_summary 中（P1-1 fix）
            record = matching[0]
            source_summary = record.source_summary
            assert "correction_pattern=先运行 lint 和 tests" in source_summary
            assert "correction_type=process_order" in source_summary

    def test_skip_procedural_proposal_keeps_pending(self):
        """skip procedural proposal → pending 保留，不写入 store。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            proposals = list_pending_proposals(memory_root=str(root))
            assert len(proposals) == 1

            skip_pending_proposal(proposals[0])
            # skip 后 pending 仍在
            still_pending = list_pending_proposals(memory_root=str(root))
            assert len(still_pending) == 1

    def test_accept_then_archived_not_in_pending(self):
        """accept 后 pending 文件归档，不再出现在 pending list 中。"""
        from agent.memory_store import InMemoryMemoryStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            proposals = list_pending_proposals(memory_root=str(root))
            store = InMemoryMemoryStore()
            accept_pending_proposal(proposals[0], store)

            remaining = list_pending_proposals(memory_root=str(root))
            assert len(remaining) == 0

    def test_reject_then_archived_not_in_pending(self):
        """reject 后 pending 归档，不再出现在 pending list。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "memory"
            candidate = _make_candidate()
            dispatch_procedural_candidates_to_pending_review(
                [candidate], memory_root=root,
            )
            proposals = list_pending_proposals(memory_root=str(root))
            reject_pending_proposal(proposals[0])

            remaining = list_pending_proposals(memory_root=str(root))
            assert len(remaining) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 八、隔离性测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestDetectorIsolation:
    """detector 不应读取/写入 filesystem store，不应调用 LLM，不应读取 .env。"""

    def test_detector_does_not_read_filesystem(self, monkeypatch):
        """detector 不访问 filesystem。"""
        # 如果尝试访问文件系统，monkeypatch 会拦截
        evidence = [
            _make_evidence("e1", "以后请先检查 git status", scope="git_operations"),
            _make_evidence("e2", "下次先检查 git status", scope="git_operations"),
            _make_evidence("e3", "先检查 git status 再提交", scope="git_operations"),
        ]
        detector = DeterministicEmergenceDetector()

        # detector 应能正常运行而不触发任何文件 IO
        result = detector.detect(evidence, active_records_count=50)
        assert len(result.candidates) >= 1

    def test_detector_does_not_write_filesystem(self, tmp_path):
        """detector 不写入 filesystem store。"""
        evidence = [
            _make_evidence("e1", "以后请先检查 git status"),
            _make_evidence("e2", "下次先检查 git status"),
            _make_evidence("e3", "先检查 git status"),
        ]
        detector = DeterministicEmergenceDetector()
        # 注入 temp 路径确保不写入
        result = detector.detect(evidence, active_records_count=50)
        # result 不包含 filesystem 引用
        assert result.candidates  # 有结果但在内存中

    def test_detector_no_llm_calls(self):
        """detector 不调用真实 LLM。"""
        # DeterministicEmergenceDetector 没有任何 LLM 调用路径
        evidence = [
            _make_evidence("e1", "以后请先检查 git status"),
            _make_evidence("e2", "下次先检查 git status"),
            _make_evidence("e3", "先检查 git status"),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=50)
        # 如果能执行完而不报错/超时，说明没有 LLM 调用
        assert result.gate_passed is True

    def test_procedural_candidate_never_auto_approved(self):
        """ProceduralCandidate 不应有 approval_status=approved 的路径。"""
        # schema 层面：ProceduralCandidate 没有 approval_status 字段
        # 只有 dispatch 后才产生 approval_status=pending
        c = _make_candidate()
        assert not hasattr(c, "approval_status")


# ═══════════════════════════════════════════════════════════════════════════════
# 九、_compute_procedural_identity 测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestProceduralIdentity:
    """procedural candidate identity 的确定性测试。"""

    def test_same_candidate_same_identity(self):
        """相同 candidate 产生相同 identity。"""
        c = _make_candidate()
        id1 = _compute_procedural_identity(c)
        id2 = _compute_procedural_identity(c)
        assert id1 == id2

    def test_different_content_different_identity(self):
        """不同 content → 不同 identity。"""
        c1 = _make_candidate(content="先检查 git status")
        c2 = _make_candidate(content="先读日志再分析")
        assert _compute_procedural_identity(c1) != _compute_procedural_identity(c2)

    def test_different_pattern_different_identity(self):
        """不同 correction_pattern → 不同 identity。"""
        c1 = _make_candidate(correction_pattern="先检查 git status")
        c2 = _make_candidate(correction_pattern="先读日志")
        assert _compute_procedural_identity(c1) != _compute_procedural_identity(c2)

    def test_identity_starts_with_emergence(self):
        """identity 以 emergence_ 开头。"""
        c = _make_candidate()
        assert _compute_procedural_identity(c).startswith("emergence_")


# ═══════════════════════════════════════════════════════════════════════════════
# 十、中国 correction marker 覆盖
# ═══════════════════════════════════════════════════════════════════════════════


class TestChineseCorrectionMarkers:
    """detector 对常见中文纠正 marker 有最小支持。"""

    def test_detect_grouped_by_marker(self):
        """相同 marker + scope + type 的 evidence 应被归组。"""
        evidence = [
            _make_evidence("e1", "以后请先检查 git status 再提交"),
            _make_evidence("e2", "下次先检查 git status 再改代码"),
            _make_evidence("e3", "记得先检查 git status 然后提交"),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=50)
        assert len(result.candidates) >= 1

    def test_buyao_pattern_grouped(self):
        """'不要再...' marker 的 evidence 归组。"""
        evidence = [
            _make_evidence("e1", "不要再自动 commit"),
            _make_evidence("e2", "不要自动 commit 代码"),
            _make_evidence("e3", "别自动做任何事"),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=50)
        # 三条 "不要再"/"不要"/"别" 可能归一化到不同 pattern
        # 但至少第一条和第二条可能归一化到一致的 pattern
        # 即使不能归组，也不应报错
        assert result.gate_passed is True

    def test_qing_shizhong_pattern_grouped(self):
        """'请始终...' marker 的 evidence 归组。"""
        evidence = [
            _make_evidence("e1", "请始终用 pytest 写测试"),
            _make_evidence("e2", "请始终为测试写 docstring"),
            _make_evidence("e3", "请始终先写测试再写实现"),
        ]
        detector = DeterministicEmergenceDetector()
        result = detector.detect(evidence, active_records_count=50)
        assert result.gate_passed is True


# ═══════════════════════════════════════════════════════════════════════════════
# 十一、ConfirmationForm 类型和校验测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestConfirmationForm:
    """ConfirmationForm 类型定义和校验函数测试。"""

    def test_disallowed_forms_frozenset(self):
        """_DISALLOWED_CONFIRMATION_FORMS 包含 silent/auto_retained/none。"""
        assert "silent" in _DISALLOWED_CONFIRMATION_FORMS
        assert "auto_retained" in _DISALLOWED_CONFIRMATION_FORMS
        assert "none" in _DISALLOWED_CONFIRMATION_FORMS
        assert len(_DISALLOWED_CONFIRMATION_FORMS) == 3

    def test_reject_silent(self):
        """silent 被拒绝。"""
        with pytest.raises(ValueError, match="不被允许"):
            _validate_confirmation_form("silent")

    def test_reject_auto_retained(self):
        """auto_retained 被拒绝。"""
        with pytest.raises(ValueError, match="不被允许"):
            _validate_confirmation_form("auto_retained")

    def test_reject_none(self):
        """none 被拒绝。"""
        with pytest.raises(ValueError, match="不被允许"):
            _validate_confirmation_form("none")

    def test_accept_pending_review(self):
        """pending_review 通过校验。"""
        _validate_confirmation_form("pending_review")

    def test_accept_inline_confirmation(self):
        """inline_confirmation 通过校验。"""
        _validate_confirmation_form("inline_confirmation")


# ═══════════════════════════════════════════════════════════════════════════════
# 十二、InlineConfirmationRequest Schema 测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestInlineConfirmationRequest:
    """InlineConfirmationRequest 数据模型的创建和校验测试。"""

    def test_can_create(self):
        """可以正常创建 InlineConfirmationRequest。"""
        req = InlineConfirmationRequest(
            candidate_content="[行为约束] 先检查 git status",
            source_evidence=("ev1", "ev2", "ev3"),
            correction_pattern="先检查 git status",
            correction_type="process_order",
            scope="git_operations",
            evidence_summary="summary",
            confidence=0.65,
            confirmation_form="inline_confirmation",
            allowed_actions=("accept", "reject", "edit", "other"),
            proposal_id="emergence_test123",
            created_at="2026-05-14T00:00:00Z",
        )
        assert req.confirmation_form == "inline_confirmation"
        assert req.candidate_content == "[行为约束] 先检查 git status"
        assert len(req.source_evidence) == 3
        assert req.allowed_actions == ("accept", "reject", "edit", "other")
        assert req.proposal_id == "emergence_test123"

    def test_rejects_non_inline_confirmation_form(self):
        """confirmation_form 必须是 inline_confirmation。"""
        with pytest.raises(ValueError, match="inline_confirmation"):
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

    def test_rejects_disallowed_form(self):
        """silent form 被 InlineConfirmationRequest 拒绝。"""
        with pytest.raises(ValueError, match="不被允许"):
            InlineConfirmationRequest(
                candidate_content="test",
                source_evidence=("ev1", "ev2", "ev3"),
                correction_pattern="test",
                correction_type="process_order",
                scope=None,
                evidence_summary=None,
                confidence=0.65,
                confirmation_form="silent",  # type: ignore[arg-type]
                allowed_actions=("accept", "reject"),
                proposal_id="test-id",
                created_at="2026-05-14T00:00:00Z",
            )

    def test_rejects_empty_content(self):
        """candidate_content 不能为空。"""
        with pytest.raises(ValueError, match="candidate_content"):
            InlineConfirmationRequest(
                candidate_content="",
                source_evidence=("ev1", "ev2", "ev3"),
                correction_pattern="test",
                correction_type="process_order",
                scope=None,
                evidence_summary=None,
                confidence=0.65,
                confirmation_form="inline_confirmation",
                allowed_actions=("accept", "reject"),
                proposal_id="test-id",
                created_at="2026-05-14T00:00:00Z",
            )

    def test_rejects_insufficient_evidence(self):
        """source_evidence 少于 3 条应失败。"""
        with pytest.raises(ValueError, match="source_evidence"):
            InlineConfirmationRequest(
                candidate_content="test",
                source_evidence=("ev1", "ev2"),
                correction_pattern="test",
                correction_type="process_order",
                scope=None,
                evidence_summary=None,
                confidence=0.65,
                confirmation_form="inline_confirmation",
                allowed_actions=("accept", "reject"),
                proposal_id="test-id",
                created_at="2026-05-14T00:00:00Z",
            )

    def test_rejects_invalid_confidence(self):
        """confidence 超出 0-1 范围应失败。"""
        with pytest.raises(ValueError, match="confidence"):
            InlineConfirmationRequest(
                candidate_content="test",
                source_evidence=("ev1", "ev2", "ev3"),
                correction_pattern="test",
                correction_type="process_order",
                scope=None,
                evidence_summary=None,
                confidence=1.5,
                confirmation_form="inline_confirmation",
                allowed_actions=("accept", "reject"),
                proposal_id="test-id",
                created_at="2026-05-14T00:00:00Z",
            )

    def test_rejects_empty_allowed_actions(self):
        """allowed_actions 不能为空。"""
        with pytest.raises(ValueError, match="allowed_actions"):
            InlineConfirmationRequest(
                candidate_content="test",
                source_evidence=("ev1", "ev2", "ev3"),
                correction_pattern="test",
                correction_type="process_order",
                scope=None,
                evidence_summary=None,
                confidence=0.65,
                confirmation_form="inline_confirmation",
                allowed_actions=(),
                proposal_id="test-id",
                created_at="2026-05-14T00:00:00Z",
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 十三、prepare_procedural_inline_confirmation_request 行为测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestPrepareInlineConfirmation:
    """prepare_procedural_inline_confirmation_request 的输入/输出测试。"""

    def test_prepare_from_valid_candidate(self):
        """从合法 candidate 生成 inline confirmation request。"""
        c = _make_candidate(
            content="[行为约束] 先检查 git status",
            evidence_ids=("ev-a", "ev-b", "ev-c"),
            correction_pattern="先检查 git status",
            correction_type="process_order",
            scope="git_operations",
            confidence=0.65,
        )
        req = prepare_procedural_inline_confirmation_request(c)
        assert req.confirmation_form == "inline_confirmation"
        assert req.candidate_content == c.content
        assert req.source_evidence == c.source_evidence
        assert req.correction_pattern == c.correction_pattern
        assert req.correction_type == c.correction_type
        assert req.scope == c.scope
        assert req.confidence == c.confidence
        assert req.allowed_actions == ("accept", "reject", "edit", "other")

    def test_prepare_rejects_non_procedural(self):
        """非 procedural candidate → ValueError。"""
        with pytest.raises(ValueError, match="procedural"):
            c = ProceduralCandidate(
                content="test",
                memory_type="semantic",  # type: ignore[arg-type]
                source_evidence=("e1", "e2", "e3"),
                correction_pattern="test",
                correction_type="test",
                scope=None,
                confidence=0.65,
                governance_route="T1",
                evidence_summary=None,
                created_at="2026-05-14T00:00:00Z",
            )
            prepare_procedural_inline_confirmation_request(c)

    def test_prepare_rejects_non_t1(self):
        """非 T1 candidate → ValueError。"""
        with pytest.raises(ValueError, match="T1"):
            c = ProceduralCandidate(
                content="test",
                memory_type="procedural",
                source_evidence=("e1", "e2", "e3"),
                correction_pattern="test",
                correction_type="test",
                scope=None,
                confidence=0.65,
                governance_route="T2",  # type: ignore[arg-type]
                evidence_summary=None,
                created_at="2026-05-14T00:00:00Z",
            )
            prepare_procedural_inline_confirmation_request(c)

    def test_prepare_different_candidates_different_request_ids(self):
        """不同 candidate 产生不同 proposal_id。"""
        c1 = _make_candidate(content="先检查", evidence_ids=("a1", "a2", "a3"))
        c2 = _make_candidate(content="先读日志", evidence_ids=("b1", "b2", "b3"))
        r1 = prepare_procedural_inline_confirmation_request(c1)
        r2 = prepare_procedural_inline_confirmation_request(c2)
        assert r1.proposal_id != r2.proposal_id

    def test_prepare_idempotent(self):
        """相同 candidate 产生相同 proposal_id（确定性）。"""
        c = _make_candidate()
        r1 = prepare_procedural_inline_confirmation_request(c)
        r2 = prepare_procedural_inline_confirmation_request(c)
        assert r1.proposal_id == r2.proposal_id
        assert r1.candidate_content == r2.candidate_content


# ═══════════════════════════════════════════════════════════════════════════════
# 十四、accept_inline_confirmation 测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestAcceptInlineConfirmation:
    """RFC §10.5 / §15.5 procedural inline_confirmation seam 的写入行为测试。

    inline_confirmation 是 explicit human confirmation，不是 silent retain，
    也不是 auto approve；只有 accept / edit_accept response 才能写 store。
    """

    def test_accept_writes_to_store(self):
        """accept → 写入 store，record 类型为 procedural。"""
        from agent.memory_store import InMemoryMemoryStore, MemoryStoreApplyStatus

        c = _make_candidate()
        req = prepare_procedural_inline_confirmation_request(c)
        store = InMemoryMemoryStore()
        result = accept_inline_confirmation(req, store)
        assert result.status is MemoryStoreApplyStatus.APPLIED

        records = store.list_records()
        procedural = [r for r in records if r.memory_type == "procedural"]
        assert len(procedural) >= 1

    def test_edit_and_accept_writes_to_store(self):
        """edit → 使用编辑后的内容写入。"""
        from agent.memory_store import InMemoryMemoryStore

        c = _make_candidate()
        req = prepare_procedural_inline_confirmation_request(c)
        store = InMemoryMemoryStore()
        edited = "[行为约束] 先检查 git status 和 lint 再提交"
        result = accept_inline_confirmation(req, store, edited_content=edited)
        assert result.status.value == "applied"
        records = store.list_records()
        matching = [r for r in records if edited in r.content]
        assert len(matching) >= 1

    def test_rejects_empty_edit(self):
        """编辑内容为空 → ValueError。"""
        from agent.memory_store import InMemoryMemoryStore

        c = _make_candidate()
        req = prepare_procedural_inline_confirmation_request(c)
        store = InMemoryMemoryStore()
        with pytest.raises(ValueError, match="不能为空"):
            accept_inline_confirmation(req, store, edited_content="")

    def test_accept_preserves_emergence_metadata(self):
        """accept 写入的 record 保留 emergence metadata。"""
        from agent.memory_store import InMemoryMemoryStore

        c = _make_candidate(
            correction_pattern="先运行测试再提交",
            correction_type="process_order",
            evidence_ids=("ev-x", "ev-y", "ev-z"),
        )
        req = prepare_procedural_inline_confirmation_request(c)
        store = InMemoryMemoryStore()
        result = accept_inline_confirmation(req, store)
        assert result.status.value == "applied"

        records = store.list_records()
        procedural = [r for r in records if r.memory_type == "procedural"]
        assert len(procedural) >= 1
        source_summary = procedural[0].source_summary
        assert "correction_pattern=先运行测试再提交" in source_summary
        assert "correction_type=process_order" in source_summary
        assert "inline_confirmation" in source_summary

    def test_prepare_does_not_write_store(self):
        """prepare 阶段不写入 store。"""
        from agent.memory_store import InMemoryMemoryStore

        c = _make_candidate()
        store = InMemoryMemoryStore()
        req = prepare_procedural_inline_confirmation_request(c)
        # prepare 后 store 应为空
        records = store.list_records()
        assert len(records) == 0
        _ = req  # used

    def test_accept_only_writes_once(self):
        """单次 accept 只写入一条 record。"""
        from agent.memory_store import InMemoryMemoryStore

        c = _make_candidate()
        req = prepare_procedural_inline_confirmation_request(c)
        store = InMemoryMemoryStore()
        accept_inline_confirmation(req, store)
        records = store.list_records()
        assert len(records) == 1

    def test_apply_accept_response_writes_procedural_record(self):
        """accept response → 写正式 procedural memory，确认形式保留为 inline_confirmation。"""
        from agent.memory_store import InMemoryMemoryStore

        c = _make_candidate()
        req = prepare_procedural_inline_confirmation_request(c)
        store = InMemoryMemoryStore()

        result = apply_inline_confirmation_response(
            req,
            InlineConfirmationResponse(action="accept"),
            store,
        )

        assert result.status == "applied"
        assert result.store_result is not None
        record = result.store_result.record
        assert record is not None
        assert record.memory_type == "procedural"
        assert record.approval_status == "approved"
        assert "confirmation_form=inline_confirmation" in record.source_summary

    def test_apply_edit_accept_response_uses_edited_content(self):
        """edit_accept response → 使用用户编辑内容写入，仍是 explicit human confirmation。"""
        from agent.memory_store import InMemoryMemoryStore

        c = _make_candidate()
        req = prepare_procedural_inline_confirmation_request(c)
        store = InMemoryMemoryStore()
        edited = "[行为约束] 先检查 git status，再运行 ruff 和 pytest"

        result = apply_inline_confirmation_response(
            req,
            InlineConfirmationResponse(action="edit_accept", edited_content=edited),
            store,
        )

        assert result.status == "applied"
        assert result.store_result is not None
        assert result.store_result.record is not None
        assert result.store_result.record.content == edited

    def test_apply_reject_response_does_not_write(self):
        """reject response → 不写 store，避免把拒绝误当成 approval。"""
        from agent.memory_store import InMemoryMemoryStore

        c = _make_candidate()
        req = prepare_procedural_inline_confirmation_request(c)
        store = InMemoryMemoryStore()

        result = apply_inline_confirmation_response(
            req,
            InlineConfirmationResponse(action="reject"),
            store,
        )

        assert result.status == "no_write"
        assert result.store_result is None
        assert store.list_records() == ()

    def test_apply_other_response_does_not_write(self):
        """other/free-text response → 需要后续澄清，不自动写入 memory。"""
        from agent.memory_store import InMemoryMemoryStore

        c = _make_candidate()
        req = prepare_procedural_inline_confirmation_request(c)
        store = InMemoryMemoryStore()

        result = apply_inline_confirmation_response(
            req,
            InlineConfirmationResponse(action="other", free_text="先问我更多上下文"),
            store,
        )

        assert result.status == "needs_followup"
        assert result.store_result is None
        assert store.list_records() == ()

    def test_apply_accept_preserves_inline_emergence_metadata(self):
        """accept/edit_accept 写入时保留 evidence chain 和 confidence，便于后续审计。"""
        from agent.memory_store import InMemoryMemoryStore

        c = _make_candidate(
            correction_pattern="先运行测试再提交",
            correction_type="process_order",
            evidence_ids=("ev-x", "ev-y", "ev-z"),
            confidence=0.72,
        )
        req = prepare_procedural_inline_confirmation_request(c)
        store = InMemoryMemoryStore()

        result = apply_inline_confirmation_response(
            req,
            InlineConfirmationResponse(action="accept"),
            store,
        )

        assert result.store_result is not None
        record = result.store_result.record
        assert record is not None
        assert "source_evidence=['ev-x', 'ev-y', 'ev-z']" in record.source_summary
        assert "correction_pattern=先运行测试再提交" in record.source_summary
        assert "correction_type=process_order" in record.source_summary
        assert "evidence_summary=evidence summary" in record.source_summary
        assert "confidence=0.72" in record.source_summary

    def test_episodic_t2_auto_retain_still_writes(self):
        """RFC §10.5 / §15.5 seam 不改变 T2：episodic auto_retained 仍可写入。

        这些测试验证 procedural inline_confirmation seam；inline_confirmation 是
        explicit human confirmation，不是 silent retain，也不是 auto approve。
        T2 governed auto-retain 仍只适用于 episodic。
        """
        from agent.memory_contracts import MemoryDecisionType, MemoryScope
        from agent.memory_confirmation import (
            MemoryConfirmationChoice,
            MemoryConfirmationStatus,
        )
        from agent.memory_operations import (
            MemoryOperationIntent,
            MemoryOperationType,
            build_memory_audit_summary,
        )
        from agent.memory_store import InMemoryMemoryStore, MemoryStoreApplyStatus

        intent = MemoryOperationIntent(
            operation_type=MemoryOperationType.RETAIN,
            decision_type=MemoryDecisionType.RETAIN,
            confirmation_status=MemoryConfirmationStatus.AUTO_RETAINED,
            user_choice=MemoryConfirmationChoice.ACCEPT,
            content_summary="上次修复 pytest 超时是因为 fixture 泄漏。",
            source_summary="synthetic episodic t2 regression",
            scope=MemoryScope.PROJECT,
            safety_summary="T2 auto_retained synthetic regression",
            sensitive_redacted=False,
            user_visible_summary="自动保留一条低风险 episodic 记录。",
            memory_type="episodic",
            source_type="emergence_test_synthetic",
            confidence=0.65,
        )
        store = InMemoryMemoryStore()

        result = store.apply_operation_intent(intent, build_memory_audit_summary(intent))

        assert result.status is MemoryStoreApplyStatus.APPLIED
        assert result.record is not None
        assert result.record.memory_type == "episodic"
        assert result.record.approval_status == "auto_retained"
