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
from agent.automation.management import AutomationManagementService
from agent.automation.schedule import occurrence_identity
from agent.automation.wake import DeterministicWakeAdapter, WakeInstallOutcome

from .test_management import _service


def _activate(service: AutomationManagementService, automation_id: str) -> None:
    preview = service.preview(automation_id)
    result = service.approve(
        automation_id,
        preview_digest=preview.preview_digest,
        expected_snapshot_token="snapshot-token-0001",
        next_snapshot_token="snapshot-token-0002",
    )
    assert result.code == "active"


@pytest.mark.parametrize(
    ("outcome", "expected_code"),
    [
        (WakeInstallOutcome.FAILED, "not_activated_install_failed"),
        (WakeInstallOutcome.UNKNOWN, "not_activated_install_unknown"),
    ],
)
def test_wake_install_failure_preserves_the_inactive_proposal(
    outcome: WakeInstallOutcome,
    expected_code: str,
) -> None:
    service, repository, _, body = _service(
        wake_adapter=DeterministicWakeAdapter(next_install_outcome=outcome)
    )
    service.create(
        body,
        expected_snapshot_token="snapshot-token-0000",
        next_snapshot_token="snapshot-token-0001",
    )
    preview = service.preview(body.automation_id)

    result = service.approve(
        body.automation_id,
        preview_digest=preview.preview_digest,
        expected_snapshot_token="snapshot-token-0001",
        next_snapshot_token="snapshot-token-0002",
    )

    assert result.code == expected_code
    assert repository.load().records[0].definition is None


def test_wake_install_then_activation_conflict_is_reported_without_running() -> None:
    repository_holder = {}

    def conflict_after_install() -> None:
        repository = repository_holder["repository"]
        with repository.try_acquire():
            current = repository.load()
            repository.compare_and_swap(
                expected_snapshot_token=current.snapshot_token,
                next_snapshot=replace(
                    current,
                    revision=current.revision + 1,
                    snapshot_token="snapshot-token-raced",
                ),
            )

    wake = DeterministicWakeAdapter(after_install=conflict_after_install)
    service, repository, workspace, body = _service(wake_adapter=wake)
    repository_holder["repository"] = repository
    service.create(
        body,
        expected_snapshot_token="snapshot-token-0000",
        next_snapshot_token="snapshot-token-0001",
    )
    preview = service.preview(body.automation_id)

    result = service.approve(
        body.automation_id,
        preview_digest=preview.preview_digest,
        expected_snapshot_token="snapshot-token-0001",
        next_snapshot_token="snapshot-token-0002",
    )

    assert result.code == "adapter_installed_activation_conflict"
    assert repository.load().records[0].definition is None

    retried = service.approve(
        body.automation_id,
        preview_digest=preview.preview_digest,
        expected_snapshot_token="snapshot-token-raced",
        next_snapshot_token="snapshot-token-0002",
    )
    assert retried.code == "active"
    assert wake.install_count == 1
    assert workspace.owned_object_count == 1


def test_needs_human_show_has_one_open_action_and_does_not_resume() -> None:
    service, repository, _, body = _service()
    service.create(
        body,
        expected_snapshot_token="snapshot-token-0000",
        next_snapshot_token="snapshot-token-0001",
    )
    _activate(service, body.automation_id)
    controller = AutomationController(repository)
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

    detail = service.show(body.automation_id)
    handoff = service.open(body.automation_id)

    assert detail.next_actions == ("open",)
    assert handoff.checkpoint_identity == authority.checkpoint_identity
    assert repository.load().records[0].status.value == "paused"
