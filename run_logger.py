"""Minimal run logger for LLM processing commands.

这个模块是 LLM Processing MVP 的审计边界，不是 transcript 存储。`runs/*.jsonl`
只能保存可审计 metadata，不能保存 raw input text、prompt、completion 或文件正文。
这样 scan/status 可以稳定复查运行过程，同时避免把用户输入内容复制到审计日志。
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


def sanitize_llm_call_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """只保留 llm_call 白名单字段，防止 raw text 从调用层漏进 JSONL。"""

    allowed_payload = {
        key: payload.get(key)
        for key in sorted(LLM_CALL_ALLOWED_FIELDS)
        if key in payload
    }
    missing = LLM_CALL_ALLOWED_FIELDS - set(allowed_payload)
    for key in sorted(missing):
        allowed_payload[key] = None
    return allowed_payload


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> str:
    return hash_bytes(path.read_bytes())


def read_json_file(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """读取 state.json；缺失或损坏都转成 warning，不让 status 命令崩溃。"""

    if not path.exists():
        return None, "state_missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, "state_invalid_json"
    if not isinstance(data, dict):
        return None, "state_not_object"
    return data, None


def read_jsonl_with_warnings(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """安全读取 runs/*.jsonl，跳过损坏行并返回 warning。

    status 是只读审计层：它要尽量展示可用证据，而不是因为一行坏 JSONL 让用户
    完全失去状态视图。这里也不尝试恢复 raw text，因为 raw text 本来就不应在日志里。
    """

    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    if not path.exists():
        return records, [f"run_log_missing:{path}"]
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            warnings.append(f"invalid_jsonl:{path}:{line_no}")
            continue
        if isinstance(record, dict):
            records.append(record)
        else:
            warnings.append(f"jsonl_not_object:{path}:{line_no}")
    return records, warnings


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
        self.log_event("llm_call", sanitize_llm_call_payload(payload))

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
