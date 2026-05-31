"""Skill 候选检索器 —— 基于 trigger/alias/keyword 的确定性匹配。

Phase 2 实现（来自 002 SDD §5.1）：
- 不使用 BM25 或 embedding
- 三遍评分: trigger 精确匹配 > alias 匹配 > keyword 匹配
- negative_triggers 命中则得分归零
- 返回 top_k 候选，按 score 降序

设计原则：
- 纯函数式评分，不调用网络/LLM
- 所有输入已通过 SkillManifest 校验，不做二次校验
- 返回不可变 SkillCandidate 列表

中文匹配增强（Loop 3）：
- 中文无空格分词，传统 split() 将整句视为一个 token
- 使用字符级 bigram 重叠计算中文相似度（轻量，不依赖 jieba/BM25）
- trigger/alias 匹配对中文做子串包含检测（"写个笔记" 包含 "笔记" 等部分匹配）
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent.skill_system.descriptor import SkillManifest

# ---- 评分权重 ----

_TRIGGER_EXACT_WEIGHT = 3.0
_TRIGGER_SUBSTRING_WEIGHT = 2.5
_ALIAS_WEIGHT = 2.0
_KEYWORD_WEIGHT = 1.0

# 中文字符正则（Unicode CJK 统一表意文字区间）
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")


def _contains_chinese(text: str) -> bool:
    """检测文本是否包含中文字符。"""
    return bool(_CJK_RE.search(text))


def _chinese_bigram_overlap(user_text: str, target_text: str) -> int:
    """计算两个中文文本的字符 bigram 重叠数。

    中文无空格分词，使用 bigram 作为轻量 tokenization：
    "帮我写个笔记" → {"帮我", "我写", "写个", "个笔", "笔记"}
    "写笔记" → {"写笔", "笔记"}

    Returns:
        overlap count (bigram 交集中的元素数)
    """
    def _bigrams(s: str) -> set[str]:
        # 只从连续中文字符中提取 bigram
        chars = _CJK_RE.findall(s)
        return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}

    user_bigrams = _bigrams(user_text)
    target_bigrams = _bigrams(target_text)
    return len(user_bigrams & target_bigrams)


def _chinese_partial_match(user_lower: str, target_lower: str) -> bool:
    """中文部分匹配：检测 user 是否包含 target 的任意连续中文子串。

    中文 trigger "写笔记" 对 "帮我写个笔记" 做放宽匹配：
    将 trigger 拆为最小2字子串，检查 user 是否包含其中任一。
    "写笔记" → ["写笔", "笔记"] → user "帮我写个笔记" 包含 "笔记" ✓
    """
    chars = _CJK_RE.findall(target_lower)
    for i in range(len(chars) - 1):
        bigram = chars[i] + chars[i + 1]
        if bigram in user_lower:
            return True
    # 单字 trigger 直接检查包含
    return bool(len(chars) == 1 and chars[0] in user_lower)


@dataclass(frozen=True)
class SkillCandidate:
    """retriever 返回的候选 skill。"""

    skill_name: str
    score: float
    match_reason: str  # "trigger_exact", "alias_match", "keyword_match"
    matched_terms: tuple[str, ...]


class SkillCandidateRetriever:
    """turn-start skill 候选检索器。

    基于 aliases / trigger examples / lexical matching 做候选评分。
    不使用 BM25 或 embedding（保留为后续 enhancement）。

    Usage::

        registry = SkillRegistry(roots=[...])
        retriever = SkillCandidateRetriever()
        candidates = retriever.retrieve("写笔记", registry, top_k=5)
    """

    def retrieve(
        self,
        user_input: str,
        registry: object,
        top_k: int = 5,
    ) -> list[SkillCandidate]:
        """检索 top_k 个候选 skill。

        Args:
            user_input: 用户输入文本
            registry: SkillRegistry 实例（duck-typed，需 list_visible_manifests()）
            top_k: 返回候选数量上限

        Returns:
            按 score 降序排列的候选列表，最多 top_k 个；score ≤ 0 的候选被过滤
        """
        user_lower = user_input.lower()
        user_words = set(user_lower.split())

        manifests = registry.list_visible_manifests()  # type: ignore[union-attr]
        candidates: list[SkillCandidate] = []

        for manifest in manifests:
            m = manifest  # SkillManifest
            # 负例惩罚优先——命中 negative 则直接跳过
            if self._has_negative_match(user_lower, m):
                continue

            score = 0.0
            reason = ""
            terms: list[str] = []

            # Pass 1: trigger 匹配（权重最高）
            t_score, t_terms = self._score_by_triggers(user_lower, m)
            if t_score > 0:
                score += t_score
                reason = "trigger_exact"
                terms.extend(t_terms)

            # Pass 2: alias 匹配
            a_score, a_terms = self._score_by_aliases(user_lower, m)
            if a_score > 0:
                score += a_score
                if not reason:
                    reason = "alias_match"
                terms.extend(a_terms)

            # Pass 3: keyword 匹配（name/description/tags）
            k_score, k_terms = self._score_by_keywords(user_words, m)
            if k_score > 0:
                score += k_score
                if not reason:
                    reason = "keyword_match"
                terms.extend(k_terms)

            if score > 0:
                candidates.append(SkillCandidate(
                    skill_name=m.name,
                    score=score,
                    match_reason=reason,
                    matched_terms=tuple(terms),
                ))

        # 按 score 降序，取 top_k
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:max(0, top_k)]

    # ---- scoring passes ----

    def _score_by_triggers(
        self, user_lower: str, manifest: SkillManifest,
    ) -> tuple[float, list[str]]:
        """Pass 1: trigger 匹配——精确匹配权重 3.0，子串匹配权重 2.5。

        双向子串匹配：用户输入含 trigger 或 trigger 含用户输入均计为子串匹配。
        只取最高分的单个匹配。

        中文增强：中文 trigger 使用 bigram 部分匹配（"写笔记" 的 bigram "笔记"
        在 "帮我写个笔记" 中存在即命中子串匹配）。
        """
        best_score = 0.0
        best_term = ""
        for trigger in manifest.triggers:
            t_lower = trigger.lower()
            if t_lower == user_lower:
                return (_TRIGGER_EXACT_WEIGHT, [trigger])
            if (t_lower in user_lower or user_lower in t_lower) \
                    and best_score < _TRIGGER_SUBSTRING_WEIGHT:
                best_score = _TRIGGER_SUBSTRING_WEIGHT
                best_term = trigger
            # 中文 bigram 部分匹配 —— "写个笔记" 不完全包含 "写笔记"，
            # 但 "写个笔记" 包含 "笔记" bigram，仍应触发子串匹配
            elif _contains_chinese(t_lower) and _contains_chinese(user_lower):
                if _chinese_partial_match(user_lower, t_lower) \
                        and best_score < _TRIGGER_SUBSTRING_WEIGHT:
                    best_score = _TRIGGER_SUBSTRING_WEIGHT
                    best_term = trigger
        if best_score > 0:
            return (best_score, [best_term])
        return (0.0, [])

    def _score_by_aliases(
        self, user_lower: str, manifest: SkillManifest,
    ) -> tuple[float, list[str]]:
        """Pass 2: alias 匹配——精确命中的 alias 权重 2.0。

        多个 alias 命中可叠加（但每个 alias 只计一次）。
        """
        score = 0.0
        matched: list[str] = []
        for alias in manifest.aliases:
            a_lower = alias.lower()
            if a_lower == user_lower or a_lower in user_lower:
                score += _ALIAS_WEIGHT
                matched.append(alias)
        return (score, matched)

    def _score_by_keywords(
        self, user_words: set[str], manifest: SkillManifest,
    ) -> tuple[float, list[str]]:
        """Pass 3: name/description/tags 关键词匹配——权重 1.0。

        将 manifest 的 name、description、tags 分词后与用户输入词集取交集。

        中文增强（Loop 3）：对中文文本使用 bigram 重叠度计算关键词相关性，
        弥补空格分词对中文无效的问题。
        - bigram 重叠 >= 3 → 视为强相关 → 权重 * 3
        - bigram 重叠 >= 1 → 视为弱相关 → 权重 * 1
        """
        manifest_text = f"{manifest.name} {manifest.description} {' '.join(manifest.tags)}"
        manifest_words = set(manifest_text.lower().split())
        hits = user_words & manifest_words
        if hits:
            return (_KEYWORD_WEIGHT * len(hits), list(hits))

        # 中文 bigram 匹配（作为英文关键词匹配的补充）
        user_text = " ".join(user_words)
        if _contains_chinese(user_text):
            overlap = _chinese_bigram_overlap(user_text, manifest_text)
            if overlap >= 3:
                return (_KEYWORD_WEIGHT * 3, [f"中文 bigram 重叠({overlap})"])
            elif overlap >= 1:
                return (_KEYWORD_WEIGHT, [f"中文 bigram 重叠({overlap})"])

        return (0.0, [])

    # ---- negative penalty ----

    def _has_negative_match(
        self, user_lower: str, manifest: SkillManifest,
    ) -> bool:
        """检查 user_input 是否命中任一 negative_trigger。

        命中则返回 True，表示该 skill 应被排除。
        """
        return any(nt.lower() in user_lower for nt in manifest.negative_triggers)
