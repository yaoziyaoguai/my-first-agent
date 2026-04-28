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


STATUS_SCHEMA_VERSION = "llm.audit.status.v1"


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


def _run_id_from_path(path: Path) -> str:
    return path.stem


def _latest_run_file(runs_dir: Path) -> Path | None:
    if not runs_dir.exists() or not runs_dir.is_dir():
        return None
    files = [path for path in runs_dir.glob("*.jsonl") if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def _run_file_for_id(runs_dir: Path, run_id: str) -> Path:
    return runs_dir / f"{run_id}.jsonl"


def _is_safe_run_id(run_id: str) -> bool:
    """限制 run-id 为单个文件名，避免 status 读取 runs/ 目录之外的日志。"""

    return run_id not in {"", ".", ".."} and Path(run_id).name == run_id


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


def _summarize_run(
    *,
    run_path: Path,
    state: dict[str, Any] | None,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """把一个 run JSONL 压缩成稳定 schema，不暴露事件原始 payload。

    runs 字段面向脚本消费，只保留 run_id、状态、hash、路径、最新事件和 llm_call
    数量。即使 JSONL 里混入 raw_text/prompt/completion，也不会从这里透出。
    """

    llm_calls = _extract_llm_calls(records)
    state_run_path = state.get("run_path") if state else None
    state_matches = state_run_path == str(run_path)
    latest_event = records[-1]["event"] if records else None
    return {
        "run_id": state.get("last_run_id") if state_matches and state else _run_id_from_path(run_path),
        "status": state.get("status") if state_matches and state else None,
        "input_file_hash": state.get("input_file_hash") if state_matches and state else None,
        "run_path": str(run_path),
        "latest_event": latest_event,
        "llm_call_count": len(llm_calls),
    }


def build_status(
    *,
    state_path: Path = Path("state.json"),
    runs_dir: Path = Path("runs"),
    run_id: str | None = None,
) -> dict[str, Any]:
    """读取 state.json 和 runs/*.jsonl，返回用户可读状态摘要。

    status 是可脚本化审计 schema：默认展示 state 指向的最近 run；传入 run_id 时
    只读取 `runs/<run_id>.jsonl`。它必须容忍缺失 state、空 runs 和损坏 JSONL 行。
    输出只展示 llm_call 白名单字段和错误摘要，不展示 raw text、prompt 或 completion。
    """

    warnings: list[str] = []
    state, state_warning = read_json_file(state_path)
    if state_warning:
        warnings.append(state_warning)

    run_path: Path | None = None
    if run_id:
        if not _is_safe_run_id(run_id):
            warnings.append(f"run_id_invalid:{run_id}")
            run_path = None
        else:
            run_path = _run_file_for_id(runs_dir, run_id)
            if not run_path.exists():
                warnings.append(f"run_missing:{run_id}")
                run_path = None
    elif state and isinstance(state.get("run_path"), str):
        run_path = Path(state["run_path"])
    if run_path is None and not run_id:
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
    runs = (
        [_summarize_run(run_path=run_path, state=state, records=records)]
        if run_path is not None
        else []
    )
    latest_run = runs[0] if runs else {
        "run_id": run_id,
        "status": None,
        "input_file_hash": None,
        "run_path": None,
        "latest_event": None,
        "llm_call_count": 0,
    }
    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "query": {"run_id": run_id},
        "state_path": str(state_path),
        "runs_dir": str(runs_dir),
        "latest_run": latest_run,
        "runs": runs,
        "llm_calls": llm_calls,
        "errors": errors,
        "warnings": warnings,
        "allowed_llm_call_fields": sorted(LLM_CALL_ALLOWED_FIELDS),
    }
