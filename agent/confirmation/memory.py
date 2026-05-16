"""memory confirmation 分流：从 handle_user_input_step 中提取，
避免 user_input handler 直接理解 memory 内部字段。

两个入口对应两类 memory 确认：
- memory_confirmation：Interactive Confirmation v1（用户确认是否记住某条信息）
- memory_inline_confirmation：Phase 7 procedural inline confirmation（用户显式
  确认/拒绝 procedural candidate）
"""

from __future__ import annotations

from typing import Any

from agent.pending_requests import PendingUserInputRequest


def dispatch_memory_confirmation(
    *,
    user_input: str,
    ctx: Any,
    pending: PendingUserInputRequest,
    on_runtime_event: Any,
) -> str | None:
    """尝试按 memory awaiting_kind 分流；非 memory pending 返回 None。

    返回 None 时调用方继续走 generic user_input 路径。
    """
    # memory_confirmation：Interactive Confirmation v1
    if pending.get("awaiting_kind") == "memory_confirmation":
        from agent.memory_interaction import handle_memory_confirmation_reply
        return handle_memory_confirmation_reply(
            user_input,
            ctx,
            memory_runtime=ctx.memory_runtime,
            on_runtime_event=on_runtime_event,
        )

    # memory_inline_confirmation：Phase 7 procedural inline confirmation
    if pending.get("awaiting_kind") == "memory_inline_confirmation":
        from agent.memory_interaction import handle_inline_confirmation_reply
        store = getattr(ctx.memory_runtime, "_store", None)
        if store is None:
            return "未写入：memory store 不可用。"
        return handle_inline_confirmation_reply(
            user_input,
            ctx,
            store=store,
            on_runtime_event=on_runtime_event,
        )

    return None
