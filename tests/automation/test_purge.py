from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from agent.automation.contracts import (
    AutomationRecordV1,
    AutomationSnapshotV1,
    AutomationStatus,
    AutomationTombstoneV1,
    BeginPurge,
    CancelAutomation,
    CreateProposal,
    FinishPurge,
    PurgeCleanupOutcome,
    PurgeObjectKind,
    PurgeOwnedObjectV1,
    PurgeOwnershipManifestV1,
    RecordPurgeProgress,
    StartPurgeObject,
    format_canonical_utc,
)
from agent.automation.controller import AutomationController, AutomationTransitionError
from agent.automation.management import PreviewConflictError
from agent.automation.reconcile import AutomationReconciler, ReconcileAutomationsV1
from agent.automation.store import (
    AutomationRepositoryUnknownCommitError,
    DeterministicAutomationRepository,
    DeterministicCommitFault,
)
from agent.automation.workspace import (
    SourceBindingV1,
    TerminalArtifactCandidateV1,
    VirtualNodeKind,
    VirtualSourceNodeV1,
    WorkspaceBoundsV1,
)

from .test_contracts import _body, _definition
from .test_controller import _active_repository
from .test_management import _service
from .test_reconcile import _token_factory

AUTOMATION_ID = "automation:nightly-report"


def _manifest() -> PurgeOwnershipManifestV1:
    return PurgeOwnershipManifestV1(
        automation_id=AUTOMATION_ID,
        automation_revision=1,
        occurrence_count=0,
        checkpoint_count=1,
        objects=(
            PurgeOwnedObjectV1(
                object_id="checkpoint:one",
                kind=PurgeObjectKind.RUNTIME_CHECKPOINT,
                identity_digest="1" * 64,
            ),
            PurgeOwnedObjectV1(
                object_id="external:one",
                kind=PurgeObjectKind.GOVERNED_EXTERNAL_REFERENCE,
                identity_digest="2" * 64,
            ),
        ),
    )


def _purge_pending_controller() -> AutomationController:
    controller = AutomationController(_active_repository())
    controller.handle(
        CancelAutomation(
            expected_snapshot_token="snapshot-token-0002",
            next_snapshot_token="snapshot-token-0003",
            automation_id=AUTOMATION_ID,
        )
    )
    manifest = _manifest()
    controller.handle(
        BeginPurge(
            expected_snapshot_token="snapshot-token-0003",
            next_snapshot_token="snapshot-token-0004",
            automation_id=AUTOMATION_ID,
            manifest=manifest,
            preview_digest=manifest.manifest_digest,
        )
    )
    return controller


def test_begin_purge_removes_private_definition_but_keeps_content_free_manifest() -> None:
    controller = _purge_pending_controller()

    record = controller.snapshot().records[0]
    assert record.definition is None
    assert record.draft_body is None
    assert record.terminal_history == ()
    assert record.purge_manifest == _manifest()


def test_purge_does_not_free_capacity_until_every_manifest_object_is_confirmed() -> None:
    controller = _purge_pending_controller()

    with pytest.raises(AutomationTransitionError, match="incomplete"):
        controller.handle(
            FinishPurge(
                expected_snapshot_token="snapshot-token-0004",
                next_snapshot_token="snapshot-token-0005",
                automation_id=AUTOMATION_ID,
                purged_at_utc="2026-08-28T01:00:00Z",
            )
        )
    assert len(controller.snapshot().records) == 1


def test_cleanup_unknown_is_durable_and_cannot_finish() -> None:
    controller = _purge_pending_controller()
    controller.handle(
        StartPurgeObject(
            expected_snapshot_token="snapshot-token-0004",
            next_snapshot_token="snapshot-token-0005",
            automation_id=AUTOMATION_ID,
            object_id="checkpoint:one",
        )
    )
    controller.handle(
        RecordPurgeProgress(
            expected_snapshot_token="snapshot-token-0005",
            next_snapshot_token="snapshot-token-0006",
            automation_id=AUTOMATION_ID,
            object_id="checkpoint:one",
            outcome=PurgeCleanupOutcome.CLEANUP_UNKNOWN,
        )
    )

    record = controller.snapshot().records[0]
    assert record.purge_cleanup_unknown_object_id == "checkpoint:one"
    with pytest.raises(AutomationTransitionError, match="unknown"):
        controller.handle(
            StartPurgeObject(
                expected_snapshot_token="snapshot-token-0006",
                next_snapshot_token="snapshot-token-0007",
                automation_id=AUTOMATION_ID,
                object_id="external:one",
            )
        )


def test_confirmed_objects_finish_to_compact_tombstone() -> None:
    controller = _purge_pending_controller()
    token_index = 4
    for object_id, outcome in (
        ("checkpoint:one", PurgeCleanupOutcome.CLEANED),
        ("external:one", PurgeCleanupOutcome.UNLINKED),
    ):
        controller.handle(
            StartPurgeObject(
                expected_snapshot_token=f"snapshot-token-{token_index:04d}",
                next_snapshot_token=f"snapshot-token-{token_index + 1:04d}",
                automation_id=AUTOMATION_ID,
                object_id=object_id,
            )
        )
        token_index += 1
        controller.handle(
            RecordPurgeProgress(
                expected_snapshot_token=f"snapshot-token-{token_index:04d}",
                next_snapshot_token=f"snapshot-token-{token_index + 1:04d}",
                automation_id=AUTOMATION_ID,
                object_id=object_id,
                outcome=outcome,
            )
        )
        token_index += 1

    result = controller.handle(
        FinishPurge(
            expected_snapshot_token=f"snapshot-token-{token_index:04d}",
            next_snapshot_token=f"snapshot-token-{token_index + 1:04d}",
            automation_id=AUTOMATION_ID,
            purged_at_utc="2026-08-28T01:00:00Z",
        )
    )

    assert result.snapshot.records == ()
    assert len(result.snapshot.tombstones) == 1
    assert result.snapshot.tombstones[0].automation_id == AUTOMATION_ID


def test_management_preview_is_manifest_bound_and_reconciler_converges() -> None:
    service, repository, workspace, body = _canceled_service()

    preview = service.preview_purge(body.automation_id)
    assert preview.owned_object_count == 1
    assert preview.external_reference_count == 0
    with pytest.raises(PreviewConflictError, match="does not match"):
        service.confirm_purge(
            body.automation_id,
            preview_digest="f" * 64,
            expected_snapshot_token="snapshot-token-0003",
            next_snapshot_token="snapshot-token-0004",
        )
    service.confirm_purge(
        body.automation_id,
        preview_digest=preview.preview_digest,
        expected_snapshot_token="snapshot-token-0003",
        next_snapshot_token="snapshot-token-0004",
    )

    reconciler = _purge_reconciler(repository, workspace, body)

    assert reconciler.reconcile(ReconcileAutomationsV1()).code == "purge_progress"
    assert reconciler.reconcile(ReconcileAutomationsV1()).code == "purge_progress"
    assert reconciler.reconcile(ReconcileAutomationsV1()).code == "purged"
    assert repository.load().records == ()
    assert repository.load().tombstones[0].automation_id == body.automation_id
    assert workspace.owned_objects(body.automation_id) == ()


def test_full_ownership_manifest_covers_every_purge_object_class() -> None:
    service, repository, workspace, body = _canceled_service()
    source = workspace.load_source_snapshot(
        body.source_snapshot_digest,
        owner_automation_id=body.automation_id,
    )
    occurrence_id = "occurrence:purge-fixture"
    occurrence_workspace = workspace.materialize_occurrence(source, occurrence_id)
    workspace.replace_workspace_nodes(
        occurrence_workspace.object_id,
        (
            VirtualSourceNodeV1(
                relative_path="report.md",
                kind=VirtualNodeKind.FILE,
                size_bytes=11,
                content_digest="3" * 64,
            ),
        ),
    )
    workspace.capture_terminal_outputs(
        occurrence_workspace,
        source,
        WorkspaceBoundsV1(),
        artifacts=(
            TerminalArtifactCandidateV1(
                artifact_id="artifact:report",
                size_bytes=10,
                content_digest="4" * 64,
            ),
        ),
    )
    workspace.admit_runtime_checkpoint(
        automation_id=body.automation_id,
        occurrence_id=occurrence_id,
        identity_digest="5" * 64,
    )
    workspace.admit_external_reference(
        object_id="external:report",
        identity_digest="6" * 64,
        owner_automation_id=body.automation_id,
    )

    preview = service.preview_purge(body.automation_id)
    kinds = {
        item.kind
        for item in workspace.owned_objects(body.automation_id)
    }

    assert kinds == set(PurgeObjectKind)
    assert preview.checkpoint_count == 1
    assert preview.owned_object_count == 5
    assert preview.external_reference_count == 1
    service.confirm_purge(
        body.automation_id,
        preview_digest=preview.preview_digest,
        expected_snapshot_token="snapshot-token-0003",
        next_snapshot_token="snapshot-token-0004",
    )
    reconciler = _purge_reconciler(repository, workspace, body)
    for _ in range(16):
        if reconciler.reconcile(ReconcileAutomationsV1()).code == "purged":
            break
    assert repository.load().records == ()
    assert workspace.owned_objects(body.automation_id) == ()


def _canceled_service():  # noqa: ANN202
    service, repository, workspace, body = _service()
    service.create(
        body,
        expected_snapshot_token="snapshot-token-0000",
        next_snapshot_token="snapshot-token-0001",
    )
    activation = service.preview(body.automation_id)
    service.approve(
        body.automation_id,
        preview_digest=activation.preview_digest,
        expected_snapshot_token="snapshot-token-0001",
        next_snapshot_token="snapshot-token-0002",
    )
    service.cancel(
        body.automation_id,
        expected_snapshot_token="snapshot-token-0002",
        next_snapshot_token="snapshot-token-0003",
    )
    return service, repository, workspace, body


def _purge_reconciler(repository, workspace, body):  # noqa: ANN001, ANN202
    return AutomationReconciler(
        controller=AutomationController(repository),
        workspace_repository=workspace,
        source_bindings={
            body.source_workspace_binding_digest: SourceBindingV1(
                binding_id="source:workspace",
                root_identity_digest="1" * 64,
                excluded_components=("private", "runtime"),
            )
        },
        workspace_bounds=WorkspaceBoundsV1(),
        executor=None,
        supervisor=None,
        clock=lambda: datetime(2026, 8, 28, 1, tzinfo=UTC),
        next_snapshot_token=_token_factory(5),
        claim_fencing_token=lambda: "unused-claim-token",
        raw_capability=lambda: "unused-capability-0000000000000000000000000000",
        checkpoint_identity=lambda: "c" * 64,
    )


@pytest.mark.parametrize(
    ("boundary", "fault"),
    [
        ("intent", DeterministicCommitFault.BEFORE_COMMIT),
        ("intent", DeterministicCommitFault.AFTER_COMMIT),
        ("progress", DeterministicCommitFault.BEFORE_COMMIT),
        ("progress", DeterministicCommitFault.AFTER_COMMIT),
        ("finish", DeterministicCommitFault.BEFORE_COMMIT),
        ("finish", DeterministicCommitFault.AFTER_COMMIT),
    ],
)
def test_purge_crash_boundaries_resume_without_recreating_private_definition(
    boundary: str,
    fault: DeterministicCommitFault,
) -> None:
    service, repository, workspace, body = _canceled_service()
    preview = service.preview_purge(body.automation_id)
    service.confirm_purge(
        body.automation_id,
        preview_digest=preview.preview_digest,
        expected_snapshot_token="snapshot-token-0003",
        next_snapshot_token="snapshot-token-0004",
    )
    reconciler = _purge_reconciler(repository, workspace, body)
    if boundary in {"progress", "finish"}:
        reconciler.reconcile(ReconcileAutomationsV1())
    if boundary == "finish":
        reconciler.reconcile(ReconcileAutomationsV1())
    repository.arm_commit_fault(fault)

    with pytest.raises(AutomationRepositoryUnknownCommitError):
        reconciler.reconcile(ReconcileAutomationsV1())

    for _ in range(4):
        result = reconciler.reconcile(ReconcileAutomationsV1())
        if result.code == "purged":
            break
    assert repository.load().records == ()
    assert repository.load().tombstones[0].automation_id == body.automation_id


def test_identity_replacement_becomes_cleanup_unknown_and_retains_capacity() -> None:
    service, repository, workspace, body = _canceled_service()
    preview = service.preview_purge(body.automation_id)
    service.confirm_purge(
        body.automation_id,
        preview_digest=preview.preview_digest,
        expected_snapshot_token="snapshot-token-0003",
        next_snapshot_token="snapshot-token-0004",
    )
    reconciler = _purge_reconciler(repository, workspace, body)
    assert reconciler.reconcile(ReconcileAutomationsV1()).code == "purge_progress"
    object_id = repository.load().records[0].purge_active_object_id
    assert object_id is not None
    workspace.replace_owned_identity(object_id, "e" * 64)

    result = reconciler.reconcile(ReconcileAutomationsV1())

    assert result.code == "purge_cleanup_unknown"
    assert len(repository.load().records) == 1
    assert repository.load().tombstones == ()


def test_governed_external_artifact_is_unlinked_only() -> None:
    service, repository, workspace, body = _canceled_service()
    workspace.admit_external_reference(
        object_id="external:one",
        identity_digest="e" * 64,
        owner_automation_id=body.automation_id,
    )
    preview = service.preview_purge(body.automation_id)
    assert preview.external_reference_count == 1
    service.confirm_purge(
        body.automation_id,
        preview_digest=preview.preview_digest,
        expected_snapshot_token="snapshot-token-0003",
        next_snapshot_token="snapshot-token-0004",
    )
    reconciler = _purge_reconciler(repository, workspace, body)

    for _ in range(8):
        if reconciler.reconcile(ReconcileAutomationsV1()).code == "purged":
            break

    assert repository.load().records == ()
    assert workspace.external_delete_count == 0


@pytest.mark.parametrize(
    "fault",
    [DeterministicCommitFault.BEFORE_COMMIT, DeterministicCommitFault.AFTER_COMMIT],
)
def test_external_unlink_commit_crash_resumes_without_external_delete(
    fault: DeterministicCommitFault,
) -> None:
    service, repository, workspace, body = _canceled_service()
    workspace.admit_external_reference(
        object_id="external:one",
        identity_digest="e" * 64,
        owner_automation_id=body.automation_id,
    )
    preview = service.preview_purge(body.automation_id)
    service.confirm_purge(
        body.automation_id,
        preview_digest=preview.preview_digest,
        expected_snapshot_token="snapshot-token-0003",
        next_snapshot_token="snapshot-token-0004",
    )
    reconciler = _purge_reconciler(repository, workspace, body)
    assert reconciler.reconcile(ReconcileAutomationsV1()).code == "purge_progress"
    assert repository.load().records[0].purge_active_object_id == "external:one"
    repository.arm_commit_fault(fault)

    with pytest.raises(AutomationRepositoryUnknownCommitError):
        reconciler.reconcile(ReconcileAutomationsV1())

    for _ in range(6):
        if reconciler.reconcile(ReconcileAutomationsV1()).code == "purged":
            break
    assert repository.load().records == ()
    assert workspace.external_delete_count == 0


def test_same_source_snapshot_is_owned_independently_per_automation() -> None:
    service, repository, workspace, body = _service()
    second = replace(
        body,
        automation_id="automation:second-report",
        definition_body_digest="",
    )
    token = 0
    for candidate in (body, second):
        service.create(
            candidate,
            expected_snapshot_token=f"snapshot-token-{token:04d}",
            next_snapshot_token=f"snapshot-token-{token + 1:04d}",
        )
        token += 1
        preview = service.preview(candidate.automation_id)
        service.approve(
            candidate.automation_id,
            preview_digest=preview.preview_digest,
            expected_snapshot_token=f"snapshot-token-{token:04d}",
            next_snapshot_token=f"snapshot-token-{token + 1:04d}",
        )
        token += 1
    assert len(workspace.owned_objects(body.automation_id)) == 1
    assert len(workspace.owned_objects(second.automation_id)) == 1

    service.cancel(
        body.automation_id,
        expected_snapshot_token=f"snapshot-token-{token:04d}",
        next_snapshot_token=f"snapshot-token-{token + 1:04d}",
    )
    token += 1
    preview = service.preview_purge(body.automation_id)
    service.confirm_purge(
        body.automation_id,
        preview_digest=preview.preview_digest,
        expected_snapshot_token=f"snapshot-token-{token:04d}",
        next_snapshot_token=f"snapshot-token-{token + 1:04d}",
    )
    reconciler = _purge_reconciler(repository, workspace, body)
    for _ in range(4):
        if reconciler.reconcile(ReconcileAutomationsV1()).code == "purged":
            break

    assert workspace.owned_objects(body.automation_id) == ()
    assert len(workspace.owned_objects(second.automation_id)) == 1


def test_finishing_129th_tombstone_evicts_only_the_oldest_confirmed_one() -> None:
    pending = _purge_pending_controller().snapshot().records[0]
    manifest = pending.purge_manifest
    assert manifest is not None
    pending = replace(
        pending,
        purge_confirmed_object_ids=tuple(item.object_id for item in manifest.objects),
    )
    base = datetime(2026, 8, 1, tzinfo=UTC)
    tombstones = tuple(
        AutomationTombstoneV1(
            automation_id=f"automation:old{index:03d}",
            purged_revision=1,
            purged_at_utc=format_canonical_utc(base + timedelta(minutes=index)),
        )
        for index in range(128)
    )
    repository = DeterministicAutomationRepository(
        AutomationSnapshotV1(
            revision=100,
            snapshot_token="snapshot-token-tombstone",
            records=(pending,),
            tombstones=tombstones,
        )
    )

    result = AutomationController(repository).handle(
        FinishPurge(
            expected_snapshot_token="snapshot-token-tombstone",
            next_snapshot_token="snapshot-token-finished",
            automation_id=AUTOMATION_ID,
            purged_at_utc="2026-08-29T00:00:00Z",
        )
    )

    assert len(result.snapshot.tombstones) == 128
    assert all(item.automation_id != "automation:old000" for item in result.snapshot.tombstones)
    assert any(item.automation_id == AUTOMATION_ID for item in result.snapshot.tombstones)


def test_full_record_capacity_is_freed_only_by_confirmed_finish_purge() -> None:
    terminal_records = tuple(
        AutomationRecordV1(
            definition=_definition(automation_id=f"automation:terminal{index:03d}"),
            status=AutomationStatus.CANCELED,
            next_occurrence_index=0,
            terminal_occurrence_count=0,
            needs_human_reason=None,
            active_claim=None,
            terminal_history=(),
        )
        for index in range(127)
    )
    manifest = _manifest()
    purge_record = AutomationRecordV1(
        definition=None,
        status=AutomationStatus.PURGE_PENDING,
        next_occurrence_index=0,
        terminal_occurrence_count=0,
        needs_human_reason=None,
        active_claim=None,
        terminal_history=(),
        purge_manifest=manifest,
        purge_confirmed_object_ids=tuple(item.object_id for item in manifest.objects),
    )
    repository = DeterministicAutomationRepository(
        AutomationSnapshotV1(
            revision=1,
            snapshot_token="snapshot-token-capacity",
            records=tuple(
                sorted((*terminal_records, purge_record), key=lambda item: item.automation_id)
            ),
            tombstones=(),
        )
    )
    controller = AutomationController(repository)
    new_body = replace(
        _body(),
        automation_id="automation:new-record",
        definition_body_digest="",
    )

    with pytest.raises(AutomationTransitionError, match="capacity"):
        controller.handle(
            CreateProposal(
                expected_snapshot_token="snapshot-token-capacity",
                next_snapshot_token="snapshot-token-rejected",
                body=new_body,
            )
        )
    controller.handle(
        FinishPurge(
            expected_snapshot_token="snapshot-token-capacity",
            next_snapshot_token="snapshot-token-freed",
            automation_id=AUTOMATION_ID,
            purged_at_utc="2026-08-29T00:00:00Z",
        )
    )
    result = controller.handle(
        CreateProposal(
            expected_snapshot_token="snapshot-token-freed",
            next_snapshot_token="snapshot-token-created",
            body=new_body,
        )
    )

    assert len(result.snapshot.records) == 128
