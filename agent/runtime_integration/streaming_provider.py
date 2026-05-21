"""Streaming provider RuntimeAction handler."""

from __future__ import annotations

from functools import partial
from typing import Any

from agent.provider.streaming import ProviderStreamEvent, collect_stream_response, sanitize_stream_text
from agent.runtime_integration.dispatcher import RuntimeActionContext
from agent.runtime_integration.schema import RuntimeActionRequest


class StreamingProviderCallHandler:
    """收集 streaming.provider_call evidence，不扩大 observability 系统。"""

    def handle(self, request: RuntimeActionRequest, context: RuntimeActionContext):
        payload = dict(request.payload)
        supports = bool(payload.get("provider_supports_streaming"))
        if not supports:
            result_payload = {
                "provider_supports_streaming": False,
                "events_received": 0,
                "final_event_received": False,
                "error_event_received": False,
                "text_delta_event_received": False,
                "text_sanitized": False,
                "sequence_monotonic": True,
                "silent_fallback_used": False,
                "fake_final_event_generated": False,
            }
            return context.not_supported(
                handler_name=type(self).__name__,
                target_module="StreamingProtocol",
                payload=result_payload,
                observed_call=None,
                evidence_extra={
                    **result_payload,
                    "runtime_e2e_disqualified_reason": "provider does not support streaming",
                },
                error_safe_preview="streaming not supported",
            )

        events = [_event_from_payload(item) for item in payload.get("events", ())]
        observed = context.observe_module_call(
            target_module="StreamingProtocol",
            function_called="collect_stream_response",
            call_signature="collect_stream_response(events)",
            call=partial(collect_stream_response, events),
        )
        text_delta_received = any(event.event_type == "text_delta" for event in events)
        final_received = any(event.event_type == "final" for event in events)
        error_received = any(event.event_type == "error" for event in events)
        sanitized = any(
            event.text_delta and sanitize_stream_text(event.text_delta) != event.text_delta
            for event in events
        )
        sequence_monotonic = _sequence_monotonic(events)
        disqualified = None
        if not text_delta_received:
            disqualified = "streaming final-only evidence is insufficient"
        elif not final_received:
            disqualified = "streaming final event missing"
        result_payload = {
            "provider_supports_streaming": True,
            "events_received": len(events),
            "final_event_received": final_received,
            "error_event_received": error_received,
            "text_delta_event_received": text_delta_received,
            "text_sanitized": sanitized,
            "sequence_monotonic": sequence_monotonic,
            "silent_fallback_used": False,
            "fake_final_event_generated": False,
            "events_tied_to_action_id": [context.action_id for _ in events],
            "final_text_preview": getattr(observed.value.content[0], "text", "")[:200] if observed.value.content else "",
        }
        evidence_extra = dict(result_payload)
        if disqualified:
            evidence_extra["runtime_e2e_disqualified_reason"] = disqualified
        return context.success(
            handler_name=type(self).__name__,
            target_module="StreamingProtocol",
            payload=result_payload,
            observed_call=observed,
            evidence_extra=evidence_extra,
        )


def _event_from_payload(item: Any) -> ProviderStreamEvent:
    if isinstance(item, ProviderStreamEvent):
        return item
    data = dict(item)
    event_type = data.get("event_type")
    sequence = int(data.get("sequence", 0))
    if event_type == "text_delta":
        return ProviderStreamEvent.delta(sequence=sequence, text_delta=str(data.get("text_delta") or ""))
    if event_type == "final":
        return ProviderStreamEvent.final(sequence=sequence)
    if event_type == "error":
        return ProviderStreamEvent.error_event(sequence=sequence, error=str(data.get("error") or "error"))
    if event_type == "tool_request":
        return ProviderStreamEvent.tool_request(sequence=sequence)
    raise ValueError(f"unsupported streaming event_type: {event_type}")


def _sequence_monotonic(events: list[ProviderStreamEvent]) -> bool:
    last = -1
    for event in events:
        if event.sequence <= last:
            return False
        last = event.sequence
    return True
