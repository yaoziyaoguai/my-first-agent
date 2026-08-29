from __future__ import annotations

from dataclasses import replace

import pytest

from agent.automation.contracts import (
    ApproveRevision,
    AutomationSnapshotV1,
    AutomationStatus,
    BackgroundOccurrenceAuthorityV1,
    CancelAutomation,
    ClaimOccurrence,
    CreateProposal,
    MarkDispatched,
    MarkRunning,
    OccurrenceControlStatus,
    OccurrenceSummaryV1,
    PauseAutomation,
    RecordOccurrenceOutcome,
    ResumeAutomation,
    StageRevision,
)
from agent.automation.controller import AutomationController, AutomationTransitionError
from agent.automation.schedule import occurrence_identity
from agent.automation.store import DeterministicAutomationRepository

from .test_contracts import _body, _definition


def _empty_snapshot() -> AutomationSnapshotV1:
    return AutomationSnapshotV1(
        revision=0,
        snapshot_token="snapshot-token-0000",
        records=(),
        tombstones=(),
    )


def _authority() -> BackgroundOccurrenceAuthorityV1:
    definition = _definition()
    scheduled_for = "2026-08-28T00:00:00Z"
    return BackgroundOccurrenceAuthorityV1(
        automation_id=definition.body.automation_id,
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


def _active_repository() -> DeterministicAutomationRepository:
    repository = DeterministicAutomationRepository(_empty_snapshot())
    controller = AutomationController(repository)
    controller.handle(
        CreateProposal(
            expected_snapshot_token="snapshot-token-0000",
            next_snapshot_token="snapshot-token-0001",
            body=_body(),
        )
    )
    controller.handle(
        ApproveRevision(
            expected_snapshot_token="snapshot-token-0001",
            next_snapshot_token="snapshot-token-0002",
            automation_id="automation:nightly-report",
            definition=_definition(),
            activation_preview_digest="9" * 64,
        )
    )
    return repository


def test_create_is_an_inactive_proposal_without_a_grant() -> None:
    repository = DeterministicAutomationRepository(_empty_snapshot())
    controller = AutomationController(repository)

    result = controller.handle(
        CreateProposal(
            expected_snapshot_token="snapshot-token-0000",
            next_snapshot_token="snapshot-token-0001",
            body=_body(),
        )
    )

    record = result.snapshot.records[0]
    assert record.status is AutomationStatus.PROPOSAL
    assert record.definition is None
    assert record.draft_body == _body()


def test_approval_binds_the_current_draft_and_preview() -> None:
    repository = DeterministicAutomationRepository(_empty_snapshot())
    controller = AutomationController(repository)
    controller.handle(
        CreateProposal(
            expected_snapshot_token="snapshot-token-0000",
            next_snapshot_token="snapshot-token-0001",
            body=_body(),
        )
    )

    result = controller.handle(
        ApproveRevision(
            expected_snapshot_token="snapshot-token-0001",
            next_snapshot_token="snapshot-token-0002",
            automation_id="automation:nightly-report",
            definition=_definition(),
            activation_preview_digest="9" * 64,
        )
    )

    record = result.snapshot.records[0]
    assert record.status is AutomationStatus.ACTIVE
    assert record.definition == _definition()
    assert record.draft_body is None


def test_approval_rejects_a_stale_draft_body() -> None:
    repository = DeterministicAutomationRepository(_empty_snapshot())
    controller = AutomationController(repository)
    controller.handle(
        CreateProposal(
            expected_snapshot_token="snapshot-token-0000",
            next_snapshot_token="snapshot-token-0001",
            body=_body(task_text="First task"),
        )
    )

    with pytest.raises(AutomationTransitionError, match="draft definition body"):
        controller.handle(
            ApproveRevision(
                expected_snapshot_token="snapshot-token-0001",
                next_snapshot_token="snapshot-token-0002",
                automation_id="automation:nightly-report",
                definition=_definition(task_text="Changed task"),
                activation_preview_digest="9" * 64,
            )
        )


def test_pause_resume_and_cancel_without_active_work_are_exact() -> None:
    repository = _active_repository()
    controller = AutomationController(repository)

    paused = controller.handle(
        PauseAutomation(
            expected_snapshot_token="snapshot-token-0002",
            next_snapshot_token="snapshot-token-0003",
            automation_id="automation:nightly-report",
        )
    )
    assert paused.snapshot.records[0].status is AutomationStatus.PAUSED

    resumed = controller.handle(
        ResumeAutomation(
            expected_snapshot_token="snapshot-token-0003",
            next_snapshot_token="snapshot-token-0004",
            automation_id="automation:nightly-report",
        )
    )
    assert resumed.snapshot.records[0].status is AutomationStatus.ACTIVE

    canceled = controller.handle(
        CancelAutomation(
            expected_snapshot_token="snapshot-token-0004",
            next_snapshot_token="snapshot-token-0005",
            automation_id="automation:nightly-report",
        )
    )
    assert canceled.snapshot.records[0].status is AutomationStatus.CANCELED


def test_cancel_running_becomes_pending_and_blocks_new_claim() -> None:
    repository = _active_repository()
    controller = AutomationController(repository)
    claimed = controller.handle(
        ClaimOccurrence(
            expected_snapshot_token="snapshot-token-0002",
            next_snapshot_token="snapshot-token-0003",
            authority=_authority(),
        )
    )
    assert claimed.snapshot.records[0].active_claim == _authority()

    canceled = controller.handle(
        CancelAutomation(
            expected_snapshot_token="snapshot-token-0003",
            next_snapshot_token="snapshot-token-0004",
            automation_id="automation:nightly-report",
        )
    )
    assert canceled.snapshot.records[0].status is AutomationStatus.CANCEL_PENDING

    with pytest.raises(AutomationTransitionError, match="cancel_pending"):
        controller.handle(
            ClaimOccurrence(
                expected_snapshot_token="snapshot-token-0004",
                next_snapshot_token="snapshot-token-0005",
                authority=replace(
                    _authority(),
                    occurrence_id="d" * 64,
                    occurrence_index=1,
                    scheduled_for_utc="2026-08-28T01:00:00Z",
                    authority_digest="",
                ),
            )
        )


def test_dispatch_running_and_completed_outcome_follow_one_claim() -> None:
    repository = _active_repository()
    controller = AutomationController(repository)
    authority = _authority()
    controller.handle(
        ClaimOccurrence(
            expected_snapshot_token="snapshot-token-0002",
            next_snapshot_token="snapshot-token-0003",
            authority=authority,
        )
    )
    dispatched = controller.handle(
        MarkDispatched(
            expected_snapshot_token="snapshot-token-0003",
            next_snapshot_token="snapshot-token-0004",
            automation_id=authority.automation_id,
            authority_digest=authority.authority_digest,
            process_identity_digest="e" * 64,
        )
    )
    assert dispatched.snapshot.records[0].active_claim_phase is (
        OccurrenceControlStatus.DISPATCHED
    )
    running = controller.handle(
        MarkRunning(
            expected_snapshot_token="snapshot-token-0004",
            next_snapshot_token="snapshot-token-0005",
            automation_id=authority.automation_id,
            authority_digest=authority.authority_digest,
            process_identity_digest="e" * 64,
        )
    )
    assert running.snapshot.records[0].active_claim_phase is OccurrenceControlStatus.RUNNING

    summary = OccurrenceSummaryV1(
        occurrence_id=authority.occurrence_id,
        status=OccurrenceControlStatus.COMPLETED,
        scheduled_for_utc=authority.scheduled_for_utc,
        definition_digest=authority.definition_digest,
        checkpoint_identity_digest=authority.checkpoint_identity,
        result_digest="f" * 64,
        replayed=False,
        error_code=None,
    )
    completed = controller.handle(
        RecordOccurrenceOutcome(
            expected_snapshot_token="snapshot-token-0005",
            next_snapshot_token="snapshot-token-0006",
            automation_id=authority.automation_id,
            authority_digest=authority.authority_digest,
            summary=summary,
        )
    )
    record = completed.snapshot.records[0]
    assert record.active_claim is None
    assert record.next_occurrence_index == 1
    assert record.terminal_occurrence_count == 1
    assert record.terminal_history == (summary,)


def test_claimed_occurrence_cannot_accept_a_runtime_completion_summary() -> None:
    repository = _active_repository()
    controller = AutomationController(repository)
    authority = _authority()
    controller.handle(
        ClaimOccurrence(
            expected_snapshot_token="snapshot-token-0002",
            next_snapshot_token="snapshot-token-0003",
            authority=authority,
        )
    )

    with pytest.raises(AutomationTransitionError, match="outcome does not match claim phase"):
        controller.handle(
            RecordOccurrenceOutcome(
                expected_snapshot_token="snapshot-token-0003",
                next_snapshot_token="snapshot-token-0004",
                automation_id=authority.automation_id,
                authority_digest=authority.authority_digest,
                summary=OccurrenceSummaryV1(
                    occurrence_id=authority.occurrence_id,
                    status=OccurrenceControlStatus.COMPLETED,
                    scheduled_for_utc=authority.scheduled_for_utc,
                    definition_digest=authority.definition_digest,
                    checkpoint_identity_digest=authority.checkpoint_identity,
                    result_digest="f" * 64,
                    replayed=False,
                    error_code=None,
                ),
            )
        )


@pytest.mark.parametrize(
    "status",
    [
        OccurrenceControlStatus.FAILED,
        OccurrenceControlStatus.WORKER_DEADLINE,
    ],
)
def test_claimed_occurrence_rejects_outcomes_that_require_a_later_phase(
    status: OccurrenceControlStatus,
) -> None:
    repository = _active_repository()
    controller = AutomationController(repository)
    authority = _authority()
    controller.handle(
        ClaimOccurrence(
            expected_snapshot_token="snapshot-token-0002",
            next_snapshot_token="snapshot-token-0003",
            authority=authority,
        )
    )

    with pytest.raises(AutomationTransitionError, match="outcome does not match claim phase"):
        controller.handle(
            RecordOccurrenceOutcome(
                expected_snapshot_token="snapshot-token-0003",
                next_snapshot_token="snapshot-token-0004",
                automation_id=authority.automation_id,
                authority_digest=authority.authority_digest,
                summary=OccurrenceSummaryV1(
                    occurrence_id=authority.occurrence_id,
                    status=status,
                    scheduled_for_utc=authority.scheduled_for_utc,
                    definition_digest=authority.definition_digest,
                    checkpoint_identity_digest=authority.checkpoint_identity,
                    result_digest=None,
                    replayed=False,
                    error_code="unproven_outcome",
                ),
            )
        )


def test_needs_human_outcome_keeps_exact_claim_and_pauses() -> None:
    repository = _active_repository()
    controller = AutomationController(repository)
    authority = _authority()
    controller.handle(
        ClaimOccurrence(
            expected_snapshot_token="snapshot-token-0002",
            next_snapshot_token="snapshot-token-0003",
            authority=authority,
        )
    )
    summary = OccurrenceSummaryV1(
        occurrence_id=authority.occurrence_id,
        status=OccurrenceControlStatus.NEEDS_HUMAN,
        scheduled_for_utc=authority.scheduled_for_utc,
        definition_digest=authority.definition_digest,
        checkpoint_identity_digest=authority.checkpoint_identity,
        result_digest=None,
        replayed=False,
        error_code="approval_required",
    )

    result = controller.handle(
        RecordOccurrenceOutcome(
            expected_snapshot_token="snapshot-token-0003",
            next_snapshot_token="snapshot-token-0004",
            automation_id=authority.automation_id,
            authority_digest=authority.authority_digest,
            summary=summary,
        )
    )

    record = result.snapshot.records[0]
    assert record.status is AutomationStatus.PAUSED
    assert record.active_claim == authority
    assert record.active_claim_phase is OccurrenceControlStatus.NEEDS_HUMAN
    assert record.needs_human_reason == "approval_required"

    with pytest.raises(AutomationTransitionError, match="paused"):
        controller.handle(
            ClaimOccurrence(
                expected_snapshot_token="snapshot-token-0004",
                next_snapshot_token="snapshot-token-0005",
                authority=replace(
                    authority,
                    claim_fencing_token="replacement-token",
                    raw_capability="replacement-capability-0000000000000000000000",
                    authority_digest="",
                ),
            )
        )


def test_update_approval_cuts_over_future_claims_but_preserves_active_claim() -> None:
    repository = _active_repository()
    controller = AutomationController(repository)
    authority = _authority()
    controller.handle(
        ClaimOccurrence(
            expected_snapshot_token="snapshot-token-0002",
            next_snapshot_token="snapshot-token-0003",
            authority=authority,
        )
    )
    next_body = _body(revision=2, task_text="Build the revised report.")
    controller.handle(
        StageRevision(
            expected_snapshot_token="snapshot-token-0003",
            next_snapshot_token="snapshot-token-0004",
            automation_id=authority.automation_id,
            body=next_body,
        )
    )
    next_definition = _definition(revision=2, task_text="Build the revised report.")

    result = controller.handle(
        ApproveRevision(
            expected_snapshot_token="snapshot-token-0004",
            next_snapshot_token="snapshot-token-0005",
            automation_id=authority.automation_id,
            definition=next_definition,
            activation_preview_digest="9" * 64,
        )
    )

    record = result.snapshot.records[0]
    assert record.definition == next_definition
    assert record.active_claim == authority
    assert record.active_claim_definition == _definition()
    assert record.next_occurrence_index == 0


def test_stale_update_approval_cannot_replace_a_newer_draft() -> None:
    repository = _active_repository()
    controller = AutomationController(repository)
    controller.handle(
        StageRevision(
            expected_snapshot_token="snapshot-token-0002",
            next_snapshot_token="snapshot-token-0003",
            automation_id="automation:nightly-report",
            body=_body(revision=2, task_text="Second revision"),
        )
    )
    controller.handle(
        StageRevision(
            expected_snapshot_token="snapshot-token-0003",
            next_snapshot_token="snapshot-token-0004",
            automation_id="automation:nightly-report",
            body=_body(revision=3, task_text="Third revision"),
        )
    )

    with pytest.raises(AutomationTransitionError, match="draft definition body"):
        controller.handle(
            ApproveRevision(
                expected_snapshot_token="snapshot-token-0004",
                next_snapshot_token="snapshot-token-0005",
                automation_id="automation:nightly-report",
                definition=_definition(revision=2, task_text="Second revision"),
                activation_preview_digest="9" * 64,
            )
        )
