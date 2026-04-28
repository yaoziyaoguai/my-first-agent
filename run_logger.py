"""Minimal run logger for LLM processing commands.

The run log is an audit stream, not a transcript store. In particular, it must
not write raw input text, prompts, completions, or file contents to
``runs/*.jsonl``.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LLM_CALL_ALLOWED_FIELDS = {
    "provider",
    "model",
    "prompt_version",
    "input_file_hash",
    "tokens",
    "latency",
    "status",
    "error",
}


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> str:
    return hash_bytes(path.read_bytes())


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class RunPaths:
    state_path: Path
    runs_dir: Path


class RunLogger:
    """Append-only JSONL audit logger for one process run."""

    def __init__(
        self,
        *,
        state_path: Path = Path("state.json"),
        runs_dir: Path = Path("runs"),
        run_id: str | None = None,
    ) -> None:
        self.paths = RunPaths(state_path=state_path, runs_dir=runs_dir)
        self.run_id = run_id or uuid.uuid4().hex
        self.paths.runs_dir.mkdir(parents=True, exist_ok=True)
        self._run_path = self.paths.runs_dir / f"{self.run_id}.jsonl"

    @property
    def run_path(self) -> Path:
        return self._run_path

    def log_event(self, event: str, payload: dict[str, Any] | None = None) -> None:
        record = {
            "ts_ms": _now_ms(),
            "run_id": self.run_id,
            "event": event,
            "payload": payload or {},
        }
        with self._run_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def log_llm_call(self, payload: dict[str, Any]) -> None:
        allowed_payload = {
            key: payload.get(key)
            for key in sorted(LLM_CALL_ALLOWED_FIELDS)
            if key in payload
        }
        missing = LLM_CALL_ALLOWED_FIELDS - set(allowed_payload)
        for key in sorted(missing):
            allowed_payload[key] = None
        self.log_event("llm_call", allowed_payload)

    def write_state(self, state: dict[str, Any]) -> None:
        state_payload = {
            "updated_ms": _now_ms(),
            "last_run_id": self.run_id,
            **state,
        }
        self.paths.state_path.write_text(
            json.dumps(state_payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
