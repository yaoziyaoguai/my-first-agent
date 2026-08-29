"""Bounded POSIX child supervisor for one prepared automation occurrence."""

from __future__ import annotations

import json
import os
import select
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from agent.automation.child import (
    MAX_OCCURRENCE_CHILD_FRAME_BYTES,
    encode_occurrence_spec_frame,
)
from agent.automation.contracts import OccurrenceControlStatus
from agent.automation.supervisor import (
    OccurrenceExecutionResultV1,
    OccurrenceStartCallbacks,
    SupervisedOccurrenceResultV1,
    SupervisedOccurrenceSpecV1,
)
from agent.automation.workspace import TerminalArtifactCandidateV1
from agent.process.group import (
    ProcessCleanupError,
    group_alive,
    terminate_group,
    verified_group_identity,
)
from agent.runtime.contracts import canonical_json_digest


@dataclass(frozen=True, slots=True)
class SupervisorProcessObservation:
    leader_pid: int
    process_group_id: int
    descendant_pid: int | None
    descendant_process_group_id: int | None


class PosixSupervisorPreStartError(RuntimeError):
    """A proven pre-READY failure with confirmed process-group cleanup."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _FrameTimeoutError(TimeoutError):
    pass


class _FrameReader:
    def __init__(self, descriptor: int) -> None:
        self._descriptor = descriptor
        self._buffer = bytearray()

    def read(self, timeout_seconds: float) -> bytes | None:
        deadline = time.monotonic() + timeout_seconds
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                frame = bytes(self._buffer[: newline + 1])
                del self._buffer[: newline + 1]
                return frame
            if len(self._buffer) > MAX_OCCURRENCE_CHILD_FRAME_BYTES:
                raise ValueError("occurrence child frame exceeds byte bound")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _FrameTimeoutError
            readable, _, _ = select.select([self._descriptor], [], [], remaining)
            if not readable:
                raise _FrameTimeoutError
            chunk = os.read(self._descriptor, 8_192)
            if not chunk:
                if self._buffer:
                    raise ValueError("occurrence child frame is not newline terminated")
                return None
            self._buffer.extend(chunk)


class PosixOccurrenceSupervisor:
    """Own one child process group and a strict READY/start/execute/result handshake."""

    def __init__(
        self,
        *,
        command: tuple[str, ...],
        ready_timeout_seconds: float,
        start_ack_timeout_seconds: float,
        result_timeout_seconds: float,
        term_grace_seconds: float,
        kill_grace_seconds: float,
        cleanup_verify_seconds: float,
        observation_sink=None,
    ) -> None:
        if (
            not isinstance(command, tuple)
            or not command
            or any(not isinstance(item, str) or not item for item in command)
            or not Path(command[0]).is_absolute()
        ):
            raise ValueError("command must be a non-empty trusted absolute argv tuple")
        for value, name in (
            (ready_timeout_seconds, "ready_timeout_seconds"),
            (start_ack_timeout_seconds, "start_ack_timeout_seconds"),
            (result_timeout_seconds, "result_timeout_seconds"),
            (term_grace_seconds, "term_grace_seconds"),
            (kill_grace_seconds, "kill_grace_seconds"),
            (cleanup_verify_seconds, "cleanup_verify_seconds"),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"{name} must be positive")
        self._command = command
        self._ready_timeout_seconds = float(ready_timeout_seconds)
        self._start_ack_timeout_seconds = float(start_ack_timeout_seconds)
        self._result_timeout_seconds = float(result_timeout_seconds)
        self._term_grace_seconds = float(term_grace_seconds)
        self._kill_grace_seconds = float(kill_grace_seconds)
        self._cleanup_verify_seconds = float(cleanup_verify_seconds)
        self._observation_sink = observation_sink

    def run(
        self,
        spec: SupervisedOccurrenceSpecV1,
        callbacks: OccurrenceStartCallbacks,
    ) -> SupervisedOccurrenceResultV1:
        if not isinstance(spec, SupervisedOccurrenceSpecV1):
            raise TypeError("spec must use SupervisedOccurrenceSpecV1")
        if not isinstance(callbacks, OccurrenceStartCallbacks):
            raise TypeError("callbacks must use OccurrenceStartCallbacks")

        proc = subprocess.Popen(  # noqa: S603 - trusted composition binds exact argv
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        if proc.stdin is None or proc.stdout is None:
            proc.kill()
            proc.wait(timeout=self._cleanup_verify_seconds)
            raise RuntimeError("private child pipes are unavailable")
        try:
            pgid = verified_group_identity(proc.pid)
        except ProcessCleanupError:
            # PGID authority is unavailable, so group cleanup cannot be claimed.
            # Still reap the exact leader to avoid leaking a known process.
            try:
                proc.kill()
                proc.wait(timeout=self._cleanup_verify_seconds)
            except (OSError, subprocess.TimeoutExpired):
                pass
            finally:
                proc.stdin.close()
                proc.stdout.close()
            raise
        process_identity_digest = canonical_json_digest(
            {
                "leader_pid": proc.pid,
                "process_group_id": pgid,
                "prepared_binding_digest": spec.prepared.binding_digest,
                "spawn_nonce": time.monotonic_ns(),
            }
        )
        reader = _FrameReader(proc.stdout.fileno())
        try:
            self._write(proc.stdin.fileno(), encode_occurrence_spec_frame(spec))
            try:
                ready_frame = reader.read(self._ready_timeout_seconds)
            except _FrameTimeoutError:
                return self._raise_prestart_or_unknown(
                    proc,
                    pgid,
                    "ready_timeout",
                )
            if ready_frame is None:
                return self._raise_prestart_or_unknown(
                    proc,
                    pgid,
                    "child_exit_before_ready",
                )
            observation = self._decode_ready(ready_frame, proc.pid, pgid)
            if self._observation_sink is not None:
                self._observation_sink(observation)

            permit = callbacks.on_ready(process_identity_digest)
            self._validate_permit(permit)
            try:
                self._write(
                    proc.stdin.fileno(),
                    self._encode_frame(
                        {
                            "type": "permit",
                            "process_identity_digest": process_identity_digest,
                            "permit": permit,
                        }
                    ),
                )
            except (BrokenPipeError, OSError):
                return self._terminal_unknown(
                    proc,
                    pgid,
                    spec,
                    process_identity_digest,
                    OccurrenceControlStatus.START_OUTCOME_UNKNOWN,
                    "start_permit_unknown",
                    start_acknowledged=False,
                )

            try:
                started_frame = reader.read(self._start_ack_timeout_seconds)
            except _FrameTimeoutError:
                started_frame = None
            if started_frame is None:
                return self._terminal_unknown(
                    proc,
                    pgid,
                    spec,
                    process_identity_digest,
                    OccurrenceControlStatus.START_OUTCOME_UNKNOWN,
                    "start_ack_timeout",
                    start_acknowledged=False,
                )
            self._decode_started(started_frame, process_identity_digest, permit)
            callbacks.on_started(process_identity_digest, permit)
            try:
                self._write(
                    proc.stdin.fileno(),
                    self._encode_frame(
                        {
                            "type": "execute",
                            "process_identity_digest": process_identity_digest,
                            "permit": permit,
                        }
                    ),
                )
            except (BrokenPipeError, OSError):
                return self._terminal_unknown(
                    proc,
                    pgid,
                    spec,
                    process_identity_digest,
                    OccurrenceControlStatus.START_OUTCOME_UNKNOWN,
                    "execution_permit_unknown",
                    start_acknowledged=True,
                )

            try:
                result_frame = reader.read(self._result_timeout_seconds)
            except _FrameTimeoutError:
                result_frame = None
            if result_frame is None:
                return self._terminal_unknown(
                    proc,
                    pgid,
                    spec,
                    process_identity_digest,
                    OccurrenceControlStatus.WORKER_DEADLINE,
                    "worker_deadline",
                    start_acknowledged=True,
                )
            result = self._decode_result(result_frame)
            if (
                result.checkpoint_identity_digest
                != spec.prepared.checkpoint_identity_digest
            ):
                return self._terminal_unknown(
                    proc,
                    pgid,
                    spec,
                    process_identity_digest,
                    OccurrenceControlStatus.EFFECT_OUTCOME_UNKNOWN,
                    "result_binding_mismatch",
                    start_acknowledged=True,
                )
            cleanup_confirmed = self._cleanup(proc, pgid)
            if not cleanup_confirmed:
                return self._result(
                    spec,
                    process_identity_digest,
                    OccurrenceControlStatus.CLEANUP_UNKNOWN,
                    "cleanup_unknown",
                    start_acknowledged=True,
                    cleanup_confirmed=False,
                )
            return SupervisedOccurrenceResultV1(
                process_identity_digest=process_identity_digest,
                start_acknowledged=True,
                cleanup_confirmed=True,
                result=result,
            )
        except PosixSupervisorPreStartError:
            raise
        except Exception:
            self._cleanup(proc, pgid)
            raise
        finally:
            proc.stdin.close()
            proc.stdout.close()

    def _raise_prestart_or_unknown(
        self,
        proc: subprocess.Popen[bytes],
        pgid: int,
        code: str,
    ) -> NoReturn:
        if self._cleanup(proc, pgid):
            raise PosixSupervisorPreStartError(code)
        raise ProcessCleanupError("pre-start child cleanup could not be confirmed")

    def _terminal_unknown(
        self,
        proc: subprocess.Popen[bytes],
        pgid: int,
        spec: SupervisedOccurrenceSpecV1,
        process_identity_digest: str,
        status: OccurrenceControlStatus,
        error_code: str,
        *,
        start_acknowledged: bool,
    ) -> SupervisedOccurrenceResultV1:
        cleanup_confirmed = self._cleanup(proc, pgid)
        if not cleanup_confirmed:
            status = OccurrenceControlStatus.CLEANUP_UNKNOWN
            error_code = "cleanup_unknown"
        return self._result(
            spec,
            process_identity_digest,
            status,
            error_code,
            start_acknowledged=start_acknowledged,
            cleanup_confirmed=cleanup_confirmed,
        )

    @staticmethod
    def _result(
        spec: SupervisedOccurrenceSpecV1,
        process_identity_digest: str,
        status: OccurrenceControlStatus,
        error_code: str,
        *,
        start_acknowledged: bool,
        cleanup_confirmed: bool,
    ) -> SupervisedOccurrenceResultV1:
        return SupervisedOccurrenceResultV1(
            process_identity_digest=process_identity_digest,
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

    def _cleanup(self, proc: subprocess.Popen[bytes], pgid: int) -> bool:
        try:
            # EOF can race with ``Popen`` updating returncode. Reap a finished
            # leader before signal-0 so macOS cannot report the dead PGID as EPERM.
            proc.poll()
            if group_alive(pgid):
                terminate_group(
                    proc,
                    pgid,
                    term_grace_seconds=self._term_grace_seconds,
                    kill_grace_seconds=self._kill_grace_seconds,
                    verify_budget_seconds=self._cleanup_verify_seconds,
                )
            else:
                proc.wait(timeout=self._cleanup_verify_seconds)
            return not group_alive(pgid)
        except (ProcessCleanupError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def _write(descriptor: int, frame: bytes) -> None:
        view = memoryview(frame)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise BrokenPipeError
            view = view[written:]

    @staticmethod
    def _encode_frame(value: dict[str, object]) -> bytes:
        frame = (
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            + "\n"
        ).encode("utf-8")
        if len(frame) > MAX_OCCURRENCE_CHILD_FRAME_BYTES:
            raise ValueError("occurrence child frame exceeds byte bound")
        return frame

    @staticmethod
    def _decode_object(frame: bytes) -> dict[str, object]:
        if (
            not frame.endswith(b"\n")
            or frame.count(b"\n") != 1
            or len(frame) > MAX_OCCURRENCE_CHILD_FRAME_BYTES
        ):
            raise ValueError("occurrence child frame is malformed")
        try:
            value = json.loads(frame.decode("utf-8"), object_pairs_hook=_strict_object)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("occurrence child frame is malformed JSON") from error
        if not isinstance(value, dict):
            raise ValueError("occurrence child frame must be an object")
        return value

    def _decode_ready(
        self,
        frame: bytes,
        leader_pid: int,
        process_group_id: int,
    ) -> SupervisorProcessObservation:
        value = self._decode_object(frame)
        if set(value) != {
            "type",
            "leader_pid",
            "process_group_id",
            "descendant_pid",
        } or value["type"] != "ready":
            raise ValueError("READY frame fields are invalid")
        if value["leader_pid"] != leader_pid or value["process_group_id"] != process_group_id:
            raise ValueError("READY process identity mismatch")
        descendant_pid = value["descendant_pid"]
        if descendant_pid is not None and (
            isinstance(descendant_pid, bool)
            or not isinstance(descendant_pid, int)
            or descendant_pid <= 0
        ):
            raise ValueError("READY descendant pid is invalid")
        descendant_pgid = None
        if descendant_pid is not None:
            descendant_pgid = os.getpgid(descendant_pid)
            if descendant_pgid != process_group_id:
                raise ValueError("READY descendant process group mismatch")
        return SupervisorProcessObservation(
            leader_pid=leader_pid,
            process_group_id=process_group_id,
            descendant_pid=descendant_pid,
            descendant_process_group_id=descendant_pgid,
        )

    def _decode_started(self, frame: bytes, identity: str, permit: str) -> None:
        value = self._decode_object(frame)
        if set(value) != {"type", "process_identity_digest", "permit"} or value[
            "type"
        ] != "started":
            raise ValueError("STARTED frame fields are invalid")
        if value["process_identity_digest"] != identity or value["permit"] != permit:
            raise ValueError("STARTED frame binding mismatch")

    def _decode_result(self, frame: bytes) -> OccurrenceExecutionResultV1:
        value = self._decode_object(frame)
        if set(value) != {"type", "result"} or value["type"] != "result":
            raise ValueError("RESULT frame fields are invalid")
        result = value["result"]
        if not isinstance(result, dict) or set(result) != {
            "status",
            "checkpoint_identity_digest",
            "result_digest",
            "replayed",
            "error_code",
            "artifacts",
        }:
            raise ValueError("RESULT payload fields are invalid")
        artifacts = result["artifacts"]
        if not isinstance(artifacts, list):
            raise ValueError("RESULT artifacts must be a list")
        decoded_artifacts: list[TerminalArtifactCandidateV1] = []
        for artifact in artifacts:
            if not isinstance(artifact, dict) or set(artifact) != {
                "artifact_id",
                "size_bytes",
                "content_digest",
            }:
                raise ValueError("RESULT artifact fields are invalid")
            decoded_artifacts.append(TerminalArtifactCandidateV1(**artifact))
        try:
            status = OccurrenceControlStatus(result["status"])
        except (TypeError, ValueError) as error:
            raise ValueError("RESULT status is invalid") from error
        return OccurrenceExecutionResultV1(
            status=status,
            checkpoint_identity_digest=result["checkpoint_identity_digest"],
            result_digest=result["result_digest"],
            replayed=result["replayed"],
            error_code=result["error_code"],
            artifacts=tuple(decoded_artifacts),
        )

    @staticmethod
    def _validate_permit(permit: object) -> None:
        if (
            not isinstance(permit, str)
            or not permit
            or len(permit.encode("utf-8")) > 1_024
            or "\n" in permit
        ):
            raise ValueError("start permit is malformed")


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate occurrence child frame field")
        value[key] = item
    return value
