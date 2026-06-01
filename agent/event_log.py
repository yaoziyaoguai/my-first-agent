"""B7 Event Log Writer — per-session JSONL event log.

EventLogWriter 只写不读；redact 在写入前完成（不改变内存中的 RuntimeActionEvent）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# 复用 agent/logger.py 中的脱敏正则（同一来源，不重复定义）
_KEY_REDACT_RE = re.compile(r"sk-[a-z]+(?:-[a-zA-Z0-9]+)*-[a-zA-Z0-9]{8,}")
_BEARER_REDACT_RE = re.compile(r"Bearer [a-zA-Z0-9_\-]{20,}")

# 需要脱敏的字段名（大小写不敏感）
_SECRET_FIELD_PATTERNS = ("key", "token", "secret", "password", "authorization", "api_key")


def _looks_like_secret_field(name: str) -> bool:
    """字段名是否看起来像 secret。"""
    lowered = name.lower()
    return any(pattern in lowered for pattern in _SECRET_FIELD_PATTERNS)


def _redact_value(value: str) -> str:
    """对单个字符串值脱敏。"""
    if not isinstance(value, str):
        return value
    value = _KEY_REDACT_RE.sub("<REDACTED>", value)
    value = _BEARER_REDACT_RE.sub("Bearer <REDACTED>", value)
    return value


def _redact_event(event: dict[str, Any]) -> dict[str, Any]:
    """DFS 遍历 event dict，脱敏 secret 字段和值中的敏感模式。

    返回新 dict（不改变传入的 event），并附加 "redacted" 字段记录被脱敏的字段路径。
    """
    redacted_fields: list[str] = []

    def _walk(obj: Any, path: str = "") -> Any:
        if isinstance(obj, dict):
            result: dict[str, Any] = {}
            for k, v in obj.items():
                child_path = f"{path}.{k}" if path else k
                if isinstance(v, str) and _looks_like_secret_field(k):
                    redacted_fields.append(child_path)
                    result[k] = "<REDACTED>"
                elif isinstance(v, str):
                    redacted = _redact_value(v)
                    if redacted != v:
                        redacted_fields.append(child_path)
                    result[k] = redacted
                else:
                    result[k] = _walk(v, child_path)
            return result
        if isinstance(obj, list):
            return [_walk(item, f"{path}[{i}]") for i, item in enumerate(obj)]
        if isinstance(obj, str):
            return _redact_value(obj)
        return obj

    result = _walk(event)
    # 始终在顶层附加
    result["redacted"] = redacted_fields
    return result


class EventLogWriter:
    """Per-session JSONL event log writer。

    只写不读；redact 在 append 时完成，不影响内存中的 RuntimeActionEvent。
    """

    def __init__(self, session_dir: Path) -> None:
        self._session_dir = session_dir
        self._file = None

    def _ensure_open(self) -> None:
        if self._file is not None:
            return
        self._session_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._session_dir / "events.jsonl"
        self._file = open(log_path, "a", encoding="utf-8")  # noqa: SIM115

    def append(self, event: dict[str, Any]) -> None:
        """Redact 并追加一行 JSON 到 events.jsonl。"""
        self._ensure_open()
        redacted = _redact_event(event)
        line = json.dumps(redacted, ensure_ascii=False, separators=(",", ":"))
        assert "\n" not in line, "JSONL line must not contain literal newline"
        self._file.write(line + "\n")
        self._file.flush()

    def close(self) -> None:
        """关闭底层文件句柄。"""
        if self._file is not None:
            self._file.close()
            self._file = None
