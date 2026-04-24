"""Confirmation handlers for plan / step / tool states.

These handlers mutate task state and write semantic control events, but they do
not own the main loop. Runtime dependencies are grouped in ConfirmationContext
so each handler has a small, readable signature.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent.checkpoint import clear_checkpoint, save_checkpoint
from agent.context_builder import build_planning_messages
from agent.conversation_events import append_control_event, append_tool_result
from agent.planner import generate_plan, format_plan_for_display
from agent.task_runtime import advance_current_step_if_needed
from agent.tool_executor import execute_pending_tool


ContinueFn = Callable[[Any], str]


@dataclass(slots=True)
class ConfirmationContext:
    """Dependencies needed by confirmation handlers.

    Grouping these dependencies keeps handler signatures readable while keeping
    the handlers free of core.py globals.
    """

    state: Any
    turn_state: Any
    client: Any
    model_name: str
    continue_fn: ContinueFn


def handle_plan_confirmation(user_input: str, ctx: ConfirmationContext) -> str:
    """Handle input when task status is awaiting_plan_confirmation."""
    confirm = user_input.strip()
    state = ctx.state
    messages = state.conversation.messages

    if confirm.lower() == "y":
        append_control_event(messages, "plan_confirm_yes", {})
        state.task.status = "running"
        save_checkpoint(state)
        return ctx.continue_fn(ctx.turn_state)

    if confirm.lower() == "n":
        append_control_event(messages, "plan_confirm_no", {})
        messages.append({"role": "assistant", "content": "好的，已取消。"})
        state.reset_task()
        clear_checkpoint()
        return "好的，已取消。"

    append_control_event(messages, "plan_feedback", {"feedback": confirm})

    revised_goal = f"{state.task.user_goal}\n\n用户对计划的修改意见：{confirm}"
    state.task.user_goal = revised_goal

    plan = generate_plan(
        revised_goal,
        ctx.client,
        ctx.model_name,
        build_planning_messages(state, revised_goal),
    )
    if not plan:
        state.reset_task()
        clear_checkpoint()
        return "未能根据你的修改意见重新生成计划，请重新描述你的需求。"

    state.task.current_plan = plan.model_dump()
    state.task.current_step_index = 0
    state.task.status = "awaiting_plan_confirmation"
    save_checkpoint(state)

    print(format_plan_for_display(plan))
    print("按此计划执行吗？(y/n/输入修改意见): ", end="", flush=True)
    return ""


def handle_step_confirmation(user_input: str, ctx: ConfirmationContext) -> str:
    """Handle input when task status is awaiting_step_confirmation."""
    confirm = user_input.strip()
    state = ctx.state
    messages = state.conversation.messages

    if confirm.lower() == "y":
        append_control_event(messages, "step_confirm_yes", {})
        advance_current_step_if_needed(state)
        state.task.status = "running"
        save_checkpoint(state)
        return ctx.continue_fn(ctx.turn_state)

    if confirm.lower() == "n":
        append_control_event(messages, "step_confirm_no", {})
        messages.append({"role": "assistant", "content": "好的，当前任务已停止。"})
        state.reset_task()
        clear_checkpoint()
        return "好的，当前任务已停止。"

    append_control_event(messages, "plan_feedback", {"feedback": confirm})

    revised_goal = (
        f"{state.task.user_goal}\n\n"
        f"用户在步骤确认阶段的补充意见：{confirm}"
    )
    state.task.user_goal = revised_goal

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
    state.task.status = "awaiting_plan_confirmation"
    save_checkpoint(state)

    print(format_plan_for_display(plan))
    print("按此计划执行吗？(y/n/输入修改意见): ", end="", flush=True)
    return ""


def handle_tool_confirmation(user_input: str, ctx: ConfirmationContext) -> str:
    """Handle input when task status is awaiting_tool_confirmation."""
    confirm = user_input.strip()
    state = ctx.state
    turn_state = ctx.turn_state
    messages = state.conversation.messages

    pending = state.task.pending_tool
    if not pending:
        return "[系统] 未找到待确认的工具。"

    tool_use_id = pending["tool_use_id"]
    tool_name = pending["tool"]
    tool_input = pending["input"]

    # Clear pending before continuing so the next loop is not intercepted again.
    state.task.pending_tool = None

    if confirm.lower() == "y":
        append_control_event(messages, "tool_confirm_yes", pending)
        execute_pending_tool(
            state=state,
            turn_state=turn_state,
            messages=messages,
            pending=pending,
        )
        state.task.status = "running"
        save_checkpoint(state)
        return ctx.continue_fn(turn_state)

    if confirm.lower() == "n":
        append_control_event(messages, "tool_confirm_no", pending)
        state.task.status = "running"
        save_checkpoint(state)
        return ctx.continue_fn(turn_state)

    append_control_event(messages, "tool_feedback", {
        "feedback": confirm,
        "tool": tool_name,
    })
    state.task.status = "running"
    save_checkpoint(state)
    return ctx.continue_fn(turn_state)