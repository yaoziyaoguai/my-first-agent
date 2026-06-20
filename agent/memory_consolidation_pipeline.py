"""Phase 6 — Consolidation Pipeline.

串联 source evidence loader → deterministic detector → (optional) LLM content enhancement，
返回结构化的 ConsolidationPipelineResult。不写 store、不接 runtime、
不接 T1 pending review CLI（dispatch 在 memory_consolidation_review.py）。

⛔ FROZEN (2026-05-25): 该模块属于 frozen consolidation pipeline。
   业务操作 deferred；dispatch path only；不允许继续增强。
   参见: docs/audit/global-agent-capability-architecture-audit-2026-05-25.md F4

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
- LLM content enhancement 是 opt-in，默认不调用
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.memory_consolidation import ConsolidationCandidate, EpisodicEvidence
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

    串联 loader → detector → (optional) LLM enhancement 后的最终输出。
    不包含 store 引用，不包含 pending review state。
    dry_run 字段用于 dogfood / audit 预览：它只描述“如果 dispatch 会发生什么”，
    pipeline 本身仍然不写 `_pending` 或正式 memory store。
    """

    candidates: tuple[ConsolidationCandidate, ...]
    evidence_count: int
    skipped_count: int
    warnings: tuple[str, ...]
    detector_name: str | None = None
    dry_run: bool = False
    validator_pass_count: int = 0
    would_dispatch_count: int = 0
    direct_store_write: bool = False
    auto_approve: bool = False
    # LLM content enhancement 相关字段（Phase 6b）
    llm_enabled: bool = False
    llm_enhanced_count: int = 0
    llm_warnings: tuple[str, ...] = ()

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
    llm_generator=None,  # LLMConsolidationContentGenerator | None
    dry_run: bool = False,
) -> ConsolidationPipelineResult:
    """执行 Phase 6 consolidation pipeline：loader → detector → (opt) LLM enhancement。

    只读操作：
    1. 从 store 装载 episodic evidence
    2. 传入 detector 执行确定性 pattern detection
    3. 校验 candidate 满足强制约束（defense-in-depth）
    4. 若 opt-in 启用 LLM，对 valid candidates 做 content/evidence_summary 增强
       - 增强失败：保留 deterministic candidate + warning
       - 增强成功：替换 content/evidence_summary，其他字段不变
    5. 返回结构化结果；dry_run=True 时额外填充 would_dispatch_count，
       但仍不写 `_pending`、不写 store、不 auto approve。

    Args:
        store: FilesystemMemoryStore 实例（需支持 list_records() API）。
        detector: DeterministicConsolidationDetector 实例，None 则使用默认实例。
        llm_generator: LLMConsolidationContentGenerator 实例，None 则跳过 LLM 增强。
                       调用者可选传入，pipeline 不负责 opt-in gate。
        dry_run: dogfood / audit 预览路径，用于验证 candidate 与治理摘要，
                 不执行任何持久化写入。

    Returns:
        ConsolidationPipelineResult:
        - candidates: 通过校验的 ConsolidationCandidate 元组
        - evidence_count: 传入 detector 的 evidence 数量
        - skipped_count: loader 跳过的记录数
        - warnings: loader 警告 + 校验失败警告 + LLM 增强警告
        - detector_name: detector 类名
        - llm_enabled: 是否尝试了 LLM 增强
        - llm_enhanced_count: 成功增强的 candidate 数
        - llm_warnings: LLM 增强过程中的警告
        - dry_run / would_dispatch_count / direct_store_write / auto_approve:
          dogfood 安全摘要字段
    """
    if detector is None:
        detector = DeterministicConsolidationDetector()

    # Step 1: 从 store 装载 episodic evidence
    load_result: SourceEvidenceLoadResult = load_episodic_evidence(store)
    all_warnings: list[str] = list(load_result.warnings)
    llm_warnings: list[str] = []
    llm_enhanced = 0
    llm_enabled = llm_generator is not None

    # Step 2: 传给 detector
    evidence_list = list(load_result.evidence)
    candidates = detector.detect(evidence_list)

    # 构建 evidence lookup（record_id → EpisodicEvidence），供 LLM 增强使用
    evidence_by_id: dict[str, EpisodicEvidence] = {
        e.record_id: e for e in evidence_list
    }

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

    # Step 4: optional LLM content enhancement
    if llm_enabled and valid_candidates:
        valid_candidates, llm_enhanced, llm_warnings = _apply_llm_enhancement(
            valid_candidates, evidence_by_id, llm_generator
        )
        all_warnings.extend(llm_warnings)

    # Step 5: 构建结果
    return ConsolidationPipelineResult(
        candidates=tuple(valid_candidates),
        evidence_count=len(evidence_list),
        skipped_count=load_result.skipped_count,
        warnings=tuple(all_warnings),
        detector_name=type(detector).__name__,
        dry_run=dry_run,
        validator_pass_count=len(valid_candidates),
        would_dispatch_count=len(valid_candidates) if dry_run else 0,
        direct_store_write=False,
        auto_approve=False,
        llm_enabled=llm_enabled,
        llm_enhanced_count=llm_enhanced,
        llm_warnings=tuple(llm_warnings),
    )


def _apply_llm_enhancement(
    candidates: list[ConsolidationCandidate],
    evidence_by_id: dict[str, EpisodicEvidence],
    llm_generator,
) -> tuple[list[ConsolidationCandidate], int, list[str]]:
    """对 valid candidates 执行 LLM content/evidence_summary 增强。

    增强失败时保留 deterministic candidate + warning，
    不因 LLM 失败而丢弃有效的确定性 candidate。

    Returns:
        (enhanced_candidates, enhanced_count, warnings)
    """
    enhanced: list[ConsolidationCandidate] = []
    warnings: list[str] = []
    enhanced_count = 0

    for c in candidates:
        # 从 evidence_by_id 重构此 candidate 的 evidence group
        group = [
            evidence_by_id[rid]
            for rid in c.source_evidence
            if rid in evidence_by_id
        ]
        if len(group) < 3:
            warnings.append(
                f"[candidate evidence={list(c.source_evidence[:3])}] "
                f"evidence group 不足 N≥3，跳过 LLM 增强，保留 deterministic"
            )
            enhanced.append(c)
            continue

        try:
            llm_candidate, llm_warn = llm_generator.enhance(c, group)
        except Exception as exc:
            warnings.append(
                f"[candidate evidence={list(c.source_evidence[:3])}] "
                f"LLM 增强异常: {exc}，保留 deterministic"
            )
            enhanced.append(c)
            continue

        if llm_candidate is None:
            warnings.append(
                f"[candidate evidence={list(c.source_evidence[:3])}] "
                f"LLM 增强失败: {llm_warn}，保留 deterministic"
            )
            enhanced.append(c)
            continue

        enhanced.append(llm_candidate)
        enhanced_count += 1

    return enhanced, enhanced_count, warnings
