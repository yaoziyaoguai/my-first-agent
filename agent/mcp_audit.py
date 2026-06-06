"""MCP 专项审计事件发射器。

中文学习边界：
- 本模块只负责 MCP 生命周期的审计事件发射，不做 server 启动、tool 注册或执行。
- MCP 审计事件在 agent/tool_audit.py 的通用 ToolAuditEvent 基础上扩展 server_name 维度。
- 主路径通过 record_evidence(subsystem="mcp") 写入 per-session events.jsonl。
- 兜底路径通过 runtime_observer.log_event 写入 agent_log.jsonl（session 上下文未注入时）。
- 不 import agent/mcp.py / agent/mcp_stdio.py 的 transport 实现，只依赖数据模型。
- MCP server name 和 tool name 在审计事件中保留，但不保留完整 config / env / command。

MCP 审计覆盖 6 类事件：
1. mcp_server_discovered  — server 被发现且通过策略检查
2. mcp_server_blocked      — server 被策略拒绝
3. mcp_tools_listed        — server 的工具列表已获取
4. mcp_tool_registered     — tool 通过策略检查并注册到本地 registry
5. mcp_tool_blocked        — tool 被策略拒绝（含拒绝原因）
6. mcp_tool_call           — tool 被实际调用
   （通过现有 tool_executor 审计通道，这里只记录 MCP 侧事实）
"""

from __future__ import annotations

import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agent.evidence_recorder import record_evidence
from agent.runtime_observer import log_event as log_runtime_event


@dataclass(frozen=True, slots=True)
class MCPServerAuditEvent:
    """MCP server 层面的审计事件。"""

    event_type: str  # "mcp_server_discovered" | "mcp_server_blocked"
    server_name: str
    decision: str
    reason: str
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "server_name": self.server_name,
            "decision": self.decision,
            "reason": self.reason,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True, slots=True)
class MCPToolAuditEvent:
    """MCP tool 层面的审计事件。"""

    event_type: str  # "mcp_tools_listed" | "mcp_tool_registered" | "mcp_tool_blocked"
    server_name: str
    tool_name: str | None
    tool_count: int | None  # 仅在 tools_listed 中有意义
    decision: str
    reason: str
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_log_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "event_type": self.event_type,
            "server_name": self.server_name,
            "decision": self.decision,
            "reason": self.reason,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
        }
        if self.tool_name is not None:
            result["tool_name"] = self.tool_name
        if self.tool_count is not None:
            result["tool_count"] = self.tool_count
        return result


def _mcp_evidence(
    *,
    operation: str,
    status: str,
    server_name: str,
    safe_summary: str,
    reason_code: str = "",
    tool_name: str | None = None,
    tool_count: int | None = None,
    dry_run: bool = True,
    transport: str = "unknown",
    mode: str = "registration",
) -> dict[str, Any]:
    """通过 record_evidence 写入 MCP audit event（主路径）。

    兜底：如果 session 上下文未注入（session_id 为空），record_evidence
    仍会写入 agent_log.jsonl；同时保留 runtime_observer 写入以确保
    legacy 兼容。
    """
    metadata: dict[str, Any] = {
        "server_name": server_name,
        "decision": status,
        "dry_run": dry_run,
        "transport": transport,
        "mode": mode,
    }
    if tool_name is not None:
        metadata["tool_name"] = tool_name
    if tool_count is not None:
        metadata["tool_count"] = tool_count

    return record_evidence(
        subsystem="mcp",
        operation=operation,
        phase="decision",
        status=status,
        reason_code=reason_code,
        safe_summary=safe_summary,
        metadata=metadata,
    )


def _fallback_log(event_type: str, event_payload: dict[str, Any]) -> None:
    """兜底写入 runtime_observer，确保 session 上下文未注入时不丢事件。"""
    with suppress(Exception):
        log_runtime_event(
            "mcp_audit",
            event_source="mcp",
            event_payload=event_payload,
        )


def emit_mcp_server_discovered(
    server_name: str,
    *,
    decision: str = "allowed",
    dry_run: bool = True,
    transport: str = "unknown",
    mode: str = "registration",
) -> MCPServerAuditEvent:
    """记录 MCP server 被发现并通过策略检查。"""
    event = MCPServerAuditEvent(
        event_type="mcp_server_discovered",
        server_name=server_name,
        decision=decision,
        reason="",
    )
    safe_summary = (
        f"MCP server '{server_name}' discovered: {decision}"
        f"{' (dry_run)' if dry_run else ''}"
    )
    _mcp_evidence(
        operation="server_discovered",
        status=decision,
        server_name=server_name,
        safe_summary=safe_summary,
        dry_run=dry_run,
        transport=transport,
        mode=mode,
    )
    _fallback_log("mcp_server_discovered", event.to_log_dict())
    return event


def emit_mcp_server_blocked(
    server_name: str,
    *,
    reason: str = "",
    dry_run: bool = True,
    transport: str = "unknown",
    mode: str = "registration",
) -> MCPServerAuditEvent:
    """记录 MCP server 被策略拒绝。"""
    event = MCPServerAuditEvent(
        event_type="mcp_server_blocked",
        server_name=server_name,
        decision="blocked",
        reason=reason,
    )
    safe_summary = f"MCP server '{server_name}' blocked: {reason or 'policy rejection'}"
    _mcp_evidence(
        operation="server_blocked",
        status="blocked",
        server_name=server_name,
        safe_summary=safe_summary,
        reason_code=reason[:200] if reason else "",
        dry_run=dry_run,
        transport=transport,
        mode=mode,
    )
    _fallback_log("mcp_server_blocked", event.to_log_dict())
    return event


def emit_mcp_tools_listed(
    server_name: str,
    *,
    tool_count: int = 0,
    dry_run: bool = True,
    transport: str = "unknown",
    mode: str = "registration",
) -> MCPToolAuditEvent:
    """记录 server tools/list 完成。"""
    event = MCPToolAuditEvent(
        event_type="mcp_tools_listed",
        server_name=server_name,
        tool_name=None,
        tool_count=tool_count,
        decision="listed",
        reason="",
    )
    safe_summary = (
        f"MCP server '{server_name}' tools listed: {tool_count} tool(s)"
        f"{' (dry_run)' if dry_run else ''}"
    )
    _mcp_evidence(
        operation="tools_listed",
        status="listed",
        server_name=server_name,
        safe_summary=safe_summary,
        tool_count=tool_count,
        dry_run=dry_run,
        transport=transport,
        mode=mode,
    )
    _fallback_log("mcp_tools_listed", event.to_log_dict())
    return event


def emit_mcp_tool_registered(
    server_name: str,
    tool_name: str,
    *,
    dry_run: bool = True,
    transport: str = "unknown",
    mode: str = "registration",
) -> MCPToolAuditEvent:
    """记录 MCP tool 通过策略检查并注册到本地 registry。"""
    event = MCPToolAuditEvent(
        event_type="mcp_tool_registered",
        server_name=server_name,
        tool_name=tool_name,
        tool_count=None,
        decision="registered",
        reason="",
    )
    safe_summary = (
        f"MCP tool '{server_name}/{tool_name}' registered"
        f"{' (dry_run)' if dry_run else ''}"
    )
    _mcp_evidence(
        operation="tool_registered",
        status="registered",
        server_name=server_name,
        safe_summary=safe_summary,
        tool_name=tool_name,
        dry_run=dry_run,
        transport=transport,
        mode=mode,
    )
    _fallback_log("mcp_tool_registered", event.to_log_dict())
    return event


def emit_mcp_tool_blocked(
    server_name: str,
    tool_name: str,
    *,
    reason: str = "",
    dry_run: bool = True,
    transport: str = "unknown",
    mode: str = "registration",
) -> MCPToolAuditEvent:
    """记录 MCP tool 被策略拒绝（含拒绝原因）。"""
    event = MCPToolAuditEvent(
        event_type="mcp_tool_blocked",
        server_name=server_name,
        tool_name=tool_name,
        tool_count=None,
        decision="blocked",
        reason=reason,
    )
    safe_summary = (
        f"MCP tool '{server_name}/{tool_name}' blocked: {reason or 'policy rejection'}"
    )
    _mcp_evidence(
        operation="tool_blocked",
        status="blocked",
        server_name=server_name,
        safe_summary=safe_summary,
        reason_code=reason[:200] if reason else "",
        tool_name=tool_name,
        dry_run=dry_run,
        transport=transport,
        mode=mode,
    )
    _fallback_log("mcp_tool_blocked", event.to_log_dict())
    return event
