"""Memory consolidation turn-end handler.

中文学习边界：
Consolidation 是从跨回合累积的 episodic 记录中检测 pattern 并生成
semantic candidates 的只读操作。它不写 store、不做 LLM 增强（除非 opt-in）、
不自动 adopt candidates（T1 review 是必经路径）。

这个 handler 注册在 MEMORY_CONSOLIDATE（schema.py 新增），在 turn-end hook
中 MEMORY_RECALL 之后触发——此时 store 状态最完整。

为什么需要新的 RuntimeActionType：
- MEMORY_TURN_END_PROPOSAL：从当前 turn 内容判定是否提议保留（单 turn 评估）
- MEMORY_PROPOSE：执行已确认 proposal 的 retain 写入
- MEMORY_RECALL：从 store 读取 snapshot 并注入 context
- MEMORY_CONSOLIDATE：跨回合批量分析 episodic → semantic candidate（全新语义）
  三者均不涉及跨回合 episodic 的 batch analysis。

SPEC: docs/specs/memory-consolidation-l3/SPEC.md
"""

from __future__ import annotations

from typing import Any


def _store_backend_name(store: Any) -> str:
    store_type = type(store).__name__
    if "InMemory" in store_type:
        return "in_memory"
    if "Filesystem" in store_type:
        return "filesystem"
    return store_type.lower()


class MemoryConsolidateHandler:
    """Turn-end consolidation handler。

    在每次 turn 结束时运行 consolidation pipeline，检测是否可以
    从累积的 episodic 记录中提取 semantic candidates。

    使用 context.invoke_registered_target() → catalog-owned adapter
    获取 trusted target_module_proof（与 MemoryRetainHandler / MemoryRecallHandler 相同模式）。

    构造：
        handler = MemoryConsolidateHandler(store=InMemoryMemoryStore())
    """

    def __init__(self, *, store=None):
        self._store = store

    def handle(self, request, context):
        """执行 MEMORY_CONSOLIDATE action。

        1. 通过 catalog adapter 运行 consolidation pipeline
        2. 根据结果返回不同 disposition
        """
        store = self._store
        if store is None:
            from agent.memory_store import InMemoryMemoryStore
            store = InMemoryMemoryStore()

        store_backend = _store_backend_name(store)

        base_evidence = {
            "readonly": True,
            "no_store_write": True,
            "store_backend": store_backend,
        }

        # 通过 catalog adapter 获取 trusted target_module_proof
        try:
            observed = context.invoke_registered_target(
                target_module="MemoryConsolidation",
                operation="run_pipeline",
                payload={"store": store},
            )
            result = observed.value
        except Exception as exc:
            return context.failed(
                handler_name=type(self).__name__,
                target_module="MemoryConsolidation",
                payload={
                    "disposition": "failed",
                    "error_type": type(exc).__name__,
                    "store_backend": store_backend,
                },
                observed_call=None,
                evidence_extra={**base_evidence, "error": str(exc)},
                error_safe_preview=f"consolidation pipeline failed: {exc}",
            )

        if not result.has_candidates:
            if result.evidence_count < 3:
                disposition = "insufficient_evidence"
            else:
                disposition = "no_candidates"
        else:
            disposition = "consolidated"

        consolidation_types = list({
            c.consolidation_type.value for c in result.candidates
        })

        return context.success(
            handler_name=type(self).__name__,
            target_module="MemoryConsolidation",
            payload={
                "disposition": disposition,
                "candidates_count": result.candidate_count,
                "evidence_count": result.evidence_count,
                "skipped_count": result.skipped_count,
                "warnings": list(result.warnings),
                "consolidation_types": consolidation_types,
                "detector_name": result.detector_name,
                "store_backend": store_backend,
            },
            observed_call=observed,
            evidence_extra=base_evidence,
        )
