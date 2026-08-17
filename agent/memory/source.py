"""Memory read path：budgeted ContextSource。

每次 ``snapshot`` 对当前 store records 做确定性 lexical 打分，返回 immutable candidates。
不构造 ``ContextPack``、不标 pinned/system、不调用 provider/tool/checkpoint。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace

from agent.memory.store import MemoryStore
from agent.runtime.contracts import (
    ContextCandidate,
    ContextQuery,
    ContextSourceSnapshot,
    context_source_snapshot_digest,
)

_ASCII_RUN = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True, slots=True)
class _Scored:
    candidate: ContextCandidate
    score: int
    rank_key: str


class MemoryContextSource:
    name = "memory"

    def __init__(self, store: MemoryStore, *, source_name: str = "memory") -> None:
        self._store = store
        self.name = source_name

    def snapshot(self, query: ContextQuery) -> ContextSourceSnapshot:
        query_tokens = _unique_tokens(query.user_text)
        normalized_query = _normalize(query.user_text)
        scored: list[_Scored] = []
        for record in self._store.snapshot():
            if record.workspace_scope_digest != query.workspace_scope_digest:
                continue
            content = record.content
            content_tokens = set(_unique_tokens(content))
            matched = query_tokens & content_tokens
            score = 2 * len(matched)
            if normalized_query and normalized_query in _normalize(content):
                score += 1
            candidate = ContextCandidate(
                candidate_id=record.record_id,
                source_name=self.name,
                workspace_scope_digest=record.workspace_scope_digest,
                content=content,
                content_digest=record.content_digest,
                provenance={
                    "approved": True,
                    "updated_at": record.updated_at,
                    "source_fact_id": record.source_fact_id,
                    "origin": record.origin,
                    "admission_binding_digest": record.admission_binding_digest,
                },
                rank_key=f"{score:08d}:{record.record_id}",
            )
            scored.append(_Scored(candidate, score, rank_key=candidate.rank_key))
        # lexical score 降序、recency 降序、record ID 升序 tie-break。
        # store.snapshot 已按 recency 排序。
        scored.sort(
            key=lambda item: (
                -item.score,
                -float(item.candidate.provenance.get("updated_at", 0)),
                item.candidate.candidate_id,
            )
        )
        candidates = _bounded_candidates(
            tuple(item.candidate for item in scored if item.score > 0),
            max_items=query.source_limits.max_items,
            max_tokens=query.source_limits.max_tokens,
        )
        digest = context_source_snapshot_digest(
            self.name, self._store.revision, candidates
        )
        return ContextSourceSnapshot(
            source_name=self.name,
            revision=self._store.revision,
            snapshot_digest=digest,
            candidates=candidates,
        )


def _normalize(text: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKC", text).casefold()


def _unique_tokens(text: str) -> set[str]:
    if not text:
        return set()
    normalized = _normalize(text)
    tokens: set[str] = set()
    for match in _ASCII_RUN.findall(normalized):
        tokens.add(match)
    remainder = _ASCII_RUN.sub(" ", normalized)
    for chunk in remainder.split(" "):
        for char in chunk:
            if char.isalnum():
                tokens.add(char)
    tokens.discard("")
    return tokens


def _bounded_candidates(
    candidates: tuple[ContextCandidate, ...],
    *,
    max_items: int,
    max_tokens: int,
) -> tuple[ContextCandidate, ...]:
    remaining_chars = max_tokens * 4
    selected: list[ContextCandidate] = []
    for candidate in candidates[:max_items]:
        if remaining_chars <= 0:
            break
        content = candidate.content[:remaining_chars]
        remaining_chars -= len(content)
        if content != candidate.content:
            candidate = replace(
                candidate,
                content=content,
                content_digest=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                provenance={
                    **candidate.provenance,
                    "original_content_digest": candidate.content_digest,
                    "truncated": True,
                    "truncation_reason": "context_source_token_limit",
                },
            )
        selected.append(candidate)
    return tuple(selected)
