"""Host adapter that enters one existing Runtime checkpoint per occurrence."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agent.automation.contracts import (
    AutomationDefinitionV1,
    AutomationRecordV1,
    BackgroundOccurrenceAuthorityV1,
    OccurrenceControlStatus,
)
from agent.automation.store import AutomationRepository
from agent.automation.supervisor import (
    OccurrenceExecutionResultV1,
    PreparedOccurrenceV1,
    RecoveredOccurrenceV1,
)
from agent.automation.workspace import OwnedObjectKind, OwnedObjectV1, OwnedWorkspaceRepository
from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.contracts import (
    BackgroundOccurrenceBindingV1,
    ConversationWorkspaceBindingV1,
    LoadedSnapshot,
    canonical_json_digest,
)
from agent.scheduler.caller import (
    ScheduledOccurrenceCaller,
    create_or_load_occurrence_store,
)
from agent.scheduler.contracts import ScheduledOccurrence, ScheduledRunReport

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class RuntimeOccurrenceBindingV1:
    """Trusted host resolution of private definition data for one occurrence."""

    scheduled_occurrence: ScheduledOccurrence
    workspace_binding: ConversationWorkspaceBindingV1
    source_identity_digest: str
    workspace_identity_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.scheduled_occurrence, ScheduledOccurrence):
            raise TypeError("scheduled_occurrence must use ScheduledOccurrence")
        if not isinstance(self.workspace_binding, ConversationWorkspaceBindingV1):
            raise TypeError("workspace_binding must use ConversationWorkspaceBindingV1")
        if not _HEX64.fullmatch(self.source_identity_digest) or not _HEX64.fullmatch(
            self.workspace_identity_digest
        ):
            raise ValueError("runtime occurrence object identities must be bare hex64")
        if (
            self.workspace_binding.workspace_identity_digest
            != self.workspace_identity_digest
            or self.workspace_binding.workspace_scope_digest
            != self.scheduled_occurrence.workspace_scope_digest
        ):
            raise ValueError("runtime occurrence workspace binding mismatch")


class RuntimeOccurrenceResolver(Protocol):
    def from_authority(
        self,
        authority: BackgroundOccurrenceAuthorityV1,
    ) -> RuntimeOccurrenceBindingV1: ...

    def from_prepared(
        self,
        prepared: PreparedOccurrenceV1,
    ) -> RuntimeOccurrenceBindingV1: ...


class RepositoryRuntimeOccurrenceResolver:
    """Rebuild private Runtime inputs from the exact durable active claim."""

    def __init__(
        self,
        *,
        repository: AutomationRepository,
        workspace_repository: OwnedWorkspaceRepository,
    ) -> None:
        if not callable(getattr(repository, "load", None)):
            raise TypeError("repository must provide load")
        if not all(
            callable(getattr(workspace_repository, name, None))
            for name in ("load_source_snapshot", "load_occurrence_workspace")
        ):
            raise TypeError("workspace_repository must provide exact load methods")
        self._repository = repository
        self._workspace_repository = workspace_repository

    def from_authority(
        self,
        authority: BackgroundOccurrenceAuthorityV1,
    ) -> RuntimeOccurrenceBindingV1:
        if not isinstance(authority, BackgroundOccurrenceAuthorityV1):
            raise TypeError("authority must use BackgroundOccurrenceAuthorityV1")
        record = self._active_record(authority.automation_id)
        if record.active_claim != authority:
            raise ValueError("active occurrence authority drift")
        return self._binding(record, authority)

    def from_prepared(
        self,
        prepared: PreparedOccurrenceV1,
    ) -> RuntimeOccurrenceBindingV1:
        if not isinstance(prepared, PreparedOccurrenceV1):
            raise TypeError("prepared must use PreparedOccurrenceV1")
        record = self._active_record(prepared.automation_id)
        authority = record.active_claim
        if authority is None or (
            authority.occurrence_id != prepared.occurrence_id
            or authority.authority_digest != prepared.authority_digest
            or authority.checkpoint_identity != prepared.checkpoint_identity_digest
            or authority.deadline_utc != prepared.deadline_utc
            or authority.raw_capability != prepared.raw_capability
        ):
            raise ValueError("active occurrence prepared binding drift")
        binding = self._binding(record, authority)
        if (
            binding.source_identity_digest != prepared.source_identity_digest
            or binding.workspace_identity_digest != prepared.workspace_identity_digest
        ):
            raise ValueError("active occurrence object identity drift")
        return binding

    def _active_record(self, automation_id: str) -> AutomationRecordV1:
        snapshot = self._repository.load()
        record = next(
            (item for item in snapshot.records if item.automation_id == automation_id),
            None,
        )
        if record is None or record.active_claim is None:
            raise ValueError("active occurrence is unavailable")
        return record

    def _binding(
        self,
        record: AutomationRecordV1,
        authority: BackgroundOccurrenceAuthorityV1,
    ) -> RuntimeOccurrenceBindingV1:
        definition = record.active_claim_definition
        if not isinstance(definition, AutomationDefinitionV1):
            raise ValueError("active occurrence definition is unavailable")
        body = definition.body
        source = self._workspace_repository.load_source_snapshot(
            body.source_snapshot_digest,
            owner_automation_id=authority.automation_id,
        )
        workspace = self._workspace_repository.load_occurrence_workspace(
            source,
            authority.occurrence_id,
        )
        if (
            source.kind is not OwnedObjectKind.SOURCE_SNAPSHOT
            or workspace.kind is not OwnedObjectKind.OCCURRENCE_WORKSPACE
            or workspace.source_identity_digest != source.identity_digest
            or source.owner_automation_id != authority.automation_id
            or workspace.owner_automation_id != authority.automation_id
        ):
            raise ValueError("active occurrence owned-object binding drift")
        budgets = body.budgets
        occurrence_binding = BackgroundOccurrenceBindingV1.create(
            automation_id=authority.automation_id,
            automation_revision=authority.automation_revision,
            occurrence_id=authority.occurrence_id,
            occurrence_index=authority.occurrence_index,
            scheduled_for_utc=authority.scheduled_for_utc,
            definition_digest=authority.definition_digest,
            grant_digest=authority.grant_digest,
            claim_authority_digest=authority.authority_digest,
            claim_capability_digest=canonical_json_digest(authority.raw_capability),
            checkpoint_identity_digest=authority.checkpoint_identity,
            deadline_utc=authority.deadline_utc,
            model_call_limit=budgets.model_calls,
            tool_call_limit=budgets.tool_calls,
            sandbox_command_limit=budgets.sandbox_commands,
            browser_action_limit=budgets.browser_actions,
            max_input_tokens=budgets.max_input_tokens,
            max_output_tokens=budgets.max_output_tokens,
        )
        workspace_binding = ConversationWorkspaceBindingV1.create(
            workspace_scope_digest=canonical_json_digest(
                {
                    "automation_id": authority.automation_id,
                    "definition_digest": authority.definition_digest,
                    "source_identity_digest": source.identity_digest,
                }
            ),
            workspace_identity_digest=workspace.identity_digest,
            bound_at=authority.scheduled_for_utc,
        )
        return RuntimeOccurrenceBindingV1(
            scheduled_occurrence=ScheduledOccurrence(
                schedule_id=authority.automation_id,
                occurrence_id=authority.occurrence_id,
                scheduled_for_utc=authority.scheduled_for_utc,
                message=body.task_text,
                workspace_scope_digest=workspace_binding.workspace_scope_digest,
                background_binding=occurrence_binding,
            ),
            workspace_binding=workspace_binding,
            source_identity_digest=source.identity_digest,
            workspace_identity_digest=workspace.identity_digest,
        )

RuntimeFactory = Callable[[LocalCheckpointStore, RuntimeOccurrenceBindingV1], object]


class RuntimeOccurrenceExecutor:
    """Create/load a checkpoint, then delegate exactly once to the scheduler caller."""

    def __init__(
        self,
        *,
        state_root: Path,
        resolver: RuntimeOccurrenceResolver,
        runtime_factory: RuntimeFactory,
    ) -> None:
        if not isinstance(state_root, Path) or not state_root.is_absolute():
            raise ValueError("state_root must be an absolute pre-bound Path")
        info = os.lstat(state_root)
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise ValueError("state_root must be a real directory")
        if not callable(runtime_factory):
            raise TypeError("runtime_factory must be callable")
        if not all(
            callable(getattr(resolver, method, None))
            for method in ("from_authority", "from_prepared")
        ):
            raise TypeError("resolver must provide both exact resolution methods")
        self._state_root = state_root
        self._resolver = resolver
        self._runtime_factory = runtime_factory

    def initialize(
        self,
        authority: BackgroundOccurrenceAuthorityV1,
        source: OwnedObjectV1,
        workspace: OwnedObjectV1,
    ) -> PreparedOccurrenceV1:
        if not isinstance(authority, BackgroundOccurrenceAuthorityV1):
            raise TypeError("authority must use BackgroundOccurrenceAuthorityV1")
        self._validate_owned_objects(authority, source, workspace)
        binding = self._resolver.from_authority(authority)
        self._validate_authority_binding(authority, binding)
        if (
            binding.source_identity_digest != source.identity_digest
            or binding.workspace_identity_digest != workspace.identity_digest
        ):
            raise ValueError("resolved occurrence object identity mismatch")
        prepared = PreparedOccurrenceV1.create(
            automation_id=authority.automation_id,
            occurrence_id=authority.occurrence_id,
            authority_digest=authority.authority_digest,
            checkpoint_identity_digest=authority.checkpoint_identity,
            source_identity_digest=source.identity_digest,
            workspace_identity_digest=workspace.identity_digest,
            deadline_utc=authority.deadline_utc,
            raw_capability=authority.raw_capability,
        )
        self._create_or_load(binding)
        return prepared

    def run_once(self, prepared: PreparedOccurrenceV1) -> OccurrenceExecutionResultV1:
        if not isinstance(prepared, PreparedOccurrenceV1):
            raise TypeError("prepared must use PreparedOccurrenceV1")
        binding = self._resolver.from_prepared(prepared)
        self._validate_prepared_binding(prepared, binding)
        return self._run(binding, prepared)

    def recover(
        self,
        authority: BackgroundOccurrenceAuthorityV1,
    ) -> RecoveredOccurrenceV1 | None:
        if not isinstance(authority, BackgroundOccurrenceAuthorityV1):
            raise TypeError("authority must use BackgroundOccurrenceAuthorityV1")
        binding = self._resolver.from_authority(authority)
        self._validate_authority_binding(authority, binding)
        prepared = PreparedOccurrenceV1.create(
            automation_id=authority.automation_id,
            occurrence_id=authority.occurrence_id,
            authority_digest=authority.authority_digest,
            checkpoint_identity_digest=authority.checkpoint_identity,
            source_identity_digest=binding.source_identity_digest,
            workspace_identity_digest=binding.workspace_identity_digest,
            deadline_utc=authority.deadline_utc,
            raw_capability=authority.raw_capability,
        )
        path = self._state_root / binding.scheduled_occurrence.checkpoint_relative_path
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise ValueError("runtime checkpoint must be a real regular file")
        _, snapshot = self._create_or_load(binding)
        if snapshot.state.revision == 0:
            return RecoveredOccurrenceV1(prepared=prepared, result=None)
        result = self._run(binding, prepared)
        return RecoveredOccurrenceV1(prepared=prepared, result=result)

    def _run(
        self,
        binding: RuntimeOccurrenceBindingV1,
        prepared: PreparedOccurrenceV1,
    ) -> OccurrenceExecutionResultV1:
        store, snapshot = self._create_or_load(binding)
        resources = self._runtime_factory(store, binding)
        runtime = getattr(resources, "runtime", None)
        close = getattr(resources, "close", None)
        if not callable(getattr(runtime, "run_turn", None)) or not callable(close):
            raise TypeError("runtime_factory must return Runtime resources")
        try:
            report = ScheduledOccurrenceCaller(
                runtime,
                store,
                snapshot,
                binding.scheduled_occurrence,
        ).run_once()
        except Exception:
            with suppress(Exception):
                close()
            raise
        try:
            close()
        except Exception:
            return OccurrenceExecutionResultV1(
                status=OccurrenceControlStatus.CLEANUP_UNKNOWN,
                checkpoint_identity_digest=prepared.checkpoint_identity_digest,
                result_digest=None,
                replayed=False,
                error_code="runtime_resource_cleanup_unknown",
                artifacts=(),
            )
        return _execution_result(report, prepared.checkpoint_identity_digest)

    def _create_or_load(
        self,
        binding: RuntimeOccurrenceBindingV1,
    ) -> tuple[LocalCheckpointStore, LoadedSnapshot]:
        return create_or_load_occurrence_store(
            binding.scheduled_occurrence,
            state_root=self._state_root,
            workspace_binding=binding.workspace_binding,
        )

    @staticmethod
    def _validate_owned_objects(
        authority: BackgroundOccurrenceAuthorityV1,
        source: OwnedObjectV1,
        workspace: OwnedObjectV1,
    ) -> None:
        if not isinstance(source, OwnedObjectV1) or source.kind is not (
            OwnedObjectKind.SOURCE_SNAPSHOT
        ):
            raise ValueError("executor source must be an owned snapshot")
        if not isinstance(workspace, OwnedObjectV1) or workspace.kind is not (
            OwnedObjectKind.OCCURRENCE_WORKSPACE
        ):
            raise ValueError("executor workspace must be an occurrence workspace")
        if (
            workspace.source_identity_digest != source.identity_digest
            or source.owner_automation_id != authority.automation_id
            or workspace.owner_automation_id != authority.automation_id
        ):
            raise ValueError("executor owned-object binding mismatch")

    @staticmethod
    def _validate_authority_binding(
        authority: BackgroundOccurrenceAuthorityV1,
        binding: RuntimeOccurrenceBindingV1,
    ) -> None:
        occurrence = binding.scheduled_occurrence
        runtime = occurrence.background_binding
        if runtime is None:
            raise ValueError("background occurrence requires a Runtime binding")
        expected = {
            "automation_id": authority.automation_id,
            "automation_revision": authority.automation_revision,
            "occurrence_id": authority.occurrence_id,
            "occurrence_index": authority.occurrence_index,
            "scheduled_for_utc": authority.scheduled_for_utc,
            "definition_digest": authority.definition_digest,
            "grant_digest": authority.grant_digest,
            "claim_authority_digest": authority.authority_digest,
            "claim_capability_digest": canonical_json_digest(authority.raw_capability),
            "checkpoint_identity_digest": authority.checkpoint_identity,
            "deadline_utc": authority.deadline_utc,
        }
        if occurrence.schedule_id != authority.automation_id or any(
            getattr(runtime, field) != value for field, value in expected.items()
        ):
            raise ValueError("resolved Runtime occurrence authority mismatch")

    @staticmethod
    def _validate_prepared_binding(
        prepared: PreparedOccurrenceV1,
        binding: RuntimeOccurrenceBindingV1,
    ) -> None:
        occurrence = binding.scheduled_occurrence
        runtime = occurrence.background_binding
        if runtime is None or (
            occurrence.schedule_id != prepared.automation_id
            or occurrence.occurrence_id != prepared.occurrence_id
            or runtime.claim_authority_digest != prepared.authority_digest
            or runtime.claim_capability_digest
            != canonical_json_digest(prepared.raw_capability)
            or runtime.checkpoint_identity_digest
            != prepared.checkpoint_identity_digest
            or runtime.deadline_utc != prepared.deadline_utc
            or binding.source_identity_digest != prepared.source_identity_digest
            or binding.workspace_identity_digest != prepared.workspace_identity_digest
        ):
            raise ValueError("prepared Runtime occurrence binding mismatch")


def _execution_result(
    report: ScheduledRunReport,
    checkpoint_identity_digest: str,
) -> OccurrenceExecutionResultV1:
    if report.occurrence_status == "completed":
        status = OccurrenceControlStatus.COMPLETED
        error_code = None
        result_digest = canonical_json_digest(
            {
                "kind": "runtime_occurrence_result_v1",
                "checkpoint_identity_digest": checkpoint_identity_digest,
                "conversation_id": report.conversation_id,
                "run_id": report.run_id,
                "run_status": report.run_status.value,
            }
        )
    elif report.error_code == "model_outcome_unknown":
        status = OccurrenceControlStatus.MODEL_OUTCOME_UNKNOWN
        error_code = report.error_code
        result_digest = None
    elif report.error_code == "conversation_busy":
        status = OccurrenceControlStatus.CLEANUP_UNKNOWN
        error_code = report.error_code
        result_digest = None
    elif report.occurrence_status == "needs_human":
        status = OccurrenceControlStatus.NEEDS_HUMAN
        error_code = report.error_code or "runtime_needs_human"
        result_digest = None
    else:
        status = OccurrenceControlStatus.FAILED
        error_code = report.error_code or "runtime_failed"
        result_digest = None
    return OccurrenceExecutionResultV1(
        status=status,
        checkpoint_identity_digest=checkpoint_identity_digest,
        result_digest=result_digest,
        replayed=report.replayed,
        error_code=error_code,
        artifacts=(),
    )
