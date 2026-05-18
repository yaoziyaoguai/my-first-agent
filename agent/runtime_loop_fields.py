"""Runtime loop debug/audit field projection.

本模块只把 TaskState 投影成日志和 dogfood 可用的最小字段。它不拥有主循环、
不修改状态、不保存 checkpoint，也不连接 Memory / ToolRegistry / observability 平台。
"""

from __future__ import annotations

from typing import Any


def build_runtime_loop_fields(state: Any) -> dict[str, Any]:
    """构造主循环最小调试字段，不参与业务判断。

    这个 helper 是 behavior-neutral extraction：输入是当前 AgentState，输出是
    可脱敏记录的摘要字段；调用方仍由 Parent Runtime 决定何时记录和如何处理。
    """

    fields: dict[str, Any] = {
        "task_status": state.task.status,
        "current_step_index": state.task.current_step_index,
        "loop_iterations": state.task.loop_iterations,
        "has_pending_tool": bool(state.task.pending_tool),
        "has_pending_user_input": bool(state.task.pending_user_input_request),
    }
    plan = state.task.current_plan or {}
    steps = plan.get("steps") or []
    idx = state.task.current_step_index
    if 0 <= idx < len(steps):
        step = steps[idx]
        fields["current_step_title"] = step.get("title")
        fields["current_step_type"] = step.get("step_type")
    return fields
