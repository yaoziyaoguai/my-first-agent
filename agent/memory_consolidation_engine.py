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
    "用户", "使用", "进行", "通过",
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

# preference_evolved 是 RFC §D.3 的“时间演进型变化”，仍属于
# semantic consolidation。这里故意只支持显式 marker，不做隐式 NLP 推断：
# 没有时间演进 marker 的 A/B 冲突继续走 clarification_needed，由 T1 review 裁决。
_PREFERENCE_EVOLUTION_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"(以前|之前|过去|原来|曾经).{0,40}(现在|如今|后来|改成|改为|变成|更喜欢|更倾向|转向)"),
    re.compile(r"(偏好|喜好).{0,20}从.{1,40}(变成|改成|改为|转向).{1,40}"),
    re.compile(r"(used to prefer|previously preferred).{0,80}(now prefer|now prefers|now use|now uses)", re.IGNORECASE),
    re.compile(r"changed\s+(my\s+|the\s+)?preference\s+from\s+.{1,40}\s+to\s+.{1,40}", re.IGNORECASE),
    re.compile(r"no longer\s+.{1,40},?\s+now\s+.{1,40}", re.IGNORECASE),
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


def _has_preference_evolution_marker(content: str) -> bool:
    """检测显式偏好演进 marker。

    这是 semantic consolidation 的最小确定性 foundation：只有用户文本明确表达
    “过去/现在”或 “from/to” 的时间演进，才进入 preference_evolved。
    """
    return any(p.search(content) for p in _PREFERENCE_EVOLUTION_PATTERNS)


def _has_chronological_order(group: list[EpisodicEvidence]) -> bool:
    """确认 evidence 至少有两个不同时间点。

    preference_evolved 与普通 contradiction 的核心区别是时间顺序。没有可验证
    created_at 时，detector fail-closed，不把冲突升级成演进结论。
    """
    timestamps = {
        ts
        for evidence in group
        if (ts := _parse_created_at(evidence.created_at)) is not None
    }
    return len(timestamps) >= 2 and min(timestamps) < max(timestamps)


def _detect_preference_evolution_in_group(group: list[EpisodicEvidence]) -> bool:
    """检测 group 是否表达了明确的偏好演进。

    只看显式 marker + created_at 顺序，不生成 procedural，不写 store。
    """
    return _has_chronological_order(group) and any(
        _has_preference_evolution_marker(evidence.content)
        for evidence in group
    )


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

# recency_factor 的衰减常量
# DECAY_DAYS 天前的 evidence 达到 floor（MIN_RECENCY）
# MIN_RECENCY 是 recency 的地板——即使非常旧的 evidence 也不会归零
_RECENCY_DECAY_DAYS: float = 90.0
_RECENCY_FLOOR: float = 0.5
# 缺失 created_at 时的中性 fallback（floor~1.0 中点）
_RECENCY_NEUTRAL: float = 0.7


def _parse_created_at(created_at: str | None) -> float | None:
    """解析 created_at 字符串为 UTC epoch 秒浮点数。

    支持 ISO8601 格式（含 'T' 和可能的 'Z' 结尾）。
    解析失败返回 None。
    """
    if not created_at or not created_at.strip():
        return None
    try:
        from datetime import datetime, timezone

        ts = created_at.strip()
        # ISO8601: 2026-05-13T10:00:00Z 或 2026-05-13T10:00:00
        if "T" in ts:
            ts = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
        else:
            # 简单日期: 2026-05-13
            dt = datetime.strptime(ts[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _compute_recency_factor(
    group: list[EpisodicEvidence],
    now_epoch: float,
) -> float:
    """计算 group 的 recency_factor（RFC §D.2）。

    算法：
    1. 取 group 中最新的 evidence 的 created_at
    2. 计算 age_days = (now - newest_epoch) / 86400
    3. recency_factor = max(RECENCY_FLOOR, 1.0 - age_days / DECAY_DAYS)
    4. 如果所有 evidence 都缺失 created_at → 使用中性 fallback

    recency_factor 是 RFC §D.2 的确定性 confidence 因子，
    用于影响 semantic consolidation 候选的可信度；
    它不是记忆遗忘策略，也不改变 governance 路由。
    """
    newest_epoch: float | None = None
    for e in group:
        ts = _parse_created_at(e.created_at)
        if ts is not None:
            if newest_epoch is None or ts > newest_epoch:
                newest_epoch = ts

    if newest_epoch is None:
        return _RECENCY_NEUTRAL

    age_days = max(0.0, (now_epoch - newest_epoch) / 86400.0)
    recency = 1.0 - (age_days / _RECENCY_DECAY_DAYS)
    return max(_RECENCY_FLOOR, recency)


def compute_recency_factor(
    group: list[EpisodicEvidence],
    *,
    now_epoch: float | None = None,
) -> float:
    """公开的最小 aging signal helper。

    recency_factor 只参与 consolidation candidate confidence scoring；
    它不修改已持久化 memory、不触发 auto approve，也不是后台 decay engine。
    暴露这个薄 helper 是为了 dogfood / audit 能直接验证 RFC §D.2 的 aging
    边界，而不是复制私有公式。
    """

    if now_epoch is None:
        now_epoch = datetime.now(timezone.utc).timestamp()
    return _compute_recency_factor(group, now_epoch)


def _compute_confidence(
    group: list[EpisodicEvidence],
    consistency: float,
    *,
    now_epoch: float | None = None,
) -> float:
    """RFC §D.2 置信度累积的确定性实现。

    公式：
      base = mean(evidence confidence)，默认 0.7
      repetition_factor = min(1.0, N/5)
      consistency_factor = 1.0（一致）或 0.7（有矛盾）
      recency_factor = max(RECENCY_FLOOR, 1.0 - age_days / DECAY_DAYS)
      confidence = min(0.95, base × repetition × consistency × recency)

    now_epoch 为可选时间参考点（用于测试注入）。
    None 时使用当前 UTC epoch。

    结果四舍五入到 2 位小数。
    """
    confidences = [e.confidence for e in group if e.confidence is not None]
    base = sum(confidences) / len(confidences) if confidences else 0.7

    n = len(group)
    repetition = min(1.0, n / 5.0)

    # recency_factor — 时间注入点（关键：now_epoch 用于测试确定性）
    if now_epoch is None:
        from datetime import datetime, timezone
        now_epoch = datetime.now(timezone.utc).timestamp()
    recency = _compute_recency_factor(group, now_epoch)

    confidence = base * repetition * consistency * recency
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

    if ctype == ConsolidationType.CLARIFICATION_NEEDED:
        return (
            f"在主题 '{topic_str}' 上观察到矛盾信号：部分 evidence 持正面/采用态度，"
            f"部分 evidence 持负面/拒绝态度。需要人工澄清实际偏好。"
        )
    elif ctype == ConsolidationType.PREFERENCE_EVOLVED:
        return (
            f"用户偏好在主题 '{topic_str}' 上呈现时间演进：旧 evidence 与新 evidence "
            "显示偏好已发生变化，需要经 T1 review 确认最新语义记忆。"
        )
    elif ctype == ConsolidationType.MERGE:
        return f"多条事件记录反复涉及相同模式：{topic_str}。"
    elif ctype == ConsolidationType.ABSTRACTION:
        scope = group[0].scope or "未知范围"
        return f"在 {scope} 范围内，多个事件指向共同知识：{topic_str}。"
    else:
        return f"用户在多个事件中反复表现出对 {topic_str} 的稳定偏好。"


# ── 矛盾检测（RFC §D.3）────────────────────────────────────────────────────


# 对立标记对：出现在同一 group 的 evidence 中 → 矛盾
# 格式：(positive, negative)
# 注意：必须按 neg 长度降序检查，避免 "不喜欢" 中的 "喜欢" 被误判为正面
_OPPOSING_MARKER_PAIRS: tuple[tuple[str, str], ...] = (
    # 中文对立对
    ("喜欢", "不喜欢"),
    ("喜欢", "讨厌"),
    ("推荐", "不推荐"),
    ("推荐", "不建议"),
    ("推荐", "避免"),
    ("偏好", "避免"),
    ("选择", "拒绝"),
    ("采纳", "拒绝"),
    ("接受", "拒绝"),
    ("赞成", "反对"),
    ("适合", "不适合"),
    ("肯定", "否定"),
    # 英文对立对
    ("prefer", "dislike"),
    ("prefer", "avoid"),
    ("like", "dislike"),
    ("like", "hate"),
    ("favorite", "hate"),
    ("recommend", "avoid"),
    ("recommend", "not recommend"),
    ("agree", "disagree"),
)


def _detect_contradiction_in_group(group: list[EpisodicEvidence]) -> bool:
    """检测 group 内 evidence 之间是否存在对立标记。

    算法：
    1. 对每对对立标记 (pos, neg)，逐条 evidence 检查极性
    2. 若 content 包含 neg → 该条记为负面
    3. 否则若 content 包含 pos 且不包含任何已知否定标记 → 该条记为正面
       （避免 "不喜欢" 中的 "喜欢" 被误判为正面）
    4. 若 group 中既有正面又有负面 → 矛盾

    限制：基于关键词匹配，无法检测含蓄/间接矛盾。由 T1 human review 兜底。

    RFC §D.3：真实矛盾 → 降低 confidence，标记 needs clarification。
    """
    all_neg_markers = {neg for _, neg in _OPPOSING_MARKER_PAIRS}

    for pos, neg in _OPPOSING_MARKER_PAIRS:
        any_pos = False
        any_neg = False
        for e in group:
            c = e.content
            if neg in c:
                any_neg = True
            elif pos in c:
                # 只有不包含任何否定标记时才算正面
                # 避免 "不喜欢" 中的 "喜欢" 被误判
                if not any(n in c for n in all_neg_markers):
                    any_pos = True
        if any_pos and any_neg:
            return True
    return False


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
        *,
        now: float | None = None,
    ) -> list[ConsolidationCandidate]:
        """对 evidence 列表执行确定性 pattern detection。

        Args:
            evidence_list: EpisodicEvidence 列表。
            now: 可选 UTC epoch 秒浮点数，作为 recency 计算的时间参考点。
                 None 时使用当前 UTC 时间。测试注入此参数以保证确定性。

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
        created_at_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        for group in groups:
            if len(group) < self.MIN_EVIDENCE:
                continue

            ctype = self._classify_group(group)
            consistency = self._compute_consistency(group)
            confidence = _compute_confidence(group, consistency, now_epoch=now)
            content = _generate_content(group, ctype)
            record_ids = tuple(e.record_id for e in group)

            if ctype == ConsolidationType.CLARIFICATION_NEEDED:
                evidence_summary = (
                    f"{len(group)} 条 episodic evidence 包含矛盾信号，"
                    f"consistency={consistency:.1f}（已折扣），"
                    f"record_ids={list(record_ids)}，需人工澄清"
                )
            else:
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
                created_at=created_at_str,
            ))

        return candidates

    # ── 内部分类逻辑 ──────────────────────────────────────────────────

    def _classify_group(
        self,
        group: list[EpisodicEvidence],
    ) -> ConsolidationType:
        """判定 group 的 consolidation_type。

        规则优先级:
        1. 存在明确时间演进 marker → preference_evolved（RFC §D.3）
        2. 存在矛盾 → clarification_needed（RFC §D.3）
        3. 所有成对 content 关键词 Jaccard > MERGE_JACCARD_THRESHOLD → merge
        4. 所有 evidence scope 相同 → abstraction
        5. 默认 → pattern_detection
        """
        # preference_evolved 必须先于 contradiction 检查。显式“过去 A，现在 B”
        # 是时间演进，不是同时冲突；仍输出 semantic/T1 candidate。
        if _detect_preference_evolution_in_group(group):
            return ConsolidationType.PREFERENCE_EVOLVED

        # contradiction check: 无时间演进 marker 的冲突走澄清路径
        if _detect_contradiction_in_group(group):
            return ConsolidationType.CLARIFICATION_NEEDED

        # merge: 基于 content 关键词的成对相似度（不是 tags）
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

        分两层：
        1. 主题层：检查是否存在显著的 token overlap 差异
        2. 语义层：检查是否存在对立标记（likes/dislikes）

        如果 group 内所有 evidence 两两之间至少有一点 overlap 且无对立标记，
        则认为一致（1.0）；否则有矛盾（0.7）。

        RFC §D.3：矛盾 → 降低 confidence。
        """
        # 层 1: token overlap
        signatures = [_build_topic_signature(e) for e in group]
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if not (signatures[i] & signatures[j]):
                    return self.CONSISTENCY_CONFLICT

        # 层 2: 对立标记检测（RFC §D.3 矛盾处理）
        if _detect_contradiction_in_group(group):
            return self.CONSISTENCY_CONFLICT

        return self.CONSISTENCY_DEFAULT

    def _check_contradiction(
        self,
        group: list[EpisodicEvidence],
    ) -> bool:
        """检查 group 内是否包含矛盾 evidence（供 classify 使用）。

        委托给 _detect_contradiction_in_group()。
        """
        return _detect_contradiction_in_group(group)
