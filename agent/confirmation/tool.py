"""工具确认 handler：处理 awaiting_tool_confirmation 状态下的用户输入。"""

from __future__ import annotations

from agent.checkpoint import save_checkpoint
from agent.conversation_events import append_control_event
from agent.runtime_events import (
    ToolConfirmationKind,
    ToolResultTransitionKind,
    tool_confirmation_transition,
    tool_result_transition,
)
from agent.tool_executor import execute_pending_tool

from agent.confirmation.dispatcher import (
    ConfirmationContext,
    _confirmation_response,
    _emit_confirmation_observer_event,
)


def handle_tool_confirmation(user_input: str, ctx: ConfirmationContext) -> str:
    """Handle input when task status is awaiting_tool_confirmation."""
    confirm = user_input.strip()
    state = ctx.state
    turn_state = ctx.turn_state
    messages = state.conversation.messages

    pending = state.task.pending_tool
    if not pending:
        return "[系统] 未找到待确认的工具。"

    tool_name = pending["tool"]

    response = _confirmation_response(confirm)

    if response == "accept":
        append_control_event(messages, "tool_confirm_yes", pending)
        try:
            execute_pending_tool(
                state=state,
                turn_state=turn_state,
                messages=messages,
                pending=pending,
            )
        except Exception as e:
            failed_transition = tool_confirmation_transition(
                ToolConfirmationKind.TOOL_ACCEPTED_FAILED
            )
            assert failed_transition.clear_pending_tool is False
            from agent.conversation_events import append_tool_result, has_tool_result
            if not has_tool_result(messages, pending["tool_use_id"]):
                append_tool_result(
                    messages,
                    pending["tool_use_id"],
                    f"[工具 {tool_name} 执行异常] {type(e).__name__}: {e}",
                )
            if failed_transition.next_status:
                state.task.status = failed_transition.next_status
            if failed_transition.should_checkpoint:
                save_checkpoint(state)
            _emit_confirmation_observer_event(
                "confirmation.tool.accepted_failed",
                payload={
                    "intent": ToolConfirmationKind.TOOL_ACCEPTED_FAILED.value,
                    "tool_name": tool_name,
                },
            )
            return ctx.continue_fn(turn_state)

        success_transition = tool_confirmation_transition(
            ToolConfirmationKind.TOOL_ACCEPTED_SUCCESS
        )
        if success_transition.clear_pending_tool:
            state.task.pending_tool = None
        if success_transition.next_status:
            state.task.status = success_transition.next_status
        if success_transition.should_checkpoint:
            save_checkpoint(state)
        _emit_confirmation_observer_event(
            "confirmation.tool.accepted_success",
            payload={
                "intent": ToolConfirmationKind.TOOL_ACCEPTED_SUCCESS.value,
                "tool_name": tool_name,
            },
        )
        return ctx.continue_fn(turn_state)

    # 用户拒绝或反馈
    transition = tool_result_transition(ToolResultTransitionKind.USER_REJECTION)
    if transition.clear_pending_tool:
        state.task.pending_tool = None

    from agent.display_events import build_tool_status_event, emit_display_event
    if response == "reject":
        rejection_text = "用户拒绝执行，已跳过。"
    else:
        rejection_text = "用户未批准，改为提供反馈意见。"
    emit_display_event(
        turn_state.on_display_event,
        build_tool_status_event(
            event_type=transition.display_events[0],
            tool_name=tool_name,
            tool_input=pending.get("input") or {},
            status_text=rejection_text,
        ),
    )

    from agent.conversation_events import append_tool_result, has_tool_result
    if not has_tool_result(messages, pending["tool_use_id"]):
        append_tool_result(
            messages,
            pending["tool_use_id"],
            "[系统] 用户拒绝执行该工具，已跳过。"
            if response == "reject"
            else f"[系统] 用户未批准该工具，改为反馈意见：{confirm}",
        )

    if response == "reject":
        append_control_event(messages, "tool_confirm_no", pending)
        state.task.status = "running"
        if transition.should_checkpoint:
            save_checkpoint(state)
        _emit_confirmation_observer_event(
            "confirmation.tool.rejected",
            payload={"tool_name": tool_name},
        )
        return ctx.continue_fn(turn_state)

    append_control_event(messages, "tool_feedback", {
        "feedback": confirm,
        "tool": tool_name,
    })
    state.task.status = "running"
    if transition.should_checkpoint:
        save_checkpoint(state)
    _emit_confirmation_observer_event(
        "confirmation.tool.feedback",
        payload={"tool_name": tool_name},
    )
    return ctx.continue_fn(turn_state)
