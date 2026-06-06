"""plan / step / feedback_intent 确认 handler。

这三个 handler 共享同一条"确认→反馈→三选一"的分流路径，放在一起避免
拆散后丢失 plan_confirmation 与 step_confirmation 的 structual symmetry。
"""

from __future__ import annotations

from agent.checkpoint import clear_checkpoint, save_checkpoint
from agent.confirmation.dispatcher import (
    _FEEDBACK_INTENT_VALID_CHOICES,
    ConfirmationContext,
    _confirmation_response,
    _emit_confirmation_observer_event,
    _emit_plan_confirmation,
    _request_feedback_intent_choice,
)
from agent.context_builder import build_planning_messages
from agent.conversation_events import append_control_event
from agent.display_events import feedback_intent_requested
from agent.planner import generate_plan
from agent.runtime_events import (
    FeedbackIntentKind,
    PlanConfirmationKind,
    StepConfirmationKind,
    feedback_intent_transition,
    plan_confirmation_transition,
    step_confirmation_transition,
)
from agent.task_runtime import advance_current_step_if_needed
from agent.transitions import (
    CheckpointAction,
    TaskTransitionRequest,
    TransitionEvent,
    apply_task_transition,
)


def handle_plan_confirmation(user_input: str, ctx: ConfirmationContext) -> str:
    """Handle input when task status is awaiting_plan_confirmation."""
    confirm = user_input.strip()
    state = ctx.state
    messages = state.conversation.messages

    response = _confirmation_response(confirm)

    if response == "accept":
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_ACCEPTED,
            owner="confirmation.plan.accept",
            expected_from_status="awaiting_plan_confirmation",
        ))
        if not result.allowed:
            return f"[系统] plan accept 状态迁移失败: {result.reason}"
        append_control_event(messages, "plan_confirm_yes", {})
        if result.checkpoint_action == CheckpointAction.SAVE:
            save_checkpoint(state)
        _emit_confirmation_observer_event(
            "confirmation.plan.accepted",
            payload={"intent": PlanConfirmationKind.PLAN_ACCEPTED.value},
        )
        return ctx.continue_fn(ctx.turn_state)

    if response == "reject":
        reject_transition = plan_confirmation_transition(
            PlanConfirmationKind.PLAN_REJECTED
        )
        append_control_event(messages, "plan_confirm_no", {})
        messages.append({"role": "assistant", "content": "好的，已取消。"})
        assert not reject_transition.should_checkpoint
        state.reset_task()
        clear_checkpoint()
        _emit_confirmation_observer_event(
            "confirmation.plan.rejected",
            payload={"intent": PlanConfirmationKind.PLAN_REJECTED.value},
        )
        return "好的，已取消。"

    return _request_feedback_intent_choice(
        ctx, confirm, origin_status="awaiting_plan_confirmation"
    )


def handle_step_confirmation(user_input: str, ctx: ConfirmationContext) -> str:
    """Handle input when task status is awaiting_step_confirmation."""
    confirm = user_input.strip()
    state = ctx.state
    messages = state.conversation.messages

    response = _confirmation_response(confirm)

    if response == "accept":
        append_control_event(messages, "step_confirm_yes", {})
        advance_current_step_if_needed(state)
        if state.task.status == "done":
            done_transition = step_confirmation_transition(
                StepConfirmationKind.STEP_ACCEPTED_TASK_DONE
            )
            assert not done_transition.should_checkpoint
            from agent.checkpoint import clear_checkpoint as _clear_ck
            _clear_ck()
            state.reset_task()
            _emit_confirmation_observer_event(
                "confirmation.step.accepted_task_done",
                payload={"intent": StepConfirmationKind.STEP_ACCEPTED_TASK_DONE.value},
            )
            return "好的，任务已完成。"
        continue_transition = step_confirmation_transition(
            StepConfirmationKind.STEP_ACCEPTED_CONTINUE
        )
        if continue_transition.should_checkpoint:
            save_checkpoint(state)
        _emit_confirmation_observer_event(
            "confirmation.step.accepted_continue",
            payload={"intent": StepConfirmationKind.STEP_ACCEPTED_CONTINUE.value},
        )
        return ctx.continue_fn(ctx.turn_state)

    if response == "reject":
        reject_transition = step_confirmation_transition(
            StepConfirmationKind.STEP_REJECTED
        )
        append_control_event(messages, "step_confirm_no", {})
        messages.append({"role": "assistant", "content": "好的，当前任务已停止。"})
        assert not reject_transition.should_checkpoint
        state.reset_task()
        clear_checkpoint()
        _emit_confirmation_observer_event(
            "confirmation.step.rejected",
            payload={"intent": StepConfirmationKind.STEP_REJECTED.value},
        )
        return "好的，当前任务已停止。"

    return _request_feedback_intent_choice(
        ctx, confirm, origin_status="awaiting_step_confirmation"
    )


def handle_feedback_intent_choice(user_input: str, ctx: ConfirmationContext) -> str:
    """awaiting_feedback_intent 状态下分流用户三选一。

    红线（与 docs/P1_TOPIC_SWITCH_PLAN.md §3 对齐）：
    - 仅识别精确匹配 "1" / "2" / "3"。
    - "1" = 当作对当前计划的反馈：恢复 origin_status，写 plan_feedback
      control event，调 planner 重生成 plan。user_goal 保持不变。
    - "2" = 切换为新任务：reset_task + clear_checkpoint + start_planning_fn。
    - "3" = 取消：恢复 origin_status，清 pending，零副作用。
    """
    state = ctx.state
    pending = state.task.pending_user_input_request or {}
    choice_raw = (user_input or "").strip()

    if choice_raw not in _FEEDBACK_INTENT_VALID_CHOICES:
        ambiguous_transition = feedback_intent_transition(
            FeedbackIntentKind.AMBIGUOUS
        )
        assert not ambiguous_transition.should_checkpoint
        assert not ambiguous_transition.clear_pending_user_input
        emit = getattr(ctx.turn_state, "on_runtime_event", None)
        if emit is not None:
            emit(feedback_intent_requested(pending))
        _emit_confirmation_observer_event(
            "confirmation.feedback_intent.ambiguous",
            payload={"intent": FeedbackIntentKind.AMBIGUOUS.value},
        )
        return ""

    feedback_text = pending.get("pending_feedback_text", "") or ""
    origin_status = pending.get("origin_status") or "awaiting_plan_confirmation"
    messages = state.conversation.messages

    if choice_raw == "3":
        cancel_transition = feedback_intent_transition(FeedbackIntentKind.CANCELLED)
        assert cancel_transition.should_checkpoint
        assert cancel_transition.clear_pending_user_input
        state.task.pending_user_input_request = None
        state.task.status = origin_status
        save_checkpoint(state, source="confirm_handlers.feedback_intent_cancel")
        _emit_confirmation_observer_event(
            "confirmation.feedback_intent.cancelled",
            payload={
                "intent": FeedbackIntentKind.CANCELLED.value,
                "origin_status": origin_status,
            },
        )
        return ""

    if choice_raw == "1":
        as_feedback_transition = feedback_intent_transition(
            FeedbackIntentKind.AS_FEEDBACK
        )
        assert as_feedback_transition.should_checkpoint
        assert as_feedback_transition.clear_pending_user_input
        state.task.pending_user_input_request = None
        state.task.status = origin_status
        append_control_event(messages, "plan_feedback", {"feedback": feedback_text})
        revised_goal = (
            f"{state.task.user_goal}\n\n"
            f"用户在确认阶段的补充意见：{feedback_text}"
        )
        plan = generate_plan(
            revised_goal,
            ctx.client,
            ctx.model_name,
            build_planning_messages(state, revised_goal),
        )
        if not plan:
            state.reset_task()
            clear_checkpoint()
            return "未能根据你的补充意见重新生成计划，请重新描述你的需求。"
        state.task.current_plan = plan.model_dump()
        state.task.current_step_index = 0
        state.task.status = as_feedback_transition.next_status or "awaiting_plan_confirmation"
        save_checkpoint(state, source="confirm_handlers.feedback_intent_as_feedback")
        _emit_plan_confirmation(ctx, plan, source="feedback_intent_choice")
        _emit_confirmation_observer_event(
            "confirmation.feedback_intent.as_feedback",
            payload={
                "intent": FeedbackIntentKind.AS_FEEDBACK.value,
                "origin_status": origin_status,
            },
        )
        return ""

    # choice_raw == "2": as_new_task
    as_new_task_transition = feedback_intent_transition(
        FeedbackIntentKind.AS_NEW_TASK
    )
    assert not as_new_task_transition.should_checkpoint
    assert as_new_task_transition.clear_pending_user_input
    if ctx.start_planning_fn is None:
        state.reset_task()
        clear_checkpoint()
        return "请重新输入你的新任务。"

    state.reset_task()
    clear_checkpoint()
    _emit_confirmation_observer_event(
        "confirmation.feedback_intent.as_new_task",
        payload={
            "intent": FeedbackIntentKind.AS_NEW_TASK.value,
            "origin_status": origin_status,
        },
    )
    return ctx.start_planning_fn(feedback_text, ctx.turn_state)
