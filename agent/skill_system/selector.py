"""Skill Selector——确定性的 Skill 选择决策。

设计原则（来自 RFC Sec 5 / SDD Sec 4）：
- 基于 name / description / tags 的确定性匹配
- 只使用 Level 1 metadata（SkillDescriptor），不加载 body
- 不调用 LLM / embedding / 网络
- hidden / disabled Skill 被排除
- 多个接近匹配返回 ranked alternatives 或 ambiguity
- deprecated Skill 置信度降低
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.skill_system.registry import SkillRegistry

# ---- Scoring constants ----

_SCORE_EXACT_NAME = 1.0
_SCORE_TRIGGER = 0.4
_SCORE_NAME_WORD = 0.3
_SCORE_ALIAS_WORD = 0.3
_SCORE_TAG = 0.2
_SCORE_DESC_WORD = 0.15
_DEPRECATED_MULTIPLIER = 0.5
_CONFIDENCE_THRESHOLD = 0.25
_AMBIGUITY_GAP = 0.15


@dataclass(frozen=True)
class SkillSelectionDecision:
    """选择器输出。

    selected=False 表示没有满足阈值的 Skill，skill_name 为 None。
    alternatives 仅在接近多选时非空。
    """

    selected: bool
    skill_name: str | None
    confidence: float
    reason: str
    alternatives: tuple[str, ...] = ()
    requires_user_confirmation: bool = False


class SkillSelector:
    """确定性的 metadata-only Skill 选择器。

    Usage::

        registry = SkillRegistry(roots=[...])
        selector = SkillSelector(registry)
        decision = selector.select("git status audit")
        if decision.selected:
            print(f"Selected: {decision.skill_name}")
    """

    def __init__(self, registry: SkillRegistry):
        self._registry = registry

    def select(
        self,
        user_goal: str,
        min_confidence: float = _CONFIDENCE_THRESHOLD,
    ) -> SkillSelectionDecision:
        """根据用户目标选择最匹配的 Skill。

        只使用 registry 中的 SkillDescriptor metadata（Level 1），
        不加载 body / resource。
        """
        if not user_goal.strip():
            return SkillSelectionDecision(
                selected=False,
                skill_name=None,
                confidence=0.0,
                reason="empty query",
            )

        visible = self._registry.list_visible()
        if not visible:
            return SkillSelectionDecision(
                selected=False,
                skill_name=None,
                confidence=0.0,
                reason="no visible skills",
            )

        goal_lower = user_goal.strip().lower()
        goal_words = set(goal_lower.split())

        # ---- Pass 1: 精确名称匹配 ----
        for desc in visible:
            if desc.name == goal_lower or desc.name.lower() == goal_lower:
                return SkillSelectionDecision(
                    selected=True,
                    skill_name=desc.name,
                    confidence=1.0,
                    reason=f"exact name match: {desc.name}",
                )

        # ---- Pass 2: 关键词评分 ----
        scored: list[tuple[str, float]] = []
        for desc in visible:
            # negative_triggers 黑名单排除（Plan 3）
            if self._has_negative_trigger_match(desc, goal_lower):
                continue
            score = self._score_descriptor(desc, goal_words, goal_lower)
            if score > 0:
                # deprecated 惩罚
                if desc.status == "deprecated":
                    score *= _DEPRECATED_MULTIPLIER
                scored.append((desc.name, score))

        if not scored:
            return SkillSelectionDecision(
                selected=False,
                skill_name=None,
                confidence=0.0,
                reason="no matching skills found",
            )

        # 按分数降序排序
        scored.sort(key=lambda x: x[1], reverse=True)
        best_name, best_score = scored[0]

        # ---- Pass 3: 阈值与歧义检测 ----
        if best_score < min_confidence:
            return SkillSelectionDecision(
                selected=False,
                skill_name=None,
                confidence=best_score,
                reason=(
                    f"best match '{best_name}' score {best_score:.2f}"
                    f" below threshold {min_confidence}"
                ),
                alternatives=tuple(name for name, _ in scored[:3]),
            )

        # 检测歧义：前两名差距过小
        alternatives: tuple[str, ...] = ()
        requires_confirmation = False
        if len(scored) >= 2:
            runner_up_score = scored[1][1]
            if best_score - runner_up_score < _AMBIGUITY_GAP:
                alternatives = tuple(name for name, _ in scored[:3])
                requires_confirmation = True

        return SkillSelectionDecision(
            selected=True,
            skill_name=best_name,
            confidence=best_score,
            reason=f"keyword match: {best_name} (score: {best_score:.2f})",
            alternatives=alternatives,
            requires_user_confirmation=requires_confirmation,
        )

    def _score_descriptor(self, desc, goal_words: set[str], goal_lower: str) -> float:
        """对单个 SkillDescriptor 打分（仅使用 metadata）。

        Plan 3 增强：triggers（子串/精确高权重）、aliases（名称级权重）、
        negative_triggers（黑名单排除）。
        """
        score = 0.0

        name_lower = desc.name.lower()
        name_parts = set(name_lower.replace("-", " ").replace("_", " ").split())

        desc_lower = desc.description.lower()
        desc_words = set(desc_lower.split())

        tags_lower = {t.lower() for t in desc.tags}

        # ---- triggers: 精确/子串匹配，权重最高 ----
        for trigger in desc.triggers:
            trigger_lower = trigger.lower().strip()
            if not trigger_lower:
                continue
            if trigger_lower in goal_lower:
                score += _SCORE_TRIGGER

        # ---- aliases: 词级匹配，权重同 name ----
        for alias in desc.aliases:
            alias_lower = alias.lower()
            alias_parts = set(alias_lower.replace("-", " ").replace("_", " ").split())
            for word in goal_words:
                if word in alias_parts:
                    score += _SCORE_ALIAS_WORD

        # ---- name / description / tag 匹配（原有逻辑） ----
        for word in goal_words:
            if word in name_parts:
                score += _SCORE_NAME_WORD
            if word in desc_words:
                score += _SCORE_DESC_WORD

        for tag in tags_lower:
            if tag in goal_words:
                score += _SCORE_TAG

        return score

    def _has_negative_trigger_match(self, desc, goal_lower: str) -> bool:
        """检查用户查询是否命中 skill 的 negative_triggers（黑名单）。"""
        for nt in desc.negative_triggers:
            nt_lower = nt.lower().strip()
            if nt_lower and nt_lower in goal_lower:
                return True
        return False
