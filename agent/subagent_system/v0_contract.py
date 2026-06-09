"""Sub-agent v0 profile, request, and result contracts.

中文学习边界：
v0 contract 只描述 parent Runtime 允许的 bounded worker 外形。这里不调用
provider、不执行工具、不写 Memory/Checkpoint，也不读取真实文件系统。handler
可以用这些类型做 fail-closed gate；真正执行路径必须等 U4。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

V0_PROFILE_STATUSES = frozenset({"demo", "product", "deprecated"})
V0_PROVIDER_MODE_ALLOWED = frozenset({"fake_only", "fake_and_real", "real_opt_in"})
V0_PROVIDER_MODES = frozenset({"fake_local", "real_opt_in", "disabled"})
V0_RESULT_STATUSES = frozenset({
    "success",
    "failed",
    "skipped",
    "policy_blocked",
})
V0_PARENT_DECISION_STATUSES = frozenset({"pending", "applied", "none"})
V0_CAPABILITY_FLAG_NAMES = (
    "can_call_provider",
    "can_use_tools",
    "can_write_memory",
    "can_request_memory",
    "can_write_checkpoint",
    "can_spawn_child",
    "can_modify_parent_context",
    "can_emit_parent_action",
)
DEFAULT_V0_MAX_CONTEXT_CHARS = 100_000
DEFAULT_V0_MAX_FILES = 20
DEFAULT_V0_OUTPUT_SCHEMA: Mapping[str, Any] = MappingProxyType({
    "type": "object",
    "required": ("summary",),
    "properties": MappingProxyType({
        "summary": MappingProxyType({"type": "string"}),
    }),
})


def stable_hash(value: object, *, prefix: str = "sha256") -> str:
    raw = str(value or "")
    if not raw:
        return ""
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def safe_arguments_metadata(value: object) -> dict[str, Any]:
    """Return shape-only metadata for child-requested arguments."""

    if isinstance(value, Mapping):
        key_fingerprint = _stable_repr(tuple(sorted(str(key) for key in value)))
        return {
            "argument_count": len(value),
            "args_key_count": len(value),
            "args_keys_hash": stable_hash(key_fingerprint, prefix="argkeys"),
            "arguments_hash": stable_hash(_stable_repr(value), prefix="args"),
            "redacted": True,
        }
    return {
        "argument_count": 0,
        "args_key_count": 0,
        "args_keys_hash": "",
        "arguments_hash": stable_hash(type(value).__name__, prefix="args"),
        "redacted": True,
    }


def sanitize_provider_value_for_result(
    value: object,
    *,
    expected_type: str = "",
    field_name: str = "",
) -> dict[str, Any]:
    """Project provider-derived values into result-safe metadata only.

    中文学习边界：即使 output_schema 允许某个 string 字段，字段值仍可能来自
    provider raw output。v0 contract result 不能返回原文，只返回 hash/length/shape。
    """

    del field_name
    if isinstance(value, str):
        return {
            "type": "string",
            "length": len(value),
            "value_hash": stable_hash(value, prefix="value"),
            "redacted": True,
            "redaction_reason": "provider_text_redacted",
            "forbidden_raw_text_detected": contains_forbidden_raw_text(value),
        }
    if isinstance(value, bool):
        return {
            "type": "boolean",
            "value": value,
            "redacted": False,
        }
    if isinstance(value, int) and not isinstance(value, bool):
        return {
            "type": "integer",
            "value": value,
            "redacted": False,
        }
    if isinstance(value, float):
        return {
            "type": "number",
            "value": value,
            "redacted": False,
        }
    if value is None:
        return {
            "type": expected_type or "null",
            "value": None,
            "redacted": False,
        }
    if isinstance(value, Mapping):
        key_fingerprint = _stable_repr(tuple(sorted(str(key) for key in value)))
        children = tuple(
            {
                "key_hash": stable_hash(str(key), prefix="key"),
                "value": sanitize_provider_value_for_result(item),
            }
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
        return {
            "type": "object",
            "key_count": len(value),
            "keys_hash": stable_hash(key_fingerprint, prefix="keys"),
            "value_hash": stable_hash(_stable_repr(value), prefix="value"),
            "children": children,
            "redacted": True,
            "redaction_reason": "provider_object_redacted",
            "forbidden_raw_text_detected": contains_forbidden_raw_text(value),
        }
    if isinstance(value, (list, tuple)):
        return {
            "type": "array",
            "length": len(value),
            "value_hash": stable_hash(_stable_repr(value), prefix="value"),
            "items": tuple(sanitize_provider_value_for_result(item) for item in value),
            "redacted": True,
            "redaction_reason": "provider_array_redacted",
            "forbidden_raw_text_detected": contains_forbidden_raw_text(value),
        }
    return {
        "type": type(value).__name__,
        "value_hash": stable_hash(_stable_repr(value), prefix="value"),
        "redacted": True,
        "redaction_reason": "provider_value_redacted",
        "forbidden_raw_text_detected": contains_forbidden_raw_text(value),
    }


def sanitize_text_metadata(
    value: object,
    *,
    label: str,
    prefix: str,
) -> dict[str, Any]:
    raw = str(value or "")
    return {
        f"{label}_present": bool(raw),
        f"{label}_length": len(raw),
        f"{label}_hash": stable_hash(raw, prefix=prefix),
        f"{label}_redacted": True,
    }


def contains_forbidden_raw_text(value: object) -> bool:
    """Detect sensitive-looking raw text without returning the text."""

    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in (
            "raw_prompt",
            "raw provider",
            "raw_provider",
            "raw_output",
            "raw_context",
            "raw_exception",
            "secret",
            "api_key",
            "apikey",
            "token",
            "bearer ",
        )):
            return True
        if "/" in value or "\\" in value:
            return True
        return "sk-" in value
    if isinstance(value, Mapping):
        return any(
            contains_forbidden_raw_text(key) or contains_forbidden_raw_text(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(contains_forbidden_raw_text(item) for item in value)
    return False


@dataclass(frozen=True, slots=True)
class SubAgentV0CapabilityFlags:
    """Contract-level gates for Sub-agent v0 behavior."""

    can_call_provider: bool = True
    can_use_tools: bool = False
    can_write_memory: bool = False
    can_request_memory: bool = False
    can_write_checkpoint: bool = False
    can_spawn_child: bool = False
    can_modify_parent_context: bool = False
    can_emit_parent_action: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None = None) -> SubAgentV0CapabilityFlags:
        data = dict(value or {})
        return cls(**{
            name: bool(data.get(name, getattr(cls(), name)))
            for name in V0_CAPABILITY_FLAG_NAMES
        })

    def to_mapping(self) -> Mapping[str, bool]:
        return MappingProxyType({
            name: bool(getattr(self, name))
            for name in V0_CAPABILITY_FLAG_NAMES
        })


@dataclass(frozen=True, slots=True)
class SubAgentV0ProfileContract:
    """Product v0 profile contract with safe defaults."""

    profile_id: str = "default-v0"
    status: str = "product"
    provider_mode_allowed: str = "fake_only"
    max_turns: int = 1
    max_context_chars: int = DEFAULT_V0_MAX_CONTEXT_CHARS
    max_files: int = DEFAULT_V0_MAX_FILES
    allowed_tools: tuple[str, ...] = ()
    output_schema: Mapping[str, Any] = field(default_factory=lambda: DEFAULT_V0_OUTPUT_SCHEMA)
    capability_flags: SubAgentV0CapabilityFlags = field(
        default_factory=SubAgentV0CapabilityFlags
    )

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> SubAgentV0ProfileContract:
        raw_profile = payload.get("profile_contract")
        profile_data = dict(raw_profile) if isinstance(raw_profile, Mapping) else {}
        capability_data: dict[str, Any] = {}
        raw_capability_flags = profile_data.get("capability_flags")
        if isinstance(raw_capability_flags, Mapping):
            capability_data.update(raw_capability_flags)
        raw_profile_capabilities = payload.get("profile_capabilities")
        if isinstance(raw_profile_capabilities, Mapping):
            capability_data.update(raw_profile_capabilities)
        for name in V0_CAPABILITY_FLAG_NAMES:
            if name in profile_data:
                capability_data[name] = profile_data[name]

        profile_id = str(
            profile_data.get("profile_id") or payload.get("profile_id") or "default-v0"
        )
        status = str(
            profile_data.get("status")
            or payload.get("requested_profile_status")
            or "product"
        )
        provider_mode_allowed = str(profile_data.get("provider_mode_allowed") or "fake_only")
        max_turns = _coerce_positive_int(
            profile_data.get("max_turns", payload.get("max_turns")),
            default=1,
        )
        max_context_chars = _coerce_positive_int(
            profile_data.get("max_context_chars", payload.get("max_context_chars")),
            default=DEFAULT_V0_MAX_CONTEXT_CHARS,
        )
        max_files = _coerce_positive_int(
            profile_data.get("max_files", payload.get("max_files")),
            default=DEFAULT_V0_MAX_FILES,
        )
        allowed_tools = _as_str_tuple(
            profile_data.get("allowed_tools", payload.get("allowed_tools", ()))
        )
        output_schema = profile_data.get(
            "output_schema",
            payload.get("output_schema", DEFAULT_V0_OUTPUT_SCHEMA),
        )
        return cls(
            profile_id=profile_id,
            status=status,
            provider_mode_allowed=provider_mode_allowed,
            max_turns=max_turns,
            max_context_chars=max_context_chars,
            max_files=max_files,
            allowed_tools=allowed_tools,
            output_schema=dict(output_schema) if isinstance(output_schema, Mapping) else {},
            capability_flags=SubAgentV0CapabilityFlags.from_mapping(capability_data),
        )

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("profile_id is required")
        if self.status not in V0_PROFILE_STATUSES:
            raise ValueError("invalid SubAgentV0 profile status")
        if self.provider_mode_allowed not in V0_PROVIDER_MODE_ALLOWED:
            raise ValueError("invalid provider_mode_allowed")
        if self.max_turns != 1:
            raise ValueError("SubAgent v0 max_turns must be 1")
        if self.max_context_chars < 0:
            raise ValueError("max_context_chars must be non-negative")
        if self.max_files < 0:
            raise ValueError("max_files must be non-negative")
        object.__setattr__(self, "allowed_tools", tuple(self.allowed_tools))
        object.__setattr__(self, "output_schema", MappingProxyType(dict(self.output_schema)))

    @property
    def product_capability(self) -> bool:
        return self.status == "product"

    def to_safe_evidence(self) -> dict[str, Any]:
        flags = dict(self.capability_flags.to_mapping())
        return {
            "profile_id": self.profile_id,
            "status": self.status,
            "provider_mode_allowed": self.provider_mode_allowed,
            "max_turns": self.max_turns,
            "max_context_chars": self.max_context_chars,
            "max_files": self.max_files,
            "allowed_tools": self.allowed_tools,
            "output_schema_id": stable_hash(
                _schema_fingerprint(self.output_schema),
                prefix="schema",
            ),
            "capability_flags": MappingProxyType(flags),
            **flags,
        }


@dataclass(frozen=True, slots=True)
class SubAgentV0Request:
    """Sanitized RuntimeAction payload projection for v0."""

    profile_id: str
    provider_mode: str
    parent_opt_in: bool
    task_hash: str
    prepared_context_metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> SubAgentV0Request:
        provider_mode = str(payload.get("provider_mode") or "fake_local")
        if provider_mode not in V0_PROVIDER_MODES:
            provider_mode = "disabled"
        prepared = payload.get("prepared_v0_context")
        context_metadata: Mapping[str, Any] = {}
        if isinstance(prepared, Mapping) and isinstance(prepared.get("metadata"), Mapping):
            context_metadata = dict(prepared["metadata"])
        return cls(
            profile_id=str(payload.get("profile_id") or "default-v0"),
            provider_mode=provider_mode,
            parent_opt_in=bool(payload.get("parent_opt_in")),
            task_hash=stable_hash(payload.get("task", ""), prefix="task"),
            prepared_context_metadata=MappingProxyType(dict(context_metadata)),
        )


@dataclass(frozen=True, slots=True)
class SubAgentV0Result:
    """Safe structured v0 result contract."""

    status: str
    safe_output: Mapping[str, Any] = field(default_factory=dict)
    needs_parent_tool_request: bool = False
    requested_tool_name: str = ""
    requested_tool_reason_metadata: Mapping[str, Any] = field(default_factory=dict)
    safe_arguments_metadata: Mapping[str, Any] = field(default_factory=dict)
    parent_decision_status: str = "pending"
    decision_type: str = ""
    adopted: bool = False

    def __post_init__(self) -> None:
        if self.status not in V0_RESULT_STATUSES:
            raise ValueError("invalid SubAgentV0Result status")
        if self.parent_decision_status not in V0_PARENT_DECISION_STATUSES:
            raise ValueError("invalid parent decision status")
        object.__setattr__(self, "safe_output", MappingProxyType(dict(self.safe_output)))
        object.__setattr__(
            self,
            "requested_tool_reason_metadata",
            MappingProxyType(dict(self.requested_tool_reason_metadata)),
        )
        object.__setattr__(
            self,
            "safe_arguments_metadata",
            MappingProxyType(dict(self.safe_arguments_metadata)),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "safe_output": dict(self.safe_output),
            "needs_parent_tool_request": self.needs_parent_tool_request,
            "requested_tool_name": self.requested_tool_name,
            "requested_tool_reason_metadata": dict(self.requested_tool_reason_metadata),
            "safe_arguments_metadata": dict(self.safe_arguments_metadata),
            "parent_decision_status": self.parent_decision_status,
            "decision_type": self.decision_type,
            "adopted": self.adopted,
        }


def provider_mode_allowed(
    *,
    profile: SubAgentV0ProfileContract,
    request: SubAgentV0Request,
) -> bool:
    if request.provider_mode == "disabled":
        return False
    if request.provider_mode == "fake_local":
        return profile.provider_mode_allowed in V0_PROVIDER_MODE_ALLOWED
    if request.provider_mode == "real_opt_in":
        return (
            profile.provider_mode_allowed in {"fake_and_real", "real_opt_in"}
            and request.parent_opt_in
        )
    return False


def validate_output_schema_contract(schema: Mapping[str, Any]) -> tuple[bool, str]:
    """Validate the small JSON-schema subset v0 accepts in U3."""

    if not isinstance(schema, Mapping):
        return False, "schema_not_mapping"
    if schema.get("type") != "object":
        return False, "schema_type_must_be_object"
    required = schema.get("required", ())
    if required is None:
        required = ()
    if not isinstance(required, (list, tuple)):
        return False, "schema_required_must_be_sequence"
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        return False, "schema_properties_must_be_mapping"
    for field_name in required:
        if str(field_name) not in properties:
            return False, "required_field_missing_property"
    return True, ""


def validate_structured_output(
    output_schema: Mapping[str, Any],
    provider_output: object,
) -> tuple[bool, dict[str, Any], str]:
    schema_ok, schema_error = validate_output_schema_contract(output_schema)
    if not schema_ok:
        return False, {}, schema_error
    if not isinstance(provider_output, Mapping):
        return False, {}, "provider_output_not_mapping"
    required = tuple(str(item) for item in output_schema.get("required", ()))
    properties = output_schema.get("properties", {})
    for field_name in required:
        if field_name not in provider_output:
            return False, {}, "required_output_field_missing"
    safe_output: dict[str, Any] = {}
    for field_name, raw_spec in dict(properties).items():
        if field_name not in provider_output:
            continue
        expected_type = str(raw_spec.get("type") if isinstance(raw_spec, Mapping) else "")
        value = provider_output[field_name]
        if expected_type and not _matches_schema_type(value, expected_type):
            return False, {}, "output_field_type_mismatch"
        safe_output[field_name] = sanitize_provider_value_for_result(
            value,
            expected_type=expected_type,
            field_name=field_name,
        )
    return True, safe_output, ""


def _matches_schema_type(value: object, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, Mapping)
    if expected_type == "array":
        return isinstance(value, (list, tuple))
    return False


def _coerce_positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _as_str_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


def _schema_fingerprint(schema: Mapping[str, Any]) -> str:
    return _stable_repr(schema)


def _stable_repr(value: object) -> str:
    if isinstance(value, Mapping):
        return "{" + ",".join(
            f"{key}:{_stable_repr(value[key])}" for key in sorted(value, key=str)
        ) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_stable_repr(item) for item in value) + "]"
    return repr(value)
