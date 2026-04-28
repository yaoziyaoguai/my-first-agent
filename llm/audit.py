"""Read-only scan/status audit helpers for the LLM processing MVP.

scan/status 是 M3 的只读审计层：它们帮助用户确认哪些输入会被处理、最近运行
发生了什么，但不能把 raw text 正文复制进 state.json 或 runs/*.jsonl。scan 只读取
文件 bytes 来计算 hash 和 metadata；status 只读取已有 state/log metadata。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from run_logger import (
    LLM_CALL_ALLOWED_FIELDS,
    hash_file,
    read_json_file,
    read_jsonl_with_warnings,
    sanitize_llm_call_payload,
)


@dataclass(frozen=True)
class ScanEntry:
    path: str
    input_file_hash: str
    size: int
    mtime: float


def scan_inputs(target: Path) -> list[ScanEntry]:
    """扫描文件或目录，只返回 hash/mtime/size 等 metadata。

    这里不会读取 text 正文做持久化，也不会写 state/runs。hash 通过 bytes 计算，
    用来让 process/status 关联同一个输入文件，同时避免日志里出现正文。
    """

    target = target.resolve()
    if target.is_file():
        candidates = [target]
    elif target.is_dir():
        candidates = [path for path in sorted(target.rglob("*")) if path.is_file()]
    else:
        raise FileNotFoundError(str(target))

    entries: list[ScanEntry] = []
    for path in candidates:
        stat = path.stat()
        entries.append(
            ScanEntry(
                path=str(path),
                input_file_hash=hash_file(path),
                size=stat.st_size,
                mtime=stat.st_mtime,
            )
        )
    return entries


def _latest_run_file(runs_dir: Path) -> Path | None:
    if not runs_dir.exists() or not runs_dir.is_dir():
        return None
    files = [path for path in runs_dir.glob("*.jsonl") if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def _extract_llm_calls(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    llm_calls: list[dict[str, Any]] = []
    for record in records:
        if record.get("event") != "llm_call":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        llm_calls.append(sanitize_llm_call_payload(payload))
    return llm_calls


def build_status(
    *,
    state_path: Path = Path("state.json"),
    runs_dir: Path = Path("runs"),
) -> dict[str, Any]:
    """读取 state.json 和 runs/*.jsonl，返回用户可读状态摘要。

    status 必须容忍缺失 state、空 runs 和损坏 JSONL 行。它只展示 llm_call 白名单
    字段和错误摘要，不展示 raw text、prompt 或 completion。
    """

    warnings: list[str] = []
    state, state_warning = read_json_file(state_path)
    if state_warning:
        warnings.append(state_warning)

    run_path: Path | None = None
    if state and isinstance(state.get("run_path"), str):
        run_path = Path(state["run_path"])
    if run_path is None:
        run_path = _latest_run_file(runs_dir)
        if run_path is None:
            warnings.append("runs_missing_or_empty")

    records: list[dict[str, Any]] = []
    if run_path is not None:
        records, log_warnings = read_jsonl_with_warnings(run_path)
        warnings.extend(log_warnings)

    llm_calls = _extract_llm_calls(records)
    errors = [
        {
            "prompt_version": call.get("prompt_version"),
            "error": call.get("error"),
            "status": call.get("status"),
        }
        for call in llm_calls
        if call.get("status") != "ok" or call.get("error")
    ]
    latest_event = records[-1]["event"] if records else None
    latest_run = {
        "run_id": state.get("last_run_id") if state else None,
        "status": state.get("status") if state else None,
        "input_file_hash": state.get("input_file_hash") if state else None,
        "run_path": str(run_path) if run_path else None,
        "latest_event": latest_event,
    }
    return {
        "state_path": str(state_path),
        "runs_dir": str(runs_dir),
        "latest_run": latest_run,
        "llm_calls": llm_calls,
        "errors": errors,
        "warnings": warnings,
        "allowed_llm_call_fields": sorted(LLM_CALL_ALLOWED_FIELDS),
    }
