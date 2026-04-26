"""Lightweight runtime observation logs.

This module centralizes human-readable runtime logs without changing runtime
state. It deliberately keeps the first version as plain stdout output: no
logging framework, no JSONL, no checkpoint writes, and no state mutation.
"""

from __future__ import annotations

from typing import Any


RUNTIME_DEBUG_LOGS = True


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _format_fields(fields: dict[str, Any]) -> str:
    parts = []
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, str | int | float | bool):
            parts.append(f"{key}={_format_value(value)}")
    return " ".join(parts)


def log_event(
    event_type: str,
    *,
    event_source: str | None = None,
    event_payload: dict[str, Any] | None = None,
    event_channel: str | None = None,
) -> None:
    """Log a resolved runtime event without printing full event payload."""
    if not RUNTIME_DEBUG_LOGS:
        return

    _ = event_payload
    fields = {
        "event_type": event_type,
        "event_source": event_source,
        "event_channel": event_channel,
    }
    print(f"[RUNTIME_EVENT] {_format_fields(fields)}")


def log_resolution(
    resolution_kind: str,
    *,
    event_type: str | None = None,
    event_source: str | None = None,
    event_channel: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Log how raw input/output was resolved into runtime semantics."""
    if not RUNTIME_DEBUG_LOGS:
        return

    fields: dict[str, Any] = {
        "resolution_kind": resolution_kind,
        "event_type": event_type,
        "event_source": event_source,
        "event_channel": event_channel,
    }
    if details:
        fields.update(details)

    print(f"[INPUT_RESOLUTION] {_format_fields(fields)}")


def log_transition(
    *,
    from_state: str,
    event_type: str,
    target_state: str,
    guard_name: str | None = None,
) -> None:
    """Log a runtime state transition."""
    if not RUNTIME_DEBUG_LOGS:
        return

    fields = {
        "from_state": from_state,
        "event_type": event_type,
        "target_state": target_state,
        "guard_name": guard_name,
    }
    print(f"[TRANSITION] {_format_fields(fields)}")


def log_actions(action_names: list[str]) -> None:
    """Log transition action names without executing any action."""
    if not RUNTIME_DEBUG_LOGS:
        return

    print(f"[ACTIONS] action_names={','.join(action_names)}")
