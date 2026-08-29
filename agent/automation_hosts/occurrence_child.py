"""POSIX stdio child for one already prepared 019 occurrence."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from typing import BinaryIO

from agent.automation.child import (
    MAX_OCCURRENCE_CHILD_FRAME_BYTES,
    ChildOccurrenceExecutor,
    decode_occurrence_spec_frame,
)
from agent.automation.supervisor import OccurrenceExecutionResultV1

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def run_posix_occurrence_child(
    *,
    executor_factory: Callable[[], ChildOccurrenceExecutor],
    input_stream: BinaryIO | None = None,
    output_stream: BinaryIO | None = None,
    leader_pid: int | None = None,
    process_group_id: int | None = None,
) -> int:
    """Cross the durable start barrier before constructing the Runtime executor."""

    if not callable(executor_factory):
        raise TypeError("executor_factory must be callable")
    source = sys.stdin.buffer if input_stream is None else input_stream
    sink = sys.stdout.buffer if output_stream is None else output_stream
    pid = os.getpid() if leader_pid is None else leader_pid
    pgid = os.getpgrp() if process_group_id is None else process_group_id
    for value, name in ((pid, "leader_pid"), (pgid, "process_group_id")):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive int")

    spec = decode_occurrence_spec_frame(_read_frame(source))
    _send(
        sink,
        {
            "descendant_pid": None,
            "leader_pid": pid,
            "process_group_id": pgid,
            "type": "ready",
        },
    )
    permit = _decode_permit(_read_frame(source))
    _send(
        sink,
        {
            "permit": permit["permit"],
            "process_identity_digest": permit["process_identity_digest"],
            "type": "started",
        },
    )
    _decode_execution_permit(_read_frame(source), permit)

    executor = executor_factory()
    if not callable(getattr(executor, "run_once", None)):
        raise TypeError("executor_factory must return ChildOccurrenceExecutor")
    result = executor.run_once(spec.prepared)
    if not isinstance(result, OccurrenceExecutionResultV1):
        raise TypeError("occurrence executor returned the wrong result type")
    if result.checkpoint_identity_digest != spec.prepared.checkpoint_identity_digest:
        raise ValueError("occurrence result checkpoint identity mismatch")
    _send(sink, {"result": _result_payload(result), "type": "result"})
    return 0


def _read_frame(stream: BinaryIO) -> bytes:
    frame = stream.readline(MAX_OCCURRENCE_CHILD_FRAME_BYTES + 1)
    if (
        not frame
        or len(frame) > MAX_OCCURRENCE_CHILD_FRAME_BYTES
        or not frame.endswith(b"\n")
        or frame.count(b"\n") != 1
    ):
        raise ValueError("occurrence child frame is malformed or oversized")
    return frame


def _decode_permit(frame: bytes) -> dict[str, str]:
    try:
        value = json.loads(frame.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("occurrence permit is malformed JSON") from error
    if not isinstance(value, dict) or set(value) != {
        "permit",
        "process_identity_digest",
        "type",
    }:
        raise ValueError("occurrence permit fields must be exact")
    permit = value["permit"]
    identity = value["process_identity_digest"]
    if value["type"] != "permit" or not isinstance(permit, str):
        raise ValueError("occurrence permit is malformed")
    if not permit or len(permit.encode("utf-8")) > 1_024 or "\n" in permit:
        raise ValueError("occurrence permit is malformed")
    if not isinstance(identity, str) or not _HEX64.fullmatch(identity):
        raise ValueError("occurrence process identity is malformed")
    return {"permit": permit, "process_identity_digest": identity}


def _decode_execution_permit(frame: bytes, start_permit: dict[str, str]) -> None:
    try:
        value = json.loads(frame.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("occurrence execution permit is malformed JSON") from error
    if not isinstance(value, dict) or set(value) != {
        "permit",
        "process_identity_digest",
        "type",
    }:
        raise ValueError("occurrence execution permit fields must be exact")
    if (
        value["type"] != "execute"
        or value["permit"] != start_permit["permit"]
        or value["process_identity_digest"] != start_permit["process_identity_digest"]
    ):
        raise ValueError("occurrence execution permit mismatch")


def _result_payload(result: OccurrenceExecutionResultV1) -> dict[str, object]:
    return {
        "artifacts": [
            {
                "artifact_id": artifact.artifact_id,
                "content_digest": artifact.content_digest,
                "size_bytes": artifact.size_bytes,
            }
            for artifact in result.artifacts
        ],
        "checkpoint_identity_digest": result.checkpoint_identity_digest,
        "error_code": result.error_code,
        "replayed": result.replayed,
        "result_digest": result.result_digest,
        "status": result.status.value,
    }


def _send(stream: BinaryIO, value: dict[str, object]) -> None:
    frame = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")
    if len(frame) > MAX_OCCURRENCE_CHILD_FRAME_BYTES:
        raise ValueError("occurrence child frame exceeds byte bound")
    stream.write(frame)
    stream.flush()


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate occurrence permit field")
        value[key] = item
    return value


__all__ = ["run_posix_occurrence_child"]
