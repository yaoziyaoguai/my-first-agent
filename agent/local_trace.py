"""Local-only observability trace foundation.

Stage 6 的目标是让本地 runtime 行为可以被结构化审计，但不能把 observability
做成新的 runtime brain。本模块只提供 trace event 数据模型和显式安全路径 JSONL
recorder：不读取真实 agent_log.jsonl、不扫描 sessions/runs、不连接 provider/network，
也不要求 core.py 立刻迁移成 tracing framework。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Literal


TraceSpanType = Literal[
    "model_call",
    "tool_call",
    "state_transition",
    "checkpoint",
    "memory_update",
    "subagent",
]
TraceStatus = Literal["ok", "failed", "cancelled", "skipped"]

_SECRET_KEY_PARTS = ("api_key", "apikey", "password", "secret", "token", "credential")
_SECRET_VALUE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
)
_REPO_RUNTIME_ARTIFACT_PARTS = {"sessions", "runs"}
_REPO_RUNTIME_ARTIFACT_NAMES = {"agent_log.jsonl"}


class TracePathPolicyError(ValueError):
    """trace recorder 拒绝写入真实 runtime artifact 或未授权路径。"""


def _is_secret_key(key: str) -> bool:
    lowered = key.replace("-", "_").lower()
    return any(part in lowered for part in _SECRET_KEY_PARTS)


def _redact_trace_value(value: Any, *, key: str | None = None) -> Any:
    """递归脱敏 trace metadata，不展开环境变量。

    key 命中 secret/token/password/api_key 时直接替换 value；普通字符串只按明显
    secret 值模式脱敏。这样 `$ANTHROPIC_API_KEY` 这类环境变量**名字**仍可用于排查
    “没有展开 env”的边界，而不会把真实 env value 写入 trace。
    """

    if key is not None and _is_secret_key(key):
        return "[REDACTED]"
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        redacted = value
        for pattern in _SECRET_VALUE_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted
    if isinstance(value, list):
        return [_redact_trace_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_trace_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(item_key): _redact_trace_value(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    return str(value)


def redact_trace_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """对 trace metadata 做统一脱敏，供 tests / future recorder 共用。"""

    return {
        str(key): _redact_trace_value(value, key=str(key))
        for key, value in metadata.items()
    }


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """单条 local trace 事件。

    这是 observability 数据模型，不是 Runtime state：它不进入 checkpoint、
    conversation.messages 或 Anthropic API messages。run_id/trace_id/span_id 让后续
    model/tool/state/checkpoint span 可以串联；metadata 只保存短字段并在输出前脱敏。
    """

    run_id: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    span_type: TraceSpanType
    name: str
    status: TraceStatus
    step_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    sequence: int = 0

    def __post_init__(self) -> None:
        for field_name in ("run_id", "trace_id", "span_id", "name"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} is required")

    def with_sequence(self, sequence: int) -> "TraceEvent":
        """返回带 recorder sequence 的副本，避免原 event 被 recorder mutate。"""

        return replace(self, sequence=sequence)

    def to_json_dict(self) -> dict[str, Any]:
        """生成确定性 JSON 友好的 dict，并在边界处脱敏 metadata。"""

        return {
            "sequence": self.sequence,
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "span_type": self.span_type,
            "name": self.name,
            "status": self.status,
            "step_id": self.step_id,
            "metadata": redact_trace_metadata(self.metadata),
        }


TraceEventSink = Callable[[TraceEvent], None]


def _is_within(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_trace_output_path(path: Path) -> Path:
    """只允许显式 tmp 路径，拒绝真实 runtime artifact 路径。

    早期 Stage 6 只需要 fake/local trace fixture。限制到 tmp_path 可以防止测试或
    dogfooding 把 trace 写到真实 `agent_log.jsonl` / `sessions` / `runs`。
    """

    raw_parts = set(path.parts)
    if path.name in _REPO_RUNTIME_ARTIFACT_NAMES:
        raise TracePathPolicyError(f"trace output path is reserved: {path}")
    if raw_parts & _REPO_RUNTIME_ARTIFACT_PARTS:
        raise TracePathPolicyError(f"trace output path is a runtime artifact path: {path}")

    resolved = path.expanduser().resolve()
    tmp_root = Path(tempfile.gettempdir()).resolve()
    if not _is_within(tmp_root, resolved):
        raise TracePathPolicyError(
            "local trace recorder only writes explicit temporary paths in this stage"
        )
    return resolved


class LocalTraceRecorder:
    """显式 safe path 的 JSONL trace recorder。

    recorder 只持有调用方显式传入的 TraceEvent，不主动读取 Runtime、sessions/runs
    或 agent_log.jsonl。未来 runtime wiring 可以在边界处构造 TraceEvent 后传入这里，
    但不应让 recorder 反向依赖 core.py。
    """

    def __init__(self, output_path: str | Path) -> None:
        self.output_path = _validate_trace_output_path(Path(output_path))
        self._events: list[TraceEvent] = []

    def record(self, event: TraceEvent) -> TraceEvent:
        """记录事件并返回带 sequence 的不可变副本。"""

        sequenced = event.with_sequence(len(self._events) + 1)
        self._events.append(sequenced)
        return sequenced

    def write_jsonl(self) -> None:
        """按记录顺序写 deterministic JSONL。"""

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(event.to_json_dict(), ensure_ascii=False, sort_keys=True)
            for event in self._events
        ]
        self.output_path.write_text(
            "".join(f"{line}\n" for line in lines),
            encoding="utf-8",
        )

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        """暴露不可变视图，避免测试或调用方直接 mutate recorder 内部列表。"""

        return tuple(self._events)
