"""subagent.delegate_l0 RuntimeAction handler.

Path status legend (V3 Sub-agent path-status clarity):

| Handler | Status | 行号 | Notes |
|---|---|---|---|
| `SubAgentV0Handler` | **V0 reg + verified** | `~L306` | reg ≠ routed；live = inline-local |
| `SubAgentDelegateL0Handler` | **L0 probe (compat)** | `~L1257` | test harness compat only |
| `SubAgentDelegateL1Handler` | **L1 frozen (legacy)** | `~L1424` | 历史 L1 prototype，非当前 |

红线：
- 不拆 `SubAgentV0Handler`（V0 设计 spike 单独做）。
- 不恢复 L1 production route；L1 仅作历史参考。
- L0 probe 不被 V0 production path 依赖；它的存活只为兼容 test harness。
- 不把上面 live 描述称为 "V0 当前 production path"——V0 仅 registered + contract-verified。
"""

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
    sanitize_text_metadata,
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
_V0_CONTEXT_METADATA_ALLOWLIST = frozenset({
    "context_hash",
    "context_length",
    "context_file_count",
    "max_context_chars",
    "max_files",
    "profile_id",
    "policy_id",
    "policy_rule_id",
    "policy_hash",
    "policy_decision_source",
    "selected_file_ids",
    "context_read_seam_calls",
    "uncontrolled_path_read_text_calls",
    "parent_policy_selects_all_files",
})
_V0_FORBIDDEN_CONTEXT_METADATA_KEYS = frozenset({
    "policy_path",
    "raw_path",
    "path",
    "file_path",
    "raw_context",
    "context_text",
    "prompt",
    "raw_prompt",
    "raw_output",
    "secret",
    "api_key",
    "token",
    "exception_message",
})
_V0_SAFE_SCALAR_CONTEXT_FIELDS = frozenset({
    "context_hash",
    "context_length",
    "context_file_count",
    "max_context_chars",
    "max_files",
    "profile_id",
    "policy_id",
    "policy_rule_id",
    "policy_hash",
    "policy_decision_source",
    "context_read_seam_calls",
    "uncontrolled_path_read_text_calls",
    "parent_policy_selects_all_files",
})
_V0_REQUIRED_EXECUTION_CONTEXT_FIELDS = frozenset({
    "context_hash",
    "context_length",
    "context_file_count",
    "max_context_chars",
    "max_files",
})
_V0_CONTEXT_GATE_FAILURE_EVENTS = (
    "subagent.request.created",
    "subagent.profile.selected",
    "subagent.execution.failed",
)


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


def _sanitize_v0_context_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Allowlist parent-built v0 context evidence metadata.

    中文学习边界：prepared_v0_context 来自 RuntimeAction payload seam，不能被当作
    可信 evidence。这里仅保留 hash/length/count/policy identifiers 这类安全字段。
    """

    safe: dict[str, Any] = {}
    dropped_count = 0
    for raw_key, raw_value in metadata.items():
        key = str(raw_key)
        if key in _V0_FORBIDDEN_CONTEXT_METADATA_KEYS:
            dropped_count += 1
            continue
        if key not in _V0_CONTEXT_METADATA_ALLOWLIST:
            dropped_count += 1
            continue
        if key == "selected_file_ids":
            safe[key] = _sanitize_selected_file_ids(raw_value)
            continue
        if key in _V0_SAFE_SCALAR_CONTEXT_FIELDS:
            safe[key] = _sanitize_context_scalar(key, raw_value)
            continue
        dropped_count += 1

    if dropped_count:
        safe["context_metadata_redacted"] = True
        safe["dropped_context_metadata_count"] = dropped_count
    return safe


def _sanitize_selected_file_ids(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_items = (value,)
    elif isinstance(value, (list, tuple)):
        raw_items = tuple(str(item) for item in value)
    else:
        return ()
    return tuple(_sanitize_file_id(item) for item in raw_items)


def _sanitize_file_id(file_id: str) -> str:
    if _is_safe_context_identifier(file_id):
        return file_id
    return f"context_file:{stable_hash(file_id, prefix='file')[-16:]}"


def _sanitize_v0_tool_name(
    tool_name: str,
    *,
    allowed_tool_names: Iterable[str],
) -> tuple[str, dict[str, Any]]:
    """Project provider-derived tool names into parent-safe metadata.

    中文学习边界：tool_use.name 来自 child/provider output，不能因为看起来像
    identifier 就原样返回。只有 parent/profile 明确 allowlist 的安全工具名才可
    成为 requested_tool_name；其他情况只返回 hash/length/redacted metadata。
    """

    allowed = (
        tool_name in set(str(name) for name in allowed_tool_names)
        and _is_safe_v0_allowed_tool_identifier(tool_name)
    )
    metadata = {
        "requested_tool_name_present": bool(tool_name),
        "requested_tool_name_length": len(tool_name),
        "requested_tool_name_hash": stable_hash(tool_name, prefix="tool"),
        "requested_tool_name_redacted": not allowed,
        "requested_tool_name_allowed": allowed,
    }
    if allowed:
        return tool_name, metadata
    return "", metadata


def _is_safe_v0_allowed_tool_identifier(tool_name: str) -> bool:
    lowered = tool_name.lower()
    if not tool_name or len(tool_name) > 80:
        return False
    if any(char.isspace() for char in tool_name):
        return False
    if any(marker in lowered for marker in (
        "sk-",
        "api_key",
        "secret",
        "token",
        "password",
    )):
        return False
    if any(marker in tool_name for marker in ("/", "\\", ".", "~", ":")):
        return False
    return all(char.isalnum() or char in {"_"} for char in tool_name)


def _is_safe_context_identifier(value: str) -> bool:
    lowered = value.lower()
    if not value or "/" in value or "\\" in value:
        return False
    return not any(marker in lowered for marker in (
        "secret",
        "api_key",
        "token",
        "password",
        "raw_context",
        "raw_prompt",
        "raw_output",
        "raw_path",
    ))


def _sanitize_context_scalar(key: str, value: object) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return max(0, value)
    if key in {"context_length", "context_file_count", "max_context_chars", "max_files",
               "context_read_seam_calls", "uncontrolled_path_read_text_calls"}:
        return _coerce_nonnegative_int(value)
    if isinstance(value, str) and _is_safe_context_scalar_text(key, value):
        return value
    return {
        f"{key}_hash": stable_hash(value, prefix="metadata"),
        f"{key}_length": len(str(value or "")),
        "redacted": True,
    }


def _is_safe_context_scalar_text(key: str, value: str) -> bool:
    lowered = value.lower()
    if "/" in value or "\\" in value:
        return False
    if any(marker in lowered for marker in (
        "secret",
        "api_key",
        "token",
        "password",
        "raw_context",
        "raw_prompt",
        "raw_output",
        "raw_path",
        "policy_path",
    )):
        return False
    if key == "policy_decision_source":
        return value in {"runtime_contract", "parent_policy", "profile_contract"}
    return True


def _coerce_nonnegative_int(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _provider_call_permitted(
    *,
    profile: SubAgentV0ProfileContract,
    request: SubAgentV0Request,
) -> bool:
    if not profile.capability_flags.can_call_provider:
        return False
    if not provider_mode_allowed(profile=profile, request=request):
        return False
    return request.provider_mode != "real_opt_in" or profile.product_capability


class SubAgentV0Handler:
    """Product v0 RuntimeAction handler.

    Path status: **V0 registered + contract-verified, NOT yet production-routed**。
    V0 设计由这条 handler 主线承担；L0 / L1 / L2 都不是当前 path。
    注意：registered 不等于 production-routed——core.py 仍 routes L1→inline-local
    fallback（execution_mode='local_fake'），V0 production wiring 是 future work
    （see V0_WIRING_DECISION）。

    中文学习边界：
    U4 只实现 parent-controlled、bounded、single-turn 的最小 execution path。
    fake/real provider mode 共用 request/context/result/sanitizer/evidence 路径；
    child 仍不能执行工具、写 Memory/Checkpoint、修改 parent state 或触发 L1/L2。
    """

    def handle(self, request: RuntimeActionRequest, context: RuntimeActionContext):
        payload = dict(request.payload)

        if payload.get("error") == "descriptor_not_found":
            return self._descriptor_not_found(context, payload)

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

        if payload.get("introspect_lifecycle_catalog") is True:
            context_gate = self._bounded_context_gate(
                profile=profile,
                v0_request=v0_request,
            )
            if context_gate:
                return self._context_gate_failed(
                    context,
                    profile=profile,
                    v0_request=v0_request,
                    base_evidence=base_evidence,
                    failure_kind=context_gate,
                )
            return self._lifecycle_catalog_introspection(
                context,
                profile=profile,
                v0_request=v0_request,
                base_evidence=base_evidence,
            )

        output_schema_ok, output_schema_error = validate_output_schema_contract(
            profile.output_schema
        )
        if not output_schema_ok:
            context_gate = self._bounded_context_gate(
                profile=profile,
                v0_request=v0_request,
            )
            if context_gate:
                return self._context_gate_failed(
                    context,
                    profile=profile,
                    v0_request=v0_request,
                    base_evidence=base_evidence,
                    failure_kind=context_gate,
                )
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

        # 中文学习边界：从这里开始的分支都会产生 v0 execution/result outcome。
        # 即使 provider_output/child_result 是测试注入，也不能绕过 parent-built
        # bounded context，否则 lifecycle 会伪造 subagent.context.built。
        context_gate = self._bounded_context_gate(
            profile=profile,
            v0_request=v0_request,
        )
        if context_gate:
            return self._context_gate_failed(
                context,
                profile=profile,
                v0_request=v0_request,
                base_evidence=base_evidence,
                failure_kind=context_gate,
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

        scenario = str(payload.get("scenario") or "")
        if scenario == "provider_failure" or payload.get("provider_failure") is not None:
            provider_gate = self._provider_execution_gate(
                profile=profile,
                v0_request=v0_request,
            )
            if provider_gate:
                return self._provider_gate_failed(
                    context,
                    profile=profile,
                    v0_request=v0_request,
                    base_evidence=base_evidence,
                    failure_kind=provider_gate,
                )
            failure = payload.get("provider_failure")
            error_type = type(failure).__name__ if failure is not None else "ProviderFailure"
            return self._failed_contract(
                context,
                target_module="SubAgentV0Executor",
                payload=self._contract_result(status="failed").to_payload(),
                reason=error_type,
                lifecycle_events=(
                    *_COMMON_V0_LIFECYCLE_EVENTS,
                    "subagent.provider.called",
                    "subagent.execution.failed",
                ),
                evidence_extra={
                    **base_evidence,
                    "execution_started": True,
                    "contract_only": False,
                    "not_implemented": False,
                    "provider_adapter_type": "SubAgentV0ProviderAdapter",
                    "provider_called": True,
                    "provider_completed": False,
                    "provider_error_type": error_type,
                    "failure_kind": "provider_failure",
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

        if not _provider_call_permitted(profile=profile, request=v0_request):
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

        return self._execute_v0(
            context,
            profile=profile,
            v0_request=v0_request,
            payload=payload,
            base_evidence=base_evidence,
        )

    def _base_evidence(
        self,
        profile: SubAgentV0ProfileContract,
        v0_request: SubAgentV0Request,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        context_metadata = _sanitize_v0_context_metadata(
            v0_request.prepared_context_metadata
        )
        flags = dict(profile.capability_flags.to_mapping())
        provider_allowed = _provider_call_permitted(profile=profile, request=v0_request)
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
            "profile_id_metadata": dict(profile.profile_id_metadata),
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
            "allowed_tools_metadata": dict(profile.allowed_tools_metadata),
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
            "checkpoint_metadata": self._checkpoint_metadata(profile, status="pending"),
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

    def _descriptor_not_found(
        self,
        context: RuntimeActionContext,
        payload: dict[str, Any],
    ):
        subagent_name = str(payload.get("subagent_name") or payload.get("profile_id") or "unknown")
        return context.rejected(
            handler_name=type(self).__name__,
            target_module="SubAgentV0Contract",
            payload={},
            observed_call=None,
            parent_adjudicated=False,
            evidence_extra={
                "failure_kind": "descriptor_not_found",
                "subagent_name": subagent_name,
                "execution_started": False,
                "provider_called": False,
                "provider_completed": False,
                "contract_only": True,
                "lifecycle_events": (
                    "subagent.request.created",
                    "subagent.descriptor.not_found",
                ),
                "event": "subagent.descriptor.not_found",
                "error_type": "descriptor_not_found",
                "error_hash": stable_hash("descriptor_not_found", prefix="error"),
                "redacted": True,
            },
            error_safe_preview=f"descriptor not found: {subagent_name}",
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

    def _lifecycle_catalog_introspection(
        self,
        context: RuntimeActionContext,
        *,
        profile: SubAgentV0ProfileContract,
        v0_request: SubAgentV0Request,
        base_evidence: dict[str, Any],
    ):
        """Return lifecycle catalog metadata without claiming child execution.

        中文学习边界：introspection 是诊断/测试 metadata path，不是 v0 child
        execution。即使调用方提供了 valid bounded context，也不能伪造
        context.built、result.produced 或 parent_decision.pending。
        """

        result = self._contract_result(status="skipped")
        lifecycle_events = (
            "subagent.request.created",
            "subagent.profile.selected",
            "subagent.execution.skipped",
        )
        return context.result(
            status="skipped",
            handler_name=type(self).__name__,
            target_module="SubAgentV0Contract",
            payload=result.to_payload(),
            observed_call=None,
            parent_adjudicated=False,
            evidence_extra={
                **base_evidence,
                "lifecycle_event_catalog": _V0_LIFECYCLE_CATALOG,
                "lifecycle_events": lifecycle_events,
                "lifecycle_event_payloads": self._lifecycle_event_payloads(
                    profile,
                    v0_request,
                    lifecycle_events,
                ),
                "action_log": self._safe_action_log_preview(
                    profile,
                    v0_request,
                    lifecycle_events=lifecycle_events,
                ),
                "log_viewer": {
                    "subsystem": "subagent_v0",
                    "event_count": len(lifecycle_events),
                    "redacted": True,
                },
                "checkpoint_metadata": {
                    **self._checkpoint_metadata(
                        profile,
                        status="skipped",
                        result_hash=stable_hash("lifecycle_introspection", prefix="result"),
                    ),
                    "decision": "none",
                },
                "lifecycle_introspection_only": True,
                "execution_started": False,
                "provider_called": False,
                "provider_completed": False,
                "contract_only": True,
                "event": "subagent.execution.skipped",
            },
        )

    def _failed_contract(
        self,
        context: RuntimeActionContext,
        *,
        target_module: str = "SubAgentV0Contract",
        payload: dict[str, Any],
        reason: str,
        lifecycle_events: tuple[str, ...],
        evidence_extra: dict[str, Any] | None = None,
    ):
        return context.failed(
            handler_name=type(self).__name__,
            target_module=target_module,
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

    def _execute_v0(
        self,
        context: RuntimeActionContext,
        *,
        profile: SubAgentV0ProfileContract,
        v0_request: SubAgentV0Request,
        payload: dict[str, Any],
        base_evidence: dict[str, Any],
    ):
        provider_gate = self._provider_execution_gate(profile=profile, v0_request=v0_request)
        if provider_gate:
            return self._provider_gate_failed(
                context,
                profile=profile,
                v0_request=v0_request,
                base_evidence=base_evidence,
                failure_kind=provider_gate,
            )
        context_gate = self._bounded_context_gate(
            profile=profile,
            v0_request=v0_request,
        )
        if context_gate:
            return self._context_gate_failed(
                context,
                profile=profile,
                v0_request=v0_request,
                base_evidence=base_evidence,
                failure_kind=context_gate,
            )

        provider_output = self._call_v0_provider_adapter(
            profile=profile,
            v0_request=v0_request,
            payload=payload,
        )
        valid, safe_output, validation_error = validate_structured_output(
            profile.output_schema,
            provider_output,
        )
        if not valid:
            return self._failed_contract(
                context,
                target_module="SubAgentV0Executor",
                payload=self._contract_result(status="failed").to_payload(),
                reason=validation_error,
                lifecycle_events=(
                    *_COMMON_V0_LIFECYCLE_EVENTS,
                    "subagent.provider.called",
                    "subagent.execution.failed",
                ),
                evidence_extra={
                    **base_evidence,
                    "execution_started": True,
                    "contract_only": False,
                    "not_implemented": False,
                    "provider_adapter_type": "SubAgentV0ProviderAdapter",
                    "provider_called": True,
                    "provider_completed": False,
                    "provider_raw_output_redacted": True,
                    "failure_kind": "output_schema_validation_failed",
                    "output_schema_valid": False,
                    "output_validation_error": validation_error,
                },
            )

        result = self._contract_result(status="success", safe_output=safe_output)
        lifecycle_events = (
            *_COMMON_V0_LIFECYCLE_EVENTS,
            "subagent.provider.called",
            "subagent.provider.completed",
            "subagent.result.produced",
            "subagent.parent_decision.pending",
        )
        return context.success(
            handler_name=type(self).__name__,
            target_module="SubAgentV0Executor",
            payload=result.to_payload(),
            observed_call=None,
            parent_adjudicated=False,
            evidence_extra={
                **base_evidence,
                "execution_started": True,
                "contract_only": False,
                "not_implemented": False,
                "provider_adapter_type": "SubAgentV0ProviderAdapter",
                "provider_called": True,
                "provider_completed": True,
                "provider_raw_output_redacted": True,
                "output_schema_valid": True,
                "safe_structured_result": True,
                "parent_decision_status": "pending",
                "auto_adoption": False,
                "checkpoint_metadata": self._checkpoint_metadata(
                    profile,
                    status="success",
                    result_hash=stable_hash(safe_output, prefix="result"),
                ),
                "lifecycle_events": lifecycle_events,
                "lifecycle_event_payloads": self._lifecycle_event_payloads(
                    profile,
                    v0_request,
                    lifecycle_events,
                ),
                "action_log": self._safe_action_log_preview(
                    profile,
                    v0_request,
                    lifecycle_events=lifecycle_events,
                ),
                "log_viewer": {
                    "subsystem": "subagent_v0",
                    "event_count": len(lifecycle_events),
                    "redacted": True,
                },
                "event": "subagent.parent_decision.pending",
            },
        )

    def _call_v0_provider_adapter(
        self,
        *,
        profile: SubAgentV0ProfileContract,
        v0_request: SubAgentV0Request,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Single v0 provider adapter seam for fake and real modes.

        U4 does not perform network IO. Tests may inject provider_output to exercise
        parsing; otherwise this adapter produces deterministic local structured output
        that still flows through output_schema validation and sanitizer.
        """

        del profile
        if "provider_output" in payload:
            provider_output = payload.get("provider_output")
            return dict(provider_output) if isinstance(provider_output, Mapping) else {
                "_invalid_provider_output_type": type(provider_output).__name__,
            }
        provider_basis = {
            "provider_mode": v0_request.provider_mode,
            "profile_id": v0_request.profile_id,
            "task_hash": v0_request.task_hash,
            "context_hash": v0_request.prepared_context_metadata.get("context_hash", ""),
        }
        return {
            "summary": stable_hash(provider_basis, prefix="v0summary"),
        }

    def _provider_execution_gate(
        self,
        *,
        profile: SubAgentV0ProfileContract,
        v0_request: SubAgentV0Request,
    ) -> str:
        if not profile.capability_flags.can_call_provider:
            return "provider_capability_disabled"
        if not provider_mode_allowed(profile=profile, request=v0_request):
            if v0_request.provider_mode == "real_opt_in" and not v0_request.parent_opt_in:
                return "real_provider_requires_parent_opt_in"
            return "provider_mode_not_allowed"
        if v0_request.provider_mode == "real_opt_in" and not profile.product_capability:
            return "real_provider_requires_product_profile"
        return ""

    def _bounded_context_gate(
        self,
        *,
        profile: SubAgentV0ProfileContract,
        v0_request: SubAgentV0Request,
    ) -> str:
        metadata = dict(v0_request.prepared_context_metadata)
        if not metadata:
            return "context_missing"
        if not set(metadata) >= _V0_REQUIRED_EXECUTION_CONTEXT_FIELDS:
            return "context_metadata_incomplete"
        context_hash = str(metadata.get("context_hash") or "")
        if not context_hash:
            return "context_hash_missing"
        if not _is_safe_context_scalar_text("context_hash", context_hash):
            return "context_hash_unsafe"
        context_length = _coerce_nonnegative_int(metadata.get("context_length"))
        context_file_count = _coerce_nonnegative_int(metadata.get("context_file_count"))
        max_context_chars = _coerce_nonnegative_int(metadata.get("max_context_chars"))
        max_files = _coerce_nonnegative_int(metadata.get("max_files"))
        if max_context_chars > profile.max_context_chars:
            return "context_limit_contract_mismatch"
        if max_files > profile.max_files:
            return "context_limit_contract_mismatch"
        if context_length > profile.max_context_chars or context_length > max_context_chars:
            return "context_length_exceeds_limit"
        if context_file_count > profile.max_files or context_file_count > max_files:
            return "context_file_count_exceeds_limit"
        return ""

    def _provider_gate_failed(
        self,
        context: RuntimeActionContext,
        *,
        profile: SubAgentV0ProfileContract,
        v0_request: SubAgentV0Request,
        base_evidence: dict[str, Any],
        failure_kind: str,
    ):
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
                "failure_kind": failure_kind,
                "blocked_reason_metadata": {
                    "reason_hash": stable_hash(failure_kind, prefix="reason"),
                    "error_type": failure_kind,
                    "redacted": True,
                },
            },
        )

    def _context_gate_failed(
        self,
        context: RuntimeActionContext,
        *,
        profile: SubAgentV0ProfileContract,
        v0_request: SubAgentV0Request,
        base_evidence: dict[str, Any],
        failure_kind: str,
    ):
        lifecycle_events = _V0_CONTEXT_GATE_FAILURE_EVENTS
        return self._failed_contract(
            context,
            target_module="SubAgentV0Executor",
            payload=self._contract_result(status="failed").to_payload(),
            reason=failure_kind,
            lifecycle_events=lifecycle_events,
            evidence_extra={
                **base_evidence,
                "execution_started": False,
                "contract_only": False,
                "not_implemented": False,
                "provider_called": False,
                "provider_completed": False,
                "provider_adapter_type": "SubAgentV0ProviderAdapter",
                "failure_kind": failure_kind,
                "context_built": False,
                "context_missing": failure_kind == "context_missing",
                "context_not_built": True,
                "context_gate_metadata": {
                    "error_type": failure_kind,
                    "error_hash": stable_hash(failure_kind, prefix="context"),
                    "redacted": True,
                },
                "lifecycle_events": lifecycle_events,
                "lifecycle_event_payloads": self._lifecycle_event_payloads(
                    profile,
                    v0_request,
                    lifecycle_events,
                ),
                "action_log": self._safe_action_log_preview(
                    profile,
                    v0_request,
                    lifecycle_events=lifecycle_events,
                ),
                "log_viewer": {
                    "subsystem": "subagent_v0",
                    "event_count": len(lifecycle_events),
                    "redacted": True,
                },
                "checkpoint_metadata": {
                    **self._checkpoint_metadata(
                        profile,
                        status="failed",
                        result_hash=stable_hash(failure_kind, prefix="result"),
                    ),
                    "decision": "none",
                },
            },
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
        raw_tool_name = str(provider_output.get("name") or "")
        if raw_tool_name in _SHELL_LIKE_TOOLS:
            return self._policy_blocked(
                context,
                profile=profile,
                v0_request=v0_request,
                requested_operation="use_tool",
                capability_flag="can_use_tools",
                base_evidence=base_evidence,
            )
        safe_tool_name, tool_name_metadata = _sanitize_v0_tool_name(
            raw_tool_name,
            allowed_tool_names=profile.allowed_tools,
        )
        result = SubAgentV0Result(
            status="success",
            needs_parent_tool_request=True,
            requested_tool_name=safe_tool_name,
            requested_tool_name_metadata=tool_name_metadata,
            requested_tool_reason_metadata=sanitize_text_metadata(
                provider_output.get("reason"),
                label="requested_tool_reason",
                prefix="reason",
            ),
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
        lifecycle_events: tuple[str, ...] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        events = lifecycle_events or ("subagent.request.created",)
        return tuple({
            "event": "subagent.request.created",
            "profile_id": profile.profile_id,
            "provider_mode": v0_request.provider_mode,
            "redacted": True,
        } if event == "subagent.request.created" else {
            "event": event,
            "profile_id": profile.profile_id,
            "provider_mode": v0_request.provider_mode,
            "redacted": True,
        } for event in events)

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
            parent_decision_status="pending" if status == "success" else "none",
            adopted=False,
        )

    def _checkpoint_metadata(
        self,
        profile: SubAgentV0ProfileContract,
        *,
        status: str,
        result_hash: str = "",
    ) -> dict[str, str]:
        return {
            "delegation_id": stable_hash(profile.profile_id, prefix="delegation"),
            "profile_id": profile.profile_id,
            "status": status,
            "result_hash": result_hash or stable_hash(status, prefix="result"),
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
    """Parent Runtime controlled L0 delegation handler.

    Path status: **L0 probe** (compatibility / test harness only).
    V0 product path is `SubAgentV0Handler`; L0 is kept for legacy L0 deterministic
    test harness and inline-local compat. Not part of V0 production path.
    """

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

    Path status: **L1-L2 frozen** (historical / future gated). Loop 3.2a
    frozen implementation; L1/L2 is NOT current production route. V0 production
    uses `SubAgentV0Handler` instead.

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
