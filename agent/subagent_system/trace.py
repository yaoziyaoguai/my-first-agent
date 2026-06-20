"""SubAgent L0 trace model."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

REDACTED = "<redacted>"
L0_TRACE_EVENTS = {
    "delegation_started",
    "context_packaged",
    "result_returned",
    "result_adjudicated",
    "delegation_failed",
}
_SECRET_KEY_MARKERS = ("secret", "token", "password", "credential", "api_key")
_MAX_TRACE_VALUE_CHARS = 1_500


@dataclass(frozen=True)
class SubAgentTraceEvent:
    """Sanitized trace event for audit/debugging."""

    event_type: str
    delegation_id: str
    timestamp: float
    data: dict[str, Any]
    parent_trace_id: str


def make_trace_event(
    event_type: str,
    *,
    delegation_id: str,
    parent_trace_id: str,
    data: dict[str, Any] | None = None,
) -> SubAgentTraceEvent:
    return SubAgentTraceEvent(
        event_type=event_type,
        delegation_id=delegation_id,
        timestamp=time.time(),
        data=sanitize_trace_data(data or {}),
        parent_trace_id=parent_trace_id,
    )


def sanitize_trace_data(data: dict[str, Any]) -> dict[str, Any]:
    """Redact secrets and truncate large values before they enter trace."""

    return {str(key): _sanitize_value(str(key), value) for key, value in data.items()}


def _sanitize_value(key: str, value: object) -> object:
    if any(marker in key.lower() for marker in _SECRET_KEY_MARKERS):
        return REDACTED
    if isinstance(value, str):
        if len(value) > _MAX_TRACE_VALUE_CHARS:
            return value[:_MAX_TRACE_VALUE_CHARS] + "\n<truncated>"
        return value
    if isinstance(value, dict):
        return sanitize_trace_data(value)
    if isinstance(value, (list, tuple)):
        return tuple(_sanitize_value(key, item) for item in value)
    return value

