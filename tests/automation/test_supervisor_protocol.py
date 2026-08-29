from __future__ import annotations

import pytest

from agent.automation.child import run_occurrence_child
from agent.automation.contracts import OccurrenceControlStatus
from agent.automation.supervisor import (
    DeterministicOccurrenceExecutor,
    DeterministicOccurrenceSupervisor,
    OccurrenceExecutionResultV1,
    OccurrenceStartCallbacks,
    OccurrenceSupervisorFault,
    PreparedOccurrenceV1,
    SupervisedOccurrenceSpecV1,
    SupervisorInjectedCrashError,
)


def _prepared() -> PreparedOccurrenceV1:
    return PreparedOccurrenceV1.create(
        automation_id="automation:test",
        occurrence_id="occurrence:test",
        authority_digest="1" * 64,
        checkpoint_identity_digest="2" * 64,
        source_identity_digest="3" * 64,
        workspace_identity_digest="4" * 64,
        deadline_utc="2026-08-28T00:10:00Z",
        raw_capability="opaque-capability-019-000000000000000000000000",
    )


def _result() -> OccurrenceExecutionResultV1:
    return OccurrenceExecutionResultV1(
        status=OccurrenceControlStatus.COMPLETED,
        checkpoint_identity_digest="2" * 64,
        result_digest="5" * 64,
        replayed=False,
        error_code=None,
        artifacts=(),
    )


def test_ready_callback_precedes_start_and_executor_runs_exactly_once() -> None:
    executor = DeterministicOccurrenceExecutor(result=_result())
    supervisor = DeterministicOccurrenceSupervisor(
        process_identity_digest="6" * 64,
    )
    events: list[str] = []

    outcome = supervisor.run(
        SupervisedOccurrenceSpecV1.from_prepared(_prepared()),
        OccurrenceStartCallbacks(
            on_ready=lambda process: events.append("ready") or "permit:exact",
            on_started=lambda process, permit: events.append("started"),
            execute=lambda: events.append("execute") or executor.run_once(_prepared()),
        ),
    )

    assert events == ["ready", "started", "execute"]
    assert executor.run_calls == 1
    assert outcome.start_acknowledged is True
    assert outcome.result == _result()


def test_unknown_start_permit_never_calls_executor() -> None:
    executor = DeterministicOccurrenceExecutor(result=_result())
    supervisor = DeterministicOccurrenceSupervisor(
        process_identity_digest="6" * 64,
        fault=OccurrenceSupervisorFault.START_PERMIT_UNKNOWN,
    )
    events: list[str] = []

    outcome = supervisor.run(
        SupervisedOccurrenceSpecV1.from_prepared(_prepared()),
        OccurrenceStartCallbacks(
            on_ready=lambda process: events.append("ready") or "permit:exact",
            on_started=lambda process, permit: events.append("started"),
            execute=lambda: events.append("execute") or executor.run_once(_prepared()),
        ),
    )

    assert events == ["ready"]
    assert executor.run_calls == 0
    assert outcome.result.status is OccurrenceControlStatus.START_OUTCOME_UNKNOWN


def test_child_protocol_announces_ready_acknowledges_and_executes_once() -> None:
    events: list[str] = []
    executor = DeterministicOccurrenceExecutor(result=_result())

    class StartChannel:
        def announce_ready(self, process_identity_digest: str) -> str:
            events.append(f"ready:{process_identity_digest}")
            return "permit:exact"

        def acknowledge_start(self, process_identity_digest: str, permit: str) -> None:
            events.append(f"started:{process_identity_digest}:{permit}")

    result = run_occurrence_child(
        SupervisedOccurrenceSpecV1.from_prepared(_prepared()),
        StartChannel(),
        executor,
        process_identity_digest="6" * 64,
    )

    assert events == [f"ready:{'6' * 64}", f"started:{'6' * 64}:permit:exact"]
    assert result.result == _result()
    assert executor.run_calls == 1


@pytest.mark.parametrize(
    ("fault", "expected_events", "expected_runs"),
    [
        (OccurrenceSupervisorFault.CRASH_AFTER_READY, ["ready"], 0),
        (OccurrenceSupervisorFault.CRASH_AFTER_STARTED, ["ready", "started"], 0),
        (
            OccurrenceSupervisorFault.CRASH_AFTER_EXECUTE,
            ["ready", "started", "execute"],
            1,
        ),
    ],
)
def test_supervisor_crash_points_do_not_cross_the_next_barrier(
    fault: OccurrenceSupervisorFault,
    expected_events: list[str],
    expected_runs: int,
) -> None:
    executor = DeterministicOccurrenceExecutor(result=_result())
    supervisor = DeterministicOccurrenceSupervisor(
        process_identity_digest="6" * 64,
        fault=fault,
    )
    events: list[str] = []

    with pytest.raises(SupervisorInjectedCrashError, match=fault.value):
        supervisor.run(
            SupervisedOccurrenceSpecV1.from_prepared(_prepared()),
            OccurrenceStartCallbacks(
                on_ready=lambda process: events.append("ready") or "permit:exact",
                on_started=lambda process, permit: events.append("started"),
                execute=lambda: events.append("execute") or executor.run_once(_prepared()),
            ),
        )

    assert events == expected_events
    assert executor.run_calls == expected_runs
