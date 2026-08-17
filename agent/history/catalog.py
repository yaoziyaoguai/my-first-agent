"""Canonical checkpoint 的 bounded、无索引 HistoryCatalog。"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from agent.continuity.sessions import (
    WORKSPACE_HISTORY_CAPACITY,
    load_workspace_checkpoints,
)
from agent.history.contracts import (
    HistoryHit,
    HistoryRecord,
    HistoryRecordKind,
    HistoryReferenceError,
    HistorySearchResult,
)
from agent.history.outcomes import project_outcome
from agent.runtime.contracts import (
    ConversationFact,
    ConversationState,
    ConversationWorkspaceBindingV1,
    FactKind,
    JSONValue,
    SourceKind,
    canonical_json_digest,
)

_MAX_QUERY_CHARS = 256
_MAX_RESULTS = 5
_SEARCH_EXCERPT_CHARS = 700
_GET_CONTENT_CHARS = 4_000
_WORD = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_SEARCH_STOP_WORDS = {
    "a",
    "an",
    "are",
    "be",
    "boundary",
    "decision",
    "decisions",
    "find",
    "for",
    "how",
    "is",
    "may",
    "only",
    "output",
    "outputs",
    "previous",
    "previously",
    "settled",
    "store",
    "stored",
    "the",
    "using",
    "verified",
    "was",
    "were",
    "what",
    "when",
    "where",
    "why",
    "决定",
}


@dataclass(frozen=True, slots=True)
class _Snapshot:
    digest: str
    records: tuple[HistoryRecord, ...]
    excluded_legacy_unbound: int
    excluded_identity_mismatch: int


class HistoryCatalog:
    """只持有 startup 已确定的目录；工具参数不能改变读取根。"""

    def __init__(
        self,
        workspace_state_directory: Path,
        workspace_binding: ConversationWorkspaceBindingV1,
        *,
        max_history_checkpoints: int = WORKSPACE_HISTORY_CAPACITY,
        current_conversation_id: str | None = None,
    ) -> None:
        if max_history_checkpoints < 1:
            raise ValueError("max_history_checkpoints must be positive")
        self._workspace_state_directory = Path(workspace_state_directory).absolute()
        self._binding = workspace_binding
        self._max_history_checkpoints = max_history_checkpoints
        self._current_conversation_id = current_conversation_id
        self._issued_refs: set[str] = set()

    def snapshot_digest(self) -> str:
        return self._load_snapshot().digest

    def validate_search(self, query: str, limit: int) -> str:
        _validate_query(query, limit)
        return self._binding.binding_digest

    def bind_ref(self, history_ref: str) -> str:
        """为 prepare 绑定本 catalog 已签发的 ref，不扫描 checkpoint。"""

        self._parse_issued_ref(history_ref)
        return canonical_json_digest(
            {
                "version": "history-ref-binding-v1",
                "workspace_binding_digest": self._binding.binding_digest,
                "history_ref": history_ref,
            }
        )

    def search(self, query: str, *, limit: int = 5) -> HistorySearchResult:
        _validate_query(query, limit)
        snapshot = self._load_snapshot()
        scored = [
            (score, record)
            for record in snapshot.records
            if (score := _score(query, record)) > 0
        ]
        scored.sort(
            key=lambda item: (
                -item[0],
                -item[1].state_revision,
                -item[1].sequence,
                item[1].conversation_id,
                item[1].record_id,
            )
        )
        selected = scored[:limit]
        match_counts: dict[str, int] = {}
        for _score_value, record in scored:
            match_counts[record.conversation_id] = (
                match_counts.get(record.conversation_id, 0) + 1
            )
        conflicting_conversations = {
            conversation_id
            for conversation_id, count in match_counts.items()
            if count > 1
        }
        cross_conversation_conflict = (
            len({record.conversation_id for _score_value, record in scored}) > 1
            and len(
                {
                    (record.content_digest, record.outcome)
                    for _score_value, record in scored
                }
            )
            > 1
        )
        hits: list[HistoryHit] = []
        for score, record in selected:
            history_ref = self._mint_ref(record)
            excerpt, truncated = _clip(record.content, _SEARCH_EXCERPT_CHARS)
            hits.append(
                HistoryHit(
                    history_ref=history_ref,
                    record=record,
                    excerpt=excerpt,
                    score=score,
                    conflict=(
                        record.conversation_id in conflicting_conversations
                        or cross_conversation_conflict
                    ),
                    truncated=truncated,
                )
            )
        return HistorySearchResult(
            snapshot_digest=snapshot.digest,
            hits=tuple(hits),
            total_matches=len(scored),
            incomplete=len(scored) > len(selected),
            excluded_legacy_unbound=snapshot.excluded_legacy_unbound,
            excluded_identity_mismatch=snapshot.excluded_identity_mismatch,
        )

    def get(self, history_ref: str) -> tuple[str, HistoryRecord, bool, str]:
        snapshot = self._load_snapshot()
        record = self._resolve_ref(snapshot, history_ref)
        content, truncated = _clip(record.content, _GET_CONTENT_CHARS)
        return content, record, truncated, _record_snapshot_digest(record)

    def _load_snapshot(self) -> _Snapshot:
        loaded = load_workspace_checkpoints(
            self._workspace_state_directory,
            max_history_checkpoints=self._max_history_checkpoints,
        )
        eligible: list[tuple[str, ConversationState]] = []
        excluded_unbound = 0
        excluded_identity = 0
        snapshot_items: list[dict[str, JSONValue]] = []
        for _path, snapshot in loaded:
            state = snapshot.state
            # 当前 conversation 已由 ContextManager 直接投影；把它再次作为
            # history source 会让本轮用户问题检索命中自己并伪装成旧证据。
            if state.conversation_id == self._current_conversation_id:
                continue
            binding = state.workspace_binding
            if binding is None:
                if state.goal is None:
                    excluded_unbound += 1
                    continue
                if (
                    state.goal.workspace_identity_digest
                    != self._binding.workspace_identity_digest
                ):
                    excluded_identity += 1
                    continue
            elif (
                binding.workspace_scope_digest != self._binding.workspace_scope_digest
                or binding.workspace_identity_digest
                != self._binding.workspace_identity_digest
            ):
                excluded_identity += 1
                continue
            eligible.append((snapshot.token, state))
            snapshot_items.append(
                {
                    "conversation_id": state.conversation_id,
                    "revision": state.revision,
                    "checkpoint_digest": snapshot.token,
                }
            )
        digest = canonical_json_digest(
            {
                "version": "history-catalog-v1",
                "workspace_scope_digest": self._binding.workspace_scope_digest,
                "workspace_identity_digest": self._binding.workspace_identity_digest,
                "checkpoints": snapshot_items,
            }
        )
        records = tuple(
            record
            for _token, state in eligible
            for record in _project_records(state)
        )
        return _Snapshot(
            digest=digest,
            records=records,
            excluded_legacy_unbound=excluded_unbound,
            excluded_identity_mismatch=excluded_identity,
        )

    def _mint_ref(self, record: HistoryRecord) -> str:
        value = (
            f"history-ref:v1:{record.record_id}:"
            f"{_record_snapshot_digest(record)}"
        )
        self._issued_refs.add(value)
        return value

    def _resolve_ref(self, snapshot: _Snapshot, history_ref: str) -> HistoryRecord:
        record_id, expected_snapshot = self._parse_issued_ref(history_ref)
        matches = tuple(record for record in snapshot.records if record.record_id == record_id)
        if len(matches) != 1:
            raise HistoryReferenceError("history ref is stale or no longer resolves exactly")
        if _record_snapshot_digest(matches[0]) != expected_snapshot:
            raise HistoryReferenceError("history ref is stale")
        return matches[0]

    def _parse_issued_ref(self, history_ref: str) -> tuple[str, str]:
        if history_ref not in self._issued_refs:
            raise HistoryReferenceError("history ref was not issued by this catalog")
        parts = history_ref.split(":")
        if (
            len(parts) != 6
            or parts[:4] != ["history-ref", "v1", "record", "v1"]
            or re.fullmatch(r"[0-9a-f]{64}", parts[4]) is None
            or re.fullmatch(r"[0-9a-f]{64}", parts[5]) is None
        ):
            raise HistoryReferenceError("history ref has an invalid shape")
        record_id = ":".join(parts[2:5])
        expected_snapshot = parts[5]
        return record_id, expected_snapshot


def _project_records(state: ConversationState) -> tuple[HistoryRecord, ...]:
    outcome = project_outcome(state)
    records: list[HistoryRecord] = []
    for position, fact in enumerate(state.facts):
        projected = _project_fact(fact)
        if projected is None:
            continue
        kind, source_kind, title, content, observed_at = projected
        records.append(
            _record(
                state,
                suffix=f"fact:{position}",
                source_kind=source_kind,
                record_kind=kind,
                sequence=position,
                observed_at=observed_at,
                title=title,
                content=content,
                outcome=outcome,
            )
        )
    goal = state.goal
    if goal is not None:
        blocker = next(
            (
                fact.content
                for fact in reversed(state.facts)
                if fact.kind is FactKind.POLICY_RESULT
                and fact.content.get("code") == "blocked_claim"
            ),
            None,
        )
        content: dict[str, JSONValue] = {
            "user_outcome": goal.user_outcome,
            "targets": list(goal.targets),
            "status": goal.status.value,
            "progress_summary": goal.progress_summary,
            "next_step": goal.next_step,
            "outcome": outcome.value,
        }
        if blocker is not None:
            content["blocker"] = blocker.get("blocker")
            content["resume_condition"] = blocker.get("resume_condition")
        records.append(
            _record(
                state,
                suffix="goal",
                source_kind=SourceKind.HISTORY_GOAL,
                record_kind=HistoryRecordKind.GOAL,
                sequence=len(state.facts),
                observed_at=goal.updated_at,
                title=goal.user_outcome,
                content=_json(content),
                outcome=outcome,
            )
        )
    for index, evidence in enumerate(state.evidence_records):
        content = _json(
            {
                "evidence_ref": _opaque("evidence", evidence.evidence_id),
                "criterion_id": evidence.criterion_id,
                "oracle_kind": evidence.oracle_kind.value,
                "passed": evidence.passed,
                "outcome": outcome.value,
            }
        )
        records.append(
            _record(
                state,
                suffix=f"evidence:{index}",
                source_kind=SourceKind.HISTORY_EVIDENCE,
                record_kind=HistoryRecordKind.EVIDENCE,
                sequence=len(state.facts) + index + 1,
                observed_at=evidence.observed_at,
                title=f"Evidence for {evidence.criterion_id}",
                content=content,
                outcome=outcome,
            )
        )
    return tuple(records)


def _project_fact(
    fact: ConversationFact,
) -> tuple[HistoryRecordKind, SourceKind, str, str, str] | None:
    if fact.kind in {FactKind.USER_MESSAGE, FactKind.ASSISTANT_MESSAGE}:
        text = fact.content.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        kind = (
            HistoryRecordKind.USER_EXCERPT
            if fact.kind is FactKind.USER_MESSAGE
            else HistoryRecordKind.ASSISTANT_PROSE
        )
        title = "User statement" if fact.kind is FactKind.USER_MESSAGE else "Assistant prose"
        return kind, SourceKind.HISTORY_EXCERPT, title, text, "unknown"
    if fact.kind is FactKind.TOOL_RESULT:
        text = fact.content.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        metadata = fact.content.get("metadata")
        code = metadata.get("code") if isinstance(metadata, dict) else None
        content = _json(
            {
                "summary": text,
                "is_error": fact.content.get("is_error") is True,
                "executed": fact.content.get("executed") is not False,
                "code": code if isinstance(code, str) else None,
            }
        )
        return (
            HistoryRecordKind.TOOL_OUTCOME,
            SourceKind.HISTORY_EVIDENCE,
            "Tool outcome",
            content,
            "unknown",
        )
    if fact.kind is FactKind.POLICY_RESULT and fact.content.get("code") == "blocked_claim":
        content = _json(
            {
                "blocker": fact.content.get("blocker"),
                "resume_condition": fact.content.get("resume_condition"),
            }
        )
        return (
            HistoryRecordKind.BLOCKER,
            SourceKind.HISTORY_GOAL,
            "Blocked task",
            content,
            "unknown",
        )
    return None


def _record(
    state: ConversationState,
    *,
    suffix: str,
    source_kind: SourceKind,
    record_kind: HistoryRecordKind,
    sequence: int,
    observed_at: str,
    title: str,
    content: str,
    outcome,
) -> HistoryRecord:
    content_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    record_id = _opaque(
        "record",
        f"{state.conversation_id}:{suffix}:{content_digest}",
    )
    return HistoryRecord(
        record_id=record_id,
        source_kind=source_kind,
        record_kind=record_kind,
        conversation_id=state.conversation_id,
        state_revision=state.revision,
        sequence=sequence,
        observed_at=observed_at,
        title=title,
        content=content,
        content_digest=content_digest,
        outcome=outcome,
    )


def _validate_query(query: str, limit: int) -> None:
    if not isinstance(query, str) or not query.strip() or len(query) > _MAX_QUERY_CHARS:
        raise ValueError("history query must be non-empty and bounded")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= _MAX_RESULTS:
        raise ValueError("history result limit must be between 1 and 5")


def _score(query: str, record: HistoryRecord) -> int:
    normalized_query = _normalize(query)
    normalized_title = _normalize(record.title)
    normalized_content = _normalize(record.content)
    score = 0
    exact_match = normalized_query in normalized_title or normalized_query in normalized_content
    if normalized_query in normalized_title:
        score += 120
    if normalized_query in normalized_content:
        score += 90
    tokens = _tokens(normalized_query)
    matched = 0
    for token in tokens:
        in_title = token in normalized_title
        in_content = token in normalized_content
        if in_title or in_content:
            matched += 1
        if in_title:
            score += 12
        if in_content:
            score += 8
    if score == 0 or (not exact_match and matched * 4 < len(tokens)):
        return 0
    if record.record_kind is HistoryRecordKind.USER_EXCERPT:
        score += 4
    elif record.record_kind is HistoryRecordKind.GOAL:
        score += 3
    return score


def _tokens(value: str) -> tuple[str, ...]:
    tokens = {
        token
        for token in _WORD.findall(value)
        if token not in _SEARCH_STOP_WORDS
    }
    cjk = "".join(_CJK.findall(value))
    tokens.update(
        token
        for index in range(max(0, len(cjk) - 1))
        if (token := cjk[index : index + 2]) not in _SEARCH_STOP_WORDS
    )
    return tuple(sorted(token for token in tokens if token))


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _clip(content: str, limit: int) -> tuple[str, bool]:
    if len(content) <= limit:
        return content, False
    return content[:limit], True


def _opaque(kind: str, value: str) -> str:
    return f"{kind}:v1:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _record_snapshot_digest(record: HistoryRecord) -> str:
    return canonical_json_digest(
        {
            "record_id": record.record_id,
            "source_kind": record.source_kind.value,
            "record_kind": record.record_kind.value,
            "conversation_id": record.conversation_id,
            "state_revision": record.state_revision,
            "sequence": record.sequence,
            "observed_at": record.observed_at,
            "title": record.title,
            "content_digest": record.content_digest,
            "outcome": record.outcome.value,
        }
    )


def _json(value: dict[str, JSONValue]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
