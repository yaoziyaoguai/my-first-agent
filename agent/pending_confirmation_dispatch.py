"""Pending confirmation dispatch.

学习型说明：
本模块只根据 `TaskState.status` / pending 字段选择确认 handler。它不解释
Memory/Tool 业务，不保存 checkpoint，不写 conversation messages。handler
仍然拥有各自的业务状态推进。
"""

from __future__ import annotations

from typing import Any

from agent.confirm_handlers import (
    handle_feedback_intent_choice,
    handle_plan_confirmation,
    handle_step_confirmation,
    handle_tool_confirmation,
    handle_user_input_step,
)


def dispatch_pending_confirmation(
    state: Any,
    user_input: str,
    confirmation_ctx: Any,
) -> str | None:
    """按当前 pending 状态分派用户输入；未命中返回 None。"""

    if state.task.current_plan and state.task.status == "awaiting_plan_confirmation":
        return handle_plan_confirmation(user_input, confirmation_ctx)

    if state.task.current_plan and state.task.status == "awaiting_step_confirmation":
        return handle_step_confirmation(user_input, confirmation_ctx)

    if (
        state.task.status == "awaiting_user_input"
        and (state.task.current_plan or state.task.pending_user_input_request)
    ):
        return handle_user_input_step(user_input, confirmation_ctx)

    if state.task.status == "awaiting_feedback_intent":
        return handle_feedback_intent_choice(user_input, confirmation_ctx)

    if (
        getattr(state.task, "pending_tool", None)
        and state.task.status == "awaiting_tool_confirmation"
    ):
        return handle_tool_confirmation(user_input, confirmation_ctx)

    return None
