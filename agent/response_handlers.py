"""Response handlers for model responses.

These helpers sit at the boundary between raw model responses and the agent
runtime. They parse stop-reason-specific model responses and delegate actual
execution to lower-level modules.
"""

from __future__ import annotations

from typing import Any

from agent.checkpoint import clear_checkpoint
from agent.conversation_events import append_tool_result, has_tool_result
from agent.display_events import tool_blocked_event as _tool_blocked_event
from agent.display_events import user_input_requested
from agent.model_output_resolution import (
    EVENT_MODEL_TEXT_REQUESTED_USER_INPUT,
    EVENT_RUNTIME_NO_PROGRESS,
    RuntimeEvent,
    resolve_end_turn_output,
    resolve_max_tokens_output,
    resolve_tool_use_block,
)
from agent.pending_requests import PendingUserInputRequest
from agent.planner import Plan
from agent.runtime_integration.checkpoint_save import save_runtime_checkpoint
from agent.runtime_observer import log_event
from agent.task_runtime import (
    USER_INPUT_STEP_TYPES,
    advance_current_step_if_needed,
    is_current_step_completed,
)
from agent.tool_executor import (
    AWAITING_USER,
    FORCE_STOP,
    TRANSITION_DENIED,
    execute_single_tool,
)
from agent.tool_registry import is_meta_tool
from agent.transitions import (
    CheckpointAction,
    TaskTransitionRequest,
    TaskTransitionResult,
    TransitionEvent,
    apply_task_transition,
    validate_task_transition,
)

MAX_TOOL_CALLS_PER_TURN = 50
MAX_REPEATED_TOOL_INPUTS = 3
TEXT_PREVIEW_LIMIT = 120


def save_checkpoint(state: Any, source: str | None = None, **kwargs: Any) -> None:
    """Compatibility patch symbol; production still goes through the gateway."""
    save_runtime_checkpoint(state, source=source, **kwargs)


def _record_runtime_evidence(
    operation: str, status: str, safe_summary: str,
    *, metadata: dict | None = None,
) -> None:
    """把 Runtime branch point 事件送入统一 evidence recorder。

    Runtime branch point（loop.stop / model.response / progress / end_turn）
    必须并行写入 evidence，不能只依赖 legacy log_event。
    """
    try:
        from agent.evidence_recorder import record_evidence

        record_evidence(
            subsystem="runtime",
            operation=operation,
            phase="end" if status in ("ok", "skipped") else "error",
            status=status,
            safe_summary=safe_summary,
            metadata=metadata or {},
        )
    except Exception:
        pass


def _log_model_event(event: RuntimeEvent, *, event_channel: str | None = None) -> None:
    """把 ModelOutputResolution 的结果送进 observer。

    这是纯观测接入点：只打印模型输出事件，不改变工具执行、状态转移、messages
    或 checkpoint 行为。
    """
    log_event(
        event.event_type,
        event_source=event.event_source,
        event_payload=event.event_payload,
        event_channel=event_channel,
    )


def _current_step_fields(state: Any) -> dict[str, Any]:
    """提取当前步骤的短观测字段，不改变 Runtime 状态。"""

    fields: dict[str, Any] = {
        "task_status": getattr(state.task, "status", None),
        "current_step_index": getattr(state.task, "current_step_index", None),
        "loop_iterations": getattr(state.task, "loop_iterations", None),
        "consecutive_end_turn_without_progress": getattr(
            state.task,
            "consecutive_end_turn_without_progress",
            None,
        ),
        "has_pending_tool": bool(getattr(state.task, "pending_tool", None)),
        "has_pending_user_input": bool(
            getattr(state.task, "pending_user_input_request", None)
        ),
    }
    if state.task.current_plan:
        try:
            plan = Plan.model_validate(state.task.current_plan)
            idx = state.task.current_step_index
            if 0 <= idx < len(plan.steps):
                step = plan.steps[idx]
                fields["current_step_title"] = step.title
                fields["current_step_type"] = step.step_type
        except Exception:
            fields["current_step_title"] = "[invalid_plan]"
    return fields


def _text_preview(text: str) -> str:
    """返回短文本预览，避免日志写入完整 assistant 输出。"""

    compact = " ".join(text.split())
    if len(compact) <= TEXT_PREVIEW_LIMIT:
        return compact
    return compact[:TEXT_PREVIEW_LIMIT] + "..."


def _apply_preflight_transition(
    state: Any,
    request: TaskTransitionRequest,
) -> TaskTransitionResult:
    """先只读验证，再用同一个 resolution 执行 transition。"""
    preflight = validate_task_transition(state, request)
    if not preflight.allowed:
        return preflight
    return apply_task_transition(state, request, preflight=preflight)


def _deactivate_task_boundary(state: Any, *, reason: str, source: str) -> None:
    from agent.runtime_integration.skill_lifecycle import (
        deactivate_active_skill_for_task_boundary,
    )

    deactivate_active_skill_for_task_boundary(
        state,
        reason=reason,
        source=source,
    )


def _record_end_turn_observation(observation: dict[str, Any]) -> None:
    """记录 end_turn 观测；需要 transition 的分支只能在 apply allowed 后调用。"""
    log_event(
        "model.response_received",
        event_source="model",
        event_payload=observation,
        event_channel="end_turn",
    )
    _record_runtime_evidence(
        "model_response", "ok",
        f"model_response channel=end_turn stop_reason={observation.get('stop_reason')}",
        metadata=observation,
    )
    log_event(
        "model.end_turn",
        event_source="model",
        event_payload=observation,
        event_channel="end_turn",
    )


def _response_observation(
    response: Any,
    *,
    state: Any,
    extract_text_fn,
) -> dict[str, Any]:
    """把模型 response 压缩成可排查 stop_reason 的短字段。"""

    text = extract_text_fn(response.content)
    tool_names = [
        block.name
        for block in response.content
        if getattr(block, "type", None) == "tool_use"
    ]
    return {
        **_current_step_fields(state),
        "stop_reason": getattr(response, "stop_reason", None),
        "text_length": len(text),
        "text_preview": _text_preview(text),
        "tool_use_names": tool_names,
        "called_mark_step_complete": "mark_step_complete" in tool_names,
        "called_request_user_input": "request_user_input" in tool_names,
        "has_tool_use": bool(tool_names),
        "has_meta_tool": any(is_meta_tool(name) for name in tool_names),
    }


def _serialize_assistant_content(content_blocks: list[Any]) -> list[dict[str, Any]]:
    """把模型返回的 content blocks 序列化为可持久化的 dict 列表。

    关键点：
    - 必须保留普通 tool_use 块（含 id/name/input），否则下一轮消息里的
      tool_result 找不到对应的 tool_use_id，Anthropic API 会直接报错。
    - **元工具的 tool_use 块必须剔除**——元工具是系统控制信号，不属于业务对话
      上下文，也没有配对的 tool_result 会写 messages（见 tool_executor 里的
      meta 分支），若不剔除就会残留"挂空" tool_use，下一轮 API 调用报 400。
    """
    serialized: list[dict[str, Any]] = []
    for block in content_blocks:
        btype = getattr(block, "type", None)
        if btype == "text":
            text = getattr(block, "text", "") or ""
            if text:
                serialized.append({"type": "text", "text": text})
        elif btype == "tool_use":
            if is_meta_tool(block.name):
                # 元工具：从 assistant content 里剔除；不让它进 state.conversation.messages。
                continue
            serialized.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
        # 其他类型（thinking 等）暂不持久化；缺失也不会破坏 tool_use/tool_result 配对。
    return serialized


def _append_assistant_response(messages: list[dict[str, Any]], response: Any) -> None:
    """把 assistant 响应以完整 content blocks 形式追加到 messages。"""
    blocks = _serialize_assistant_content(response.content)
    if not blocks:
        # 完全空响应时放一个占位 text，避免 messages 出现空 content。
        blocks = [{"type": "text", "text": "[空响应]"}]
    messages.append({
        "role": "assistant",
        "content": blocks,
    })


def handle_tool_use_response(
    response: Any,
    *,
    state: Any,
    turn_state: Any,
    messages: list[dict[str, Any]],
    extract_text_fn,
    runtime_action_dispatcher: Any | None = None,
    runtime_identity: Any = None,
) -> str | None:
    """Handle a model response whose stop_reason is tool_use.

    Responsibilities:
    - append assistant content blocks (含 tool_use) into conversation messages
    - extract tool_use blocks
    - enforce per-turn tool call limit
    - delegate single-tool execution to ToolRuntimeMediator (方案 2) 或
      回退到 tool_executor（兼容旧路径）
    - translate tool executor sentinel values into loop-level results
    - 遇到 AWAITING_USER / FORCE_STOP 时，为剩余未处理的 tool_use 写占位
      tool_result，保证下一次调用 API 时 tool_use/tool_result 配对完整。
    """
    observation = _response_observation(
        response,
        state=state,
        extract_text_fn=extract_text_fn,
    )
    log_event(
        "model.response_received",
        event_source="model",
        event_payload=observation,
        event_channel="tool_use",
    )
    _record_runtime_evidence(
        "model_response", "ok",
        f"model_response channel=tool_use stop_reason={observation.get('stop_reason')}"
        f" tools={observation.get('tool_use_names')}",
        metadata=observation,
    )
    log_event(
        "model.tool_use",
        event_source="model",
        event_payload=observation,
        event_channel="tool_use",
    )

    _append_assistant_response(messages, response)

    state.task.consecutive_max_tokens = 0
    # 任何工具调用（业务或元）都视为"有效推进"，清零 end_turn 兜底计数器。
    # 这一步必须在 for 循环之前——即使本轮里调的工具触发了 AWAITING_USER /
    # FORCE_STOP / awaiting_user_input 提前 return，模型确实"动起来了"，
    # 死循环兜底就不该把它算成"无进展"。
    state.task.consecutive_end_turn_without_progress = 0

    tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
    # 元工具不算"业务工具调用"——既不吃 per-turn 配额，也不需要在 messages 里
    # 配 tool_result；`_fill_placeholder_results` 若作用到元工具会产生"挂空"
    # tool_result（对应的 tool_use 已被序列化时剔除），破坏 API 协议。
    business_blocks = [b for b in tool_use_blocks if not is_meta_tool(b.name)]
    state.task.tool_call_count += len(business_blocks)

    if state.task.tool_call_count > MAX_TOOL_CALLS_PER_TURN:
        _fill_placeholder_results(messages, business_blocks, reason="工具调用次数超限，未执行")
        _deactivate_task_boundary(
            state,
            reason="tool_call_limit_exceeded",
            source="response_handlers.handle_tool_use_response",
        )
        clear_checkpoint()
        state.reset_task()
        return "工具调用次数过多，请简化任务或分步执行。"

    turn_context: dict[str, Any] = {}

    # Loop 1.3 方案 2：构造 ToolRuntimeMediator 作为 dispatcher 中介层。
    # mediator 共享 turn_context（execute_single_tool 通过它传递执行结果）。
    # Loop 2.2b: skill_allowed_tools 从 lifecycle 传入 mediator，
    # 由 ToolGateHandler 在 execute_single_tool 之前执行工具约束检查。
    # Phase 4 (Plan 3): allowed_tools 来源从 _active_skill dict 迁移到 lifecycle。
    if runtime_action_dispatcher is not None:
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        _skill_at: frozenset[str] | None = None
        try:
            from agent.logger import get_runtime_session_id
            from agent.skill_system.lifecycle import get_default_lifecycle
            _sid = getattr(runtime_identity, "session_id", "") or get_runtime_session_id()
            _lc = get_default_lifecycle(_sid)
            _tools = _lc.get_allowed_tools()
            _skill_at = _tools if _tools else None
        except ImportError:
            _skill_at = None

        _mediator = ToolRuntimeMediator(
            runtime_action_dispatcher,
            state=state,
            turn_state=turn_state,
            turn_context=turn_context,
            messages=messages,
            skill_allowed_tools=_skill_at,
            identity=runtime_identity,
        )
        # P1-2: 将 mediator 挂到 turn_state，使 handle_tool_confirmation
        # 能通过 mediator.mediate_pending() 走统一工具执行路径。
        turn_state._tool_mediator = _mediator
    else:
        _mediator = None
        turn_state._tool_mediator = None

    for idx, block in enumerate(tool_use_blocks):
        # 先把模型输出归类成事件并记录下来；后续仍沿用原来的
        # execute_single_tool 路径。这样第一阶段只做到"事件可见"，不迁移执行层。
        model_event = resolve_tool_use_block(block)
        _log_model_event(model_event, event_channel="tool_use")

        if not is_meta_tool(block.name):
            failed_same_input_count = sum(
                1
                for entry in state.task.tool_execution_log.values()
                if entry.get("tool") == block.name
                and entry.get("input") == block.input
                and entry.get("status") == "failed"
            )
            if failed_same_input_count:
                _fill_placeholder_results(
                    messages,
                    [block],
                    reason=(
                        "同一工具和同一输入此前已失败，本轮不会再次请求用户确认或执行；"
                        "请换用其他来源、使用已有信息继续，或说明该来源不可用"
                    ),
                )
                continue

            same_input_count = sum(
                1
                for entry in state.task.tool_execution_log.values()
                if entry.get("tool") == block.name
                and entry.get("input") == block.input
                and entry.get("status") == "executed"
            )
            if same_input_count >= MAX_REPEATED_TOOL_INPUTS:
                remaining_business = [b for b in tool_use_blocks[idx:] if not is_meta_tool(b.name)]
                _fill_placeholder_results(
                    messages,
                    remaining_business,
                    reason=(
                        "检测到同一工具和同一输入被重复请求多次，"
                        "为避免无限重试，本轮未执行"
                    ),
                )
                _deactivate_task_boundary(
                    state,
                    reason="repeated_tool_input_limit",
                    source="response_handlers.handle_tool_use_response",
                )
                clear_checkpoint()
                state.reset_task()
                return "检测到重复工具调用过多，任务已停止。请调整目标或换一种信息来源。"

        # Loop 1.3 方案 2：通过 ToolRuntimeMediator 走 dispatcher 中介路径；
        # mediator 为 None 时回退到直接调用 execute_single_tool（向后兼容）。
        if _mediator is not None and not is_meta_tool(block.name):
            result = _mediator.mediate(block)
        else:
            result = execute_single_tool(
                block,
                state=state,
                turn_state=turn_state,
                turn_context=turn_context,
                messages=messages,
            )
        if result == TRANSITION_DENIED:
            return "[系统] request_user_input 状态迁移失败，本轮已停止且未提交等待状态。"
        if result == FORCE_STOP:
            # Loop 4.2: 用户可见 tool blocked 事件
            if turn_state.on_runtime_event is not None:
                turn_state.on_runtime_event(
                    _tool_blocked_event(
                        block.name,
                        "被安全策略拒绝执行（TOOL_GATE rejected），具体原因见上方工具消息",
                    ),
                )
            remaining_business = [b for b in tool_use_blocks[idx + 1:] if not is_meta_tool(b.name)]
            _fill_placeholder_results(
                messages,
                remaining_business,
                reason=(
                    "前序工具被安全策略阻断。本工具未被执行，"
                    "不会在后续自动重试——如有需要请换用其他方式"
                ),
            )
            # UMT-P2-001: 不在这里 return 停止循环。
            # _handle_blocked 已将拒绝原因写入 messages（tool_result），
            # 模型在下一轮会看到拒绝反馈并尝试替代方案。
            # 将 stop_reason 记录到 tool_execution_log 供审计，但不阻断循环。
            state.task.tool_execution_log.setdefault("_last_block_reason", {})
            state.task.tool_execution_log["_last_block_reason"] = {
                "tool": block.name,
                "reason": "被安全策略拒绝执行（TOOL_GATE rejected）。"
                          "具体拒绝原因已写入上方工具消息，模型将尝试替代方案。",
            }
            # consume block (already handled by mediator) and continue to next
        if result == AWAITING_USER:
            log_event(
                "loop.stop",
                event_source="runtime",
                event_payload={
                    **_current_step_fields(state),
                    "reason_for_stop": "awaiting_tool_or_user_confirmation",
                    "pending_tool_name": (
                        state.task.pending_tool or {}
                    ).get("tool"),
                    "pending_user_input_kind": (
                        state.task.pending_user_input_request or {}
                    ).get("awaiting_kind"),
                },
                event_channel="tool_use",
            )
            _record_runtime_evidence(
                "loop", "stop",
                "awaiting_tool_or_user_confirmation",
                metadata={
                    "pending_tool_name": (
                        state.task.pending_tool or {}
                    ).get("tool"),
                    "pending_user_input_kind": (
                        state.task.pending_user_input_request or {}
                    ).get("awaiting_kind"),
                },
            )
            remaining_business = [b for b in tool_use_blocks[idx + 1:] if not is_meta_tool(b.name)]
            _fill_placeholder_results(
                messages,
                remaining_business,
                reason=(
                    "前序工具正在等待用户确认，本工具本轮未被执行，"
                    "且不会在后续自动重试——请不要在下一轮响应里再次调用同一工具,"
                    "等前序工具完成后根据实际结果再决定是否需要它"
                ),
            )
            return ""

        # request_user_input 元工具触发的执行期求助：tool_executor 已经把 status
        # 切到 awaiting_user_input 并写好 pending_user_input_request。
        # 这里负责本轮收尾：
        # - 给本轮剩余未执行的"业务" tool_use 补占位 tool_result，避免 API 协议悬空
        # - 把 question / why_needed / options 通过 RuntimeEvent 投影给用户
        # - 跳出 loop 等用户输入，避免本轮里继续误执行剩余工具或走 _maybe_advance_step
        if state.task.status == "awaiting_user_input":
            remaining_business = [b for b in tool_use_blocks[idx + 1:] if not is_meta_tool(b.name)]
            _fill_placeholder_results(
                messages,
                remaining_business,
                reason=(
                    "前序工具调用了 request_user_input 暂停了执行，本工具本轮未运行；"
                    "等用户回复后再决定是否需要它"
                ),
            )
            pending = state.task.pending_user_input_request or {}
            emit = getattr(turn_state, "on_runtime_event", None)
            if emit is not None:
                # request_user_input 是 Runtime 控制信号：pending 写在 TaskState，
                # tool_use/tool_result 不进入 Anthropic messages。这里仅把等待问题投影
                # 到 UI，不能清 pending、不能推进状态机，也不能把 observer/debug 日志
                # 混进 RuntimeEvent。
                emit(user_input_requested(pending))
            return ""

    # 元工具触发的步骤推进：本轮里若模型调用了 mark_step_complete 且分值达阈值，
    # 立刻在 tool_use 这一轮就处理"步骤推进 / 等用户确认 / 任务完成"——避免再多
    # 一次没必要的 API 调用，也避免 messages 出现"assistant(text) 后没 tool_result"
    # 的协议软违规（元工具不写 tool_result，若不在此处收尾会让模型空跑一轮）。
    has_meta_call = any(is_meta_tool(b.name) for b in tool_use_blocks)
    if has_meta_call:
        return _maybe_advance_step(state)

    return None


def _maybe_advance_step(state: Any) -> str | None:
    """若当前步骤已完成（mark_step_complete 分值达阈值），处理推进 / 等确认 / 任务完成。

    返回值：
    - None：步骤未完成，调用方继续 loop
    - "\n[请确认: ...]"：进入下一步前需要用户确认（多步且非最后一步）
    - ""：任务完成或单步推进完成（无需用户确认）
    """
    before_index = getattr(state.task, "current_step_index", None)
    if not is_current_step_completed(state):
        log_event(
            "runtime.no_progress_detected",
            event_source="runtime",
            event_payload={
                **_current_step_fields(state),
                "no_progress_reason": "mark_step_complete_missing_or_below_threshold",
                "mark_step_complete_called": False,
            },
            event_channel="progress",
        )
        _record_runtime_evidence(
            "progress", "no_progress",
            "mark_step_complete missing or below threshold",
            metadata={"_current_step_index": getattr(state.task, "current_step_index", None)},
        )
        return None

    if state.task.current_plan:
        # 每步确认分支先完成 transition preflight；denied 时不能先写 observer、
        # checkpoint 或 step index。其他 step advance/done 路径由共享 helper 处理。
        _plan_dict = state.task.current_plan
        if "plan_id" not in _plan_dict or "nodes" not in _plan_dict:
            plan = Plan.model_validate(state.task.current_plan)
            idx = state.task.current_step_index
            if idx < len(plan.steps) - 1 and state.task.confirm_each_step:
                request = TaskTransitionRequest(
                    event=TransitionEvent.STEP_CONFIRMATION_REQUIRED,
                    owner="response_handlers.maybe_advance_step",
                    expected_from_status="running",
                )
                transition = _apply_preflight_transition(state, request)
                if not transition.allowed:
                    return f"[系统] step confirmation 状态迁移失败: {transition.reason}"
                assert transition.checkpoint_action is CheckpointAction.SAVE

                log_event(
                    "runtime.progress_detected",
                    event_source="runtime",
                    event_payload={
                        **_current_step_fields(state),
                        "current_step_index_before": before_index,
                        "mark_step_complete_called": True,
                    },
                    event_channel="progress",
                )
                _record_runtime_evidence(
                    "progress", "detected",
                    "step progress detected via mark_step_complete",
                    metadata={"step_index_before": before_index},
                )
                save_checkpoint(state)
                return "\n[请确认: y 进入下一步 / n 停止任务 / 输入意见以重规划]"

    transition = advance_current_step_if_needed(
        state,
        owner="response_handlers.maybe_advance_step",
    )
    if not transition.allowed:
        return f"[系统] step advance 状态迁移失败: {transition.reason}"

    log_event(
        "runtime.progress_detected",
        event_source="runtime",
        event_payload={
            **_current_step_fields(state),
            "current_step_index_before": before_index,
            "mark_step_complete_called": True,
        },
        event_channel="progress",
    )
    _record_runtime_evidence(
        "progress", "detected",
        "step progress detected via mark_step_complete",
        metadata={"step_index_before": before_index},
    )

    log_event(
        "runtime.progress_applied",
        event_source="runtime",
        event_payload={
            **_current_step_fields(state),
            "current_step_index_before": before_index,
            "current_step_index_after": state.task.current_step_index,
            "should_continue_loop": state.task.status != "done",
        },
        event_channel="progress",
    )
    _record_runtime_evidence(
        "progress", "applied",
        f"step advanced {before_index} → {state.task.current_step_index}"
        f" done={state.task.status == 'done'}",
        metadata={
            "step_index_before": before_index,
            "step_index_after": state.task.current_step_index,
            "task_status": state.task.status,
        },
    )

    if transition.checkpoint_action is CheckpointAction.CLEAR:
        state.conversation.messages.append({
            "role": "assistant",
            "content": [{"type": "text", "text": "好的，任务已完成。"}],
        })
        _deactivate_task_boundary(
            state,
            reason="task_completed",
            source="response_handlers.maybe_advance_step",
        )
        clear_checkpoint()
        state.reset_task()
        return "好的，任务已完成。"

    assert transition.checkpoint_action is CheckpointAction.SAVE
    save_checkpoint(state)
    return None


def _fill_placeholder_results(
    messages: list[dict[str, Any]],
    blocks: list[Any],
    *,
    reason: str,
) -> None:
    """为未执行的 tool_use 补占位 tool_result，保证 API 配对合法。"""
    for b in blocks:
        if has_tool_result(messages, b.id):
            continue
        append_tool_result(messages, b.id, f"[系统] {reason}。")


def handle_max_tokens_response(
    response: Any,
    *,
    state: Any,
    turn_state: Any,
    messages: list[dict[str, Any]],
    extract_text_fn,
    max_consecutive_max_tokens: int,
) -> str | None:
    """Handle a model response whose stop_reason is max_tokens.

    This preserves the core.py behavior:
    - keep the assistant content blocks in conversation messages
    - increment consecutive max_tokens count on state.task (持久化)
    - stop when the configured threshold is exceeded
    """
    observation = _response_observation(
        response,
        state=state,
        extract_text_fn=extract_text_fn,
    )
    log_event(
        "model.response_received",
        event_source="model",
        event_payload=observation,
        event_channel="max_tokens",
    )
    _record_runtime_evidence(
        "model_response", "ok",
        f"model_response channel=max_tokens stop_reason={observation.get('stop_reason')}",
        metadata=observation,
    )
    log_event(
        "model.max_tokens",
        event_source="model",
        event_payload=observation,
        event_channel="max_tokens",
    )
    _append_assistant_response(messages, response)
    _log_model_event(resolve_max_tokens_output(), event_channel="stop_reason")

    state.task.consecutive_max_tokens += 1

    if state.task.consecutive_max_tokens >= max_consecutive_max_tokens:
        return "模型连续多次达到最大输出长度，任务已停止。请缩小任务范围后重试。"

    return None


def handle_end_turn_response(
    response: Any,
    *,
    state: Any,
    turn_state: Any,
    messages: list[dict[str, Any]],
    extract_text_fn,
) -> str | None:
    """Handle a model response whose stop_reason is end_turn.

    This keeps end-turn behavior outside core.py while preserving state-driven
    execution semantics:
    - append assistant content blocks into conversation messages
    - detect whether current step completed
    - move to awaiting_step_confirmation when there are more steps
    - advance / clear checkpoint when the task is done

    **返回约定**：不返回模型正文。正文已经由 `_call_model` 在流式阶段逐字 print。
    返回值只包含"**控制型 UI 文字**"——比如 "本步骤已完成。回复 y 继续下一步"
    这种给用户的提示。普通 end_turn 返回空串，main_loop 的 `if reply: print(reply)`
    判假不再打印，避免正文重复输出两次。
    """
    observation = _response_observation(
        response,
        state=state,
        extract_text_fn=extract_text_fn,
    )
    text_content = extract_text_fn(response.content)
    step_completed_before = is_current_step_completed(state)
    needs_collect_input = False
    if state.task.current_plan:
        # ActionPlan 格式（plan_id + nodes）不进入旧 Plan step 逻辑，
        # 避免 Plan.model_validate 对 ActionPlan dict 报 Field required。
        _plan_dict = state.task.current_plan
        if "plan_id" not in _plan_dict or "nodes" not in _plan_dict:
            plan = Plan.model_validate(state.task.current_plan)
            idx = state.task.current_step_index
            current_step = plan.steps[idx] if 0 <= idx < len(plan.steps) else None
            needs_collect_input = bool(
                current_step and current_step.step_type in USER_INPUT_STEP_TYPES
            )

    projected_no_progress = state.task.consecutive_end_turn_without_progress + 1
    model_event = None
    pending_request: PendingUserInputRequest | None = None
    if (
        not needs_collect_input
        and state.task.current_plan
        and state.task.status == "running"
        and not step_completed_before
    ):
        model_event = resolve_end_turn_output(text_content, projected_no_progress)
        if (
            model_event is not None
            and model_event.event_type in (
                EVENT_MODEL_TEXT_REQUESTED_USER_INPUT,
                EVENT_RUNTIME_NO_PROGRESS,
            )
        ):
            awaiting_kind = (
                "fallback_question"
                if model_event.event_type == EVENT_MODEL_TEXT_REQUESTED_USER_INPUT
                else "no_progress"
            )
            pending_request = {
                "awaiting_kind": awaiting_kind,
                "question": (
                    text_content[:500] if text_content
                    else "[模型 end_turn 但未声明步骤完成；请你介入]"
                ),
                "why_needed": (
                    "模型未调用 request_user_input；为防 loop 死循环，"
                    "系统强制暂停等你回应"
                ),
                "options": [],
                "context": "",
                "tool_use_id": "",
                "step_index": state.task.current_step_index,
            }

    if needs_collect_input or pending_request is not None:
        request = TaskTransitionRequest(
            event=TransitionEvent.USER_INPUT_REQUIRED,
            owner=(
                "response_handlers.collect_input_required"
                if needs_collect_input
                else "response_handlers.end_turn_user_input_required"
            ),
            expected_from_status="running",
        )
        transition = _apply_preflight_transition(state, request)
        if not transition.allowed:
            return f"[系统] user input 状态迁移失败: {transition.reason}"
        assert transition.checkpoint_action is CheckpointAction.SAVE

        # transition 已成功后才提交 message/counter/pending/observer/checkpoint。
        _append_assistant_response(messages, response)
        state.task.consecutive_max_tokens = 0

        if needs_collect_input:
            _record_end_turn_observation(observation)
            save_checkpoint(state)
            return "\n[请补充上面的信息后继续]"

        state.task.consecutive_end_turn_without_progress = projected_no_progress
        state.task.pending_user_input_request = pending_request
        _record_end_turn_observation(observation)
        log_event(
            "runtime.end_turn_without_completion",
            event_source="runtime",
            event_payload={
                **_current_step_fields(state),
                "had_text_output": bool(text_content),
                "had_tool_use": False,
                "mark_step_complete_called": False,
                "request_user_input_called": False,
            },
            event_channel="assistant_text",
        )
        _record_runtime_evidence(
            "end_turn", "no_completion",
            f"end_turn without step completion (consecutive={projected_no_progress})",
            metadata={
                "had_text_output": bool(text_content),
                "consecutive_end_turn_without_progress": projected_no_progress,
            },
        )
        assert model_event is not None
        _log_model_event(model_event, event_channel="assistant_text")
        log_event(
            "runtime.no_progress_detected",
            event_source="runtime",
            event_payload={
                **_current_step_fields(state),
                "no_progress_reason": model_event.event_type,
                "text_preview": _text_preview(text_content),
            },
            event_channel="assistant_text",
        )
        _record_runtime_evidence(
            "progress", "no_progress",
            f"no progress in end_turn: {model_event.event_type}",
            metadata={
                "no_progress_reason": model_event.event_type,
                "consecutive_end_turn_without_progress": projected_no_progress,
            },
        )
        save_checkpoint(state)
        return ""

    _record_end_turn_observation(observation)
    state.task.consecutive_max_tokens = 0
    _append_assistant_response(messages, response)

    # 步骤推进逻辑统一走 _maybe_advance_step——它读 mark_step_complete 日志判完成，
    # 而不是关键词匹配。end_turn 这条路径通常用于：
    #   - 模型在 tool_use 那一轮已经调过 mark_step_complete + 走完步骤推进，
    #     下一轮纯 end_turn 收尾（此时 log 不再有"当前 step 的"完成项，返回 None）
    #   - 或模型偷懒只发 end_turn 没调元工具——此时返回 None，等下轮继续
    advance_reply = _maybe_advance_step(state)
    if advance_reply is not None:
        return advance_reply
    if step_completed_before:
        # 本轮已经产生真实 step progress，不能再把同一响应计为 no-progress。
        return None

    if state.task.current_plan and state.task.status == "running":
        # 双层兜底：模型 end_turn 但没调任何工具、也没 mark_step_complete。
        # 旧实现硬塞"请打分或继续"会陷入死循环——若模型违反协议（用文本散问而非
        # request_user_input），它会再次散问 → end_turn → 再注入 → 永远刷屏。
        #
        # 第一层：启发式判断 assistant 文本是否在向用户提阻塞性问题。命中即停。
        # 第二层：连续 2 次没有任何工具调用（计数在 handle_tool_use_response 里清零）
        #         强制停。覆盖陈述句问题之类启发式漏判的场景。
        # no_progress 是安全阀，不是正常完成机制；正常路径仍应由
        # mark_step_complete / request_user_input 等结构化信号驱动。
        state.task.consecutive_end_turn_without_progress = projected_no_progress
        log_event(
            "runtime.end_turn_without_completion",
            event_source="runtime",
            event_payload={
                **_current_step_fields(state),
                "had_text_output": bool(text_content),
                "had_tool_use": False,
                "mark_step_complete_called": False,
                "request_user_input_called": False,
            },
            event_channel="assistant_text",
        )
        _record_runtime_evidence(
            "end_turn", "no_completion",
            f"end_turn without step completion "
            f"(consecutive={state.task.consecutive_end_turn_without_progress})",
            metadata={
                "had_text_output": bool(text_content),
                "consecutive_end_turn_without_progress": (
                    projected_no_progress
                ),
            },
        )

        # end_turn 没有 tool_use 结构：text_requested_user_input 是协议外文本兜底，
        # runtime.no_progress 是 runtime 观察到的无进展事件。当前仍由本 handler
        # 负责真正切 awaiting_user_input；resolver 只提供事件分类。
        if model_event is not None:
            _log_model_event(model_event, event_channel="assistant_text")

        # 第一次：温和软驱动（保留现有"模型在思考、注入提示推它继续"的行为）。
        # 提示里同时把 request_user_input 的协议要求重申一遍，引导模型回到正轨。
        messages.append({
            "role": "user",
            "content": (
                "[系统] 当前计划步骤尚未收到 mark_step_complete 完成信号。"
                "如果本步骤已经完成，请立即调用 mark_step_complete；"
                "如果尚未完成，请继续执行当前步骤。"
                "如果你需要用户补充信息，请调用 request_user_input 元工具，"
                "**不要**只用普通文本向用户提问。"
            ),
        })
        save_checkpoint(state)
        return None

    if not state.task.current_plan:
        _deactivate_task_boundary(
            state,
            reason="no_current_plan_reset",
            source="response_handlers.handle_end_turn_response",
        )
        clear_checkpoint()
        state.reset_task()

    # 普通 end_turn：返回模型正文。
    # 交互式 CLI 通过 main.py:174 的 dedup 逻辑避免重复打印；
    # 非交互式调用方（dogfood harness / 程序化 API）依赖此返回值获取文本。
    return extract_text_fn(response.content) or ""
