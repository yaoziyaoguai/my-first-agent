"""Phase 5b — L2 LLM Inline Extraction Foundation.

本模块实现 RFC §11.3 / §10.4 / §15.3 Phase 5b 的 L2 inline extraction foundation。

架构边界：
- L2TriggerGuard：触发守卫（turn counter、task boundary、explicit trigger、budget）
- run_l2_inline_extraction()：L2 inline extraction 入口（trigger → extract → governance routing）
- 复用现有 MemoryCandidateProposal schema（不新增并行 schema）
- 复用现有 governance pipeline（不新增并行 store path）
- 默认不调用真实 LLM（factory seam 控制）
- 不实现 semantic consolidation（Phase 6）和 procedural emergence（Phase 7）

非目标：
- 不做 semantic consolidation（Phase 6, RFC §15.4）
- 不做 procedural emergence（Phase 7, RFC §15.5）
- 不做 backend abstraction
- 不做 status / inspect CLI
- 不做 pending review CLI 增强
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.memory import _build_t1_pending_dict

# ═══════════════════════════════════════════════════════════════════════════════
# L2 Trigger Guard — RFC §11.3 触发约束
# ═══════════════════════════════════════════════════════════════════════════════
#
# Phase 5b L2 inline extraction 的触发守卫，负责：
# 1. turn counter（N≥5 turns 后触发）
# 2. task boundary 检测（"OK", "done", "下一步" 等简单关键词匹配）
# 3. 用户显式触发
# 4. session 内 L2 调用上限（Haiku 成本控制，最多 5 次）
#
# 不使用 LLM 判断 task boundary —— 简单关键词匹配就够，
# 避免为判断"是否该触发"而额外消耗 token。


# task boundary 检测信号词（RFC §11.3 示例："OK", "done", "下一步" 等）
_TASK_BOUNDARY_SIGNALS: tuple[str, ...] = (
    "done",
    "ok",
    "完成了",
    "做好了",
    "搞定了",
    "下一步",
    "接下来",
    "继续",
    "finished",
    "complete",
)


@dataclass
class L2TriggerGuard:
    """Phase 5b L2 inline extraction 触发守卫。

    按 RFC §11.3 定义的三类触发条件 + 成本上限：

    - N≥5 turns：用户连续输入 5 轮后触发
    - task boundary：检测到完成/下一步信号时触发
    - explicit trigger：用户显式触发
    - session budget：最多 5 次 L2 调用（Haiku 成本控制）

    使用方式：
        guard = L2TriggerGuard()
        for user_input in session:
            guard.record_turn()
            if guard.should_trigger(user_input):
                # run L2 inline extraction
                guard.mark_triggered()

    trigger 后 turn counter 重置，避免连续触发；
    call counter 递增，到上限后停止触发。
    """

    turn_threshold: int = 5
    max_calls_per_session: int = 5

    _turn_count: int = 0
    _l2_call_count: int = 0

    def record_turn(self) -> None:
        """每轮用户输入后调用，递增 turn counter。

        应在每次用户输入被处理后调用，不受 trigger 结果影响。
        """
        self._turn_count += 1

    def should_trigger(
        self,
        user_input: str,
        *,
        is_explicit_trigger: bool = False,
    ) -> bool:
        """判断当前是否应触发 L2 inline extraction。

        检查顺序：budget → explicit → task boundary → turn count。
        任一命中且未超预算即返回 True。
        """
        # budget 耗尽，不再触发
        if self._l2_call_count >= self.max_calls_per_session:
            return False

        if is_explicit_trigger:
            return True

        if self._is_task_boundary(user_input):
            return True

        return self._turn_count >= self.turn_threshold

    def mark_triggered(self) -> None:
        """L2 extraction 触发后调用。

        重置 turn counter（避免连续触发），递增 call counter（累计预算消耗）。
        """
        self._turn_count = 0
        self._l2_call_count += 1

    @property
    def remaining_calls(self) -> int:
        """剩余可调用次数。"""
        return max(0, self.max_calls_per_session - self._l2_call_count)

    @property
    def turn_count(self) -> int:
        """当前连续 turn 计数（用于测试/调试）。"""
        return self._turn_count

    @property
    def l2_call_count(self) -> int:
        """已触发 L2 调用次数（用于测试/调试）。"""
        return self._l2_call_count

    @staticmethod
    def _is_task_boundary(text: str) -> bool:
        """检测 task boundary signal。

        简单关键词匹配，不调用 LLM。
        匹配时要求文本较短（≤20 字符），避免长句中偶然命中信号词导致误触发。

        这是 Phase 5b L2 trigger guard 的最小实现，
        不是 semantic consolidation 的 task understanding。
        """
        stripped = text.strip()
        # 只对短文本做 boundary 检测，避免误触发
        if len(stripped) > 20:
            return False
        text_lower = stripped.lower()
        return any(signal in text_lower for signal in _TASK_BOUNDARY_SIGNALS)


# ═══════════════════════════════════════════════════════════════════════════════
# L2 Inline Extraction Entry Point — RFC §11.3 + §10.4
# ═══════════════════════════════════════════════════════════════════════════════


def run_l2_inline_extraction(
    messages: list[dict],
    store,
    *,
    guard: L2TriggerGuard | None = None,
    model_name: str = "claude-haiku-4-5",
    summary: dict | None = None,
) -> dict:
    """Phase 5b L2 inline extraction 入口。

    从 conversation segment 中提取 memory candidate，
    按 RFC §10.4 governance 矩阵路由到 T1/T2/T3。

    Post-Memory hardening boundary:
        这是显式直调 helper，不是 ``core.chat()`` 的 automatic production path。
        automatic L2 触发只能返回 skipped/deferred safe summary，不能经由本
        helper 构造 standalone store、apply T2 或持久化 T1 pending。

    Args:
        messages: 当前 session 的对话消息（通常为最近 N 条）
        store: MemoryStoreProtocol 实例
        guard: L2TriggerGuard 实例。None 时不更新 trigger 状态（测试用）。
        model_name: L2 extraction 使用的模型名称（默认 Haiku）
        summary: 可选的外部 summary dict，用于聚合统计。

    Returns:
        summary dict: {total_proposals, t1_pending, t2_auto_retained, t3_ignored, ...}

    L2 输出路由（RFC §10.4）：
        episodic + confidence [0.6, 0.8) → T2 auto-retain
        episodic + confidence ≥ 0.8      → T1 pending
        semantic + confidence ≥ 0.6       → T1 pending（永不走 T2）
        procedural + confidence ≥ 0.6     → T1 pending（永不走 T2）
        confidence < 0.6                  → T3 ignore
    """
    import os as _os

    from agent.memory_contracts import MemoryScope, MemorySensitivity
    from agent.memory_extraction import (
        ExtractionInput,
        create_extractor,
    )
    from agent.memory_extraction_bridge import proposal_to_candidate
    from agent.memory_operations import (
        MemoryConfirmationChoice,
        MemoryConfirmationStatus,
        MemoryDecisionType,
        MemoryOperationIntent,
        MemoryOperationType,
        build_memory_audit_summary,
    )
    from agent.memory_store import MemoryStoreApplyStatus

    if summary is None:
        summary: dict[str, Any] = {
            "total_proposals": 0,
            "t1_pending": 0,
            "t2_auto_retained": 0,
            "t3_ignored": 0,
            "dedup_hits": 0,
            "errors": [],
            "source": "l2_inline_extraction",
        }

    if not messages:
        return summary

    # ── 更新 trigger guard ──────────────────────────────────────────────
    if guard is not None:
        guard.mark_triggered()

    # ── Extraction：通过 factory seam 创建 L2 extractor ──────────────────
    # 默认 fake（safe path），真实 LLM 需 MEMORY_EXTRACTION_REAL_LLM=1 opt-in
    _use_real_llm = _os.getenv("MEMORY_EXTRACTION_REAL_LLM", "").strip() in (
        "1", "true", "yes",
    )
    _extractor_type = "l2_inline"
    try:
        extractor = create_extractor(
            _extractor_type,
            min_confidence=0.6,
            min_importance=3,
            use_real_llm=_use_real_llm,
            model_name=model_name,
        )
        extraction_input = ExtractionInput(
            transcript=messages,
            session_metadata={"source": "l2_inline_extraction"},
        )
        result = extractor.extract(extraction_input)
    except Exception as exc:
        summary["errors"].append(f"L2 extraction 失败: {exc}")
        return summary

    proposals = list(result.proposals)
    summary["total_proposals"] = len(proposals)
    if hasattr(result, "extraction_summary") and result.extraction_summary:
        summary["extraction_summary"] = result.extraction_summary

    # ── L2 Governance Routing（RFC §10.4 矩阵）──────────────────────────
    # 与 W3 的关键区别：
    #   - W3 session-end 只处理 episodic（non-episodic → T3 ignore）
    #   - L2 处理所有类型，但 non-episodic（semantic/procedural）永不走 T2
    #
    # 共享约束（与 W3 一致）：
    #   - T2 仅 episodic + confidence [0.6, 0.8)
    #   - T2 单 session 上限 3 条
    #   - T3: confidence < 0.6
    #   - T1: confidence ≥ 0.8 的 episodic，或 ≥ 0.6 的 non-episodic

    max_t2_per_session = 3
    t2_count = 0
    t1_proposals: list[dict] = []

    from agent.memory_store import find_duplicate_record

    existing_records = store.list_records()

    for proposal in proposals:
        confidence = proposal.confidence

        # ── T3: confidence < 0.6 → ignore ────────────────────────────
        if confidence < 0.6:
            summary["t3_ignored"] += 1
            continue

        # ── Non-episodic（semantic / procedural）→ 永远 T1 ──────────
        # RFC §10.4：L2 LLM [0.6, 0.8) → semantic T1, procedural T1
        # 不可 silent retain non-episodic
        if proposal.memory_type != "episodic":
            t1_proposals.append(_build_t1_pending_dict(
                proposal, "l2_inline_extraction",
            ))
            summary["t1_pending"] += 1
            continue

        # ── Episodic routing ─────────────────────────────────────────
        # T2: episodic + confidence [0.6, 0.8)
        if 0.6 <= confidence < 0.8:
            if t2_count >= max_t2_per_session:
                summary["t3_ignored"] += 1
                continue

            candidate = proposal_to_candidate(proposal)
            if candidate.sensitivity in {
                MemorySensitivity.HIGH,
                MemorySensitivity.SECRET,
            }:
                summary["t3_ignored"] += 1
                continue

            # 去重检查
            duplicate = find_duplicate_record(
                candidate.content, candidate.proposed_type, candidate.scope,
                existing_records,
            )
            if duplicate is not None:
                summary["dedup_hits"] += 1
                summary["t3_ignored"] += 1
                continue

            # T2 写入
            t2_intent = MemoryOperationIntent(
                operation_type=MemoryOperationType.RETAIN,
                decision_type=MemoryDecisionType.RETAIN,
                confirmation_status=MemoryConfirmationStatus.AUTO_RETAINED,
                user_choice=MemoryConfirmationChoice.ACCEPT,
                content_summary=proposal.content,
                source_summary=f"l2_inline_extraction: {proposal.evidence[:100]}",
                scope=candidate.scope or MemoryScope.USER,
                safety_summary="T2 auto_retained (L2 inline extraction)",
                sensitive_redacted=False,
                user_visible_summary=f"[自动记录] {proposal.content[:80]}",
                memory_type="episodic",
                source_type="agent_suggested",
                confidence=proposal.confidence,
            )
            t2_audit = build_memory_audit_summary(t2_intent)
            t2_result = store.apply_operation_intent(t2_intent, t2_audit)

            if t2_result.status is MemoryStoreApplyStatus.APPLIED:
                t2_count += 1
                summary["t2_auto_retained"] += 1
            else:
                summary["errors"].append(
                    f"L2 T2 auto_retain apply 失败: {t2_result.message}"
                )
            continue

        # T1: episodic + confidence ≥ 0.8
        t1_proposals.append(_build_t1_pending_dict(
            proposal, "l2_inline_extraction",
        ))
        summary["t1_pending"] += 1

    # ── T1 pending 持久化 ──────────────────────────────────────────────
    if t1_proposals:
        from agent.memory import _persist_t1_pending_proposals

        try:
            _persist_t1_pending_proposals(t1_proposals)
        except Exception as exc:
            summary["errors"].append(f"L2 T1 pending 持久化失败: {exc}")

    return summary


def maybe_run_l2_inline(
    messages: list[dict],
    *,
    guard: L2TriggerGuard | None = None,
    model_name: str = "claude-haiku-4-5",
) -> dict:
    """Bounded automatic L2 inline orchestration for core.py.

    ``core.py`` must not construct durable stores directly, and this automatic
    path must not construct a standalone store on its behalf. In this hardening
    stage L2 productionization stays deferred even when a durable root is
    configured: no HOME fallback, no write path, no T1 pending persistence, and
    no raw transcript/path in the returned summary.
    """
    from agent.memory_fs_store import resolve_configured_memory_root

    summary: dict[str, Any] = {
        "source": "l2_inline_extraction",
        "decision": "skipped",
        "reason": "",
        "redacted": True,
        "total_proposals": 0,
        "t1_pending": 0,
        "t2_auto_retained": 0,
        "t3_ignored": 0,
        "dedup_hits": 0,
        "errors": [],
    }
    root = resolve_configured_memory_root()
    if root is None:
        summary["reason"] = "durable_memory_root_not_configured"
        _record_l2_skipped(summary["reason"])
        return summary

    summary["decision"] = "deferred"
    summary["reason"] = "l2_inline_automatic_path_deferred"
    summary.update(_safe_l2_root_metadata(root))
    _record_l2_skipped(summary["reason"])
    return summary


def _safe_l2_root_metadata(root: Path) -> dict[str, Any]:
    from agent.memory import _safe_memory_root_metadata

    return _safe_memory_root_metadata(root)


def _record_l2_skipped(reason: str) -> None:
    try:
        from agent.evidence_recorder import record_memory_evidence

        record_memory_evidence(
            event_type="memory.proposal_skipped",
            operation="extract",
            phase="decision",
            status="skipped",
            source_type="system",
            decision="skipped",
            policy_path="l2_inline_extraction_deferred",
            reason=reason,
            count=0,
            raw_fields={},
        )
    except Exception:
        pass
