

"""Response handlers for model responses.

These helpers sit at the boundary between raw model responses and the agent
runtime. They parse stop-reason-specific model responses and delegate actual
execution to lower-level modules.
"""

from __future__ import annotations

from typing import Any

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