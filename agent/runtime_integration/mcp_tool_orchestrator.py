"""MCP Tool Orchestrator — thin composition layer.

中文学习边界：
本模块是把 MCP tool-like call 串入已有 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT
管线的 thin orchestrator。它不是 dispatcher handler、不注册新的 RuntimeActionType、
不新增 Anchor、不新增 branch point、不新增 runtime flow。

orchestrator 持有 dispatcher 引用，内部调用 dispatcher.route() 串联三个已有
handler，自己只负责编排逻辑（何时继续、何时停止）。所有业务逻辑（gate 检查、
工具执行、结果格式化）仍在已有 handler/adapter 中。

证据分类：
- orchestrator 调用 dispatcher.route() → harness_runtime_e2e（target_module_proof 完整）
- 不是 real_core_loop_runtime_e2e（没有从 route_from_runtime_loop 进入）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.runtime_integration.dispatcher import RuntimeActionDispatcher
from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionResult


@dataclass(frozen=True)
class MCPPipelineResult:
    """MCP tool pipeline 编排结果。

    gate_result 一定存在（pipeline 总是先走 TOOL_GATE）。
    gate 被 blocked/not_found 时 invoke_result 和 result_feedback 为 None。
    """

    gate_result: RuntimeActionResult
    invoke_result: RuntimeActionResult | None = None
    result_feedback: RuntimeActionResult | None = None
    action_log_entries: int = 0
    stopped_early: bool = False
    stop_reason: str = ""


def run_mcp_tool_pipeline(
    dispatcher: RuntimeActionDispatcher,
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    parent_trace_id: str = "trace:mcp-tool-pipeline",
) -> MCPPipelineResult:
    """把 MCP tool-like call 串入已有 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT 管线。

    编排逻辑：
    1. TOOL_GATE：检查工具是否可执行（allowed/confirmation_required/blocked/not_found）
    2. gate 通过 → TOOL_INVOKE：实际执行工具函数
    3. TOOL_RESULT：格式化执行结果为 prompt section

    gate 被 blocked/not_found/rejected 时 pipeline 提前终止，
    TOOL_INVOKE 和 TOOL_RESULT 不会被触发。

    所有 evidence 由 dispatcher.route() 内部的 handler/context 产生，
    orchestrator 不自产 evidence、不自签 runtime_e2e proof。
    """
    from agent.runtime_integration.schema import RuntimeActionType

    action_log_before = len(dispatcher.action_log)

    # Step 1: TOOL_GATE
    gate_result = dispatcher.route(RuntimeActionRequest(
        action_type=RuntimeActionType.TOOL_GATE,
        source="mcp_tool_orchestrator",
        parent_trace_id=parent_trace_id,
        payload={"tool_name": tool_name},
    ))

    gate_payload = dict(gate_result.payload)
    gate_evidence = dict(gate_result.evidence)
    gate_disposition = gate_payload.get("gate_disposition")
    decision = str(gate_evidence.get("decision") or "")

    # gate blocked/not_found/rejected → 提前终止
    if decision in ("not_found", "rejected") or gate_disposition is None:
        return MCPPipelineResult(
            gate_result=gate_result,
            action_log_entries=len(dispatcher.action_log) - action_log_before,
            stopped_early=True,
            stop_reason=f"gate returned {decision or 'blocked'}",
        )

    # Step 2: TOOL_INVOKE
    invoke_result = dispatcher.route(RuntimeActionRequest(
        action_type=RuntimeActionType.TOOL_INVOKE,
        source="mcp_tool_orchestrator",
        parent_trace_id=parent_trace_id,
        payload={"tool_name": tool_name, "tool_input": tool_input},
    ))

    invoke_payload = dict(invoke_result.payload)
    tool_output = invoke_payload.get("tool_output")
    execution_status = str(invoke_payload.get("execution_status") or "success")

    # Step 3: TOOL_RESULT
    result_feedback = dispatcher.route(RuntimeActionRequest(
        action_type=RuntimeActionType.TOOL_RESULT,
        source="mcp_tool_orchestrator",
        parent_trace_id=parent_trace_id,
        payload={
            "tool_name": tool_name,
            "tool_output": tool_output,
            "execution_status": execution_status,
        },
    ))

    return MCPPipelineResult(
        gate_result=gate_result,
        invoke_result=invoke_result,
        result_feedback=result_feedback,
        action_log_entries=len(dispatcher.action_log) - action_log_before,
    )
