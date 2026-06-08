"""memory confirmation 分流：从 handle_user_input_step 中提取，
避免 user_input handler 直接理解 memory 内部字段。

两个入口对应两类 memory 确认：
- memory_confirmation：Interactive Confirmation v1（用户确认是否记住某条信息）
- memory_inline_confirmation：Phase 7 procedural inline confirmation（用户显式
  确认/拒绝 procedural candidate）
"""

from __future__ import annotations

import contextlib
from typing import Any

from agent.pending_requests import PendingUserInputRequest

_FORGET_CONFIRM_CHOICES = frozenset({
    "1", "y", "yes", "ok", "okay", "确认", "删除", "好", "是", "可以",
})


def _record_forget_delete_failed(record_id: str, *, reason: str) -> None:
    with contextlib.suppress(Exception):
        from agent.evidence_recorder import record_memory_evidence

        record_memory_evidence(
            event_type="memory.delete_failed",
            operation="delete",
            phase="error",
            status="failed",
            source_type="explicit_user",
            decision="failed",
            reason=reason,
            record_id=record_id,
            raw_fields={"record_id": record_id},
        )


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
            dispatcher=getattr(ctx, "dispatcher", None),
        )

    if pending.get("awaiting_kind") == "memory_forget_confirmation":
        return _handle_memory_forget_confirmation(
            user_input=user_input,
            ctx=ctx,
            pending=pending,
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


def _handle_memory_forget_confirmation(
    *,
    user_input: str,
    ctx: Any,
    pending: PendingUserInputRequest,
) -> str:
    """处理模型发起的 request-only forget 确认。

    MEMORY_FORGET_REQUEST 只能把 runtime 置为等待用户确认；真正删除必须在
    用户确认后通过 RuntimeActionDispatcher 的 MEMORY_FORGET handler 执行。
    """
    from agent.runtime_integration.checkpoint_save import save_runtime_checkpoint
    from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType
    from agent.transitions import (
        CheckpointAction,
        TaskTransitionRequest,
        TransitionEvent,
        apply_task_transition,
        validate_task_transition,
    )

    state = ctx.state
    transition_request = TaskTransitionRequest(
        event=TransitionEvent.MEMORY_CONFIRMATION_RESOLVED,
        owner="confirmation.memory.forget_confirmation",
        expected_from_status="awaiting_user_input",
    )
    preflight = validate_task_transition(state, transition_request)
    if not preflight.allowed:
        return f"无法处理 memory forget confirmation：{preflight.reason}"
    transition = apply_task_transition(
        state,
        transition_request,
        preflight=preflight,
    )
    if not transition.allowed:
        return f"无法处理 memory forget confirmation：{transition.reason}"
    assert transition.checkpoint_action is CheckpointAction.SAVE

    text = (user_input or "").strip().lower()
    record_id = str(pending.get("_record_id") or "")
    dispatcher = getattr(ctx, "dispatcher", None)
    if text in _FORGET_CONFIRM_CHOICES and record_id:
        if dispatcher is None:
            _record_forget_delete_failed(record_id, reason="dispatcher_unavailable")
            state.task.pending_user_input_request = None
            save_runtime_checkpoint(
                state,
                source="confirmation.memory.forget_failed",
            )
            return "删除失败：memory dispatcher 不可用。"

        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.MEMORY_FORGET,
                source="confirmation.memory.forget_confirmation",
                parent_trace_id="",
                payload={"record_id": record_id},
            )
        )
        state.task.pending_user_input_request = None
        save_runtime_checkpoint(
            state,
            source="confirmation.memory.forget_confirmation",
        )
        payload = dict(getattr(result, "payload", {}) or {})
        status = str(getattr(result, "status", "") or "")
        if (
            status == "success"
            and payload.get("forgotten") is True
            and payload.get("disposition") == "forgotten"
        ):
            return "已移除记忆。"
        if payload.get("disposition") == "not_found":
            return "未找到该记忆，可能已经不存在。"

        reason = "dispatcher_result_failed"
        if status == "not_supported":
            reason = "dispatcher_no_handler"
        elif status == "rejected":
            reason = "dispatcher_rejected"
        elif status == "failed":
            reason = "dispatcher_failed"
        _record_forget_delete_failed(record_id, reason=reason)
        return "删除失败：未能移除该记忆。"

    state.task.pending_user_input_request = None
    save_runtime_checkpoint(
        state,
        source="confirmation.memory.forget_cancelled",
    )
    return "已取消，不删除记忆。"
