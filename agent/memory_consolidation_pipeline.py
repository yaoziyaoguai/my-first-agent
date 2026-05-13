"""Phase 6 — Consolidation Pipeline.

只读串联 source evidence loader → deterministic detector，
返回结构化的 ConsolidationPipelineResult。不写 store、不接 runtime、
不接 T1 pending review CLI、不调 LLM。

RFC 参考：
- §15.4 Phase 6 — Consolidation
- §6.1 consolidation lifecycle — episodic → semantic
- §6.3 consolidation operation types
- §6.4 governance — T1 only
- Appendix D — consolidation semantics
- W4 — consolidation evidence → semantic candidate

架构边界：
- 输入: FilesystemMemoryStore（通过公开 list_records API）
- 输出: ConsolidationPipelineResult（candidates + 统计 + warnings）
- 只读：不调用 store 任何写方法
- 不 import runtime / confirmation / policy / pending review 模块
- 不调用 LLM
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.memory_consolidation import ConsolidationCandidate
from agent.memory_consolidation_engine import DeterministicConsolidationDetector
from agent.memory_consolidation_loader import (
    SourceEvidenceLoadResult,
    load_episodic_evidence,
)


# ── 候选校验（fail-closed 防御层）───────────────────────────────────────────


def _validate_candidate(candidate: ConsolidationCandidate) -> str | None:
    """验证 ConsolidationCandidate 满足 Phase 6 强制约束。

    detector 是确定性的，理论上不会产出无效 candidate。
    本函数作为 defense-in-depth：若 detector 实现有 bug 或未来变更引入错误，
    pipeline 层能 fail-closed 而非静默传播无效数据。

    Returns:
        None 表示通过；非空字符串为失败原因。
    """
    # 1. memory_type 必须为 semantic（RFC §6.4）
    if candidate.memory_type != "semantic":
        return f"memory_type={candidate.memory_type}，非 semantic，已丢弃"

    # 2. governance_route 必须为 T1（RFC §6.4）
    if candidate.governance_route != "T1":
        return f"governance_route={candidate.governance_route}，非 T1，已丢弃"

    # 3. confidence 必须在 [0.0, 1.0] 范围内
    if not (0.0 <= candidate.confidence <= 1.0):
        return f"confidence={candidate.confidence} 超出 [0, 1] 范围，已丢弃"

    # 4. source_evidence 至少 3 条（RFC §D.1 N≥3）
    if len(candidate.source_evidence) < 3:
        return (
            f"source_evidence 仅 {len(candidate.source_evidence)} 条，"
            f"不足 N≥3 门槛（RFC §D.1），已丢弃"
        )

    # 5. content 不能为空
    if not candidate.content or not candidate.content.strip():
        return "content 为空，已丢弃"

    return None


# ── pipeline result ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ConsolidationPipelineResult:
    """Phase 6 consolidation pipeline 的结构化结果。

    串联 loader → detector 后的最终输出。不包含 store 引用，
    不包含 pending review state。
    """

    candidates: tuple[ConsolidationCandidate, ...]
    evidence_count: int
    skipped_count: int
    warnings: tuple[str, ...]
    detector_name: str | None = None

    @property
    def candidate_count(self) -> int:
        """成功生成的 candidate 数。"""
        return len(self.candidates)

    @property
    def has_candidates(self) -> bool:
        """是否有可进入 T1 review 的 candidate。"""
        return len(self.candidates) > 0


# ── 公开 API ─────────────────────────────────────────────────────────────────


def run_consolidation_pipeline(
    store,
    *,
    detector: DeterministicConsolidationDetector | None = None,
) -> ConsolidationPipelineResult:
    """执行 Phase 6 consolidation pipeline：loader → detector。

    只读操作：
    1. 从 store 装载 episodic evidence
    2. 传入 detector 执行确定性 pattern detection
    3. 校验 candidate 满足强制约束（defense-in-depth）
    4. 返回结构化结果

    Args:
        store: FilesystemMemoryStore 实例（需支持 list_records() API）。
        detector: DeterministicConsolidationDetector 实例，None 则使用默认实例。

    Returns:
        ConsolidationPipelineResult:
        - candidates: 通过校验的 ConsolidationCandidate 元组
        - evidence_count: 传入 detector 的 evidence 数量
        - skipped_count: loader 跳过的记录数
        - warnings: loader 警告 + 校验失败警告
        - detector_name: detector 类名（便于审计追踪）
    """
    if detector is None:
        detector = DeterministicConsolidationDetector()

    # Step 1: 从 store 装载 episodic evidence
    load_result: SourceEvidenceLoadResult = load_episodic_evidence(store)
    all_warnings: list[str] = list(load_result.warnings)

    # Step 2: 传给 detector
    evidence_list = list(load_result.evidence)
    candidates = detector.detect(evidence_list)

    # Step 3: 校验 candidate 强制约束（defense-in-depth）
    valid_candidates: list[ConsolidationCandidate] = []
    for c in candidates:
        violation = _validate_candidate(c)
        if violation:
            cid = c.source_evidence[:3] if c.source_evidence else ("?",)
            all_warnings.append(
                f"[candidate evidence={list(cid)}...] {violation}"
            )
            continue
        valid_candidates.append(c)

    # Step 4: 构建结果
    return ConsolidationPipelineResult(
        candidates=tuple(valid_candidates),
        evidence_count=len(evidence_list),
        skipped_count=load_result.skipped_count,
        warnings=tuple(all_warnings),
        detector_name=type(detector).__name__,
    )
