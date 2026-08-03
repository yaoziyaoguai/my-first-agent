"""受治理的唯一 Tool Runtime。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Protocol

from agent.runtime.contracts import (
    ApprovalGrant,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalRequired,
    ExecutionIntent,
    JSONValue,
    KnownExecutedError,
    KnownNotExecuted,
    PolicyDecision,
    SideEffectClass,
    ToolCall,
    ToolDefinition,
    ToolPreparation,
    ToolPrepareContext,
    ToolResult,
    ToolSpec,
)

ToolCallable = Callable[..., object]
BindingPreparer = Callable[[dict[str, JSONValue]], dict[str, JSONValue]]


class IntentConflictError(RuntimeError):
    """执行意图与已经准备/持久化的合同不一致。"""


class ToolPolicy(Protocol):
    identity: str

    def evaluate(
        self,
        spec: ToolSpec,
        arguments: dict[str, JSONValue],
        binding: dict[str, JSONValue],
    ) -> PolicyDecision:
        """只基于结构化元数据作出治理决定。"""


class DefaultToolPolicy:
    identity = "kernel-default-tool-policy-v1"

    def evaluate(
        self,
        spec: ToolSpec,
        arguments: dict[str, JSONValue],
        binding: dict[str, JSONValue],
    ) -> PolicyDecision:
        del arguments, binding
        if spec.safety_policy.get("enabled") is False:
            return PolicyDecision.DENY
        if spec.approval_policy is ApprovalPolicy.ALWAYS:
            return PolicyDecision.REQUIRE_APPROVAL
        return PolicyDecision.ALLOW


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    spec: ToolSpec
    func: ToolCallable
    prepare_binding: BindingPreparer | None = None
    policy: ToolPolicy | None = None


class KernelToolRuntime:
    def __init__(
        self,
        registrations: tuple[RegisteredTool, ...],
        *,
        policy: ToolPolicy | None = None,
    ) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        for registration in registrations:
            if registration.spec.name in self._tools:
                raise ValueError(f"duplicate tool registration: {registration.spec.name}")
            self._tools[registration.spec.name] = registration
        self._default_policy = policy or DefaultToolPolicy()
        self._invoked_keys: set[str] = set()

    def _policy_for(self, registration: RegisteredTool) -> ToolPolicy:
        # 每个 registration 可绑定自己的 policy identity；未绑定则回退到 runtime 默认策略。
        # 不按工具名路由。
        return registration.policy or self._default_policy

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(registration.spec.definition() for registration in self._tools.values())

    def prepare(
        self,
        call: ToolCall,
        context: ToolPrepareContext,
        approval: ApprovalGrant | None = None,
    ) -> ToolPreparation:
        registration = self._tools.get(call.name)
        if registration is None:
            return self._error(call.tool_call_id, "unknown_tool", "Unknown tool requested.")

        arguments, validation_error = _validate_arguments(
            call.arguments,
            registration.spec.input_schema,
        )
        if validation_error is not None:
            return self._error(call.tool_call_id, "invalid_arguments", validation_error)

        try:
            binding = (
                registration.prepare_binding(arguments)
                if registration.prepare_binding is not None
                else {}
            )
            _canonical_json(binding)
        except Exception:
            return self._error(
                call.tool_call_id,
                "binding_failure",
                "Tool safety preconditions could not be prepared.",
            )

        try:
            decision = self._policy_for(registration).evaluate(
                registration.spec, arguments, binding
            )
        except Exception:
            return self._error(
                call.tool_call_id,
                "policy_failure",
                "Tool policy evaluation failed closed.",
            )
        if decision is PolicyDecision.DENY:
            return self._error(call.tool_call_id, "policy_denied", "Tool policy denied the call.")
        if (
            registration.spec.safety_policy.get("kind") == "memory_remember"
            and context.goal_id is not None
            and context.fact_admission is None
        ):
            return self._error(
                call.tool_call_id,
                "fact_admission_required",
                "Workspace memory requires a Runtime-verified source fact.",
            )
        if (
            registration.spec.safety_policy.get("kind")
            in {"owner_preference_confirm", "owner_preference_correct"}
            and context.preference_admission is None
        ):
            return self._error(
                call.tool_call_id,
                "preference_admission_required",
                "Owner preference mutation requires an exact user-confirmed source fact.",
            )
        if decision is PolicyDecision.REQUIRE_APPROVAL and self._goal_authorizes(
            registration.spec,
            arguments,
            context,
        ):
            decision = PolicyDecision.ALLOW

        intent = self._make_intent(
            call,
            context,
            registration.spec,
            arguments,
            binding,
            self._policy_for(registration).identity,
        )
        if decision is PolicyDecision.REQUIRE_APPROVAL:
            request = self._approval_request(intent, registration.spec, context)
            if approval is None:
                return ApprovalRequired(request)
            if (
                approval.request_id != request.request_id
                or approval.binding_digest != request.binding_digest
            ):
                return self._error(
                    call.tool_call_id,
                    "approval_mismatch",
                    "Approval does not match the current tool intent.",
                )
        return intent

    def invoke(self, intent: ExecutionIntent) -> ToolResult:
        registration = self._tools.get(intent.tool_name)
        if registration is None:
            raise IntentConflictError("intent references an unknown tool")
        if intent.idempotency_key in self._invoked_keys:
            raise IntentConflictError("intent was already invoked")
        if registration.spec.identity_digest != intent.tool_identity:
            raise IntentConflictError("tool identity changed after preparation")
        if _digest_json(intent.arguments) != intent.arguments_digest:
            raise IntentConflictError("intent arguments digest does not match")

        current_binding = (
            registration.prepare_binding(intent.arguments)
            if registration.prepare_binding is not None
            else {}
        )
        if current_binding != intent.safety_binding:
            raise IntentConflictError("tool safety preconditions changed after preparation")
        if self._intent_digest(intent) != intent.intent_digest:
            raise IntentConflictError("intent binding digest does not match")
        try:
            decision = self._policy_for(registration).evaluate(
                registration.spec,
                intent.arguments,
                current_binding,
            )
        except Exception as error:
            raise IntentConflictError("tool policy could not be re-evaluated") from error
        if decision is PolicyDecision.DENY:
            raise IntentConflictError("tool policy now denies the intent")
        intent_context = ToolPrepareContext(
            conversation_id=intent.conversation_id,
            run_id=intent.run_id,
            state_revision=0,
            goal_id=intent.goal_id,
            goal_revision=intent.goal_revision,
            workspace_identity_digest=intent.workspace_identity_digest,
            goal_authorization=intent.goal_authorization,
        )
        if (
            decision is PolicyDecision.REQUIRE_APPROVAL
            and intent.goal_authorization is not None
            and not self._goal_authorizes(
                registration.spec,
                intent.arguments,
                intent_context,
            )
        ):
            raise IntentConflictError("goal authorization changed after preparation")

        self._invoked_keys.add(intent.idempotency_key)
        try:
            raw_result = registration.func(intent)
            if isinstance(raw_result, KnownExecutedError):
                # effect 已发生但明确失败：known-executed error，不能展平为 success（A18/R27）。
                return ToolResult(
                    tool_call_id=intent.tool_call_id,
                    content=raw_result.message[: registration.spec.output_limit_chars],
                    is_error=True,
                    executed=True,
                    metadata={
                        "code": raw_result.code,
                        "tool_identity": registration.spec.identity_digest,
                    },
                )
            if isinstance(raw_result, KnownNotExecuted):
                # executor 在 effect 前证明副作用没有发生：作为普通 tool result 推进游标，
                # 标记 executed=False 让模型修正；不进入 unknown-outcome recovery。
                return ToolResult(
                    tool_call_id=intent.tool_call_id,
                    content=raw_result.message[: registration.spec.output_limit_chars],
                    is_error=True,
                    executed=False,
                    metadata={
                        "code": raw_result.code,
                        "tool_identity": registration.spec.identity_digest,
                    },
                )
            content = _normalize_output(raw_result)
        except Exception:
            if registration.spec.side_effect is not SideEffectClass.READ_ONLY:
                # 写入/外部效果可能已经发生；必须由上层进入 unknown-outcome 恢复态。
                raise
            return ToolResult(
                tool_call_id=intent.tool_call_id,
                content="Tool execution failed."[: registration.spec.output_limit_chars],
                is_error=True,
                executed=False,
                metadata={"code": "tool_error"},
            )
        return ToolResult(
            tool_call_id=intent.tool_call_id,
            content=content[: registration.spec.output_limit_chars],
            metadata={
                "truncated": len(content) > registration.spec.output_limit_chars,
                "tool_identity": registration.spec.identity_digest,
            },
        )

    def _make_intent(
        self,
        call: ToolCall,
        context: ToolPrepareContext,
        spec: ToolSpec,
        arguments: dict[str, JSONValue],
        binding: dict[str, JSONValue],
        policy_identity: str,
    ) -> ExecutionIntent:
        intent = ExecutionIntent(
            tool_call_id=call.tool_call_id,
            tool_name=call.name,
            tool_identity=spec.identity_digest,
            arguments=arguments,
            arguments_digest=_digest_json(arguments),
            intent_digest="",
            idempotency_key=(
                f"{context.conversation_id}:{context.run_id}:{call.tool_call_id}"
            ),
            policy_identity=policy_identity,
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            side_effect=spec.side_effect,
            safety_binding=binding,
            goal_id=context.goal_id,
            goal_revision=context.goal_revision,
            workspace_identity_digest=context.workspace_identity_digest,
            goal_authorization=context.goal_authorization,
            fact_admission=context.fact_admission,
            preference_admission=context.preference_admission,
        )
        return replace(
            intent,
            intent_digest=self._intent_digest(intent),
        )

    def _intent_digest(self, intent: ExecutionIntent) -> str:
        return _digest_json(
            {
                "tool_call_id": intent.tool_call_id,
                "tool_name": intent.tool_name,
                "tool_identity": intent.tool_identity,
                "arguments_digest": intent.arguments_digest,
                "idempotency_key": intent.idempotency_key,
                "policy_identity": intent.policy_identity,
                "conversation_id": intent.conversation_id,
                "run_id": intent.run_id,
                "side_effect": intent.side_effect.value,
                "safety_binding": intent.safety_binding,
                "goal_id": intent.goal_id,
                "goal_revision": intent.goal_revision,
                "workspace_identity_digest": intent.workspace_identity_digest,
                "goal_authorization_digest": (
                    intent.goal_authorization.binding_digest
                    if intent.goal_authorization is not None
                    else None
                ),
                "fact_admission_digest": (
                    intent.fact_admission.binding_digest
                    if intent.fact_admission is not None
                    else None
                ),
                "preference_admission_digest": (
                    intent.preference_admission.binding_digest
                    if intent.preference_admission is not None
                    else None
                ),
            }
        )

    @staticmethod
    def _goal_authorizes(
        spec: ToolSpec,
        arguments: dict[str, JSONValue],
        context: ToolPrepareContext,
    ) -> bool:
        binding = context.goal_authorization
        target = arguments.get("path")
        if (
            binding is None
            or context.goal_id is None
            or context.goal_revision is None
            or context.workspace_identity_digest is None
            or spec.side_effect is not SideEffectClass.WRITE
            or spec.safety_policy.get("workspace_scoped") is not True
            or not isinstance(target, str)
            or target != binding.normalized_target
        ):
            return False
        return binding.authorizes(
            goal_id=context.goal_id,
            goal_revision=context.goal_revision,
            workspace_identity_digest=context.workspace_identity_digest,
            operation=spec.name,
            normalized_target=target,
        )

    def _approval_request(
        self,
        intent: ExecutionIntent,
        spec: ToolSpec,
        context: ToolPrepareContext,
    ) -> ApprovalRequest:
        binding = intent.safety_binding
        preview = binding.get("effect_preview")
        if not isinstance(preview, str):
            preview = f"{spec.name}: {spec.side_effect.value}"
        return ApprovalRequest(
            request_id=f"approval-{intent.intent_digest[:16]}",
            run_id=context.run_id,
            tool_call_id=intent.tool_call_id,
            binding_digest=intent.intent_digest,
            preview=preview,
            tool_name=spec.name,
            state_revision=context.state_revision,
            arguments_digest=intent.arguments_digest,
            policy_identity=intent.policy_identity,
            risk=spec.risk.value,
            side_effect=spec.side_effect.value,
            target_digest=_optional_string(binding.get("target_digest")),
            precondition_digest=_optional_string(binding.get("precondition_digest")),
            new_content_digest=_optional_string(binding.get("new_content_digest")),
        )

    @staticmethod
    def _error(tool_call_id: str, code: str, message: str) -> ToolResult:
        # prepare 阶段的拒绝（unknown_tool/invalid_arguments/policy_denied/approval_mismatch/
        # binding/policy_failure）都发生在 callable 调用之前，是 known-not-executed（A16/A18/R27）。
        return ToolResult(
            tool_call_id=tool_call_id,
            content=message,
            is_error=True,
            executed=False,
            metadata={"code": code},
        )


def _optional_string(value: JSONValue | None) -> str | None:
    return value if isinstance(value, str) else None


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalize_output(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None or isinstance(value, int | float | bool | list | dict):
        return _canonical_json(value)
    raise TypeError(f"unsupported tool output type: {type(value).__name__}")


def _validate_arguments(
    arguments: dict[str, JSONValue],
    schema: dict[str, JSONValue],
) -> tuple[dict[str, JSONValue], str | None]:
    if schema.get("type") != "object":
        return {}, "Tool schema root must be an object."
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        return {}, "Tool schema is malformed."
    if any(not isinstance(name, str) for name in required):
        return {}, "Tool schema required keys are malformed."
    missing = [name for name in required if name not in arguments]
    if missing:
        return {}, f"Missing required arguments: {', '.join(missing)}"
    if schema.get("additionalProperties") is False:
        extra = sorted(set(arguments).difference(properties))
        if extra:
            return {}, f"Unexpected arguments: {', '.join(extra)}"
    for name, value in arguments.items():
        property_schema = properties.get(name)
        if isinstance(property_schema, dict):
            expected = property_schema.get("type")
            if isinstance(expected, str) and not _matches_json_type(value, expected):
                return {}, f"Argument {name} must be {expected}."
    try:
        normalized = json.loads(_canonical_json(arguments))
    except (TypeError, ValueError):
        return {}, "Arguments must be JSON-compatible."
    return normalized, None


def _matches_json_type(value: JSONValue, expected: str) -> bool:
    checks = {
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, int | float) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "array": lambda item: isinstance(item, list),
        "object": lambda item: isinstance(item, dict),
        "null": lambda item: item is None,
    }
    check = checks.get(expected)
    return True if check is None else check(value)
