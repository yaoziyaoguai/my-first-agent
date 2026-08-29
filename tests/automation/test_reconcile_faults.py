from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent.automation.contracts import CancelAutomation, OccurrenceControlStatus
from agent.automation.controller import AutomationController
from agent.automation.reconcile import ReconcileAutomationsV1
from agent.automation.store import (
    AutomationRepositoryUnknownCommitError,
    DeterministicCommitFault,
)
from agent.automation.supervisor import (
    DeterministicOccurrenceExecutor,
    DeterministicOccurrenceSupervisor,
    ExecutorInjectedCrashError,
    OccurrenceExecutionResultV1,
    OccurrenceExecutorFault,
    OccurrenceStartCallbacks,
    OccurrenceSupervisorFault,
    SupervisorInjectedCrashError,
)
from agent.automation.workspace import TerminalArtifactCandidateV1

from .test_reconcile import _active_fixture


class _ArmBarrierCommitFaultSupervisor(DeterministicOccurrenceSupervisor):
    def __init__(self, *, repository, barrier: str, fault: DeterministicCommitFault) -> None:  # noqa: ANN001
        super().__init__(process_identity_digest="e" * 64)
        self._repository = repository
        self.barrier = barrier
        self._commit_fault = fault

    def run(self, spec, callbacks):  # noqa: ANN001, ANN201
        def on_ready(process_identity_digest: str) -> str:
            if self.barrier == "dispatch":
                self._repository.arm_commit_fault(self._commit_fault)
            return callbacks.on_ready(process_identity_digest)

        def on_started(process_identity_digest: str, permit: str) -> None:
            if self.barrier == "running":
                self._repository.arm_commit_fault(self._commit_fault)
            callbacks.on_started(process_identity_digest, permit)

        return super().run(
            spec,
            OccurrenceStartCallbacks(
                on_ready=on_ready,
                on_started=on_started,
                execute=callbacks.execute,
            ),
        )


@pytest.mark.parametrize(
    ("fault", "expected_phase"),
    [
        (
            OccurrenceSupervisorFault.START_PERMIT_UNKNOWN,
            OccurrenceControlStatus.START_OUTCOME_UNKNOWN,
        ),
        (OccurrenceSupervisorFault.CLEANUP_UNKNOWN, OccurrenceControlStatus.CLEANUP_UNKNOWN),
    ],
)
def test_unknown_barrier_outcomes_pause_without_executor_replay(
    fault: OccurrenceSupervisorFault,
    expected_phase: OccurrenceControlStatus,
) -> None:
    reconciler, repository, executor, supervisor = _active_fixture(
        now=datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
    )
    supervisor.fault = fault

    result = reconciler.reconcile(ReconcileAutomationsV1())

    record = repository.load().records[0]
    assert result.code == expected_phase.value
    assert record.active_claim_phase is expected_phase
    assert executor.run_calls == 0


def test_crash_before_ready_leaves_exact_claim_and_zero_execution() -> None:
    reconciler, repository, executor, supervisor = _active_fixture(
        now=datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
    )
    supervisor.fault = OccurrenceSupervisorFault.CRASH_BEFORE_READY

    with pytest.raises(SupervisorInjectedCrashError):
        reconciler.reconcile(ReconcileAutomationsV1())

    record = repository.load().records[0]
    assert record.active_claim_phase is OccurrenceControlStatus.CLAIMED
    assert executor.run_calls == 0

    supervisor.fault = OccurrenceSupervisorFault.NONE
    resumed = reconciler.reconcile(ReconcileAutomationsV1())

    assert resumed.code == "completed"
    assert executor.checkpoint_creations == 1
    assert executor.run_calls == 1


def test_cancel_after_claim_before_ready_terminalizes_without_starting_child() -> None:
    reconciler, repository, executor, supervisor = _active_fixture(
        now=datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
    )
    supervisor.fault = OccurrenceSupervisorFault.CRASH_BEFORE_READY
    with pytest.raises(SupervisorInjectedCrashError):
        reconciler.reconcile(ReconcileAutomationsV1())
    current = repository.load()
    AutomationController(repository).handle(
        CancelAutomation(
            expected_snapshot_token=current.snapshot_token,
            next_snapshot_token="snapshot-token-cancel",
            automation_id=current.records[0].automation_id,
        )
    )
    supervisor.fault = OccurrenceSupervisorFault.NONE

    result = reconciler.reconcile(ReconcileAutomationsV1())

    record = repository.load().records[0]
    assert result.status is OccurrenceControlStatus.CANCELED
    assert record.status.value == "canceled"
    assert record.active_claim is None
    assert executor.run_calls == 0
    assert supervisor.run_calls == 1


@pytest.mark.parametrize(
    ("fault", "durable_phase", "reconciled_phase"),
    [
        (
            OccurrenceSupervisorFault.CRASH_AFTER_READY,
            OccurrenceControlStatus.DISPATCHED,
            OccurrenceControlStatus.START_OUTCOME_UNKNOWN,
        ),
        (
            OccurrenceSupervisorFault.CRASH_AFTER_STARTED,
            OccurrenceControlStatus.RUNNING,
            OccurrenceControlStatus.EFFECT_OUTCOME_UNKNOWN,
        ),
    ],
)
def test_restart_classifies_ambiguous_start_or_effect_without_replay(
    fault: OccurrenceSupervisorFault,
    durable_phase: OccurrenceControlStatus,
    reconciled_phase: OccurrenceControlStatus,
) -> None:
    reconciler, repository, executor, supervisor = _active_fixture(
        now=datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
    )
    supervisor.fault = fault

    with pytest.raises(SupervisorInjectedCrashError):
        reconciler.reconcile(ReconcileAutomationsV1())

    assert repository.load().records[0].active_claim_phase is durable_phase
    supervisor.fault = OccurrenceSupervisorFault.NONE
    result = reconciler.reconcile(ReconcileAutomationsV1())

    assert result.status is reconciled_phase
    assert repository.load().records[0].active_claim_phase is reconciled_phase
    assert executor.run_calls == 0


@pytest.mark.parametrize(
    ("barrier", "fault", "durable_phase", "reconciled_phase", "completes"),
    [
        (
            "dispatch",
            DeterministicCommitFault.BEFORE_COMMIT,
            OccurrenceControlStatus.CLAIMED,
            OccurrenceControlStatus.COMPLETED,
            True,
        ),
        (
            "dispatch",
            DeterministicCommitFault.AFTER_COMMIT,
            OccurrenceControlStatus.DISPATCHED,
            OccurrenceControlStatus.START_OUTCOME_UNKNOWN,
            False,
        ),
        (
            "running",
            DeterministicCommitFault.BEFORE_COMMIT,
            OccurrenceControlStatus.DISPATCHED,
            OccurrenceControlStatus.START_OUTCOME_UNKNOWN,
            False,
        ),
        (
            "running",
            DeterministicCommitFault.AFTER_COMMIT,
            OccurrenceControlStatus.RUNNING,
            OccurrenceControlStatus.EFFECT_OUTCOME_UNKNOWN,
            False,
        ),
    ],
)
def test_barrier_commit_unknown_never_crosses_an_unconfirmed_phase(
    barrier: str,
    fault: DeterministicCommitFault,
    durable_phase: OccurrenceControlStatus,
    reconciled_phase: OccurrenceControlStatus,
    completes: bool,
) -> None:
    reconciler, repository, executor, supervisor = _active_fixture(
        now=datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
        supervisor_factory=lambda repository: _ArmBarrierCommitFaultSupervisor(
            repository=repository,
            barrier=barrier,
            fault=fault,
        ),
    )

    with pytest.raises(AutomationRepositoryUnknownCommitError):
        reconciler.reconcile(ReconcileAutomationsV1())

    assert repository.load().records[0].active_claim_phase is durable_phase
    assert executor.run_calls == 0
    supervisor.barrier = "none"

    result = reconciler.reconcile(ReconcileAutomationsV1())

    assert result.status is reconciled_phase
    assert executor.run_calls == (1 if completes else 0)


def test_child_result_recovery_terminalizes_without_a_second_execution() -> None:
    reconciler, repository, executor, supervisor = _active_fixture(
        now=datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
    )
    supervisor.fault = OccurrenceSupervisorFault.CRASH_AFTER_EXECUTE

    with pytest.raises(SupervisorInjectedCrashError):
        reconciler.reconcile(ReconcileAutomationsV1())

    assert repository.load().records[0].active_claim_phase is OccurrenceControlStatus.RUNNING
    assert executor.run_calls == 1
    supervisor.fault = OccurrenceSupervisorFault.NONE

    result = reconciler.reconcile(ReconcileAutomationsV1())

    record = repository.load().records[0]
    assert result.code == "completed"
    assert executor.run_calls == 1
    assert record.terminal_history[-1].replayed is True


@pytest.mark.parametrize(
    ("fault", "expected_checkpoint_creations"),
    [
        (OccurrenceExecutorFault.CRASH_BEFORE_INITIALIZE, 0),
        (OccurrenceExecutorFault.CRASH_AFTER_INITIALIZE, 1),
    ],
)
def test_claimed_checkpoint_crash_resumes_without_duplicate_checkpoint(
    fault: OccurrenceExecutorFault,
    expected_checkpoint_creations: int,
) -> None:
    def executor_factory(result, repository, workspace):  # noqa: ANN001, ARG001, ANN202
        return DeterministicOccurrenceExecutor(result=result, fault=fault)

    reconciler, repository, executor, supervisor = _active_fixture(
        now=datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
        executor_factory=executor_factory,
    )

    with pytest.raises(ExecutorInjectedCrashError, match=fault.value):
        reconciler.reconcile(ReconcileAutomationsV1())

    assert repository.load().records[0].active_claim_phase is OccurrenceControlStatus.CLAIMED
    assert executor.checkpoint_creations == expected_checkpoint_creations
    assert executor.run_calls == 0
    executor.fault = OccurrenceExecutorFault.NONE

    result = reconciler.reconcile(ReconcileAutomationsV1())

    assert result.code == "completed"
    assert executor.checkpoint_creations == 1
    assert executor.run_calls == 1
    assert supervisor.run_calls == 1


class _ArmTerminalCommitFaultExecutor(DeterministicOccurrenceExecutor):
    def __init__(self, *, result, repository, fault) -> None:  # noqa: ANN001
        super().__init__(result=result)
        self._repository = repository
        self._fault = fault

    def run_once(self, prepared):  # noqa: ANN001, ANN201
        result = super().run_once(prepared)
        self._repository.arm_commit_fault(self._fault)
        return result


def test_terminal_commit_unknown_reloads_without_reexecuting() -> None:
    reconciler, repository, executor, supervisor = _active_fixture(
        now=datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
        executor_factory=lambda result, repository, workspace: _ArmTerminalCommitFaultExecutor(
            result=result,
            repository=repository,
            fault=DeterministicCommitFault.AFTER_COMMIT,
        ),
    )

    with pytest.raises(AutomationRepositoryUnknownCommitError):
        reconciler.reconcile(ReconcileAutomationsV1())

    assert repository.load().records[0].terminal_history[-1].status is (
        OccurrenceControlStatus.COMPLETED
    )
    assert executor.run_calls == 1

    result = reconciler.reconcile(ReconcileAutomationsV1())

    assert result.code == "not_due"
    assert executor.run_calls == 1


def test_terminal_commit_before_commit_recovers_exact_artifact_without_reexecution() -> None:
    artifact = TerminalArtifactCandidateV1(
        artifact_id="artifact:terminal-recovery",
        size_bytes=32,
        content_digest="f" * 64,
    )

    def executor_factory(result, repository, workspace):  # noqa: ANN001, ARG001, ANN202
        terminal = OccurrenceExecutionResultV1(
            status=result.status,
            checkpoint_identity_digest=result.checkpoint_identity_digest,
            result_digest=result.result_digest,
            replayed=False,
            error_code=None,
            artifacts=(artifact,),
        )
        return _ArmTerminalCommitFaultExecutor(
            result=terminal,
            repository=repository,
            fault=DeterministicCommitFault.BEFORE_COMMIT,
        )

    reconciler, repository, executor, supervisor = _active_fixture(
        now=datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
        executor_factory=executor_factory,
    )

    with pytest.raises(AutomationRepositoryUnknownCommitError):
        reconciler.reconcile(ReconcileAutomationsV1())

    assert repository.load().records[0].active_claim_phase is OccurrenceControlStatus.RUNNING
    assert executor.run_calls == 1

    result = reconciler.reconcile(ReconcileAutomationsV1())

    assert result.code == "completed"
    assert executor.run_calls == 1
    assert repository.load().records[0].terminal_history[-1].replayed is True
