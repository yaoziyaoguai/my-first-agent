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
from agent.conversation_events import append_control_event
from agent.planner import generate_plan, format_plan_for_display
from agent.task_runtime import advance_current_step_if_needed
from agent.tool_executor import execute_pending_tool


ContinueFn = Callable[[Any], str]


# ===== 用户意图识别 =====
# 三处 handle_*_confirmation 原来都是 `confirm.lower() == "y"` 精确匹配，
# 导致 "yes"、"好的"、"OK" 这些常见肯定词全部落入 feedback 分支触发错误重规划。
# 统一用集合判断；两个集合保证不相交。
_ACCEPT = {"y", "yes", "ok", "okay", "好", "好的", "是", "是的", "行", "可以"}
_REJECT = {"n", "no", "不", "不要", "否", "取消"}


def _is_accept(confirm: str) -> bool:
    return confirm.strip().lower() in _ACCEPT


def _is_reject(confirm: str) -> bool:
    return confirm.strip().lower() in _REJECT


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

    if _is_accept(confirm):
        append_control_event(messages, "plan_confirm_yes", {})
        state.task.status = "running"
        save_checkpoint(state)
        return ctx.continue_fn(ctx.turn_state)

    if _is_reject(confirm):
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

    if _is_accept(confirm):
        append_control_event(messages, "step_confirm_yes", {})
        advance_current_step_if_needed(state)
        # 不要在这里手工 status = "running"：advance_current_step_if_needed
        # 已经按规则把 status 置为 "running"（还有下一步）或 "done"（最后一步）。
        # 手工覆盖会把 "done" 遮蔽成 "running"，让主循环再跑一次空转。
        if state.task.status == "done":
            # 最后一步的确认落在这里：清理任务后直接返回。
            from agent.checkpoint import clear_checkpoint as _clear_ck
            _clear_ck()
            state.reset_task()
            return "好的，任务已完成。"
        save_checkpoint(state)
        return ctx.continue_fn(ctx.turn_state)

    if _is_reject(confirm):
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

    tool_name = pending["tool"]

    if _is_accept(confirm):
        append_control_event(messages, "tool_confirm_yes", pending)
        try:
            execute_pending_tool(
                state=state,
                turn_state=turn_state,
                messages=messages,
                pending=pending,
            )
        except Exception as e:
            # 执行失败时保留 pending_tool 以便排查；同时写一条 tool_result，
            # 避免下次调用 API 因 tool_use 悬空而失败。
            from agent.conversation_events import append_tool_result, has_tool_result
            if not has_tool_result(messages, pending["tool_use_id"]):
                append_tool_result(
                    messages,
                    pending["tool_use_id"],
                    f"[工具 {tool_name} 执行异常] {type(e).__name__}: {e}",
                )
            state.task.status = "running"
            save_checkpoint(state)
            return ctx.continue_fn(turn_state)

        # 成功后再清空 pending_tool，失败情况下保留以便人工排查。
        state.task.pending_tool = None
        state.task.status = "running"
        save_checkpoint(state)
        return ctx.continue_fn(turn_state)

    # 未执行分支（n / feedback）也要清空 pending_tool 并为悬空 tool_use 补占位结果。
    state.task.pending_tool = None

    from agent.conversation_events import append_tool_result, has_tool_result
    if not has_tool_result(messages, pending["tool_use_id"]):
        append_tool_result(
            messages,
            pending["tool_use_id"],
            "[系统] 用户拒绝执行该工具，已跳过。"
            if _is_reject(confirm)
            else f"[系统] 用户未批准该工具，改为反馈意见：{confirm}",
        )

    if _is_reject(confirm):
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