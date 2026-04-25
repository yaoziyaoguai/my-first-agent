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
from agent.tool_registry import is_meta_tool


MAX_TOOL_CALLS_PER_TURN = 50


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
    # 元工具不算"业务工具调用"——既不吃 per-turn 配额，也不需要在 messages 里
    # 配 tool_result；`_fill_placeholder_results` 若作用到元工具会产生"挂空"
    # tool_result（对应的 tool_use 已被序列化时剔除），破坏 API 协议。
    business_blocks = [b for b in tool_use_blocks if not is_meta_tool(b.name)]
    state.task.tool_call_count += len(business_blocks)

    if state.task.tool_call_count > MAX_TOOL_CALLS_PER_TURN:
        _fill_placeholder_results(messages, business_blocks, reason="工具调用次数超限，未执行")
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
            remaining_business = [b for b in tool_use_blocks[idx + 1:] if not is_meta_tool(b.name)]
            _fill_placeholder_results(
                messages,
                remaining_business,
                reason=(
                    "前序工具被安全策略阻断。本工具未被执行，"
                    "不会在后续自动重试——如有需要请换用其他方式"
                ),
            )
            return "用户连续拒绝多次操作，任务已停止。"
        if result == AWAITING_USER:
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
    if not is_current_step_completed(state):
        return None

    if state.task.current_plan:
        plan = Plan.model_validate(state.task.current_plan)
        idx = state.task.current_step_index

        if idx < len(plan.steps) - 1:
            state.task.status = "awaiting_step_confirmation"
            save_checkpoint(state)
            return "\n[请确认: y 进入下一步 / n 停止任务 / 输入意见以重规划]"

    advance_current_step_if_needed(state)

    if state.task.status == "done":
        clear_checkpoint()
        state.reset_task()

    return ""


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

    **返回约定**：不返回模型正文。正文已经由 `_call_model` 在流式阶段逐字 print。
    返回值只包含"**控制型 UI 文字**"——比如 "本步骤已完成。回复 y 继续下一步"
    这种给用户的提示。普通 end_turn 返回空串，main_loop 的 `if reply: print(reply)`
    判假不再打印，避免正文重复输出两次。
    """
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

    # 普通 end_turn：返回空串。正文已流式打过，main_loop 不会重复打印。
    return ""