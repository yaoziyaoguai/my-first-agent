"""Secret-free HTTP attempt ledger for acceptance and operator diagnostics."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

TRANSPORT_ATTEMPT_SCHEMA = "first-agent/transport-attempt/v1"
TransportAttemptRecorder = Callable[[str, str], None]


@dataclass(frozen=True, slots=True)
class TransportAttemptLedger:
    """在 HTTP adapter 边界、发送前追加不含 payload/credential 的计数事实。"""

    path: Path

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
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            status = os.fstat(descriptor)
            if not stat.S_ISREG(status.st_mode):
                raise OSError("transport audit target must be a regular file")
            if status.st_uid != os.getuid() or status.st_mode & 0o077:
                raise OSError("transport audit target must be owner-only")
            written = os.write(descriptor, payload)
            if written != len(payload):
                raise OSError("transport audit append was incomplete")
        finally:
            os.close(descriptor)


__all__ = [
    "TRANSPORT_ATTEMPT_SCHEMA",
    "TransportAttemptLedger",
    "TransportAttemptRecorder",
]
