"""subagent.delegate_l0 RuntimeAction handler."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from agent.runtime_integration.dispatcher import RuntimeActionContext
from agent.runtime_integration.schema import RuntimeActionRequest
from agent.subagent_system.delegation import delegate_once
from agent.subagent_system.registry import SubAgentRegistry
from agent.subagent_system.request import SubAgentRequest


_SHELL_LIKE_TOOLS = frozenset({"shell", "bash", "run_shell"})


class SubAgentDelegateL0Handler:
    """Parent Runtime controlled L0 delegation handler."""

    def __init__(self, *, registry: SubAgentRegistry) -> None:
        self._registry = registry

    @classmethod
    def from_roots(cls, roots: Iterable[Path]) -> "SubAgentDelegateL0Handler":
        return cls(registry=SubAgentRegistry(roots=tuple(Path(root) for root in roots)))

    def handle(self, request: RuntimeActionRequest, context: RuntimeActionContext):
        payload = dict(request.payload)
        subagent_name = str(payload.get("subagent_name") or "")
        if payload.get("in_delegation_context") is True:
            return self._reject(context, "nested delegation is forbidden", no_nested=False, subagent_name=subagent_name)
        if not subagent_name:
            return self._reject(context, "subagent_name is required", subagent_name=subagent_name)
        descriptor = self._registry.get_descriptor(subagent_name)
        if descriptor is None:
            return self._reject(context, "subagent is not registered", subagent_name=subagent_name)
        if not descriptor.is_visible():
            return self._reject(context, "subagent is disabled", subagent_name=subagent_name)

        requested_tools = tuple(str(item) for item in payload.get("allowed_tools", ()))
        if not set(requested_tools).issubset(set(descriptor.allowed_tools)):
            return self._reject(context, "requested tools exceed descriptor allowed_tools", subagent_name=subagent_name)
        if set(requested_tools) & _SHELL_LIKE_TOOLS:
            return self._reject(context, "shell/external process is forbidden in L0", subagent_name=subagent_name)
        if payload.get("parent_adjudication_required") is not True:
            return self._reject(context, "parent adjudication is required", subagent_name=subagent_name)

        budget = dict(payload.get("budget") or {})
        max_iterations = int(budget.get("max_iterations", 1))
        if max_iterations > descriptor.max_iterations_default:
            return self._reject(context, "budget exceeds descriptor max_iterations_default", subagent_name=subagent_name)

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
        observed = context.observe_module_call(
            target_module="SubAgentExecutor",
            function_called="delegate_once",
            call_signature="delegate_once(SubAgentRequest, SubAgentRegistry)",
            call=lambda: delegate_once(subagent_request, self._registry),
        )
        run = observed.value
        adjudication = run.adjudication
        adjudication_label = _adjudication_label(getattr(adjudication, "action", ""))
        result_payload = {
            "subagent_name": subagent_name,
            "execution_result": getattr(run.result, "summary", "") if run.result is not None else "",
            "delegate_once_called": True,
            "subagent_request_built": True,
            "handoff_note": getattr(run.result, "handoff_back", None) if run.result is not None else None,
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


def _adjudication_label(action: str) -> str:
    if action == "accept_result":
        return "accept"
    if action == "reject_result":
        return "reject"
    return "needs_review"
