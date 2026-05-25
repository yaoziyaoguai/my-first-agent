"""Streaming provider RuntimeAction handlers.

中文学习边界：
- StreamingProviderCallHandler：处理 STREAMING_PROVIDER_CALL，收集整轮 streaming
  evidence（所有 event 的聚合）
- StreamingEventHandler：处理 STREAMING_EVENT，验证单个 streaming event 的
  event_type / sanitization / sequence，提供 per-event evidence 粒度
"""

from __future__ import annotations

from typing import Any

from agent.provider.streaming import ProviderStreamEvent, sanitize_stream_text
from agent.runtime_integration.dispatcher import RuntimeActionContext
from agent.runtime_integration.schema import RuntimeActionRequest


def validate_stream_event(event: ProviderStreamEvent) -> dict[str, Any]:
    """验证单个 ProviderStreamEvent 的合法性。

    不聚合为 ProviderResponse——那是 collect_stream_response 的职责。
    本函数只做单 event 的字段校验和脱敏检查，供 StreamingEventHandler 作为
    catalog-owned target function。

    返回验证结果字典，包含 event_type、sequence、sanitization 状态等。
    """
    result: dict[str, Any] = {
        "event_type": event.event_type,
        "sequence": event.sequence,
        "source": event.source,
        "sequence_positive": event.sequence >= 0,
        "event_type_valid": event.event_type in {
            "text_delta", "final", "error", "tool_request",
        },
    }
    if event.text_delta:
        sanitized = sanitize_stream_text(event.text_delta)
        result["has_text_delta"] = True
        result["text_sanitized"] = sanitized != event.text_delta
        result["text_length"] = len(event.text_delta)
    else:
        result["has_text_delta"] = False
    if event.is_final:
        result["is_final"] = True
    if event.error:
        result["has_error"] = True
        result["error_sanitized"] = sanitize_stream_text(event.error) != event.error
    return result


class StreamingEventHandler:
    """处理单个 STREAMING_EVENT——per-event 验证和 evidence 收集。

    与 StreamingProviderCallHandler 的区别：
    - StreamingProviderCallHandler：整轮 event 列表 → collect_stream_response 聚合 → 单次 L3 evidence
    - StreamingEventHandler：单 event → validate_stream_event 验证 → per-event evidence

    两者共享同一 RuntimeAction 类型族（streaming.*），但 handler/target 不同。
    """

    def handle(self, request: RuntimeActionRequest, context: RuntimeActionContext):
        payload = dict(request.payload)
        event_payload = payload.get("event")
        if not event_payload:
            return context.not_supported(
                handler_name=type(self).__name__,
                target_module="StreamingProtocol",
                payload={"event_received": False},
                observed_call=None,
                evidence_extra={
                    "runtime_e2e_disqualified_reason": "no event in payload",
                },
                error_safe_preview="streaming event payload missing",
            )

        event = _event_from_payload(event_payload)
        observed = context.invoke_registered_target(
            target_module="StreamingProtocol",
            operation="validate_stream_event",
            payload={"event": event},
        )
        validation = observed.value if observed else {}
        return context.success(
            handler_name=type(self).__name__,
            target_module="StreamingProtocol",
            payload={
                "event_type": event.event_type,
                "sequence": event.sequence,
                "has_text_delta": bool(event.text_delta),
                "is_final": event.is_final,
                "validation": dict(validation) if isinstance(validation, dict) else {},
            },
            observed_call=observed,
            evidence_extra={
                "event_type": event.event_type,
                "sequence": event.sequence,
                "streaming_event_validated": True,
            },
        )


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
        if not events:
            # 无流式事件——call_model() 走非流式路径，或 provider 未产出事件
            return context.not_supported(
                handler_name=type(self).__name__,
                target_module="StreamingProtocol",
                payload={
                    "provider_supports_streaming": True,
                    "events_received": 0,
                    "final_event_received": False,
                    "error_event_received": False,
                    "text_delta_event_received": False,
                },
                observed_call=None,
                evidence_extra={
                    "runtime_e2e_disqualified_reason": "no streaming events collected",
                },
                error_safe_preview="streaming not used in this turn",
            )
        observed = context.invoke_registered_target(
            target_module="StreamingProtocol",
            operation="collect_stream_response",
            payload={"events": events},
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
