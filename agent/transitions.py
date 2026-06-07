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

from collections.abc import Callable
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
from agent.planner import Plan
from agent.runtime_observer import log_actions, log_transition

EVENT_USER_REPLIED = "user.replied"

# ============================================================================
# Phase 1A: 通用 task status transition API
# ============================================================================


class TransitionEvent(Enum):
    """Phase 1A-3 使用的确定性 task status transition 事件。"""
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
    FEEDBACK_INTENT_AS_FEEDBACK = "feedback_intent.as_feedback"
    # Phase 2: human-waiting states
    USER_INPUT_RESOLVED = "user_input.resolved"
    STEP_CONFIRMATION_REQUIRED = "step_confirmation.required"
    USER_INPUT_REQUIRED = "user_input.required"
    # Phase 3: memory confirmation
    MEMORY_CONFIRMATION_REQUIRED = "memory_confirmation.required"
    MEMORY_CONFIRMATION_RESOLVED = "memory_confirmation.resolved"
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


@dataclass(frozen=True, slots=True)
class StepAdvanceDecision:
    """在任何 state mutation 前计算出的 step 推进决定。"""

    event: TransitionEvent
    next_step_index: int


# Phase 1A-3 transition table: 覆盖 confirmation、human waiting、memory、
# task runtime 与 planning 的确定性 transition。
# Phase 1B 新增 6 条 feedback_intent / origin_status restore / PLAN_GENERATED rule。
# <origin_status> sentinel 在 apply_task_transition() 中通过 resolve_origin_status()
# 解析，不在 table lookup 阶段处理。
_TRANSITION_TABLE: dict[tuple[str, TransitionEvent], TransitionRule] = {
    # === Phase 1A: plan/tool confirmation (4 rules) ===
    ("awaiting_plan_confirmation", TransitionEvent.USER_ACCEPTED): TransitionRule(
        to_status="running",
        checkpoint_action=CheckpointAction.SAVE,
    ),
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
    # === Phase 1B: feedback_intent request (2 rules) ===
    ("awaiting_plan_confirmation", TransitionEvent.FEEDBACK_INTENT_REQUIRED): TransitionRule(
        to_status="awaiting_feedback_intent",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    ("awaiting_step_confirmation", TransitionEvent.FEEDBACK_INTENT_REQUIRED): TransitionRule(
        to_status="awaiting_feedback_intent",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    # === Phase 1B: feedback_intent cancel / as_feedback restore (2 rules) ===
    # to_status="<origin_status>" 是 sentinel，apply_task_transition() 执行时
    # 通过 resolve_origin_status() 解析为实际 origin_status。
    ("awaiting_feedback_intent", TransitionEvent.USER_CANCELLED): TransitionRule(
        to_status="<origin_status>",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    ("awaiting_feedback_intent", TransitionEvent.FEEDBACK_INTENT_AS_FEEDBACK): TransitionRule(
        to_status="<origin_status>",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    # === Phase 1B: planner re-generate after feedback (2 rules) ===
    # 覆盖 plan/step confirmation 两种 origin_status restore 路径。
    ("awaiting_plan_confirmation", TransitionEvent.PLAN_GENERATED): TransitionRule(
        to_status="awaiting_plan_confirmation",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    ("awaiting_step_confirmation", TransitionEvent.PLAN_GENERATED): TransitionRule(
        to_status="awaiting_plan_confirmation",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    # === Phase 2: human-waiting states (5 rules) ===
    # apply_user_replied_transition 保持内部 checkpoint owner，因此两条 exit
    # rule 返回 NONE；其他 entry rule 由 caller 按结果保存一次。
    ("awaiting_user_input", TransitionEvent.USER_INPUT_RESOLVED): TransitionRule(
        to_status="running",
        checkpoint_action=CheckpointAction.NONE,
    ),
    (
        "awaiting_user_input",
        TransitionEvent.STEP_CONFIRMATION_REQUIRED,
    ): TransitionRule(
        to_status="awaiting_step_confirmation",
        checkpoint_action=CheckpointAction.NONE,
    ),
    ("running", TransitionEvent.STEP_CONFIRMATION_REQUIRED): TransitionRule(
        to_status="awaiting_step_confirmation",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    ("running", TransitionEvent.USER_INPUT_REQUIRED): TransitionRule(
        to_status="awaiting_user_input",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    # 无多步计划时 core 以 idle 直接进入单步 loop；request_user_input 仍是
    # 合法 human-waiting entry。这不是 origin restore allowlist。
    ("idle", TransitionEvent.USER_INPUT_REQUIRED): TransitionRule(
        to_status="awaiting_user_input",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    # === Phase 3: memory confirmation (3 rules) ===
    ("idle", TransitionEvent.MEMORY_CONFIRMATION_REQUIRED): TransitionRule(
        to_status="awaiting_user_input",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    ("running", TransitionEvent.MEMORY_CONFIRMATION_REQUIRED): TransitionRule(
        to_status="awaiting_user_input",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    (
        "awaiting_user_input",
        TransitionEvent.MEMORY_CONFIRMATION_RESOLVED,
    ): TransitionRule(
        to_status="<memory_origin_status>",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    # === Phase 3: task runtime (6 rules) ===
    # helper 只负责 transition + step index；checkpoint 由真实 caller
    # 在 message/control side effects 完成后按 SAVE/CLEAR 执行一次。
    ("running", TransitionEvent.STEP_ADVANCED): TransitionRule(
        to_status="running",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    ("running", TransitionEvent.TASK_COMPLETED): TransitionRule(
        to_status="done",
        checkpoint_action=CheckpointAction.CLEAR,
    ),
    ("awaiting_user_input", TransitionEvent.STEP_ADVANCED): TransitionRule(
        to_status="running",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    ("awaiting_user_input", TransitionEvent.TASK_COMPLETED): TransitionRule(
        to_status="done",
        checkpoint_action=CheckpointAction.CLEAR,
    ),
    ("awaiting_step_confirmation", TransitionEvent.STEP_ADVANCED): TransitionRule(
        to_status="running",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    ("awaiting_step_confirmation", TransitionEvent.TASK_COMPLETED): TransitionRule(
        to_status="done",
        checkpoint_action=CheckpointAction.CLEAR,
    ),
    # === Phase 3: planning entry (1 rule) ===
    ("idle", TransitionEvent.PLAN_GENERATED): TransitionRule(
        to_status="awaiting_plan_confirmation",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    # === Phase 3: tool confirmation entry (2 rules) ===
    # no-plan 主循环保持 idle，也允许直接进入工具确认。
    ("idle", TransitionEvent.TOOL_CONFIRMATION_REQUIRED): TransitionRule(
        to_status="awaiting_tool_confirmation",
        checkpoint_action=CheckpointAction.SAVE,
    ),
    ("running", TransitionEvent.TOOL_CONFIRMATION_REQUIRED): TransitionRule(
        to_status="awaiting_tool_confirmation",
        checkpoint_action=CheckpointAction.SAVE,
    ),
}


_ORIGIN_STATUS_SENTINEL = "<origin_status>"
_MEMORY_ORIGIN_STATUS_SENTINEL = "<memory_origin_status>"

# origin_status allowlist：仅这两个 confirmation 状态可从 feedback_intent 恢复。
_ORIGIN_STATUS_ALLOWLIST = frozenset({
    "awaiting_plan_confirmation",
    "awaiting_step_confirmation",
})


def resolve_origin_status(state: Any) -> str | None:
    """从 state.task.pending_user_input_request 读取并验证 origin_status。

    返回解析后的 status 字符串，或 None（无法解析/不在 allowlist 内）。
    caller 负责将 None 解释为 deny。
    """
    pending = getattr(state.task, "pending_user_input_request", None) or {}
    origin = pending.get("origin_status")
    if not isinstance(origin, str) or not origin.strip():
        return None
    if origin not in _ORIGIN_STATUS_ALLOWLIST:
        return None
    return origin


@dataclass(frozen=True, slots=True)
class MemoryOriginResolution:
    """memory confirmation 恢复目标的独立解析结果。"""

    allowed: bool
    target_status: str | None
    reason: str
    source_key: str | None


_MEMORY_AWAITING_KINDS = frozenset({
    "memory_confirmation",
    "memory_inline_confirmation",
})
_MEMORY_ORIGIN_ALLOWLIST = frozenset({"idle", "running"})


def resolve_memory_origin_status(state: Any) -> MemoryOriginResolution:
    """解析 memory confirmation 的 origin，不复用 generic feedback resolver。"""
    pending = getattr(state.task, "pending_user_input_request", None) or {}
    awaiting_kind = pending.get("awaiting_kind")
    if awaiting_kind not in _MEMORY_AWAITING_KINDS:
        return MemoryOriginResolution(
            allowed=False,
            target_status=None,
            reason="pending awaiting_kind is not a memory confirmation",
            source_key=None,
        )

    has_private = "_origin_status" in pending
    has_compat = "origin_status" in pending
    if has_private and has_compat and pending["_origin_status"] != pending["origin_status"]:
        return MemoryOriginResolution(
            allowed=False,
            target_status=None,
            reason="conflicting memory origin status keys",
            source_key=None,
        )

    if has_private:
        source_key = "_origin_status"
        origin = pending[source_key]
    elif has_compat:
        source_key = "origin_status"
        origin = pending[source_key]
    else:
        return MemoryOriginResolution(
            allowed=True,
            target_status="running",
            reason="legacy missing origin fallback",
            source_key="legacy_missing_fallback",
        )

    if not isinstance(origin, str) or not origin.strip():
        return MemoryOriginResolution(
            allowed=False,
            target_status=None,
            reason=f"{source_key} must be a non-empty string",
            source_key=source_key,
        )
    if origin not in _MEMORY_ORIGIN_ALLOWLIST:
        return MemoryOriginResolution(
            allowed=False,
            target_status=None,
            reason=f"memory origin status {origin!r} is not allowed",
            source_key=source_key,
        )
    return MemoryOriginResolution(
        allowed=True,
        target_status=origin,
        reason="memory origin status resolved",
        source_key=source_key,
    )


def _denied_transition(
    *,
    actual_from: str,
    request: TaskTransitionRequest,
    reason: str,
) -> TaskTransitionResult:
    """构造统一 denied 结果，确保 caller 永远不会收到 checkpoint 动作。"""
    return TaskTransitionResult(
        allowed=False,
        reason=reason,
        previous_status=actual_from,
        next_status=None,
        event=request.event,
        owner=request.owner,
        checkpoint_action=CheckpointAction.NONE,
    )


def _resolve_task_transition(
    state: Any,
    request: TaskTransitionRequest,
) -> TaskTransitionResult:
    """只读解析 transition，供 validate 和无 preflight 的 legacy apply 共用。"""
    actual_from = state.task.status

    if (
        request.expected_from_status is not None
        and request.expected_from_status != actual_from
    ):
        return _denied_transition(
            actual_from=actual_from,
            request=request,
            reason=(
                f"expected_from_status mismatch: "
                f"expected={request.expected_from_status!r}, "
                f"actual={actual_from!r}"
            ),
        )

    rule = _TRANSITION_TABLE.get((actual_from, request.event))
    if rule is None:
        return _denied_transition(
            actual_from=actual_from,
            request=request,
            reason=(
                f"no transition rule for "
                f"from_status={actual_from!r}, event={request.event.value!r}"
            ),
        )

    resolved_to_status = rule.to_status
    if resolved_to_status == _ORIGIN_STATUS_SENTINEL:
        origin = resolve_origin_status(state)
        if origin is None:
            return _denied_transition(
                actual_from=actual_from,
                request=request,
                reason=(
                    f"origin_status sentinel resolution failed: "
                    f"pending origin_status missing, empty, or not in allowlist "
                    f"{sorted(_ORIGIN_STATUS_ALLOWLIST)!r}"
                ),
            )
        resolved_to_status = origin
    elif resolved_to_status == _MEMORY_ORIGIN_STATUS_SENTINEL:
        memory_origin = resolve_memory_origin_status(state)
        if not memory_origin.allowed:
            return _denied_transition(
                actual_from=actual_from,
                request=request,
                reason=f"memory origin status resolution failed: {memory_origin.reason}",
            )
        assert memory_origin.target_status is not None
        resolved_to_status = memory_origin.target_status

    return TaskTransitionResult(
        allowed=True,
        reason="preflight validation passed",
        previous_status=actual_from,
        next_status=resolved_to_status,
        event=request.event,
        owner=request.owner,
        checkpoint_action=rule.checkpoint_action,
    )


def _verify_preflight_for_apply(
    state: Any,
    request: TaskTransitionRequest,
    preflight: TaskTransitionResult,
) -> TaskTransitionResult:
    """验证 preflight 仍属于同一 request，且权威状态没有变旧。"""
    actual_from = state.task.status

    if not preflight.allowed:
        return _denied_transition(
            actual_from=actual_from,
            request=request,
            reason=f"preflight denied: {preflight.reason}",
        )
    if preflight.event != request.event or preflight.owner != request.owner:
        return _denied_transition(
            actual_from=actual_from,
            request=request,
            reason="preflight does not match transition request event/owner",
        )
    if preflight.previous_status != actual_from:
        return _denied_transition(
            actual_from=actual_from,
            request=request,
            reason=(
                "stale preflight: "
                f"validated={preflight.previous_status!r}, actual={actual_from!r}"
            ),
        )
    if (
        request.expected_from_status is not None
        and request.expected_from_status != actual_from
    ):
        return _denied_transition(
            actual_from=actual_from,
            request=request,
            reason=(
                f"expected_from_status mismatch: "
                f"expected={request.expected_from_status!r}, "
                f"actual={actual_from!r}"
            ),
        )

    rule = _TRANSITION_TABLE.get((actual_from, request.event))
    if rule is None:
        return _denied_transition(
            actual_from=actual_from,
            request=request,
            reason=(
                f"no transition rule for "
                f"from_status={actual_from!r}, event={request.event.value!r}"
            ),
        )
    if preflight.checkpoint_action != rule.checkpoint_action:
        return _denied_transition(
            actual_from=actual_from,
            request=request,
            reason="preflight checkpoint_action does not match transition rule",
        )
    if preflight.next_status is None:
        return _denied_transition(
            actual_from=actual_from,
            request=request,
            reason="preflight resolved next_status is missing",
        )
    if (
        rule.to_status
        not in {_ORIGIN_STATUS_SENTINEL, _MEMORY_ORIGIN_STATUS_SENTINEL}
        and preflight.next_status != rule.to_status
    ):
        return _denied_transition(
            actual_from=actual_from,
            request=request,
            reason="preflight next_status does not match transition rule",
        )
    if (
        rule.to_status == _ORIGIN_STATUS_SENTINEL
        and preflight.next_status not in _ORIGIN_STATUS_ALLOWLIST
    ):
        return _denied_transition(
            actual_from=actual_from,
            request=request,
            reason="preflight resolved origin_status is not allowed",
        )
    if (
        rule.to_status == _MEMORY_ORIGIN_STATUS_SENTINEL
        and preflight.next_status not in _MEMORY_ORIGIN_ALLOWLIST
    ):
        return _denied_transition(
            actual_from=actual_from,
            request=request,
            reason="preflight resolved memory origin status is not allowed",
        )
    return preflight


def apply_task_transition(
    state: Any,
    request: TaskTransitionRequest,
    *,
    preflight: TaskTransitionResult | None = None,
) -> TaskTransitionResult:
    """验证并执行 task status transition。

    职责：
    - 从 state.task.status 读取权威 from_status
    - 若 expected_from_status 不匹配 → allowed=False，不修改状态
    - 查 _TRANSITION_TABLE 验证 (from_status, event)
    - 解析 generic/memory origin sentinel
    - 执行 state.task.status = rule.to_status
    - 返回 TaskTransitionResult 含 checkpoint_action

    不负责：
    - save_checkpoint / clear_checkpoint（caller 根据 checkpoint_action 执行）
    - LLM reasoning / plan generation / tool execution
    """
    resolution = (
        _verify_preflight_for_apply(state, request, preflight)
        if preflight is not None
        else _resolve_task_transition(state, request)
    )
    if not resolution.allowed:
        return resolution

    actual_from = resolution.previous_status
    resolved_to_status = resolution.next_status
    assert resolved_to_status is not None

    # 执行 transition
    state.task.status = resolved_to_status
    log_transition(
        from_state=actual_from,
        event_type=request.event.value,
        target_state=resolved_to_status,
    )

    return TaskTransitionResult(
        allowed=True,
        reason=f"transition {actual_from!r} + {request.event.value!r} → {resolved_to_status!r}",
        previous_status=actual_from,
        next_status=resolved_to_status,
        event=request.event,
        owner=request.owner,
        checkpoint_action=resolution.checkpoint_action,
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
    return _resolve_task_transition(state, request)


def _decide_current_step_advance(state: Any) -> StepAdvanceDecision:
    """只读计算当前步骤应推进还是完成，避免 denied 后留下部分 mutation。"""
    current_index = state.task.current_step_index
    current_plan = state.task.current_plan
    if not current_plan:
        return StepAdvanceDecision(
            event=TransitionEvent.TASK_COMPLETED,
            next_step_index=current_index,
        )

    # ActionPlan 的 node 推进由 scheduler 负责，不进入旧 Plan step 逻辑。
    if "plan_id" in current_plan and "nodes" in current_plan:
        return StepAdvanceDecision(
            event=TransitionEvent.TASK_COMPLETED,
            next_step_index=current_index,
        )

    plan = Plan.model_validate(current_plan)
    if current_index < len(plan.steps) - 1:
        return StepAdvanceDecision(
            event=TransitionEvent.STEP_ADVANCED,
            next_step_index=current_index + 1,
        )
    return StepAdvanceDecision(
        event=TransitionEvent.TASK_COMPLETED,
        next_step_index=current_index,
    )


def advance_current_step_if_needed(
    state: Any,
    *,
    owner: str,
) -> TaskTransitionResult:
    """先验证并应用 status transition，再提交 step index mutation。

    checkpoint 由真实 caller 在其 message/control side effects 完成后，按返回的
    checkpoint_action 显式执行一次。
    """
    decision = _decide_current_step_advance(state)
    request = TaskTransitionRequest(
        event=decision.event,
        owner=owner,
        expected_from_status=state.task.status,
    )
    preflight = validate_task_transition(state, request)
    if not preflight.allowed:
        return preflight

    transition = apply_task_transition(state, request, preflight=preflight)
    if transition.allowed:
        state.task.current_step_index = decision.next_step_index
    return transition


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
    save_checkpoint_fn: Callable[..., None] | None = None,
    task_boundary_callback: Callable[..., None] | None = None,
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
        step_input_payload = {
            "question": pending.get("question", ""),
            "why_needed": pending.get("why_needed", ""),
            "content": resolution.content,
        }
        request = TaskTransitionRequest(
            event=TransitionEvent.USER_INPUT_RESOLVED,
            owner="transitions.runtime_user_input_answer",
            expected_from_status="awaiting_user_input",
        )
        preflight = validate_task_transition(state, request)
        if not preflight.allowed:
            return TransitionResult(
                should_continue_loop=False,
                reply=f"[系统] 用户回复状态迁移失败: {preflight.reason}",
            )
        transition = apply_task_transition(
            state,
            request,
            preflight=preflight,
        )
        if not transition.allowed:
            return TransitionResult(
                should_continue_loop=False,
                reply=f"[系统] 用户回复状态迁移失败: {transition.reason}",
            )
        assert transition.checkpoint_action is CheckpointAction.NONE

        # request_user_input 回复落地在 Runtime transition 边界：InputIntent 已经在
        # adapter 层完成分类，RuntimeEvent 只负责输出提示，二者都不能进入
        # conversation.messages 或 checkpoint。这里写入的是给下一轮模型阅读的
        # step_input 文本事实，不是 Anthropic tool_result；元工具 tool_use 在
        # response_handlers 序列化时已被剔除，因此不能为了“配对”制造 ru_* 结果。
        # 若未来要改成 tool_result 语义，必须单独设计 tool_use_id 配对、checkpoint
        # migration 和旧会话恢复，不能在 transition 层扩大兼容补丁。
        append_control_event(messages, "step_input", step_input_payload)
        # pending 表示“系统正在等这一条用户答复”。答复已经写入 step_input 后，
        # 必须清掉 pending，否则下一轮用户输入还会被误认为是在回答旧问题。
        state.task.pending_user_input_request = None
        _save_checkpoint = save_checkpoint_fn
        if _save_checkpoint is None:
            from agent.runtime_integration.checkpoint_save import save_runtime_checkpoint
            _save_checkpoint = save_runtime_checkpoint
        _save_checkpoint(state, source="transitions.runtime_user_input_answer")
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
        step_input_payload = {"content": resolution.content}
        current_plan = state.task.current_plan or {}
        total_steps = len(current_plan.get("steps", []))
        is_last_step = state.task.current_step_index >= max(total_steps - 1, 0)

        if state.task.confirm_each_step and not is_last_step:
            request = TaskTransitionRequest(
                event=TransitionEvent.STEP_CONFIRMATION_REQUIRED,
                owner="transitions.collect_input_answer",
                expected_from_status="awaiting_user_input",
            )
            preflight = validate_task_transition(state, request)
            if not preflight.allowed:
                return TransitionResult(
                    should_continue_loop=False,
                    reply=f"[系统] 用户回复状态迁移失败: {preflight.reason}",
                )
            transition = apply_task_transition(
                state,
                request,
                preflight=preflight,
            )
            if not transition.allowed:
                return TransitionResult(
                    should_continue_loop=False,
                    reply=f"[系统] 用户回复状态迁移失败: {transition.reason}",
                )
            assert transition.checkpoint_action is CheckpointAction.NONE

            # 保留原有“每步确认”语义：collect_input 已完成，但是否进入下一步
            # 仍交给用户确认，所以这里不直接 advance。
            append_control_event(messages, "step_input", step_input_payload)
            _save_checkpoint = save_checkpoint_fn
            if _save_checkpoint is None:
                from agent.runtime_integration.checkpoint_save import save_runtime_checkpoint
                _save_checkpoint = save_runtime_checkpoint
            _save_checkpoint(state, source="transitions.collect_input_answer")
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

        transition = advance_current_step_if_needed(
            state,
            owner="transitions.collect_input_answer",
        )
        if not transition.allowed:
            return TransitionResult(
                should_continue_loop=False,
                reply=f"[系统] 用户回复状态迁移失败: {transition.reason}",
            )

        append_control_event(messages, "step_input", step_input_payload)

        if transition.checkpoint_action is CheckpointAction.CLEAR:
            # 最后一个 collect_input/clarify step 被用户答复后，任务可能直接完成。
            if task_boundary_callback is not None:
                task_boundary_callback(
                    reason="collect_input_task_completed",
                    source="transitions.collect_input_answer",
                )
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

        assert transition.checkpoint_action is CheckpointAction.SAVE
        _save_checkpoint = save_checkpoint_fn
        if _save_checkpoint is None:
            from agent.runtime_integration.checkpoint_save import save_runtime_checkpoint
            _save_checkpoint = save_runtime_checkpoint
        _save_checkpoint(state, source="transitions.collect_input_answer")
        log_transition(
            from_state="awaiting_user_input",
            event_type=EVENT_USER_REPLIED,
            target_state="running",
        )
        log_actions(["append_step_input", "advance_step", "save_checkpoint"])
        return TransitionResult(should_continue_loop=True)

    return TransitionResult(should_continue_loop=False)
