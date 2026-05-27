"""Memory forget branch behavior handler.

Loop 2.1: 将 forget CLI 路径从直接 _memory_runtime.remove_record() 迁入 dispatcher。
forget = 接收 record_id → memory_runtime.remove_record() → disposition="forgotten" 或 "not_found"。

纯删除操作，不生成 proposal、不触发 confirmation/consolidation/recall。
"""

from __future__ import annotations

from typing import Any


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

        if not record_id or self._memory_runtime is None:
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
                    "record_id": record_id,
                },
            )

        try:
            removed = self._memory_runtime.remove_record(record_id)
        except Exception:
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
                    "record_id": record_id,
                },
            )

        if removed:
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
                    "record_id": record_id,
                },
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
                "record_id": record_id,
            },
        )
