"""SubAgent L2 native loop delegation handler — Next-stage D-01.

L2 在 L1 基础上增加：
- independent stop condition（child 自主 end_turn）
- parent adjudication mandatory gate（accept/reject/revision）
- child-initiated revision request
- batched memory proposals
- deepened tool access（grep + glob）

L2 受 SubAgentPolicy.real_llm_tool_requesting_allowed gate 保护。
不读 .env，不调真实 provider（contract tests 用 _SpyProvider）。
"""

from __future__ import annotations

from typing import Any

from agent.subagent_system.delegation import delegate_l2
from agent.subagent_system.registry import SubAgentRegistry
from agent.subagent_system.request import SubAgentRequest


class SubAgentDelegateL2Handler:
    """L2 native loop delegation handler.

    受 policy gate 保护：SubAgentPolicy.real_llm_tool_requesting_allowed 必须为 True。
    """

    def __init__(self, *, registry: SubAgentRegistry, dispatcher: Any = None) -> None:
        self._registry = registry
        self._provider: Any = None
        self._tool_mediator: Any = None
        self._dispatcher = dispatcher

    def set_provider(self, provider: Any, tool_mediator: Any = None) -> None:
        self._provider = provider
        self._tool_mediator = tool_mediator

    def handle(self, request: Any, context: Any) -> Any:
        payload = dict(request.payload)
        subagent_name = str(payload.get("subagent_name") or "")

        if not subagent_name:
            return context.failed(
                handler_name=type(self).__name__,
                target_module="SubAgentExecutor",
                payload={"subagent_name": "", "delegate_l2_called": False},
                observed_call=None,
                parent_adjudicated=True,
                evidence_extra={"delegate_l2_called": False},
                error_safe_preview="no subagent name for L2 delegation",
            )

        descriptor = self._registry.get_descriptor(subagent_name)
        if descriptor is None:
            return context.rejected(
                handler_name=type(self).__name__,
                target_module="SubAgentExecutor",
                payload={
                    "subagent_name": subagent_name,
                    "delegate_l2_called": False,
                    "adjudication": "reject",
                    "adjudication_reason": "subagent not registered",
                },
                observed_call=None,
                parent_adjudicated=False,
                evidence_extra={"runtime_e2e_disqualified_reason": "subagent not registered"},
                error_safe_preview=f"subagent '{subagent_name}' not registered",
            )

        task = str(payload.get("delegation_goal") or payload.get("task") or "")
        if not task:
            return context.rejected(
                handler_name=type(self).__name__,
                target_module="SubAgentExecutor",
                payload={"subagent_name": subagent_name, "delegate_l2_called": False},
                observed_call=None,
                parent_adjudicated=False,
                evidence_extra={"runtime_e2e_disqualified_reason": "no delegation task"},
                error_safe_preview="no delegation task for L2",
            )

        subagent_request = SubAgentRequest(
            task=task,
            role=descriptor.role,
            allowed_tools=descriptor.allowed_tools,
            parent_trace_id=request.parent_trace_id,
            delegation_reason="RuntimeAction subagent.delegate_l2",
            max_iterations=descriptor.max_iterations_default,
            execution_mode="real_llm_tool_requesting",
            risk_level=descriptor.risk_level,
        )

        run = delegate_l2(
            subagent_request,
            self._registry,
            provider=self._provider,
            tool_mediator=self._tool_mediator,
            parent_dispatcher=self._dispatcher,
        )

        if run.state == "failed" or run.result is None:
            return context.failed(
                handler_name=type(self).__name__,
                target_module="SubAgentExecutor",
                payload={
                    "subagent_name": subagent_name,
                    "delegate_l2_called": True,
                    "run_state": run.state,
                },
                observed_call=None,
                parent_adjudicated=True,
                evidence_extra={
                    "delegate_l2_called": True,
                    "run_state": run.state,
                    "revision_count": run.revision_count,
                },
                error_safe_preview="L2 delegation failed",
            )

        result = run.result
        return context.success(
            handler_name=type(self).__name__,
            target_module="SubAgentExecutor",
            payload={
                "subagent_name": subagent_name,
                "delegate_l2_called": True,
                "summary": result.summary[:200],
                "status": result.status,
                "stop_reason": result.stop_reason,
                "batch_memory_count": len(result.batch_memory_proposals),
                "revision_count": run.revision_count,
            },
            observed_call="delegate_l2() → execute_l2() → provider.create(child loop)",
            parent_adjudicated=True,
            evidence_extra={
                "delegate_l2_called": True,
                "run_state": run.state,
                "stop_reason": result.stop_reason,
                "batch_memory_count": len(result.batch_memory_proposals),
                "revision_count": run.revision_count,
                "tools_requested": list(result.audit.tools_requested) if result.audit else [],
            },
            error_safe_preview="L2 delegation completed",
        )
