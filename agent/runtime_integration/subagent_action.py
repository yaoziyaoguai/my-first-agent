"""subagent.delegate_l0 RuntimeAction handler."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from agent.runtime_integration.dispatcher import RuntimeActionContext
from agent.runtime_integration.schema import RuntimeActionRequest
from agent.subagent_system.registry import SubAgentRegistry
from agent.subagent_system.request import SubAgentRequest

_SHELL_LIKE_TOOLS = frozenset({"shell", "bash", "run_shell"})


class SubAgentDelegateL0Handler:
    """Parent Runtime controlled L0 delegation handler."""

    def __init__(self, *, registry: SubAgentRegistry) -> None:
        self._registry = registry

    @classmethod
    def from_roots(cls, roots: Iterable[Path]) -> SubAgentDelegateL0Handler:
        return cls(registry=SubAgentRegistry(roots=tuple(Path(root) for root in roots)))

    def handle(self, request: RuntimeActionRequest, context: RuntimeActionContext):
        payload = dict(request.payload)
        subagent_name = str(payload.get("subagent_name") or "")

        # 中文学习注释：当 subagent_name 为空且不在 delegation context 中时，
        # 这是 turn-end hook 的 L3 evidence dispatch（非模型驱动 dispatch）。handler
        # 仍通过 invoke_registered_target 获得完整 target_module_proof 证据链，
        # 但返回 failed disposition。不影响现有模型输出驱动的 subagent delegation。
        if not subagent_name and payload.get("in_delegation_context") is not True:
            observed = context.invoke_registered_target(
                target_module="SubAgentExecutor",
                operation="no_suitable_subagent",
                payload={"reason": "no subagent available for delegation"},
            )
            return context.failed(
                handler_name=type(self).__name__,
                target_module="SubAgentExecutor",
                payload={
                    "subagent_name": "",
                    "delegate_once_called": False,
                    "subagent_request_built": False,
                    "failure_reason": "no subagent available for delegation",
                },
                observed_call=observed,
                parent_adjudicated=True,
                evidence_extra={
                    "delegate_once_called": False,
                    "subagent_request_built": False,
                },
                error_safe_preview="no subagent available for delegation",
            )

        if payload.get("in_delegation_context") is True:
            return self._reject(context, "nested delegation is forbidden", no_nested=False, subagent_name=subagent_name)  # noqa: E501
        if not subagent_name:
            return self._reject(context, "subagent_name is required", subagent_name=subagent_name)
        descriptor = self._registry.get_descriptor(subagent_name)
        if descriptor is None:
            return self._reject(context, "subagent is not registered", subagent_name=subagent_name)
        if not descriptor.is_visible():
            return self._reject(context, "subagent is disabled", subagent_name=subagent_name)

        requested_tools = tuple(str(item) for item in payload.get("allowed_tools", ()))
        if not set(requested_tools).issubset(set(descriptor.allowed_tools)):
            return self._reject(context, "requested tools exceed descriptor allowed_tools", subagent_name=subagent_name)  # noqa: E501
        if set(requested_tools) & _SHELL_LIKE_TOOLS:
            return self._reject(context, "shell/external process is forbidden in L0", subagent_name=subagent_name)  # noqa: E501
        if payload.get("parent_adjudication_required") is not True:
            return self._reject(context, "parent adjudication is required", subagent_name=subagent_name)  # noqa: E501

        budget = dict(payload.get("budget") or {})
        max_iterations = int(budget.get("max_iterations", 1))
        if max_iterations > descriptor.max_iterations_default:
            return self._reject(context, "budget exceeds descriptor max_iterations_default", subagent_name=subagent_name)  # noqa: E501

        subagent_request = SubAgentRequest(
            task=str(payload.get("delegation_goal") or ""),
            role=descriptor.role,
            allowed_tools=requested_tools,
            parent_trace_id=request.parent_trace_id,
            delegation_reason="RuntimeAction subagent.delegate_l0",
            memory_scope="none",
            max_iterations=max_iterations,
            execution_mode="local_fake",
            risk_level=descriptor.risk_level,
            context={"summary": str(payload.get("context_package_summary") or "")},
        )
        observed = context.invoke_registered_target(
            target_module="SubAgentExecutor",
            operation="delegate_once",
            payload={"subagent_request": subagent_request, "registry": self._registry},
        )
        run = observed.value
        adjudication = run.adjudication
        adjudication_label = _adjudication_label(getattr(adjudication, "action", ""))
        result_payload = {
            "subagent_name": subagent_name,
            "execution_result": getattr(run.result, "summary", "") if run.result is not None else "",  # noqa: E501
            "delegate_once_called": True,
            "subagent_request_built": True,
            "handoff_note": getattr(run.result, "handoff_back", None) if run.result is not None else None,  # noqa: E501
            "adjudication": adjudication_label,
            "adjudication_reason": getattr(adjudication, "reason", ""),
            "parent_adjudicated": adjudication is not None,
            "no_nested_delegation": True,
            "no_shell_or_external_process": True,
        }
        return context.success(
            handler_name=type(self).__name__,
            target_module="SubAgentExecutor",
            payload=result_payload,
            observed_call=observed,
            parent_adjudicated=True,
            evidence_extra={
                key: value
                for key, value in result_payload.items()
                if key != "parent_adjudicated"
            },
        )

    def _reject(
        self,
        context: RuntimeActionContext,
        reason: str,
        *,
        subagent_name: str,
        no_nested: bool = True,
    ):
        payload = {
            "subagent_name": subagent_name,
            "execution_result": "",
            "delegate_once_called": False,
            "subagent_request_built": False,
            "handoff_note": None,
            "adjudication": "reject",
            "adjudication_reason": reason,
            "parent_adjudicated": False,
            "no_nested_delegation": no_nested,
            "no_shell_or_external_process": "shell" not in reason,
        }
        return context.rejected(
            handler_name=type(self).__name__,
            target_module="SubAgentExecutor",
            payload=payload,
            observed_call=None,
            parent_adjudicated=False,
            evidence_extra={
                **{key: value for key, value in payload.items() if key != "parent_adjudicated"},
                "runtime_e2e_disqualified_reason": reason,
            },
            error_safe_preview=reason,
        )


class SubAgentDelegateL1Handler:
    """Parent Runtime controlled L1 delegation handler — Loop 3.2a.

    L1 与 L0 关键区别：
    - child 调真实 provider（非 deterministic keyword-match）
    - child tool_use 走 parent ToolRuntimeMediator pipeline
    - 所有 child action 有 dispatcher evidence
    - L1 是 business action（非 probe）

    provider 和 tool_mediator 由 core.chat() 在运行时注入（set_provider()），
    因为 dispatcher 在 chat() 入口构建时 provider 尚未确定。
    """

    def __init__(self, *, registry: SubAgentRegistry, dispatcher: Any = None) -> None:
        self._registry = registry
        self._provider: Any = None
        self._tool_mediator: Any = None
        self._dispatcher = dispatcher

    def set_provider(self, provider: Any, tool_mediator: Any = None) -> None:
        """由 core.chat() 在每次 delegation 前注入 provider + mediator。"""
        self._provider = provider
        self._tool_mediator = tool_mediator

    def handle(self, request: RuntimeActionRequest, context: RuntimeActionContext):
        payload = dict(request.payload)
        subagent_name = str(payload.get("subagent_name") or "")

        if not subagent_name:
            return context.failed(
                handler_name=type(self).__name__,
                target_module="SubAgentExecutor",
                payload={"subagent_name": "", "delegate_once_called": False},
                observed_call=None,
                parent_adjudicated=True,
                evidence_extra={"delegate_l1_called": False},
                error_safe_preview="no subagent name for L1 delegation",
            )

        descriptor = self._registry.get_descriptor(subagent_name)
        if descriptor is None:
            return context.rejected(
                handler_name=type(self).__name__,
                target_module="SubAgentExecutor",
                payload={
                    "subagent_name": subagent_name,
                    "delegate_l1_called": False,
                    "subagent_request_built": False,
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
                payload={"subagent_name": subagent_name, "delegate_l1_called": False},
                observed_call=None,
                parent_adjudicated=False,
                evidence_extra={"runtime_e2e_disqualified_reason": "no delegation task"},
                error_safe_preview="no delegation task for L1",
            )

        subagent_request = SubAgentRequest(
            task=task,
            role=descriptor.role,
            allowed_tools=descriptor.allowed_tools,
            parent_trace_id=request.parent_trace_id,
            delegation_reason="RuntimeAction subagent.delegate_l1",
            max_iterations=descriptor.max_iterations_default,
            execution_mode="local_fake",
            risk_level=descriptor.risk_level,
        )

        # 调用 delegate_l1（需要 provider）
        if self._provider is None:
            return context.failed(
                handler_name=type(self).__name__,
                target_module="SubAgentExecutor",
                payload={
                    "subagent_name": subagent_name,
                    "delegate_l1_called": False,
                    "failure_reason": "provider not set on L1 handler",
                },
                observed_call=None,
                parent_adjudicated=True,
                evidence_extra={"delegate_l1_called": False},
                error_safe_preview="L1 handler: provider not set",
            )

        from agent.subagent_system.delegation import delegate_l1

        try:
            run = delegate_l1(
                subagent_request,
                self._registry,
                provider=self._provider,
                tool_mediator=self._tool_mediator,
            )
        except Exception as exc:
            return context.failed(
                handler_name=type(self).__name__,
                target_module="SubAgentExecutor",
                payload={
                    "subagent_name": subagent_name,
                    "delegate_l1_called": True,
                    "failure_reason": str(exc),
                },
                observed_call=None,
                parent_adjudicated=True,
                evidence_extra={"delegate_l1_called": True, "error": str(exc)},
                error_safe_preview=f"L1 delegation failed: {exc}",
            )

        result = run.result
        adjudication = run.adjudication
        adjudication_label = _adjudication_label(getattr(adjudication, "action", ""))

        result_payload = {
            "subagent_name": subagent_name,
            "execution_result": getattr(result, "summary", "") if result else "",
            "delegate_l1_called": True,
            "subagent_request_built": True,
            "status": getattr(result, "status", "unknown") if result else "unknown",
            "stop_reason": getattr(result, "stop_reason", "") if result else "",
            "iterations_used": (
                getattr(getattr(result, "audit", None), "iterations_used", 0)
                if result else 0
            ),
            "adjudication": adjudication_label,
            "adjudication_reason": getattr(adjudication, "reason", ""),
            "parent_adjudicated": adjudication is not None,
            "execution_mode": "L1",
        }

        # Dispatch SUBAGENT_CHILD_RESULT evidence (best-effort)
        if self._dispatcher is not None:
            import contextlib
            with contextlib.suppress(Exception):
                from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType
                self._dispatcher.route_from_runtime_loop(
                    RuntimeActionRequest(
                        action_type=RuntimeActionType.SUBAGENT_CHILD_RESULT,
                        source="SubAgentDelegateL1Handler",
                        parent_trace_id=request.parent_trace_id,
                        payload={
                            "subagent_name": subagent_name,
                            "status": getattr(result, "status", "unknown") if result else "unknown",
                            "stop_reason": getattr(result, "stop_reason", "") if result else "",
                            "summary_preview": (
                                getattr(result, "summary", "")[:200] if result else ""
                            ),
                            "iterations_used": (
                                getattr(getattr(result, "audit", None), "iterations_used", 0)
                                if result else 0
                            ),
                        },
                    ),
                    core_entrypoint="core.chat",
                    runtime_hook_name="delegate_l1",
                )

        # Dispatch SUBAGENT_PARENT_ADJUDICATION evidence (best-effort)
        if self._dispatcher is not None:
            import contextlib
            with contextlib.suppress(Exception):
                from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType
                self._dispatcher.route_from_runtime_loop(
                    RuntimeActionRequest(
                        action_type=RuntimeActionType.SUBAGENT_PARENT_ADJUDICATION,
                        source="SubAgentDelegateL1Handler",
                        parent_trace_id=request.parent_trace_id,
                        payload={
                            "subagent_name": subagent_name,
                            "adjudication": adjudication_label,
                            "adjudication_reason": getattr(adjudication, "reason", ""),
                            "child_status": (
                                getattr(result, "status", "unknown")
                                if result else "unknown"
                            ),
                        },
                    ),
                    core_entrypoint="core.chat",
                    runtime_hook_name="delegate_l1",
                )

        return context.success(
            handler_name=type(self).__name__,
            target_module="SubAgentExecutor",
            payload=result_payload,
            observed_call=None,
            parent_adjudicated=True,
            evidence_extra={
                key: value
                for key, value in result_payload.items()
                if key != "parent_adjudicated"
            },
        )


def _adjudication_label(action: str) -> str:
    if action == "accept_result":
        return "accept"
    if action == "reject_result":
        return "reject"
    return "needs_review"
