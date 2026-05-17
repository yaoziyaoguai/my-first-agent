"""Provider-neutral streaming helpers.

本模块只定义 First Agent 内部最小 streaming protocol。它不是 SSE/WebSocket
协议，也不负责 UI 展示；provider adapter 产出事件，runtime 只消费事件并
聚合为最终 ProviderResponse。这样 core.py 不需要知道 Anthropic/OpenAI SDK
的 stream event 细节。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from agent.provider.protocol import ProviderResponse, ProviderResponseError, ProviderTextBlock


_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+", re.IGNORECASE),
    re.compile(r"Authorization:\s*[^\n]+", re.IGNORECASE),
)


def sanitize_stream_text(text: str) -> str:
    """脱敏 provider delta 文本，防止 secret-like token 进入 UI/checkpoint。"""

    sanitized = text
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED_SECRET]", sanitized)
    return sanitized


@dataclass(frozen=True)
class ProviderStreamEvent:
    """Provider 到 runtime 的最小 streaming event。

    字段固定为审计需要的 schema：event_type / sequence / source /
    text_delta / payload / is_final / error。payload 只用于少量控制事件，
    checkpoint 不应保存 raw delta flood。
    """

    event_type: str
    sequence: int
    source: str = "provider"
    text_delta: str = ""
    payload: dict[str, object] | None = None
    is_final: bool = False
    error: str | None = None

    @classmethod
    def delta(cls, *, sequence: int, text_delta: str, source: str = "provider") -> "ProviderStreamEvent":
        return cls(
            event_type="text_delta",
            sequence=sequence,
            source=source,
            text_delta=sanitize_stream_text(text_delta),
        )

    @classmethod
    def tool_request(cls, *, sequence: int, source: str = "provider") -> "ProviderStreamEvent":
        return cls(event_type="tool_request", sequence=sequence, source=source)

    @classmethod
    def final(cls, *, sequence: int, source: str = "provider") -> "ProviderStreamEvent":
        return cls(event_type="final", sequence=sequence, source=source, is_final=True)

    @classmethod
    def error_event(cls, *, sequence: int, error: str, source: str = "provider") -> "ProviderStreamEvent":
        return cls(
            event_type="error",
            sequence=sequence,
            source=source,
            error=sanitize_stream_text(error),
        )


def collect_stream_response(events: Iterable[ProviderStreamEvent]) -> ProviderResponse:
    """把 stream events 聚合为 ProviderResponse，error 事件 fail closed。"""

    parts: list[str] = []
    final_seen = False
    last_sequence = 0
    for event in events:
        if event.sequence <= last_sequence:
            raise ProviderResponseError("provider_stream_sequence_not_monotonic")
        last_sequence = event.sequence
        if event.event_type == "error":
            raise ProviderResponseError("provider_stream_error")
        if event.text_delta:
            parts.append(sanitize_stream_text(event.text_delta))
        if event.is_final:
            final_seen = True
    if not final_seen:
        raise ProviderResponseError("provider_stream_missing_final")
    return ProviderResponse(
        content=[ProviderTextBlock(text="".join(parts))] if parts else [],
        stop_reason="end_turn",
    )
