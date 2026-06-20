"""Phase 6 — Consolidation Domain Model.

定义 episodic → semantic 沉淀过程的数据契约层。
ConsolidationCandidate 是 consolidation engine 的输出候选，
经 T1 human review 后进入 semantic memory。

本模块不包含：
- consolidation engine / pattern detection 逻辑
- runtime integration / session hook
- store 写入
- 真实 LLM 调用

⛔ FROZEN (2026-05-25): Memory Consolidation pipeline 整体冻结。
   - dispatch path / handler path 已验证（通过 L3 tests）
   - business operation / real LLM consolidation DEFERRED
   - 不允许继续增强，除非另开 Architecture Decision
   - 该冻结标签覆盖全部 6 个 consolidation 模块
   参见: docs/audit/global-agent-capability-architecture-audit-2026-05-25.md F4
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agent.memory_extraction import MemoryCandidateProposal, SuggestedAction

# ── Detector Input Contract ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class EpisodicEvidence:
    """Phase 6 deterministic detector 的纯输入视图。

    用于避免 consolidation 逻辑过早耦合 filesystem store。
    后续 source evidence loader 可以把 MemoryRecord 转成 EpisodicEvidence，
    但本轮不做 loader —— detector 只消费此轻量 contract。

    domain model 层允许 source_evidence≥2 是底层 contract；
    detector 层按 RFC §D.1 使用 N≥3 作为 semantic consolidation 门槛。
    """

    record_id: str
    content: str
    scope: str | None = None
    created_at: str | None = None
    confidence: float | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.record_id.strip():
            raise ValueError("EpisodicEvidence.record_id 不能为空")
        if not self.content.strip():
            raise ValueError("EpisodicEvidence.content 不能为空")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError("EpisodicEvidence.confidence 必须在 0.0-1.0 之间")


# ── Consolidation Type ──────────────────────────────────────────────────────


class ConsolidationType(StrEnum):
    """Consolidation 操作类型（RFC §6.3, Appendix D.3）。

    pattern_detection: 多条 episodic 揭示同一偏好/事实
    merge: 合并高度相似的 episodic
    abstraction: 提取跨事件的一般性知识
    clarification_needed: 存在矛盾，需用户裁决（RFC §D.3）
    preference_evolved: 时间演进型变化（RFC §D.3）
    """

    PATTERN_DETECTION = "pattern_detection"
    MERGE = "merge"
    ABSTRACTION = "abstraction"
    CLARIFICATION_NEEDED = "clarification_needed"
    PREFERENCE_EVOLVED = "preference_evolved"


@dataclass(frozen=True, slots=True)
class ConsolidationCandidate:
    """一条从多条 episodic 沉淀出的 semantic candidate。

    Consolidation 输出必须始终走 T1 human review（RFC §6.4）。
    不自动 adopt，不自动删除源 episodic。
    """

    content: str
    memory_type: str  # 必须为 "semantic"
    source_evidence: tuple[str, ...]  # 支撑它的 episodic record ID 列表
    consolidation_type: ConsolidationType
    confidence: float  # 0.0-1.0
    governance_route: str  # 必须为 "T1"
    evidence_summary: str
    created_at: str

    def __post_init__(self) -> None:
        # content 非空
        if not self.content.strip():
            raise ValueError("ConsolidationCandidate.content 不能为空")

        # memory_type 必须为 semantic（RFC §6.1：consolidation 只产出 semantic）
        if self.memory_type != "semantic":
            raise ValueError(
                f"ConsolidationCandidate.memory_type 必须为 'semantic'，"
                f"不允许 '{self.memory_type}'"
            )

        # source_evidence 至少 2 条（RFC §D.1 Repetition: N ≥ 3 设计值，
        # domain model 设最小 2 以保证至少有一对可比较的 episodic）
        if len(self.source_evidence) < 2:
            raise ValueError(
                f"ConsolidationCandidate.source_evidence 至少需要 2 条，"
                f"当前 {len(self.source_evidence)} 条"
            )
        for eid in self.source_evidence:
            if not eid.strip():
                raise ValueError(
                    "ConsolidationCandidate.source_evidence 中每条 ID 不能为空"
                )

        # confidence 范围
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"ConsolidationCandidate.confidence 必须在 0.0-1.0 之间，"
                f"当前 {self.confidence}"
            )

        # governance_route 必须为 T1（RFC §6.4: consolidation 输出永远 T1）
        if self.governance_route != "T1":
            raise ValueError(
                f"ConsolidationCandidate.governance_route 必须为 'T1'，"
                f"不允许 '{self.governance_route}'"
            )

        # evidence_summary 非空
        if not self.evidence_summary.strip():
            raise ValueError("ConsolidationCandidate.evidence_summary 不能为空")

        # created_at 非空
        if not self.created_at.strip():
            raise ValueError("ConsolidationCandidate.created_at 不能为空")


def to_memory_operation_intent_for_review(
    candidate: ConsolidationCandidate,
) -> MemoryCandidateProposal:
    """将 ConsolidationCandidate 转换为 MemoryCandidateProposal。

    转换后的 proposal 可经 proposal_to_candidate() → proposal_to_decision()
    → build_memory_operation_intent() 链进入现有 governance/confirmation pipeline。

    consolidation 输出始终强制 T1（RFC §6.4）：
    - suggested_action 固定为 PROPOSE（不 AUTO_RETAIN）
    - requires_confirmation 固定为 True
    - memory_type 固定为 "semantic"

    本函数不写 store，不产生 side effect。
    """
    return MemoryCandidateProposal(
        memory_type="semantic",
        content=candidate.content,
        evidence=candidate.evidence_summary,
        importance=_importance_from_confidence(candidate.confidence),
        confidence=candidate.confidence,
        requires_confirmation=True,
        suggested_action=SuggestedAction.PROPOSE,
        rationale=(
            f"[consolidation:{candidate.consolidation_type.value}] "
            f"source_evidence={list(candidate.source_evidence)} | "
            f"governance={candidate.governance_route} | "
            f"created_at={candidate.created_at}"
        ),
    )


def _importance_from_confidence(confidence: float) -> int:
    """将 confidence 映射到 1-10 的 importance 值。"""
    raw = round(confidence * 10)
    return max(1, min(10, raw))
