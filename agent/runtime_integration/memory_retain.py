"""Memory retain branch behavior handler.

中文学习边界：
Memory retain 是属于已有 memory.turn_end_proposal branch point 的下游
execution behavior（不是新 Anchor、不是新 capability milestone）。
retain = 已确认的 proposal → store.apply_operation_intent() → disposition="retain"。

这个 handler 注册在 MEMORY_PROPOSE（schema.py:27 已定义），与注册在
MEMORY_TURN_END_PROPOSAL 的 MemoryTurnEndProposalHandler 各司其职：
- MEMORY_TURN_END_PROPOSAL → stateless proposal generator（evaluation）
- MEMORY_PROPOSE → confirmed proposal executor（retain execution）

SPEC OQ#1 方案 B：复用已有 MEMORY_PROPOSE，不新增 RuntimeActionType。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from agent.memory_confirmation import MemoryConfirmationChoice, MemoryConfirmationStatus
from agent.memory_contracts import MemoryDecisionType, MemoryScope
from agent.memory_operations import (
    MemoryOperationIntent,
    MemoryOperationType,
    build_memory_audit_summary,
)
from agent.memory_store import InMemoryMemoryStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store_backend_name(store: Any) -> str:
    """从 store 实例类型推导 backend 名称，用于 evidence metadata。"""
    store_type = type(store).__name__
    if "InMemory" in store_type:
        return "in_memory"
    if "Filesystem" in store_type:
        return "filesystem"
    return store_type.lower()


def _has_external_side_effects(store: Any) -> bool:
    """Filesystem 等持久化 store 有外部副作用；InMemory 没有。"""
    return "Filesystem" in type(store).__name__


class MemoryRetainHandler:
    """已确认 memory proposal 的 retain 执行 handler。

    中文学习边界：
    这个 handler 不生成 proposal、不调用 MemoryPolicy、不读取真实 episodes、
    不触发 recall/consolidation/reminder。它只把已确认的 candidate 通过
    store.apply_operation_intent() 写入 store。

    构造：
        handler = MemoryRetainHandler(store=InMemoryMemoryStore())
    """

    def __init__(self, *, store: InMemoryMemoryStore | None = None) -> None:
        self._store = store or InMemoryMemoryStore()

    def handle(self, request, context):
        """处理 MEMORY_PROPOSE action。

        验证 confirmation_result、proposal_id、candidate 的完整性和一致性，
        然后构造 MemoryOperationIntent + MemoryAuditSummary 并写入 store。
        """
        payload = dict(request.payload)
        confirmation_result = str(payload.get("confirmation_result") or "")
        proposal_id = str(payload.get("proposal_id") or "")
        candidate = payload.get("candidate")

        store_backend = _store_backend_name(self._store)
        external_side_effects = _has_external_side_effects(self._store)
        provider_kind = str(payload.get("provider_kind") or "")

        base_evidence: dict[str, Any] = {
            "no_silent_retain": True,
            "real_episodes_read": False,
            "external_side_effects": external_side_effects,
        }
        if provider_kind:
            base_evidence["provider_kind"] = provider_kind

        # --- 字段存在性验证 ---
        if not confirmation_result:
            return context.rejected(
                handler_name=type(self).__name__,
                target_module="MemoryStore",
                payload={
                    "disposition": "rejected",
                    "stored": False,
                    "proposal_id": proposal_id or "",
                    "store_backend": store_backend,
                    "rejection_reason": "missing confirmation_result",
                },
                observed_call=None,
                evidence_extra=base_evidence,
                error_safe_preview="missing confirmation_result",
            )

        if not proposal_id:
            return context.rejected(
                handler_name=type(self).__name__,
                target_module="MemoryStore",
                payload={
                    "disposition": "rejected",
                    "stored": False,
                    "proposal_id": "",
                    "store_backend": store_backend,
                    "rejection_reason": "missing proposal_id",
                },
                observed_call=None,
                evidence_extra=base_evidence,
                error_safe_preview="missing proposal_id",
            )

        # --- proposal_id 格式验证 ---
        if not proposal_id.startswith("prop:"):
            return context.rejected(
                handler_name=type(self).__name__,
                target_module="MemoryStore",
                payload={
                    "disposition": "rejected",
                    "stored": False,
                    "proposal_id": proposal_id,
                    "store_backend": store_backend,
                    "rejection_reason": f"proposal_id not found: {proposal_id}",
                },
                observed_call=None,
                evidence_extra=base_evidence,
                error_safe_preview=f"proposal_id not found: {proposal_id}",
            )

        # --- candidate 验证 ---
        if not isinstance(candidate, Mapping):
            return context.rejected(
                handler_name=type(self).__name__,
                target_module="MemoryStore",
                payload={
                    "disposition": "rejected",
                    "stored": False,
                    "proposal_id": proposal_id,
                    "store_backend": store_backend,
                    "rejection_reason": "missing or invalid candidate",
                },
                observed_call=None,
                evidence_extra=base_evidence,
                error_safe_preview="missing or invalid candidate",
            )

        # 转换为普通 dict（payload 中的 nested MappingProxyType 经 deep_freeze 冻结）
        candidate = dict(candidate)

        # proposal_id 与 candidate 内 proposal_id 一致性
        candidate_pid = str(candidate.get("proposal_id") or "")
        if candidate_pid != proposal_id:
            return context.rejected(
                handler_name=type(self).__name__,
                target_module="MemoryStore",
                payload={
                    "disposition": "rejected",
                    "stored": False,
                    "proposal_id": proposal_id,
                    "store_backend": store_backend,
                    "rejection_reason": "proposal_id mismatch between request and candidate",
                },
                observed_call=None,
                evidence_extra=base_evidence,
                error_safe_preview="proposal_id mismatch",
            )

        # --- 用户拒绝路径 ---
        if confirmation_result == "rejected":
            return context.success(
                handler_name=type(self).__name__,
                target_module="MemoryStore",
                payload={
                    "disposition": "not_retained",
                    "stored": False,
                    "proposal_id": proposal_id,
                    "store_backend": store_backend,
                },
                observed_call=None,
                evidence_extra=base_evidence,
            )

        # --- accepted 路径：content hash 防篡改 ---
        content = str(candidate.get("content") or "")
        expected_hash = str(candidate.get("content_hash") or "")
        actual_hash = hashlib.sha256(content.encode()).hexdigest()

        if expected_hash and actual_hash != expected_hash:
            return context.rejected(
                handler_name=type(self).__name__,
                target_module="MemoryStore",
                payload={
                    "disposition": "rejected",
                    "stored": False,
                    "proposal_id": proposal_id,
                    "store_backend": store_backend,
                    "rejection_reason": "content hash mismatch: tampered candidate",
                },
                observed_call=None,
                evidence_extra=base_evidence,
                error_safe_preview="tampered candidate content",
            )

        # --- 构造 MemoryOperationIntent ---
        scope_str = str(candidate.get("scope") or "user")
        try:
            scope = MemoryScope(scope_str)
        except ValueError:
            scope = MemoryScope.USER

        sensitivity = str(candidate.get("sensitivity") or "low").upper()
        sensitive_redacted = sensitivity in ("HIGH", "SECRET")

        intent = MemoryOperationIntent(
            operation_type=MemoryOperationType.RETAIN,
            decision_type=MemoryDecisionType.RETAIN,
            confirmation_status=MemoryConfirmationStatus.APPROVED,
            user_choice=MemoryConfirmationChoice.ACCEPT,
            content_summary=content,
            source_summary=str(candidate.get("source", "turn_end_proposal")),
            scope=scope,
            safety_summary="无额外安全标记",
            sensitive_redacted=sensitive_redacted,
            user_visible_summary=f"已形成长期记忆操作意图：{content[:80]}",
        )
        audit = build_memory_audit_summary(intent)

        # --- 通过 catalog adapter 写入 store ---
        # 使用 invoke_registered_target 获得 trusted target_module_proof，
        # 使 evidence_level 达到 harness_runtime_e2e（dispatcher.route 路径）。
        try:
            observed = context.invoke_registered_target(
                target_module="MemoryStore",
                operation="apply_operation_intent",
                payload={
                    "store": self._store,
                    "intent": intent,
                    "audit_summary": audit,
                },
            )
        except Exception as exc:
            return context.failed(
                handler_name=type(self).__name__,
                target_module="MemoryStore",
                payload={
                    "disposition": "failed",
                    "stored": False,
                    "proposal_id": proposal_id,
                    "store_backend": store_backend,
                    "content_hash": actual_hash,
                },
                observed_call=None,
                evidence_extra={
                    **base_evidence,
                    "error_type": type(exc).__name__,
                },
                error_safe_preview=str(exc),
            )

        return context.success(
            handler_name=type(self).__name__,
            target_module="MemoryStore",
            payload={
                "disposition": "retain",
                "stored": True,
                "proposal_id": proposal_id,
                "store_backend": store_backend,
                "stored_at": _now_iso(),
                "content_hash": actual_hash or expected_hash,
            },
            observed_call=observed,
            evidence_extra=base_evidence,
        )
