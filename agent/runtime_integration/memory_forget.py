"""Memory forget branch behavior handler.

Loop 2.1: 将 forget CLI 路径从直接 _memory_runtime.remove_record() 迁入 dispatcher。
forget = 接收 record_id → memory_runtime.remove_record() → disposition="forgotten" 或 "not_found"。

纯删除操作，不生成 proposal、不触发 confirmation/consolidation/recall。
"""

from __future__ import annotations

from typing import Any

from agent.evidence_recorder import build_memory_evidence_metadata


def _delete_requested_metadata(record_id: str) -> dict[str, Any]:
    return build_memory_evidence_metadata(
        event_type="memory.delete_requested",
        operation="delete",
        source_type="explicit_user",
        decision="pending",
        record_id=record_id,
        reason="user_requested_forget",
        raw_fields={"record_id": record_id},
    )


def _delete_completed_metadata(
    event_type: str,
    *,
    record_id: str,
    decision: str,
    reason: str,
) -> dict[str, Any]:
    return build_memory_evidence_metadata(
        event_type=event_type,
        operation="delete",
        source_type="explicit_user",
        decision=decision,
        record_id=record_id,
        reason=reason,
        raw_fields={"record_id": record_id},
    )


class MemoryForgetHandler:
    """forget memory 的 dispatcher handler。

    通过 memory_runtime (与 core.py 共享同一实例) 执行 remove_record，
    通过 context.success/rejected/failed 返回结果，保持 dispatcher evidence chain 闭合。

    构造：
        handler = MemoryForgetHandler(memory_runtime=_memory_runtime)
    """

    def __init__(self, *, memory_runtime: Any = None) -> None:
        self._memory_runtime = memory_runtime

    def handle(self, request: Any, context: Any) -> Any:
        payload = dict(request.payload) if request.payload else {}
        record_id = str(payload.get("record_id") or "")
        requested_metadata = _delete_requested_metadata(record_id)

        if not record_id or self._memory_runtime is None:
            completed_metadata = _delete_completed_metadata(
                "memory.delete_failed",
                record_id=record_id,
                decision="blocked",
                reason="missing_record_id" if not record_id else "no_memory_runtime",
            )
            return context.rejected(
                handler_name=type(self).__name__,
                target_module="MemoryRuntime",
                payload={
                    "disposition": "rejected",
                    "forgotten": False,
                    "record_id": record_id,
                    "rejection_reason": (
                        "missing record_id" if not record_id else "no memory_runtime"
                    ),
                },
                observed_call=None,
                evidence_extra={
                    "disposition": "rejected",
                    "forgotten": False,
                    "memory_delete_requested": requested_metadata,
                    "memory_delete_completed": completed_metadata,
                },
            )

        try:
            removed = self._memory_runtime.remove_record(record_id)
        except Exception:
            completed_metadata = _delete_completed_metadata(
                "memory.delete_failed",
                record_id=record_id,
                decision="failed",
                reason="remove_record_exception",
            )
            return context.failed(
                handler_name=type(self).__name__,
                target_module="MemoryRuntime",
                payload={
                    "disposition": "failed",
                    "forgotten": False,
                    "record_id": record_id,
                },
                observed_call=None,
                evidence_extra={
                    "disposition": "failed",
                    "forgotten": False,
                    "memory_delete_requested": requested_metadata,
                    "memory_delete_completed": completed_metadata,
                },
            )

        if removed:
            completed_metadata = _delete_completed_metadata(
                "memory.deleted",
                record_id=record_id,
                decision="allowed",
                reason="record_removed",
            )
            return context.success(
                handler_name=type(self).__name__,
                target_module="MemoryRuntime",
                payload={
                    "disposition": "forgotten",
                    "forgotten": True,
                    "record_id": record_id,
                },
                observed_call=None,
                evidence_extra={
                    "disposition": "forgotten",
                    "forgotten": True,
                    "memory_delete_requested": requested_metadata,
                    "memory_delete_completed": completed_metadata,
                },
            )

        completed_metadata = _delete_completed_metadata(
            "memory.delete_failed",
            record_id=record_id,
            decision="failed",
            reason="record_not_found",
        )
        return context.success(
            handler_name=type(self).__name__,
            target_module="MemoryRuntime",
            payload={
                "disposition": "not_found",
                "forgotten": False,
                "record_id": record_id,
            },
            observed_call=None,
            evidence_extra={
                "disposition": "not_found",
                "forgotten": False,
                "memory_delete_requested": requested_metadata,
                "memory_delete_completed": completed_metadata,
            },
        )
