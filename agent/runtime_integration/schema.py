"""RuntimeAction schema.

中文学习边界：
schema 只描述 Runtime 与子系统 action handler 之间的不可变消息，不推进
Runtime state，也不代表 target module 已经执行。真正能否算 runtime_e2e
由 `agent.runtime_integration.evidence` 统一判定。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import uuid4
import re


class RuntimeActionType(StrEnum):
    SKILL_SELECT = "skill.select"
    TOOL_REQUEST = "tool.request"
    TOOL_GATE = "tool.gate"
    TOOL_INVOKE = "tool.invoke"
    MEMORY_TURN_END_PROPOSAL = "memory.turn_end_proposal"
    MEMORY_PROPOSE = "memory.propose"
    CHECKPOINT_SAFE_SUMMARY = "checkpoint.safe_summary"
    STREAMING_PROVIDER_CALL = "streaming.provider_call"
    STREAMING_EVENT = "streaming.event"
    SUBAGENT_DELEGATE_L0 = "subagent.delegate_l0"


VALID_RESULT_STATUSES = frozenset({
    "success",
    "rejected",
    "confirmation_required",
    "not_supported",
    "failed",
})

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"api[_-]?key\s*[:=]\s*(?!\[REDACTED\])[^,\s]+", re.IGNORECASE),
    re.compile(r"token\s*[:=]\s*(?!\[REDACTED\])[^,\s]+", re.IGNORECASE),
    re.compile(r"password\s*[:=]\s*(?!\[REDACTED\])[^,\s]+", re.IGNORECASE),
    re.compile(r"Bearer\s+(?!\[REDACTED\])[A-Za-z0-9._-]+", re.IGNORECASE),
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_action_id() -> str:
    return f"act:{uuid4().hex}"


def new_event_id() -> str:
    return f"evt:{uuid4().hex}"


def normalize_action_type(value: str | RuntimeActionType) -> str | RuntimeActionType:
    if isinstance(value, RuntimeActionType):
        return value
    try:
        return RuntimeActionType(str(value))
    except ValueError:
        return str(value)


def action_type_value(value: str | RuntimeActionType) -> str:
    if isinstance(value, RuntimeActionType):
        return value.value
    return str(value)


def deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(deep_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(deep_freeze(item) for item in value)
    return value


def contains_secret_like(value: Any) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _SECRET_PATTERNS)
    if isinstance(value, Mapping):
        # 字段名如 secret_content_detected 是安全布尔标签，不是泄露内容。
        return any(contains_secret_like(item) for item in value.values())
    if isinstance(value, list | tuple | set | frozenset):
        return any(contains_secret_like(item) for item in value)
    return False


@dataclass(frozen=True, slots=True)
class RuntimeActionRequest:
    """RuntimeAction 的不可变请求。

    payload 可能来自 model tool-call arguments，也可能来自 Runtime policy hook。
    它不是证据，只是 action 输入；审计用 proof 必须由 dispatcher observer 生成。
    """

    action_type: RuntimeActionType | str
    source: str
    parent_trace_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    constraints: frozenset[str] | set[str] = field(default_factory=frozenset)
    created_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_type", normalize_action_type(self.action_type))
        object.__setattr__(self, "payload", deep_freeze(dict(self.payload)))
        object.__setattr__(self, "constraints", frozenset(str(item) for item in self.constraints))


@dataclass(frozen=True, slots=True)
class RuntimeActionResult:
    """RuntimeAction 的不可变结果。

    RuntimeActionEvent 会复制这里的 evidence，但 event 仍只是 receipt；不能因为
    event 存在就把 capability 标成 runtime_e2e。
    """

    action_type: RuntimeActionType | str
    action_id: str = field(default_factory=new_action_id)
    status: str = "success"
    payload: Mapping[str, Any] = field(default_factory=dict)
    evidence: Mapping[str, Any] = field(default_factory=dict)
    error_safe_preview: str = ""
    latency_ms: int = 0
    timestamp: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        if self.status not in VALID_RESULT_STATUSES:
            raise ValueError(f"invalid RuntimeActionResult.status: {self.status}")
        if contains_secret_like(self.evidence) or contains_secret_like(self.error_safe_preview):
            raise ValueError("RuntimeActionResult evidence contains secret-like value")
        object.__setattr__(self, "action_type", normalize_action_type(self.action_type))
        object.__setattr__(self, "payload", deep_freeze(dict(self.payload)))
        object.__setattr__(self, "evidence", deep_freeze(dict(self.evidence)))


@dataclass(frozen=True, slots=True)
class RuntimeActionEvent:
    """Dispatcher route receipt。

    这条 event 只说明 RuntimeActionDispatcher 处理过一个 action；没有
    target_module_proof 时，它不能证明目标模块真实执行。
    """

    event_id: str
    action_id: str
    action_type: RuntimeActionType | str
    source: str
    status: str
    evidence: Mapping[str, Any]
    parent_trace_id: str
    timestamp: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_type", normalize_action_type(self.action_type))
        object.__setattr__(self, "evidence", deep_freeze(dict(self.evidence)))
