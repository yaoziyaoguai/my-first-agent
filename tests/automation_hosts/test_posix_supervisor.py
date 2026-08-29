from __future__ import annotations

import os
import sys
import time

from agent.automation.contracts import OccurrenceControlStatus
from agent.automation.supervisor import (
    OccurrenceExecutionResultV1,
    OccurrenceStartCallbacks,
    PreparedOccurrenceV1,
    SupervisedOccurrenceSpecV1,
)
from agent.automation_hosts.posix_supervisor import (
    PosixOccurrenceSupervisor,
    SupervisorProcessObservation,
)
from agent.process.group import group_alive


def _prepared() -> PreparedOccurrenceV1:
    return PreparedOccurrenceV1.create(
        automation_id="automation:one",
        occurrence_id="occurrence:0000",
        authority_digest="1" * 64,
        checkpoint_identity_digest="2" * 64,
        source_identity_digest="3" * 64,
        workspace_identity_digest="4" * 64,
        deadline_utc="2099-01-01T00:00:00Z",
        raw_capability="raw-capability-" + "5" * 48,
    )


def _callbacks(events: list[str]) -> OccurrenceStartCallbacks:
    def parent_execute_must_not_run() -> OccurrenceExecutionResultV1:
        raise AssertionError("real child execution cannot run in the supervisor parent")

    return OccurrenceStartCallbacks(
        on_ready=lambda _identity: events.append("ready") or "permit:exact",
        on_started=lambda _identity, _permit: events.append("started"),
        execute=parent_execute_must_not_run,
    )


def _supervisor(
    mode: str,
    *,
    observations: list[SupervisorProcessObservation] | None = None,
) -> PosixOccurrenceSupervisor:
    return PosixOccurrenceSupervisor(
        command=(
            sys.executable,
            "-m",
            "tests.automation_hosts.fixtures.occurrence_child",
            mode,
        ),
        ready_timeout_seconds=0.35,
        start_ack_timeout_seconds=0.35,
        result_timeout_seconds=0.5,
        term_grace_seconds=0.1,
        kill_grace_seconds=0.1,
        cleanup_verify_seconds=1.0,
        observation_sink=None if observations is None else observations.append,
    )


def test_real_child_ready_start_result_and_descendant_cleanup() -> None:
    events: list[str] = []
    observations: list[SupervisorProcessObservation] = []

    outcome = _supervisor("success-with-descendant", observations=observations).run(
        SupervisedOccurrenceSpecV1.from_prepared(_prepared()),
        _callbacks(events),
    )

    assert events == ["ready", "started"]
    assert outcome.start_acknowledged is True
    assert outcome.cleanup_confirmed is True
    assert outcome.result.status is OccurrenceControlStatus.COMPLETED
    assert len(observations) == 1
    observed = observations[0]
    assert observed.leader_pid == observed.process_group_id
    assert observed.descendant_pid is not None
    assert observed.descendant_process_group_id == observed.process_group_id
    assert group_alive(observed.process_group_id) is False
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        try:
            os.kill(observed.descendant_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        raise AssertionError("owned descendant survived supervisor cleanup")
