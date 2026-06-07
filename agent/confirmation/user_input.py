"""通用用户输入 handler：处理 awaiting_user_input 状态。

内存确认分流委托给 agent.confirmation.memory.dispatch_memory_confirmation；
本 handler 只负责 generic user input / collect_input / clarify 路径。
"""

from __future__ import annotations

import inspect

from agent.checkpoint import clear_checkpoint
from agent.confirmation.dispatcher import (
    ConfirmationContext,
    _emit_confirmation_observer_event,
)
from agent.confirmation.memory import dispatch_memory_confirmation
from agent.input_resolution import EMPTY_USER_INPUT, resolve_user_input
from agent.transitions import apply_user_replied_transition


def handle_user_input_step(user_input: str, ctx: ConfirmationContext) -> str:
    """Handle input when task status is awaiting_user_input.

    awaiting_user_input 有四种触发来源（按优先级）：
    1. memory_confirmation / memory_inline_confirmation → 委托 memory dispatch
    2. 执行期求助：request_user_input 元工具调用 → 补充信息，不推进 step
    3. collect_input / clarify 步骤收尾 → planner 规划的"问用户"步骤
    4. 无 plan / 无 pending 的损坏态 → reset
    """
    state = ctx.state
    turn_state = ctx.turn_state
    pending = state.task.pending_user_input_request or {}
    on_runtime_event = getattr(turn_state, "on_runtime_event", None)

    # 委托 memory 确认分流
    memory_result = dispatch_memory_confirmation(
        user_input=user_input,
        ctx=ctx,
        pending=pending,
        on_runtime_event=on_runtime_event,
    )
    if memory_result is not None:
        return memory_result

    messages = state.conversation.messages
    current_plan = state.task.current_plan

    if not current_plan and not state.task.pending_user_input_request:
        from agent.runtime_integration.skill_lifecycle import (
            deactivate_active_skill_for_task_boundary,
        )

        deactivate_active_skill_for_task_boundary(
            state,
            reason="invalid_user_input_state",
            source="confirmation.user_input.invalid_state",
        )
        state.reset_task()
        clear_checkpoint()
        return ""

    resolution = resolve_user_input(state, user_input)
    if resolution.kind == EMPTY_USER_INPUT:
        _emit_confirmation_observer_event(
            "confirmation.user_input.empty",
            payload={"resolution_kind": resolution.kind},
        )
        return "请输入有效内容，或输入取消/退出。"

    transition = _apply_user_replied_transition(
        state=state,
        messages=messages,
        resolution=resolution,
        save_checkpoint_fn=_save_runtime_checkpoint_for_user_input,
        task_boundary_callback=_task_boundary_callback(ctx),
    )
    _emit_confirmation_observer_event(
        "confirmation.user_input.resolved",
        payload={
            "resolution_kind": resolution.kind,
            "should_continue_loop": bool(transition.should_continue_loop),
        },
    )
    if transition.should_continue_loop:
        return ctx.continue_fn(turn_state)
    return transition.reply


def _apply_user_replied_transition(**kwargs):
    """Apply user-input transition while preserving legacy unit-test fakes."""
    try:
        signature = inspect.signature(apply_user_replied_transition)
    except (TypeError, ValueError):
        return apply_user_replied_transition(**kwargs)

    parameters = signature.parameters
    accepts_var_kwargs = any(
        param.kind is inspect.Parameter.VAR_KEYWORD
        for param in parameters.values()
    )
    if accepts_var_kwargs:
        return apply_user_replied_transition(**kwargs)
    filtered = {
        key: value
        for key, value in kwargs.items()
        if key in parameters
    }
    return apply_user_replied_transition(**filtered)


def _save_runtime_checkpoint_for_user_input(state, *, source: str) -> None:
    from agent.runtime_integration.checkpoint_save import save_runtime_checkpoint

    save_runtime_checkpoint(state, source=source)


def _task_boundary_callback(ctx: ConfirmationContext):
    def _callback(*, reason: str, source: str) -> None:
        from agent.runtime_integration.skill_lifecycle import (
            deactivate_active_skill_for_task_boundary,
        )

        deactivate_active_skill_for_task_boundary(
            ctx.state,
            reason=reason,
            source=source,
        )

    return _callback
