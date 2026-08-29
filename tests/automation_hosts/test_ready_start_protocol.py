from __future__ import annotations

import pytest

from agent.automation.child import decode_occurrence_spec_frame, encode_occurrence_spec_frame
from agent.automation.supervisor import SupervisedOccurrenceSpecV1
from tests.automation_hosts.test_posix_supervisor import _prepared


def test_occurrence_spec_private_frame_round_trips_exact_binding() -> None:
    spec = SupervisedOccurrenceSpecV1.from_prepared(_prepared())

    assert decode_occurrence_spec_frame(encode_occurrence_spec_frame(spec)) == spec


@pytest.mark.parametrize(
    "mutation",
    [
        b"{}\n",
        b'{"type":"spec","prepared":{}}\n',
        b"x" * (64 * 1024 + 1),
        b'{"type":"spec","prepared":{"extra":true}}\n',
    ],
)
def test_occurrence_spec_private_frame_is_bounded_and_exact(mutation: bytes) -> None:
    with pytest.raises(ValueError):
        decode_occurrence_spec_frame(mutation)
