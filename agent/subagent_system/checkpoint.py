"""SubAgent checkpoint-safe summary.

Formal SubAgent 不改变全局 checkpoint schema。这里仅定义可以嵌入/投影到
checkpoint 的小型关联摘要，并提供 secret/large artifact safety check。
"""

from __future__ import annotations

from dataclasses import dataclass
import re


_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)
_MAX_SAFE_VALUE_CHARS = 50_000


@dataclass(frozen=True)
class SubAgentCheckpointSummary:
    """Checkpoint-safe delegation summary. No raw prompt / transcript / secrets."""

    delegation_id: str
    subagent_name: str
    status: str
    execution_mode: str
    iterations_used: int
    max_iterations: int
    parent_trace_id: str
    pending_confirmation: tuple[str, ...]
    stop_reason: str
    revision_count: int

    @property
    def should_replay_tools(self) -> bool:
        """Resume must re-adjudicate pending effects, never replay tools."""

        return False


def is_checkpoint_safe(data: object) -> bool:
    """Return False if data contains likely secrets or large raw artifacts."""

    if isinstance(data, str):
        return len(data) < _MAX_SAFE_VALUE_CHARS and not any(
            pattern.search(data) for pattern in _SECRET_PATTERNS
        )
    if isinstance(data, dict):
        return all(is_checkpoint_safe(key) and is_checkpoint_safe(value) for key, value in data.items())
    if isinstance(data, (list, tuple, set)):
        return all(is_checkpoint_safe(item) for item in data)
    return True

