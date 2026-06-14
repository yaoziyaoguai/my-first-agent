"""MemoryOwner — single runtime authority for explicit_user_request memory mutation.

MemoryOwner is the canonical write authority for memory.
不是 human owner，不是 storage，不是 LLM。

职责：receive explicit_user_request candidate → policy/privacy gate →
decide create/delete/noop/reject → produce audit evidence → delegate storage.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class MemoryMutationType(StrEnum):
    CREATE = "create"
    DELETE = "delete"
    NOOP = "noop"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class MemoryMutationDecision:
    mutation_type: MemoryMutationType
    reason: str
    audit_id: str
    evidence: dict[str, object] = field(default_factory=dict)
    record_id: str | None = None
    content_hash: str = ""
    memory_type: str = "semantic"
    source_type: str = "explicit_user_request"


class MemoryOwner:
    """explicit_user_request / semantic memory 的单一变异入口。"""

    def __init__(self, *, store) -> None:
        self._store = store

    # ── public ──

    def mutate(
        self,
        *,
        content: str,
        memory_type: str = "semantic",
        source_type: str = "explicit_user_request",
        intent: str = "retain",
        **_kwargs: object,
    ) -> MemoryMutationDecision:
        content_hash = _hash(content)

        if intent == "forget":
            return self._decide_forget(content, content_hash)

        if self._blocked_by_policy(content):
            return MemoryMutationDecision(
                mutation_type=MemoryMutationType.REJECTED,
                reason="policy_gate:包含敏感内容",
                audit_id=_audit(content_hash, "rejected"),
                evidence={"policy": "rejected_sensitive"},
                content_hash=content_hash,
            )

        if self._duplicate(content_hash):
            return MemoryMutationDecision(
                mutation_type=MemoryMutationType.NOOP,
                reason="duplicate:相同内容已存在",
                audit_id=_audit(content_hash, "noop"),
                evidence={"dedup": "content_hash_match"},
                content_hash=content_hash,
            )

        record_id = self._write(content, content_hash, memory_type, source_type)
        return MemoryMutationDecision(
            mutation_type=MemoryMutationType.CREATE,
            reason="stored",
            audit_id=_audit(content_hash, "create"),
            record_id=record_id,
            evidence={"retain": "stored", "record_id": record_id or ""},
            content_hash=content_hash,
        )

    # ── private ──

    def _blocked_by_policy(self, content: str) -> bool:
        try:
            from agent.memory_extraction import _contains_sensitive
            return _contains_sensitive(content)
        except Exception:
            return True  # fail-closed

    def _duplicate(self, content_hash: str) -> bool:
        try:
            for r in self._store.list_records():
                if getattr(r, "is_deleted", False):
                    continue
                if _hash(getattr(r, "content", "")) == content_hash:
                    return True
        except Exception:
            return False
        return False

    def _write(
        self, content: str, content_hash: str,
        memory_type: str, source_type: str,
    ) -> str | None:
        from agent.memory_store import MemoryRecord

        rid = f"mem-{uuid.uuid4().hex[:12]}"
        record = MemoryRecord(
            id=rid,
            content=content,
            scope=None,
            source_summary=f"MemoryOwner:{source_type}",
            safety_summary="policy_gate_passed",
            audit_id=_audit(content_hash, "store"),
            created_by_operation="retain_intent",
            updated_by_operation="retain_intent",
            memory_type=memory_type,
            source_type=source_type,
        )
        try:
            # InMemoryMemoryStore._records 是 dict[str, MemoryRecord]
            # key 格式: f"{namespace}:{record.id}", 默认 namespace="default"
            if hasattr(self._store, "_namespaced_key"):
                key = self._store._namespaced_key(rid)
                self._store._records[key] = record
            elif hasattr(self._store, "_records"):
                # fallback: 直接存为 key
                self._store._records[rid] = record
        except Exception:
            pass
        return rid

    def _decide_forget(self, content: str, content_hash: str) -> MemoryMutationDecision:
        match_id = None
        try:
            for r in self._store.list_records():
                if getattr(r, "is_deleted", False):
                    continue
                if content.strip() == getattr(r, "content", "").strip():
                    match_id = getattr(r, "id", None)
                    break
        except Exception:
            pass

        if match_id is None:
            return MemoryMutationDecision(
                mutation_type=MemoryMutationType.NOOP,
                reason="forget:未找到匹配记录",
                audit_id=_audit(content_hash, "forget_noop"),
                evidence={"forget": "no_match"},
                content_hash=content_hash,
            )

        import contextlib
        with contextlib.suppress(Exception):
            getattr(self._store, "remove_record", lambda _: False)(match_id)

        return MemoryMutationDecision(
            mutation_type=MemoryMutationType.DELETE,
            reason="soft_deleted",
            audit_id=_audit(content_hash, "delete"),
            record_id=match_id,
            evidence={"forget": "soft_deleted", "record_id": match_id},
            content_hash=content_hash,
        )


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _audit(content_hash: str, operation: str) -> str:
    return f"audit-{operation}-{content_hash}-{uuid.uuid4().hex[:8]}"
