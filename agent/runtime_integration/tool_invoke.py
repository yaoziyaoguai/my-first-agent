"""Tool invoke branch behavior handler.

中文学习边界：
Tool invoke 归属 Contract Section 2 "tool execution / confirmation handling" 分支点。
它不是新 Anchor、不是新 capability milestone、不是新 runtime flow。

tool.invoke 是 tool.gate（pre-execution gating）和 tool.result（post-execution
feedback）之间的 evidence-only 中间环节：

tool.gate (allowed/blocked/confirmation_required)
  → tool.invoke (记录 invoke_started，不执行工具)
    → tool.result (格式化/截断/redact → prompt section)

真实工具执行只能通过 ToolRuntimeMediator → tool_executor 发生。直接 dispatch
TOOL_INVOKE 不得调用工具函数，避免旧 dispatcher 路径绕过 mediator 或造成双重执行。
"""

from __future__ import annotations

from typing import Any

DEFAULT_RISK_LEVEL = "medium"
_EXTERNAL_SIDE_EFFECT_CAPABILITIES = frozenset({
    "file_write",
    "command_execution",
    "network_fetch",
})


class ToolInvokeHandler:
    """Tool invoke handler — evidence-only invoke marker。

    中文学习边界：
    这个 handler 不做 gating（那是 TOOL_GATE 的职责），也不做 result formatting
    （那是 TOOL_RESULT 的职责），也不执行工具。它只负责把误 dispatch 到
    TOOL_INVOKE 的路径降级为 evidence-only 事件。

    与 ToolGateHandler / ToolResultFeedbackHandler 的管线关系：
    - ToolGateHandler: pre-execution gating (allowed/confirmation_required/blocked)
    - ToolInvokeHandler: evidence-only invoke marker (不调用 func)
    - ToolResultFeedbackHandler: post-execution feedback (format/truncate/redact)
    """

    def __init__(self, *, store=None) -> None:
        from agent.memory_store import InMemoryMemoryStore

        self._store = store or InMemoryMemoryStore()

    def handle(self, request, context):
        """处理 TOOL_INVOKE action。

        Args:
            request: RuntimeActionRequest with payload keys:
                tool_name (str, required), tool_input (dict, required)
            context: RuntimeActionContext
        """
        payload = dict(request.payload)
        tool_name = payload.get("tool_name")
        tool_input_missing = "tool_input" not in payload
        tool_input = payload.get("tool_input") if not tool_input_missing else None

        # 验证必填字段
        if tool_name is None:
            return context.success(
                handler_name=type(self).__name__,
                target_module="ToolRegistry",
                payload={
                    "disposition": "failed",
                    "error": "missing required field: tool_name",
                    "tool_invoked": False,
                    "dangerous_tool_function_invoked": False,
                    "tool_output": None,
                    "execution_status": "failed",
                },
                observed_call=None,
                evidence_extra={
                    "validation_failed": True,
                    "missing_field": "tool_name",
                    "external_side_effects": False,
                    "no_tool_registry_modification": True,
                    "no_memory_side_effects": True,
                },
            )

        if tool_input_missing:
            return context.success(
                handler_name=type(self).__name__,
                target_module="ToolRegistry",
                payload={
                    "disposition": "failed",
                    "error": "missing required field: tool_input",
                    "tool_invoked": False,
                    "dangerous_tool_function_invoked": False,
                    "tool_output": None,
                    "execution_status": "failed",
                },
                observed_call=None,
                evidence_extra={
                    "validation_failed": True,
                    "missing_field": "tool_input",
                    "external_side_effects": False,
                    "no_tool_registry_modification": True,
                    "no_memory_side_effects": True,
                },
            )

        # ── evidence-only：通过 catalog 只查元数据，不执行工具 ───────────
        observed = context.invoke_registered_target(
            target_module="ToolRegistry",
            operation="lookup_invoke_metadata",
            payload={"tool_name": tool_name, "tool_input": tool_input or {}},
        )

        adapter_result: dict[str, Any] = observed.value
        found: bool = adapter_result.get("found", False)
        tool_output = adapter_result.get("tool_output")
        execution_status: str = adapter_result.get(
            "execution_status", "not_executed"
        )
        risk_level: str = adapter_result.get("risk_level", DEFAULT_RISK_LEVEL)
        capability: str = adapter_result.get("capability", "")

        dangerous = risk_level == "high"
        external_side_effects = capability in _EXTERNAL_SIDE_EFFECT_CAPABILITIES

        disposition = "not_found" if not found else "evidence_only"
        tool_invoked = False

        return context.success(
            handler_name=type(self).__name__,
            target_module="ToolRegistry",
            payload={
                "disposition": disposition,
                "tool_name": tool_name,
                "tool_invoked": tool_invoked,
                "dangerous_tool_function_invoked": dangerous,
                "tool_output": tool_output,
                "execution_status": execution_status,
            },
            observed_call=observed,
            evidence_extra={
                "tool_name": tool_name,
                "tool_invoked": tool_invoked,
                "operation": "invoke_started",
                "dangerous_tool_function_invoked": dangerous,
                "external_side_effects": external_side_effects,
                "execution_status": execution_status,
                "risk_level": risk_level,
                "capability": capability,
                "no_tool_registry_modification": True,
                "no_memory_side_effects": True,
                "no_tool_invocation_side_effects": True,
            },
        )
