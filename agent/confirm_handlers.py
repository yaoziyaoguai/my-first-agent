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
from agent.display_events import (
    feedback_intent_requested,
    plan_confirmation_requested,
)
from agent.input_intents import classify_confirmation_response
from agent.input_resolution import EMPTY_USER_INPUT, resolve_user_input
from agent.planner import generate_plan, format_plan_for_display
from agent.runtime_events import (
    FeedbackIntentKind,
    PlanConfirmationKind,
    StepConfirmationKind,
    ToolConfirmationKind,
    ToolResultTransitionKind,
    feedback_intent_transition,
    plan_confirmation_transition,
    step_confirmation_transition,
    tool_confirmation_transition,
    tool_result_transition,
)
from agent.runtime_observer import log_event as _log_runtime_event
from agent.task_runtime import advance_current_step_if_needed
from agent.tool_executor import execute_pending_tool
from agent.transitions import apply_user_replied_transition


ContinueFn = Callable[[Any], str]
StartPlanningFn = Callable[[str, Any], str]


# v0.5 Phase 1 第五小步（H · confirmation observer evidence）：confirmation
# 决策的 observer 证据写入入口。落 `agent_log.jsonl`，与 docs/V0_5_OBSERVER_AUDIT.md
# §4 Gap G2 对应。
#
# 学习型注释：
# - **职责**：仅把"用户在 5 条 confirmation 链路上做出了什么 outcome"标签写入
#   runtime_observer.log_event。observer 是只读观测面，不是状态机的一部分。
# - **不负责**：(a) 不参与 transition 决策；(b) 不写 messages；(c) 不写
#   checkpoint；(d) 不投递 DisplayEvent；(e) 不读取真实 agent_log.jsonl 内容。
# - **失败隔离（产品契约）**：observer 写入抛任何异常都必须 swallow——confirmation
#   是用户决策的关键路径，绝不能因为日志层故障让 handler 卡死或返回值改变。
# - **payload 安全红线**：禁止把 user_input 原文 / feedback_text / tool_input
#   完整内容塞进 payload。允许：transition kind 字符串、origin_status、
#   tool_name、resolution_kind 等"枚举/标识"短字段。
# - **MVP 边界**：当前直接调 runtime_observer.log_event；不引入新 dataclass 也
#   不动 logger.log_event (legacy)。未来如需细化 schema（按 docs/V0_5_OBSERVER_AUDIT.md
#   G2 / G4 / G5 规划），请扩展本 helper 而不是把字面 log_event 调用散落到 5
#   个 handler 里。
# - **为什么不在 handler 内 inline `try/except`**：会污染 5 个 handler 的可读性、
#   重复 5 次"为什么 swallow"的注释、且未来要改 payload 字段命名时必须改 5 处。
# - **为什么不是完整 observer 系统**：本 slice 只接入面均衡化（H），不新增
#   ObserverEvent / 不接 TUI / 不做 _dispatch_pending_confirmation。
# - **artifact 排查路径**：tail -n 50 agent_log.jsonl | grep '"event_type":
#   "confirmation\.' 即可看到 confirmation 决策序列。
def _emit_confirmation_observer_event(
    event_type: str,
    *,
    payload: dict[str, Any] | None = None,
) -> None:
    """confirmation observer evidence 写入入口（详见模块顶部 H slice 注释）。"""

    try:
        _log_runtime_event(
            event_type,
            event_source="confirm_handlers",
            event_payload=payload or {},
            event_channel="confirmation",
        )
    except Exception:
        # observer 失败必须不影响 confirmation handler 的返回值与 state。
        # 这里 swallow 是产品契约——不允许把 logging 故障扩散到主流程。
        # 测试 test_observer_failure_does_not_break_handler 钉死该不变量。
        pass


# P1 反馈意图三选一固定文案。常量在模块级声明而不是写在 handler 里，方便测试
# 和 UI adapter 共享同一份选项标签；也避免后续在多处出现"看起来差不多但又微
# 妙不同"的提示文本。文案不依赖模型、不依赖任何启发式，是 Runtime 的产品契约。
FEEDBACK_INTENT_QUESTION = (
    "你刚才的输入既可能是对当前计划的修改意见，也可能是一个新任务，"
    "请告诉系统怎么处理。"
)
FEEDBACK_INTENT_WHY = (
    "Runtime 不允许在没有明确信号的情况下猜测意图（红线：禁止关键词/启发式/"
    "LLM 二次分类）。请用 1/2/3 显式选择。"
)
FEEDBACK_INTENT_OPTIONS: tuple[str, ...] = (
    "1. 当作对当前计划的修改意见（在原任务上重新规划）",
    "2. 切换为新任务（放弃当前计划）",
    "3. 取消（保持当前计划，不做任何事）",
)
# 精确匹配集合：任何不在此集合内的输入都按"模糊"处理，触发 RuntimeEvent 重发。
# 这是反 heuristic 的硬约束——不接受 "1." / "选 1" / "第一项" 等等价写法，
# 任何放宽都会让"猜测意图"的边界悄悄回流。如未来 UI 提供按钮，按钮回填的
# 字面值必须是 "1"/"2"/"3" 之一，而不是新增同义词。
_FEEDBACK_INTENT_VALID_CHOICES = frozenset({"1", "2", "3"})


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

    本轮（slash command 整体下线 + 启发式回退）边界说明：
    - 旧版本曾注入 `start_new_task_fn` 和浅层 feedback 二次分类
      (`classify_feedback_intent`)，让 awaiting_plan / awaiting_step 反馈分支
      自动判定"用户提出新任务"并切换。本轮整体回退该启发式：浅层关键词/字符
      重叠不允许用来推断用户意图；后续应通过显式 RuntimeEvent 用户确认流或
      正式状态机转移表达"切换任务"，而不是在分类器里悄悄放宽规则。
    - **保留**的结构化收益：feedback 分支只在本地组装 `revised_goal` 给 planner，
      绝不写回 `state.task.user_goal`，避免连续反馈让 user_goal 字符串无限膨胀。
    """

    state: Any
    turn_state: Any
    client: Any
    model_name: str
    continue_fn: ContinueFn
    # P1 注入：when 用户在 awaiting_feedback_intent 选 [2] 切新任务时，handler
    # 需要走与正常 chat() 入口完全同构的"reset_task + _run_planning_phase + 后续
    # 主循环"路径。把这个能力以函数引用的方式注入，避免 confirm_handlers 反向
    # 依赖 core.chat / _run_planning_phase。函数引用只在内存里传递，不写
    # checkpoint、不进 messages、不属于 schema。
    start_planning_fn: StartPlanningFn | None = None


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


def _request_feedback_intent_choice(
    ctx: ConfirmationContext, confirm: str, *, origin_status: str
) -> str:
    """切换到 awaiting_feedback_intent 子状态，等待用户三选一。

    架构边界（与设计稿 §4.2 对齐）：
    - **不**写 plan_feedback control event：归属未定时 messages 是 append-only，
      若先写则用户后续选 [2] 切新任务时旧反馈会污染新 planner 上下文，无法撤销。
    - **不**调 planner：避免无谓 LLM 调用，也防止旧 plan 被新话题污染。
    - 复用 `pending_user_input_request` 字段（仅通过 `awaiting_kind="feedback_intent"`
      区分新分流路径），避免新增 task 顶层字段——红线 #4：checkpoint schema
      顶层字段不变，旧 checkpoint 兼容自然成立。
    - 通过 `RuntimeEvent` 出口暴露三选一选项，**不**通过 stdout / print /
      conversation.messages。RuntimeEvent 不进 checkpoint、不进 messages、
      也不进 Anthropic API messages。
    """

    state = ctx.state
    pending = {
        "awaiting_kind": "feedback_intent",
        "question": FEEDBACK_INTENT_QUESTION,
        "why_needed": FEEDBACK_INTENT_WHY,
        "options": list(FEEDBACK_INTENT_OPTIONS),
        "context": "",
        "tool_use_id": "",
        "step_index": state.task.current_step_index,
        # 私有内部 key：仅供 handle_feedback_intent_choice 分流读取。
        # 它们存在于 pending 字典内部，不暴露给 _project_to_api 或 messages，
        # 也不会被 RuntimeEvent payload 序列化（feedback_intent_requested 只读
        # options/awaiting_kind/step_index）。
        "pending_feedback_text": confirm,
        "origin_status": origin_status,
    }
    state.task.pending_user_input_request = pending
    state.task.status = "awaiting_feedback_intent"
    save_checkpoint(state, source="confirm_handlers.feedback_intent_request")

    emit = getattr(ctx.turn_state, "on_runtime_event", None)
    if emit is not None:
        emit(feedback_intent_requested(pending))
    return ""


def handle_plan_confirmation(user_input: str, ctx: ConfirmationContext) -> str:
    """Handle input when task status is awaiting_plan_confirmation."""
    confirm = user_input.strip()
    state = ctx.state
    messages = state.conversation.messages

    response = _confirmation_response(confirm)

    if response == "accept":
        # v0.4 Phase 1 slice 6（plan 子切片）：把"用户接受 plan"的 Runtime
        # 意图通过 PlanConfirmationKind.PLAN_ACCEPTED 走 transition 表达；
        # transition 只描述意图（next_status="running" + should_checkpoint=True），
        # 实际 messages append / save_checkpoint / 继续主循环仍由本 handler
        # 完成，**不**改变行为，仅把"该向何处去"的命名集中到 runtime_events，
        # 与 ToolResult / ModelOutput 边界保持同一套 v0.4 方向。
        accept_transition = plan_confirmation_transition(
            PlanConfirmationKind.PLAN_ACCEPTED
        )
        append_control_event(messages, "plan_confirm_yes", {})
        if accept_transition.next_status:
            state.task.status = accept_transition.next_status
        if accept_transition.should_checkpoint:
            save_checkpoint(state)
        # v0.5 H · observer evidence：仅记录 outcome 标签，不改 state/messages/checkpoint。
        _emit_confirmation_observer_event(
            "confirmation.plan.accepted",
            payload={"intent": PlanConfirmationKind.PLAN_ACCEPTED.value},
        )
        return ctx.continue_fn(ctx.turn_state)

    if response == "reject":
        # v0.4 Phase 1 slice 6（plan 子切片）：把"用户拒绝 plan = 取消任务"
        # 的意图通过 PlanConfirmationKind.PLAN_REJECTED 表达。transition 不
        # 写新 checkpoint（task 即将清空），但提示 handler 仍要 reset_task
        # + clear_checkpoint —— 这两步是真实 durable mutation，本 slice
        # 不抽象掉，等后续 slice 把"负向落盘"也统一时再扩展 TransitionResult。
        reject_transition = plan_confirmation_transition(
            PlanConfirmationKind.PLAN_REJECTED
        )
        append_control_event(messages, "plan_confirm_no", {})
        messages.append({"role": "assistant", "content": "好的，已取消。"})
        # transition 明确不 checkpoint；handler 显式做反向清理。
        assert not reject_transition.should_checkpoint
        state.reset_task()
        clear_checkpoint()
        # v0.5 H · observer evidence：在 reset_task 之后记录，确保事件时序正确。
        _emit_confirmation_observer_event(
            "confirmation.plan.rejected",
            payload={"intent": PlanConfirmationKind.PLAN_REJECTED.value},
        )
        return "好的，已取消。"

    # P1：feedback 分支不再立刻调 planner，而是切到 awaiting_feedback_intent
    # 子状态等用户显式三选一。这样 awaiting_plan_confirmation 与
    # awaiting_step_confirmation 两个入口共用同一条分流（_request_feedback_intent_choice）。
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
        # v0.4 Phase 1 slice 6-b（step 子切片）：把"用户接受当前 step"的
        # Runtime 意图通过 step_confirmation_transition 表达。step accept
        # 有两种真实终态——继续下一步 vs 任务完成——必须在 advance 之后
        # 根据 status 选择对应 kind，因为 advance_current_step_if_needed
        # 才是真实状态变更的源头；transition 只描述"该选哪个意图"。
        append_control_event(messages, "step_confirm_yes", {})
        advance_current_step_if_needed(state)
        # 不要在这里手工 status = "running"：advance_current_step_if_needed
        # 已经按规则把 status 置为 "running"（还有下一步）或 "done"（最后一步）。
        # 手工覆盖会把 "done" 遮蔽成 "running"，让主循环再跑一次空转。
        if state.task.status == "done":
            # 最后一步的确认落在这里：清理任务后直接返回。
            # transition 只表明"任务自然完成"的 intent；不写新 checkpoint，
            # 由 handler 显式 reset_task + clear_checkpoint 完成反向落盘。
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
        # 中间步通过：transition 表达 should_checkpoint=True，handler 负责真实落盘。
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
        # v0.4 Phase 1 slice 6-b（step 子切片）：用户在 step 节点主动停止任务。
        # transition 表达 should_checkpoint=False，handler 仍负责 reset_task +
        # clear_checkpoint 的反向落盘；与 plan reject 同形但语义独立（一个是
        # plan 阶段取消，一个是已开始执行后的中途停止）。
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

    # P1：feedback 分支与 plan_confirmation 对称——切到 awaiting_feedback_intent
    # 子状态等用户三选一。仅在用户明确选 [1] 时才回写 plan_feedback control event
    # 并调 planner；选 [2] 走 reset_task + _run_planning_phase；选 [3] 完全无副作用。
    return _request_feedback_intent_choice(
        ctx, confirm, origin_status="awaiting_step_confirmation"
    )


def handle_feedback_intent_choice(user_input: str, ctx: ConfirmationContext) -> str:
    """awaiting_feedback_intent 状态下分流用户三选一。

    红线（与 docs/P1_TOPIC_SWITCH_PLAN.md §3 对齐）：
    - 仅识别精确匹配 "1" / "2" / "3"。任何其他输入（包括"看起来像反馈"的
      自然语言）只重发同一 RuntimeEvent，绝不通过关键词、字符重叠率、长度阈值
      或 LLM 二次分类来猜测意图。
    - "1" = 当作对当前计划的反馈：恢复 origin_status 视角，写一条 plan_feedback
      control event 到 messages（**这是 messages 唯一的写入时机**），调 planner
      用本地 revised_goal 重生成 plan。`state.task.user_goal` 保持不变，与
      hardcore #6 的不膨胀不变量保持一致。
    - "2" = 切换为新任务：reset_task + clear_checkpoint + start_planning_fn(
      pending_feedback_text)，与正常 chat() 新任务入口完全同构。新 plan 的
      user_goal == 新话题原文，不与旧目标拼接。
    - "3" = 取消：恢复 origin_status，清 pending，**不**写任何 control event，
      **不**调 planner。完全无副作用。
    - 模糊输入：状态 / pending / messages 完全不变，仅再次 emit
      EVENT_FEEDBACK_INTENT_REQUESTED。
    """

    state = ctx.state
    pending = state.task.pending_user_input_request or {}
    choice_raw = (user_input or "").strip()

    if choice_raw not in _FEEDBACK_INTENT_VALID_CHOICES:
        # 模糊输入：不动状态、不动 pending、不动 messages，只重发提示。
        # 这是反 heuristic 红线最关键的执行点——任何"看起来像 X"的猜测都会
        # 在这里被无条件拒绝。
        # v0.4 Phase 1 slice 6-e：transition 边界只声明意图（不写 checkpoint，
        # 不清 pending）。AMBIGUOUS 的 should_checkpoint=False 是关键契约，
        # 防止未来"统一动作"重构把未决意图持久化到 checkpoint，让下次 resume
        # 从一个本不该存在的中间态恢复。
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
        # cancel：复原 origin_status，清 pending，不写 messages，不调 planner。
        # 这条路径**不能**写 plan_feedback——否则就破坏了"取消 = 完全无副作用"
        # 的产品语义，并让 messages 残留一条永远无法撤销的反馈记录。
        # v0.4 Phase 1 slice 6-e：transition 声明 should_checkpoint=True
        # （origin_status 必须落盘，否则下次 resume 把 awaiting_feedback_intent
        # 当残留态恢复）+ clear_pending_user_input=True；handler 仍负责真实 mutation。
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
        # as_feedback：恢复 origin 视角后再走原 feedback 路径。
        # v0.4 Phase 1 slice 6-e：transition 声明 next_status=
        # "awaiting_plan_confirmation"（planner 成功路径）+ should_checkpoint=True
        # + clear_pending_user_input=True。handler 仍负责 LLM 调用、messages 写入、
        # current_plan 赋值与 emit。revised_goal 仅作 planner 入参，绝不回写
        # state.task.user_goal（hardcore #6 不变量，已被 source-level 测试钉死）。
        as_feedback_transition = feedback_intent_transition(
            FeedbackIntentKind.AS_FEEDBACK
        )
        assert as_feedback_transition.should_checkpoint
        assert as_feedback_transition.clear_pending_user_input
        state.task.pending_user_input_request = None
        state.task.status = origin_status
        # ★ messages 唯一写入时机：分流确认归属为"反馈"之后。
        append_control_event(messages, "plan_feedback", {"feedback": feedback_text})
        # 本地 revised_goal 仅用于喂 planner，绝不写回 state.task.user_goal。
        # 这是 c252795 / hardcore #6 保留的结构化收益：user_goal 忠实记录用户
        # 最初的任务，反馈只是 planning 的临时上下文。
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

    # choice_raw == "2": as_new_task —— 与正常 chat() 新任务入口完全同构。
    # reset_task() 把 user_goal/current_plan/pending/log 等全部清掉；clear_checkpoint
    # 抹掉旧任务持久化痕迹；start_planning_fn 走 _run_planning_phase，由它把
    # state.task.user_goal 直接赋值为新话题原文（不与旧目标拼接）。
    # v0.4 Phase 1 slice 6-e：transition 声明 should_checkpoint=False
    # （由 clear_checkpoint 抹旧 + start_planning_fn 内部决定新 ckpt 节奏）+
    # clear_pending_user_input=True（reset_task 间接清）。reset_task 必须严格
    # 先于 start_planning_fn（已被契约测试钉死）。
    as_new_task_transition = feedback_intent_transition(
        FeedbackIntentKind.AS_NEW_TASK
    )
    assert not as_new_task_transition.should_checkpoint
    assert as_new_task_transition.clear_pending_user_input
    if ctx.start_planning_fn is None:
        # 防御：注入未生效。降级为 reset 让用户重新发起，避免悄悄丢话题。
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
            # v0.4 Phase 1 slice 6-c（tool 子切片）：用户已批准但执行抛异常。
            # transition 表达 should_checkpoint=True + clear_pending_tool=False
            # （**保留** pending_tool 以便人工排查，是 confirm_handlers L444
            # 注释明确的真实诊断需求）；handler 仍负责实际写 tool_result
            # 占位、status mutation、save_checkpoint，不让 transition 自己
            # mutate 状态以保持 single source of truth。
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

        # v0.4 Phase 1 slice 6-c（tool 子切片）：用户批准且工具成功执行。
        # transition 表达 should_checkpoint=True + clear_pending_tool=True，
        # handler 负责实际清 pending_tool（保持 L458 single source of truth，
        # 由 test_tool_accept_success_path_clears_pending_tool_via_handler 钉死）
        # 与 save_checkpoint。clear_pending_tool=True 只是 intent 标记，**不**
        # 代表 transition 自己 mutate state；这一边界后续 slice 不能漂移。
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

    # 未执行分支（n / feedback）也要清空 pending_tool 并为悬空 tool_use 补占位结果。
    # v0.4 Phase 1 先把 user rejection 映射成 TransitionResult：handler 仍按
    # 既有协议写 tool_result/control event，但清 pending / checkpoint / display
    # 语义从临时 transition 结果读取，避免继续把状态动作散在多处注释里。
    transition = tool_result_transition(ToolResultTransitionKind.USER_REJECTION)
    if transition.clear_pending_tool:
        state.task.pending_tool = None

    # M7-B 真实修复：旧实现用户拒绝后没有任何 display event，CLI 终端
    # 用户只看到自己输入的 'n' 然后是下一轮的 chat 输出，无法清晰确认
    # 「我的拒绝是否被系统接受」。这里 emit 一个 tool.user_rejected 事件，
    # 与 tool.rejected（安全检查）/tool.failed（工具运行报错）区分语义，
    # 都映射到 EVENT_TOOL_RESULT_VISIBLE 让 UI 一致显示。
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
