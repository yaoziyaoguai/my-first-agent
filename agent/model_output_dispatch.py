"""Model output dispatch for the runtime loop.

学习型说明：
主循环负责“下一轮是否继续”，本模块负责“当前模型 stop_reason 交给哪个
response handler”。它不执行工具、不写 checkpoint、不直接推进 TaskState；
这些仍由 response_handlers 的 owner 函数完成。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent.display_events import RuntimeEvent, unknown_stop_reason_event
from agent.runtime_events import ModelOutputKind, classify_model_output
from agent.runtime_observer import log_event as log_runtime_event

RuntimeEventSink = Callable[[RuntimeEvent], None] | None


@dataclass(frozen=True, slots=True)
class ModelOutputDispatchDependencies:
    """模型输出分派依赖集合，避免 dispatch 模块反向 import core.py。"""

    state: Any
    handle_max_tokens_response: Callable[..., str | None]
    handle_end_turn_response: Callable[..., str | None]
    handle_tool_use_response: Callable[..., str | None]
    extract_text: Callable[[Any], str]
    runtime_loop_fields: Callable[[], dict[str, Any]]
    safe_emit_runtime_event: Callable[[RuntimeEventSink, RuntimeEvent], None]
    max_consecutive_max_tokens: int
    runtime_action_dispatcher: Any | None = None
    runtime_identity: Any = None
    memory_runtime: Any = None


def dispatch_model_output(
    response: Any,
    *,
    turn_state: Any,
    dependencies: ModelOutputDispatchDependencies,
) -> str | None:
    """按 ModelOutputKind 分派 response；handler 返回 None 时继续主循环。"""

    state = dependencies.state
    runtime_loop_fields = dependencies.runtime_loop_fields
    model_kind = classify_model_output(response.stop_reason)
    log_runtime_event(
        "loop.iteration_end",
        event_source="runtime",
        event_payload={
            **runtime_loop_fields(),
            "stop_reason": response.stop_reason,
        },
        event_channel="loop",
    )

    if model_kind is ModelOutputKind.MAX_TOKENS:
        result = dependencies.handle_max_tokens_response(
            response,
            state=state,
            turn_state=turn_state,
            messages=state.conversation.messages,
            extract_text_fn=dependencies.extract_text,
            max_consecutive_max_tokens=dependencies.max_consecutive_max_tokens,
        )
        return _handler_result_or_continue(
            result,
            response=response,
            runtime_loop_fields=runtime_loop_fields,
        )

    if model_kind is ModelOutputKind.END_TURN:
        result = dependencies.handle_end_turn_response(
            response,
            state=state,
            turn_state=turn_state,
            messages=state.conversation.messages,
            extract_text_fn=dependencies.extract_text,
        )
        return _handler_result_or_continue(
            result,
            response=response,
            runtime_loop_fields=runtime_loop_fields,
        )

    if model_kind is ModelOutputKind.TOOL_USE:
        result = dependencies.handle_tool_use_response(
            response,
            state=state,
            turn_state=turn_state,
            messages=state.conversation.messages,
            extract_text_fn=dependencies.extract_text,
            runtime_action_dispatcher=dependencies.runtime_action_dispatcher,
            runtime_identity=dependencies.runtime_identity,
            memory_runtime=dependencies.memory_runtime,
        )
        return _handler_result_or_continue(
            result,
            response=response,
            runtime_loop_fields=runtime_loop_fields,
        )

    if model_kind is ModelOutputKind.UNKNOWN:
        # UNKNOWN：未知的 stop_reason 必须显式 fail-closed，不能落到任一成功 handler。
        event = unknown_stop_reason_event(response.stop_reason)
        dependencies.safe_emit_runtime_event(turn_state.on_runtime_event, event)
        log_runtime_event(
            "loop.stop",
            event_source="runtime",
            event_payload={
                **runtime_loop_fields(),
                "stop_reason": response.stop_reason,
                "reason_for_stop": "unknown_stop_reason",
            },
            event_channel="loop",
        )
        return "意外的响应"

    return "意外的响应"


def _handler_result_or_continue(
    result: str | None,
    *,
    response: Any,
    runtime_loop_fields: Callable[[], dict[str, Any]],
) -> str | None:
    """统一记录 handler terminal result；None 表示继续主循环。"""

    if result is None:
        return None
    log_runtime_event(
        "loop.stop",
        event_source="runtime",
        event_payload={
            **runtime_loop_fields(),
            "stop_reason": response.stop_reason,
            "reason_for_stop": "handler_returned",
        },
        event_channel="loop",
    )
    return result
