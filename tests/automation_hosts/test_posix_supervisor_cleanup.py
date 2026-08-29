from __future__ import annotations

import os

import pytest

from agent.automation.contracts import OccurrenceControlStatus
from agent.automation.supervisor import SupervisedOccurrenceSpecV1
from agent.automation_hosts import posix_supervisor
from agent.automation_hosts.posix_supervisor import (
    PosixSupervisorPreStartError,
    SupervisorProcessObservation,
)
from agent.process.group import ProcessCleanupError
from tests.automation_hosts.test_posix_supervisor import _callbacks, _prepared, _supervisor


def test_child_exit_before_ready_is_known_prestart_and_zero_callback() -> None:
    events: list[str] = []

    try:
        _supervisor("exit-before-ready").run(
            SupervisedOccurrenceSpecV1.from_prepared(_prepared()),
            _callbacks(events),
        )
    except PosixSupervisorPreStartError as error:
        assert error.code == "child_exit_before_ready"
    else:
        raise AssertionError("pre-READY child exit must remain a pre-start failure")

    assert events == []


def test_ready_timeout_is_known_prestart_and_zero_callback() -> None:
    events: list[str] = []

    try:
        _supervisor("no-ready").run(
            SupervisedOccurrenceSpecV1.from_prepared(_prepared()),
            _callbacks(events),
        )
    except PosixSupervisorPreStartError as error:
        assert error.code == "ready_timeout"
    else:
        raise AssertionError("READY timeout must remain a pre-start failure")

    assert events == []


def test_missing_start_ack_is_unknown_and_never_marks_running() -> None:
    events: list[str] = []

    outcome = _supervisor("no-start-ack").run(
        SupervisedOccurrenceSpecV1.from_prepared(_prepared()),
        _callbacks(events),
    )

    assert events == ["ready"]
    assert outcome.start_acknowledged is False
    assert outcome.cleanup_confirmed is True
    assert outcome.result.status is OccurrenceControlStatus.START_OUTCOME_UNKNOWN
    assert outcome.result.error_code == "start_ack_timeout"


def test_result_timeout_after_execution_permit_is_effect_outcome_unknown() -> None:
    events: list[str] = []

    outcome = _supervisor("hang-after-start").run(
        SupervisedOccurrenceSpecV1.from_prepared(_prepared()),
        _callbacks(events),
    )

    assert events == ["ready", "started"]
    assert outcome.start_acknowledged is True
    assert outcome.cleanup_confirmed is True
    assert outcome.result.status is OccurrenceControlStatus.EFFECT_OUTCOME_UNKNOWN
    assert outcome.result.error_code == "effect_outcome_unknown"


@pytest.mark.parametrize(
    "mode",
    ("partial-result-after-execute", "malformed-result-after-execute"),
)
def test_invalid_result_after_execution_permit_is_effect_outcome_unknown(
    mode: str,
) -> None:
    events: list[str] = []

    outcome = _supervisor(mode).run(
        SupervisedOccurrenceSpecV1.from_prepared(_prepared()),
        _callbacks(events),
    )

    assert events == ["ready", "started"]
    assert outcome.start_acknowledged is True
    assert outcome.cleanup_confirmed is True
    assert outcome.result.status is OccurrenceControlStatus.EFFECT_OUTCOME_UNKNOWN
    assert outcome.result.error_code == "effect_outcome_unknown"


def test_partial_result_cleanup_uncertainty_reports_cleanup_unknown(monkeypatch) -> None:
    events: list[str] = []

    def unknown_liveness(_pgid: int) -> bool:
        raise ProcessCleanupError("liveness unknown")

    monkeypatch.setattr(posix_supervisor, "group_alive", unknown_liveness)

    outcome = _supervisor("partial-result-after-execute").run(
        SupervisedOccurrenceSpecV1.from_prepared(_prepared()),
        _callbacks(events),
    )

    assert events == ["ready", "started"]
    assert outcome.start_acknowledged is True
    assert outcome.cleanup_confirmed is False
    assert outcome.result.status is OccurrenceControlStatus.CLEANUP_UNKNOWN
    assert outcome.result.error_code == "cleanup_unknown"


def test_liveness_uncertainty_after_result_reports_cleanup_unknown(monkeypatch) -> None:
    events: list[str] = []

    def unknown_liveness(_pgid: int) -> bool:
        raise ProcessCleanupError("liveness unknown")

    monkeypatch.setattr(posix_supervisor, "group_alive", unknown_liveness)

    outcome = _supervisor("success-without-descendant").run(
        SupervisedOccurrenceSpecV1.from_prepared(_prepared()),
        _callbacks(events),
    )

    assert events == ["ready", "started"]
    assert outcome.cleanup_confirmed is False
    assert outcome.result.status is OccurrenceControlStatus.CLEANUP_UNKNOWN
    assert outcome.result.error_code == "cleanup_unknown"


def test_group_identity_failure_reaps_leader_and_never_reaches_ready(monkeypatch) -> None:
    events: list[str] = []
    processes = []
    real_popen = posix_supervisor.subprocess.Popen

    def observed_popen(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    def identity_unknown(_pid: int) -> int:
        raise ProcessCleanupError("identity unknown")

    monkeypatch.setattr(posix_supervisor.subprocess, "Popen", observed_popen)
    monkeypatch.setattr(posix_supervisor, "verified_group_identity", identity_unknown)

    with pytest.raises(ProcessCleanupError, match="identity unknown"):
        _supervisor("no-ready").run(
            SupervisedOccurrenceSpecV1.from_prepared(_prepared()),
            _callbacks(events),
        )

    assert events == []
    assert len(processes) == 1
    process = processes[0]
    process.wait(timeout=2)
    with pytest.raises(ProcessLookupError):
        os.kill(process.pid, 0)


def test_parent_failure_after_ready_cleans_exact_group_before_propagating() -> None:
    observations: list[SupervisorProcessObservation] = []

    def fail_dispatch(_identity: str) -> str:
        raise RuntimeError("dispatch CAS failed")

    callbacks = _callbacks([])
    callbacks = type(callbacks)(
        on_ready=fail_dispatch,
        on_started=callbacks.on_started,
        execute=callbacks.execute,
    )

    with pytest.raises(RuntimeError, match="dispatch CAS failed"):
        _supervisor(
            "success-with-descendant",
            observations=observations,
        ).run(
            SupervisedOccurrenceSpecV1.from_prepared(_prepared()),
            callbacks,
        )

    assert len(observations) == 1
    observed = observations[0]
    assert observed.descendant_pid is not None
    with pytest.raises(ProcessLookupError):
        os.kill(observed.descendant_pid, 0)
