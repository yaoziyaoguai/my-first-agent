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

SCHEMA_VERSION = "1.0"

# metadata 值超过此字节数时替换为摘要 dict
_MAX_METADATA_VALUE_BYTES = 2048  # 2KB
_MAX_METADATA_PREVIEW_CHARS = 200

# 模块级上下文（由 main.py 在 session 启动时注入）
_session_context: dict[str, str] = {}

# 模块级 EventLogWriter（由 main.py 在创建 EventLogWriter 后注入）
# record_evidence() 自动使用此 writer 写入 per-session events.jsonl
_event_log_writer: object | None = None


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
        "metadata": {k: _summarize_metadata_value(v) for k, v in (metadata or {}).items()},
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
        log_event("evidence.recorded", {
            "subsystem": subsystem,
            "operation": operation,
            "phase": phase,
            "status": status,
            "reason_code": reason_code,
            "safe_summary": safe_summary[:200],
            "event_id": envelope["event_id"],
            "session_id": envelope["session_id"],
        })

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

    if isinstance(summary, dict):
        safe_summary = (
            f"tool={tool_name} path={path[:50]} "
            f"size={summary.get('result_size', 0)} "
            f"hash={summary.get('result_hash', '')}"
        )
        content_persisted = summary.get("content_persisted", False)
        content_redacted = summary.get("content_redacted", False)
        sensitive = summary.get("sensitive", False)
    else:
        safe_summary = f"tool={tool_name} path={path[:50]}"
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
            "path": path,
            "result_summary": summary if isinstance(summary, dict) else None,
        },
        event_log_writer=event_log_writer or _event_log_writer,
    )
