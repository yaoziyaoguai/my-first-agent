"""工具生命周期审计事件系统。

中文学习边界：
- 本模块只负责定义 ToolAuditEvent 和发送审计事件，不做工具注册、执行或策略决策。
- 审计事件是观测层（observability layer），可丢弃；持久事实仍在 tool_execution_log 和
  checkpoint 中。两者分工明确：tool_execution_log 记录执行事实（进入 checkpoint），
  ToolAuditEvent 记录审计观测（进入 agent_log.jsonl）。
- 审计事件不包含完整的 tool_input / tool_result，只保留脱敏后的 safe_preview 和
  content_length，避免敏感数据通过审计通道泄漏。
- 本模块不 import agent/core.py / agent/tool_executor.py / agent/checkpoint.py，
  保持对 Runtime 主循环的零依赖。只依赖 agent/runtime_observer 做日志写入。
- 每个事件包含 request_id（UUID），可串联同一 tool_call 的 request → block →
  execute → result → error 完整链路。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
import uuid

from agent.runtime_observer import log_event as log_runtime_event


ToolAuditEventType = Literal[
    "tool_blocked",
    "tool_requires_confirmation",
    "tool_executed",
    "tool_failed",
    "tool_skipped",
]


@dataclass(frozen=True, slots=True)
class ToolAuditEvent:
    """单条工具审计事件。

    所有字段均为基础类型或短字符串，保证 JSON 序列化安全和日志体积可控。
    safe_preview 已在上游（ToolResultEnvelope）脱敏，这里只做透传。
    不保留原始 tool_input / tool_result 全文。
    """

    event_type: ToolAuditEventType
    tool_name: str
    tool_use_id: str
    step_index: int | None
    status: str
    error_type: str | None
    safe_preview: str
    content_length: int
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_log_dict(self) -> dict[str, Any]:
        """返回供 agent_log.jsonl 写入的短字段 dict。

        这里只保存审计摘要，不保留完整的 tool_input / tool_result。
        该 dict 会被 log_runtime_event 序列化后追加到 agent_log.jsonl。
        """
        return {
            "event_type": self.event_type,
            "tool_name": self.tool_name,
            "tool_use_id": self.tool_use_id,
            "step_index": self.step_index,
            "status": self.status,
            "error_type": self.error_type,
            "safe_preview": self.safe_preview,
            "content_length": self.content_length,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
        }


def emit_tool_audit_event(
    *,
    event_type: ToolAuditEventType,
    tool_name: str,
    tool_use_id: str,
    step_index: int | None = None,
    status: str = "",
    error_type: str | None = None,
    safe_preview: str = "",
    content_length: int = 0,
) -> ToolAuditEvent:
    """发送一条工具审计事件到 runtime observer。

    调用方负责在 executor 的各个关键节点构造事件并调用本函数。
    本函数只做事件持久化，不修改 state / checkpoint / messages。

    参数 safe_preview 必须已经过脱敏——调用方在上游通过
    ToolResultEnvelope.safe_preview 或等价机制保证。
    """
    event = ToolAuditEvent(
        event_type=event_type,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        step_index=step_index,
        status=status,
        error_type=error_type,
        safe_preview=safe_preview,
        content_length=content_length,
    )
    log_runtime_event(
        "tool_audit",
        event_source="tool",
        event_payload=event.to_log_dict(),
    )
    return event
