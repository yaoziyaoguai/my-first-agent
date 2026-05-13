"""Phase 6 deterministic pattern detector 的结构性测试。

这些测试验证 RFC Phase 6 deterministic pattern detector 的结构性规则
和 governance 边界，不验证真实 semantic consolidation quality，也不读写
memory store。

测试覆盖：
- 空/不足 N≥3 evidence → 空列表
- pattern_detection / merge / abstraction 三类检测
- source_evidence 引用正确性
- governance T1 / memory_type semantic 硬约束
- confidence ∈ [0,1]
- deterministic 幂等性
- procedural-like 过滤
- store-free / LLM-free 架构边界
"""

import pytest

from agent.memory_consolidation import (
    ConsolidationType,
    EpisodicEvidence,
)
from agent.memory_consolidation_engine import (
    DeterministicConsolidationDetector,
    _extract_keywords,
    _is_procedural_like,
    _token_overlap,
    _group_by_topic,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _evidence(record_id: str, content: str, **kwargs) -> EpisodicEvidence:
    return EpisodicEvidence(record_id=record_id, content=content, **kwargs)


def _e(rid: str, content: str, tags: tuple[str, ...] = (), scope: str | None = None) -> EpisodicEvidence:
    """快捷构造 EpisodicEvidence。"""
    return EpisodicEvidence(
        record_id=rid,
        content=content,
        tags=tags,
        scope=scope,
    )


@pytest.fixture
def detector() -> DeterministicConsolidationDetector:
    return DeterministicConsolidationDetector()


# ── 关键词提取 ──────────────────────────────────────────────────────────────


class TestKeywordExtraction:
    def test_chinese_keywords(self):
        """中文文本提取关键词。"""
        kw = _extract_keywords("用户喜欢使用 pytest 作为 Python 测试框架")
        assert "pytest" in kw or "python" in kw.lower() or "测试" in kw or "用户" in kw

    def test_stopwords_filtered(self):
        """停用词被过滤。"""
        kw = _extract_keywords("这是一个测试内容")
        assert "这是" not in kw
        assert "一个" not in kw


# ── procedural-like 检测 ────────────────────────────────────────────────────


class TestProceduralLikeDetection:
    def test_procedural_pattern_detected(self):
        """'以后必须...' 模式被识别为 procedural-like。"""
        assert _is_procedural_like("以后必须先跑测试再提交代码") is True

    def test_procedural_never_pattern(self):
        """'永远不要...' 模式被识别。"""
        assert _is_procedural_like("永远不要跳过安全扫描") is True

    def test_normal_content_not_procedural(self):
        """正常语义内容不误判。"""
        assert _is_procedural_like("用户偏好使用 pytest 做 Python 测试") is False

    def test_english_procedural_detected(self):
        """英文 procedural 模式。"""
        assert _is_procedural_like("you must always check the logs first") is True


# ── token overlap ────────────────────────────────────────────────────────────


class TestTokenOverlap:
    def test_identical_sets(self):
        assert _token_overlap(frozenset({"a", "b"}), frozenset({"a", "b"})) == 1.0

    def test_disjoint_sets(self):
        assert _token_overlap(frozenset({"a"}), frozenset({"b"})) == 0.0

    def test_partial_overlap(self):
        score = _token_overlap(frozenset({"a", "b"}), frozenset({"a", "c"}))
        assert score == pytest.approx(1.0 / 3, rel=0.01)


# ── 分组逻辑 ──────────────────────────────────────────────────────────────────


class TestGroupByTopic:
    def test_empty_list(self):
        assert _group_by_topic([]) == []

    def test_single_item(self):
        groups = _group_by_topic([_e("1", "test", tags=("x",))])
        assert len(groups) == 1
        assert len(groups[0]) == 1

    def test_shared_tags_grouped(self):
        items = [
            _e("1", "a", tags=("pytest",)),
            _e("2", "b", tags=("pytest",)),
            _e("3", "c", tags=("unrelated",)),
        ]
        groups = _group_by_topic(items)
        # 1 和 2 共享 pytest，3 独立
        assert len(groups) == 2

    def test_disjoint_groups(self):
        items = [
            _e("1", "a", tags=("x",)),
            _e("2", "b", tags=("y",)),
        ]
        groups = _group_by_topic(items)
        assert len(groups) == 2


# ── 空/不足 N≥3 ─────────────────────────────────────────────────────────────


class TestDetectorInsufficientEvidence:
    def test_empty_input(self, detector):
        """空输入返回空列表。"""
        assert detector.detect([]) == []

    def test_single_evidence(self, detector):
        """单条 evidence 返回空列表（RFC §D.1 N≥3）。"""
        result = detector.detect([_e("1", "test", tags=("x",))])
        assert result == []

    def test_two_evidence_same_topic(self, detector):
        """2 条同主题 evidence 返回空列表（RFC §D.1 N≥3）。

        domain model 允许 source_evidence≥2 是底层 contract；
        detector 层按 RFC §D.1 使用 N≥3 作为 semantic consolidation 门槛。
        """
        items = [
            _e("1", "pytest 测试", tags=("pytest",)),
            _e("2", "pytest 单元测试", tags=("pytest",)),
        ]
        assert detector.detect(items) == []

    def test_two_evidence_different_topics(self, detector):
        """2 条不同主题 evidence 返回空列表。"""
        items = [
            _e("1", "pytest", tags=("testing",)),
            _e("2", "PostgreSQL", tags=("database",)),
        ]
        assert detector.detect(items) == []


# ── pattern_detection ───────────────────────────────────────────────────────


class TestPatternDetection:
    def test_three_same_topic_generates_pattern(self, detector):
        """3 条同主题 evidence 生成 pattern_detection candidate。"""
        items = [
            _e("1", "项目A 使用 pytest", tags=("pytest", "testing")),
            _e("2", "项目B 配置 pytest", tags=("pytest", "config")),
            _e("3", "项目C 迁移到 pytest", tags=("pytest", "migration")),
        ]
        result = detector.detect(items)
        assert len(result) == 1
        c = result[0]
        assert c.consolidation_type == ConsolidationType.PATTERN_DETECTION
        assert c.memory_type == "semantic"
        assert c.governance_route == "T1"
        assert len(c.source_evidence) == 3

    def test_source_evidence_correct(self, detector):
        """source_evidence 正确引用输入 record_id。"""
        items = [
            _e("ep-001", "pytest", tags=("pytest",)),
            _e("ep-002", "pytest again", tags=("pytest",)),
            _e("ep-003", "pytest again again", tags=("pytest",)),
        ]
        result = detector.detect(items)
        assert len(result) == 1
        assert set(result[0].source_evidence) == {"ep-001", "ep-002", "ep-003"}


# ── merge ────────────────────────────────────────────────────────────────────


class TestMergeDetection:
    def test_three_highly_similar_merge(self, detector):
        """3 条高度相似 evidence 生成 merge candidate。"""
        items = [
            _e("1", "pytest test framework preference", tags=("pytest", "testing", "preference")),
            _e("2", "preference for pytest testing framework", tags=("pytest", "testing", "preference")),
            _e("3", "testing framework preference pytest", tags=("pytest", "testing", "preference")),
        ]
        result = detector.detect(items)
        assert len(result) == 1
        assert result[0].consolidation_type == ConsolidationType.MERGE


# ── abstraction ─────────────────────────────────────────────────────────────


class TestAbstractionDetection:
    def test_three_same_scope_abstraction(self, detector):
        """3 条同 scope evidence 生成 abstraction candidate。"""
        items = [
            _e("1", "pytest unit test", tags=("testing",), scope="project"),
            _e("2", "unittest migration to pytest", tags=("testing",), scope="project"),
            _e("3", "coverage report for tests", tags=("testing",), scope="project"),
        ]
        result = detector.detect(items)
        assert len(result) == 1
        assert result[0].consolidation_type == ConsolidationType.ABSTRACTION


# ── governance 硬约束 ────────────────────────────────────────────────────────


class TestGovernanceConstraints:
    def test_all_outputs_are_semantic(self, detector):
        """所有输出 memory_type 都是 semantic。"""
        items = [
            _e("1", "pytest A", tags=("pytest",)),
            _e("2", "pytest B", tags=("pytest",)),
            _e("3", "pytest C", tags=("pytest",)),
            _e("4", "postgres A", tags=("pg",), scope="project"),
            _e("5", "postgres B", tags=("pg",), scope="project"),
            _e("6", "postgres C", tags=("pg",), scope="project"),
        ]
        result = detector.detect(items)
        assert all(c.memory_type == "semantic" for c in result)

    def test_all_outputs_are_t1(self, detector):
        """所有输出 governance_route 都是 T1。"""
        items = [
            _e("1", "a", tags=("x",)),
            _e("2", "b", tags=("x",)),
            _e("3", "c", tags=("x",)),
        ]
        result = detector.detect(items)
        assert len(result) >= 1
        assert all(c.governance_route == "T1" for c in result)

    def test_all_confidence_in_range(self, detector):
        """所有输出 confidence ∈ [0, 1]。"""
        items = [
            _e("1", "a", tags=("x",)),
            _e("2", "b", tags=("x",)),
            _e("3", "c", tags=("x",)),
        ]
        result = detector.detect(items)
        assert all(0.0 <= c.confidence <= 1.0 for c in result)


# ── procedural-like 过滤 ────────────────────────────────────────────────────


class TestProceduralFiltering:
    def test_procedural_like_evidence_excluded(self, detector):
        """procedural-like evidence 不进入 semantic candidate 生成。"""
        items = [
            _e("1", "pytest testing", tags=("pytest",)),
            _e("2", "pytest again", tags=("pytest",)),
            _e("3", "pytest once more", tags=("pytest",)),
            _e("4", "以后必须先跑测试再提交代码", tags=("pytest",)),
        ]
        result = detector.detect(items)
        # 第 4 条被过滤后，还剩 3 条（刚好 N≥3），但第 4 条不在 source_evidence 中
        assert len(result) == 1
        assert "4" not in result[0].source_evidence

    def test_all_procedural_excluded_no_candidate(self, detector):
        """如果所有 evidence 都是 procedural-like，不生成 candidate。"""
        items = [
            _e("1", "以后必须先跑测试再提交"),
            _e("2", "以后禁止跳过 lint 检查"),
            _e("3", "永远不要 auto commit"),
        ]
        result = detector.detect(items)
        # 过滤后不足 N≥3 或为空组
        assert len(result) == 0


# ── deterministic / store-free / LLM-free ────────────────────────────────────


class TestDeterministicProperties:
    def test_idempotent(self, detector):
        """相同输入多次调用输出一致。"""
        items = [
            _e("1", "pytest", tags=("pytest",)),
            _e("2", "pytest again", tags=("pytest",)),
            _e("3", "pytest once more", tags=("pytest",)),
        ]
        r1 = detector.detect(items)
        r2 = detector.detect(items)
        assert len(r1) == len(r2)
        for a, b in zip(r1, r2):
            assert a.content == b.content
            assert a.confidence == b.confidence
            assert a.consolidation_type == b.consolidation_type
            assert a.source_evidence == b.source_evidence

    def test_no_store_imports(self):
        """detector 模块不 import store 相关模块。"""
        import ast
        with open("agent/memory_consolidation_engine.py") as f:
            tree = ast.parse(f.read())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)
        forbidden = {
            "agent.memory_store", "agent.memory_fs_store",
            "agent.memory_runtime", "agent.core",
            "agent.memory_operations", "agent.memory_confirmation",
            "agent.memory_policy",
        }
        assert not (imports & forbidden), f"Forbidden imports: {imports & forbidden}"

    def test_no_llm_imports(self):
        """detector 不 import anthropic / LLM 相关。"""
        import ast
        with open("agent/memory_consolidation_engine.py") as f:
            tree = ast.parse(f.read())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)
        assert "anthropic" not in imports
        assert "openai" not in imports


# ── 多组 evidence ────────────────────────────────────────────────────────────


class TestMultipleGroups:
    def test_two_independent_groups_two_candidates(self, detector):
        """两个独立主题组各生成一个 candidate。"""
        items = [
            _e("1", "pytest A", tags=("pytest",)),
            _e("2", "pytest B", tags=("pytest",)),
            _e("3", "pytest C", tags=("pytest",)),
            _e("4", "postgres A", tags=("pg",)),
            _e("5", "postgres B", tags=("pg",)),
            _e("6", "postgres C", tags=("pg",)),
        ]
        result = detector.detect(items)
        assert len(result) == 2

    def test_overlapping_groups_merged(self, detector):
        """通过共享关键词连接的 evidence 归入同一组。"""
        items = [
            _e("1", "pytest testing", tags=("pytest", "testing")),
            _e("2", "testing CI", tags=("testing", "ci")),
            _e("3", "CI pipeline", tags=("ci", "pipeline")),
        ]
        # 1-2 共享 testing, 2-3 共享 ci → 一个连通分量
        result = detector.detect(items)
        assert len(result) == 1
        assert set(result[0].source_evidence) == {"1", "2", "3"}


# ── EpisodicEvidence 校验 ───────────────────────────────────────────────────


class TestEpisodicEvidence:
    def test_valid_construction(self):
        e = EpisodicEvidence(record_id="r1", content="test content")
        assert e.record_id == "r1"
        assert e.content == "test content"
        assert e.confidence is None

    def test_confidence_validation(self):
        with pytest.raises(ValueError, match="confidence"):
            EpisodicEvidence(record_id="r1", content="test", confidence=1.5)

    def test_empty_record_id_rejected(self):
        with pytest.raises(ValueError, match="record_id"):
            EpisodicEvidence(record_id="", content="test")

    def test_empty_content_rejected(self):
        with pytest.raises(ValueError, match="content"):
            EpisodicEvidence(record_id="r1", content="")
