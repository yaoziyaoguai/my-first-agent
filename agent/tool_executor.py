

"""Tool execution helpers.

This module owns the execution of a single model-emitted tool_use block.
It does not own the agent loop; core.py remains responsible for orchestration.
"""

from __future__ import annotations

from typing import Any

from agent.checkpoint import save_checkpoint
from agent.conversation_events import append_tool_result, has_tool_result
from agent.review import needs_tool_confirmation
from agent.tool_registry import execute_tool


AWAITING_USER = "__awaiting_user__"
FORCE_STOP = "__force_stop__"


def execute_single_tool(
    block: Any,
    *,
    state: Any,
    turn_state: Any,
    turn_context: dict[str, Any],
    messages: list[dict[str, Any]],
) -> str | None:
    """Execute or suspend a single tool_use block.

    Return values:
    - None: normal execution completed, caller may continue processing tools
    - AWAITING_USER: tool requires human confirmation; caller should stop loop
    - FORCE_STOP: tool was blocked or rejected enough times; caller should stop task
    """
    tool_use_id = block.id
    tool_name = block.name
    tool_input = block.input

    # Idempotency: never execute the same tool_use_id twice.
    execution_log = state.task.tool_execution_log
    if tool_use_id in execution_log:
        cached = execution_log[tool_use_id]["result"]
        print(f"\n[系统] 工具 {tool_name} 已执行过，跳过执行")
        if not has_tool_result(messages, tool_use_id):
            append_tool_result(messages, tool_use_id, cached)
        return None

    confirmation = needs_tool_confirmation(tool_name, tool_input)

    if confirmation == "block":
        result = "[系统] 该工具调用被安全策略阻止，未执行。"
        append_tool_result(messages, tool_use_id, result)
        state.task.tool_execution_log[tool_use_id] = {
            "tool": tool_name,
            "input": tool_input,
            "result": result,
            "status": "blocked",
        }
        save_checkpoint(state)
        return FORCE_STOP

    if confirmation is True:
        state.task.pending_tool = {
            "tool_use_id": tool_use_id,
            "tool": tool_name,
            "input": tool_input,
        }
        state.task.status = "awaiting_tool_confirmation"
        save_checkpoint(state)
        print(f"\n⚠️ 需要确认执行工具：{tool_name}({tool_input})")
        print("是否执行？(y/n/输入反馈意见): ", end="", flush=True)
        return AWAITING_USER

    result = execute_tool(tool_name, tool_input, context=turn_state.round_tool_traces)

    state.task.tool_execution_log[tool_use_id] = {
        "tool": tool_name,
        "input": tool_input,
        "result": result,
        "status": "executed",
    }

    turn_state.round_tool_traces.append({
        "tool_use_id": tool_use_id,
        "tool": tool_name,
        "input": tool_input,
        "status": "executed",
        "result": result,
    })

    turn_context[tool_use_id] = result
    append_tool_result(messages, tool_use_id, result)
    save_checkpoint(state)
    return None