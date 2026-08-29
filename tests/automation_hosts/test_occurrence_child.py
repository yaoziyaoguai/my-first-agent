from __future__ import annotations

import io
import json

import pytest

from agent.automation.child import encode_occurrence_spec_frame
from agent.automation.contracts import OccurrenceControlStatus
from agent.automation.supervisor import (
    OccurrenceExecutionResultV1,
    SupervisedOccurrenceSpecV1,
)
from agent.automation_hosts.occurrence_child import run_posix_occurrence_child
from tests.automation_hosts.test_posix_supervisor import _prepared


def _permit(identity: str = "8" * 64) -> bytes:
    return (
        json.dumps(
            {
                "permit": "permit:exact",
                "process_identity_digest": identity,
                "type": "permit",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def _execution_permit(identity: str = "8" * 64) -> bytes:
    return (
        json.dumps(
            {
                "permit": "permit:exact",
                "process_identity_digest": identity,
                "type": "execute",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def _completed() -> OccurrenceExecutionResultV1:
    return OccurrenceExecutionResultV1(
        status=OccurrenceControlStatus.COMPLETED,
        checkpoint_identity_digest=_prepared().checkpoint_identity_digest,
        result_digest="9" * 64,
        replayed=False,
        error_code=None,
        artifacts=(),
    )


def test_child_constructs_executor_only_after_exact_execution_permit() -> None:
    prepared = _prepared()
    input_stream = io.BytesIO(
        encode_occurrence_spec_frame(SupervisedOccurrenceSpecV1.from_prepared(prepared))
        + _permit()
        + _execution_permit()
    )
    output_stream = io.BytesIO()
    events: list[str] = []

    class _Executor:
        def run_once(self, actual):  # noqa: ANN001, ANN201
            assert actual == prepared
            events.append("execute")
            return _completed()

    def factory():  # noqa: ANN202
        frames = output_stream.getvalue().splitlines()
        assert [json.loads(frame)["type"] for frame in frames] == ["ready", "started"]
        events.append("factory")
        return _Executor()

    result = run_posix_occurrence_child(
        executor_factory=factory,
        input_stream=input_stream,
        output_stream=output_stream,
        leader_pid=321,
        process_group_id=321,
    )

    frames = [json.loads(frame) for frame in output_stream.getvalue().splitlines()]
    assert [frame["type"] for frame in frames] == ["ready", "started", "result"]
    assert frames[0] == {
        "descendant_pid": None,
        "leader_pid": 321,
        "process_group_id": 321,
        "type": "ready",
    }
    assert frames[1] == {
        "permit": "permit:exact",
        "process_identity_digest": "8" * 64,
        "type": "started",
    }
    assert frames[2]["result"]["status"] == "completed"
    assert result == 0
    assert events == ["factory", "execute"]


def test_child_waits_for_execution_permit_before_executor_construction() -> None:
    called = False

    def factory():  # noqa: ANN202
        nonlocal called
        called = True
        raise AssertionError("executor must wait for the execution permit")

    with pytest.raises(ValueError, match="occurrence child frame"):
        run_posix_occurrence_child(
            executor_factory=factory,
            input_stream=io.BytesIO(
                encode_occurrence_spec_frame(
                    SupervisedOccurrenceSpecV1.from_prepared(_prepared())
                )
                + _permit()
            ),
            output_stream=io.BytesIO(),
            leader_pid=321,
            process_group_id=321,
        )

    assert called is False


@pytest.mark.parametrize(
    "permit",
    [
        b"{}\n",
        b'{"permit":"x","process_identity_digest":"bad","type":"permit"}\n',
        (
            b'{"extra":true,"permit":"x","process_identity_digest":"'
            + b"8" * 64
            + b'","type":"permit"}\n'
        ),
        b"x" * (64 * 1024 + 1),
    ],
)
def test_child_rejects_malformed_permit_before_executor_construction(
    permit: bytes,
) -> None:
    called = False

    def factory():  # noqa: ANN202
        nonlocal called
        called = True
        raise AssertionError("invalid permit must not construct the executor")

    with pytest.raises(ValueError):
        run_posix_occurrence_child(
            executor_factory=factory,
            input_stream=io.BytesIO(
                encode_occurrence_spec_frame(
                    SupervisedOccurrenceSpecV1.from_prepared(_prepared())
                )
                + permit
            ),
            output_stream=io.BytesIO(),
            leader_pid=321,
            process_group_id=321,
        )

    assert called is False


def test_child_rejects_executor_result_for_another_checkpoint() -> None:
    class _Executor:
        def run_once(self, _prepared):  # noqa: ANN001, ANN201
            return OccurrenceExecutionResultV1(
                status=OccurrenceControlStatus.COMPLETED,
                checkpoint_identity_digest="a" * 64,
                result_digest="b" * 64,
                replayed=False,
                error_code=None,
                artifacts=(),
            )

    with pytest.raises(ValueError, match="checkpoint identity"):
        run_posix_occurrence_child(
            executor_factory=lambda: _Executor(),
            input_stream=io.BytesIO(
                encode_occurrence_spec_frame(
                    SupervisedOccurrenceSpecV1.from_prepared(_prepared())
                )
                + _permit()
                + _execution_permit()
            ),
            output_stream=io.BytesIO(),
            leader_pid=321,
            process_group_id=321,
        )
