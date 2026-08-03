"""Memory read path：budgeted ContextSource。

每次 ``snapshot`` 对当前 store records 做确定性 lexical 打分，返回 immutable candidates。
不构造 ``ContextPack``、不标 pinned/system、不调用 provider/tool/checkpoint。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from agent.memory.store import MemoryStore
from agent.runtime.contracts import (
    ContextCandidate,
    ContextQuery,
    ContextSourceSnapshot,
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
        candidates = tuple(item.candidate for item in scored if item.score > 0)
        digest = _snapshot_digest(self.name, self._store.revision, candidates)
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


def _snapshot_digest(source_name: str, revision: int, candidates) -> str:
    payload = {
        "source": source_name,
        "revision": revision,
        "candidates": [
            (candidate.candidate_id, candidate.content_digest) for candidate in candidates
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
