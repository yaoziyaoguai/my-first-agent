"""RuntimeAction schema.

中文学习边界：
schema 只描述 Runtime 与子系统 action handler 之间的不可变消息，不推进
Runtime state，也不代表 target module 已经执行。真正能否算 runtime_e2e
由 `agent.runtime_integration.evidence` 统一判定。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import uuid4


class RuntimeActionType(StrEnum):
    SKILL_SELECT = "skill.select"
    TOOL_REQUEST = "tool.request"
    TOOL_GATE = "tool.gate"
    TOOL_INVOKE = "tool.invoke"
    TOOL_RESULT = "tool.result"
    MEMORY_TURN_END_PROPOSAL = "memory.turn_end_proposal"
    MEMORY_PROPOSE = "memory.propose"
    MEMORY_RECALL = "memory.recall"
    MEMORY_CONSOLIDATE = "memory.consolidate"
    MEMORY_FORGET = "memory.forget"
    CHECKPOINT_SAFE_SUMMARY = "checkpoint.safe_summary"
    CHECKPOINT_SAVE = "checkpoint.save"
    CHECKPOINT_RESUME = "checkpoint.resume"
    STREAMING_PROVIDER_CALL = "streaming.provider_call"
    # STREAMING_EVENT：单 event 验证和 per-event evidence 收集。
    # handler 已注册（phase1_hook.py），catalog entry 指向 validate_stream_event。
    STREAMING_EVENT = "streaming.event"
    SUBAGENT_DELEGATE_L0 = "subagent.delegate_l0"
    # Loop 3.2a: SubAgent L1 parent-mediated child loop action types
    SUBAGENT_DELEGATE_L1 = "subagent.delegate_l1"
    # Product Sub-agent v0: contract-only handler shell in U3, execution deferred to U4.
    SUBAGENT_DELEGATE_V0 = "subagent.delegate.v0"
    SUBAGENT_CHILD_TOOL_REQUEST = "subagent.child_tool_request"
    SUBAGENT_CHILD_RESULT = "subagent.child_result"
    SUBAGENT_PARENT_ADJUDICATION = "subagent.parent_adjudication"
    # Loop 3.2b: child memory proposal → parent-mediated store write
    SUBAGENT_CHILD_MEMORY_REQUEST = "subagent.child_memory_request"
    # Next-stage D-01: SubAgent L2 native loop action types
    SUBAGENT_DELEGATE_L2 = "subagent.delegate_l2"
    SUBAGENT_CHILD_BATCH_MEMORY = "subagent.child_batch_memory"
    # CLI meta-command action types（Loop 4: Runtime Entry Consolidation）
    # READ_ONLY CLI commands 走 dispatcher 获得 evidence chain，不再绕过统一入口。
    # MUTATING/DELEGATING commands (forget/delegate) 需要 confirmation pipeline 就绪后再迁入。
    CLI_SHOW_MEMORIES = "cli.show_memories"
    CLI_SHOW_SUBAGENTS = "cli.show_subagents"
    MCP_BRIDGE_LIFECYCLE = "mcp.bridge_lifecycle"
    # Phase 3 turn-start skill selection evidence（per-turn probe，非用户可见业务动作）
    SKILL_SELECTION_ENTERED = "skill.selection.entered"
    SKILL_CANDIDATES_BUILT = "skill.candidates.built"
    # Loop 3.4: Advanced Scheduler — runtime-owned action graph executor evidence
    ACTION_PLAN_START = "scheduler.action_plan_start"
    NODE_ENTER = "scheduler.node_enter"
    NODE_EXIT = "scheduler.node_exit"
    NODE_FAILURE = "scheduler.node_failure"
    ACTION_PLAN_COMPLETE = "scheduler.action_plan_complete"


# ── Evidence Kind Classification ──────────────────────────────────────────────

# 中文学习说明：
#   每个 RuntimeActionType 有一个「默认 evidence kind」：business（用户可见业务动作）
#   或 probe（每 turn 无条件运行的内部生命周期检查，大部分时候返回 noop/no_action）。
#   具体 action 结果的 evidence_kind 可以由 handler 的 disposition 进一步细化
#   （例如 TOOL_GATE with _safe_noop → probe, with allowed → business gate）。

# business: 产生用户可见效果的动作（工具调用、记忆写入、subagent 委托、provider 调用）
# probe: 生命周期检查——每 turn 运行但大多数时候无有效结果（gate noop、recall noop 等）
_EVIDENCE_KIND_BUSINESS = "business"
_EVIDENCE_KIND_PROBE = "probe"

_ACTION_TYPE_EVIDENCE_KIND: dict[RuntimeActionType, str] = {
    RuntimeActionType.SKILL_SELECT: _EVIDENCE_KIND_PROBE,
    RuntimeActionType.TOOL_REQUEST: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.TOOL_GATE: _EVIDENCE_KIND_PROBE,
    RuntimeActionType.TOOL_INVOKE: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.TOOL_RESULT: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.MEMORY_TURN_END_PROPOSAL: _EVIDENCE_KIND_PROBE,
    RuntimeActionType.MEMORY_PROPOSE: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.MEMORY_RECALL: _EVIDENCE_KIND_PROBE,
    RuntimeActionType.MEMORY_CONSOLIDATE: _EVIDENCE_KIND_PROBE,
    RuntimeActionType.MEMORY_FORGET: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.CHECKPOINT_SAFE_SUMMARY: _EVIDENCE_KIND_PROBE,
    RuntimeActionType.CHECKPOINT_SAVE: _EVIDENCE_KIND_PROBE,
    RuntimeActionType.CHECKPOINT_RESUME: _EVIDENCE_KIND_PROBE,
    RuntimeActionType.STREAMING_PROVIDER_CALL: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.STREAMING_EVENT: _EVIDENCE_KIND_BUSINESS,
    # SUBAGENT_DELEGATE_L0 每 turn 无差别运行，绝大多数返回 rejected（pure routing
    # check）。当且仅当 handler disposition=delegated 时才升为 business，默认 probe。
    RuntimeActionType.SUBAGENT_DELEGATE_L0: _EVIDENCE_KIND_PROBE,
    # Loop 3.2a: SubAgent L1 类型均为 business（用户可见委托/工具/结果/裁决）
    RuntimeActionType.SUBAGENT_DELEGATE_L1: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.SUBAGENT_DELEGATE_V0: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.SUBAGENT_CHILD_TOOL_REQUEST: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.SUBAGENT_CHILD_RESULT: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.SUBAGENT_PARENT_ADJUDICATION: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.SUBAGENT_CHILD_MEMORY_REQUEST: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.SUBAGENT_DELEGATE_L2: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.SUBAGENT_CHILD_BATCH_MEMORY: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.CLI_SHOW_MEMORIES: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.CLI_SHOW_SUBAGENTS: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.MCP_BRIDGE_LIFECYCLE: _EVIDENCE_KIND_PROBE,
    # Phase 3: turn-start skill selection evidence — per-turn probe
    RuntimeActionType.SKILL_SELECTION_ENTERED: _EVIDENCE_KIND_PROBE,
    RuntimeActionType.SKILL_CANDIDATES_BUILT: _EVIDENCE_KIND_PROBE,
    # Loop 3.4: Scheduler evidence — 全部 business（runtime-owned action graph 决策）
    RuntimeActionType.ACTION_PLAN_START: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.NODE_ENTER: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.NODE_EXIT: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.NODE_FAILURE: _EVIDENCE_KIND_BUSINESS,
    RuntimeActionType.ACTION_PLAN_COMPLETE: _EVIDENCE_KIND_BUSINESS,
}


def classify_action_evidence_kind(
    action_type: RuntimeActionType | str,
) -> str:
    """返回 RuntimeActionType 的默认 evidence kind: ``"business"`` 或 ``"probe"``。

    中文学习说明：
      - business: 用户可见业务动作（工具调用/记忆写入/subagent 委托/provider 调用）
      - probe:  每 turn 无条件运行的生命周期检查（gate noop / recall check / consolidate check）
      - 未知类型默认视为 probe（fail-closed），避免过度宣称
      - 具体 action 的 evidence_kind 由 handler disposition 进一步细化
    """
    if isinstance(action_type, RuntimeActionType):
        return _ACTION_TYPE_EVIDENCE_KIND.get(action_type, _EVIDENCE_KIND_PROBE)
    # 字符串类型：尝试匹配已知 action type
    for known, kind in _ACTION_TYPE_EVIDENCE_KIND.items():
        if known.value == action_type or known.name == action_type:
            return kind
    return _EVIDENCE_KIND_PROBE


VALID_RESULT_STATUSES = frozenset({
    "success",
    "rejected",
    "confirmation_required",
    "not_supported",
    "failed",
    "skipped",
    "policy_blocked",
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
class RuntimeActionSupportDescriptor:
    """RuntimeAction support ownership metadata.

    The catalog is intentionally separate from handler registration. Some
    action types exist as reserved schema/evidence shapes before Sub-agent v0;
    callers must not treat that as production support.
    """

    action_type: RuntimeActionType
    support_status: str
    production_supported: bool
    reserved: bool = False
    expected_behavior: str = ""
    evidence_requirements: str = ""
    raw_child_payload_allowed: bool = False
    subagent_v0_owner: str = ""
    add_handler_now: bool = True


_DEFERRED_SUBAGENT_SUPPORT: dict[RuntimeActionType, RuntimeActionSupportDescriptor] = {
    RuntimeActionType.SUBAGENT_DELEGATE_L0: RuntimeActionSupportDescriptor(
        action_type=RuntimeActionType.SUBAGENT_DELEGATE_L0,
        support_status="compat_only",
        production_supported=False,
        reserved=False,
        expected_behavior="demo/compat L0 route; not product Sub-agent v0 capability",
        evidence_requirements="safe demo/compat metadata only",
        raw_child_payload_allowed=False,
        subagent_v0_owner="Sub-agent v0 product action boundary",
        add_handler_now=True,
    ),
    RuntimeActionType.SUBAGENT_DELEGATE_L1: RuntimeActionSupportDescriptor(
        action_type=RuntimeActionType.SUBAGENT_DELEGATE_L1,
        support_status="compat_only",
        production_supported=False,
        reserved=False,
        expected_behavior="frozen legacy parent-mediated child loop; not product v0",
        evidence_requirements="safe legacy metadata only",
        raw_child_payload_allowed=False,
        subagent_v0_owner="Sub-agent v0 freeze gate",
        add_handler_now=False,
    ),
    RuntimeActionType.SUBAGENT_DELEGATE_L2: RuntimeActionSupportDescriptor(
        action_type=RuntimeActionType.SUBAGENT_DELEGATE_L2,
        support_status="experimental",
        production_supported=False,
        reserved=True,
        expected_behavior="frozen experimental native loop; not product v0",
        evidence_requirements="safe experimental metadata only",
        raw_child_payload_allowed=False,
        subagent_v0_owner="Sub-agent v0 freeze gate",
        add_handler_now=False,
    ),
    RuntimeActionType.SUBAGENT_CHILD_TOOL_REQUEST: RuntimeActionSupportDescriptor(
        action_type=RuntimeActionType.SUBAGENT_CHILD_TOOL_REQUEST,
        support_status="deferred",
        production_supported=False,
        reserved=True,
        expected_behavior="evidence-only or direct-dispatch unsupported/deferred",
        evidence_requirements="safe tool/status/hash metadata only",
        raw_child_payload_allowed=False,
        subagent_v0_owner="Sub-agent v0 child tool ownership",
        add_handler_now=False,
    ),
    RuntimeActionType.SUBAGENT_CHILD_RESULT: RuntimeActionSupportDescriptor(
        action_type=RuntimeActionType.SUBAGENT_CHILD_RESULT,
        support_status="deferred",
        production_supported=False,
        reserved=True,
        expected_behavior="evidence-only or direct-dispatch unsupported/deferred",
        evidence_requirements="safe result status/count/hash metadata only",
        raw_child_payload_allowed=False,
        subagent_v0_owner="Sub-agent v0 child result contract",
        add_handler_now=False,
    ),
    RuntimeActionType.SUBAGENT_PARENT_ADJUDICATION: RuntimeActionSupportDescriptor(
        action_type=RuntimeActionType.SUBAGENT_PARENT_ADJUDICATION,
        support_status="deferred",
        production_supported=False,
        reserved=True,
        expected_behavior="explicit deferred; no parent adjudication behavior",
        evidence_requirements="safe decision/disposition metadata only",
        raw_child_payload_allowed=False,
        subagent_v0_owner="Sub-agent v0 adjudication plan",
        add_handler_now=False,
    ),
    RuntimeActionType.SUBAGENT_CHILD_MEMORY_REQUEST: RuntimeActionSupportDescriptor(
        action_type=RuntimeActionType.SUBAGENT_CHILD_MEMORY_REQUEST,
        support_status="deferred",
        production_supported=False,
        reserved=True,
        expected_behavior="reject/defer evidence-only; never write MemoryStore",
        evidence_requirements="safe hashes/counts/reason only",
        raw_child_payload_allowed=False,
        subagent_v0_owner="Sub-agent v0 memory boundary",
        add_handler_now=False,
    ),
    RuntimeActionType.SUBAGENT_CHILD_BATCH_MEMORY: RuntimeActionSupportDescriptor(
        action_type=RuntimeActionType.SUBAGENT_CHILD_BATCH_MEMORY,
        support_status="deferred",
        production_supported=False,
        reserved=True,
        expected_behavior="reserved/deferred; no MemoryStore write",
        evidence_requirements="safe count/hash/reason only",
        raw_child_payload_allowed=False,
        subagent_v0_owner="Sub-agent v0 batch memory schema",
        add_handler_now=False,
    ),
}


def runtime_action_support_status(
    action_type: RuntimeActionType | str,
) -> RuntimeActionSupportDescriptor:
    """Return explicit production/deferred support ownership for an action."""
    normalized = normalize_action_type(action_type)
    if isinstance(normalized, RuntimeActionType) and normalized in _DEFERRED_SUBAGENT_SUPPORT:
        return _DEFERRED_SUBAGENT_SUPPORT[normalized]
    if isinstance(normalized, RuntimeActionType):
        return RuntimeActionSupportDescriptor(
            action_type=normalized,
            support_status="production",
            production_supported=True,
            reserved=False,
            expected_behavior="requires registered handler when production-supported",
            evidence_requirements="handler-specific safe evidence",
            raw_child_payload_allowed=False,
            add_handler_now=True,
        )
    raise ValueError(f"unknown RuntimeActionType: {action_type!r}")


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
    # B7: multi-instance identity fields（默认 "" 保证向后兼容）
    session_id: str = ""
    run_id: str = ""
    instance_id: str = ""
    timestamp: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_type", normalize_action_type(self.action_type))
        object.__setattr__(self, "evidence", deep_freeze(dict(self.evidence)))
