"""HistoryCatalog 的封闭投影合同。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agent.runtime.contracts import SourceKind


class HistoryOutcome(StrEnum):
    USER_CONFIRMED_ACCEPTANCE = "user_confirmed_acceptance"
    VERIFIED_DELIVERY = "verified_delivery"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    FAILED = "failed"
    ACCEPTANCE_UNKNOWN = "acceptance_unknown"


class HistoryRecordKind(StrEnum):
    USER_EXCERPT = "user_excerpt"
    ASSISTANT_PROSE = "assistant_prose"
    GOAL = "goal"
    EVIDENCE = "evidence"
    TOOL_OUTCOME = "tool_outcome"
    BLOCKER = "blocker"


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    record_id: str
    source_kind: SourceKind
    record_kind: HistoryRecordKind
    conversation_id: str
    state_revision: int
    sequence: int
    observed_at: str
    title: str
    content: str
    content_digest: str
    outcome: HistoryOutcome


@dataclass(frozen=True, slots=True)
class HistoryHit:
    history_ref: str
    record: HistoryRecord
    excerpt: str
    score: int
    conflict: bool
    truncated: bool


@dataclass(frozen=True, slots=True)
class HistorySearchResult:
    snapshot_digest: str
    hits: tuple[HistoryHit, ...]
    total_matches: int
    incomplete: bool
    excluded_legacy_unbound: int
    excluded_identity_mismatch: int


class HistoryReferenceError(ValueError):
    """History ref 不是本 catalog 本轮签发，或已因 checkpoint 变化而过期。"""
