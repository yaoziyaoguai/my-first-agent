"""019 AutomationStore 的唯一 mutation owner。

Controller 只做短 lease 下的 strict load/reduce/CAS；它不读 clock、不生成随机数、
不打开 Runtime checkpoint，也不调用 provider、supervisor 或 tool。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from agent.automation.contracts import (
    ApproveRevision,
    AutomationControllerResultV1,
    AutomationMutationV1,
    AutomationRecordV1,
    AutomationSnapshotV1,
    AutomationStatus,
    AutomationTombstoneV1,
    BeginPurge,
    CancelAutomation,
    ClaimOccurrence,
    CreateProposal,
    FinishPurge,
    MarkDispatched,
    MarkRunning,
    OccurrenceControlStatus,
    PauseAutomation,
    PurgeCleanupOutcome,
    RecordOccurrenceOutcome,
    RecordPurgeProgress,
    ResumeAutomation,
    StageRevision,
    StartPurgeObject,
    format_canonical_utc,
    parse_canonical_utc,
)
from agent.automation.schedule import occurrence_identity
from agent.automation.store import (
    AutomationRepository,
    AutomationRepositoryConflictError,
)


class AutomationTransitionError(RuntimeError):
    """Typed action is invalid for the current canonical snapshot."""


class AutomationController:
    def __init__(self, repository: AutomationRepository) -> None:
        self._repository = repository

    def snapshot(self) -> AutomationSnapshotV1:
        """Return a detached read-only snapshot; CAS remains private to this owner."""

        return self._repository.load()

    def handle(self, action: AutomationMutationV1) -> AutomationControllerResultV1:
        if not isinstance(
            action,
            (
                CreateProposal,
                ApproveRevision,
                StageRevision,
                PauseAutomation,
                ResumeAutomation,
                CancelAutomation,
                BeginPurge,
                StartPurgeObject,
                RecordPurgeProgress,
                FinishPurge,
                ClaimOccurrence,
                MarkDispatched,
                MarkRunning,
                RecordOccurrenceOutcome,
            ),
        ):
            raise TypeError("action must be a closed automation mutation")
        with self._repository.try_acquire():
            current = self._repository.load()
            if action.expected_snapshot_token != current.snapshot_token:
                raise AutomationRepositoryConflictError("automation snapshot token conflict")
            next_snapshot = _reduce(current, action)
            self._repository.compare_and_swap(
                expected_snapshot_token=action.expected_snapshot_token,
                next_snapshot=next_snapshot,
            )
        return AutomationControllerResultV1(code="applied", snapshot=next_snapshot)


def _reduce(
    snapshot: AutomationSnapshotV1,
    action: AutomationMutationV1,
) -> AutomationSnapshotV1:
    if isinstance(action, CreateProposal):
        return _create_proposal(snapshot, action)
    if isinstance(action, ApproveRevision):
        return _approve_revision(snapshot, action)
    if isinstance(action, StageRevision):
        return _stage_revision(snapshot, action)
    if isinstance(action, PauseAutomation):
        return _pause(snapshot, action)
    if isinstance(action, ResumeAutomation):
        return _resume(snapshot, action)
    if isinstance(action, CancelAutomation):
        return _cancel(snapshot, action)
    if isinstance(action, BeginPurge):
        return _begin_purge(snapshot, action)
    if isinstance(action, StartPurgeObject):
        return _start_purge_object(snapshot, action)
    if isinstance(action, RecordPurgeProgress):
        return _record_purge_progress(snapshot, action)
    if isinstance(action, FinishPurge):
        return _finish_purge(snapshot, action)
    if isinstance(action, ClaimOccurrence):
        return _claim(snapshot, action)
    if isinstance(action, MarkDispatched):
        return _mark_dispatched(snapshot, action)
    if isinstance(action, MarkRunning):
        return _mark_running(snapshot, action)
    if isinstance(action, RecordOccurrenceOutcome):
        return _record_occurrence_outcome(snapshot, action)
    raise TypeError("unsupported automation mutation")


def _create_proposal(
    snapshot: AutomationSnapshotV1,
    action: CreateProposal,
) -> AutomationSnapshotV1:
    automation_id = action.body.automation_id
    if _find_record(snapshot, automation_id) is not None or any(
        item.automation_id == automation_id for item in snapshot.tombstones
    ):
        raise AutomationTransitionError("automation id already exists")
    if len(snapshot.records) >= 128:
        raise AutomationTransitionError("automation record capacity reached")
    record = AutomationRecordV1(
        definition=None,
        status=AutomationStatus.PROPOSAL,
        next_occurrence_index=0,
        terminal_occurrence_count=0,
        needs_human_reason=None,
        active_claim=None,
        terminal_history=(),
        draft_body=action.body,
    )
    return _next_snapshot(snapshot, action.next_snapshot_token, (*snapshot.records, record))


def _approve_revision(
    snapshot: AutomationSnapshotV1,
    action: ApproveRevision,
) -> AutomationSnapshotV1:
    record = _require_record(snapshot, action.automation_id)
    if record.draft_body is None:
        raise AutomationTransitionError("automation has no draft definition body")
    if record.draft_body.definition_body_digest != action.definition.body.definition_body_digest:
        raise AutomationTransitionError("approval does not match draft definition body")
    if action.definition.body.automation_id != action.automation_id:
        raise AutomationTransitionError("approval automation id mismatch")
    if (
        action.definition.grant.activation_preview_digest
        != action.activation_preview_digest
    ):
        raise AutomationTransitionError("approval does not match activation preview")
    if record.definition is not None and (
        action.definition.body.revision <= record.definition.body.revision
    ):
        raise AutomationTransitionError("approved revision must advance")
    replacement = replace(
        record,
        definition=action.definition,
        draft_body=None,
        status=(
            record.status
            if record.status in {AutomationStatus.PAUSED, AutomationStatus.CANCEL_PENDING}
            else AutomationStatus.ACTIVE
        ),
        next_occurrence_index=0,
        terminal_occurrence_count=0,
    )
    return _replace_record(snapshot, replacement, action.next_snapshot_token)


def _stage_revision(
    snapshot: AutomationSnapshotV1,
    action: StageRevision,
) -> AutomationSnapshotV1:
    record = _require_record(snapshot, action.automation_id)
    if record.definition is None:
        raise AutomationTransitionError("proposal must be approved before update")
    if record.status in {
        AutomationStatus.CANCELED,
        AutomationStatus.PURGE_PENDING,
        AutomationStatus.PURGED,
    }:
        raise AutomationTransitionError("terminal automation cannot be updated")
    if action.body.automation_id != action.automation_id:
        raise AutomationTransitionError("draft automation id mismatch")
    newest_revision = max(
        record.definition.body.revision,
        record.draft_body.revision if record.draft_body is not None else 0,
    )
    if action.body.revision <= newest_revision:
        raise AutomationTransitionError("draft revision must advance")
    replacement = replace(record, draft_body=action.body)
    return _replace_record(snapshot, replacement, action.next_snapshot_token)


def _pause(
    snapshot: AutomationSnapshotV1,
    action: PauseAutomation,
) -> AutomationSnapshotV1:
    record = _require_record(snapshot, action.automation_id)
    if record.status not in {AutomationStatus.ACTIVE, AutomationStatus.PAUSED}:
        raise AutomationTransitionError("only active automation can be paused")
    replacement = replace(record, status=AutomationStatus.PAUSED)
    return _replace_record(snapshot, replacement, action.next_snapshot_token)


def _resume(
    snapshot: AutomationSnapshotV1,
    action: ResumeAutomation,
) -> AutomationSnapshotV1:
    record = _require_record(snapshot, action.automation_id)
    if record.status is not AutomationStatus.PAUSED:
        raise AutomationTransitionError("only paused automation can be resumed")
    if record.active_claim is not None or record.needs_human_reason is not None:
        raise AutomationTransitionError("paused automation still has unresolved occurrence")
    replacement = replace(record, status=AutomationStatus.ACTIVE)
    return _replace_record(snapshot, replacement, action.next_snapshot_token)


def _cancel(
    snapshot: AutomationSnapshotV1,
    action: CancelAutomation,
) -> AutomationSnapshotV1:
    record = _require_record(snapshot, action.automation_id)
    if record.status in {AutomationStatus.CANCELED, AutomationStatus.PURGE_PENDING}:
        raise AutomationTransitionError("automation is already terminal or purging")
    status = (
        AutomationStatus.CANCEL_PENDING
        if record.active_claim is not None
        else AutomationStatus.CANCELED
    )
    replacement = replace(record, status=status)
    return _replace_record(snapshot, replacement, action.next_snapshot_token)


def _begin_purge(
    snapshot: AutomationSnapshotV1,
    action: BeginPurge,
) -> AutomationSnapshotV1:
    record = _require_record(snapshot, action.automation_id)
    if record.status is not AutomationStatus.CANCELED or record.active_claim is not None:
        raise AutomationTransitionError("only fully terminal automation can begin purge")
    definition = record.definition
    assert definition is not None
    if (
        action.manifest.automation_revision != definition.body.revision
        or action.manifest.occurrence_count != record.terminal_occurrence_count
    ):
        raise AutomationTransitionError("purge manifest does not match terminal record")
    replacement = AutomationRecordV1(
        definition=None,
        draft_body=None,
        status=AutomationStatus.PURGE_PENDING,
        next_occurrence_index=record.next_occurrence_index,
        terminal_occurrence_count=record.terminal_occurrence_count,
        needs_human_reason=None,
        active_claim=None,
        terminal_history=(),
        purge_manifest=action.manifest,
    )
    return _replace_record(snapshot, replacement, action.next_snapshot_token)


def _start_purge_object(
    snapshot: AutomationSnapshotV1,
    action: StartPurgeObject,
) -> AutomationSnapshotV1:
    record = _require_record(snapshot, action.automation_id)
    if record.status is not AutomationStatus.PURGE_PENDING:
        raise AutomationTransitionError("automation is not purge pending")
    assert record.purge_manifest is not None
    if record.purge_cleanup_unknown_object_id is not None:
        raise AutomationTransitionError("purge cleanup outcome is unknown")
    if record.purge_active_object_id is not None:
        if record.purge_active_object_id == action.object_id:
            return _replace_record(snapshot, record, action.next_snapshot_token)
        raise AutomationTransitionError("another purge object is active")
    known = {item.object_id for item in record.purge_manifest.objects}
    if action.object_id not in known or action.object_id in record.purge_confirmed_object_ids:
        raise AutomationTransitionError("purge object is not pending")
    return _replace_record(
        snapshot,
        replace(record, purge_active_object_id=action.object_id),
        action.next_snapshot_token,
    )


def _record_purge_progress(
    snapshot: AutomationSnapshotV1,
    action: RecordPurgeProgress,
) -> AutomationSnapshotV1:
    record = _require_record(snapshot, action.automation_id)
    if (
        record.status is not AutomationStatus.PURGE_PENDING
        or record.purge_active_object_id != action.object_id
    ):
        raise AutomationTransitionError("purge progress does not match active object")
    if action.outcome is PurgeCleanupOutcome.CLEANUP_UNKNOWN:
        replacement = replace(
            record,
            purge_cleanup_unknown_object_id=action.object_id,
        )
    else:
        assert record.purge_manifest is not None
        expected = next(
            item for item in record.purge_manifest.objects if item.object_id == action.object_id
        )
        if (
            expected.kind.value == "governed_external_reference"
            and action.outcome is not PurgeCleanupOutcome.UNLINKED
        ) or (
            expected.kind.value != "governed_external_reference"
            and action.outcome is not PurgeCleanupOutcome.CLEANED
        ):
            raise AutomationTransitionError("purge cleanup outcome does not match object kind")
        replacement = replace(
            record,
            purge_confirmed_object_ids=tuple(
                sorted((*record.purge_confirmed_object_ids, action.object_id))
            ),
            purge_active_object_id=None,
            purge_cleanup_unknown_object_id=None,
        )
    return _replace_record(snapshot, replacement, action.next_snapshot_token)


def _finish_purge(
    snapshot: AutomationSnapshotV1,
    action: FinishPurge,
) -> AutomationSnapshotV1:
    record = _require_record(snapshot, action.automation_id)
    if record.status is not AutomationStatus.PURGE_PENDING:
        raise AutomationTransitionError("automation is not purge pending")
    assert record.purge_manifest is not None
    expected_ids = tuple(item.object_id for item in record.purge_manifest.objects)
    if (
        record.purge_active_object_id is not None
        or record.purge_cleanup_unknown_object_id is not None
        or record.purge_confirmed_object_ids != expected_ids
    ):
        raise AutomationTransitionError("purge cleanup is incomplete")
    tombstone = AutomationTombstoneV1(
        automation_id=action.automation_id,
        purged_revision=record.purge_manifest.automation_revision,
        purged_at_utc=action.purged_at_utc,
    )
    records = tuple(item for item in snapshot.records if item.automation_id != action.automation_id)
    tombstones = (*snapshot.tombstones, tombstone)
    if len(tombstones) > 128:
        oldest = min(tombstones, key=lambda item: (item.purged_at_utc, item.automation_id))
        tombstones = tuple(item for item in tombstones if item is not oldest)
    return AutomationSnapshotV1(
        revision=snapshot.revision + 1,
        snapshot_token=action.next_snapshot_token,
        records=tuple(sorted(records, key=lambda item: item.automation_id)),
        tombstones=tuple(sorted(tombstones, key=lambda item: item.automation_id)),
    )


def _claim(
    snapshot: AutomationSnapshotV1,
    action: ClaimOccurrence,
) -> AutomationSnapshotV1:
    authority = action.authority
    record = _require_record(snapshot, authority.automation_id)
    if record.status is not AutomationStatus.ACTIVE:
        raise AutomationTransitionError(f"automation is {record.status.value}")
    if record.active_claim is not None or any(
        candidate.active_claim is not None for candidate in snapshot.records
    ):
        raise AutomationTransitionError("global occurrence concurrency is FORBID")
    definition = record.definition
    assert definition is not None
    if (
        authority.automation_revision != definition.body.revision
        or authority.definition_digest != definition.definition_digest
        or authority.grant_digest != definition.grant.grant_digest
    ):
        raise AutomationTransitionError("occurrence authority does not match active definition")
    if authority.occurrence_index != record.next_occurrence_index:
        raise AutomationTransitionError("occurrence index does not match schedule cursor")
    expected_id = occurrence_identity(
        definition,
        authority.occurrence_index,
        authority.scheduled_for_utc,
    )
    if authority.occurrence_id != expected_id:
        raise AutomationTransitionError("occurrence identity mismatch")
    scheduled = parse_canonical_utc(authority.scheduled_for_utc, "scheduled_for_utc")
    expected_deadline = format_canonical_utc(
        scheduled
        + timedelta(seconds=definition.body.budgets.occurrence_deadline_seconds)
    )
    if authority.deadline_utc != expected_deadline:
        raise AutomationTransitionError("occurrence deadline mismatch")
    replacement = replace(
        record,
        active_claim=authority,
        active_claim_phase=OccurrenceControlStatus.CLAIMED,
        active_claim_definition=definition,
        active_process_identity_digest=None,
    )
    return _replace_record(snapshot, replacement, action.next_snapshot_token)


def _require_exact_claim(
    snapshot: AutomationSnapshotV1,
    automation_id: str,
    authority_digest: str,
) -> AutomationRecordV1:
    record = _require_record(snapshot, automation_id)
    if record.active_claim is None:
        raise AutomationTransitionError("automation has no active occurrence claim")
    if record.active_claim.authority_digest != authority_digest:
        raise AutomationTransitionError("occurrence authority digest mismatch")
    return record


def _mark_dispatched(
    snapshot: AutomationSnapshotV1,
    action: MarkDispatched,
) -> AutomationSnapshotV1:
    record = _require_exact_claim(
        snapshot,
        action.automation_id,
        action.authority_digest,
    )
    if record.active_claim_phase is not OccurrenceControlStatus.CLAIMED:
        raise AutomationTransitionError("only claimed occurrence can be dispatched")
    replacement = replace(
        record,
        active_claim_phase=OccurrenceControlStatus.DISPATCHED,
        active_process_identity_digest=action.process_identity_digest,
    )
    return _replace_record(snapshot, replacement, action.next_snapshot_token)


def _mark_running(
    snapshot: AutomationSnapshotV1,
    action: MarkRunning,
) -> AutomationSnapshotV1:
    record = _require_exact_claim(
        snapshot,
        action.automation_id,
        action.authority_digest,
    )
    if record.active_claim_phase is not OccurrenceControlStatus.DISPATCHED:
        raise AutomationTransitionError("only dispatched occurrence can be running")
    if record.active_process_identity_digest != action.process_identity_digest:
        raise AutomationTransitionError("process identity digest mismatch")
    replacement = replace(record, active_claim_phase=OccurrenceControlStatus.RUNNING)
    return _replace_record(snapshot, replacement, action.next_snapshot_token)


_SAFE_TERMINAL_OUTCOMES = {
    OccurrenceControlStatus.COMPLETED,
    OccurrenceControlStatus.FAILED,
    OccurrenceControlStatus.MISFIRE_SKIPPED,
    OccurrenceControlStatus.SUPERSEDED,
    OccurrenceControlStatus.WORKER_DEADLINE,
    OccurrenceControlStatus.CANCELED,
}

_UNRESOLVED_OUTCOMES = {
    OccurrenceControlStatus.NEEDS_HUMAN,
    OccurrenceControlStatus.START_OUTCOME_UNKNOWN,
    OccurrenceControlStatus.MODEL_OUTCOME_UNKNOWN,
    OccurrenceControlStatus.EFFECT_OUTCOME_UNKNOWN,
    OccurrenceControlStatus.CLEANUP_UNKNOWN,
}

_TERMINAL_OUTCOMES_BY_CLAIM_PHASE = {
    OccurrenceControlStatus.CLAIMED: frozenset(
        {
            OccurrenceControlStatus.MISFIRE_SKIPPED,
            OccurrenceControlStatus.SUPERSEDED,
            OccurrenceControlStatus.CANCELED,
        }
    ),
    OccurrenceControlStatus.RUNNING: frozenset(
        {
            OccurrenceControlStatus.COMPLETED,
            OccurrenceControlStatus.FAILED,
            OccurrenceControlStatus.WORKER_DEADLINE,
            OccurrenceControlStatus.CANCELED,
        }
    ),
}


def _record_occurrence_outcome(
    snapshot: AutomationSnapshotV1,
    action: RecordOccurrenceOutcome,
) -> AutomationSnapshotV1:
    record = _require_exact_claim(
        snapshot,
        action.automation_id,
        action.authority_digest,
    )
    claim = record.active_claim
    assert claim is not None
    phase = record.active_claim_phase
    assert phase is not None
    summary = action.summary
    if (
        summary.occurrence_id != claim.occurrence_id
        or summary.scheduled_for_utc != claim.scheduled_for_utc
        or summary.definition_digest != claim.definition_digest
        or summary.checkpoint_identity_digest != claim.checkpoint_identity
    ):
        raise AutomationTransitionError("occurrence summary does not match active claim")
    if summary.status in _SAFE_TERMINAL_OUTCOMES and summary.status not in (
        _TERMINAL_OUTCOMES_BY_CLAIM_PHASE.get(phase, frozenset())
    ):
        raise AutomationTransitionError("outcome does not match claim phase")
    if summary.status in _UNRESOLVED_OUTCOMES:
        if not summary.error_code:
            raise AutomationTransitionError("unresolved outcome requires an error code")
        replacement = replace(
            record,
            status=AutomationStatus.PAUSED,
            needs_human_reason=summary.error_code,
            active_claim_phase=summary.status,
        )
        return _replace_record(snapshot, replacement, action.next_snapshot_token)
    if summary.status not in _SAFE_TERMINAL_OUTCOMES:
        raise AutomationTransitionError("outcome is not terminal or needs-human")
    if len(record.terminal_history) >= 128:
        raise AutomationTransitionError("terminal history capacity reached")
    status = (
        AutomationStatus.CANCELED
        if record.status is AutomationStatus.CANCEL_PENDING
        else record.status
        if record.status is AutomationStatus.PAUSED
        else AutomationStatus.ACTIVE
    )
    replacement = replace(
        record,
        status=status,
        next_occurrence_index=claim.occurrence_index + 1,
        terminal_occurrence_count=record.terminal_occurrence_count + 1,
        needs_human_reason=None,
        active_claim=None,
        active_claim_phase=None,
        active_claim_definition=None,
        active_process_identity_digest=None,
        terminal_history=(*record.terminal_history, summary),
    )
    return _replace_record(snapshot, replacement, action.next_snapshot_token)


def _require_record(snapshot: AutomationSnapshotV1, automation_id: str) -> AutomationRecordV1:
    record = _find_record(snapshot, automation_id)
    if record is None:
        raise AutomationTransitionError("automation not found")
    return record


def _find_record(
    snapshot: AutomationSnapshotV1,
    automation_id: str,
) -> AutomationRecordV1 | None:
    return next(
        (record for record in snapshot.records if record.automation_id == automation_id),
        None,
    )


def _replace_record(
    snapshot: AutomationSnapshotV1,
    replacement: AutomationRecordV1,
    next_snapshot_token: str,
) -> AutomationSnapshotV1:
    records = tuple(
        replacement if record.automation_id == replacement.automation_id else record
        for record in snapshot.records
    )
    return _next_snapshot(snapshot, next_snapshot_token, records)


def _next_snapshot(
    snapshot: AutomationSnapshotV1,
    next_snapshot_token: str,
    records: tuple[AutomationRecordV1, ...],
) -> AutomationSnapshotV1:
    return AutomationSnapshotV1(
        revision=snapshot.revision + 1,
        snapshot_token=next_snapshot_token,
        records=tuple(sorted(records, key=lambda record: record.automation_id)),
        tombstones=snapshot.tombstones,
    )
