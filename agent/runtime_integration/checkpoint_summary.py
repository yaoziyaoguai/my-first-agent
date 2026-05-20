"""Checkpoint-safe summary RuntimeAction handler."""

from __future__ import annotations

from agent.display_events import mask_user_visible_secrets
from agent.runtime_integration.dispatcher import RuntimeActionContext
from agent.runtime_integration.schema import RuntimeActionRequest, contains_secret_like


class CheckpointSafeSummaryHandler:
    """turn-end / before save_checkpoint boundary proof.

    本 handler 不改 checkpoint schema，也不调用 save_checkpoint。它只产生
    checkpoint-safe summary evidence，供 Parent Runtime 在保存前消费。
    """

    def handle(self, request: RuntimeActionRequest, context: RuntimeActionContext):
        payload = dict(request.payload)
        runtime_state_summary = str(payload.get("runtime_state_summary") or "")
        last_tool_call = payload.get("last_tool_call")
        trigger = str(payload.get("trigger") or "turn_end")

        observed = context.observe_module_call(
            target_module="CheckpointSafeSummary",
            function_called="CheckpointSafeSummary.redact",
            call_signature="redact(runtime_state_summary: str)",
            call=lambda: _safe_summary(runtime_state_summary),
        )
        safe_summary = observed.value
        no_tool_boundary_reached = last_tool_call is None and trigger == "turn_end"
        result_payload = {
            "safe_summary": safe_summary,
            "secret_content_detected": contains_secret_like(runtime_state_summary),
            "huge_prompt_truncated": len(runtime_state_summary) > 2000,
            "pending_high_risk_tool": payload.get("pending_high_risk_tool"),
            "checkpoint_boundary": "turn_end_before_save_checkpoint",
            "no_tool_boundary_reached": no_tool_boundary_reached,
        }
        return context.success(
            handler_name=type(self).__name__,
            target_module="CheckpointSafeSummary",
            payload=result_payload,
            observed_call=observed,
            evidence_extra={
                **result_payload,
                "checkpoint_schema_changed": False,
                "tool_after_only_trigger": False,
                "memory_hook_substituted": False,
            },
        )


def _safe_summary(text: str) -> str:
    masked = mask_user_visible_secrets(text)
    if len(masked) > 2000:
        return masked[:2000]
    return masked
