"""subagent.delegate_l0 RuntimeAction handler."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from agent.runtime_integration.dispatcher import RuntimeActionContext
from agent.runtime_integration.schema import RuntimeActionRequest
from agent.subagent_system.registry import SubAgentRegistry
from agent.subagent_system.request import SubAgentRequest
from agent.subagent_system.v0_contract import (
    SubAgentV0ProfileContract,
    SubAgentV0Request,
    SubAgentV0Result,
    provider_mode_allowed,
    safe_arguments_metadata,
    stable_hash,
    validate_output_schema_contract,
    validate_structured_output,
)

_SHELL_LIKE_TOOLS = frozenset({"shell", "bash", "run_shell"})
_COMMON_V0_LIFECYCLE_EVENTS = (
    "subagent.request.created",
    "subagent.profile.selected",
    "subagent.context.built",
    "subagent.execution.started",
)
_V0_LIFECYCLE_CATALOG = (
    *_COMMON_V0_LIFECYCLE_EVENTS,
    "subagent.provider.called",
    "subagent.provider.completed",
    "subagent.result.produced",
    "subagent.parent_decision.pending",
    "subagent.parent_decision.applied",
    "subagent.execution.failed",
    "subagent.execution.skipped",
    "subagent.policy.blocked",
)
_V0_POLICY_METADATA = {
    "policy_id": "subagent-v0-contract",
    "policy_rule_id": "contract-only-shell",
    "policy_hash": stable_hash("subagent-v0-contract-only-shell", prefix="policy"),
    "policy_decision_source": "runtime_contract",
}
_V0_OPERATION_CAPABILITY_FLAGS = {
    "call_provider": "can_call_provider",
    "provider_call": "can_call_provider",
    "use_tool": "can_use_tools",
    "tool_use": "can_use_tools",
    "write_memory": "can_write_memory",
    "request_memory": "can_request_memory",
    "write_checkpoint": "can_write_checkpoint",
    "spawn_child": "can_spawn_child",
    "modify_parent_context": "can_modify_parent_context",
    "emit_parent_action": "can_emit_parent_action",
}


def _safe_hash(value: object, *, prefix: str) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _safe_text_metadata(value: object, *, label: str, prefix: str) -> dict[str, object]:
    raw = str(value or "")
    return {
        f"{label}_hash": _safe_hash(raw, prefix=prefix),
        f"{label}_length": len(raw),
        "redacted": True,
    }


class SubAgentV0Handler:
    """Contract-only product v0 RuntimeAction handler.

    中文学习边界：
    U3 只建立 RuntimeAction/Profile/Request/Result 合同和 fail-closed gates。
    这里不调用 provider、不执行工具、不写 Memory/Checkpoint、不启动 child loop。
    """

    def handle(self, request: RuntimeActionRequest, context: RuntimeActionContext):
        payload = dict(request.payload)
        try:
            profile = SubAgentV0ProfileContract.from_payload(payload)
            v0_request = SubAgentV0Request.from_payload(payload)
        except ValueError as exc:
            return self._failed_contract(
                context,
                payload={},
                reason=type(exc).__name__,
                lifecycle_events=(*_COMMON_V0_LIFECYCLE_EVENTS, "subagent.execution.failed"),
                evidence_extra={"failure_kind": "invalid_v0_contract"},
            )

        base_evidence = self._base_evidence(profile, v0_request, payload)

        if payload.get("omitted_lifecycle_event"):
            omitted_event = str(payload.get("omitted_lifecycle_event") or "")
            return self._failed_contract(
                context,
                payload=self._contract_result(status="failed").to_payload(),
                reason="missing_required_lifecycle_event",
                lifecycle_events=tuple(
                    event
                    for event in self._scenario_lifecycle_events(
                        str(payload.get("scenario") or "success")
                    )
                    if event != omitted_event
                ),
                evidence_extra={
                    **base_evidence,
                    "failure_kind": "missing_required_lifecycle_event",
                    "missing_lifecycle_event": omitted_event,
                },
            )

        requested_operation = self._requested_operation(payload)
        capability_flag = _V0_OPERATION_CAPABILITY_FLAGS.get(requested_operation, "")
        if capability_flag and not bool(getattr(profile.capability_flags, capability_flag)):
            return self._policy_blocked(
                context,
                profile=profile,
                v0_request=v0_request,
                requested_operation=requested_operation,
                capability_flag=capability_flag,
                base_evidence=base_evidence,
            )

        if payload.get("introspect_lifecycle_catalog") is True:
            result = self._contract_result(status="success")
            return context.success(
                handler_name=type(self).__name__,
                target_module="SubAgentV0Contract",
                payload=result.to_payload(),
                observed_call=None,
                parent_adjudicated=False,
                evidence_extra={
                    **base_evidence,
                    "lifecycle_event_catalog": _V0_LIFECYCLE_CATALOG,
                    "lifecycle_events": _COMMON_V0_LIFECYCLE_EVENTS,
                    "event": "subagent.execution.started",
                },
            )

        output_schema_ok, output_schema_error = validate_output_schema_contract(
            profile.output_schema
        )
        if not output_schema_ok:
            return self._failed_contract(
                context,
                payload=self._contract_result(status="failed").to_payload(),
                reason=output_schema_error,
                lifecycle_events=(*_COMMON_V0_LIFECYCLE_EVENTS, "subagent.execution.failed"),
                evidence_extra={
                    **base_evidence,
                    "failure_kind": "invalid_output_schema",
                    "output_schema_valid": False,
                    "schema_error": output_schema_error,
                },
            )

        scenario = str(payload.get("scenario") or "")
        if scenario == "provider_failure" or payload.get("provider_failure") is not None:
            failure = payload.get("provider_failure")
            error_type = type(failure).__name__ if failure is not None else "ProviderFailure"
            return self._failed_contract(
                context,
                payload=self._contract_result(status="failed").to_payload(),
                reason=error_type,
                lifecycle_events=(
                    *_COMMON_V0_LIFECYCLE_EVENTS,
                    "subagent.provider.called",
                    "subagent.execution.failed",
                ),
                evidence_extra={
                    **base_evidence,
                    "provider_called": False,
                    "provider_error_type": error_type,
                    "safe_error_metadata": {
                        "error_type": error_type,
                        "error_hash": stable_hash(error_type, prefix="error"),
                        "redacted": True,
                    },
                },
            )
        if scenario == "skipped":
            return self._skipped_contract(context, base_evidence=base_evidence)
        if scenario == "policy_blocked":
            return self._policy_blocked(
                context,
                profile=profile,
                v0_request=v0_request,
                requested_operation=str(payload.get("blocked_operation") or "contract_policy"),
                capability_flag=str(payload.get("capability_flag") or "contract_policy"),
                base_evidence=base_evidence,
            )

        if not provider_mode_allowed(profile=profile, request=v0_request):
            return self._policy_blocked(
                context,
                profile=profile,
                v0_request=v0_request,
                requested_operation="call_provider",
                capability_flag="can_call_provider",
                base_evidence={
                    **base_evidence,
                    "provider_call_allowed": False,
                    "real_call_allowed": False,
                },
            )

        provider_output = payload.get("provider_output")
        if isinstance(provider_output, Mapping) and provider_output.get("type") == "tool_use":
            return self._tool_request_result(
                context,
                profile=profile,
                v0_request=v0_request,
                provider_output=dict(provider_output),
                base_evidence=base_evidence,
            )

        if provider_output is not None:
            if isinstance(provider_output, Mapping) and "batch_memory" in provider_output:
                return self._policy_blocked(
                    context,
                    profile=profile,
                    v0_request=v0_request,
                    requested_operation="write_memory",
                    capability_flag="can_write_memory",
                    base_evidence={
                        **base_evidence,
                        "batch_memory_seen": False,
                        "memory_proposals_count": 0,
                        "pending_memory_proposal_created": False,
                    },
                )
            valid, safe_output, validation_error = validate_structured_output(
                profile.output_schema,
                provider_output,
            )
            if not valid:
                return self._failed_contract(
                    context,
                    payload=self._contract_result(status="failed").to_payload(),
                    reason=validation_error,
                    lifecycle_events=(
                        *_COMMON_V0_LIFECYCLE_EVENTS,
                        "subagent.execution.failed",
                    ),
                    evidence_extra={
                        **base_evidence,
                        "failure_kind": "output_schema_validation_failed",
                        "output_schema_valid": True,
                        "output_validation_error": validation_error,
                    },
                )
            result = self._contract_result(status="success", safe_output=safe_output)
            return context.success(
                handler_name=type(self).__name__,
                target_module="SubAgentV0Contract",
                payload=result.to_payload(),
                observed_call=None,
                parent_adjudicated=False,
                evidence_extra={
                    **base_evidence,
                    "output_schema_valid": True,
                    "safe_structured_result": True,
                    "lifecycle_events": (
                        *_COMMON_V0_LIFECYCLE_EVENTS,
                        "subagent.result.produced",
                        "subagent.parent_decision.pending",
                    ),
                    "event": "subagent.parent_decision.pending",
                },
            )

        child_result = payload.get("child_result")
        if child_result is not None:
            parent_decision = payload.get("parent_decision")
            decision_type = ""
            parent_decision_status = "pending"
            lifecycle_events = (
                *_COMMON_V0_LIFECYCLE_EVENTS,
                "subagent.result.produced",
                "subagent.parent_decision.pending",
            )
            event = "subagent.parent_decision.pending"
            if isinstance(parent_decision, Mapping):
                decision_type = str(parent_decision.get("decision_type") or "")
                if decision_type:
                    parent_decision_status = "applied"
                    lifecycle_events = (
                        *lifecycle_events,
                        "subagent.parent_decision.applied",
                    )
                    event = "subagent.parent_decision.applied"
            result = SubAgentV0Result(
                status="success",
                parent_decision_status=parent_decision_status,
                decision_type=decision_type,
                adopted=False,
            )
            return context.success(
                handler_name=type(self).__name__,
                target_module="SubAgentV0Contract",
                payload=result.to_payload(),
                observed_call=None,
                parent_adjudicated=False,
                evidence_extra={
                    **base_evidence,
                    "lifecycle_events": lifecycle_events,
                    "event": event,
                },
            )

        result = self._contract_result(status="success")
        return context.success(
            handler_name=type(self).__name__,
            target_module="SubAgentV0Contract",
            payload=result.to_payload(),
            observed_call=None,
            parent_adjudicated=False,
            evidence_extra={
                **base_evidence,
                "contract_only": True,
                "not_implemented": True,
                "provider_call_allowed": profile.capability_flags.can_call_provider,
                "lifecycle_events": (
                    *_COMMON_V0_LIFECYCLE_EVENTS,
                    "subagent.result.produced",
                    "subagent.parent_decision.pending",
                )
                if scenario == "success"
                else _COMMON_V0_LIFECYCLE_EVENTS,
                "event": "subagent.execution.started",
            },
        )

    def _base_evidence(
        self,
        profile: SubAgentV0ProfileContract,
        v0_request: SubAgentV0Request,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        context_metadata = dict(v0_request.prepared_context_metadata)
        flags = dict(profile.capability_flags.to_mapping())
        provider_allowed = (
            profile.capability_flags.can_call_provider
            and provider_mode_allowed(profile=profile, request=v0_request)
        )
        return {
            "request_type": "SubAgentV0Request",
            "handler_type": "SubAgentV0Handler",
            "executor_type": "SubAgentV0Executor",
            "parser_type": "SubAgentV0OutputParser",
            "sanitizer_type": "SubAgentV0ResultSanitizer",
            "result_type": "SubAgentV0Result",
            "evidence_recorder_type": "RuntimeActionDispatcher",
            "profile_contract": profile.to_safe_evidence(),
            "profile_id": profile.profile_id,
            "profile_status": profile.status,
            "product_capability": profile.product_capability,
            "provider_mode": v0_request.provider_mode,
            "provider_mode_allowed": profile.provider_mode_allowed,
            "provider_call_allowed": provider_allowed,
            "real_call_allowed": (
                v0_request.provider_mode == "real_opt_in"
                and provider_allowed
            ),
            "network_allowed": False,
            "activated_from_environment": False,
            "provider_secret_present": isinstance(payload.get("ambient_env"), Mapping),
            "secret_material_exposed": False,
            "max_turns": profile.max_turns,
            "allowed_tool_count": len(profile.allowed_tools),
            "allowed_tools": profile.allowed_tools,
            "memory_scope": "none",
            "context_metadata": context_metadata,
            "uncontrolled_path_read_text_calls": int(
                context_metadata.get("uncontrolled_path_read_text_calls", 0)
            ),
            "parent_policy_selects_all_files": bool(
                context_metadata.get("parent_policy_selects_all_files", True)
            ),
            "second_runtime_created": False,
            "autonomous_child_loop": False,
            "l2_revision_loop": False,
            "batch_memory_seen": False,
            "legacy_fallback_used": False,
            "legacy_adjudication_called": False,
            "tool_executed": False,
            "memory_store_write": False,
            "memory_runtime_direct_write": False,
            "checkpoint_write": False,
            "checkpoint_metadata": self._checkpoint_metadata(profile, status="contract_only"),
            "parent_messages_mutated": False,
            "parent_checkpoint_mutated": False,
            "context_mutated": False,
            "prompt_mutated": False,
            "messages_mutated": False,
            "memory_mutated": False,
            "checkpoint_mutated": False,
            "direct_parent_action_emitted": False,
            "tool_result_hash": stable_hash(
                payload.get("raw_child_tool_result"),
                prefix="toolresult",
            ),
            "raw_child_result_hash": stable_hash(
                payload.get("raw_child_result"),
                prefix="childresult",
            ),
            "action_log": self._safe_action_log_preview(profile, v0_request),
            "log_viewer": {
                "subsystem": "subagent_v0",
                "event_count": 1,
                "redacted": True,
            },
            "lifecycle_event_payloads": self._lifecycle_event_payloads(
                profile,
                v0_request,
                _COMMON_V0_LIFECYCLE_EVENTS,
            ),
            "redacted": True,
            "request_hash": v0_request.task_hash,
            **flags,
        }

    def _policy_blocked(
        self,
        context: RuntimeActionContext,
        *,
        profile: SubAgentV0ProfileContract,
        v0_request: SubAgentV0Request,
        requested_operation: str,
        capability_flag: str,
        base_evidence: dict[str, Any],
    ):
        result = self._contract_result(status="policy_blocked")
        blocked_metadata = dict(_V0_POLICY_METADATA)
        evidence_extra = {
            **base_evidence,
            "provider_mode": (
                "fake_local"
                if v0_request.provider_mode == "real_opt_in"
                and not v0_request.parent_opt_in
                else v0_request.provider_mode
            ),
            "provider_call_allowed": (
                False
                if capability_flag == "can_call_provider"
                else base_evidence.get("provider_call_allowed", False)
            ),
            "real_call_allowed": False,
            "blocked_operation": requested_operation,
            "capability_flag": capability_flag,
            "blocked_policy_metadata": blocked_metadata,
            "skipped_policy_metadata": blocked_metadata,
            "lifecycle_events": (*_COMMON_V0_LIFECYCLE_EVENTS, "subagent.policy.blocked"),
            "event": "subagent.policy.blocked",
            "contract_only": True,
        }
        return context.result(
            status="policy_blocked",
            handler_name=type(self).__name__,
            target_module="SubAgentV0Contract",
            payload=result.to_payload(),
            observed_call=None,
            parent_adjudicated=False,
            evidence_extra=evidence_extra,
            error_safe_preview="subagent v0 policy blocked",
        )

    def _skipped_contract(
        self,
        context: RuntimeActionContext,
        *,
        base_evidence: dict[str, Any],
    ):
        result = self._contract_result(status="skipped")
        metadata = dict(_V0_POLICY_METADATA)
        lifecycle_events = (*_COMMON_V0_LIFECYCLE_EVENTS, "subagent.execution.skipped")
        return context.result(
            status="skipped",
            handler_name=type(self).__name__,
            target_module="SubAgentV0Contract",
            payload=result.to_payload(),
            observed_call=None,
            parent_adjudicated=False,
            evidence_extra={
                **base_evidence,
                "skipped_policy_metadata": metadata,
                "lifecycle_events": lifecycle_events,
                "event": "subagent.execution.skipped",
                "contract_only": True,
            },
        )

    def _failed_contract(
        self,
        context: RuntimeActionContext,
        *,
        payload: dict[str, Any],
        reason: str,
        lifecycle_events: tuple[str, ...],
        evidence_extra: dict[str, Any] | None = None,
    ):
        return context.failed(
            handler_name=type(self).__name__,
            target_module="SubAgentV0Contract",
            payload=payload,
            observed_call=None,
            parent_adjudicated=False,
            evidence_extra={
                "contract_only": True,
                "error_type": reason,
                "error_hash": stable_hash(reason, prefix="error"),
                "redacted": True,
                "lifecycle_events": lifecycle_events,
                **dict(evidence_extra or {}),
            },
            error_safe_preview=reason,
        )

    def _tool_request_result(
        self,
        context: RuntimeActionContext,
        *,
        profile: SubAgentV0ProfileContract,
        v0_request: SubAgentV0Request,
        provider_output: dict[str, Any],
        base_evidence: dict[str, Any],
    ):
        tool_name = str(provider_output.get("name") or "")
        if tool_name in _SHELL_LIKE_TOOLS:
            return self._policy_blocked(
                context,
                profile=profile,
                v0_request=v0_request,
                requested_operation="use_tool",
                capability_flag="can_use_tools",
                base_evidence=base_evidence,
            )
        result = SubAgentV0Result(
            status="success",
            needs_parent_tool_request=True,
            requested_tool_name=tool_name,
            requested_tool_reason=str(provider_output.get("reason") or ""),
            safe_arguments_metadata=safe_arguments_metadata(provider_output.get("input")),
        )
        return context.success(
            handler_name=type(self).__name__,
            target_module="SubAgentV0Contract",
            payload=result.to_payload(),
            observed_call=None,
            parent_adjudicated=False,
            evidence_extra={
                **base_evidence,
                "tool_executed": False,
                "tool_request_deferred_to_parent": True,
                "lifecycle_events": (
                    *_COMMON_V0_LIFECYCLE_EVENTS,
                    "subagent.result.produced",
                    "subagent.parent_decision.pending",
                ),
                "event": "subagent.parent_decision.pending",
            },
        )

    def _safe_action_log_preview(
        self,
        profile: SubAgentV0ProfileContract,
        v0_request: SubAgentV0Request,
    ) -> tuple[dict[str, Any], ...]:
        return ({
            "event": "subagent.request.created",
            "profile_id": profile.profile_id,
            "provider_mode": v0_request.provider_mode,
            "redacted": True,
        },)

    def _lifecycle_event_payloads(
        self,
        profile: SubAgentV0ProfileContract,
        v0_request: SubAgentV0Request,
        lifecycle_events: tuple[str, ...],
    ) -> tuple[dict[str, Any], ...]:
        return tuple({
            "event": event,
            "delegation_id": stable_hash(profile.profile_id, prefix="delegation"),
            "parent_trace_id": "parent-trace",
            "profile_id": profile.profile_id,
            "provider_mode": v0_request.provider_mode,
            "redacted": True,
        } for event in lifecycle_events)

    def _scenario_lifecycle_events(self, scenario: str) -> tuple[str, ...]:
        if scenario == "provider_failure":
            return (
                *_COMMON_V0_LIFECYCLE_EVENTS,
                "subagent.provider.called",
                "subagent.execution.failed",
            )
        if scenario == "skipped":
            return (*_COMMON_V0_LIFECYCLE_EVENTS, "subagent.execution.skipped")
        if scenario == "policy_blocked":
            return (*_COMMON_V0_LIFECYCLE_EVENTS, "subagent.policy.blocked")
        return (
            *_COMMON_V0_LIFECYCLE_EVENTS,
            "subagent.provider.called",
            "subagent.provider.completed",
            "subagent.result.produced",
            "subagent.parent_decision.pending",
        )

    def _contract_result(
        self,
        *,
        status: str,
        safe_output: dict[str, Any] | None = None,
    ) -> SubAgentV0Result:
        return SubAgentV0Result(
            status=status,
            safe_output=safe_output or {},
            parent_decision_status="pending",
            adopted=False,
        )

    def _checkpoint_metadata(
        self,
        profile: SubAgentV0ProfileContract,
        *,
        status: str,
    ) -> dict[str, str]:
        return {
            "delegation_id": stable_hash(profile.profile_id, prefix="delegation"),
            "profile_id": profile.profile_id,
            "status": status,
            "result_hash": stable_hash(status, prefix="result"),
            "decision": "pending",
        }

    def _requested_operation(self, payload: dict[str, Any]) -> str:
        if payload.get("requested_operation"):
            return str(payload["requested_operation"])
        provider_output = payload.get("provider_output")
        if isinstance(provider_output, Mapping) and provider_output.get("type") == "tool_use":
            return ""
        if payload.get("raw_child_result") or payload.get("raw_child_tool_result"):
            return "write_checkpoint" if payload.get("raw_child_result") else "use_tool"
        if (
            payload.get("child_requested_files")
            or payload.get("child_prompt_patch")
            or payload.get("child_message")
        ):
            return "modify_parent_context"
        child_result = payload.get("child_result")
        if isinstance(child_result, Mapping) and child_result.get("parent_action"):
            return "emit_parent_action"
        return ""


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
                **{
                    key: value
                    for key, value in result_payload.items()
                    if key
                    not in {
                        "parent_adjudicated",
                        "execution_result",
                        "handoff_note",
                        "adjudication_reason",
                    }
                },
                **_safe_text_metadata(
                    result_payload.get("execution_result", ""),
                    label="execution_result",
                    prefix="childresult",
                ),
                **_safe_text_metadata(
                    result_payload.get("handoff_note", ""),
                    label="handoff_note",
                    prefix="childhandoff",
                ),
                **_safe_text_metadata(
                    result_payload.get("adjudication_reason", ""),
                    label="adjudication_reason",
                    prefix="childreason",
                ),
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
            error_type = type(exc).__name__
            return context.failed(
                handler_name=type(self).__name__,
                target_module="SubAgentExecutor",
                payload={
                    "subagent_name": subagent_name,
                    "delegate_l1_called": True,
                    "failure_reason": error_type,
                },
                observed_call=None,
                parent_adjudicated=True,
                evidence_extra={
                    "delegate_l1_called": True,
                    "error_type": error_type,
                    "redacted": True,
                },
                error_safe_preview=f"L1 delegation failed: {error_type}",
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
                            **_safe_text_metadata(
                                getattr(result, "summary", "") if result else "",
                                label="summary",
                                prefix="childsummary",
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
                            **_safe_text_metadata(
                                getattr(adjudication, "reason", ""),
                                label="adjudication_reason",
                                prefix="childreason",
                            ),
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
                **{
                    key: value
                    for key, value in result_payload.items()
                    if key
                    not in {
                        "parent_adjudicated",
                        "execution_result",
                        "adjudication_reason",
                    }
                },
                **_safe_text_metadata(
                    result_payload.get("execution_result", ""),
                    label="execution_result",
                    prefix="childresult",
                ),
                **_safe_text_metadata(
                    result_payload.get("adjudication_reason", ""),
                    label="adjudication_reason",
                    prefix="childreason",
                ),
            },
        )


def _adjudication_label(action: str) -> str:
    if action == "accept_result":
        return "accept"
    if action == "reject_result":
        return "reject"
    return "needs_review"
