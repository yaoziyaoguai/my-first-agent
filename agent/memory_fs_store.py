"""Filesystem-native MemoryStore.

Phase 4 minimal implementation — 只实现 spike 已验证过的部分：
  - grouped topic markdown files with YAML frontmatter
  - index rebuild on session start, write-through on mutation
  - scope / recency / memory_type recall
  - MemoryStoreProtocol 兼容 (drop-in replacement for InMemoryMemoryStore)

不实现：decay, consolidation, archival, L2/L3, semantic search, vector DB.

架构边界：
  - .md 文件是 source of truth
  - _meta/index.json 是 derived cache
  - 单用户单进程，无并发锁
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from agent.memory_contracts import MemoryScope
from agent.memory_operations import (
    MemoryAuditSummary,
    MemoryOperationIntent,
    MemoryOperationType,
)
from agent.memory_store import (
    MUTATING_OPERATION_TYPES,
    NON_WRITING_OPERATION_TYPES,
    MemoryRecord,
    MemoryStoreApplyResult,
    MemoryStoreApplyStatus,
    derive_memory_record_id,
    _validate_apply_inputs,
)

# ── topic routing ──────────────────────────────────────────────────────────

DEFAULT_TOPIC_FILES = {
    ("semantic", MemoryScope.USER): "semantic/user_preferences.md",
    ("semantic", MemoryScope.PROJECT): "semantic/project_rules.md",
    ("semantic", MemoryScope.REPO): "semantic/repo_conventions.md",
    ("procedural", MemoryScope.USER): "procedural/learned.md",
    ("procedural", MemoryScope.PROJECT): "procedural/learned.md",
}


def _route_topic(memory_type: str, scope: MemoryScope) -> str:
    """Route memory to grouped topic file path (relative to store root)."""
    key = (memory_type, scope)
    if key in DEFAULT_TOPIC_FILES:
        return DEFAULT_TOPIC_FILES[key]
    if memory_type == "episodic":
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"episodic/{today}.md"
    # fallback
    scope_dir = scope.value if scope else "session"
    return f"{scope_dir}/general.md"


# ── frontmatter parser (stdlib only, no pyyaml) ─────────────────────────────

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse --- key: value --- content from markdown text.

    Returns (metadata_dict, body_text). If no valid frontmatter,
    returns ({}, full_text).
    """
    text = text.strip()
    if not text.startswith("---"):
        return {}, text

    # Find closing ---
    lines = text.split("\n")
    if len(lines) < 2:
        return {}, text

    # Skip opening ---
    header_lines = []
    body_start = 1
    found_closing = False
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            body_start = i + 1
            found_closing = True
            break
        header_lines.append(lines[i])

    if not found_closing:
        return {}, text

    body = "\n".join(lines[body_start:]).strip()
    meta: dict = {}
    for line in header_lines:
        line = line.strip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        # unquote
        val = val.strip('"').strip("'")
        # parse bool
        if val.lower() in ("true", "false"):
            val = val.lower() == "true"
        # parse number
        elif val.replace(".", "").replace("-", "").replace("e", "").replace("+", "").isdigit():
            try:
                val = float(val) if "." in val or "e" in val.lower() else int(val)
            except ValueError:
                pass
        meta[key] = val
    return meta, body


def parse_memory_file(filepath: Path) -> list[dict]:
    """Parse a .md file with potentially multiple --- separated sections.

    Returns list of {meta_fields..., _content: str} dicts.
    """
    text = filepath.read_text(encoding="utf-8")
    sections = re.split(r"\n\n---\n\n", text)
    records = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        meta, content = parse_frontmatter(section)
        if meta and content:
            meta["_content"] = content
            records.append(meta)
    return records


# ── section write helpers ───────────────────────────────────────────────────

def _format_section(meta: dict, content: str) -> str:
    """Format a single memory as YAML frontmatter + content."""
    lines = ["---"]
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, bool):
            lines.append(f"{k}: {str(v).lower()}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k}: {v}")
        else:
            escaped = str(v).replace('"', '\\"')
            lines.append(f'{k}: "{escaped}"')
    lines.append("---")
    lines.append("")
    lines.append(content)
    return "\n".join(lines)


def write_memory_section(filepath: Path, meta: dict, content: str) -> None:
    """Append a memory section to a grouped topic file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    section = _format_section(meta, content)
    if filepath.exists():
        existing = filepath.read_text(encoding="utf-8")
        if existing.strip():
            section = existing.rstrip() + "\n\n---\n\n" + section
    # atomic write via temp file + rename
    tmp = filepath.with_suffix(".tmp")
    tmp.write_text(section, encoding="utf-8")
    tmp.rename(filepath)


def remove_memory_section(filepath: Path, record_id: str) -> bool:
    """Remove a memory section from a grouped topic file. Returns True if removed."""
    if not filepath.exists():
        return False
    sections = re.split(r"\n\n---\n\n", filepath.read_text(encoding="utf-8"))
    new_sections = []
    removed = False
    for section in sections:
        section = section.strip()
        if not section:
            continue
        meta, _ = parse_frontmatter(section)
        if meta.get("id") == record_id:
            removed = True
            continue
        new_sections.append(section)
    if not removed:
        return False
    if not new_sections:
        filepath.unlink()
        return True
    tmp = filepath.with_suffix(".tmp")
    tmp.write_text("\n\n---\n\n".join(new_sections), encoding="utf-8")
    tmp.rename(filepath)
    return True


def update_memory_section(filepath: Path, record_id: str, new_meta: dict, new_content: str) -> bool:
    """Update a specific memory section in a grouped topic file."""
    if not filepath.exists():
        return False
    sections = re.split(r"\n\n---\n\n", filepath.read_text(encoding="utf-8"))
    new_sections = []
    updated = False
    for section in sections:
        section = section.strip()
        if not section:
            continue
        meta, _ = parse_frontmatter(section)
        if meta.get("id") == record_id:
            new_sections.append(_format_section(new_meta, new_content))
            updated = True
        else:
            new_sections.append(section)
    if not updated:
        return False
    tmp = filepath.with_suffix(".tmp")
    tmp.write_text("\n\n---\n\n".join(new_sections), encoding="utf-8")
    tmp.rename(filepath)
    return True


# ── index ───────────────────────────────────────────────────────────────────

def build_fs_index(root_dir: Path) -> dict[str, dict]:
    """Walk memory_store/ directory and rebuild index.

    Index JSON schema: {record_id: {file, memory_type, scope, created_at, stability, ...}}
    """
    index: dict[str, dict] = {}
    if not root_dir.exists():
        return index

    for md_file in sorted(root_dir.rglob("*.md")):
        rel = str(md_file.relative_to(root_dir))
        if rel.startswith("_meta"):
            continue
        try:
            records = parse_memory_file(md_file)
        except Exception:
            continue
        for rec in records:
            rid = rec.get("id", "")
            if not rid:
                continue
            index[rid] = {
                "file": rel,
                "memory_type": rec.get("memory_type", "semantic"),
                "scope": rec.get("scope", "user"),
                "source_type": rec.get("source_type", "unknown"),
                "approval_status": rec.get("approval_status", "approved"),
                "confidence": rec.get("confidence", 0.5),
                "stability": rec.get("stability", "stable"),
                "created_at": rec.get("created_at", ""),
                "updated_at": rec.get("updated_at", ""),
            }

    # write index.json
    meta_dir = root_dir / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    index_path = meta_dir / "index.json"
    index_payload = {
        "records": index,
        "total": len(index),
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    tmp = meta_dir / "index.tmp"
    tmp.write_text(json.dumps(index_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(index_path)

    return index


def _load_index(root_dir: Path) -> dict[str, dict]:
    """Load index from _meta/index.json, or rebuild if missing/corrupt."""
    index_path = root_dir / "_meta" / "index.json"
    if not index_path.exists():
        return build_fs_index(root_dir)
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        return payload.get("records", {})
    except (json.JSONDecodeError, KeyError):
        return build_fs_index(root_dir)


def _write_index_entry(root_dir: Path, record_id: str, entry: dict) -> None:
    """Write-through: update a single entry in index.json."""
    index = _load_index(root_dir)
    index[record_id] = entry
    meta_dir = root_dir / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    index_path = meta_dir / "index.json"
    payload = {
        "records": index,
        "total": len(index),
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    tmp = meta_dir / "index.tmp"
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(index_path)


def _remove_index_entry(root_dir: Path, record_id: str) -> None:
    """Remove an entry from index.json."""
    index = _load_index(root_dir)
    if record_id in index:
        del index[record_id]
    meta_dir = root_dir / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    index_path = meta_dir / "index.json"
    payload = {
        "records": index,
        "total": len(index),
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    tmp = meta_dir / "index.tmp"
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(index_path)


# ── audit ───────────────────────────────────────────────────────────────────

def _derive_audit_id_fs(audit_summary: MemoryAuditSummary) -> str:
    payload = "|".join((
        audit_summary.operation_type,
        audit_summary.decision_type,
        audit_summary.source_summary,
        audit_summary.user_choice,
        audit_summary.safety_summary,
        str(audit_summary.sensitive_redacted),
    ))
    digest = sha256(payload.encode("utf-8")).hexdigest()
    return f"audit:fs:{digest[:16]}"


# ── record construction ────────────────────────────────────────────────────

def _record_from_frontmatter(meta: dict) -> MemoryRecord:
    """Build a MemoryRecord from parsed frontmatter metadata."""
    content = meta.get("_content", "")
    rid = meta.get("id", "")
    scope_str = meta.get("scope", "session")
    try:
        scope = MemoryScope(scope_str)
    except ValueError:
        scope = MemoryScope.SESSION

    return MemoryRecord(
        id=rid,
        content=content,
        scope=scope,
        source_summary=meta.get("source_summary", ""),
        safety_summary=meta.get("safety_summary", "safe"),
        audit_id=meta.get("audit_id", ""),
        created_by_operation=MemoryOperationType(meta.get("created_by_operation", "retain_intent")),
        updated_by_operation=MemoryOperationType(meta.get("updated_by_operation", "retain_intent")),
        sensitive_redacted=meta.get("sensitive_redacted", False),
        memory_type=meta.get("memory_type", "semantic"),
        source_type=meta.get("source_type", "explicit_user_request"),
        approval_status=meta.get("approval_status", "approved"),
        metadata={
            "confidence": meta.get("confidence", 0.5),
            "stability": meta.get("stability", "stable"),
            "created_at": meta.get("created_at", ""),
            "updated_at": meta.get("updated_at", ""),
        },
    )


def _meta_from_intent(intent: MemoryOperationIntent, audit_id: str, record_id: str) -> dict:
    """Build frontmatter metadata dict from MemoryOperationIntent."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    scope_str = intent.scope.value if intent.scope else "session"
    return {
        "id": record_id,
        "memory_type": "semantic",  # v1 default
        "scope": scope_str,
        "source_type": "explicit_user_request",
        "approval_status": intent.confirmation_status.value
        if hasattr(intent.confirmation_status, "value") else str(intent.confirmation_status),
        "created_at": now,
        "updated_at": now,
        "source_summary": intent.source_summary,
        "safety_summary": intent.safety_summary,
        "audit_id": audit_id,
        "sensitive_redacted": intent.sensitive_redacted,
        "created_by_operation": intent.operation_type.value,
        "updated_by_operation": intent.operation_type.value,
        "stability": "stable",
        "confidence": 0.85 if intent.confirmation_status.value == "approved" else 0.5,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# FilesystemMemoryStore
# ═══════════════════════════════════════════════════════════════════════════════

class FilesystemMemoryStore:
    """Filesystem-native memory store — .md files with YAML frontmatter.

    Implements MemoryStoreProtocol for drop-in replacement of InMemoryMemoryStore.
    Adds recall() for scope/recency/memory_type filtering.

    Files are source of truth. _meta/index.json is a derived cache, rebuilt on
    session start (constructor) and updated via write-through on mutation.
    """

    def __init__(self, root_dir: Path | str | None = None) -> None:
        if root_dir is None:
            root_dir = Path.home() / ".my-first-agent" / "memory"
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        # Rebuild index on session start
        self._index: dict[str, dict] = build_fs_index(self.root_dir)

    # ── MemoryStoreProtocol ──────────────────────────────────────────────

    def apply_operation_intent(
        self,
        intent: MemoryOperationIntent,
        audit_summary: MemoryAuditSummary,
    ) -> MemoryStoreApplyResult:
        """Apply confirmed/audited intent to filesystem store."""
        _validate_apply_inputs(intent, audit_summary)
        audit_id = _derive_audit_id_fs(audit_summary)

        if intent.operation_type in NON_WRITING_OPERATION_TYPES:
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.SKIPPED,
                operation_type=intent.operation_type,
                record=None,
                audit_id=audit_id,
                message="operation does not authorize store write",
            )

        if intent.operation_type is MemoryOperationType.USE_ONCE:
            return self._apply_use_once(intent, audit_id)

        if (
            intent.operation_type in MUTATING_OPERATION_TYPES
            and intent.confirmation_status.value != "approved"
        ):
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.REJECTED,
                operation_type=intent.operation_type,
                record=None,
                audit_id=audit_id,
                message="mutating memory operation requires approved confirmation",
            )

        if intent.operation_type is MemoryOperationType.RETAIN:
            return self._apply_retain(intent, audit_id)

        if intent.operation_type is MemoryOperationType.UPDATE:
            return self._apply_update(intent, audit_id)

        if intent.operation_type is MemoryOperationType.FORGET:
            return self._apply_forget(intent, audit_id)

        return MemoryStoreApplyResult(
            status=MemoryStoreApplyStatus.SKIPPED,
            operation_type=intent.operation_type,
            record=None,
            audit_id=audit_id,
            message="operation is not handled",
        )

    def get_record(self, record_id: str) -> MemoryRecord | None:
        entry = self._index.get(record_id)
        if entry is None:
            return None
        filepath = self.root_dir / entry["file"]
        if not filepath.exists():
            return None
        sections = parse_memory_file(filepath)
        for meta in sections:
            if meta.get("id") == record_id:
                return _record_from_frontmatter(meta)
        return None

    def list_records(self) -> tuple[MemoryRecord, ...]:
        records: list[MemoryRecord] = []
        for record_id in sorted(self._index):
            rec = self.get_record(record_id)
            if rec is not None:
                records.append(rec)
        return tuple(records)

    # ── recall API ───────────────────────────────────────────────────────

    def recall(
        self,
        *,
        scope: MemoryScope | None = None,
        memory_type: str | None = None,
        max_items: int = 5,
    ) -> list[MemoryRecord]:
        """Recall memory records filtered by scope, type, and recency.

        Deterministic filtering only — no semantic search, no weighted ranking.
        Results sorted by created_at descending (most recent first).

        query_context and recency_weight are intentionally not supported in
        Phase 4. Semantic search belongs in external provider backend.
        """
        candidates = []
        for record_id, entry in self._index.items():
            if scope is not None and entry.get("scope") != scope.value:
                continue
            if memory_type is not None and entry.get("memory_type") != memory_type:
                continue
            if entry.get("approval_status") == "rejected":
                continue
            candidates.append((record_id, entry))

        # sort by created_at desc (recency)
        candidates.sort(key=lambda x: x[1].get("created_at", ""), reverse=True)

        records = []
        for record_id, entry in candidates[:max_items]:
            rec = self.get_record(record_id)
            if rec is not None:
                records.append(rec)
        return records

    # ── internal operations ──────────────────────────────────────────────

    def _apply_retain(self, intent: MemoryOperationIntent, audit_id: str) -> MemoryStoreApplyResult:
        record_id = derive_memory_record_id(intent.source_summary)
        meta = _meta_from_intent(intent, audit_id, record_id)
        topic = _route_topic("semantic", intent.scope or MemoryScope.USER)
        filepath = self.root_dir / topic
        write_memory_section(filepath, meta, intent.content_summary)

        # write-through index
        _write_index_entry(self.root_dir, record_id, {
            "file": topic,
            "memory_type": "semantic",
            "scope": intent.scope.value if intent.scope else "session",
            "source_type": "explicit_user_request",
            "approval_status": "approved",
            "confidence": 0.85,
            "stability": "stable",
            "created_at": meta["created_at"],
            "updated_at": meta["updated_at"],
            "created_by_operation": meta["created_by_operation"],
        })
        self._index = _load_index(self.root_dir)

        record = self.get_record(record_id)
        return MemoryStoreApplyResult(
            status=MemoryStoreApplyStatus.APPLIED,
            operation_type=intent.operation_type,
            record=record,
            audit_id=audit_id,
            message="memory record retained to filesystem",
        )

    def _apply_use_once(self, intent: MemoryOperationIntent, audit_id: str) -> MemoryStoreApplyResult:
        record_id = derive_memory_record_id(intent.source_summary)
        meta = _meta_from_intent(intent, audit_id, record_id)
        meta["approval_status"] = "session_only"
        topic = _route_topic("semantic", intent.scope or MemoryScope.USER)
        filepath = self.root_dir / topic
        write_memory_section(filepath, meta, intent.content_summary)

        _write_index_entry(self.root_dir, record_id, {
            "file": topic,
            "memory_type": "semantic",
            "scope": intent.scope.value if intent.scope else "session",
            "source_type": "explicit_user_request",
            "approval_status": "session_only",
            "confidence": 0.5,
            "stability": "ephemeral",
            "created_at": meta["created_at"],
            "updated_at": meta["updated_at"],
            "created_by_operation": meta["created_by_operation"],
        })
        self._index = _load_index(self.root_dir)

        record = self.get_record(record_id)
        return MemoryStoreApplyResult(
            status=MemoryStoreApplyStatus.APPLIED,
            operation_type=intent.operation_type,
            record=record,
            audit_id=audit_id,
            message="session-only memory record retained to filesystem",
        )

    def _apply_update(self, intent: MemoryOperationIntent, audit_id: str) -> MemoryStoreApplyResult:
        record_id = derive_memory_record_id(intent.source_summary)
        entry = self._index.get(record_id)
        if entry is None:
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.NOT_FOUND,
                operation_type=intent.operation_type,
                record=None,
                audit_id=audit_id,
                message="memory record not found for update",
            )

        new_meta = _meta_from_intent(intent, audit_id, record_id)
        new_meta["created_at"] = entry.get("created_at", new_meta["created_at"])
        new_meta["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        new_meta["created_by_operation"] = entry.get("created_by_operation", "retain_intent")

        filepath = self.root_dir / entry["file"]
        ok = update_memory_section(filepath, record_id, new_meta, intent.content_summary)
        if not ok:
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.NOT_FOUND,
                operation_type=intent.operation_type,
                record=None,
                audit_id=audit_id,
                message="section not found in file for update",
            )

        _write_index_entry(self.root_dir, record_id, {**entry,
            "updated_at": new_meta["updated_at"],
            "stability": "modified",
        })
        self._index = _load_index(self.root_dir)

        record = self.get_record(record_id)
        return MemoryStoreApplyResult(
            status=MemoryStoreApplyStatus.APPLIED,
            operation_type=intent.operation_type,
            record=record,
            audit_id=audit_id,
            message="memory record updated on filesystem",
        )

    def _apply_forget(self, intent: MemoryOperationIntent, audit_id: str) -> MemoryStoreApplyResult:
        record_id = derive_memory_record_id(intent.source_summary)
        entry = self._index.get(record_id)
        if entry is None:
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.NOT_FOUND,
                operation_type=intent.operation_type,
                record=None,
                audit_id=audit_id,
                message="memory record not found for forget",
            )

        filepath = self.root_dir / entry["file"]
        existing_record = self.get_record(record_id)
        remove_memory_section(filepath, record_id)
        _remove_index_entry(self.root_dir, record_id)
        self._index = _load_index(self.root_dir)

        return MemoryStoreApplyResult(
            status=MemoryStoreApplyStatus.APPLIED,
            operation_type=intent.operation_type,
            record=existing_record,
            audit_id=audit_id,
            message="memory record forgotten from filesystem",
        )
