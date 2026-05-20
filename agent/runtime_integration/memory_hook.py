"""Memory turn-end proposal RuntimeAction handler."""

from __future__ import annotations

from agent.display_events import mask_user_visible_secrets
from agent.memory_contracts import MemoryDecisionType
from agent.memory_policy import DeterministicMemoryPolicy
from agent.runtime_integration.dispatcher import RuntimeActionContext
from agent.runtime_integration.schema import RuntimeActionRequest, contains_secret_like


class MemoryTurnEndProposalHandler:
    """turn-end / response-end memory proposal hook.

    这个 handler 不读取真实 memory episodes，不写 confirmed memory，只把候选转换为
    pending_review evidence，保持 no silent retain / no auto approve。
    """

    def __init__(self, *, policy: DeterministicMemoryPolicy | None = None) -> None:
        self._policy = policy or DeterministicMemoryPolicy()

    def handle(self, request: RuntimeActionRequest, context: RuntimeActionContext):
        payload = dict(request.payload)
        user_message = str(payload.get("user_message") or "")
        assistant_response = str(payload.get("assistant_response") or "")
        task_context_summary = str(payload.get("task_context_summary") or "")
        prior_snapshot = payload.get("prior_confirmed_memory_snapshot")

        observed = context.observe_module_call(
            target_module="MemoryPolicy",
            function_called="DeterministicMemoryPolicy.decide",
            call_signature="decide(text: str)",
            call=lambda: self._policy.decide(user_message),
        )
        decision = observed.value
        secret_like = contains_secret_like(user_message) or contains_secret_like(assistant_response)

        if secret_like or decision.decision_type is MemoryDecisionType.REJECT:
            result_payload = {
                "proposal_id": None,
                "disposition": "should_not_remember",
                "reason": "secret_like_detected" if secret_like else decision.reason,
                "secret_like_detected": True,
                "redacted_secret": True,
                "pending_review": False,
                "not_confirmed": True,
                "auto_approved": False,
                "real_episodes_read": False,
                "proposal_preview": "",
            }
            return context.rejected(
                handler_name=type(self).__name__,
                target_module="MemoryPolicy",
                payload=result_payload,
                observed_call=observed,
                evidence_extra={
                    **result_payload,
                    "turn_end_hook_invoked": True,
                    "input_included_user_message": bool(user_message),
                    "input_included_assistant_response": bool(assistant_response),
                    "input_included_task_context_summary": bool(task_context_summary),
                    "input_included_prior_confirmed_memory_snapshot": prior_snapshot is not None,
                    "no_silent_retain": True,
                },
                error_safe_preview=result_payload["reason"],
            )

        candidate = decision.target_candidate
        if decision.decision_type in {MemoryDecisionType.RETAIN, MemoryDecisionType.UPDATE} and candidate is not None:
            result_payload = {
                "proposal_id": candidate.id,
                "disposition": "proposed",
                "reason": decision.reason,
                "secret_like_detected": False,
                "redacted_secret": False,
                "pending_review": True,
                "not_confirmed": True,
                "auto_approved": False,
                "real_episodes_read": False,
                "proposal_preview": mask_user_visible_secrets(candidate.content)[:200],
            }
        else:
            result_payload = {
                "proposal_id": None,
                "disposition": "no_action",
                "reason": decision.reason,
                "secret_like_detected": False,
                "redacted_secret": False,
                "pending_review": False,
                "not_confirmed": True,
                "auto_approved": False,
                "real_episodes_read": False,
                "proposal_preview": "",
            }

        return context.success(
            handler_name=type(self).__name__,
            target_module="MemoryPolicy",
            payload=result_payload,
            observed_call=observed,
            evidence_extra={
                **result_payload,
                "turn_end_hook_invoked": True,
                "input_included_user_message": bool(user_message),
                "input_included_assistant_response": bool(assistant_response),
                "input_included_task_context_summary": bool(task_context_summary),
                "input_included_prior_confirmed_memory_snapshot": prior_snapshot is not None,
                "no_silent_retain": True,
            },
        )
