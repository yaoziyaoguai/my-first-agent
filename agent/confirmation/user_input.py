"""通用用户输入 handler：处理 awaiting_user_input 状态。

内存确认分流委托给 agent.confirmation.memory.dispatch_memory_confirmation；
本 handler 只负责 generic user input / collect_input / clarify 路径。
"""

from __future__ import annotations

from agent.checkpoint import clear_checkpoint
from agent.input_resolution import EMPTY_USER_INPUT, resolve_user_input
from agent.transitions import apply_user_replied_transition

from agent.confirmation.dispatcher import (
    ConfirmationContext,
    _emit_confirmation_observer_event,
)
from agent.confirmation.memory import dispatch_memory_confirmation


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

    transition = apply_user_replied_transition(
        state=state,
        messages=messages,
        resolution=resolution,
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
