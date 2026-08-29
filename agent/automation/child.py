"""Platform-neutral bounded child handshake for one 019 occurrence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from agent.automation.supervisor import (
    OccurrenceExecutionResultV1,
    PreparedOccurrenceV1,
    SupervisedOccurrenceSpecV1,
)


class OccurrenceStartChannel(Protocol):
    def announce_ready(self, process_identity_digest: str) -> str: ...

    def acknowledge_start(self, process_identity_digest: str, permit: str) -> None: ...


class ChildOccurrenceExecutor(Protocol):
    def run_once(self, prepared: PreparedOccurrenceV1) -> OccurrenceExecutionResultV1: ...


@dataclass(frozen=True, slots=True)
class ChildResultV1:
    result: OccurrenceExecutionResultV1


MAX_OCCURRENCE_CHILD_FRAME_BYTES = 64 * 1024


def encode_occurrence_spec_frame(spec: SupervisedOccurrenceSpecV1) -> bytes:
    """Encode the private bounded child binding; this frame is never user-visible."""

    if not isinstance(spec, SupervisedOccurrenceSpecV1):
        raise TypeError("spec must use SupervisedOccurrenceSpecV1")
    prepared = spec.prepared
    payload = {
        "type": "spec",
        "prepared": {
            "automation_id": prepared.automation_id,
            "occurrence_id": prepared.occurrence_id,
            "authority_digest": prepared.authority_digest,
            "checkpoint_identity_digest": prepared.checkpoint_identity_digest,
            "source_identity_digest": prepared.source_identity_digest,
            "workspace_identity_digest": prepared.workspace_identity_digest,
            "deadline_utc": prepared.deadline_utc,
            "raw_capability": prepared.raw_capability,
            "binding_digest": prepared.binding_digest,
        },
    }
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")
    if len(encoded) > MAX_OCCURRENCE_CHILD_FRAME_BYTES:
        raise ValueError("occurrence child frame exceeds byte bound")
    return encoded


def decode_occurrence_spec_frame(frame: bytes) -> SupervisedOccurrenceSpecV1:
    if (
        not isinstance(frame, bytes)
        or not frame.endswith(b"\n")
        or frame.count(b"\n") != 1
        or len(frame) > MAX_OCCURRENCE_CHILD_FRAME_BYTES
    ):
        raise ValueError("occurrence child frame is malformed or oversized")
    try:
        value = json.loads(frame.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("occurrence child frame is malformed JSON") from error
    if not isinstance(value, dict) or set(value) != {"type", "prepared"}:
        raise ValueError("occurrence child frame fields must be exact")
    if value["type"] != "spec":
        raise ValueError("occurrence child frame type is invalid")
    prepared = value["prepared"]
    expected = {
        "automation_id",
        "occurrence_id",
        "authority_digest",
        "checkpoint_identity_digest",
        "source_identity_digest",
        "workspace_identity_digest",
        "deadline_utc",
        "raw_capability",
        "binding_digest",
    }
    if not isinstance(prepared, dict) or set(prepared) != expected:
        raise ValueError("prepared occurrence fields must be exact")
    return SupervisedOccurrenceSpecV1.from_prepared(PreparedOccurrenceV1(**prepared))


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate occurrence child frame field")
        value[key] = item
    return value


def run_occurrence_child(
    spec: SupervisedOccurrenceSpecV1,
    start_channel: OccurrenceStartChannel,
    occurrence_executor: ChildOccurrenceExecutor,
    *,
    process_identity_digest: str,
) -> ChildResultV1:
    """Cross the READY barrier, acknowledge one permit, then execute exactly once."""

    permit = start_channel.announce_ready(process_identity_digest)
    start_channel.acknowledge_start(process_identity_digest, permit)
    return ChildResultV1(occurrence_executor.run_once(spec.prepared))
