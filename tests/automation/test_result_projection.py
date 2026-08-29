from __future__ import annotations

from dataclasses import replace

from agent.runtime.contracts import (
    BackgroundOccurrenceBindingV1,
    ConversationFact,
    ConversationState,
    FactKind,
    GoalStatus,
)
from agent.runtime.views import project_background_recovery
from tests.continuity.test_contracts import _goal


def _binding() -> BackgroundOccurrenceBindingV1:
    return BackgroundOccurrenceBindingV1.create(
        automation_id="automation:nightly-report",
        automation_revision=1,
        occurrence_id="occurrence:0000",
        occurrence_index=0,
        scheduled_for_utc="2026-08-28T00:00:00Z",
        definition_digest="1" * 64,
        grant_digest="2" * 64,
        claim_authority_digest="3" * 64,
        claim_capability_digest="4" * 64,
        checkpoint_identity_digest="5" * 64,
        deadline_utc="2026-08-28T00:10:00Z",
        model_call_limit=4,
        tool_call_limit=8,
        sandbox_command_limit=2,
        browser_action_limit=3,
        max_input_tokens=20_000,
        max_output_tokens=4_000,
    )


def test_owner_result_is_projected_from_runtime_checkpoint_not_automation_summary() -> None:
    state = ConversationState(
        conversation_id="conversation:background",
        goal=replace(_goal(), status=GoalStatus.BLOCKED),
        facts=(
            ConversationFact(
                fact_id="fact:blocked",
                kind=FactKind.ASSISTANT_MESSAGE,
                content={
                    "code": "blocked_claim",
                    "blocker": "Runtime approval is required.",
                    "safe_attempts": ["inspected the isolated snapshot"],
                    "resume_condition": "owner resolves the exact Runtime request",
                },
            ),
        ),
        background_occurrence_binding=_binding(),
    )

    projection = project_background_recovery(
        state,
        automation_id="automation:nightly-report",
        automation_revision=1,
        occurrence_id="occurrence:0000",
        checkpoint_identity_digest="5" * 64,
        definition_digest="1" * 64,
    )

    assert projection.goal.blocker == "Runtime approval is required."
    assert projection.goal.safe_attempts == ("inspected the isolated snapshot",)
    assert "result_digest" not in projection.__dataclass_fields__
