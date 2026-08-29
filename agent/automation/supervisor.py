"""019 portable READY/start/result protocol and deterministic adapters.

The supervisor owns no AutomationStore, Runtime, provider or tool.  It only
coordinates the bounded child-start barrier through callbacks supplied by the
one-shot reconciler.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Protocol

from agent.automation.contracts import (
    BackgroundOccurrenceAuthorityV1,
    OccurrenceControlStatus,
    parse_canonical_utc,
)
from agent.automation.workspace import (
    OwnedObjectKind,
    OwnedObjectV1,
    TerminalArtifactCandidateV1,
)
from agent.runtime.contracts import canonical_json_digest

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_RESULT_STATUSES = {
    OccurrenceControlStatus.COMPLETED,
    OccurrenceControlStatus.FAILED,
    OccurrenceControlStatus.NEEDS_HUMAN,
    OccurrenceControlStatus.WORKER_DEADLINE,
    OccurrenceControlStatus.MISFIRE_SKIPPED,
    OccurrenceControlStatus.SUPERSEDED,
    OccurrenceControlStatus.START_OUTCOME_UNKNOWN,
    OccurrenceControlStatus.MODEL_OUTCOME_UNKNOWN,
    OccurrenceControlStatus.EFFECT_OUTCOME_UNKNOWN,
    OccurrenceControlStatus.CLEANUP_UNKNOWN,
    OccurrenceControlStatus.CANCELED,
}
_UNKNOWN_STATUSES = {
    OccurrenceControlStatus.NEEDS_HUMAN,
    OccurrenceControlStatus.START_OUTCOME_UNKNOWN,
    OccurrenceControlStatus.MODEL_OUTCOME_UNKNOWN,
    OccurrenceControlStatus.EFFECT_OUTCOME_UNKNOWN,
    OccurrenceControlStatus.CLEANUP_UNKNOWN,
}


def _require_hex64(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ValueError(f"{field_name} must be bare hex64")
    return value


@dataclass(frozen=True, slots=True)
class PreparedOccurrenceV1:
    automation_id: str
    occurrence_id: str
    authority_digest: str
    checkpoint_identity_digest: str
    source_identity_digest: str
    workspace_identity_digest: str
    deadline_utc: str
    raw_capability: str = field(repr=False)
    binding_digest: str = ""

    @classmethod
    def create(
        cls,
        *,
        automation_id: str,
        occurrence_id: str,
        authority_digest: str,
        checkpoint_identity_digest: str,
        source_identity_digest: str,
        workspace_identity_digest: str,
        deadline_utc: str,
        raw_capability: str,
    ) -> PreparedOccurrenceV1:
        return cls(
            automation_id=automation_id,
            occurrence_id=occurrence_id,
            authority_digest=authority_digest,
            checkpoint_identity_digest=checkpoint_identity_digest,
            source_identity_digest=source_identity_digest,
            workspace_identity_digest=workspace_identity_digest,
            deadline_utc=deadline_utc,
            raw_capability=raw_capability,
        )

    def __post_init__(self) -> None:
        for field_name in ("automation_id", "occurrence_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not _OPAQUE_ID.fullmatch(value):
                raise ValueError(f"{field_name} must be an opaque id")
        for field_name in (
            "authority_digest",
            "checkpoint_identity_digest",
            "source_identity_digest",
            "workspace_identity_digest",
        ):
            _require_hex64(getattr(self, field_name), field_name)
        parse_canonical_utc(self.deadline_utc, "deadline_utc")
        if not isinstance(self.raw_capability, str) or len(self.raw_capability) < 32:
            raise ValueError("raw_capability must be opaque")
        digest = canonical_json_digest(
            {
                "automation_id": self.automation_id,
                "occurrence_id": self.occurrence_id,
                "authority_digest": self.authority_digest,
                "checkpoint_identity_digest": self.checkpoint_identity_digest,
                "source_identity_digest": self.source_identity_digest,
                "workspace_identity_digest": self.workspace_identity_digest,
                "deadline_utc": self.deadline_utc,
                "capability_digest": canonical_json_digest(self.raw_capability),
            }
        )
        if self.binding_digest and self.binding_digest != digest:
            raise ValueError("prepared occurrence binding digest mismatch")
        object.__setattr__(self, "binding_digest", digest)


@dataclass(frozen=True, slots=True)
class OccurrenceExecutionResultV1:
    status: OccurrenceControlStatus
    checkpoint_identity_digest: str
    result_digest: str | None
    replayed: bool
    error_code: str | None
    artifacts: tuple[TerminalArtifactCandidateV1, ...]

    def __post_init__(self) -> None:
        if self.status not in _RESULT_STATUSES:
            raise ValueError("status is not an executor outcome")
        _require_hex64(self.checkpoint_identity_digest, "checkpoint_identity_digest")
        if self.result_digest is not None:
            _require_hex64(self.result_digest, "result_digest")
        if self.status is OccurrenceControlStatus.COMPLETED and self.result_digest is None:
            raise ValueError("completed result requires result_digest")
        if self.status in _UNKNOWN_STATUSES and not self.error_code:
            raise ValueError("unresolved result requires error_code")
        if self.error_code is not None and (
            not isinstance(self.error_code, str) or not _OPAQUE_ID.fullmatch(self.error_code)
        ):
            raise ValueError("error_code must be an opaque id or null")
        if not isinstance(self.replayed, bool):
            raise ValueError("replayed must be bool")
        if not isinstance(self.artifacts, tuple) or any(
            not isinstance(item, TerminalArtifactCandidateV1) for item in self.artifacts
        ):
            raise ValueError("artifacts must be a tuple of terminal candidates")


@dataclass(frozen=True, slots=True)
class SupervisedOccurrenceSpecV1:
    prepared: PreparedOccurrenceV1

    @classmethod
    def from_prepared(cls, prepared: PreparedOccurrenceV1) -> SupervisedOccurrenceSpecV1:
        if not isinstance(prepared, PreparedOccurrenceV1):
            raise TypeError("prepared must use PreparedOccurrenceV1")
        return cls(prepared=prepared)


@dataclass(frozen=True, slots=True)
class OccurrenceStartCallbacks:
    on_ready: Callable[[str], str]
    on_started: Callable[[str, str], None]
    execute: Callable[[], OccurrenceExecutionResultV1]


@dataclass(frozen=True, slots=True)
class SupervisedOccurrenceResultV1:
    process_identity_digest: str
    start_acknowledged: bool
    cleanup_confirmed: bool
    result: OccurrenceExecutionResultV1

    def __post_init__(self) -> None:
        _require_hex64(self.process_identity_digest, "process_identity_digest")
        if not isinstance(self.start_acknowledged, bool) or not isinstance(
            self.cleanup_confirmed, bool
        ):
            raise ValueError("supervisor booleans are malformed")


@dataclass(frozen=True, slots=True)
class RecoveredOccurrenceV1:
    prepared: PreparedOccurrenceV1
    result: OccurrenceExecutionResultV1 | None

    def __post_init__(self) -> None:
        if not isinstance(self.prepared, PreparedOccurrenceV1):
            raise ValueError("recovered occurrence requires a prepared binding")
        if self.result is not None and (
            self.result.checkpoint_identity_digest
            != self.prepared.checkpoint_identity_digest
        ):
            raise ValueError("recovered result checkpoint identity mismatch")


class OccurrenceSupervisor(Protocol):
    def run(
        self,
        spec: SupervisedOccurrenceSpecV1,
        callbacks: OccurrenceStartCallbacks,
    ) -> SupervisedOccurrenceResultV1: ...


class OccurrenceExecutor(Protocol):
    def initialize(
        self,
        authority: BackgroundOccurrenceAuthorityV1,
        source: OwnedObjectV1,
        workspace: OwnedObjectV1,
    ) -> PreparedOccurrenceV1: ...

    def run_once(self, prepared: PreparedOccurrenceV1) -> OccurrenceExecutionResultV1: ...

    def recover(
        self,
        authority: BackgroundOccurrenceAuthorityV1,
    ) -> RecoveredOccurrenceV1 | None: ...


class OccurrenceSupervisorFault(StrEnum):
    NONE = "none"
    CRASH_BEFORE_READY = "crash_before_ready"
    CRASH_AFTER_READY = "crash_after_ready"
    CRASH_AFTER_STARTED = "crash_after_started"
    CRASH_AFTER_EXECUTE = "crash_after_execute"
    START_PERMIT_UNKNOWN = "start_permit_unknown"
    CLEANUP_UNKNOWN = "cleanup_unknown"


class OccurrenceExecutorFault(StrEnum):
    NONE = "none"
    CRASH_BEFORE_INITIALIZE = "crash_before_initialize"
    CRASH_AFTER_INITIALIZE = "crash_after_initialize"


class SupervisorInjectedCrashError(RuntimeError):
    """A deterministic crash point used by protocol tests."""


class ExecutorInjectedCrashError(RuntimeError):
    """A deterministic checkpoint-initialization crash used by protocol tests."""


class DeterministicOccurrenceExecutor:
    def __init__(
        self,
        *,
        result: OccurrenceExecutionResultV1,
        fault: OccurrenceExecutorFault = OccurrenceExecutorFault.NONE,
    ) -> None:
        self._result = result
        self._prepared: dict[str, PreparedOccurrenceV1] = {}
        self._results: dict[str, OccurrenceExecutionResultV1] = {}
        self.initialize_calls = 0
        self.checkpoint_creations = 0
        self.run_calls = 0
        self.recover_calls = 0
        self.fault = fault

    @property
    def configured_result(self) -> OccurrenceExecutionResultV1:
        return self._result

    def initialize(
        self,
        authority: BackgroundOccurrenceAuthorityV1,
        source: OwnedObjectV1,
        workspace: OwnedObjectV1,
    ) -> PreparedOccurrenceV1:
        self.initialize_calls += 1
        if self.fault is OccurrenceExecutorFault.CRASH_BEFORE_INITIALIZE:
            raise ExecutorInjectedCrashError(self.fault.value)
        if source.kind is not OwnedObjectKind.SOURCE_SNAPSHOT:
            raise ValueError("executor source must be an owned snapshot")
        if workspace.kind is not OwnedObjectKind.OCCURRENCE_WORKSPACE:
            raise ValueError("executor workspace must be an occurrence workspace")
        if workspace.source_identity_digest != source.identity_digest:
            raise ValueError("executor workspace source binding mismatch")
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
        existing = self._prepared.get(authority.authority_digest)
        if existing is not None:
            if existing != prepared:
                raise ValueError("prepared occurrence identity drift")
            return existing
        self._prepared[authority.authority_digest] = prepared
        self.checkpoint_creations += 1
        if self.fault is OccurrenceExecutorFault.CRASH_AFTER_INITIALIZE:
            raise ExecutorInjectedCrashError(self.fault.value)
        return prepared

    def run_once(self, prepared: PreparedOccurrenceV1) -> OccurrenceExecutionResultV1:
        if not isinstance(prepared, PreparedOccurrenceV1):
            raise TypeError("prepared must use PreparedOccurrenceV1")
        self.run_calls += 1
        if self._result.checkpoint_identity_digest != prepared.checkpoint_identity_digest:
            raise ValueError("executor result checkpoint identity mismatch")
        self._prepared.setdefault(prepared.authority_digest, prepared)
        self._results[prepared.authority_digest] = self._result
        return self._result

    def recover(
        self,
        authority: BackgroundOccurrenceAuthorityV1,
    ) -> RecoveredOccurrenceV1 | None:
        self.recover_calls += 1
        prepared = self._prepared.get(authority.authority_digest)
        if prepared is None:
            return None
        if (
            prepared.automation_id != authority.automation_id
            or prepared.occurrence_id != authority.occurrence_id
            or prepared.checkpoint_identity_digest != authority.checkpoint_identity
            or prepared.raw_capability != authority.raw_capability
        ):
            raise ValueError("recovered occurrence authority mismatch")
        result = self._results.get(authority.authority_digest)
        return RecoveredOccurrenceV1(
            prepared=prepared,
            result=None if result is None else replace(result, replayed=True),
        )


class DeterministicOccurrenceSupervisor:
    def __init__(
        self,
        *,
        process_identity_digest: str,
        fault: OccurrenceSupervisorFault = OccurrenceSupervisorFault.NONE,
    ) -> None:
        self.process_identity_digest = _require_hex64(
            process_identity_digest,
            "process_identity_digest",
        )
        self.fault = fault
        self.run_calls = 0

    def run(
        self,
        spec: SupervisedOccurrenceSpecV1,
        callbacks: OccurrenceStartCallbacks,
    ) -> SupervisedOccurrenceResultV1:
        if not isinstance(spec, SupervisedOccurrenceSpecV1):
            raise TypeError("spec must use SupervisedOccurrenceSpecV1")
        self.run_calls += 1
        if self.fault is OccurrenceSupervisorFault.CRASH_BEFORE_READY:
            raise SupervisorInjectedCrashError("crash_before_ready")
        if self.fault is OccurrenceSupervisorFault.NONE:
            from agent.automation.child import run_occurrence_child

            child = run_occurrence_child(
                spec,
                _CallbackStartChannel(callbacks),
                _CallbackChildExecutor(spec.prepared, callbacks),
                process_identity_digest=self.process_identity_digest,
            )
            return SupervisedOccurrenceResultV1(
                process_identity_digest=self.process_identity_digest,
                start_acknowledged=True,
                cleanup_confirmed=True,
                result=child.result,
            )
        permit = callbacks.on_ready(self.process_identity_digest)
        if self.fault is OccurrenceSupervisorFault.CRASH_AFTER_READY:
            raise SupervisorInjectedCrashError("crash_after_ready")
        if self.fault is OccurrenceSupervisorFault.START_PERMIT_UNKNOWN:
            return self._unknown(
                spec,
                OccurrenceControlStatus.START_OUTCOME_UNKNOWN,
                "start_permit_unknown",
                start_acknowledged=False,
                cleanup_confirmed=False,
            )
        callbacks.on_started(self.process_identity_digest, permit)
        if self.fault is OccurrenceSupervisorFault.CRASH_AFTER_STARTED:
            raise SupervisorInjectedCrashError("crash_after_started")
        if self.fault is OccurrenceSupervisorFault.CLEANUP_UNKNOWN:
            return self._unknown(
                spec,
                OccurrenceControlStatus.CLEANUP_UNKNOWN,
                "cleanup_unknown",
                start_acknowledged=True,
                cleanup_confirmed=False,
            )
        result = callbacks.execute()
        if self.fault is OccurrenceSupervisorFault.CRASH_AFTER_EXECUTE:
            raise SupervisorInjectedCrashError("crash_after_execute")
        if result.checkpoint_identity_digest != spec.prepared.checkpoint_identity_digest:
            raise ValueError("supervisor result checkpoint identity mismatch")
        return SupervisedOccurrenceResultV1(
            process_identity_digest=self.process_identity_digest,
            start_acknowledged=True,
            cleanup_confirmed=True,
            result=result,
        )

    def _unknown(
        self,
        spec: SupervisedOccurrenceSpecV1,
        status: OccurrenceControlStatus,
        error_code: str,
        *,
        start_acknowledged: bool,
        cleanup_confirmed: bool,
    ) -> SupervisedOccurrenceResultV1:
        return SupervisedOccurrenceResultV1(
            process_identity_digest=self.process_identity_digest,
            start_acknowledged=start_acknowledged,
            cleanup_confirmed=cleanup_confirmed,
            result=OccurrenceExecutionResultV1(
                status=status,
                checkpoint_identity_digest=spec.prepared.checkpoint_identity_digest,
                result_digest=None,
                replayed=False,
                error_code=error_code,
                artifacts=(),
            ),
        )


class _CallbackStartChannel:
    def __init__(self, callbacks: OccurrenceStartCallbacks) -> None:
        self._callbacks = callbacks

    def announce_ready(self, process_identity_digest: str) -> str:
        return self._callbacks.on_ready(process_identity_digest)

    def acknowledge_start(self, process_identity_digest: str, permit: str) -> None:
        self._callbacks.on_started(process_identity_digest, permit)


class _CallbackChildExecutor:
    def __init__(
        self,
        prepared: PreparedOccurrenceV1,
        callbacks: OccurrenceStartCallbacks,
    ) -> None:
        self._prepared = prepared
        self._callbacks = callbacks

    def run_once(self, prepared: PreparedOccurrenceV1) -> OccurrenceExecutionResultV1:
        if prepared != self._prepared:
            raise ValueError("child prepared binding mismatch")
        result = self._callbacks.execute()
        if result.checkpoint_identity_digest != prepared.checkpoint_identity_digest:
            raise ValueError("child result checkpoint identity mismatch")
        return result
