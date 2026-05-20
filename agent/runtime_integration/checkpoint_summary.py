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
        evidence_extra = {
            **result_payload,
            "checkpoint_schema_changed": False,
            "tool_after_only_trigger": not no_tool_boundary_reached,
            "memory_hook_substituted": False,
        }
        if not no_tool_boundary_reached:
            # 中文学习注释：checkpoint runtime_e2e 证明的是 no-tool turn-end
            # 到 before save_checkpoint 的边界；tool-after-only 只能说明子系统可用，
            # 不能证明父 runtime 在无工具回合结束时会触达保存前安全摘要。
            evidence_extra["runtime_e2e_disqualified_reason"] = (
                "checkpoint boundary was not reached from no-tool turn end"
            )
        return context.success(
            handler_name=type(self).__name__,
            target_module="CheckpointSafeSummary",
            payload=result_payload,
            observed_call=observed,
            evidence_extra=evidence_extra,
        )


def _safe_summary(text: str) -> str:
    masked = mask_user_visible_secrets(text)
    if len(masked) > 2000:
        return masked[:2000]
    return masked
