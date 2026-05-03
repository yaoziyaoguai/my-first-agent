"""Optional runtime trace sink emission helpers.

RFC 0002 的目标是窄边界 opt-in wiring：tool_executor 在已有 legacy
tool_result 字符串之后，可以把同一事实投影给调用方提供的 trace sink。这里不创建
LocalTraceRecorder、不读取 runtime/checkpoint/session，也不吞掉 sink 异常。
"""

from __future__ import annotations

from typing import Any

from agent.local_trace import TraceEvent
from agent.runtime_trace_projection import build_tool_result_trace_event


def emit_tool_result_trace_event(
    turn_state: Any,
    *,
    tool_use_id: str,
    tool_name: str,
    tool_result: str,
    step_index: int | None,
) -> TraceEvent | None:
    """Emit a ToolResult TraceEvent to an explicitly provided sink.

    中文学习边界：
    - 没有 sink 时直接 no-op，默认 runtime 行为完全不变。
    - 有 sink 时必须有 trace_run_id / trace_id；缺失说明调用方注入不完整，
      应显式报错而不是悄悄丢 trace。
    - 本 helper 只投影已生成的 tool_result，不执行工具、不写 checkpoint、不读日志。
    """

    sink = getattr(turn_state, "on_trace_event", None)
    if sink is None:
        return None

    run_id = getattr(turn_state, "trace_run_id", None)
    trace_id = getattr(turn_state, "trace_id", None)
    if not run_id or not trace_id:
        raise ValueError("trace sink requires trace_run_id and trace_id on turn_state")

    event = build_tool_result_trace_event(
        run_id=run_id,
        trace_id=trace_id,
        span_id=f"tool_result:{tool_use_id}",
        parent_span_id=f"tool_use:{tool_use_id}",
        tool_name=tool_name,
        tool_result=tool_result,
        tool_use_id=tool_use_id,
        step_id=_step_id(step_index),
    )
    sink(event)
    return event


def _step_id(step_index: int | None) -> str | None:
    if step_index is None:
        return None
    if step_index < 0:
        return None
    return f"step-{step_index}"
