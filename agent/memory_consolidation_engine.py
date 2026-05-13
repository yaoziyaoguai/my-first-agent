"""Phase 6 — Deterministic Consolidation Engine.

实现 episodic → semantic 沉淀的确定性模式检测器。
基于简单关键词分组 + token overlap 相似度，不调 LLM、不做 embedding。

RFC 参考：
- §6.3: consolidation operation types (pattern_detection, merge, abstraction)
- §D.1: 沉淀必要条件 (repetition N≥3, stability, evidence chain, confidence accumulation)
- §D.2: 置信度累积模型
- §6.4: governance — candidate generation silent, candidate adoption T1
- §10.4: W4 Consolidation 行 → Semantic T1 only

架构边界：
- 输入: list[EpisodicEvidence]（纯数据，不依赖 store）
- 输出: list[ConsolidationCandidate]（数据契约，不写 store）
- 不 import store / runtime / confirmation / policy 模块
- 不调用 LLM
- 不做 embedding / vector similarity
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from agent.memory_consolidation import (
    ConsolidationCandidate,
    ConsolidationType,
    EpisodicEvidence,
)

# ── 停用词 ─────────────────────────────────────────────────────────────────

_STOPWORDS: frozenset[str] = frozenset({
    # English
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "in", "on", "at", "to", "for", "of", "and", "or", "not",
    "it", "this", "that", "with", "from", "by", "as", "but",
    "we", "you", "he", "she", "they", "i", "me", "my", "our",
    "has", "have", "had", "do", "does", "did", "will", "would",
    "can", "could", "should", "may", "might", "just", "very",
    # 中文
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都",
    "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你",
    "会", "着", "没有", "看", "好", "自己", "这", "那", "他", "她",
    "它", "们", "什么", "怎么", "为什么", "因为", "所以", "但是",
    "如果", "可以", "需要", "应该", "能够", "已经", "还是", "或者",
    "这个", "那个", "哪个", "一些", "一下", "一点", "一种", "知道",
})

# procedural-like 关键词：如果 evidence 内容匹配这些模式，说明可能是行为约束
# 而非语义偏好，不应直接生成 semantic candidate（RFC §D.4: 不生成 procedural）
_PROCEDURAL_LIKE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"以后.{0,10}(必须|禁止|不要|不能|不应该|永远|绝对)"),
    re.compile(r"(记住|牢记|别忘了).{0,10}(必须|禁止|不要|永远)"),
    re.compile(r"(以后|下次|从现在开始).{0,15}(先|再|不要|别)"),
    re.compile(r"(永远|千万|绝对).{0,5}(不要|禁止|不能|别)"),
    re.compile(r"(never|always|must|must\s*not|don't|do\s*not)\s+\w+"),
)

# ── 关键词提取 ─────────────────────────────────────────────────────────────


def _extract_keywords(text: str) -> frozenset[str]:
    """从文本中提取关键词（中英文混合）。

    算法：正则分词 → 去停用词 → 保留 2 字以上 token。
    不做 embedding，不做 NLP parsing。
    """
    # 中文词：连续中文字符 ≥2
    chinese = re.findall(r"[一-鿿]{2,}", text)
    # 英文词：连续字母 ≥2
    english = re.findall(r"[a-zA-Z]{2,}", text.lower())
    tokens = set(chinese) | set(english)
    return frozenset(t for t in tokens if t not in _STOPWORDS)


def _token_overlap(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard 相似度。空集对空集返回 0.0。"""
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── procedural-like 检测 ──────────────────────────────────────────────────


def _is_procedural_like(content: str) -> bool:
    """检测内容是否包含 procedural-like 语言模式。

    如果匹配，不应生成 semantic candidate（RFC §D.4）。
    """
    return any(p.search(content) for p in _PROCEDURAL_LIKE_PATTERNS)


# ── 分组逻辑 ───────────────────────────────────────────────────────────────


def _build_topic_signature(evidence: EpisodicEvidence) -> frozenset[str]:
    """构建 evidence 的主题签名。

    优先使用显式 tags（可测试性），否则从 content 提取关键词。
    """
    if evidence.tags:
        return frozenset(evidence.tags)
    return _extract_keywords(evidence.content)


def _group_by_topic(
    evidence_list: list[EpisodicEvidence],
) -> list[list[EpisodicEvidence]]:
    """按共享关键词将 evidence 分组。

    两组 evidence 如果关键词集有交集，则归入同一组
    （连通分量算法 —— 简单 union-find）。
    """
    n = len(evidence_list)
    if n == 0:
        return []

    signatures = [_build_topic_signature(e) for e in evidence_list]
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i in range(n):
        for j in range(i + 1, n):
            if signatures[i] & signatures[j]:
                union(i, j)

    groups: dict[int, list[EpisodicEvidence]] = {}
    for i, evidence in enumerate(evidence_list):
        root = find(i)
        groups.setdefault(root, []).append(evidence)

    return list(groups.values())


# ── 置信度计算 ────────────────────────────────────────────────────────────


def _compute_confidence(
    group: list[EpisodicEvidence],
    consistency: float,
) -> float:
    """RFC §D.2 置信度累积的确定性实现。

    公式：
      base = mean(evidence confidence)，默认 0.7
      repetition_factor = min(1.0, N/5)
      consistency_factor = 1.0（一致）或 0.7（有矛盾）
      confidence = min(0.95, base × repetition × consistency)

    结果四舍五入到 2 位小数。
    """
    confidences = [e.confidence for e in group if e.confidence is not None]
    base = sum(confidences) / len(confidences) if confidences else 0.7

    n = len(group)
    repetition = min(1.0, n / 5.0)

    confidence = base * repetition * consistency
    return round(min(0.95, max(0.0, confidence)), 2)


# ── 内容生成 ──────────────────────────────────────────────────────────────


def _generate_content(
    group: list[EpisodicEvidence],
    ctype: ConsolidationType,
) -> str:
    """为 candidate 生成模板化 content 语句。

    这是一个确定性占位实现，不伪装成真实 LLM consolidation quality。
    """
    keywords = set()
    for e in group:
        keywords |= set(_extract_keywords(e.content))
    topic_str = "、".join(sorted(keywords)[:5]) if keywords else "未知主题"

    if ctype == ConsolidationType.MERGE:
        return f"多条事件记录反复涉及相同模式：{topic_str}。"
    elif ctype == ConsolidationType.ABSTRACTION:
        scope = group[0].scope or "未知范围"
        return f"在 {scope} 范围内，多个事件指向共同知识：{topic_str}。"
    else:
        return f"用户在多个事件中反复表现出对 {topic_str} 的稳定偏好。"


# ═══════════════════════════════════════════════════════════════════════════════
# DeterministicConsolidationDetector
# ═══════════════════════════════════════════════════════════════════════════════


class DeterministicConsolidationDetector:
    """确定性 consolidation 模式检测器。

    输入: list[EpisodicEvidence] — 跨 session 的 episodic 视图
    输出: list[ConsolidationCandidate] — 待 T1 review 的 semantic candidate

    RFC §D.1 强制 N≥3 门槛：
    - < 3 条相关 evidence → 不生成 candidate
    - ≥ 3 条 → 可生成 pattern_detection / merge / abstraction candidate

    不读 store、不写 store、不调 LLM、不做 embedding。
    """

    # ── 阈值常量 ──────────────────────────────────────────────────────

    MIN_EVIDENCE = 3  # RFC §D.1: N ≥ 3
    MERGE_JACCARD_THRESHOLD = 0.6  # merge 判定：成对相似度 > 此值
    CONSISTENCY_DEFAULT = 1.0  # 默认一致性（无矛盾）
    CONSISTENCY_CONFLICT = 0.7  # 有矛盾时的一致性折扣

    # ── 公开 API ──────────────────────────────────────────────────────

    def detect(
        self,
        evidence_list: list[EpisodicEvidence],
    ) -> list[ConsolidationCandidate]:
        """对 evidence 列表执行确定性 pattern detection。

        Returns:
            list[ConsolidationCandidate] — 可能为空。
            所有 candidate 均满足:
            - memory_type="semantic"
            - governance_route="T1"
            - source_evidence 引用 ≥MIN_EVIDENCE 条输入 record_id
            - confidence ∈ [0.0, 1.0]
        """
        if not evidence_list:
            return []

        # Step 1: 过滤 procedural-like evidence（RFC §D.4）
        clean = [e for e in evidence_list if not _is_procedural_like(e.content)]

        # Step 2: 按主题分组
        groups = _group_by_topic(clean)

        # Step 3: 每组 ≥ MIN_EVIDENCE → 生成 candidate
        candidates: list[ConsolidationCandidate] = []
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        for group in groups:
            if len(group) < self.MIN_EVIDENCE:
                continue

            ctype = self._classify_group(group)
            consistency = self._compute_consistency(group)
            confidence = _compute_confidence(group, consistency)
            content = _generate_content(group, ctype)
            record_ids = tuple(e.record_id for e in group)
            evidence_summary = (
                f"{len(group)} 条 episodic evidence 共享主题，"
                f"consistency={consistency:.1f}，"
                f"record_ids={list(record_ids)}"
            )

            candidates.append(ConsolidationCandidate(
                content=content,
                memory_type="semantic",
                source_evidence=record_ids,
                consolidation_type=ctype,
                confidence=confidence,
                governance_route="T1",
                evidence_summary=evidence_summary,
                created_at=now,
            ))

        return candidates

    # ── 内部分类逻辑 ──────────────────────────────────────────────────

    def _classify_group(
        self,
        group: list[EpisodicEvidence],
    ) -> ConsolidationType:
        """判定 group 的 consolidation_type。

        规则优先级:
        1. 所有成对 content 关键词 Jaccard > MERGE_JACCARD_THRESHOLD → merge
           (使用 content 关键词而非 tags，避免 tags 分组导致过拟合)
        2. 所有 evidence scope 相同 → abstraction
        3. 默认 → pattern_detection
        """
        # merge: 基于 content 关键词的成对相似度（不是 tags）
        # tags 用于分组，content 关键词用于合并判定
        content_sigs = [_extract_keywords(e.content) for e in group]

        all_high_similarity = True
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if _token_overlap(content_sigs[i], content_sigs[j]) < self.MERGE_JACCARD_THRESHOLD:
                    all_high_similarity = False
                    break
            if not all_high_similarity:
                break

        if all_high_similarity:
            return ConsolidationType.MERGE

        # abstraction check: 所有 evidence 有相同的非 None scope
        scopes = {e.scope for e in group}
        if len(scopes) == 1 and None not in scopes:
            return ConsolidationType.ABSTRACTION

        return ConsolidationType.PATTERN_DETECTION

    def _compute_consistency(
        self,
        group: list[EpisodicEvidence],
    ) -> float:
        """计算 group 内 evidence 的一致性。

        当前简化实现：检查是否存在显著的 token overlap 差异。
        如果 group 内所有 evidence 两两之间至少有一点 overlap，
        则认为一致（1.0）；否则有矛盾（0.7）。

        不做完整 contradiction resolution（RFC §D.3）。
        """
        signatures = [_build_topic_signature(e) for e in group]
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if not (signatures[i] & signatures[j]):
                    return self.CONSISTENCY_CONFLICT
        return self.CONSISTENCY_DEFAULT
