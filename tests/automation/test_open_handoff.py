from __future__ import annotations

from dataclasses import replace

import pytest

from agent.automation.contracts import (
    BackgroundOccurrenceAuthorityV1,
    ClaimOccurrence,
    OccurrenceControlStatus,
    OccurrenceSummaryV1,
    RecordOccurrenceOutcome,
)
from agent.automation.controller import AutomationController
from agent.automation.schedule import occurrence_identity
from agent.runtime.contracts import BackgroundOccurrenceBindingV1, ConversationState
from agent.runtime.views import project_background_recovery

from .test_management import _service


def _paused_handoff_fixture():  # noqa: ANN202
    service, repository, _, body = _service()
    service.create(
        body,
        expected_snapshot_token="snapshot-token-0000",
        next_snapshot_token="snapshot-token-0001",
    )
    preview = service.preview(body.automation_id)
    service.approve(
        body.automation_id,
        preview_digest=preview.preview_digest,
        expected_snapshot_token="snapshot-token-0001",
        next_snapshot_token="snapshot-token-0002",
    )
    definition = repository.load().records[0].definition
    assert definition is not None
    scheduled_for = definition.body.schedule.anchor_utc
    authority = BackgroundOccurrenceAuthorityV1(
        automation_id=body.automation_id,
        automation_revision=definition.body.revision,
        occurrence_id=occurrence_identity(definition, 0, scheduled_for),
        occurrence_index=0,
        scheduled_for_utc=scheduled_for,
        definition_digest=definition.definition_digest,
        grant_digest=definition.grant.grant_digest,
        claim_fencing_token="claim-token-0000",
        checkpoint_identity="c" * 64,
        deadline_utc="2026-08-28T00:10:00Z",
        raw_capability="opaque-capability-0000000000000000000000000000",
    )
    controller = AutomationController(repository)
    controller.handle(
        ClaimOccurrence(
            expected_snapshot_token="snapshot-token-0002",
            next_snapshot_token="snapshot-token-0003",
            authority=authority,
        )
    )
    controller.handle(
        RecordOccurrenceOutcome(
            expected_snapshot_token="snapshot-token-0003",
            next_snapshot_token="snapshot-token-0004",
            automation_id=body.automation_id,
            authority_digest=authority.authority_digest,
            summary=OccurrenceSummaryV1(
                occurrence_id=authority.occurrence_id,
                status=OccurrenceControlStatus.NEEDS_HUMAN,
                scheduled_for_utc=authority.scheduled_for_utc,
                definition_digest=authority.definition_digest,
                checkpoint_identity_digest=authority.checkpoint_identity,
                result_digest=None,
                replayed=False,
                error_code="approval_required",
            ),
        )
    )
    binding = BackgroundOccurrenceBindingV1.create(
        automation_id=authority.automation_id,
        automation_revision=authority.automation_revision,
        occurrence_id=authority.occurrence_id,
        occurrence_index=authority.occurrence_index,
        scheduled_for_utc=authority.scheduled_for_utc,
        definition_digest=authority.definition_digest,
        grant_digest=authority.grant_digest,
        claim_authority_digest=authority.authority_digest,
        claim_capability_digest="d" * 64,
        checkpoint_identity_digest=authority.checkpoint_identity,
        deadline_utc=authority.deadline_utc,
        model_call_limit=definition.body.budgets.model_calls,
        tool_call_limit=definition.body.budgets.tool_calls,
        sandbox_command_limit=definition.body.budgets.sandbox_commands,
        browser_action_limit=definition.body.budgets.browser_actions,
        max_input_tokens=definition.body.budgets.max_input_tokens,
        max_output_tokens=definition.body.budgets.max_output_tokens,
    )
    return service, repository, authority, ConversationState.new(
        "conversation:background",
        background_occurrence_binding=binding,
    )


def test_open_handoff_is_exact_and_runtime_projection_keeps_automation_paused() -> None:
    service, repository, _, state = _paused_handoff_fixture()
    handoff = service.open("automation:nightly-report")

    projection = project_background_recovery(
        state,
        automation_id=handoff.automation_id,
        automation_revision=handoff.automation_revision,
        occurrence_id=handoff.occurrence_id,
        checkpoint_identity_digest=handoff.checkpoint_identity,
        definition_digest=handoff.definition_digest,
    )

    assert projection.occurrence_id == handoff.occurrence_id
    assert repository.load().records[0].status.value == "paused"
    assert service.show(handoff.automation_id).next_actions == ("open",)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("automation_id", "automation:other"),
        ("automation_revision", 2),
        ("occurrence_id", "occurrence:other"),
        ("checkpoint_identity", "e" * 64),
        ("definition_digest", "f" * 64),
    ],
)
def test_open_handoff_drift_fails_before_any_runtime_action(
    field: str,
    replacement: object,
) -> None:
    service, repository, _, state = _paused_handoff_fixture()
    handoff = replace(service.open("automation:nightly-report"), **{field: replacement})

    with pytest.raises(ValueError, match="does not match"):
        project_background_recovery(
            state,
            automation_id=handoff.automation_id,
            automation_revision=handoff.automation_revision,
            occurrence_id=handoff.occurrence_id,
            checkpoint_identity_digest=handoff.checkpoint_identity,
            definition_digest=handoff.definition_digest,
        )

    assert repository.load().records[0].status.value == "paused"
