"""Normalize provider-specific responses into AgentLoop blocks."""

from __future__ import annotations

import json
from typing import Any

from agent.provider.protocol import ProviderResponse, ProviderTextBlock, ToolUseBlock


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalize_tool_input(raw_input: Any) -> dict[str, Any]:
    if isinstance(raw_input, dict):
        return raw_input
    if isinstance(raw_input, str):
        try:
            parsed = json.loads(raw_input)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _normalize_usage(raw_usage: Any) -> dict[str, Any]:
    if raw_usage is None:
        return {}
    names = (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    )
    if isinstance(raw_usage, dict):
        return {name: raw_usage[name] for name in names if name in raw_usage}
    usage: dict[str, Any] = {}
    for name in names:
        value = getattr(raw_usage, name, None)
        if value is not None:
            usage[name] = value
    return usage


def normalize_anthropic_response(
    raw_response: Any,
    *,
    raw_provider_name: str | None = None,
) -> ProviderResponse:
    """Normalize Anthropic Messages-style content blocks.

    Compatible endpoints often return dicts while the official SDK returns objects.
    This function accepts both so AgentLoop sees one stable internal shape.
    """

    raw_content = _value(raw_response, "content", [])
    content: list[ProviderTextBlock | ToolUseBlock] = []
    for block in raw_content:
        block_type = _value(block, "type")
        if block_type == "text":
            text = _value(block, "text", "") or ""
            if text:
                content.append(ProviderTextBlock(text=text))
        elif block_type == "tool_use":
            content.append(
                ToolUseBlock(
                    id=str(_value(block, "id", "")),
                    name=str(_value(block, "name", "")),
                    input=_normalize_tool_input(_value(block, "input", {})),
                )
            )
    return ProviderResponse(
        content=content,
        stop_reason=_value(raw_response, "stop_reason"),
        usage=_normalize_usage(_value(raw_response, "usage")),
        raw_provider_name=raw_provider_name,
    )
