"""Response handlers for model responses.

These helpers sit at the boundary between raw model responses and the agent
runtime. They parse stop-reason-specific model responses and delegate actual
execution to lower-level modules.
"""

from __future__ import annotations

from typing import Any
from agent.checkpoint import clear_checkpoint, save_checkpoint
from agent.planner import Plan
from agent.task_runtime import advance_current_step_if_needed, is_current_step_completed

from agent.tool_executor import AWAITING_USER, FORCE_STOP, execute_single_tool


MAX_TOOL_CALLS_PER_TURN = 10


def handle_tool_use_response(
    response: Any,
    *,
    state: Any,
    turn_state: Any,
    messages: list[dict[str, Any]],
    extract_text_fn,
) -> str | None:
    """Handle a model response whose stop_reason is tool_use.

    Responsibilities:
    - append assistant text into conversation messages
    - extract tool_use blocks
    - enforce per-turn tool call limit
    - delegate single-tool execution to tool_executor
    - translate tool executor sentinel values into loop-level results
    """
    assistant_text = extract_text_fn(response.content)
    if assistant_text:
        messages.append({
            "role": "assistant",
            "content": assistant_text,
        })

    turn_state.consecutive_max_tokens = 0

    tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
    turn_state.tool_call_count += len(tool_use_blocks)

    if turn_state.tool_call_count > MAX_TOOL_CALLS_PER_TURN:
        return "工具调用次数过多，请简化任务或分步执行。"

    turn_context: dict[str, Any] = {}

    for block in tool_use_blocks:
        result = execute_single_tool(
            block,
            state=state,
            turn_state=turn_state,
            turn_context=turn_context,
            messages=messages,
        )
        if result == FORCE_STOP:
            return "用户连续拒绝多次操作，任务已停止。"
        if result == AWAITING_USER:
            return ""

    return None


def handle_max_tokens_response(
    response: Any,
    *,
    turn_state: Any,
    messages: list[dict[str, Any]],
    extract_text_fn,
    max_consecutive_max_tokens: int,
) -> str | None:
    """Handle a model response whose stop_reason is max_tokens.

    This preserves the core.py behavior:
    - keep the assistant text in conversation messages
    - increment consecutive max_tokens count
    - stop when the configured threshold is exceeded
    """
    assistant_text = extract_text_fn(response.content)
    if assistant_text:
        messages.append({
            "role": "assistant",
            "content": assistant_text,
        })

    turn_state.consecutive_max_tokens += 1

    if turn_state.consecutive_max_tokens >= max_consecutive_max_tokens:
        return "模型连续多次达到最大输出长度，任务已停止。请缩小任务范围后重试。"

    return None


def handle_end_turn_response(
    response: Any,
    *,
    state: Any,
    turn_state: Any,
    messages: list[dict[str, Any]],
    extract_text_fn,
) -> str:
    """Handle a model response whose stop_reason is end_turn.

    This keeps end-turn behavior outside core.py while preserving state-driven
    execution semantics:
    - append assistant text into conversation messages
    - detect whether current step completed
    - move to awaiting_step_confirmation when there are more steps
    - advance / clear checkpoint when the task is done
    """
    turn_state.consecutive_max_tokens = 0

    assistant_text = extract_text_fn(response.content)
    if not assistant_text:
        assistant_text = "[任务完成]"

    messages.append({
        "role": "assistant",
        "content": assistant_text,
    })

    if is_current_step_completed(state, assistant_text):
        if state.task.current_plan:
            plan = Plan.model_validate(state.task.current_plan)
            idx = state.task.current_step_index

            if idx < len(plan.steps) - 1:
                state.task.status = "awaiting_step_confirmation"
                save_checkpoint(state)
                return (
                    assistant_text
                    + "\n\n本步骤已完成。回复 y 继续下一步，回复 n 停止任务。"
                )

        advance_current_step_if_needed(state)

    if state.task.status == "done":
        clear_checkpoint()

    return assistant_text