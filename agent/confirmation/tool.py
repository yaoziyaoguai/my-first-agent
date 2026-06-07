"""工具确认 handler：处理 awaiting_tool_confirmation 状态下的用户输入。"""

from __future__ import annotations

from agent.confirmation.dispatcher import (
    ConfirmationContext,
    _confirmation_response,
    _emit_confirmation_observer_event,
)
from agent.conversation_events import append_control_event
from agent.runtime_events import (
    ToolConfirmationKind,
    ToolResultTransitionKind,
    tool_confirmation_transition,
    tool_result_transition,
)
from agent.runtime_integration.checkpoint_save import save_runtime_checkpoint
from agent.tool_executor import execute_pending_tool
from agent.transitions import (
    CheckpointAction,
    TaskTransitionRequest,
    TransitionEvent,
    apply_task_transition,
    validate_task_transition,
)


def save_checkpoint(state, source=None, **kwargs):
    """Backward-compatible patch symbol that still uses the runtime gateway."""

    save_runtime_checkpoint(state, source=source, **kwargs)


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
        accept_req = TaskTransitionRequest(
            event=TransitionEvent.USER_ACCEPTED,
            owner="confirmation.tool.accept_validate",
            expected_from_status="awaiting_tool_confirmation",
        )
        preflight = validate_task_transition(state, accept_req)
        if not preflight.allowed:
            return f"[系统] tool accept 前置验证失败: {preflight.reason}"

        append_control_event(messages, "tool_confirm_yes", pending)
        try:
            # P1-2: 优先通过 ToolRuntimeMediator 执行 pending tool，
            # 确保走统一 gate_decision → invoke → pending_execute → result 证据链。
            #
            # 关键修复（P1-2 冲突复核）：turn_state 是 chat() 每次调用新建的
            # per-invocation 对象，而 pending confirmation 跨越两次 chat() 调用。
            # turn_state._tool_mediator 在第一次调用中设置，第二次调用时已不存在。
            # 因此当 _tool_mediator 为 None 但 ctx.dispatcher 可用时，即时构造
            # mediator 以保证 pending accept 路径必然进入 mediator-controlled path。
            mediator = getattr(ctx.turn_state, "_tool_mediator", None)
            if mediator is None and ctx.dispatcher is not None:
                from agent.tool_runtime_mediator import ToolRuntimeMediator
                mediator = ToolRuntimeMediator(
                    ctx.dispatcher,
                    state=state,
                    turn_state=turn_state,
                    turn_context={},
                    messages=messages,
                )
                ctx.turn_state._tool_mediator = mediator
            if mediator is not None:
                mediator.mediate_pending(pending)
            else:
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
            accept_error_result = apply_task_transition(state, TaskTransitionRequest(
                event=TransitionEvent.USER_ACCEPTED,
                owner="confirmation.tool.accept_error",
                expected_from_status="awaiting_tool_confirmation",
            ))
            if not accept_error_result.allowed:
                return f"[系统] tool accept error 状态迁移失败: {accept_error_result.reason}"
            if accept_error_result.checkpoint_action == CheckpointAction.SAVE:
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
        accept_result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_ACCEPTED,
            owner="confirmation.tool.accept_success",
            expected_from_status="awaiting_tool_confirmation",
        ))
        if not accept_result.allowed:
            return f"[系统] tool accept 状态迁移失败: {accept_result.reason}"
        if accept_result.checkpoint_action == CheckpointAction.SAVE:
            save_checkpoint(state)
        _emit_confirmation_observer_event(
            "confirmation.tool.accepted_success",
            payload={
                "intent": ToolConfirmationKind.TOOL_ACCEPTED_SUCCESS.value,
                "tool_name": tool_name,
            },
        )
        return ctx.continue_fn(turn_state)

    # 用户拒绝或反馈 — 先验证 transition 合法性，再执行副作用
    if response == "reject":
        reject_event = TransitionEvent.USER_REJECTED
        reject_owner = "confirmation.tool.reject"
    else:
        reject_event = TransitionEvent.USER_FEEDBACK
        reject_owner = "confirmation.tool.feedback"

    preflight = validate_task_transition(state, TaskTransitionRequest(
        event=reject_event,
        owner=reject_owner,
        expected_from_status="awaiting_tool_confirmation",
    ))
    if not preflight.allowed:
        return f"[系统] tool {response} 前置验证失败: {preflight.reason}"

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
        reject_result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_REJECTED,
            owner="confirmation.tool.reject",
            expected_from_status="awaiting_tool_confirmation",
        ))
        if not reject_result.allowed:
            return f"[系统] tool reject 状态迁移失败: {reject_result.reason}"
        if reject_result.checkpoint_action == CheckpointAction.SAVE:
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
    feedback_result = apply_task_transition(state, TaskTransitionRequest(
        event=TransitionEvent.USER_FEEDBACK,
        owner="confirmation.tool.feedback",
        expected_from_status="awaiting_tool_confirmation",
    ))
    if not feedback_result.allowed:
        return f"[系统] tool feedback 状态迁移失败: {feedback_result.reason}"
    if feedback_result.checkpoint_action == CheckpointAction.SAVE:
        save_checkpoint(state)
    _emit_confirmation_observer_event(
        "confirmation.tool.feedback",
        payload={"tool_name": tool_name},
    )
    return ctx.continue_fn(turn_state)
