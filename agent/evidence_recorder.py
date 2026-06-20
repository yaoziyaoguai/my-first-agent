"""统一 Evidence Recorder — Evidence Instrumentation Layer.

为所有 Runtime 子系统提供统一的 evidence 写入入口。
后续 MCP / Skill / Memory / SubAgent / TUI 只通过本模块的 record_evidence()
写事件，不各自新建日志系统。

设计原则：
- 未来子系统不硬编码。subsystem/operation/phase 是自由字符串。
- 业务代码不直接写 agent_log.jsonl / events.jsonl。
- recorder 负责补齐 session_id / provider / entry 等上下文。
- recorder 负责调用统一 persistence policy 做内容摘要。
- 全局 agent_log.jsonl 只记录 lightweight index（无大内容）。

当前最小覆盖（Core Chat 必需观察点）：
- session.start / session.end
- model.call_summary
- tool.gate_decision
- tool.invoke_result_summary
- checkpoint.save_summary
- sensitive.block_metadata

Envelope 字段（所有事件通用）：
- schema_version: "1.0"
- event_id: 自动生成
- session_id: 自动补齐
- run_id: 可选
- turn_id: 可选
- timestamp: 自动生成
- entry: 自动补齐
- provider_type: 自动补齐
- provider_model: 自动补齐
- subsystem: 调用方指定（"tool"/"skill"/"mcp"/"memory"/"subagent"/"tui"/...）
- operation: 调用方指定
- phase: start/decision/end/error/summary
- status: success/failed/blocked/error
- reason_code: 可选
- safe_summary: 持久化策略处理后的安全摘要
- content_persisted: bool
- content_redacted: bool
- sensitive: bool
- metadata: dict — 子系统专属字段
"""

from __future__ import annotations

import hashlib
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from agent.evidence_persistence import (
    summarize_content_for_persistence,
    summarize_tool_result_for_persistence,
)
from agent.evidence_redaction import redact_metadata

SCHEMA_VERSION = "1.0"
MEMORY_EVENT_VERSION = "1.0"

MEMORY_EVENT_TYPES_V0 = frozenset({
    "memory.recall.requested",
    "memory.recall.completed",
    "memory.recall.skipped",
    "memory.recall.failed",
    "memory.proposed",
    "memory.proposal_surfaced",
    "memory.proposal_skipped",
    "memory.proposal_deferred",
    "memory.proposal_expired",
    "memory.proposal_failed",
    "memory.approved",
    "memory.rejected",
    "memory.policy_blocked",
    "memory.sensitive_blocked",
    "memory.redacted",
    "memory.committed",
    "memory.updated",
    "memory.deleted",
    "memory.delete_requested",
    "memory.commit_failed",
    "memory.update_failed",
    "memory.delete_failed",
    "memory.backend_selected",
    "memory.backend_warning",
    "memory.reference_saved",
    "memory.reference_checked",
    "memory.reference_mismatch",
    "memory.restored",
    "memory.restore_skipped",
    "memory.summary_created",
    "memory.summary_updated",
    "memory.summary_cleared",
    "memory.summary_redacted",
    "memory.summary_restored",
    "memory.child_request_received",
    "memory.child_request_deferred",
    "memory.child_request_rejected",
})

MEMORY_EVENT_TYPES_RESERVED = frozenset({
    # Future Sub-agent memory phase only. Memory v0 rejected/deferred lockdown
    # must not emit this event.
    "memory.child_proposal_created",
})

MEMORY_SAFE_METADATA_FIELDS = frozenset({
    "event_type",
    "memory_event_version",
    "memory_id_hash",
    "record_id_hash",
    "source_type",
    "operation",
    "policy_path",
    "policy_id",
    "policy_rule_id",
    "policy_hash",
    "policy_decision_source",
    "decision",
    "reason",
    "backend",
    "namespace",
    "session_id",
    "run_id",
    "count",
    "redacted",
    "sensitive_category_detected",
    "prompt_injection_flagged",
    "checkpoint_ref",
    "store_revision",
    "child_payload_hash",
    "key_hash",
    "root_hash",
    "root_kind",
    "path_kind",
    "path_hash",
})

_MEMORY_FORBIDDEN_FIELD_NAMES = frozenset({
    "content",
    "content_summary",
    "candidate_content",
    "memory_text",
    "memory_body",
    "candidate_id",
    "proposal_id",
    "user_prompt",
    "user_message",
    "assistant_prompt",
    "assistant_response",
    "prompt",
    "preview",
    "proposal_preview",
    "tool_result",
    "file_content",
    "skill_body",
    "child_payload",
    "subagent_payload",
    "value",
    "record_id",
    "memory_id",
    "key",
    "value_preview",
    "path",
    "full_path",
    "api_key",
    "secret",
    "token",
    "credential",
    "password",
})

_MEMORY_SECRET_MARKERS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "credential",
    "bearer ",
    "sk-",
)

# metadata 值超过此字节数时替换为摘要 dict
_MAX_METADATA_VALUE_BYTES = 2048  # 2KB
_MAX_METADATA_PREVIEW_CHARS = 200

# 模块级上下文（由 main.py 在 session 启动时注入）
_session_context: dict[str, str] = {}

# 模块级 EventLogWriter（由 main.py 在创建 EventLogWriter 后注入）
# record_evidence() 自动使用此 writer 写入 per-session events.jsonl
_event_log_writer: object | None = None


def _short_hash(value: str, *, prefix: str, length: int = 16) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}:{digest}"


def hash_memory_identifier(value: str | None) -> str:
    """返回 stable redacted memory/record id hash，不暴露原始 id。"""
    raw = str(value or "")
    if not raw:
        return ""
    return _short_hash(raw, prefix="memid")


def _hash_memory_payload(value: str | None) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    return _short_hash(raw, prefix="mempayload")


def _hash_memory_key(value: str | None) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    return _short_hash(raw, prefix="memkey")


def build_safe_path_metadata(path: Any) -> dict[str, Any]:
    """把路径输入投影成 evidence-safe metadata，不暴露 basename 或完整路径。"""

    raw = str(path or "")
    if not raw:
        return {}
    if raw.startswith("~"):
        path_kind = "home"
    elif (
        raw == "/tmp"
        or raw.startswith("/tmp/")
        or raw == "/private/tmp"
        or raw.startswith("/private/tmp/")
        or "/var/folders/" in raw
    ):
        path_kind = "tmp"
    elif raw.startswith("/"):
        path_kind = "absolute"
    elif raw.strip():
        path_kind = "relative"
    else:
        path_kind = "unknown"
    return {
        "path_kind": path_kind,
        "path_hash": _short_hash(raw, prefix="path"),
        "redacted": True,
    }


def _derive_memory_operation(event_type: str) -> str:
    if event_type.startswith("memory."):
        return event_type.removeprefix("memory.")
    return event_type


def _memory_value_is_sensitive(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return any(marker in lowered for marker in _MEMORY_SECRET_MARKERS)
    if isinstance(value, dict):
        return any(
            _memory_value_is_sensitive(key) or _memory_value_is_sensitive(item)
            for key, item in value.items()
        )
    if isinstance(value, list | tuple | set | frozenset):
        return any(_memory_value_is_sensitive(item) for item in value)
    return False


def _safe_memory_text_field(value: Any) -> str:
    raw = str(value or "")
    return raw if raw and not _memory_value_is_sensitive(raw) else ""


def build_memory_evidence_metadata(
    *,
    event_type: str,
    operation: str = "",
    source_type: str = "system",
    decision: str = "",
    policy_path: str = "",
    reason: str = "",
    backend: str = "",
    namespace: str = "",
    session_id: str = "",
    run_id: str = "",
    count: int | None = None,
    redacted: bool | None = None,
    sensitive_category_detected: bool | None = None,
    prompt_injection_flagged: bool = False,
    checkpoint_ref: str = "",
    store_revision: str = "",
    memory_id: str | None = None,
    record_id: str | None = None,
    child_payload: str | None = None,
    child_key: str | None = None,
    root: str | None = None,
    root_kind: str = "",
    path_kind: str = "",
    raw_fields: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造 Memory evidence metadata，只允许 v0 审计白名单字段。

    raw_fields 只作为检测/派生 hash 的输入，绝不原样写入返回值。这样后续
    lifecycle wiring 可以统一复用，不把 memory body、prompt、tool result、
    child payload、路径或原始 record id 带进 evidence/log。
    """
    if event_type not in MEMORY_EVENT_TYPES_V0 and event_type not in MEMORY_EVENT_TYPES_RESERVED:
        raise ValueError(f"unknown memory event_type: {event_type}")

    raw = dict(raw_fields or {})
    if record_id is None and "record_id" in raw:
        record_id = str(raw.get("record_id") or "")
    if memory_id is None and "memory_id" in raw:
        memory_id = str(raw.get("memory_id") or "")
    if child_key is None and "key" in raw:
        child_key = str(raw.get("key") or "")
    if child_payload is None:
        child_payload = str(
            raw.get("child_payload")
            or raw.get("subagent_payload")
            or raw.get("value_preview")
            or ""
        )
    if root is None and "path" in raw:
        root = str(raw.get("path") or "")

    forbidden_present = bool(set(raw).intersection(_MEMORY_FORBIDDEN_FIELD_NAMES))
    forbidden_present = forbidden_present or bool(child_payload or child_key or root)
    sensitive_present = any(
        _memory_value_is_sensitive(key) or _memory_value_is_sensitive(value)
        for key, value in raw.items()
    )

    metadata: dict[str, Any] = {
        "event_type": event_type,
        "memory_event_version": MEMORY_EVENT_VERSION,
        "source_type": source_type,
        "operation": operation or _derive_memory_operation(event_type),
        "decision": decision,
        "redacted": bool(redacted) if redacted is not None else forbidden_present,
        "sensitive_category_detected": (
            bool(sensitive_category_detected)
            if sensitive_category_detected is not None
            else sensitive_present
        ),
        "prompt_injection_flagged": bool(prompt_injection_flagged),
    }

    optional_values: dict[str, Any] = {
        "policy_path": policy_path,
        "reason": reason,
        "backend": backend,
        "namespace": namespace,
        "session_id": session_id,
        "run_id": run_id,
        "count": count,
        "checkpoint_ref": checkpoint_ref,
        "store_revision": store_revision,
        "memory_id_hash": hash_memory_identifier(memory_id),
        "record_id_hash": hash_memory_identifier(record_id),
        "child_payload_hash": _hash_memory_payload(child_payload),
        "key_hash": _hash_memory_key(child_key),
        "root_hash": _short_hash(root, prefix="memroot") if root else "",
        "path_hash": _short_hash(root, prefix="path") if root else "",
        "root_kind": root_kind,
        "path_kind": path_kind,
    }
    for key, value in optional_values.items():
        if value is None or value == "":
            continue
        metadata[key] = value

    for key, value in (extra or {}).items():
        key = str(key)
        if key not in MEMORY_SAFE_METADATA_FIELDS:
            continue
        safe_text_fields = {
            "memory_id_hash",
            "record_id_hash",
            "child_payload_hash",
            "key_hash",
            "session_id",
            "run_id",
            "namespace",
            "checkpoint_ref",
            "store_revision",
        }
        if key in safe_text_fields:
            metadata[key] = _safe_memory_text_field(value)
        elif key in {"count"}:
            metadata[key] = int(value)
        elif key in {"redacted", "sensitive_category_detected", "prompt_injection_flagged"}:
            metadata[key] = bool(value)
        else:
            metadata[key] = _safe_memory_text_field(value)

    return {key: metadata[key] for key in metadata if key in MEMORY_SAFE_METADATA_FIELDS}


def build_memory_safe_summary(
    *,
    event_type: str,
    operation: str = "",
    decision: str = "",
    count: int | None = None,
    backend: str = "",
    reason: str = "",
) -> str:
    """生成 Memory evidence 的短安全摘要，不包含正文或原始 id。"""
    bits = [event_type]
    if operation:
        bits.append(f"operation={operation}")
    if decision:
        bits.append(f"decision={decision}")
    if count is not None:
        bits.append(f"count={count}")
    if backend:
        bits.append(f"backend={backend}")
    if reason:
        bits.append(f"reason={reason}")
    return " ".join(bits)


def record_memory_evidence(
    *,
    event_type: str,
    operation: str = "",
    phase: str = "",
    status: str = "",
    reason_code: str = "",
    source_type: str = "system",
    decision: str = "",
    policy_path: str = "",
    reason: str = "",
    backend: str = "",
    namespace: str = "",
    session_id: str = "",
    run_id: str = "",
    count: int | None = None,
    memory_id: str | None = None,
    record_id: str | None = None,
    child_payload: str | None = None,
    child_key: str | None = None,
    raw_fields: dict[str, Any] | None = None,
    metadata_extra: dict[str, Any] | None = None,
    event_log_writer: object | None = None,
    turn_id: str = "",
) -> dict[str, Any]:
    """通过统一 evidence_recorder 记录 Memory evidence。

    这是 adapter/helper，不是新的日志系统。返回值是 record_evidence() 的标准
    envelope，metadata 已经由 build_memory_evidence_metadata 收口。
    """
    safe_operation = operation or _derive_memory_operation(event_type)
    recorder_operation = _derive_memory_operation(event_type)
    metadata = build_memory_evidence_metadata(
        event_type=event_type,
        operation=recorder_operation,
        source_type=source_type,
        decision=decision,
        policy_path=policy_path,
        reason=reason,
        backend=backend,
        namespace=namespace,
        session_id=session_id,
        run_id=run_id,
        count=count,
        memory_id=memory_id,
        record_id=record_id,
        child_payload=child_payload,
        child_key=child_key,
        raw_fields=raw_fields,
        extra=metadata_extra,
    )
    safe_summary = build_memory_safe_summary(
        event_type=event_type,
        operation=safe_operation,
        decision=decision,
        count=count,
        backend=backend,
        reason=reason or reason_code,
    )
    return record_evidence(
        subsystem="memory",
        operation=recorder_operation,
        phase=phase,
        status=status,
        reason_code=reason_code,
        safe_summary=safe_summary,
        content_persisted=False,
        content_redacted=bool(metadata.get("redacted", False)),
        sensitive=bool(metadata.get("sensitive_category_detected", False)),
        metadata=metadata,
        turn_id=turn_id,
        event_log_writer=event_log_writer or _event_log_writer,
    )


def record_memory_runtime_event(
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """MemoryRuntime legacy event logger adapter → built-in safe evidence.

    MemoryRuntime 仍用二元 ``_log(event_type, payload)`` seam，方便单元测试和
    显式注入；默认生产 logger 通过本 adapter 收口到统一 evidence_recorder。
    """
    payload = dict(payload or {})
    v0_event_type = _map_memory_runtime_event_type(event_type, payload)
    decision_type = str(payload.get("decision_type") or "")
    reason = str(payload.get("reason") or "")
    candidate_id = str(payload.get("candidate_id") or "")
    record_id = str(payload.get("record_id") or candidate_id)
    operation = _memory_operation_from_event(v0_event_type, decision_type)
    decision = _memory_decision_from_event(v0_event_type)
    status = _memory_status_from_event(v0_event_type)
    phase = _memory_phase_from_event(v0_event_type)
    source_type = str(payload.get("source_type") or "explicit_user")
    raw_content = (
        payload.get("content_summary")
        or payload.get("proposal_preview")
        or payload.get("preview")
        or ""
    )
    return record_memory_evidence(
        event_type=v0_event_type,
        operation=operation,
        phase=phase,
        status=status,
        source_type=source_type,
        decision=decision,
        reason=reason,
        memory_id=candidate_id,
        record_id=record_id,
        raw_fields={
            "candidate_id": candidate_id,
            "record_id": record_id,
            "content_summary": raw_content,
            "reason": reason,
        },
        metadata_extra={
            "prompt_injection_flagged": bool(
                payload.get("prompt_injection_flagged", False)
            ),
        },
    )


def _map_memory_runtime_event_type(event_type: str, payload: dict[str, Any]) -> str:
    if event_type in MEMORY_EVENT_TYPES_V0:
        return event_type
    if event_type == "memory.candidate_detected":
        return "memory.proposed"
    if event_type == "memory.confirmation_requested":
        return "memory.proposal_surfaced"
    if event_type in {"memory.confirmation_accepted", "memory.confirmation_approved"}:
        return "memory.approved"
    if event_type in {"memory.confirmation_rejected", "memory.confirmation_session_only"}:
        return "memory.rejected"
    if event_type in {"memory.blocked", "memory.sensitive_blocked"}:
        flags = tuple(payload.get("safety_flags") or ())
        reason = str(payload.get("reason") or "").lower()
        if flags or any(marker in reason for marker in _MEMORY_SECRET_MARKERS):
            return "memory.sensitive_blocked"
        return "memory.policy_blocked"
    if event_type == "memory.injected":
        return "memory.recall.completed"
    if event_type == "memory.agent_suggested_candidate":
        return "memory.proposed"
    return "memory.proposal_skipped"


def _memory_operation_from_event(event_type: str, decision_type: str = "") -> str:
    if ".recall." in event_type:
        return "recall"
    if event_type in {"memory.committed", "memory.commit_failed"}:
        return "commit"
    if event_type in {"memory.updated", "memory.update_failed"}:
        return "update"
    if event_type in {
        "memory.deleted",
        "memory.delete_requested",
        "memory.delete_failed",
    }:
        return "delete"
    if event_type.startswith("memory.summary_"):
        return "summarize"
    if event_type.startswith("memory.child_"):
        return "propose"
    if event_type in {"memory.restored", "memory.restore_skipped"}:
        return "restore"
    normalized = decision_type.lower()
    if "forget" in normalized:
        return "delete"
    if "update" in normalized:
        return "update"
    if "retain" in normalized:
        return "propose"
    return "propose"


def _memory_decision_from_event(event_type: str) -> str:
    if event_type.endswith(".skipped") or event_type.endswith("_skipped"):
        return "skipped"
    if event_type.endswith(".failed") or event_type.endswith("_failed"):
        return "failed"
    if "blocked" in event_type or event_type.endswith(".rejected"):
        return "blocked"
    if event_type in {"memory.proposed", "memory.proposal_surfaced"}:
        return "pending"
    return "allowed"


def _memory_status_from_event(event_type: str) -> str:
    decision = _memory_decision_from_event(event_type)
    if decision == "failed":
        return "failed"
    if decision in {"blocked", "skipped"}:
        return "blocked"
    return "success"


def _memory_phase_from_event(event_type: str) -> str:
    if event_type.endswith(".requested") or event_type.endswith("_requested"):
        return "start"
    if event_type.endswith(".failed") or event_type.endswith("_failed"):
        return "error"
    if event_type.endswith(".skipped") or event_type.endswith("_skipped"):
        return "decision"
    if "blocked" in event_type or event_type.endswith(".rejected"):
        return "decision"
    return "end"


def set_event_log_writer(writer: object | None) -> None:
    """注入 per-session EventLogWriter，使 record_evidence() 可自动写 events.jsonl。"""
    global _event_log_writer
    _event_log_writer = writer


def set_session_context(
    *,
    session_id: str = "",
    entry: str = "",
    provider_type: str = "",
    provider_model: str = "",
    run_id: str = "",
) -> None:
    """注入当前 session 上下文。main.py 在 session 初始化后调用。"""
    global _session_context
    _session_context = {
        "session_id": session_id,
        "entry": entry or "plain",
        "provider_type": provider_type or "unknown",
        "provider_model": provider_model or "unknown",
        "run_id": run_id or "",
    }


def get_session_context() -> dict[str, str]:
    """返回当前 session 上下文的只读副本。"""
    return dict(_session_context)


def _summarize_metadata_value(value: Any, max_bytes: int = _MAX_METADATA_VALUE_BYTES) -> Any:
    """对 metadata 中的大字符串值做摘要化。

    只处理 str 类型的大值；其他类型（int/float/bool/list/dict）原样保留。
    摘要 dict 包含 result_size / result_hash / preview_redacted / truncated，
    与 evidence_persistence 的摘要格式一致。
    """
    if not isinstance(value, str):
        return value
    content_bytes = value.encode("utf-8")
    if len(content_bytes) <= max_bytes:
        return value
    return {
        "result_size": len(content_bytes),
        "result_hash": hashlib.sha256(content_bytes).hexdigest()[:16],
        "preview_redacted": value[:_MAX_METADATA_PREVIEW_CHARS],
        "truncated": True,
        "content_persisted": False,
    }


def _build_envelope(
    *,
    subsystem: str,
    operation: str,
    phase: str = "",
    status: str = "",
    reason_code: str = "",
    safe_summary: str = "",
    content_persisted: bool = False,
    content_redacted: bool = False,
    sensitive: bool = False,
    metadata: dict[str, Any] | None = None,
    turn_id: str = "",
) -> dict[str, Any]:
    """构造标准 evidence envelope。"""
    ctx = _session_context
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"evt-{uuid.uuid4().hex[:16]}",
        "session_id": ctx.get("session_id", ""),
        "run_id": ctx.get("run_id", ""),
        "turn_id": turn_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entry": ctx.get("entry", "unknown"),
        "provider_type": ctx.get("provider_type", "unknown"),
        "provider_model": ctx.get("provider_model", "unknown"),
        "subsystem": subsystem,
        "operation": operation,
        "phase": phase,
        "status": status,
        "reason_code": reason_code,
        "safe_summary": safe_summary,
        "content_persisted": content_persisted,
        "content_redacted": content_redacted,
        "sensitive": sensitive,
        "metadata": {
            k: _summarize_metadata_value(v)
            for k, v in redact_metadata(metadata or {}).items()
        },
    }


def record_evidence(
    *,
    subsystem: str,
    operation: str,
    phase: str = "",
    status: str = "",
    reason_code: str = "",
    safe_summary: str = "",
    content_persisted: bool = False,
    content_redacted: bool = False,
    sensitive: bool = False,
    metadata: dict[str, Any] | None = None,
    turn_id: str = "",
    event_log_writer: object | None = None,
) -> dict[str, Any]:
    """统一 evidence 写入入口。

    所有新事件必须通过此函数写入。自动补齐 session_id / provider / entry 上下文。

    Args:
        subsystem: 子系统标识符（"tool"/"skill"/"mcp"/"memory"/"subagent"/"tui"）
        operation: 操作名称（如 "gate_decision"/"invoke"/"scope_resolve"）
        phase: 阶段（"start"/"decision"/"end"/"error"/"summary"）
        status: 结果状态（"success"/"failed"/"blocked"/"error"）
        reason_code: 失败/拒绝原因（如 "sensitive_path"）
        safe_summary: 安全摘要文本（不含敏感信息）
        content_persisted: 原始内容是否被持久化
        content_redacted: 内容是否被脱敏
        sensitive: 操作是否涉及敏感数据
        metadata: 子系统专属字段
        turn_id: 当前 turn ID（可选）
        event_log_writer: EventLogWriter 实例（可选，传入则同时写 events.jsonl）

    Returns:
        构造好的 evidence envelope dict
    """
    envelope = _build_envelope(
        subsystem=subsystem,
        operation=operation,
        phase=phase,
        status=status,
        reason_code=reason_code,
        safe_summary=safe_summary,
        content_persisted=content_persisted,
        content_redacted=content_redacted,
        sensitive=sensitive,
        metadata=metadata,
        turn_id=turn_id,
    )

    # 写入全局 lightweight index（agent_log.jsonl）
    with suppress(Exception):
        from agent.logger import log_event
        log_data: dict[str, Any] = {
            "subsystem": subsystem,
            "operation": operation,
            "phase": phase,
            "status": status,
            "reason_code": reason_code,
            "safe_summary": safe_summary[:200],
            "event_id": envelope["event_id"],
            "session_id": envelope["session_id"],
        }
        if metadata and "tool_use_id" in metadata:
            log_data["tool_use_id"] = metadata["tool_use_id"]
        log_event("evidence.recorded", log_data)

    # 写入 per-session events.jsonl（优先使用显式传入的 writer，否则用全局 writer）
    _writer = event_log_writer or _event_log_writer
    if _writer is not None:
        with suppress(Exception):
            _writer.append({
                "action_type": f"{subsystem}.{operation}",
                "source": subsystem,
                "event_id": envelope["event_id"],
                "status": status,
                "data": envelope,
            })

    return envelope


def record_tool_result_summary(
    *,
    tool_name: str,
    path: str = "",
    content: str = "",
    status: str = "success",
    reason_code: str = "",
    event_log_writer: object | None = None,
) -> dict[str, Any]:
    """便捷函数：记录工具调用结果摘要。

    自动对 content 应用持久化策略，生成安全摘要。
    用于 tool.invoke_result_summary 事件。
    """
    if status == "blocked":
        summary = summarize_tool_result_for_persistence(
            content, path=path, tool_name=tool_name,
        )
    else:
        summary = summarize_content_for_persistence(
            content, path=path, tool_name=tool_name,
        )

    path_metadata = build_safe_path_metadata(path)

    if isinstance(summary, dict):
        safe_summary = (
            f"tool={tool_name} "
            f"path_kind={path_metadata.get('path_kind', 'none')} "
            f"size={summary.get('result_size', 0)} "
            f"hash={summary.get('result_hash', '')}"
        )
        content_persisted = summary.get("content_persisted", False)
        content_redacted = summary.get("content_redacted", False)
        sensitive = summary.get("sensitive", False)
    else:
        safe_summary = (
            f"tool={tool_name} "
            f"path_kind={path_metadata.get('path_kind', 'none')}"
        )
        content_persisted = True
        content_redacted = False
        sensitive = False

    return record_evidence(
        subsystem="tool",
        operation="invoke_result_summary",
        phase="end",
        status=status,
        reason_code=reason_code,
        safe_summary=safe_summary,
        content_persisted=content_persisted,
        content_redacted=content_redacted,
        sensitive=sensitive,
        metadata={
            "tool_name": tool_name,
            **path_metadata,
            "result_summary": summary if isinstance(summary, dict) else None,
        },
        event_log_writer=event_log_writer or _event_log_writer,
    )
