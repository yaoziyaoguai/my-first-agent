"""Canonical checkpoint 的 bounded、无索引 HistoryCatalog。"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

from agent.continuity.sessions import (
    WORKSPACE_HISTORY_CAPACITY,
    load_workspace_checkpoints,
)
from agent.history.contracts import (
    HistoryHit,
    HistoryOutcome,
    HistoryRecord,
    HistoryRecordKind,
    HistoryReferenceError,
    HistorySearchResult,
)
from agent.history.outcomes import project_outcome
from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.contracts import (
    ConversationFact,
    ConversationState,
    ConversationSummaryV1,
    ConversationWorkspaceBindingV1,
    FactKind,
    JSONValue,
    LoadedSnapshot,
    SourceKind,
    canonical_json_digest,
)
from agent.runtime.ports import ConversationArchive

_MAX_QUERY_CHARS = 256
_MAX_RESULTS = 5
_DEFAULT_ARCHIVE_READS_PER_SEARCH = 256
_MAX_PENDING_CONTINUATIONS = 32
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


@dataclass(frozen=True, slots=True)
class _CanonicalRoot:
    checkpoint_path: Path
    snapshot: LoadedSnapshot
    project_root: bool
    traverse_lineage: bool


@dataclass(frozen=True, slots=True)
class _RecordSource:
    conversation_id: str
    source_checkpoint_digest: str
    checkpoint_path: Path | None
    catalog_digest: str


@dataclass(frozen=True, slots=True)
class _LocatedMatch:
    score: int
    record: HistoryRecord
    source: _RecordSource


@dataclass(slots=True)
class _PagedSearch:
    query: str
    limit: int
    root_digest: str
    root_index: int
    newer_state: ConversationState | None
    next_digest: str | None
    top_matches: list[_LocatedMatch]
    total_matches: int
    match_counts: dict[str, int]
    first_signature: tuple[str, HistoryOutcome] | None
    cross_conversation: bool
    conflicting_content: bool


class HistoryCatalog:
    """只持有 startup 已确定的目录；工具参数不能改变读取根。"""

    def __init__(
        self,
        workspace_state_directory: Path,
        workspace_binding: ConversationWorkspaceBindingV1,
        *,
        max_history_checkpoints: int = WORKSPACE_HISTORY_CAPACITY,
        current_conversation_id: str | None = None,
        conversation_archive: ConversationArchive | None = None,
        max_archive_reads_per_search: int = _DEFAULT_ARCHIVE_READS_PER_SEARCH,
    ) -> None:
        if max_history_checkpoints < 1:
            raise ValueError("max_history_checkpoints must be positive")
        if max_archive_reads_per_search < 1:
            raise ValueError("max_archive_reads_per_search must be positive")
        if max_archive_reads_per_search > _DEFAULT_ARCHIVE_READS_PER_SEARCH:
            raise ValueError("max_archive_reads_per_search must not exceed 256")
        self._workspace_state_directory = Path(workspace_state_directory).absolute()
        self._binding = workspace_binding
        self._max_history_checkpoints = max_history_checkpoints
        self._current_conversation_id = current_conversation_id
        self._conversation_archive = conversation_archive
        self._max_archive_reads_per_search = max_archive_reads_per_search
        self._issued_refs: set[str] = set()
        self._issued_sources: dict[str, _RecordSource] = {}
        # continuation 会暂存累计 top-k 与遍历位置；上限与单次 turn 的默认
        # tool-call 量级一致，允许交错搜索但不形成无界内存状态。
        self._continuations: dict[str, _PagedSearch] = {}

    def snapshot_digest(self) -> str:
        if self._conversation_archive is not None:
            return self._canonical_roots()[1]
        return self._load_snapshot().digest

    def validate_search(
        self,
        query: str,
        limit: int,
        continuation: str | None = None,
    ) -> str:
        _validate_query(query, limit)
        if continuation is not None:
            _validate_continuation_shape(continuation)
            if self._conversation_archive is None:
                raise ValueError("history continuation is unavailable")
            pending = self._continuations.get(continuation)
            if pending is None:
                raise ValueError("history continuation was not issued by this catalog")
            if pending.query != query or pending.limit != limit:
                raise ValueError("history continuation does not match query and limit")
            root_digest = self._canonical_roots()[1]
            if pending.root_digest != root_digest:
                raise ValueError("history continuation is stale")
            return root_digest
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

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        continuation: str | None = None,
    ) -> HistorySearchResult:
        _validate_query(query, limit)
        if self._conversation_archive is not None:
            return self._search_archive_lineage(
                query,
                limit=limit,
                continuation=continuation,
            )
        if continuation is not None:
            raise ValueError("history continuation is unavailable")
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
            coverage_complete=True,
            continuation=None,
            excluded_legacy_unbound=snapshot.excluded_legacy_unbound,
            excluded_identity_mismatch=snapshot.excluded_identity_mismatch,
        )

    def _search_archive_lineage(
        self,
        query: str,
        *,
        limit: int,
        continuation: str | None,
    ) -> HistorySearchResult:
        roots, root_digest, excluded_unbound, excluded_identity = (
            self._canonical_roots()
        )
        if continuation is None:
            search = _PagedSearch(
                query=query,
                limit=limit,
                root_digest=root_digest,
                root_index=0,
                newer_state=None,
                next_digest=None,
                top_matches=[],
                total_matches=0,
                match_counts={},
                first_signature=None,
                cross_conversation=False,
                conflicting_content=False,
            )
            for root in roots:
                if root.project_root:
                    _accumulate_matches(
                        search,
                        _project_records(root.snapshot.state),
                        source=_RecordSource(
                            conversation_id=root.snapshot.state.conversation_id,
                            source_checkpoint_digest=root.snapshot.token,
                            checkpoint_path=root.checkpoint_path,
                            catalog_digest=root_digest,
                        ),
                    )
        else:
            _validate_continuation_shape(continuation)
            pending = self._continuations.get(continuation)
            if pending is None:
                raise ValueError("history continuation was not issued by this catalog")
            if pending.query != query or pending.limit != limit:
                raise ValueError("history continuation does not match query and limit")
            if pending.root_digest != root_digest:
                raise ValueError("history continuation is stale")
            # archive 读取失败时保留旧 cursor 的未修改状态，调用方可以安全重试。
            search = replace(
                pending,
                top_matches=list(pending.top_matches),
                match_counts=dict(pending.match_counts),
            )

        reads = 0
        while reads < self._max_archive_reads_per_search:
            _position_lineage(search, roots)
            if search.root_index >= len(roots):
                break
            assert search.newer_state is not None and search.next_digest is not None
            predecessor = self._conversation_archive.load_archived_by_identity(
                conversation_id=search.newer_state.conversation_id,
                workspace_scope_digest=self._binding.workspace_scope_digest,
                source_checkpoint_digest=search.next_digest,
            )
            _validate_lineage_predecessor(
                predecessor,
                newer=search.newer_state,
                expected_digest=search.next_digest,
                workspace_binding=self._binding,
            )
            _accumulate_matches(
                search,
                _lineage_delta_records(search.newer_state, predecessor.state),
                source=_RecordSource(
                    conversation_id=predecessor.state.conversation_id,
                    source_checkpoint_digest=predecessor.token,
                    checkpoint_path=None,
                    catalog_digest=root_digest,
                ),
            )
            search.newer_state = predecessor.state
            search.next_digest = _lineage_predecessor_digest(predecessor.state)
            reads += 1

        _position_lineage(search, roots)
        coverage_complete = search.root_index >= len(roots)
        if continuation is not None:
            self._continuations.pop(continuation, None)
        next_continuation = None
        if not coverage_complete:
            next_continuation = _continuation_token(search)
            self._continuations[next_continuation] = search
            while len(self._continuations) > _MAX_PENDING_CONTINUATIONS:
                oldest = next(iter(self._continuations))
                self._continuations.pop(oldest)
        conflicting_conversations = {
            conversation_id
            for conversation_id, count in search.match_counts.items()
            if count > 1
        }
        cross_conflict = search.cross_conversation and search.conflicting_content
        hits: list[HistoryHit] = []
        for match in search.top_matches:
            score, record = match.score, match.record
            excerpt, truncated = _clip(record.content, _SEARCH_EXCERPT_CHARS)
            hits.append(
                HistoryHit(
                    history_ref=self._mint_ref(record, source=match.source),
                    record=record,
                    excerpt=excerpt,
                    score=score,
                    conflict=(
                        record.conversation_id in conflicting_conversations
                        or cross_conflict
                    ),
                    truncated=truncated,
                )
            )
        return HistorySearchResult(
            snapshot_digest=root_digest,
            hits=tuple(hits),
            total_matches=search.total_matches,
            incomplete=(not coverage_complete or search.total_matches > len(hits)),
            coverage_complete=coverage_complete,
            continuation=next_continuation,
            excluded_legacy_unbound=excluded_unbound,
            excluded_identity_mismatch=excluded_identity,
        )

    def _canonical_roots(
        self,
    ) -> tuple[tuple[_CanonicalRoot, ...], str, int, int]:
        loaded = load_workspace_checkpoints(
            self._workspace_state_directory,
            max_history_checkpoints=self._max_history_checkpoints,
        )
        roots: list[_CanonicalRoot] = []
        commitments: list[dict[str, JSONValue]] = []
        excluded_unbound = 0
        excluded_identity = 0
        for path, snapshot in loaded:
            state = snapshot.state
            binding = state.workspace_binding
            is_current = state.conversation_id == self._current_conversation_id
            if binding is None:
                if is_current:
                    continue
                if state.goal is None:
                    excluded_unbound += 1
                    continue
                if (
                    state.goal.workspace_identity_digest
                    != self._binding.workspace_identity_digest
                ):
                    excluded_identity += 1
                    continue
                traverse_lineage = False
            elif (
                binding.workspace_scope_digest != self._binding.workspace_scope_digest
                or binding.workspace_identity_digest
                != self._binding.workspace_identity_digest
            ):
                excluded_identity += 1
                continue
            else:
                traverse_lineage = True
            lineage_head = (
                _lineage_predecessor_digest(state) if traverse_lineage else None
            )
            roots.append(
                _CanonicalRoot(
                    checkpoint_path=path,
                    snapshot=snapshot,
                    project_root=not is_current,
                    traverse_lineage=traverse_lineage,
                )
            )
            commitments.append(
                {
                    "conversation_id": state.conversation_id,
                    "checkpoint_digest": None if is_current else snapshot.token,
                    "lineage_head": lineage_head,
                }
            )
        digest = canonical_json_digest(
            {
                "version": "history-catalog-v2",
                "workspace_scope_digest": self._binding.workspace_scope_digest,
                "workspace_identity_digest": self._binding.workspace_identity_digest,
                "roots": commitments,
            }
        )
        return tuple(roots), digest, excluded_unbound, excluded_identity

    def get(self, history_ref: str) -> tuple[str, HistoryRecord, bool, str]:
        source = self._issued_sources.get(history_ref)
        if source is not None:
            record = self._load_issued_record(history_ref, source)
            content, truncated = _clip(record.content, _GET_CONTENT_CHARS)
            return content, record, truncated, _record_snapshot_digest(record)
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

    def _mint_ref(
        self,
        record: HistoryRecord,
        *,
        source: _RecordSource | None = None,
    ) -> str:
        value = (
            f"history-ref:v1:{record.record_id}:"
            f"{_record_snapshot_digest(record)}"
        )
        self._issued_refs.add(value)
        if source is not None:
            self._issued_sources[value] = source
        return value

    def _load_issued_record(
        self,
        history_ref: str,
        source: _RecordSource,
    ) -> HistoryRecord:
        record_id, expected_snapshot = self._parse_issued_ref(history_ref)
        if self._canonical_roots()[1] != source.catalog_digest:
            raise HistoryReferenceError("history ref is stale")
        if source.checkpoint_path is None:
            if self._conversation_archive is None:
                raise HistoryReferenceError("history archive source is unavailable")
            snapshot = self._conversation_archive.load_archived_by_identity(
                conversation_id=source.conversation_id,
                workspace_scope_digest=self._binding.workspace_scope_digest,
                source_checkpoint_digest=source.source_checkpoint_digest,
            )
        else:
            snapshot = LocalCheckpointStore(source.checkpoint_path).load()
            if snapshot.token != source.source_checkpoint_digest:
                raise HistoryReferenceError("history ref is stale")
        state = snapshot.state
        binding = state.workspace_binding
        if state.conversation_id != source.conversation_id:
            raise HistoryReferenceError("history source identity changed")
        if binding is None:
            goal = state.goal
            if (
                source.checkpoint_path is None
                or goal is None
                or goal.workspace_identity_digest
                != self._binding.workspace_identity_digest
            ):
                raise HistoryReferenceError("history source identity changed")
        elif (
            binding.workspace_scope_digest != self._binding.workspace_scope_digest
            or binding.workspace_identity_digest
            != self._binding.workspace_identity_digest
        ):
            raise HistoryReferenceError("history source identity changed")
        matches = tuple(
            record for record in _project_records(state) if record.record_id == record_id
        )
        if len(matches) != 1 or _record_snapshot_digest(matches[0]) != expected_snapshot:
            raise HistoryReferenceError("history ref is stale or no longer resolves exactly")
        return matches[0]

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


def _lineage_predecessor_digest(state: ConversationState) -> str | None:
    summaries = tuple(
        fact for fact in state.facts if fact.kind is FactKind.CONTEXT_SUMMARY
    )
    if not summaries:
        return None
    if len(summaries) != 1:
        raise ValueError("canonical archive lineage must have at most one summary")
    summary = ConversationSummaryV1.from_content(summaries[0].content)
    return f"sha256:{summary.source_checkpoint_digest}"


def _position_lineage(
    search: _PagedSearch,
    roots: tuple[_CanonicalRoot, ...],
) -> None:
    while search.root_index < len(roots):
        if search.newer_state is None:
            root = roots[search.root_index]
            search.newer_state = root.snapshot.state
            search.next_digest = (
                _lineage_predecessor_digest(search.newer_state)
                if root.traverse_lineage
                else None
            )
        if search.next_digest is not None:
            return
        search.root_index += 1
        search.newer_state = None


def _validate_lineage_predecessor(
    predecessor: LoadedSnapshot,
    *,
    newer: ConversationState,
    expected_digest: str,
    workspace_binding: ConversationWorkspaceBindingV1,
) -> None:
    state = predecessor.state
    if predecessor.token != expected_digest:
        raise ValueError("archive lineage adapter returned the wrong digest")
    if state.conversation_id != newer.conversation_id:
        raise ValueError("archive lineage changed conversation identity")
    binding = state.workspace_binding
    if (
        binding is None
        or binding.workspace_scope_digest != workspace_binding.workspace_scope_digest
        or binding.workspace_identity_digest
        != workspace_binding.workspace_identity_digest
    ):
        raise ValueError("archive lineage changed workspace identity")
    if state.revision >= newer.revision:
        raise ValueError("archive lineage revision must move strictly backward")


def _lineage_delta_records(
    newer: ConversationState,
    predecessor: ConversationState,
) -> tuple[HistoryRecord, ...]:
    newer_ids = {record.record_id for record in _project_records(newer)}
    return tuple(
        record
        for record in _project_records(predecessor)
        if record.record_id not in newer_ids
    )


def _match_sort_key(item: _LocatedMatch) -> tuple[object, ...]:
    score, record = item.score, item.record
    return (
        -score,
        -record.state_revision,
        -record.sequence,
        record.conversation_id,
        record.record_id,
    )


def _accumulate_matches(
    search: _PagedSearch,
    records: tuple[HistoryRecord, ...],
    *,
    source: _RecordSource,
) -> None:
    for record in records:
        score = _score(search.query, record)
        if score <= 0:
            continue
        if search.match_counts and record.conversation_id not in search.match_counts:
            search.cross_conversation = True
        search.match_counts[record.conversation_id] = (
            search.match_counts.get(record.conversation_id, 0) + 1
        )
        signature = (record.content_digest, record.outcome)
        if search.first_signature is None:
            search.first_signature = signature
        elif signature != search.first_signature:
            search.conflicting_content = True
        search.total_matches += 1
        search.top_matches.append(
            _LocatedMatch(score=score, record=record, source=source)
        )
        search.top_matches.sort(key=_match_sort_key)
        del search.top_matches[search.limit :]


def _continuation_token(search: _PagedSearch) -> str:
    digest = canonical_json_digest(
        {
            "version": "history-continuation-v1",
            "root_digest": search.root_digest,
            "query": search.query,
            "limit": search.limit,
            "root_index": search.root_index,
            "next_digest": search.next_digest,
            "total_matches": search.total_matches,
        }
    )
    return f"history-continuation:v1:{digest}"


def _project_records(state: ConversationState) -> tuple[HistoryRecord, ...]:
    outcome = project_outcome(state)
    records: list[HistoryRecord] = []
    for position, fact in enumerate(state.facts):
        # record identity 必须绑定 stable fact_id：compaction 会位移 fact 的
        # position，重叠 archive 中同一 fact 不得分裂成两个 record_id。
        projected = _project_fact(fact)
        if projected is None:
            continue
        kind, source_kind, title, content, observed_at = projected
        records.append(
            _record(
                state,
                suffix=f"fact:{fact.fact_id}",
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
                # 与 fact 同理：evidence_id 稳定，重叠 archive 去重依赖它。
                suffix=f"evidence:{evidence.evidence_id}",
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


def _validate_continuation_shape(continuation: str) -> None:
    if not isinstance(continuation, str) or re.fullmatch(
        r"history-continuation:v1:[0-9a-f]{64}", continuation
    ) is None:
        raise ValueError("history continuation has an invalid shape")


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
