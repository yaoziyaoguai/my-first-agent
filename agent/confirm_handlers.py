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
from agent.display_events import control_message, plan_confirmation_requested
from agent.input_intents import classify_confirmation_response, classify_feedback_intent
from agent.input_resolution import EMPTY_USER_INPUT, resolve_user_input
from agent.planner import generate_plan, format_plan_for_display
from agent.task_runtime import advance_current_step_if_needed
from agent.tool_executor import execute_pending_tool
from agent.transitions import apply_user_replied_transition


ContinueFn = Callable[[Any], str]
StartNewTaskFn = Callable[[str, Any], str]


def _confirmation_response(confirm: str) -> str:
    """把确认输入委托给 InputIntent 分类层。

    confirm_handlers 是状态推进层，不应该继续维护自己的 yes/no/中文词表；否则
    Textual/simple CLI adapter 和 Runtime handler 会再次出现字符串判断分叉。这里仅
    读取分类结果，然后保留原有 plan/step/tool 状态推进、checkpoint 保存、
    tool_use_id 配对和 tool_result placeholder 语义。InputIntent 本身不会写入
    conversation.messages，也不会混入 RuntimeEvent 或 Anthropic API messages。
    """

    return classify_confirmation_response(confirm)


@dataclass(slots=True)
class ConfirmationContext:
    """Dependencies needed by confirmation handlers.

    Grouping these dependencies keeps handler signatures readable while keeping
    the handlers free of core.py globals.

    `start_new_task_fn` 是 awaiting_plan / awaiting_step 反馈分支用来路由“话题
    切换”的回调：它由 core.chat() 注入，封装了 reset_task + planning_phase +
    main loop 的标准“开新任务”路径。把这个能力抽成回调，而不是让 handler 直接
    import core.py，是为了维持现有架构边界——confirm_handlers 是状态推进层，
    不应该回头依赖 main loop 的具体实现。该回调可选；老调用方（例如直接
    针对 handle_user_input_step 的单测）可以不传，handler 只在真正检测到话题
    切换时才调用它。它**不会**写 messages、不会改 checkpoint schema、不会改变
    tool_use_id / tool_result placeholder / request_user_input 的语义边界。
    """

    state: Any
    turn_state: Any
    client: Any
    model_name: str
    continue_fn: ContinueFn
    start_new_task_fn: StartNewTaskFn | None = None


def _try_route_topic_switch(
    user_input: str,
    ctx: ConfirmationContext,
    *,
    source: str,
) -> str | None:
    """如果 feedback 输入显然是新任务，转入 start_new_task_fn 而不是当作 plan feedback。

    这里是 awaiting_plan_confirmation / awaiting_step_confirmation 反馈分支上的
    分流点。它做且仅做三件事：

    1. 调用 `classify_feedback_intent` 这个**结构化二次分类**：判定原则只有两条
       结构性条件——明确的“新任务祈使前缀”和与当前 plan 词表的零字符重叠。
       这避免了用反馈关键词黑名单去“否定”输入的补丁式做法；判定本身不读
       state 状态机字段，不会改 conversation.messages、checkpoint、API messages、
       tool_use_id 配对、request_user_input 语义。
    2. 命中 `new_task_topic_switch` 时，发一个 `control_message` RuntimeEvent 让
       UI 显式告知用户“已切到新任务”。RuntimeEvent 是 Runtime -> UI 输出边界，
       刻意不写进 conversation.messages，避免模型把这条 UI 文案当成事实再演绎一遍。
    3. 调用注入的 `start_new_task_fn`，由它负责 reset_task + planning_phase +
       main loop 的标准入口。这里不直接调 core.py，是为了保持 confirm_handlers
       不反向依赖主循环实现。

    返回 None 表示“按原 feedback 流程继续”。返回字符串表示切换路径已经处理完
    本轮，调用方应当直接 return 这个回复。当 ctx 没有提供 `start_new_task_fn` 时
    （旧测试 / 兼容路径），即使疑似切换也只能保守走原 feedback 路径——这避免了
    改变现有调用方语义。
    """

    state = ctx.state
    intent = classify_feedback_intent(user_input, plan=state.task.current_plan)
    if intent != "new_task_topic_switch":
        return None

    if ctx.start_new_task_fn is None:
        return None

    emit = getattr(ctx.turn_state, "on_runtime_event", None)
    if emit is not None:
        emit(
            control_message(
                "[系统] 检测到你提出了一个新任务，已结束当前计划并切换到新任务。",
                metadata={
                    "source": source,
                    "feedback_intent": intent,
                },
            )
        )

    # 清理当前任务和 checkpoint，把切换语义写干净。这里调用现有 reset_task /
    # clear_checkpoint，不引入新的 schema 字段，也不改变 task 状态机定义。
    state.reset_task()
    clear_checkpoint()
    return ctx.start_new_task_fn(user_input, ctx.turn_state)


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

    response = _confirmation_response(confirm)

    if response == "accept":
        append_control_event(messages, "plan_confirm_yes", {})
        state.task.status = "running"
        save_checkpoint(state)
        return ctx.continue_fn(ctx.turn_state)

    if response == "reject":
        append_control_event(messages, "plan_confirm_no", {})
        messages.append({"role": "assistant", "content": "好的，已取消。"})
        state.reset_task()
        clear_checkpoint()
        return "好的，已取消。"

    append_control_event(messages, "plan_feedback", {"feedback": confirm})

    # 话题切换分流：如果用户输入显然是新任务，转入 start_new_task_fn 而不是
    # 把它拼进 user_goal。分流由 _try_route_topic_switch 完成；它只在确实切换
    # 时返回字符串回复，否则返回 None。
    switched = _try_route_topic_switch(confirm, ctx, source="plan_feedback")
    if switched is not None:
        return switched

    # 反馈分支只在本地组装 revised_goal 给 planner，**不再**写回 state.task.user_goal。
    # 旧实现会把每次反馈拼进 user_goal，导致连续反馈时字符串无限膨胀（plan/step
    # feedback 单向累加 bug）。架构上 user_goal 应该忠实记录“用户最初提出的任务”，
    # 反馈只是 planning 的临时上下文；plan 重生成本来就能在 planner 端融合反馈，
    # 不需要把累积态塞进 task 状态。这样改不动 checkpoint schema，不影响
    # tool_use_id / tool_result placeholder / request_user_input 语义。
    revised_goal = f"{state.task.user_goal}\n\n用户对计划的修改意见：{confirm}"

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

    response = _confirmation_response(confirm)

    if response == "accept":
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

    if response == "reject":
        append_control_event(messages, "step_confirm_no", {})
        messages.append({"role": "assistant", "content": "好的，当前任务已停止。"})
        state.reset_task()
        clear_checkpoint()
        return "好的，当前任务已停止。"

    append_control_event(messages, "plan_feedback", {"feedback": confirm})

    # awaiting_step 同样需要分流话题切换：用户在“是否进入下一步”阶段直接抛出
    # 一个无关新任务时，不应把它拼成 step feedback 喂回 planner。详见
    # handle_plan_confirmation 同名分支的注释。
    switched = _try_route_topic_switch(confirm, ctx, source="step_feedback")
    if switched is not None:
        return switched

    # step 反馈分支同样只在本地组装 revised_goal，**不再**写回 state.task.user_goal。
    # 见 handle_plan_confirmation 中的注释：单向累加会让 user_goal 字符串随反馈
    # 次数线性膨胀，每次 planning 都被旧反馈污染。fix 的边界：只动 planner 输入
    # 的临时上下文，state 字段语义保持“用户最初提出的任务”。
    revised_goal = (
        f"{state.task.user_goal}\n\n"
        f"用户在步骤确认阶段的补充意见：{confirm}"
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
            if response == "reject"
            else f"[系统] 用户未批准该工具，改为反馈意见：{confirm}",
        )

    if response == "reject":
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
