

"""Tool execution helpers.

This module owns the execution of a single model-emitted tool_use block.
It does not own the agent loop; core.py remains responsible for orchestration.
"""

from __future__ import annotations

from typing import Any

from agent.checkpoint import save_checkpoint
from agent.conversation_events import append_tool_result, has_tool_result
from agent.tool_registry import execute_tool, is_meta_tool
from agent.tool_registry import needs_tool_confirmation


AWAITING_USER = "__awaiting_user__"
FORCE_STOP = "__force_stop__"

TOOL_FAILURE_PREFIXES = (
    "错误：",
    "读取超时：",
    "HTTP 错误：",
    "读取失败：",
    "执行超时：",
    "[工具 ",
    "[安装失败]",
    "[更新失败]",
)


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

    **元工具特殊路径**：`mark_step_complete` 这类系统控制信号工具，只写 state.task.
    tool_execution_log（供 task_runtime 读分值判断），不写 messages——它们的
    tool_use 已经在 _serialize_assistant_content 里过滤掉了，自然也不能有
    tool_result（否则 tool_result 会"挂空"，下轮 API 调用 400）。
    """
    tool_use_id = block.id
    tool_name = block.name
    tool_input = block.input

    # 元工具分支：走独立路径，既不需要确认，也不需要在 messages 里配对。
    if is_meta_tool(tool_name):
        execution_log = state.task.tool_execution_log
        if tool_use_id in execution_log:
            # 已记录（幂等），什么都不做——messages 里本来就没有它。
            return None

        state.task.tool_execution_log[tool_use_id] = {
            "tool": tool_name,
            "input": tool_input,
            "result": "",   # 元工具没有业务语义上的返回值
            "status": "meta_recorded",
            "step_index": state.task.current_step_index,
        }

        # request_user_input：执行期求助元工具。
        # 副作用：暂停 loop（切 status）+ 记录待回答的请求 + 清掉同轮可能写入的
        # mark_step_complete 残留分值（求助语义即"当前步骤未完成"，必须作废任何已写
        # 入的完成声明，否则用户回复后下一轮 _maybe_advance_step 会读到残留分值
        # 错误推进步骤）。这条清洗只针对**当前 step_index** 的记录，其他步骤的
        # 完成声明不动。
        if tool_name == "request_user_input":
            current_idx = state.task.current_step_index
            stale_mark_ids = [
                tid
                for tid, entry in state.task.tool_execution_log.items()
                if entry.get("tool") == "mark_step_complete"
                and entry.get("step_index") == current_idx
            ]
            for tid in stale_mark_ids:
                state.task.tool_execution_log.pop(tid, None)

            state.task.pending_user_input_request = {
                "question": tool_input.get("question", ""),
                "why_needed": tool_input.get("why_needed", ""),
                "options": tool_input.get("options") or [],
                "context": tool_input.get("context", ""),
                "tool_use_id": tool_use_id,
                "step_index": current_idx,
            }
            state.task.status = "awaiting_user_input"

        save_checkpoint(state)
        return None

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
            "step_index": state.task.current_step_index,
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
    failed = any(result.startswith(prefix) for prefix in TOOL_FAILURE_PREFIXES)
    if failed:
        result = (
            f"{result}\n\n"
            "[系统提示] 该工具调用没有获得可用结果。"
            f"不要再次调用同一工具和同一输入：{tool_name}({tool_input})；"
            "请换用其他来源、使用已有信息继续，或明确说明当前来源不可用。"
        )
    status = "failed" if failed else "executed"

    state.task.tool_execution_log[tool_use_id] = {
        "tool": tool_name,
        "input": tool_input,
        "result": result,
        "status": status,
        "step_index": state.task.current_step_index,
    }

    turn_state.round_tool_traces.append({
        "tool_use_id": tool_use_id,
        "tool": tool_name,
        "input": tool_input,
        "status": status,
        "result": result,
    })

    turn_context[tool_use_id] = result
    append_tool_result(messages, tool_use_id, result)
    save_checkpoint(state)
    return None


def execute_pending_tool(
    *,
    state: Any,
    turn_state: Any,
    messages: list[dict[str, Any]],
    pending: dict[str, Any],
) -> str:
    """Execute a previously suspended pending tool after user confirmation."""
    tool_use_id = pending["tool_use_id"]
    tool_name = pending["tool"]
    tool_input = pending["input"]

    result = execute_tool(tool_name, tool_input, context=turn_state.round_tool_traces)
    failed = any(result.startswith(prefix) for prefix in TOOL_FAILURE_PREFIXES)
    if failed:
        result = (
            f"{result}\n\n"
            "[系统提示] 该工具调用没有获得可用结果。"
            f"不要再次调用同一工具和同一输入：{tool_name}({tool_input})；"
            "请换用其他来源、使用已有信息继续，或明确说明当前来源不可用。"
        )
    status = "failed" if failed else "executed"

    state.task.tool_execution_log[tool_use_id] = {
        "tool": tool_name,
        "input": tool_input,
        "result": result,
        "status": status,
        "step_index": state.task.current_step_index,
    }

    turn_state.round_tool_traces.append({
        "tool_use_id": tool_use_id,
        "tool": tool_name,
        "input": tool_input,
        "status": status,
        "result": result,
    })

    append_tool_result(messages, tool_use_id, result)
    return result
