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
from agent.conversation_events import append_tool_result, has_tool_result


MAX_TOOL_CALLS_PER_TURN = 10


def _serialize_assistant_content(content_blocks: list[Any]) -> list[dict[str, Any]]:
    """把模型返回的 content blocks 序列化为可持久化的 dict 列表。

    关键点：必须保留 tool_use 块（含 id/name/input），否则下一轮消息里的
    tool_result 找不到对应的 tool_use_id，Anthropic API 会直接报错。
    """
    serialized: list[dict[str, Any]] = []
    for block in content_blocks:
        btype = getattr(block, "type", None)
        if btype == "text":
            text = getattr(block, "text", "") or ""
            if text:
                serialized.append({"type": "text", "text": text})
        elif btype == "tool_use":
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
) -> str | None:
    """Handle a model response whose stop_reason is tool_use.

    Responsibilities:
    - append assistant content blocks (含 tool_use) into conversation messages
    - extract tool_use blocks
    - enforce per-turn tool call limit
    - delegate single-tool execution to tool_executor
    - translate tool executor sentinel values into loop-level results
    - 遇到 AWAITING_USER / FORCE_STOP 时，为剩余未处理的 tool_use 写占位
      tool_result，保证下一次调用 API 时 tool_use/tool_result 配对完整。
    """
    _append_assistant_response(messages, response)

    state.task.consecutive_max_tokens = 0

    tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
    state.task.tool_call_count += len(tool_use_blocks)

    if state.task.tool_call_count > MAX_TOOL_CALLS_PER_TURN:
        # 超限时也要给未配对的 tool_use 补 tool_result，避免下次调用炸。
        _fill_placeholder_results(messages, tool_use_blocks, reason="工具调用次数超限，未执行")
        return "工具调用次数过多，请简化任务或分步执行。"

    turn_context: dict[str, Any] = {}

    for idx, block in enumerate(tool_use_blocks):
        result = execute_single_tool(
            block,
            state=state,
            turn_state=turn_state,
            turn_context=turn_context,
            messages=messages,
        )
        if result == FORCE_STOP:
            _fill_placeholder_results(
                messages,
                tool_use_blocks[idx + 1:],
                reason="前序工具被安全策略阻断，本工具跳过",
            )
            return "用户连续拒绝多次操作，任务已停止。"
        if result == AWAITING_USER:
            _fill_placeholder_results(
                messages,
                tool_use_blocks[idx + 1:],
                reason="等待用户确认前序工具，本工具本轮跳过",
            )
            return ""

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
    _append_assistant_response(messages, response)

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
) -> str:
    """Handle a model response whose stop_reason is end_turn.

    This keeps end-turn behavior outside core.py while preserving state-driven
    execution semantics:
    - append assistant content blocks into conversation messages
    - detect whether current step completed
    - move to awaiting_step_confirmation when there are more steps
    - advance / clear checkpoint when the task is done
    """
    state.task.consecutive_max_tokens = 0

    _append_assistant_response(messages, response)

    assistant_text = extract_text_fn(response.content) or "[任务完成]"

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
        # 任务完成：清 checkpoint + 重置 task 内存态。
        # 否则 current_plan / current_step_index / tool_execution_log 会残留，
        # 下一次 chat() 如果被 planner 判为单步任务（不走规划），
        # build_execution_messages 仍会读到旧 plan 并把"旧步骤指令"喂给模型。
        clear_checkpoint()
        state.reset_task()

    return assistant_text