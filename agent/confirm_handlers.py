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
from agent.display_events import plan_confirmation_requested
from agent.input_resolution import EMPTY_USER_INPUT, resolve_user_input
from agent.planner import generate_plan, format_plan_for_display
from agent.task_runtime import advance_current_step_if_needed
from agent.tool_executor import execute_pending_tool
from agent.transitions import apply_user_replied_transition


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


def _emit_plan_confirmation(ctx: ConfirmationContext, plan: Any, *, source: str) -> None:
    """把重规划后的确认提示投影到 UI。

    confirmation handler 负责状态机和语义控制事件；计划文本展示只是 Runtime -> UI
    输出，不应写入 conversation.messages，也不应改变 checkpoint schema。这里通过
    turn_state.on_runtime_event 走统一出口；若测试用的简化 turn_state 没有该字段，
    则保持无输出而不把兼容逻辑扩大成 stdout 猜测。
    """

    emit = getattr(ctx.turn_state, "on_runtime_event", None)
    if emit is None:
        return
    emit(
        plan_confirmation_requested(
            f"{format_plan_for_display(plan)}\n按此计划执行吗？(y/n/输入修改意见):",
            metadata={"source": source},
        )
    )


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

    _emit_plan_confirmation(ctx, plan, source="plan_feedback")
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

    _emit_plan_confirmation(ctx, plan, source="step_feedback")
    return ""


def handle_user_input_step(user_input: str, ctx: ConfirmationContext) -> str:
    """Handle input when task status is awaiting_user_input.

    awaiting_user_input 现在有两种触发来源：
    1. **执行期求助**：模型在普通 step 里调用了 request_user_input 元工具。
       特征：state.task.pending_user_input_request 非 None。
       语义：当前 step 还没完成，用户只是为它补充信息。
       行为：写 step_input（含 question / why_needed），清 pending，status=running，
            **不调** advance_current_step_if_needed——回到 loop 让模型继续做当前 step。
    2. **collect_input / clarify 步骤收尾**：planner 提前规划出来的"问用户"步骤。
       特征：pending_user_input_request 为 None。
       语义：这一步的目标本就是问用户，用户回了就算这步完成。
       行为：原有逻辑——写 step_input，按 confirm_each_step 决定推进 / 等确认 / 收任务。
    """
    state = ctx.state
    turn_state = ctx.turn_state
    messages = state.conversation.messages
    current_plan = state.task.current_plan

    if not current_plan and not state.task.pending_user_input_request:
        # 没有 plan、也没有 runtime pending，说明无法判断用户在回答哪个等待点；
        # 这是损坏态，重置。若有 pending，则允许无 plan 的单步任务恢复 request_user_input。
        state.reset_task()
        clear_checkpoint()
        return ""

    # awaiting_user_input 的两种回复语义已经从 handler 抽到两层：
    # 1. input_resolution：只判断这是 collect_input 答案还是执行期求助答案；
    # 2. transitions：集中执行 append / clear pending / advance / save 等动作。
    # handler 只负责把 transition 结果接回主循环，后续更多事件也可以沿用这个边界。
    resolution = resolve_user_input(state, user_input)
    if resolution.kind == EMPTY_USER_INPUT:
        # 这是正式 User Input Layer 前的 runtime 防御：空输入没有产生有效事实，
        # 所以不能进入 transition/action 层，也就不能清 pending、推进 step 或保存 checkpoint。
        return "请输入有效内容，或输入取消/退出。"

    transition = apply_user_replied_transition(
        state=state,
        messages=messages,
        resolution=resolution,
    )
    if transition.should_continue_loop:
        return ctx.continue_fn(turn_state)
    return transition.reply


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
