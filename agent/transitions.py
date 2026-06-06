"""显式 transition 层：task status 状态迁移的统一入口。

本模块提供两层 transition：
1. 通用 task status transition API（Phase 1A 新增）：
   - TransitionEvent / CheckpointAction / TransitionRule
   - TaskTransitionRequest / TaskTransitionResult
   - apply_task_transition()
2. 已有 user_replied transition（保持向后兼容）：
   - TransitionResult / apply_user_replied_transition()

apply_task_transition() 是 Phase 1A 新增的唯一合法 state.task.status 写入点。
caller 根据返回的 TaskTransitionResult.checkpoint_action 自行执行
save_checkpoint / clear_checkpoint，transition layer 不自动操作 checkpoint。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from agent import checkpoint
from agent.conversation_events import append_control_event
from agent.input_resolution import (
    COLLECT_INPUT_ANSWER,
    RUNTIME_USER_INPUT_ANSWER,
    InputResolution,
)
from agent.runtime_observer import log_actions, log_transition
from agent.task_runtime import advance_current_step_if_needed

EVENT_USER_REPLIED = "user.replied"

# ============================================================================
# Phase 1A: 通用 task status transition API
# ============================================================================


class TransitionEvent(Enum):
    """确定性 task status transition 事件。

    Phase 1A 只需要 USER_ACCEPTED / USER_REJECTED / USER_FEEDBACK。
    其余事件为后续 Phase 预留，不在 Phase 1A transition table 中。
    """
    USER_ACCEPTED = "user.accepted"
    USER_REJECTED = "user.rejected"
    USER_FEEDBACK = "user.feedback"
    # 后续 Phase 预留
    USER_CANCELLED = "user.cancelled"
    PLAN_GENERATED = "plan.generated"
    STEP_ADVANCED = "step.advanced"
    TASK_COMPLETED = "task.completed"
    TOOL_CONFIRMATION_REQUIRED = "tool.confirmation_required"
    FEEDBACK_INTENT_REQUIRED = "feedback_intent.required"
    EXECUTION_FAILED = "execution.failed"
    INCONSISTENCY_DETECTED = "inconsistency.detected"


class CheckpointAction(Enum):
    """transition 后 caller 应执行的 checkpoint 操作。"""
    NONE = "none"
    SAVE = "save"
    CLEAR = "clear"


@dataclass(frozen=True, slots=True)
class TransitionRule:
    """单条 transition rule：(from_status, event) → to_status + checkpoint 行为。

    checkpoint_action 绑定到 rule 而非 event，因为同一 event 在不同
    from_status 下的 checkpoint 行为可能不同（如 USER_REJECTED 对于
    plan confirmation vs tool confirmation）。
    """
    to_status: str
    checkpoint_action: CheckpointAction


@dataclass(frozen=True, slots=True)
class TaskTransitionRequest:
    """task status transition 请求。

    caller 不传权威 from_status — apply_task_transition() 内部从
    state.task.status 读取权威值。expected_from_status 是可选断言，
    不匹配时 transition 被 deny。
    """
    event: TransitionEvent
    owner: str
    expected_from_status: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class TaskTransitionResult:
    """task status transition 执行结果。

    这是独立新类型，不复用/扩展已有 transitions.TransitionResult
    或 runtime_events.TransitionResult。两者保持原有语义不变。
    """
    allowed: bool
    reason: str
    previous_status: str
    next_status: str | None
    event: TransitionEvent
    owner: str
    checkpoint_action: CheckpointAction


# Phase 1A transition table：只覆盖 awaiting_plan_confirmation 和
# awaiting_tool_confirmation 的确定性 transition。
# feedback_intent / origin_status restore 不进 Phase 1A。
_TRANSITION_TABLE: dict[tuple[str, TransitionEvent], TransitionRule] = {
    # plan confirmation accept
    ("awaiting_plan_confirmation", TransitionEvent.USER_ACCEPTED): TransitionRule(
        to_status="running",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    # tool confirmation — 四条路径全部 → running + SAVE
    ("awaiting_tool_confirmation", TransitionEvent.USER_ACCEPTED): TransitionRule(
        to_status="running",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    ("awaiting_tool_confirmation", TransitionEvent.USER_REJECTED): TransitionRule(
        to_status="running",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    ("awaiting_tool_confirmation", TransitionEvent.USER_FEEDBACK): TransitionRule(
        to_status="running",
        checkpoint_action=CheckpointAction.SAVE,
    ),
}


def apply_task_transition(
    state: Any,
    request: TaskTransitionRequest,
) -> TaskTransitionResult:
    """验证并执行 task status transition。

    职责：
    - 从 state.task.status 读取权威 from_status
    - 若 expected_from_status 不匹配 → allowed=False，不修改状态
    - 查 _TRANSITION_TABLE 验证 (from_status, event)
    - 执行 state.task.status = rule.to_status
    - 返回 TaskTransitionResult 含 checkpoint_action

    不负责：
    - save_checkpoint / clear_checkpoint（caller 根据 checkpoint_action 执行）
    - LLM reasoning / plan generation / tool execution
    """
    actual_from = state.task.status

    # 可选断言：caller 预期当前状态
    if (
        request.expected_from_status is not None
        and request.expected_from_status != actual_from
    ):
        return TaskTransitionResult(
            allowed=False,
            reason=(
                f"expected_from_status mismatch: "
                f"expected={request.expected_from_status!r}, "
                f"actual={actual_from!r}"
            ),
            previous_status=actual_from,
            next_status=None,
            event=request.event,
            owner=request.owner,
            checkpoint_action=CheckpointAction.NONE,
        )

    # 查 transition table
    key = (actual_from, request.event)
    rule = _TRANSITION_TABLE.get(key)
    if rule is None:
        return TaskTransitionResult(
            allowed=False,
            reason=(
                f"no transition rule for "
                f"from_status={actual_from!r}, event={request.event.value!r}"
            ),
            previous_status=actual_from,
            next_status=None,
            event=request.event,
            owner=request.owner,
            checkpoint_action=CheckpointAction.NONE,
        )

    # 执行 transition
    state.task.status = rule.to_status
    log_transition(
        from_state=actual_from,
        event_type=request.event.value,
        target_state=rule.to_status,
    )

    return TaskTransitionResult(
        allowed=True,
        reason=f"transition {actual_from!r} + {request.event.value!r} → {rule.to_status!r}",
        previous_status=actual_from,
        next_status=rule.to_status,
        event=request.event,
        owner=request.owner,
        checkpoint_action=rule.checkpoint_action,
    )


def validate_task_transition(
    state: Any,
    request: TaskTransitionRequest,
) -> TaskTransitionResult:
    """只读验证 transition 是否合法，不修改 state.task.status。

    用于 caller 必须在执行副作用（工具调用、clear pending、append result、
    save checkpoint 等）之前确认 transition 合法的场景。
    验证通过后 caller 仍需调用 apply_task_transition() 执行实际 mutation。
    """
    actual_from = state.task.status

    if (
        request.expected_from_status is not None
        and request.expected_from_status != actual_from
    ):
        return TaskTransitionResult(
            allowed=False,
            reason=(
                f"expected_from_status mismatch: "
                f"expected={request.expected_from_status!r}, "
                f"actual={actual_from!r}"
            ),
            previous_status=actual_from,
            next_status=None,
            event=request.event,
            owner=request.owner,
            checkpoint_action=CheckpointAction.NONE,
        )

    key = (actual_from, request.event)
    rule = _TRANSITION_TABLE.get(key)
    if rule is None:
        return TaskTransitionResult(
            allowed=False,
            reason=(
                f"no transition rule for "
                f"from_status={actual_from!r}, event={request.event.value!r}"
            ),
            previous_status=actual_from,
            next_status=None,
            event=request.event,
            owner=request.owner,
            checkpoint_action=CheckpointAction.NONE,
        )

    return TaskTransitionResult(
        allowed=True,
        reason="preflight validation passed",
        previous_status=actual_from,
        next_status=rule.to_status,
        event=request.event,
        owner=request.owner,
        checkpoint_action=rule.checkpoint_action,
    )


@dataclass(frozen=True, slots=True)
class TransitionResult:
    """transition 执行后的控制结果。

    - should_continue_loop：告诉 handler 是否要立刻回到 agent 主循环继续执行。
      runtime_user_input_answer 和普通 collect_input 推进后通常需要继续。
    - reply：如果不继续 loop，需要返回给 CLI 的控制文案，例如等待 step 确认、
      或任务完成提示。

    target_status 目前不单独作为字段返回，因为第一阶段 transition 已直接修改
    `state.task.status`，handler 只需要知道“继续 loop 还是把 reply 返回用户”。
    """

    should_continue_loop: bool
    reply: str = ""


def apply_user_replied_transition(
    *,
    state: Any,
    messages: list[dict[str, Any]],
    resolution: InputResolution,
) -> TransitionResult:
    """执行 `awaiting_user_input + USER_REPLIED` 的显式状态转移。

    两条路径的语义不同：
    - `collect_input_answer`：用户回答的是计划中的信息收集/澄清步骤。这个 step
      的目标就是获得用户信息，所以答复写入 messages 后应推进当前 step。
    - `runtime_user_input_answer`：用户回答的是执行中途 request_user_input 或
      fallback 暂停的问题。它只是给当前 step 补上下文，step 是否完成仍需要模型
      后续调用 mark_step_complete，因此不能推进 current_step_index。

    两条路径都要保存 checkpoint，因为用户回复后 state 和 conversation.messages
    都发生了关键变化；此时如果进程中断，恢复后必须能看到这次答复。
    """
    if resolution.kind == RUNTIME_USER_INPUT_ANSWER:
        pending = resolution.pending_user_input_request or {}
        # request_user_input 回复落地在 Runtime transition 边界：InputIntent 已经在
        # adapter 层完成分类，RuntimeEvent 只负责输出提示，二者都不能进入
        # conversation.messages 或 checkpoint。这里写入的是给下一轮模型阅读的
        # step_input 文本事实，不是 Anthropic tool_result；元工具 tool_use 在
        # response_handlers 序列化时已被剔除，因此不能为了“配对”制造 ru_* 结果。
        # 若未来要改成 tool_result 语义，必须单独设计 tool_use_id 配对、checkpoint
        # migration 和旧会话恢复，不能在 transition 层扩大兼容补丁。
        append_control_event(messages, "step_input", {
            "question": pending.get("question", ""),
            "why_needed": pending.get("why_needed", ""),
            "content": resolution.content,
        })
        # pending 表示“系统正在等这一条用户答复”。答复已经写入 step_input 后，
        # 必须清掉 pending，否则下一轮用户输入还会被误认为是在回答旧问题。
        state.task.pending_user_input_request = None
        state.task.status = "running"
        checkpoint.save_checkpoint(state, source="transitions.runtime_user_input_answer")
        log_transition(
            from_state="awaiting_user_input",
            event_type=EVENT_USER_REPLIED,
            target_state="running",
        )
        log_actions([
            "append_step_input_with_question",
            "clear_pending_user_input",
            "save_checkpoint",
        ])
        return TransitionResult(should_continue_loop=True)

    if resolution.kind == COLLECT_INPUT_ANSWER:
        # collect_input/clarify 本身就是计划里的一个 step；用户答复就是这个 step
        # 的产出，因此写入普通 step_input 后可以进入步骤推进逻辑。
        append_control_event(messages, "step_input", {"content": resolution.content})
        current_plan = state.task.current_plan or {}
        total_steps = len(current_plan.get("steps", []))
        is_last_step = state.task.current_step_index >= max(total_steps - 1, 0)

        if state.task.confirm_each_step and not is_last_step:
            # 保留原有“每步确认”语义：collect_input 已完成，但是否进入下一步
            # 仍交给用户确认，所以这里不直接 advance。
            state.task.status = "awaiting_step_confirmation"
            checkpoint.save_checkpoint(state, source="transitions.collect_input_answer")
            log_transition(
                from_state="awaiting_user_input",
                event_type=EVENT_USER_REPLIED,
                target_state="awaiting_step_confirmation",
            )
            log_actions(["append_step_input", "save_checkpoint"])
            return TransitionResult(
                should_continue_loop=False,
                reply="\n[请确认: y 进入下一步 / n 停止任务 / 输入意见以重规划]",
            )

        advance_current_step_if_needed(state)

        if state.task.status == "done":
            # 最后一个 collect_input/clarify step 被用户答复后，任务可能直接完成。
            checkpoint.clear_checkpoint()
            state.reset_task()
            log_transition(
                from_state="awaiting_user_input",
                event_type=EVENT_USER_REPLIED,
                target_state="done",
            )
            log_actions([
                "append_step_input",
                "advance_step",
                "clear_checkpoint",
                "reset_task",
            ])
            return TransitionResult(
                should_continue_loop=False,
                reply="好的，任务已完成。",
            )

        checkpoint.save_checkpoint(state, source="transitions.collect_input_answer")
        log_transition(
            from_state="awaiting_user_input",
            event_type=EVENT_USER_REPLIED,
            target_state="running",
        )
        log_actions(["append_step_input", "advance_step", "save_checkpoint"])
        return TransitionResult(should_continue_loop=True)

    return TransitionResult(should_continue_loop=False)
