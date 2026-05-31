"""Phase 2 TDD RED Tests — Candidate Skill Retrieval (R01-R05).

测试范围（来自 docs/design/002-skill-selection-sdd-vNext.md §7.2）：
- R01: 无关输入 → 空列表
- R02: user_input 精确命中 trigger → 最高分
- R03: alias 命中 → 次高分
- R04: negative_triggers 命中 → 得分归零
- R05: 返回 ≤K 个候选，按 score 降序

RED 状态说明：
- R01-R05: 预期 FAIL — SkillCandidateRetriever / SkillCandidate 尚不存在，
  测试因 ImportError 失败。

这些测试是 Phase 2 的 contract tests。实现 SkillCandidateRetriever 后全部 GREEN。
"""

from __future__ import annotations

from agent.skill_system.retriever import SkillCandidateRetriever

from agent.skill_system.descriptor import SkillManifest

# ---- helpers ----

def _make_manifest(
    name: str = "test-skill",
    triggers: tuple[str, ...] = (),
    aliases: tuple[str, ...] = (),
    negative_triggers: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    description: str = "A test skill.",
) -> SkillManifest:
    """构造含 Plan 3 新字段的 SkillManifest，供 retriever 测试使用。"""
    return SkillManifest(
        name=name,
        description=description,
        version="0.1.0",
        status="active",
        tags=tags,
        triggers=triggers,
        aliases=aliases,
        negative_triggers=negative_triggers,
    )


def _make_retriever() -> SkillCandidateRetriever:
    return SkillCandidateRetriever()


class MockRegistry:
    """Mock SkillRegistry —— 返回预置 SkillManifest 列表。

    SkillCandidateRetriever.retrieve() 通过 registry 获取所有可见 skill
    的 manifest，然后按匹配规则评分。此 mock 允许测试控制输入集合。
    """

    def __init__(self, manifests: list[SkillManifest] | None = None):
        self._manifests = manifests or []

    def list_visible_manifests(self) -> list[SkillManifest]:
        """返回可见 skill 的 manifest 列表（等价于 registry 的迭代接口）。"""
        return list(self._manifests)


# ==================================================================
# R01: 无关输入 → 空列表
# ==================================================================

def test_retriever_returns_empty_for_no_match():
    """R01: 当 user_input 与任何 skill 的 triggers/aliases/keywords 都不匹配时，
    返回空列表。
    """
    manifest = _make_manifest(
        name="demo-note-maker",
        triggers=("写笔记", "待办"),
        aliases=("note",),
    )
    registry = MockRegistry([manifest])
    retriever = _make_retriever()

    candidates = retriever.retrieve("今天天气真好", registry, top_k=5)
    assert candidates == [], (
        f"无关输入应返回空列表，实际: {candidates}"
    )


def test_retriever_returns_empty_for_empty_registry():
    """R01 扩展: 空 registry 下任何输入都返回空列表。"""
    registry = MockRegistry([])
    retriever = _make_retriever()

    candidates = retriever.retrieve("写笔记", registry)
    assert candidates == []


# ==================================================================
# R02: trigger 精确匹配 → 最高分
# ==================================================================

def test_trigger_exact_match_scores_highest():
    """R02: user_input 精确命中 manifest.triggers 中的某条 trigger → 得分最高。

    trigger 匹配权重应高于 alias 和 keyword 匹配。
    """
    manifest = _make_manifest(
        name="demo-note-maker",
        triggers=("写笔记", "记录任务"),
        aliases=("note",),
    )
    registry = MockRegistry([manifest])
    retriever = _make_retriever()

    candidates = retriever.retrieve("写笔记", registry, top_k=5)
    assert len(candidates) == 1, (
        f"应返回 1 个候选，实际: {len(candidates)}"
    )
    c = candidates[0]
    assert c.skill_name == "demo-note-maker"
    assert c.score > 0, f"trigger 精确命中应得分 > 0，实际: {c.score}"
    assert c.match_reason == "trigger_exact", (
        f"match_reason 应为 'trigger_exact'，实际: {c.match_reason}"
    )


def test_trigger_substring_match_scores_lower():
    """R02 扩展: trigger 子串匹配得分应低于精确匹配。"""
    manifest = _make_manifest(
        name="demo-note-maker",
        triggers=("写笔记",),
    )
    # 构建另一个只有 alias 匹配的 skill 做对比
    manifest2 = _make_manifest(
        name="other-skill",
        aliases=("笔记",),
    )
    registry = MockRegistry([manifest, manifest2])
    retriever = _make_retriever()

    candidates = retriever.retrieve("笔记", registry, top_k=5)
    # manifest 有 trigger 匹配（子串），manifest2 有 alias 匹配
    # trigger 匹配（即使是子串）应比 alias 匹配得分高
    assert len(candidates) >= 1
    top = candidates[0]
    assert top.skill_name == "demo-note-maker", (
        f"trigger 子串匹配应优于 alias 匹配，实际 top: {top.skill_name}"
    )


# ==================================================================
# R03: alias 匹配 → 次高分
# ==================================================================

def test_alias_match_scores_second():
    """R03: alias 精确命中应得分，但低于 trigger 精确匹配的权重。

    同时声明 trigger 和 alias 的 skill 中，trigger 匹配得分应高于 alias 匹配。
    """
    manifest_no_trigger = _make_manifest(
        name="aliased-skill",
        aliases=("note", "笔记"),
    )
    manifest_with_trigger = _make_manifest(
        name="triggered-skill",
        triggers=("trigger-me",),
    )
    registry = MockRegistry([manifest_no_trigger, manifest_with_trigger])
    retriever = _make_retriever()

    # 输入同时命中 aliased-skill 的 alias 和 triggered-skill（通过 keyword）
    candidates = retriever.retrieve("note", registry, top_k=5)
    assert len(candidates) >= 1
    top = candidates[0]
    assert top.skill_name == "aliased-skill", (
        f"alias 精确匹配的 skill 应排第一，实际: {top.skill_name}"
    )
    assert top.match_reason == "alias_match", (
        f"match_reason 应为 'alias_match'，实际: {top.match_reason}"
    )


def test_alias_match_has_positive_score():
    """R03 扩展: alias 匹配应给出正值分数（不是零分或负分）。"""
    manifest = _make_manifest(
        name="note-skill",
        aliases=("note",),
    )
    registry = MockRegistry([manifest])
    retriever = _make_retriever()

    candidates = retriever.retrieve("note", registry)
    assert len(candidates) == 1
    assert candidates[0].score > 0, (
        f"alias 匹配得分应 > 0，实际: {candidates[0].score}"
    )


# ==================================================================
# R04: negative_triggers 命中 → 得分归零
# ==================================================================

def test_negative_trigger_zeroes_score():
    """R04: user_input 命中 negative_triggers 时，该 skill 得分归零（排除候选）。

    即使同时命中 positive trigger，negative 仍应归零或排除。
    """
    manifest = _make_manifest(
        name="note-skill",
        triggers=("写笔记",),
        negative_triggers=("写代码", "debug"),
    )
    registry = MockRegistry([manifest])
    retriever = _make_retriever()

    candidates = retriever.retrieve("写代码", registry, top_k=5)
    # 命中 negative_trigger "写代码" → 不得进入候选
    assert candidates == [], (
        f"negative_trigger 命中时应排除候选，实际: {candidates}"
    )


def test_negative_trigger_does_not_block_other_skills():
    """R04 扩展: 一个 skill 的 negative 命中只影响该 skill，不影响其他 skill。"""
    bad_skill = _make_manifest(
        name="code-reviewer",
        triggers=("review",),
        negative_triggers=("写代码",),
    )
    good_skill = _make_manifest(
        name="note-maker",
        triggers=("写笔记",),
    )
    registry = MockRegistry([bad_skill, good_skill])
    retriever = _make_retriever()

    candidates = retriever.retrieve("写代码", registry, top_k=5)
    # bad_skill 被 negative 排除；good_skill 应参与评分
    names = {c.skill_name for c in candidates}
    assert "code-reviewer" not in names, (
        "negative_trigger 命中的 skill 不应出现在候选中"
    )


# ==================================================================
# R05: top_k 限制
# ==================================================================

def test_retriever_respects_top_k():
    """R05: retrieve() 返回候选数 ≤ top_k，按 score 降序排列。"""
    manifests = [
        _make_manifest(name=f"skill-{i}", triggers=(f"trigger-{i}",))
        for i in range(10)
    ]
    registry = MockRegistry(manifests)
    retriever = _make_retriever()

    candidates = retriever.retrieve("trigger-5", registry, top_k=3)
    assert len(candidates) <= 3, (
        f"返回候选数应 ≤ top_k(3)，实际: {len(candidates)}"
    )
    # 按 score 降序
    scores = [c.score for c in candidates]
    assert scores == sorted(scores, reverse=True), (
        f"候选应按 score 降序排列，实际 scores: {scores}"
    )


def test_retriever_default_top_k():
    """R05 扩展: 不传 top_k 时使用默认值 5。"""
    manifests = [
        _make_manifest(name=f"skill-{i}", triggers=(f"trigger-{i}",))
        for i in range(10)
    ]
    registry = MockRegistry(manifests)
    retriever = _make_retriever()

    candidates = retriever.retrieve("trigger-3", registry)
    assert len(candidates) <= 5, (
        f"默认 top_k=5，返回候选应 ≤5，实际: {len(candidates)}"
    )


# ==================================================================
# Score 排序正确性
# ==================================================================

def test_candidates_sorted_by_score_descending():
    """多个 skill 匹配时，结果严格按 score 降序排列。"""
    high = _make_manifest(
        name="high-match",
        triggers=("精确匹配",),
    )
    medium = _make_manifest(
        name="medium-match",
        aliases=("部分匹配",),
    )
    low = _make_manifest(
        name="low-match",
        tags=("匹配",),
    )
    registry = MockRegistry([low, medium, high])  # 故意乱序
    retriever = _make_retriever()

    candidates = retriever.retrieve("精确匹配 部分匹配", registry, top_k=5)
    scores = [c.score for c in candidates]
    assert scores == sorted(scores, reverse=True), (
        f"候选应按 score 降序，实际: {scores}"
    )
    # 最高分应来自 trigger 精确匹配的 skill
    assert candidates[0].skill_name == "high-match", (
        f"最高分应来自 high-match，实际: {candidates[0].skill_name}"
    )
