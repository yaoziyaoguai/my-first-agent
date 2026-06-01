"""B7 Event Log Writer — per-session JSONL event log.

EventLogWriter 只写不读；redact 在写入前完成（不改变内存中的 RuntimeActionEvent）。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

# 脱敏正则
_KEY_REDACT_RE = re.compile(r"sk-[a-z]+(?:-[a-zA-Z0-9]+)*-[a-zA-Z0-9]{8,}")
_BEARER_REDACT_RE = re.compile(r"Bearer [a-zA-Z0-9_\-]{20,}")
# 长 token 字符串（base64-like, hex, 或随机字符串 >= 32 chars）
# 需要脱敏的字段名（大小写不敏感）
_SECRET_FIELD_PATTERNS = (
    "key", "token", "secret", "password", "authorization", "api_key",
    "credential", "private",
)
# 大写+下划线且包含 secret 关键词 — 典型的 env var 机密名
_ENV_VAR_SECRET_RE = re.compile(
    r"^(?:[A-Z][A-Z0-9_]*(?:SECRET|KEY|TOKEN|PASSWORD|CREDENTIAL|PRIVATE)[A-Z0-9_]*)$"
)

# 最大 payload 字符串长度
_MAX_STRING_LEN = 5000

SCHEMA_VERSION = "1.0"

_SOURCE_SUBSYSTEM_MAP: dict[str, str] = {
    "skill": "skill_system",
    "memory": "memory_kernel",
    "mcp": "mcp_bridge",
    "checkpoint": "checkpoint",
    "subagent": "subagent",
    "runtime": "runtime_integration",
    "dispatcher": "runtime_integration",
    "scheduler": "action_scheduler",
    "core": "core",
}


def _looks_like_secret_field(name: str) -> bool:
    """字段名是否看起来像 secret。"""
    lowered = name.lower()
    if any(pattern in lowered for pattern in _SECRET_FIELD_PATTERNS):
        return True
    # 大写+下划线且包含 secret 关键词（如 OPENAI_API_KEY）
    return bool(_ENV_VAR_SECRET_RE.match(name))


def _map_source_to_subsystem(source: str) -> str:
    """将 RuntimeActionEvent.source 映射为稳定的 source_subsystem。"""
    return _SOURCE_SUBSYSTEM_MAP.get(source, source or "unknown")


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
    result["redacted"] = redacted_fields
    return result


def _truncate_long_strings(obj: Any, max_len: int = _MAX_STRING_LEN) -> Any:
    """截断超过 max_len 的字符串值，防止 raw prompt/response 撑爆 event log。"""
    if isinstance(obj, dict):
        return {k: _truncate_long_strings(v, max_len) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_truncate_long_strings(item, max_len) for item in obj]
    if isinstance(obj, str) and len(obj) > max_len:
        return obj[:max_len] + f"...[TRUNCATED:{len(obj)}]"
    return obj


def _enrich_event(event: dict[str, Any]) -> dict[str, Any]:
    """为 event dict 添加 schema_version、event_type、source_subsystem、written_at。

    event_type 由 action_type 派生；source_subsystem 由 source 派生。
    """
    enriched = dict(event)
    enriched["schema_version"] = SCHEMA_VERSION
    enriched["event_type"] = event.get("action_type", "unknown")
    enriched["source_subsystem"] = _map_source_to_subsystem(
        event.get("source", "")
    )
    enriched["written_at"] = time.time()
    return enriched


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
        """Enrich → redact → truncate → 追加一行 JSON 到 events.jsonl。"""
        self._ensure_open()
        enriched = _enrich_event(event)
        redacted = _redact_event(enriched)
        bounded = _truncate_long_strings(redacted)
        line = json.dumps(bounded, ensure_ascii=False, separators=(",", ":"))
        assert "\n" not in line, "JSONL line must not contain literal newline"
        self._file.write(line + "\n")
        self._file.flush()

    def close(self) -> None:
        """关闭底层文件句柄。"""
        if self._file is not None:
            self._file.close()
            self._file = None
