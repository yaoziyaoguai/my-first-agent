"""Memory recall branch behavior handler.

中文学习边界：
Memory recall 归属 Contract Section 2 "pre-loop explicit Memory evaluation" 分支点。
它不是新 Anchor、不是新 capability milestone、不是新 runtime flow。

recall = 从 store 读取已批准/auto_retained records → 生成 governed MemorySnapshot →
渲染 prompt section → 返回给调用方注入 system prompt。

这个 handler 注册在 MEMORY_RECALL（schema.py 新增），与 MEMORY_TURN_END_PROPOSAL
（proposal generation）和 MEMORY_PROPOSE（retain execution）并列，各司其职：
- MEMORY_TURN_END_PROPOSAL → stateless proposal generator
- MEMORY_PROPOSE → confirmed proposal executor (retain)
- MEMORY_RECALL → pre-loop snapshot generator for prompt injection

纯读取操作，不写 store、不触发 proposal/consolidation/emergence。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.evidence_recorder import build_memory_evidence_metadata
from agent.memory import build_memory_section
from agent.memory_store import InMemoryMemoryStore, MemoryStoreProtocol


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


class MemoryRecallHandler:
    """Pre-loop memory recall handler。

    中文学习边界：
    这个 handler 不生成 proposal、不调用 MemoryPolicy、不读取真实 episodes、
    不触发 consolidation/emergence/reminder。它只从 store 读取已批准 records，
    生成 governed MemorySnapshot，渲染 prompt section 并返回。

    构造：
        handler = MemoryRecallHandler(store=InMemoryMemoryStore())

    SPEC 决定：recall 触发时机为 chat() 入口（pre-loop），与当前
    refresh_runtime_system_prompt() 行为一致。
    """

    def __init__(self, *, store: MemoryStoreProtocol | None = None) -> None:
        self._store = store or InMemoryMemoryStore()

    def handle(self, request, context):
        """处理 MEMORY_RECALL action。

        从 store 读取已批准 records → 生成 MemorySnapshot → 渲染 prompt section →
        通过 context.invoke_registered_target() 获取 target_module_proof。

        Args:
            request: RuntimeActionRequest，包含 source / parent_trace_id 等
            context: RuntimeActionContext，提供 invoke_registered_target / success / rejected
        """
        payload = dict(request.payload)
        selection_reason = str(payload.get("selection_reason") or "Memory Kernel v1 recall")
        max_items = int(payload.get("max_items") or 5)
        rendered_char_budget = int(payload.get("rendered_char_budget") or 500)
        policy_path = str(payload.get("policy_path") or "")
        policy_decision = str(payload.get("decision") or "")
        policy_reason = str(payload.get("reason") or "")

        store_backend = _store_backend_name(self._store)
        external_side_effects = _has_external_side_effects(self._store)
        requested_metadata = build_memory_evidence_metadata(
            event_type="memory.recall.requested",
            operation="recall",
            source_type="explicit_user",
            decision="pending",
            backend=store_backend,
            count=0,
            reason="pre_loop_prompt_recall",
        )

        if policy_decision == "blocked":
            blocked_metadata = build_memory_evidence_metadata(
                event_type="memory.policy_blocked",
                operation="recall",
                source_type="skill",
                decision="blocked",
                policy_path=policy_path or "skill.memory_scope",
                backend=store_backend,
                count=0,
                reason=policy_reason or "skill_memory_scope_blocked",
            )
            skipped_metadata = build_memory_evidence_metadata(
                event_type="memory.recall.skipped",
                operation="recall",
                source_type="skill",
                decision="skipped",
                policy_path=policy_path or "skill.memory_scope",
                backend=store_backend,
                count=0,
                reason=policy_reason or "skill_memory_scope_blocked",
            )
            return context.success(
                handler_name=type(self).__name__,
                target_module="MemoryRuntime",
                payload={
                    "disposition": "policy_blocked",
                    "snapshot_item_count": 0,
                    "omitted_count": 0,
                    "prompt_section": "",
                    "selection_reason": selection_reason,
                },
                observed_call=None,
                evidence_extra={
                    "memory_recall_requested": requested_metadata,
                    "memory_policy_blocked": blocked_metadata,
                    "memory_recall_skipped": skipped_metadata,
                    "disposition": "policy_blocked",
                    "snapshot_item_count": 0,
                    "omitted_count": 0,
                    "store_backend": store_backend,
                    "external_side_effects": external_side_effects,
                    "policy_path": policy_path or "skill.memory_scope",
                    "read_only_operation": True,
                    "no_silent_retain": True,
                    "no_consolidation": True,
                    "no_emergence": True,
                    "no_proactive_reminder": True,
                },
            )

        # ── 构造 snapshot options ──────────────────────────────────────────
        options = {
            "selection_reason": selection_reason,
            "max_items": max_items,
            "rendered_char_budget": rendered_char_budget,
        }

        # ── 通过 catalog adapter 获取 trusted target_module_proof ──────────
        # 中文学习注释：context.invoke_registered_target() 是 trusted target
        # invocation 的唯一入口。它通过 catalog-owned adapter 调用
        # build_memory_snapshot_from_store()，mint trusted target_module_proof。
        # handler 不自己构造 proof，也不绕过 catalog。
        try:
            observed = context.invoke_registered_target(
                target_module="MemoryRuntime",
                operation="build_memory_snapshot",
                payload={"store": self._store, "options": options},
            )
            snapshot = observed.value  # MemorySnapshot
            # ── 渲染 prompt section ────────────────────────────────────────────
            prompt_section = build_memory_section(snapshot)
        except Exception as exc:
            failed_metadata = build_memory_evidence_metadata(
                event_type="memory.recall.failed",
                operation="recall",
                source_type="explicit_user",
                decision="failed",
                backend=store_backend,
                count=0,
                reason="snapshot_build_failed",
            )
            return context.failed(
                handler_name=type(self).__name__,
                target_module="MemoryRuntime",
                payload={
                    "disposition": "failed",
                    "snapshot_item_count": 0,
                    "omitted_count": 0,
                    "prompt_section": "",
                    "selection_reason": selection_reason,
                },
                observed_call=None,
                evidence_extra={
                    "memory_recall_requested": requested_metadata,
                    "memory_recall_failed": failed_metadata,
                    "disposition": "failed",
                    "snapshot_item_count": 0,
                    "omitted_count": 0,
                    "store_backend": store_backend,
                    "external_side_effects": external_side_effects,
                    "error_type": type(exc).__name__,
                    "read_only_operation": True,
                    "no_silent_retain": True,
                    "no_consolidation": True,
                    "no_emergence": True,
                    "no_proactive_reminder": True,
                },
                error_safe_preview=type(exc).__name__,
            )

        disposition = "recalled" if snapshot.items else "no_memory"
        completed_metadata = build_memory_evidence_metadata(
            event_type="memory.recall.completed",
            operation="recall",
            source_type="explicit_user",
            decision="allowed" if snapshot.items else "skipped",
            backend=store_backend,
            count=len(snapshot.items),
            reason=disposition,
        )
        skipped_metadata = (
            build_memory_evidence_metadata(
                event_type="memory.recall.skipped",
                operation="recall",
                source_type="explicit_user",
                decision="skipped",
                backend=store_backend,
                count=0,
                reason="no_memory",
            )
            if not snapshot.items
            else None
        )
        memory_evidence = {
            "memory_recall_requested": requested_metadata,
            "memory_recall_completed": completed_metadata,
        }
        if skipped_metadata is not None:
            memory_evidence["memory_recall_skipped"] = skipped_metadata

        return context.success(
            handler_name=type(self).__name__,
            target_module="MemoryRuntime",
            payload={
                "disposition": disposition,
                "snapshot_item_count": len(snapshot.items),
                "omitted_count": snapshot.omitted_count,
                "prompt_section": prompt_section,
                "selection_reason": selection_reason,
            },
            observed_call=observed,
            evidence_extra={
                **memory_evidence,
                "disposition": disposition,
                "snapshot_item_count": len(snapshot.items),
                "omitted_count": snapshot.omitted_count,
                "store_backend": store_backend,
                "external_side_effects": external_side_effects,
                "no_silent_retain": True,
                "no_consolidation": True,
                "no_emergence": True,
                "no_proactive_reminder": True,
                "read_only_operation": True,
            },
        )
