"""confirmation 模块的共享基础设施：ConfirmationContext、observer 证据写入、
feedback intent 常量、通用 helper——不拥有任何具体的 handler 逻辑。
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent.checkpoint import save_checkpoint
from agent.display_events import (
    feedback_intent_requested,
    plan_confirmation_requested,
)
from agent.input_intents import classify_confirmation_response
from agent.pending_requests import PendingUserInputRequest
from agent.planner import format_plan_for_display
from agent.runtime_observer import log_event as _log_runtime_event
from agent.transitions import (
    CheckpointAction,
    TaskTransitionRequest,
    TransitionEvent,
    apply_task_transition,
)

ContinueFn = Callable[[Any], str]
StartPlanningFn = Callable[[str, Any], str]


# =============================================================================
# confirmation observer evidence 写入入口
# =============================================================================
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
# - **artifact 排查路径**：tail -n 50 agent_log.jsonl | grep '"event_type":
#   "confirmation\.' 即可看到 confirmation 决策序列。
def _emit_confirmation_observer_event(
    event_type: str,
    *,
    payload: dict[str, Any] | None = None,
) -> None:
    """confirmation observer evidence 写入入口（详见模块顶部 H slice 注释）。"""
    with contextlib.suppress(Exception):
        _log_runtime_event(
            event_type,
            event_source="confirm_handlers",
            event_payload=payload or {},
            event_channel="confirmation",
        )


# =============================================================================
# P1 反馈意图三选一固定文案
# =============================================================================
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
_FEEDBACK_INTENT_VALID_CHOICES = frozenset({"1", "2", "3"})


# =============================================================================
# 通用 helper
# =============================================================================

def _confirmation_response(confirm: str) -> str:
    """把确认输入委托给 InputIntent 分类层。"""
    return classify_confirmation_response(confirm)


# =============================================================================
# ConfirmationContext
# =============================================================================

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
    start_planning_fn: StartPlanningFn | None = None
    memory_runtime: Any | None = None
    dispatcher: Any | None = None


# =============================================================================
# 内部共享 helper（供 plan / step handler 使用）
# =============================================================================

def _emit_plan_confirmation(ctx: ConfirmationContext, plan: Any, *, source: str) -> None:
    """把重规划后的确认提示投影到 UI。"""
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
    """
    state = ctx.state

    result = apply_task_transition(state, TaskTransitionRequest(
        event=TransitionEvent.FEEDBACK_INTENT_REQUIRED,
        owner="confirmation.dispatcher.feedback_intent_request",
        expected_from_status=origin_status,
    ))
    if not result.allowed:
        return f"[系统] feedback_intent 状态迁移失败: {result.reason}"

    pending: PendingUserInputRequest = {
        "awaiting_kind": "feedback_intent",
        "question": FEEDBACK_INTENT_QUESTION,
        "why_needed": FEEDBACK_INTENT_WHY,
        "options": list(FEEDBACK_INTENT_OPTIONS),
        "context": "",
        "tool_use_id": "",
        "step_index": state.task.current_step_index,
        "pending_feedback_text": confirm,
        "origin_status": origin_status,
    }
    state.task.pending_user_input_request = pending
    if result.checkpoint_action == CheckpointAction.SAVE:
        save_checkpoint(state, source="confirm_handlers.feedback_intent_request")

    emit = getattr(ctx.turn_state, "on_runtime_event", None)
    if emit is not None:
        emit(feedback_intent_requested(pending))
    return ""
