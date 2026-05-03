"""Pure projection from legacy ToolResult strings to local TraceEvent.

RFC 0001 的 first safe slice 只提供 adapter：调用方显式传入 tool result 字符串，
本模块把它分类成 `ToolResultEnvelope`，再投影成 `TraceEvent` metadata。它不执行
工具、不写 checkpoint、不读取 runtime/log/session，也不把 `LocalTraceRecorder`
接进 core.py。
"""

from __future__ import annotations

from agent.local_trace import TraceEvent, TraceStatus
from agent.tool_result_contract import ToolResultStatus, classify_tool_result


def build_tool_result_trace_event(
    *,
    run_id: str,
    trace_id: str,
    span_id: str,
    parent_span_id: str | None,
    tool_name: str,
    tool_result: str,
    tool_use_id: str | None = None,
    step_id: str | None = None,
) -> TraceEvent:
    """Build a TraceEvent from explicit ToolResult boundary fields.

    中文学习边界：这里不接 runtime state，也不调用 tool_executor；它只是把已经存在的
    legacy result 字符串投影成可审计 metadata。未来 runtime wiring 应在边界处调用
    本函数，而不是让 adapter 反向读取 runtime/checkpoint。
    """

    envelope = classify_tool_result(tool_result)
    metadata = {
        "tool_name": tool_name,
        "tool_result_status": envelope.status,
        "display_event_type": envelope.display_event_type,
        "status_text": envelope.status_text,
        "error_type": envelope.error_type,
        "safe_preview": envelope.safe_preview,
        "content_length": envelope.content_length,
        "preview_truncated": envelope.preview_truncated,
    }
    if tool_use_id is not None:
        metadata["tool_use_id"] = tool_use_id

    return TraceEvent(
        run_id=run_id,
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        span_type="tool_call",
        name=f"tool_result:{tool_name}",
        status=_trace_status_for_tool_result(envelope.status),
        step_id=step_id,
        metadata=metadata,
    )


def _trace_status_for_tool_result(status: ToolResultStatus) -> TraceStatus:
    if status == "executed":
        return "ok"
    if status == "rejected_by_check":
        return "skipped"
    return "failed"
