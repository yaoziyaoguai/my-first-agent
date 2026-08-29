"""Private protocol fixture for the real POSIX supervisor tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

from agent.automation.child import decode_occurrence_spec_frame


def _send(value: dict[str, object]) -> None:
    sys.stdout.buffer.write(
        (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )
    sys.stdout.buffer.flush()


def _descendant() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def main() -> int:
    mode = sys.argv[1]
    if mode == "exit-before-ready":
        return 23
    if mode == "no-ready":
        time.sleep(30)
        return 24

    spec = decode_occurrence_spec_frame(sys.stdin.buffer.readline())
    descendant = None
    if mode in {"success-with-descendant", "hang-after-start"}:
        descendant = _descendant()
    _send(
        {
            "type": "ready",
            "leader_pid": os.getpid(),
            "process_group_id": os.getpgrp(),
            "descendant_pid": None if descendant is None else descendant.pid,
        }
    )
    permit = json.loads(sys.stdin.buffer.readline())
    if mode == "no-start-ack":
        time.sleep(30)
        return 25
    _send(
        {
            "type": "started",
            "process_identity_digest": permit["process_identity_digest"],
            "permit": permit["permit"],
        }
    )
    execution_permit = json.loads(sys.stdin.buffer.readline())
    if execution_permit != {
        "type": "execute",
        "process_identity_digest": permit["process_identity_digest"],
        "permit": permit["permit"],
    }:
        return 27
    if mode == "hang-after-start":
        time.sleep(30)
        return 26
    if mode == "partial-result-after-execute":
        sys.stdout.buffer.write(b'{"type":"result"')
        sys.stdout.buffer.flush()
        return 28
    if mode == "malformed-result-after-execute":
        _send({"type": "result", "result": {}})
        return 29
    _send(
        {
            "type": "result",
            "result": {
                "status": "completed",
                "checkpoint_identity_digest": spec.prepared.checkpoint_identity_digest,
                "result_digest": "9" * 64,
                "replayed": False,
                "error_code": None,
                "artifacts": [],
            },
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
