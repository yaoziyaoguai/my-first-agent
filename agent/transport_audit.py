"""Secret-free HTTP attempt ledger for acceptance and operator diagnostics."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agent.runtime.ports import ModelAttemptBudgetExhaustedError

TRANSPORT_ATTEMPT_SCHEMA = "first-agent/transport-attempt/v1"
TransportAttemptRecorder = Callable[[str, str], None]
_MAX_LEDGER_BYTES = 1_000_000


@dataclass(frozen=True, slots=True)
class TransportAttemptLedger:
    """在 HTTP adapter 边界、发送前追加不含 payload/credential 的计数事实。"""

    path: Path
    max_model_attempts: int | None = None

    def __post_init__(self) -> None:
        if self.max_model_attempts is not None and (
            not isinstance(self.max_model_attempts, int)
            or isinstance(self.max_model_attempts, bool)
            or self.max_model_attempts < 1
        ):
            raise ValueError("max_model_attempts must be a positive integer")

    def record(self, kind: str, destination: str) -> None:
        if kind not in {"model", "web"}:
            raise ValueError("transport attempt kind is not admitted")
        if not destination or any(ord(character) < 0x20 for character in destination):
            raise ValueError("transport attempt destination is malformed")
        document = {
            "schema": TRANSPORT_ATTEMPT_SCHEMA,
            "kind": kind,
            "destination_digest": hashlib.sha256(
                destination.encode("utf-8")
            ).hexdigest(),
        }
        payload = (
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC
        flags |= getattr(os, "O_NOFOLLOW", 0)
        parent_fd, name = _open_ledger_parent(self.path)
        lock_descriptor: int | None = None
        descriptor: int | None = None
        try:
            try:
                import fcntl
            except ImportError as error:  # pragma: no cover - 当前产品 host 是 POSIX
                raise OSError("transport audit locking is unavailable") from error
            lock_descriptor = _open_or_create_owner_file(
                parent_fd,
                f".{name}.lock",
                flags,
            )
            _validate_owner_file(lock_descriptor, label="lock")
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            descriptor = _open_or_create_owner_file(parent_fd, name, flags)
            status = _validate_owner_file(descriptor, label="target")
            if status.st_size > _MAX_LEDGER_BYTES:
                raise OSError("transport audit ledger exceeds its read limit")
            os.lseek(descriptor, 0, os.SEEK_SET)
            existing = os.read(descriptor, _MAX_LEDGER_BYTES + 1)
            records = _decode_records(existing)
            if (
                kind == "model"
                and self.max_model_attempts is not None
                and sum(record["kind"] == "model" for record in records)
                >= self.max_model_attempts
            ):
                raise ModelAttemptBudgetExhaustedError(
                    "model attempt budget exhausted before dispatch"
                )
            os.lseek(descriptor, 0, os.SEEK_END)
            remaining = memoryview(payload)
            while remaining:
                written = os.write(descriptor, remaining)
                if written < 1:
                    raise OSError("transport audit append was incomplete")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if lock_descriptor is not None:
                os.close(lock_descriptor)
            os.close(parent_fd)


def _decode_records(payload: bytes) -> tuple[dict[str, str], ...]:
    if not payload:
        return ()
    if len(payload) > _MAX_LEDGER_BYTES or not payload.endswith(b"\n"):
        raise OSError("transport audit ledger is malformed")
    try:
        lines = payload.decode("utf-8").splitlines()
        records = tuple(json.loads(line) for line in lines)
    except (UnicodeDecodeError, ValueError):
        raise OSError("transport audit ledger is malformed") from None
    expected_keys = {"schema", "kind", "destination_digest"}
    for record in records:
        if (
            not isinstance(record, dict)
            or set(record) != expected_keys
            or record.get("schema") != TRANSPORT_ATTEMPT_SCHEMA
            or record.get("kind") not in {"model", "web"}
            or not isinstance(record.get("destination_digest"), str)
            or len(record["destination_digest"]) != 64
            or any(
                character not in "0123456789abcdef"
                for character in record["destination_digest"]
            )
        ):
            raise OSError("transport audit ledger is malformed")
    return records


def _open_ledger_parent(path: Path) -> tuple[int, str]:
    absolute = Path(path).absolute()
    parent = absolute.parent
    try:
        if parent.resolve(strict=True) != parent:
            raise OSError("transport audit parent must not contain symlinks")
        descriptor = os.open(
            parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
    except (FileNotFoundError, OSError) as error:
        raise OSError("transport audit parent is unavailable or unsafe") from error
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise OSError("transport audit parent must be owner-only")
        return descriptor, absolute.name
    except Exception:
        os.close(descriptor)
        raise


def _validate_owner_file(descriptor: int, *, label: str) -> os.stat_result:
    status = os.fstat(descriptor)
    if not stat.S_ISREG(status.st_mode):
        raise OSError(f"transport audit {label} must be a regular file")
    if status.st_uid != os.getuid() or status.st_mode & 0o077:
        raise OSError(f"transport audit {label} must be owner-only")
    return status


def _open_or_create_owner_file(parent_fd: int, name: str, flags: int) -> int:
    open_flags = flags & ~os.O_CREAT
    try:
        return os.open(name, open_flags, dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            created = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                0o600,
                dir_fd=parent_fd,
            )
        except FileExistsError:
            pass
        else:
            os.close(created)
        return os.open(name, open_flags, dir_fd=parent_fd)


__all__ = [
    "TRANSPORT_ATTEMPT_SCHEMA",
    "TransportAttemptLedger",
    "TransportAttemptRecorder",
]
