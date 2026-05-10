"""Memory Interactive Confirmation v1 — pending request / reply parsing / handling.

本模块是 MemoryRuntime 确认需求与现有 awaiting_user_input +
pending_user_input_request 机制之间的桥接层。它**不**读写 store、不调用 LLM、
**模块级不** import checkpoint、不 import MCP/provider。

职责边界：
- build_memory_pending_request: MemoryConfirmationRequest → JSON-safe pending dict
- parse_memory_confirmation_reply: 用户输入 → (choice, free_text)
- handle_memory_confirmation_reply: 完整 handler，由 confirm_handlers 委托

v1 已知妥协：
- handle_memory_confirmation_reply 内部 lazy import save_checkpoint 以清 pending
  并保存状态。checkpoint 依赖注入（而非本模块直接 own checkpoint）是更干净的架构，
  但当前上移 save_checkpoint 到调用方需要重构 handler 返回接口，保留为 v1 compromise。
- 本模块不模块级 import checkpoint，AST boundary tests 已验证。
"""

from __future__ import annotations

from typing import Any, Protocol

from agent.display_events import (
    RuntimeEvent,
    RuntimeEventSink,
)
from agent.memory_confirmation import (
    MemoryConfirmationChoice,
    MemoryConfirmationRequest,
)


# MemoryRuntime 的 resolve_confirmation 接口（避免循环 import）
class MemoryRuntimeProtocol(Protocol):
    def resolve_confirmation(
        self,
        candidate_id: str | None,
        choice: MemoryConfirmationChoice,
        free_text: str | None = None,
    ) -> Any: ...


def build_memory_pending_request(
    confirmation_request: MemoryConfirmationRequest,
    *,
    candidate_id: str | None,
    origin_status: str,
) -> dict[str, Any]:
    """把 MemoryConfirmationRequest 投影为 JSON-safe pending_user_input_request dict。

    本函数只做数据转换，不写 state、不写 checkpoint、不调 LLM。
    """
    option_lines: list[str] = []
    choice_map: dict[str, str] = {}
    for i, opt in enumerate(confirmation_request.options, start=1):
        key = str(i)
        choice_map[key] = opt.choice.value
        suffix = "（需附文本）" if opt.requires_free_text else ""
        option_lines.append(f"{key}. {opt.label}{suffix} — {opt.description}")

    return {
        "awaiting_kind": "memory_confirmation",
        "question": confirmation_request.question,
        "why_needed": "请选择如何处理这条记忆（输入数字选择，或输入自由文本）。",
        "options": option_lines,
        "context": "",
        "tool_use_id": "",
        "step_index": None,
        "_candidate_id": candidate_id,
        "_choice_map": choice_map,
        "_origin_status": origin_status,
    }


def parse_memory_confirmation_reply(
    user_text: str,
    pending: dict[str, Any],
) -> tuple[MemoryConfirmationChoice, str | None]:
    """把用户回复解析为 (choice, free_text)，不执行任何副作用。

    解析规则：
    - "1"~"N" 精确匹配 → 对应 choice
    - "<数字> <文本>" → 对应 choice + free_text（用于 edit/other 等需附文本的选择）
    - 其他任意文本 → OTHER + 全文作为 free_text
    """
    choice_map: dict[str, str] = pending.get("_choice_map", {})
    text = user_text.strip()

    if not text:
        raise ValueError("输入为空，请重新选择。")

    if text in choice_map:
        return MemoryConfirmationChoice(choice_map[text]), None

    for key, choice_str in choice_map.items():
        if text.startswith(key + " ") or text.startswith(key + "\t"):
            free_text = text[len(key):].strip()
            return MemoryConfirmationChoice(choice_str), free_text

    return MemoryConfirmationChoice.OTHER, text


def handle_memory_confirmation_reply(
    user_text: str,
    ctx: Any,
    *,
    memory_runtime: MemoryRuntimeProtocol,
    on_runtime_event: RuntimeEventSink | None = None,
) -> str:
    """处理 memory confirmation 的用户回复，委托 confirm_handlers 调用。

    本函数负责：
    1. 解析用户输入 → (choice, free_text)
    2. 调 memory_runtime.resolve_confirmation 执行实际写入/拒绝
    3. 清 pending、恢复 status、save checkpoint
    4. emit 结果 RuntimeEvent

    不负责：
    - 不直接操作 store
    - 不调 LLM
    - 不 import checkpoint（通过 ctx.state + save_checkpoint 间接操作）
    """
    from agent.checkpoint import save_checkpoint

    state = ctx.state
    pending = state.task.pending_user_input_request or {}
    origin_status = pending.get("_origin_status", "running")

    # 1. 解析用户选择
    try:
        choice, free_text = parse_memory_confirmation_reply(user_text, pending)
    except ValueError:
        # 空输入：不清 pending，让用户重新输入
        return "请输入有效选项（数字 1-5 或自由文本）。"

    candidate_id: str | None = pending.get("_candidate_id")

    # 2. 执行确认结果
    result = memory_runtime.resolve_confirmation(candidate_id, choice, free_text)
    # result is MemoryEvaluationResult

    # 3. 清 pending，恢复状态
    state.task.pending_user_input_request = None
    state.task.status = origin_status
    save_checkpoint(state, source="memory_interaction.resolve")

    # 4. emit 结果事件
    from agent.memory_runtime import MemoryEvaluationAction

    if result.action is MemoryEvaluationAction.STORED:
        from agent.display_events import memory_stored_event as _stored_evt
        _sink_runtime_event(on_runtime_event, _stored_evt(result.content_summary))
        return f"已记住：{result.content_summary}"

    if result.action is MemoryEvaluationAction.REJECTED:
        return "已拒绝，不记住这条信息。"

    if result.action is MemoryEvaluationAction.BLOCKED:
        from agent.display_events import memory_blocked_event as _blocked_evt
        _sink_runtime_event(on_runtime_event, _blocked_evt(result.reason))
        return f"已拦截：{result.reason}"

    # SESSION_ONLY 或其他：返回确认信息
    return f"已处理：{result.reason}"


def _sink_runtime_event(
    sink: RuntimeEventSink | None,
    event: RuntimeEvent,
) -> None:
    """安全投递 RuntimeEvent，sink 为 None 或抛异常时静默吞掉。"""
    if sink is None:
        return
    try:
        sink(event)
    except Exception:
        pass
