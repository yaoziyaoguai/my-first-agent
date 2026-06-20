"""Phase 6 deterministic pattern detector 的结构性测试。

这些测试验证 RFC Phase 6 deterministic pattern detector 的结构性规则
和 governance 边界，不验证真实 semantic consolidation quality，也不读写
memory store。

测试覆盖：
- 空/不足 N≥3 evidence → 空列表
- pattern_detection / merge / abstraction 三类检测
- source_evidence 引用正确性
- governance T1 / memory_type semantic 硬约束
- confidence ∈ [0,1]（含 RFC §D.2 recency_factor）
- deterministic 幂等性
- procedural-like 过滤
- store-free / LLM-free 架构边界
- recency_factor fallenback / clamp / 确定性
"""

import pytest

from agent.memory_consolidation import (
    ConsolidationType,
    EpisodicEvidence,
)
from agent.memory_consolidation_engine import (
    DeterministicConsolidationDetector,
    _compute_confidence,
    _compute_recency_factor,
    _extract_keywords,
    _group_by_topic,
    _is_procedural_like,
    _parse_created_at,
    _token_overlap,
)

# ── helpers ──────────────────────────────────────────────────────────────────

def _evidence(record_id: str, content: str, **kwargs) -> EpisodicEvidence:
    return EpisodicEvidence(record_id=record_id, content=content, **kwargs)


def _e(
    rid: str, content: str, tags: tuple[str, ...] = (), scope: str | None = None
) -> EpisodicEvidence:
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
            _e(
                "1",
                "pytest test framework preference",
                tags=("pytest", "testing", "preference"),
            ),
            _e(
                "2",
                "preference for pytest testing framework",
                tags=("pytest", "testing", "preference"),
            ),
            _e(
                "3",
                "testing framework preference pytest",
                tags=("pytest", "testing", "preference"),
            ),
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


# ── preference_evolved ──────────────────────────────────────────────────────


class TestPreferenceEvolvedDetection:
    """这些测试验证 RFC 中 preference_evolved 的最小 deterministic foundation：
    它属于 semantic consolidation 的演化候选，不是 procedural memory，
    不允许 silent retain，也不能绕过 T1 pending review。
    """

    def test_explicit_past_now_marker_generates_preference_evolved(self, detector):
        """明确“过去 A，现在 B”的同主题 evidence 生成 preference_evolved。"""
        items = [
            _evidence(
                "old-1",
                "用户以前喜欢 unittest 作为 Python 测试框架",
                tags=("testing-preference",),
                created_at="2026-05-01T10:00:00Z",
                confidence=0.82,
            ),
            _evidence(
                "new-1",
                "用户现在更喜欢 pytest 作为 Python 测试框架",
                tags=("testing-preference",),
                created_at="2026-05-10T10:00:00Z",
                confidence=0.86,
            ),
            _evidence(
                "new-2",
                "用户说测试偏好从 unittest 变成 pytest",
                tags=("testing-preference",),
                created_at="2026-05-12T10:00:00Z",
                confidence=0.88,
            ),
        ]

        result = detector.detect(items, now=_parse_created_at("2026-05-13T10:00:00Z"))

        assert len(result) == 1
        candidate = result[0]
        assert candidate.consolidation_type == ConsolidationType.PREFERENCE_EVOLVED
        assert candidate.memory_type == "semantic"
        assert candidate.governance_route == "T1"
        assert set(candidate.source_evidence) == {"old-1", "new-1", "new-2"}
        assert 0.0 <= candidate.confidence <= 1.0
        assert "偏好" in candidate.content

    def test_unordered_contradiction_does_not_become_preference_evolved(self, detector):
        """没有时间演进 marker 的 A/B 冲突应保持 clarification_needed。"""
        items = [
            _e("pos-1", "用户喜欢 pytest 作为测试框架", tags=("testing-preference",)),
            _e("neg-1", "用户不喜欢 pytest 作为测试框架", tags=("testing-preference",)),
            _e("pos-2", "用户推荐 pytest 作为测试框架", tags=("testing-preference",)),
        ]

        result = detector.detect(items)

        assert len(result) == 1
        assert result[0].consolidation_type == ConsolidationType.CLARIFICATION_NEEDED
        assert result[0].consolidation_type != ConsolidationType.PREFERENCE_EVOLVED

    def test_procedural_like_evolution_instruction_is_filtered(self, detector):
        """procedural-like “以后必须...” 不应被 preference_evolved 变成 procedural 写入。"""
        items = [
            _e("old-1", "用户以前喜欢 unittest", tags=("testing-preference",)),
            _e("new-1", "用户现在更喜欢 pytest", tags=("testing-preference",)),
            _e("proc-1", "以后你必须使用 pytest 写所有新测试", tags=("testing-preference",)),
        ]

        result = detector.detect(items)

        assert result == []

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
        for a, b in zip(r1, r2, strict=True):
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
            elif isinstance(node, ast.ImportFrom) and node.module:
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
            elif isinstance(node, ast.ImportFrom) and node.module:
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


# ═══════════════════════════════════════════════════════════════════════════════
# RFC Appendix D.2 recency_factor 测试
# ═══════════════════════════════════════════════════════════════════════════════
# 这些测试验证 RFC Appendix D.2 recency_factor 对 Phase 6 semantic
# consolidation confidence 的确定性影响，不验证真实语义质量，也不调用 LLM。


class TestRecencyFactor:
    """验证 _compute_recency_factor 的核心行为。"""

    def test_newer_evidence_higher_recency(self):
        """较新的 evidence 产生更高的 recency_factor。"""
        recent = _evidence("r1", "a", created_at="2026-05-14T10:00:00Z")
        old = _evidence("r2", "b", created_at="2026-02-14T10:00:00Z")

        now_epoch = _parse_created_at("2026-05-14T10:00:00Z")
        recency_recent = _compute_recency_factor([recent], now_epoch)
        recency_old = _compute_recency_factor([old], now_epoch)

        assert recency_recent > recency_old

    def test_very_recent_evidence_near_one(self):
        """刚发生的事件 recency_factor 接近 1.0。"""
        e = _evidence("r1", "a", created_at="2026-05-14T09:00:00Z")
        now_epoch = _parse_created_at("2026-05-14T10:00:00Z")
        recency = _compute_recency_factor([e], now_epoch)
        # 1 小时前 → 1/24 ≈ 0.04 days → recency ≈ 0.9995+
        assert recency >= 0.99

    def test_recency_never_below_floor(self):
        """无论 evidence 多旧，recency_factor 不低于 RECENCY_FLOOR (0.5)。"""
        old = _evidence("r1", "a", created_at="2020-01-01T00:00:00Z")
        now_epoch = _parse_created_at("2026-05-14T00:00:00Z")
        recency = _compute_recency_factor([old], now_epoch)
        assert recency >= 0.5

    def test_missing_created_at_uses_neutral(self):
        """created_at 缺失时使用中性 fallback（不崩溃）。"""
        e = _evidence("r1", "a")  # 无 created_at
        now_epoch = _parse_created_at("2026-05-14T10:00:00Z")
        recency = _compute_recency_factor([e], now_epoch)
        # 中性 fallback = 0.7
        assert recency == 0.7

    def test_unparseable_created_at_uses_neutral(self):
        """created_at 格式异常时使用中性 fallback（不崩溃）。"""
        e = _evidence("r1", "a", created_at="not-a-date-at-all")
        now_epoch = _parse_created_at("2026-05-14T10:00:00Z")
        recency = _compute_recency_factor([e], now_epoch)
        # 解析失败 → fallback
        assert recency == 0.7

    def test_empty_string_created_at_uses_neutral(self):
        """created_at 为空字符串时使用中性 fallback。"""
        e = _evidence("r1", "a", created_at="")
        now_epoch = _parse_created_at("2026-05-14T10:00:00Z")
        recency = _compute_recency_factor([e], now_epoch)
        assert recency == 0.7

    def test_group_uses_newest_evidence(self):
        """group 中有多条 evidence 时，取最新的 created_at 计算 recency。"""
        old = _evidence("r1", "a", created_at="2026-01-01T00:00:00Z")
        recent = _evidence("r2", "b", created_at="2026-05-14T00:00:00Z")
        now_epoch = _parse_created_at("2026-05-14T12:00:00Z")
        # group 中有一条旧的和一条新的 → 取新的
        recency = _compute_recency_factor([old, recent], now_epoch)
        # 0.5 天前 → ≈ 0.994
        assert recency > 0.99

    def test_mixed_missing_and_present_created_at(self):
        """混有缺失和存在 created_at 的 group——使用存在的。"""
        no_date = _evidence("r1", "a")  # 缺失
        has_date = _evidence("r2", "b", created_at="2026-05-14T10:00:00Z")
        now_epoch = _parse_created_at("2026-05-14T10:00:00Z")
        recency = _compute_recency_factor([no_date, has_date], now_epoch)
        assert recency > 0.99  # 使用 has_date 的 created_at

    def test_deterministic_same_input_same_output(self):
        """相同输入和相同 now 参数多次运行结果一致。"""
        e = _evidence("r1", "a", created_at="2026-05-13T10:00:00Z")
        now_epoch = _parse_created_at("2026-05-14T10:00:00Z")
        r1 = _compute_recency_factor([e], now_epoch)
        r2 = _compute_recency_factor([e], now_epoch)
        assert r1 == r2

    def test_recency_in_range(self):
        """recency_factor 始终在 [RECENCY_FLOOR, 1.0]。"""
        cases = [
            ("2026-05-14T10:00:00Z",),  # 最近
            ("2025-05-14T10:00:00Z",),  # 1 年前
            ("2020-01-01T00:00:00Z",),  # 很久前
            (None,),  # 缺失
        ]
        now_epoch = _parse_created_at("2026-05-14T10:00:00Z")
        for (created_at,) in cases:
            e = _evidence("r1", "a", created_at=created_at)
            r = _compute_recency_factor([e], now_epoch)
            assert 0.5 <= r <= 1.0, f"recency={r} out of range for created_at={created_at}"


class TestRecencyConfidenceIntegration:
    """验证 recency_factor 在 _compute_confidence 中被正确应用。"""

    def test_newer_group_higher_confidence(self):
        """较新的 evidence group 产生更高的 candidate confidence。"""
        recent = [
            _evidence("r1", "a", created_at="2026-05-14T00:00:00Z"),
            _evidence("r2", "b", created_at="2026-05-14T00:00:00Z"),
            _evidence("r3", "c", created_at="2026-05-14T00:00:00Z"),
        ]
        old = [
            _evidence("r4", "a", created_at="2026-01-01T00:00:00Z"),
            _evidence("r5", "b", created_at="2026-01-01T00:00:00Z"),
            _evidence("r6", "c", created_at="2026-01-01T00:00:00Z"),
        ]
        now_epoch = _parse_created_at("2026-05-14T12:00:00Z")
        conf_recent = _compute_confidence(recent, consistency=1.0, now_epoch=now_epoch)
        conf_old = _compute_confidence(old, consistency=1.0, now_epoch=now_epoch)
        assert conf_recent > conf_old

    def test_confidence_clamped_zero_to_one(self):
        """confidence 始终 clamped 到 [0, 1]。"""
        # 极端情况：低 base + 低 repetition + 低 consistency + 低 recency
        items = [
            _evidence("r1", "a", confidence=0.1, created_at="2020-01-01T00:00:00Z"),
            _evidence("r2", "b", confidence=0.1, created_at="2020-01-01T00:00:00Z"),
            _evidence("r3", "c", confidence=0.1, created_at="2020-01-01T00:00:00Z"),
        ]
        now_epoch = _parse_created_at("2026-05-14T12:00:00Z")
        conf = _compute_confidence(items, consistency=0.7, now_epoch=now_epoch)
        assert 0.0 <= conf <= 1.0

    def test_deterministic_same_now_same_confidence(self):
        """相同 group + 相同 consistency + 相同 now_epoch → confidence 一致。"""
        items = [
            _evidence("r1", "a", created_at="2026-05-01T00:00:00Z"),
            _evidence("r2", "b", created_at="2026-05-01T00:00:00Z"),
            _evidence("r3", "c", created_at="2026-05-01T00:00:00Z"),
        ]
        now_epoch = _parse_created_at("2026-05-14T10:00:00Z")
        c1 = _compute_confidence(items, consistency=1.0, now_epoch=now_epoch)
        c2 = _compute_confidence(items, consistency=1.0, now_epoch=now_epoch)
        assert c1 == c2

    def test_recency_does_not_change_n3_threshold(self):
        """recency_factor 不改变 N≥3 门槛——detector 仍只对 ≥3 条 group 生成 candidate。"""
        detector = DeterministicConsolidationDetector()
        items = [
            _evidence("r1", "a", tags=("x",), created_at="2026-05-14T10:00:00Z"),
            _evidence("r2", "b", tags=("x",), created_at="2026-05-14T10:00:00Z"),
        ]
        result = detector.detect(items, now=_parse_created_at("2026-05-14T10:00:00Z"))
        assert len(result) == 0  # N=2 不满足 N≥3

    def test_recency_does_not_change_memory_type(self):
        """recency_factor 不改变 memory_type=semantic。"""
        detector = DeterministicConsolidationDetector()
        items = [
            _evidence("r1", "a", tags=("x",), created_at="2026-05-14T10:00:00Z"),
            _evidence("r2", "b", tags=("x",), created_at="2026-05-14T10:00:00Z"),
            _evidence("r3", "c", tags=("x",), created_at="2026-05-14T10:00:00Z"),
        ]
        result = detector.detect(items, now=_parse_created_at("2026-05-14T10:00:00Z"))
        assert len(result) == 1
        assert result[0].memory_type == "semantic"

    def test_recency_does_not_change_governance_route(self):
        """recency_factor 不改变 governance_route=T1。"""
        detector = DeterministicConsolidationDetector()
        items = [
            _evidence("r1", "a", tags=("x",), created_at="2026-05-14T10:00:00Z"),
            _evidence("r2", "b", tags=("x",), created_at="2026-05-14T10:00:00Z"),
            _evidence("r3", "c", tags=("x",), created_at="2026-05-14T10:00:00Z"),
        ]
        result = detector.detect(items, now=_parse_created_at("2026-05-14T10:00:00Z"))
        assert len(result) == 1
        assert result[0].governance_route == "T1"

    def test_detector_preserves_source_evidence_with_recency(self):
        """recency_factor 不影响 source_evidence 保留。"""
        detector = DeterministicConsolidationDetector()
        items = [
            _evidence("r1", "a", tags=("x",), created_at="2026-05-14T10:00:00Z"),
            _evidence("r2", "b", tags=("x",), created_at="2026-05-14T10:00:00Z"),
            _evidence("r3", "c", tags=("x",), created_at="2026-05-14T10:00:00Z"),
        ]
        result = detector.detect(items, now=_parse_created_at("2026-05-14T10:00:00Z"))
        assert len(result) == 1
        assert result[0].source_evidence == ("r1", "r2", "r3")


class TestRecencyArchitectureBoundaries:
    """验证 recency_factor 不破坏架构边界。"""

    def test_recency_no_store_write(self):
        """recency_factor 不会让 detector 写 store。"""
        # _compute_recency_factor 只返回 float，无 IO
        e = _evidence("r1", "a", created_at="2026-05-14T10:00:00Z")
        now_epoch = _parse_created_at("2026-05-14T10:00:00Z")
        result = _compute_recency_factor([e], now_epoch)
        assert isinstance(result, float)

    def test_recency_no_llm(self):
        """recency_factor 不调用 LLM。"""
        # _compute_recency_factor 是纯计算函数
        import inspect
        src = inspect.getsource(_compute_recency_factor)
        assert "anthropic" not in src.lower()
        assert "openai" not in src.lower()
        assert "llm" not in src.lower()

    def test_recency_no_env_read(self):
        """recency_factor 不读取环境变量。"""
        import inspect
        src = inspect.getsource(_compute_recency_factor)
        assert "os.environ" not in src
        assert "os.getenv" not in src
        assert "getenv" not in src

    def test_recency_no_file_io(self):
        """recency_factor 不读取文件。"""
        import inspect
        src = inspect.getsource(_compute_recency_factor)
        assert "open(" not in src
        assert "read_text" not in src
        assert "Path(" not in src

    def test_recency_no_real_sessions(self):
        """recency_factor 不读取真实 sessions/runs。"""
        import inspect
        src = inspect.getsource(_compute_recency_factor)
        assert "session" not in src.lower()
        assert "agent_log" not in src.lower()


class TestParseCreatedAt:
    """验证 _parse_created_at 的健壮性。"""

    def test_iso8601_with_z(self):
        ts = _parse_created_at("2026-05-14T10:00:00Z")
        assert ts is not None
        assert ts > 0

    def test_iso8601_without_z(self):
        ts = _parse_created_at("2026-05-14T10:00:00")
        assert ts is not None
        assert ts > 0

    def test_simple_date(self):
        ts = _parse_created_at("2026-05-14")
        assert ts is not None
        assert ts > 0

    def test_none_returns_none(self):
        assert _parse_created_at(None) is None

    def test_empty_returns_none(self):
        assert _parse_created_at("") is None

    def test_whitespace_returns_none(self):
        assert _parse_created_at("   ") is None

    def test_garbage_returns_none(self):
        assert _parse_created_at("garbage-date-string") is None


# ── 矛盾检测测试（RFC §D.3）──────────────────────────────────────────────────


class TestDetectContradiction:
    """_detect_contradiction_in_group() 的确定性测试。"""

    def test_no_contradiction_for_uniform_positive(self):
        """所有 evidence 都正面 → 无矛盾。"""
        from agent.memory_consolidation import EpisodicEvidence
        from agent.memory_consolidation_engine import _detect_contradiction_in_group

        group = [
            EpisodicEvidence("e1", "用户喜欢使用 pytest 进行测试", scope="user"),
            EpisodicEvidence("e2", "用户偏好 pytest 的 fixture 机制", scope="user"),
            EpisodicEvidence("e3", "用户推荐 pytest 给团队", scope="user"),
        ]
        assert _detect_contradiction_in_group(group) is False

    def test_no_contradiction_for_uniform_negative(self):
        """所有 evidence 都负面 → 无矛盾（一致性偏好为负面）。"""
        from agent.memory_consolidation import EpisodicEvidence
        from agent.memory_consolidation_engine import _detect_contradiction_in_group

        group = [
            EpisodicEvidence("e1", "用户不喜欢使用 unittest", scope="user"),
            EpisodicEvidence("e2", "用户拒绝 unittest 的迁移方案", scope="user"),
            EpisodicEvidence("e3", "用户讨厌 verbose 的测试写法", scope="user"),
        ]
        assert _detect_contradiction_in_group(group) is False

    def test_contradiction_like_dislike_chinese(self):
        """喜欢 vs 不喜欢 中文对立 → 矛盾。"""
        from agent.memory_consolidation import EpisodicEvidence
        from agent.memory_consolidation_engine import _detect_contradiction_in_group

        group = [
            EpisodicEvidence("e1", "用户喜欢 pytest", scope="user"),
            EpisodicEvidence("e2", "用户喜欢 pytest 的 fixture", scope="user"),
            EpisodicEvidence("e3", "用户不喜欢 pytest 的 parametrize 语法", scope="user"),
        ]
        assert _detect_contradiction_in_group(group) is True

    def test_contradiction_recommend_avoid_chinese(self):
        """推荐 vs 避免 中文对立 → 矛盾。"""
        from agent.memory_consolidation import EpisodicEvidence
        from agent.memory_consolidation_engine import _detect_contradiction_in_group

        group = [
            EpisodicEvidence("e1", "用户推荐使用 Redis 做缓存", scope="user"),
            EpisodicEvidence("e2", "用户建议避免使用 Redis", scope="user"),
        ]
        assert _detect_contradiction_in_group(group) is True

    def test_contradiction_accept_reject(self):
        """接受 vs 拒绝 同一事物 → 矛盾。"""
        from agent.memory_consolidation import EpisodicEvidence
        from agent.memory_consolidation_engine import _detect_contradiction_in_group

        group = [
            EpisodicEvidence("e1", "用户接受了全局变量的提案", scope="user"),
            EpisodicEvidence("e2", "用户拒绝了全局变量的使用方案", scope="user"),
        ]
        assert _detect_contradiction_in_group(group) is True

    def test_marker_level_catches_any_pos_neg(self):
        """标记级检测会捕获任何正负面组合（不区分主题）。

        实际使用中，_group_by_topic 会按 shared keywords/tags 分组，
        不同主题的 evidence 不会出现在同一 group 中，因此不会误报。
        这是确定性方法的已知限制。
        """
        from agent.memory_consolidation import EpisodicEvidence
        from agent.memory_consolidation_engine import _detect_contradiction_in_group

        group = [
            EpisodicEvidence("e1", "用户喜欢 pytest", scope="user"),
            EpisodicEvidence("e2", "用户不喜欢 Java", scope="user"),
        ]
        # 标记级：喜欢/不喜欢 正负面对立 → True
        # 但实际 pipeline 中这两个不会被分到同一 topic group
        assert _detect_contradiction_in_group(group) is True

    def test_contradiction_prefer_avoid_english(self):
        """prefer vs avoid 英文对立 → 矛盾。"""
        from agent.memory_consolidation import EpisodicEvidence
        from agent.memory_consolidation_engine import _detect_contradiction_in_group

        group = [
            EpisodicEvidence("e1", "user prefers pytest for testing", scope="user"),
            EpisodicEvidence("e2", "user suggests to avoid pytest", scope="user"),
        ]
        assert _detect_contradiction_in_group(group) is True

    def test_empty_group_no_contradiction(self):
        """空 group → 无矛盾。"""
        from agent.memory_consolidation_engine import _detect_contradiction_in_group

        assert _detect_contradiction_in_group([]) is False

    def test_single_evidence_no_contradiction(self):
        """单条 evidence → 无矛盾。"""
        from agent.memory_consolidation import EpisodicEvidence
        from agent.memory_consolidation_engine import _detect_contradiction_in_group

        group = [EpisodicEvidence("e1", "用户喜欢 pytest", scope="user")]
        assert _detect_contradiction_in_group(group) is False


class TestClarificationNeededCandidate:
    """矛盾 evidence → clarification_needed candidate 的 integration 测试。"""

    def test_contradictory_group_yields_clarification_needed(self):
        """包含矛盾的 group → consolidation_type=clarification_needed。"""
        from agent.memory_consolidation import (
            ConsolidationType,
            EpisodicEvidence,
        )
        from agent.memory_consolidation_engine import DeterministicConsolidationDetector

        detector = DeterministicConsolidationDetector()
        evidence = [
            EpisodicEvidence("e1", "用户喜欢 pytest", scope="user", tags=("pytest",)),
            EpisodicEvidence("e2", "用户推荐 pytest 给团队", scope="user", tags=("pytest",)),
            EpisodicEvidence("e3", "用户不喜欢 pytest 的某些特性", scope="user", tags=("pytest",)),
        ]

        candidates = detector.detect(evidence, now=1000000.0)
        assert len(candidates) == 1
        c = candidates[0]
        assert c.consolidation_type == ConsolidationType.CLARIFICATION_NEEDED

    def test_clarification_needed_has_lower_confidence(self):
        """矛盾 candidate 的 confidence 应打折（consistency=0.7）。"""
        from agent.memory_consolidation import EpisodicEvidence
        from agent.memory_consolidation_engine import DeterministicConsolidationDetector

        detector = DeterministicConsolidationDetector()

        # 一致的 evidence（无矛盾）
        uniform_ev = [
            EpisodicEvidence("e1", "用户喜欢 pytest", tags=("pytest",), confidence=0.85),
            EpisodicEvidence("e2", "用户推荐 pytest", tags=("pytest",), confidence=0.85),
            EpisodicEvidence("e3", "用户偏好 pytest", tags=("pytest",), confidence=0.85),
        ]
        uniform_cands = detector.detect(uniform_ev, now=0.0)

        # 矛盾的 evidence
        conflict_ev = [
            EpisodicEvidence("e1", "用户喜欢 pytest", tags=("pytest",), confidence=0.85),
            EpisodicEvidence("e2", "用户推荐 pytest", tags=("pytest",), confidence=0.85),
            EpisodicEvidence("e3", "用户不喜欢 pytest", tags=("pytest",), confidence=0.85),
        ]
        conflict_cands = detector.detect(conflict_ev, now=0.0)

        assert len(uniform_cands) == 1
        assert len(conflict_cands) == 1
        # 矛盾的 confidence 应该更低（consistency 折扣 0.7）
        assert conflict_cands[0].confidence < uniform_cands[0].confidence

    def test_clarification_needed_still_t1(self):
        """矛盾 candidate 仍必须是 T1 governance。"""
        from agent.memory_consolidation import (
            EpisodicEvidence,
        )
        from agent.memory_consolidation_engine import DeterministicConsolidationDetector

        detector = DeterministicConsolidationDetector()
        evidence = [
            EpisodicEvidence("e1", "用户喜欢 pytest", tags=("pytest",)),
            EpisodicEvidence("e2", "用户推荐 pytest", tags=("pytest",)),
            EpisodicEvidence("e3", "用户不喜欢 pytest", tags=("pytest",)),
        ]

        candidates = detector.detect(evidence, now=1000000.0)
        assert len(candidates) == 1
        c = candidates[0]
        assert c.governance_route == "T1"

    def test_clarification_needed_still_semantic(self):
        """矛盾 candidate 仍必须是 semantic memory_type。"""
        from agent.memory_consolidation import EpisodicEvidence
        from agent.memory_consolidation_engine import DeterministicConsolidationDetector

        detector = DeterministicConsolidationDetector()
        evidence = [
            EpisodicEvidence("e1", "用户喜欢 pytest", tags=("pytest",)),
            EpisodicEvidence("e2", "用户推荐 pytest", tags=("pytest",)),
            EpisodicEvidence("e3", "用户不喜欢 pytest", tags=("pytest",)),
        ]

        candidates = detector.detect(evidence, now=1000000.0)
        assert len(candidates) == 1
        c = candidates[0]
        assert c.memory_type == "semantic"

    def test_clarification_needed_preserves_source_evidence(self):
        """矛盾 candidate 保留所有 source_evidence。"""
        from agent.memory_consolidation import EpisodicEvidence
        from agent.memory_consolidation_engine import DeterministicConsolidationDetector

        detector = DeterministicConsolidationDetector()
        evidence = [
            EpisodicEvidence("e1", "用户喜欢 pytest", tags=("pytest",)),
            EpisodicEvidence("e2", "用户推荐 pytest", tags=("pytest",)),
            EpisodicEvidence("e3", "用户讨厌 pytest", tags=("pytest",)),
        ]

        candidates = detector.detect(evidence, now=1000000.0)
        assert len(candidates) == 1
        c = candidates[0]
        assert len(c.source_evidence) == 3

    def test_clarification_needed_never_auto_approve(self):
        """矛盾 candidate 的 approval_status 不得为 approved。"""
        from agent.memory_consolidation import EpisodicEvidence
        from agent.memory_consolidation_engine import DeterministicConsolidationDetector

        detector = DeterministicConsolidationDetector()
        evidence = [
            EpisodicEvidence("e1", "用户喜欢 pytest", tags=("pytest",)),
            EpisodicEvidence("e2", "用户推荐 pytest", tags=("pytest",)),
            EpisodicEvidence("e3", "用户不喜欢 pytest", tags=("pytest",)),
        ]

        candidates = detector.detect(evidence, now=1000000.0)
        assert len(candidates) == 1
        c = candidates[0]
        # ConsolidationCandidate 本身没有 approval_status，由 dispatch 层设置
        # 这里验证不会在 detector 层被 approve
        assert c.governance_route == "T1"

    def test_contradiction_does_not_break_n3_threshold(self):
        """矛盾 detection 不影响 N≥3 门槛。"""
        from agent.memory_consolidation import EpisodicEvidence
        from agent.memory_consolidation_engine import DeterministicConsolidationDetector

        detector = DeterministicConsolidationDetector()
        # 只有 2 条（即使有矛盾）→ 不应生成 candidate
        evidence = [
            EpisodicEvidence("e1", "用户喜欢 pytest", tags=("pytest",)),
            EpisodicEvidence("e2", "用户不喜欢 pytest", tags=("pytest",)),
        ]

        candidates = detector.detect(evidence, now=1000000.0)
        assert len(candidates) == 0

    def test_contradiction_content_includes_clarification_marker(self):
        """矛盾 candidate 的 content 应提及需要澄清。"""
        from agent.memory_consolidation import EpisodicEvidence
        from agent.memory_consolidation_engine import DeterministicConsolidationDetector

        detector = DeterministicConsolidationDetector()
        evidence = [
            EpisodicEvidence("e1", "用户喜欢 pytest", tags=("pytest",)),
            EpisodicEvidence("e2", "用户推荐 pytest", tags=("pytest",)),
            EpisodicEvidence("e3", "用户不喜欢 pytest", tags=("pytest",)),
        ]

        candidates = detector.detect(evidence, now=1000000.0)
        assert len(candidates) == 1
        assert "矛盾" in candidates[0].content
        assert "澄清" in candidates[0].content
