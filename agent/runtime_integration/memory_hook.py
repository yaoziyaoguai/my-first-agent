"""Memory turn-end proposal RuntimeAction handler."""

from __future__ import annotations

from agent.display_events import mask_user_visible_secrets
from agent.evidence_recorder import build_memory_evidence_metadata
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

    def _proposal_metadata(
        self,
        event_type: str,
        *,
        decision: str,
        reason: str,
        count: int = 0,
    ) -> dict:
        return build_memory_evidence_metadata(
            event_type=event_type,
            operation="propose",
            source_type="agent_suggested",
            decision=decision,
            policy_path="turn_end_memory_proposal",
            reason=reason,
            count=count,
            redacted=True,
        )

    def _base_evidence(
        self,
        *,
        result_payload: dict,
        user_message: str,
        assistant_response: str,
        task_context_summary: str,
        prior_snapshot: object,
    ) -> dict:
        """Return safe turn-end proposal evidence without raw ids or previews."""
        return {
            "disposition": result_payload["disposition"],
            "reason": result_payload["reason"],
            "secret_like_detected": result_payload["secret_like_detected"],
            "redacted_secret": result_payload["redacted_secret"],
            "pending_review": result_payload["pending_review"],
            "not_confirmed": result_payload["not_confirmed"],
            "auto_approved": result_payload["auto_approved"],
            "real_episodes_read": result_payload["real_episodes_read"],
            "turn_end_hook_invoked": True,
            "input_included_user_message": bool(user_message),
            "input_included_assistant_response": bool(assistant_response),
            "input_included_task_context_summary": bool(task_context_summary),
            "input_included_prior_confirmed_memory_snapshot": prior_snapshot is not None,
            "no_silent_retain": True,
        }

    def handle(self, request: RuntimeActionRequest, context: RuntimeActionContext):
        payload = dict(request.payload)
        user_message = str(payload.get("user_message") or "")
        assistant_response = str(payload.get("assistant_response") or "")
        task_context_summary = str(payload.get("task_context_summary") or "")
        prior_snapshot = payload.get("prior_confirmed_memory_snapshot")

        observed = context.invoke_registered_target(
            target_module="MemoryPolicy",
            operation="decide",
            payload={"policy": self._policy, "user_message": user_message},
        )
        decision = observed.value
        secret_like = contains_secret_like(user_message) or contains_secret_like(assistant_response)

        if secret_like or decision.decision_type is MemoryDecisionType.REJECT:
            reason = "secret_like_detected" if secret_like else decision.reason
            result_payload = {
                "proposal_id": None,
                "disposition": "should_not_remember",
                "reason": reason,
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
                    **self._base_evidence(
                        result_payload=result_payload,
                        user_message=user_message,
                        assistant_response=assistant_response,
                        task_context_summary=task_context_summary,
                        prior_snapshot=prior_snapshot,
                    ),
                    "memory_proposal_skipped": self._proposal_metadata(
                        "memory.proposal_skipped",
                        decision="skipped",
                        reason=reason,
                    ),
                },
                error_safe_preview=result_payload["reason"],
        )

        candidate = decision.target_candidate
        if (
            decision.decision_type in {MemoryDecisionType.RETAIN, MemoryDecisionType.UPDATE}
            and candidate is not None
        ):
            proposal_evidence = {
                "memory_proposed": build_memory_evidence_metadata(
                    event_type="memory.proposed",
                    operation="propose",
                    source_type="agent_suggested",
                    decision="pending",
                    policy_path="turn_end_memory_proposal",
                    reason=decision.reason,
                    count=1,
                    memory_id=candidate.id,
                    raw_fields={
                        "candidate_id": candidate.id,
                        "content_summary": candidate.content,
                    },
                ),
                "memory_proposal_deferred": self._proposal_metadata(
                    "memory.proposal_deferred",
                    decision="deferred",
                    reason="user_confirmation_required",
                    count=1,
                ),
            }
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
            proposal_evidence = {
                "memory_proposal_skipped": self._proposal_metadata(
                    "memory.proposal_skipped",
                    decision="skipped",
                    reason=decision.reason or "no_candidate",
                ),
            }
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
                **self._base_evidence(
                    result_payload=result_payload,
                    user_message=user_message,
                    assistant_response=assistant_response,
                    task_context_summary=task_context_summary,
                    prior_snapshot=prior_snapshot,
                ),
                **proposal_evidence,
            },
        )
