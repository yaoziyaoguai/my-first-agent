"""One-shot 019 schedule reconciliation over typed controller transitions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from agent.automation.contracts import (
    AutomationRecordV1,
    AutomationStatus,
    BackgroundOccurrenceAuthorityV1,
    ClaimOccurrence,
    FinishPurge,
    MarkDispatched,
    MarkRunning,
    OccurrenceControlStatus,
    OccurrenceSummaryV1,
    PurgeCleanupOutcome,
    RecordOccurrenceOutcome,
    RecordPurgeProgress,
    ScheduleDecisionKind,
    StartPurgeObject,
    format_canonical_utc,
    parse_canonical_utc,
)
from agent.automation.controller import AutomationController
from agent.automation.schedule import occurrence_identity, resolve_schedule
from agent.automation.supervisor import (
    OccurrenceExecutionResultV1,
    OccurrenceExecutor,
    OccurrenceStartCallbacks,
    OccurrenceSupervisor,
    PreparedOccurrenceV1,
    SupervisedOccurrenceSpecV1,
)
from agent.automation.workspace import (
    CleanupOutcome,
    OwnedObjectV1,
    OwnedWorkspaceRepository,
    SourceBindingV1,
    WorkspaceBoundsV1,
)
from agent.runtime.contracts import canonical_json_digest

_SAFE_TERMINAL = {
    OccurrenceControlStatus.COMPLETED,
    OccurrenceControlStatus.FAILED,
    OccurrenceControlStatus.WORKER_DEADLINE,
    OccurrenceControlStatus.CANCELED,
}


@dataclass(frozen=True, slots=True)
class ReconcileAutomationsV1:
    schema_version: int = 1
    delivery_id: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise ValueError("unsupported reconcile schema version")
        if self.delivery_id is not None and (
            not isinstance(self.delivery_id, str) or not 1 <= len(self.delivery_id) <= 64
        ):
            raise ValueError("delivery_id must be bounded text or null")


@dataclass(frozen=True, slots=True)
class ReconcileAutomationsResultV1:
    code: str
    automation_id: str | None = None
    occurrence_id: str | None = None
    status: OccurrenceControlStatus | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        allowed = {
            "not_due",
            "needs_019_config",
            "purge_progress",
            "purge_cleanup_unknown",
            "purged",
            *(item.value for item in OccurrenceControlStatus),
        }
        if self.code not in allowed:
            raise ValueError("reconcile result code is not closed")
        if self.code == "not_due":
            if any(
                item is not None
                for item in (
                    self.automation_id,
                    self.occurrence_id,
                    self.status,
                    self.reason,
                )
            ):
                raise ValueError("not_due result must not carry occurrence identity")
        elif self.code in {
            "needs_019_config",
            "purge_progress",
            "purge_cleanup_unknown",
            "purged",
        }:
            if (
                self.occurrence_id is not None
                or self.status is not None
                or not self.automation_id
                or (
                    self.code in {"needs_019_config", "purge_cleanup_unknown"}
                    and not self.reason
                )
                or (
                    self.code in {"purge_progress", "purged"}
                    and self.reason is not None
                )
            ):
                raise ValueError("lifecycle result fields are incomplete")
        elif (
            not self.automation_id
            or not self.occurrence_id
            or self.status is None
            or self.code != self.status.value
            or self.reason is not None
        ):
            raise ValueError("occurrence result fields are incomplete")


@dataclass(frozen=True, slots=True)
class ExecutionAvailabilityV1:
    provider_available: bool = True
    supervisor_available: bool = True
    sandbox_available: bool = True
    browser_available: bool = True

    def __post_init__(self) -> None:
        if not all(
            isinstance(getattr(self, field_name), bool)
            for field_name in self.__dataclass_fields__
        ):
            raise ValueError("execution availability flags must be bools")


class AutomationReconciler:
    def __init__(
        self,
        *,
        controller: AutomationController,
        workspace_repository: OwnedWorkspaceRepository,
        source_bindings: Mapping[str, SourceBindingV1],
        workspace_bounds: WorkspaceBoundsV1,
        executor: OccurrenceExecutor | None,
        supervisor: OccurrenceSupervisor | None,
        clock: Callable[[], datetime],
        next_snapshot_token: Callable[[], str],
        claim_fencing_token: Callable[[], str],
        raw_capability: Callable[[], str],
        checkpoint_identity: Callable[[], str],
        execution_availability: ExecutionAvailabilityV1 | None = None,
    ) -> None:
        self._controller = controller
        self._workspace_repository = workspace_repository
        self._source_bindings = dict(source_bindings)
        self._workspace_bounds = workspace_bounds
        self._executor = executor
        self._supervisor = supervisor
        self._clock = clock
        self._next_snapshot_token = next_snapshot_token
        self._claim_fencing_token = claim_fencing_token
        self._raw_capability = raw_capability
        self._checkpoint_identity = checkpoint_identity
        self._execution_availability = execution_availability or ExecutionAvailabilityV1()

    def reconcile(self, request: ReconcileAutomationsV1) -> ReconcileAutomationsResultV1:
        if not isinstance(request, ReconcileAutomationsV1):
            raise TypeError("request must use ReconcileAutomationsV1")
        now = self._clock()
        snapshot = self._controller.snapshot()
        active = next(
            (record for record in snapshot.records if record.active_claim is not None),
            None,
        )
        if active is not None:
            return self._reconcile_active(active)

        purge_record = next(
            (
                record
                for record in snapshot.records
                if record.status is AutomationStatus.PURGE_PENDING
            ),
            None,
        )
        if purge_record is not None:
            return self._reconcile_purge(purge_record, now)

        candidates: list[tuple[str, str, AutomationRecordV1, object]] = []
        for record in snapshot.records:
            if record.definition is None:
                continue
            decision = resolve_schedule(record.definition, record, now)
            if decision.kind in {
                ScheduleDecisionKind.DUE,
                ScheduleDecisionKind.MISFIRE_SKIPPED,
            }:
                assert decision.scheduled_for_utc is not None
                candidates.append(
                    (
                        decision.scheduled_for_utc,
                        record.automation_id,
                        record,
                        decision,
                    )
                )
        if not candidates:
            return ReconcileAutomationsResultV1(code="not_due")

        _, _, record, untyped_decision = min(candidates, key=lambda item: item[:2])
        decision = untyped_decision
        assert record.definition is not None
        unavailable = self._configuration_reason(record)
        if unavailable is not None:
            return self._configuration_result(record, unavailable)
        assert decision.occurrence_index is not None
        assert decision.scheduled_for_utc is not None
        authority = self._authority(
            record,
            decision.occurrence_index,
            decision.scheduled_for_utc,
            execution_capability=decision.kind is ScheduleDecisionKind.DUE,
        )
        self._claim(authority)

        if decision.kind is ScheduleDecisionKind.MISFIRE_SKIPPED:
            result = OccurrenceExecutionResultV1(
                status=OccurrenceControlStatus.MISFIRE_SKIPPED,
                checkpoint_identity_digest=authority.checkpoint_identity,
                result_digest=None,
                replayed=False,
                error_code="misfire_skipped",
                artifacts=(),
            )
            return self._record(authority, result)

        source, workspace = self._prepare_workspace(record, authority)
        assert self._executor is not None
        prepared = self._executor.initialize(authority, source, workspace)
        self._workspace_repository.admit_runtime_checkpoint(
            automation_id=authority.automation_id,
            occurrence_id=authority.occurrence_id,
            identity_digest=prepared.checkpoint_identity_digest,
        )
        return self._supervise(authority, source, workspace, prepared)

    def _supervise(
        self,
        authority: BackgroundOccurrenceAuthorityV1,
        source: OwnedObjectV1,
        workspace: OwnedObjectV1,
        prepared: PreparedOccurrenceV1,
    ) -> ReconcileAutomationsResultV1:
        expected_permit: list[str] = []

        def on_ready(process_identity_digest: str) -> str:
            self._mark_dispatched(authority, process_identity_digest)
            permit = canonical_json_digest(
                {
                    "authority_digest": authority.authority_digest,
                    "process_identity_digest": process_identity_digest,
                    "phase": "start_permit",
                }
            )
            expected_permit.append(permit)
            return permit

        def on_started(process_identity_digest: str, permit: str) -> None:
            if expected_permit != [permit]:
                raise ValueError("start permit identity mismatch")
            self._mark_running(authority, process_identity_digest)

        assert self._supervisor is not None and self._executor is not None
        supervised = self._supervisor.run(
            SupervisedOccurrenceSpecV1.from_prepared(prepared),
            OccurrenceStartCallbacks(
                on_ready=on_ready,
                on_started=on_started,
                execute=lambda: self._executor.run_once(prepared),
            ),
        )
        result = supervised.result
        if result.status in _SAFE_TERMINAL:
            result = self._capture_and_cleanup(result, source, workspace)
        return self._record(authority, result)

    def _reconcile_active(
        self,
        record: AutomationRecordV1,
    ) -> ReconcileAutomationsResultV1:
        authority = record.active_claim
        phase = record.active_claim_phase
        assert authority is not None and phase is not None
        if (
            record.status is AutomationStatus.CANCEL_PENDING
            and phase is OccurrenceControlStatus.CLAIMED
        ):
            canceled = OccurrenceExecutionResultV1(
                status=OccurrenceControlStatus.CANCELED,
                checkpoint_identity_digest=authority.checkpoint_identity,
                result_digest=None,
                replayed=False,
                error_code="canceled_before_start",
                artifacts=(),
            )
            source = self._source_snapshot(record)
            try:
                workspace = self._workspace_repository.load_occurrence_workspace(
                    source,
                    authority.occurrence_id,
                )
            except ValueError:
                return self._record(authority, canceled)
            return self._record(
                authority,
                self._capture_and_cleanup(canceled, source, workspace),
            )
        if phase in {
            OccurrenceControlStatus.NEEDS_HUMAN,
            OccurrenceControlStatus.START_OUTCOME_UNKNOWN,
            OccurrenceControlStatus.MODEL_OUTCOME_UNKNOWN,
            OccurrenceControlStatus.EFFECT_OUTCOME_UNKNOWN,
            OccurrenceControlStatus.CLEANUP_UNKNOWN,
        }:
            return self._active_result(record)
        if phase is OccurrenceControlStatus.DISPATCHED:
            return self._record(
                authority,
                self._unknown_result(
                    authority,
                    OccurrenceControlStatus.START_OUTCOME_UNKNOWN,
                    "start_outcome_unknown",
                ),
            )
        if phase is OccurrenceControlStatus.RUNNING:
            unavailable = self._configuration_reason(record)
            if unavailable is not None:
                return self._configuration_result(record, unavailable)
            assert self._executor is not None
            recovered = self._executor.recover(authority)
            if recovered is None or recovered.result is None:
                return self._record(
                    authority,
                    self._unknown_result(
                        authority,
                        OccurrenceControlStatus.EFFECT_OUTCOME_UNKNOWN,
                        "effect_outcome_unknown",
                    ),
                )
            source = self._source_snapshot(record)
            try:
                workspace = self._workspace_repository.load_occurrence_workspace(
                    source,
                    authority.occurrence_id,
                )
            except ValueError:
                return self._record(
                    authority,
                    self._unknown_result(
                        authority,
                        OccurrenceControlStatus.CLEANUP_UNKNOWN,
                        "workspace_recovery_unknown",
                    ),
                )
            if (
                recovered.prepared.source_identity_digest != source.identity_digest
                or recovered.prepared.workspace_identity_digest != workspace.identity_digest
            ):
                return self._record(
                    authority,
                    self._unknown_result(
                        authority,
                        OccurrenceControlStatus.CLEANUP_UNKNOWN,
                        "workspace_identity_drift",
                    ),
                )
            result = recovered.result
            if result.status in _SAFE_TERMINAL:
                result = self._capture_and_cleanup(result, source, workspace)
            return self._record(authority, result)
        if phase is OccurrenceControlStatus.CLAIMED:
            unavailable = self._configuration_reason(record)
            if unavailable is not None:
                return self._configuration_result(record, unavailable)
            source, workspace = self._prepare_workspace(record, authority)
            assert self._executor is not None
            prepared = self._executor.initialize(authority, source, workspace)
            self._workspace_repository.admit_runtime_checkpoint(
                automation_id=authority.automation_id,
                occurrence_id=authority.occurrence_id,
                identity_digest=prepared.checkpoint_identity_digest,
            )
            return self._supervise(authority, source, workspace, prepared)
        return self._active_result(record)

    def _reconcile_purge(
        self,
        record: AutomationRecordV1,
        now: datetime,
    ) -> ReconcileAutomationsResultV1:
        manifest = record.purge_manifest
        assert manifest is not None
        if record.purge_cleanup_unknown_object_id is not None:
            return ReconcileAutomationsResultV1(
                code="purge_cleanup_unknown",
                automation_id=record.automation_id,
                reason="owned_object_cleanup_unknown",
            )
        if record.purge_active_object_id is not None:
            expected = next(
                item
                for item in manifest.objects
                if item.object_id == record.purge_active_object_id
            )
            outcome = self._workspace_repository.delete_purge_object(
                expected,
                allow_missing_after_intent=True,
            )
            snapshot = self._controller.snapshot()
            self._controller.handle(
                RecordPurgeProgress(
                    expected_snapshot_token=snapshot.snapshot_token,
                    next_snapshot_token=self._next_snapshot_token(),
                    automation_id=record.automation_id,
                    object_id=expected.object_id,
                    outcome=outcome,
                )
            )
            return ReconcileAutomationsResultV1(
                code=(
                    "purge_cleanup_unknown"
                    if outcome is PurgeCleanupOutcome.CLEANUP_UNKNOWN
                    else "purge_progress"
                ),
                automation_id=record.automation_id,
                reason=(
                    "owned_object_cleanup_unknown"
                    if outcome is PurgeCleanupOutcome.CLEANUP_UNKNOWN
                    else None
                ),
            )
        pending = next(
            (
                item
                for item in manifest.objects
                if item.object_id not in record.purge_confirmed_object_ids
            ),
            None,
        )
        snapshot = self._controller.snapshot()
        if pending is not None:
            self._controller.handle(
                StartPurgeObject(
                    expected_snapshot_token=snapshot.snapshot_token,
                    next_snapshot_token=self._next_snapshot_token(),
                    automation_id=record.automation_id,
                    object_id=pending.object_id,
                )
            )
            return ReconcileAutomationsResultV1(
                code="purge_progress",
                automation_id=record.automation_id,
            )
        self._controller.handle(
            FinishPurge(
                expected_snapshot_token=snapshot.snapshot_token,
                next_snapshot_token=self._next_snapshot_token(),
                automation_id=record.automation_id,
                purged_at_utc=format_canonical_utc(now),
            )
        )
        return ReconcileAutomationsResultV1(
            code="purged",
            automation_id=record.automation_id,
        )

    def _authority(
        self,
        record: AutomationRecordV1,
        occurrence_index: int,
        scheduled_for_utc: str,
        *,
        execution_capability: bool,
    ) -> BackgroundOccurrenceAuthorityV1:
        definition = record.definition
        assert definition is not None
        scheduled = parse_canonical_utc(scheduled_for_utc, "scheduled_for_utc")
        occurrence_id = occurrence_identity(
            definition,
            occurrence_index,
            scheduled_for_utc,
        )
        inert_identity = canonical_json_digest(
            {
                "occurrence_id": occurrence_id,
                "kind": "nonexecuting_schedule_outcome",
            }
        )
        return BackgroundOccurrenceAuthorityV1(
            automation_id=record.automation_id,
            automation_revision=definition.body.revision,
            occurrence_id=occurrence_id,
            occurrence_index=occurrence_index,
            scheduled_for_utc=scheduled_for_utc,
            definition_digest=definition.definition_digest,
            grant_digest=definition.grant.grant_digest,
            claim_fencing_token=self._claim_fencing_token(),
            checkpoint_identity=(
                self._checkpoint_identity() if execution_capability else inert_identity
            ),
            deadline_utc=format_canonical_utc(
                scheduled
                + timedelta(seconds=definition.body.budgets.occurrence_deadline_seconds)
            ),
            raw_capability=(
                self._raw_capability() if execution_capability else inert_identity
            ),
        )

    def _claim(self, authority: BackgroundOccurrenceAuthorityV1) -> None:
        snapshot = self._controller.snapshot()
        self._controller.handle(
            ClaimOccurrence(
                expected_snapshot_token=snapshot.snapshot_token,
                next_snapshot_token=self._next_snapshot_token(),
                authority=authority,
            )
        )

    def _mark_dispatched(
        self,
        authority: BackgroundOccurrenceAuthorityV1,
        process_identity_digest: str,
    ) -> None:
        snapshot = self._controller.snapshot()
        self._controller.handle(
            MarkDispatched(
                expected_snapshot_token=snapshot.snapshot_token,
                next_snapshot_token=self._next_snapshot_token(),
                automation_id=authority.automation_id,
                authority_digest=authority.authority_digest,
                process_identity_digest=process_identity_digest,
            )
        )

    def _mark_running(
        self,
        authority: BackgroundOccurrenceAuthorityV1,
        process_identity_digest: str,
    ) -> None:
        snapshot = self._controller.snapshot()
        self._controller.handle(
            MarkRunning(
                expected_snapshot_token=snapshot.snapshot_token,
                next_snapshot_token=self._next_snapshot_token(),
                automation_id=authority.automation_id,
                authority_digest=authority.authority_digest,
                process_identity_digest=process_identity_digest,
            )
        )

    def _prepare_workspace(
        self,
        record: AutomationRecordV1,
        authority: BackgroundOccurrenceAuthorityV1,
    ) -> tuple[OwnedObjectV1, OwnedObjectV1]:
        source = self._source_snapshot(record)
        workspace = self._workspace_repository.materialize_occurrence(
            source,
            authority.occurrence_id,
        )
        return source, workspace

    def _source_snapshot(self, record: AutomationRecordV1) -> OwnedObjectV1:
        definition = record.active_claim_definition or record.definition
        assert definition is not None
        if definition.body.source_workspace_binding_digest not in self._source_bindings:
            raise ValueError("source binding unavailable")
        return self._workspace_repository.load_source_snapshot(
            definition.body.source_snapshot_digest,
            owner_automation_id=record.automation_id,
        )

    def _configuration_reason(self, record: AutomationRecordV1) -> str | None:
        availability = self._execution_availability
        if self._executor is None or not availability.provider_available:
            return "provider_unavailable"
        if self._supervisor is None or not availability.supervisor_available:
            return "supervisor_unavailable"
        definition = record.active_claim_definition or record.definition
        assert definition is not None
        if definition.body.budgets.sandbox_commands and not availability.sandbox_available:
            return "sandbox_unavailable"
        if definition.body.budgets.browser_actions and not availability.browser_available:
            return "browser_unavailable"
        return None

    @staticmethod
    def _configuration_result(
        record: AutomationRecordV1,
        reason: str,
    ) -> ReconcileAutomationsResultV1:
        return ReconcileAutomationsResultV1(
            code="needs_019_config",
            automation_id=record.automation_id,
            reason=reason,
        )

    @staticmethod
    def _unknown_result(
        authority: BackgroundOccurrenceAuthorityV1,
        status: OccurrenceControlStatus,
        error_code: str,
    ) -> OccurrenceExecutionResultV1:
        return OccurrenceExecutionResultV1(
            status=status,
            checkpoint_identity_digest=authority.checkpoint_identity,
            result_digest=None,
            replayed=False,
            error_code=error_code,
            artifacts=(),
        )

    def _capture_and_cleanup(
        self,
        result: OccurrenceExecutionResultV1,
        source: OwnedObjectV1,
        workspace: OwnedObjectV1,
    ) -> OccurrenceExecutionResultV1:
        try:
            capture = self._workspace_repository.capture_terminal_outputs(
                workspace,
                source,
                self._workspace_bounds,
                artifacts=result.artifacts,
            )
        except Exception:
            return OccurrenceExecutionResultV1(
                status=OccurrenceControlStatus.CLEANUP_UNKNOWN,
                checkpoint_identity_digest=result.checkpoint_identity_digest,
                result_digest=None,
                replayed=result.replayed,
                error_code="terminal_capture_unknown",
                artifacts=(),
            )
        cleanup = self._workspace_repository.delete_owned_object(workspace)
        if cleanup.outcome is not CleanupOutcome.CLEANED:
            return OccurrenceExecutionResultV1(
                status=OccurrenceControlStatus.CLEANUP_UNKNOWN,
                checkpoint_identity_digest=result.checkpoint_identity_digest,
                result_digest=None,
                replayed=result.replayed,
                error_code="workspace_cleanup_unknown",
                artifacts=(),
            )
        return OccurrenceExecutionResultV1(
            status=result.status,
            checkpoint_identity_digest=result.checkpoint_identity_digest,
            result_digest=canonical_json_digest(
                {
                    "runtime_result_digest": result.result_digest,
                    "diff_digest": capture.diff_digest,
                }
            ),
            replayed=result.replayed,
            error_code=result.error_code,
            artifacts=result.artifacts,
        )

    def _record(
        self,
        authority: BackgroundOccurrenceAuthorityV1,
        result: OccurrenceExecutionResultV1,
    ) -> ReconcileAutomationsResultV1:
        snapshot = self._controller.snapshot()
        self._controller.handle(
            RecordOccurrenceOutcome(
                expected_snapshot_token=snapshot.snapshot_token,
                next_snapshot_token=self._next_snapshot_token(),
                automation_id=authority.automation_id,
                authority_digest=authority.authority_digest,
                summary=OccurrenceSummaryV1(
                    occurrence_id=authority.occurrence_id,
                    status=result.status,
                    scheduled_for_utc=authority.scheduled_for_utc,
                    definition_digest=authority.definition_digest,
                    checkpoint_identity_digest=result.checkpoint_identity_digest,
                    result_digest=result.result_digest,
                    replayed=result.replayed,
                    error_code=result.error_code,
                ),
            )
        )
        return ReconcileAutomationsResultV1(
            code=result.status.value,
            automation_id=authority.automation_id,
            occurrence_id=authority.occurrence_id,
            status=result.status,
        )

    @staticmethod
    def _active_result(record: AutomationRecordV1) -> ReconcileAutomationsResultV1:
        assert record.active_claim is not None
        status = record.active_claim_phase
        assert status is not None
        return ReconcileAutomationsResultV1(
            code=status.value,
            automation_id=record.automation_id,
            occurrence_id=record.active_claim.occurrence_id,
            status=status,
        )
