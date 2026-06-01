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

import contextlib
import json
import os
import re
import threading
import warnings
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - current target is POSIX/macOS, fallback is best-effort.
    fcntl = None  # type: ignore[assignment]

from agent.memory_confirmation import MemoryConfirmationChoice, MemoryConfirmationStatus
from agent.memory_contracts import MemoryDecisionType, MemoryScope
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
    _validate_apply_inputs,
    derive_memory_record_id,
    find_duplicate_record,
    find_record_by_content,
    intent_rejects_store_write,
    mutating_intent_allows_store_write,
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
            with contextlib.suppress(ValueError):
                val = float(val) if "." in val or "e" in val.lower() else int(val)
        meta[key] = val
    return meta, body


def parse_memory_file(filepath: Path) -> list[dict]:
    """解析含多个 memory section 的 .md 文件。

    每个 section 格式：``---\\n[YAML frontmatter]\\n---\\n\\n[body]``
    Section 之间由 ``\\n\\n---\\n\\n`` 分隔。

    稳健性策略：
    - 分隔正则容忍空白变化（\\n{2,}---\\n{1,}），兼容手动编辑的格式偏差
    - 不以 ``---`` 开头的 section 自动补前缀
    - 单个 section 损坏不影响其余 section 的解析（per-section isolation）
    """
    text = filepath.read_text(encoding="utf-8")
    # 使用更稳健的分隔模式：
    # \\n{2,}---\\n{1,} = 至少两个换行 + --- + 至少一个换行
    # 避免了单换行 + ---（frontmatter 关闭标记）的误匹配
    sections = re.split(r"\n{2,}---\n{1,}", text)
    records: list[dict] = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        # 手动编辑格式可能导致 section 不以 --- 开头（前缀被分割符消费）
        if not section.startswith("---"):
            section = "---\n" + section
        try:
            meta, content = parse_frontmatter(section)
            if meta and content:
                meta["_content"] = content
                records.append(meta)
        except Exception:
            # 单个 section 解析失败，隔离之，继续解析后续 section
            continue
    return records


# ── section write helpers ───────────────────────────────────────────────────

_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


def _process_lock_for(lock_path: Path) -> threading.RLock:
    """返回进程内同路径锁，补足 fcntl 对同进程多线程的保护边界。"""

    key = str(lock_path.resolve())
    with _PROCESS_LOCKS_GUARD:
        if key not in _PROCESS_LOCKS:
            _PROCESS_LOCKS[key] = threading.RLock()
        return _PROCESS_LOCKS[key]


@contextmanager
def _locked_filesystem_rmw(target_path: Path):
    """锁住 filesystem read-modify-write 临界区。

    这里锁住的是 filesystem read-modify-write 临界区，不是 memory governance；
    目的是避免多个 runtime 同时更新同一 Markdown memory 文件或 derived index
    时发生 TOCTOU 覆盖。当前项目主要运行在 POSIX/macOS，使用 fcntl.flock 做
    跨进程锁；进程内再用 threading.RLock 补齐多线程测试和同进程并发边界。
    """

    target_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target_path.with_name(f".{target_path.name}.lock")
    process_lock = _process_lock_for(lock_path)
    with process_lock, lock_path.open("a+b") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        else:
            # fcntl 不可用时只能降级为 best-effort 写入；这是可观测性
            # warning，不改变 memory governance，也不输出任何 memory 正文。
            warnings.warn(
                "filesystem memory lock degraded: fcntl unavailable; "
                "using process-local best-effort lock only",
                RuntimeWarning,
                stacklevel=2,
            )
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _atomic_write_text(filepath: Path, text: str) -> None:
    """以唯一 temp file + replace 写入，避免并发 writer 共享固定 `.tmp`。"""

    filepath.parent.mkdir(parents=True, exist_ok=True)
    tmp = filepath.with_name(
        f".{filepath.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(filepath)
    finally:
        if tmp.exists():
            tmp.unlink()

def _format_section(meta: dict, content: str) -> str:
    """Format a single memory as YAML frontmatter + content.

    内部键 _content（parse_memory_file 用于传递 body text）不会写入 YAML。
    """
    lines = ["---"]
    for k, v in meta.items():
        # 跳过内部键，避免泄露到 YAML frontmatter
        if k.startswith("_"):
            continue
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
    with _locked_filesystem_rmw(filepath):
        section = _format_section(meta, content)
        if filepath.exists():
            existing = filepath.read_text(encoding="utf-8")
            if existing.strip():
                section = existing.rstrip() + "\n\n---\n\n" + section
        _atomic_write_text(filepath, section)


def remove_memory_section(filepath: Path, record_id: str) -> bool:
    """Remove a memory section from a grouped topic file. Returns True if removed."""
    with _locked_filesystem_rmw(filepath):
        if not filepath.exists():
            return False
        sections = re.split(r"\n{2,}---\n{1,}", filepath.read_text(encoding="utf-8"))
        new_sections: list[str] = []
        removed = False
        for section in sections:
            section = section.strip()
            if not section:
                continue
            if not section.startswith("---"):
                section = "---\n" + section
            try:
                meta, _ = parse_frontmatter(section)
            except Exception:
                new_sections.append(section)
                continue
            if meta.get("id") == record_id:
                removed = True
                continue
            new_sections.append(section)
        if not removed:
            return False
        if not new_sections:
            filepath.unlink()
            return True
        _atomic_write_text(filepath, "\n\n---\n\n".join(new_sections))
        return True


def update_memory_section(filepath: Path, record_id: str, new_meta: dict, new_content: str) -> bool:
    """Update a specific memory section in a grouped topic file."""
    with _locked_filesystem_rmw(filepath):
        if not filepath.exists():
            return False
        sections = re.split(r"\n{2,}---\n{1,}", filepath.read_text(encoding="utf-8"))
        new_sections: list[str] = []
        updated = False
        for section in sections:
            section = section.strip()
            if not section:
                continue
            if not section.startswith("---"):
                section = "---\n" + section
            try:
                meta, _ = parse_frontmatter(section)
            except Exception:
                new_sections.append(section)
                continue
            if meta.get("id") == record_id:
                new_sections.append(_format_section(new_meta, new_content))
                updated = True
            else:
                new_sections.append(section)
        if not updated:
            return False
        _atomic_write_text(filepath, "\n\n---\n\n".join(new_sections))
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
    with _locked_filesystem_rmw(index_path):
        _atomic_write_text(
            index_path,
            json.dumps(index_payload, indent=2, ensure_ascii=False),
        )

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


def _read_index_records_without_rebuild(root_dir: Path) -> dict[str, dict]:
    """读取 index records，不在已持有 index lock 时递归 rebuild。"""

    index_path = root_dir / "_meta" / "index.json"
    if not index_path.exists():
        return {}
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    records = payload.get("records", {})
    return records if isinstance(records, dict) else {}


def _write_index_entry(root_dir: Path, record_id: str, entry: dict) -> None:
    """Write-through: update a single entry in index.json."""
    meta_dir = root_dir / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    index_path = meta_dir / "index.json"
    with _locked_filesystem_rmw(index_path):
        index = _read_index_records_without_rebuild(root_dir)
        index[record_id] = entry
        payload = {
            "records": index,
            "total": len(index),
            "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        _atomic_write_text(
            index_path,
            json.dumps(payload, indent=2, ensure_ascii=False),
        )


def _remove_index_entry(root_dir: Path, record_id: str) -> None:
    """Remove an entry from index.json."""
    meta_dir = root_dir / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    index_path = meta_dir / "index.json"
    with _locked_filesystem_rmw(index_path):
        index = _read_index_records_without_rebuild(root_dir)
        if record_id in index:
            del index[record_id]
        payload = {
            "records": index,
            "total": len(index),
            "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        _atomic_write_text(
            index_path,
            json.dumps(payload, indent=2, ensure_ascii=False),
        )


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
    """Build a MemoryRecord from parsed frontmatter metadata。

    不会修改输入的 meta dict（使用 .get() 只读访问）。
    """
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
            "tags": meta.get("tags", ""),
        },
    )


def _meta_from_intent(intent: MemoryOperationIntent, audit_id: str, record_id: str) -> dict:
    """Build frontmatter metadata dict from MemoryOperationIntent.

    Metadata Continuity Invariant (RFC §14.5):
    memory_type/source_type/approval_status 禁止在 store 层重新推断。
    intent 的字段由 governance routing 设置，store 原样使用，不 fallback。
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    scope_str = intent.scope.value if intent.scope else "session"
    return {
        "id": record_id,
        "memory_type": intent.memory_type,
        "scope": scope_str,
        "source_type": intent.source_type,
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
        # confidence metadata continuity（Slice 1 P1-1 修复）：
        # 优先使用 intent.confidence（来自 extraction → governance routing 的真实值）。
        # None 时使用 legacy fallback，仅兼容旧路径（如 explicit_user_request），
        # 不做重新推断。新 extraction/governance 路径必须传入真实 confidence。
        "confidence": (
            intent.confidence
            if intent.confidence is not None
            else (0.85 if intent.confirmation_status.value == "approved" else 0.5)
        ),
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
        # 优先级：显式参数 > MEMORY_STORE_ROOT > MEMORY_ROOT > 默认 ~/.my-first-agent/memory
        import os as _os
        if root_dir is None:
            root_dir = (
                _os.getenv("MEMORY_STORE_ROOT")
                or _os.getenv("MEMORY_ROOT")
                or (Path.home() / ".my-first-agent" / "memory")
            )
        self.root_dir = Path(root_dir)
        try:
            self.root_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise OSError(
                f"无法创建 FilesystemMemoryStore 根目录 {self.root_dir}: {e}"
            ) from e
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

        if intent_rejects_store_write(intent):
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.REJECTED,
                operation_type=intent.operation_type,
                record=None,
                audit_id=audit_id,
                message="rejected memory intent does not authorize store write",
            )

        if intent.operation_type is MemoryOperationType.USE_ONCE:
            return self._apply_use_once(intent, audit_id)

        # T1 explicit approval 和 T2 auto_retained 均可写入 store。
        if (
            intent.operation_type in MUTATING_OPERATION_TYPES
            and not mutating_intent_allows_store_write(intent)
        ):
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.REJECTED,
                operation_type=intent.operation_type,
                record=None,
                audit_id=audit_id,
                message="mutating memory operation requires approved or auto_retained confirmation",
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

    def store_retained_record(self, candidate: dict) -> None:
        """从 dispatcher payload candidate 直接写入 filesystem store。

        MemoryRuntime.resolve_confirmation 在 direct_write 模式中调用此方法，
        构造最小 MemoryOperationIntent 后走 _apply_retain 标准写入路径。
        """
        record_id = str(candidate.get("proposal_id", ""))
        content = str(candidate.get("content", ""))
        if not record_id or not content:
            return

        scope_raw = candidate.get("scope", "user")
        try:
            scope = MemoryScope(scope_raw)
        except ValueError:
            scope = MemoryScope.USER

        intent = MemoryOperationIntent(
            operation_type=MemoryOperationType.RETAIN,
            decision_type=MemoryDecisionType.RETAIN,
            confirmation_status=MemoryConfirmationStatus.APPROVED,
            user_choice=MemoryConfirmationChoice.ACCEPT,
            content_summary=content,
            source_summary=f"candidate:{record_id}",
            scope=scope,
            safety_summary="no_safety_concern",
            sensitive_redacted=False,
            user_visible_summary=content[:80],
            memory_type="semantic",
            source_type="explicit_user_request",
        )

        from agent.memory_operations import build_memory_audit_summary
        audit = build_memory_audit_summary(intent)
        self._apply_retain(intent, _derive_audit_id_fs(audit))

    # ── recall API ───────────────────────────────────────────────────────

    def recall(
        self,
        *,
        scope: MemoryScope | str | None = None,
        memory_type: str | None = None,
        max_items: int = 5,
        query_context: str | None = None,
        recency_weight: float | None = None,
    ) -> list[MemoryRecord]:
        """Recall memory records filtered by scope, type, and recency.

        Phase 4 recall only supports deterministic scope/type/recency/max_items
        filtering.  Results sorted by created_at descending (most recent first).

        query_context is reserved for future semantic retrieval and is not
        implemented.  recency_weight is reserved for future weighted ranking
        and is not implemented.
        """
        if query_context is not None:
            raise NotImplementedError(
                "query_context is reserved for future semantic retrieval "
                "and is not implemented in Phase 4"
            )
        if recency_weight is not None:
            raise NotImplementedError(
                "recency_weight is reserved for future weighted ranking "
                "and is not implemented in Phase 4"
            )

        # 兼容 str 和 MemoryScope：index 中 scope 存为字符串
        scope_value: str | None = None
        if scope is not None:
            scope_value = scope.value if isinstance(scope, MemoryScope) else scope

        candidates = []
        for record_id, entry in self._index.items():
            if scope_value is not None and entry.get("scope") != scope_value:
                continue
            if memory_type is not None and entry.get("memory_type") != memory_type:
                continue
            if entry.get("approval_status") == "rejected":
                continue
            candidates.append((record_id, entry))

        # sort by created_at desc (recency)
        candidates.sort(key=lambda x: x[1].get("created_at", ""), reverse=True)

        records = []
        for record_id, _entry in candidates[:max_items]:
            rec = self.get_record(record_id)
            if rec is not None:
                records.append(rec)
        return records

    # ── internal operations ──────────────────────────────────────────────

    def _apply_retain(self, intent: MemoryOperationIntent, audit_id: str) -> MemoryStoreApplyResult:
        # 去重检查：基于 content + memory_type + scope，不求助于 embedding/similarity
        # Metadata Continuity (RFC §14.5): 使用 intent.memory_type，不 fallback
        memory_type = intent.memory_type
        existing = find_duplicate_record(
            intent.content_summary, memory_type, intent.scope,
            self.list_records(),
        )
        if existing is not None:
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.APPLIED,
                operation_type=intent.operation_type,
                record=existing,
                audit_id=audit_id,
                message="dedup_hit: 内容已存在于 filesystem store，不重复写入",
            )

        record_id = derive_memory_record_id(intent.source_summary)
        meta = _meta_from_intent(intent, audit_id, record_id)
        topic = _route_topic(memory_type, intent.scope or MemoryScope.USER)
        filepath = self.root_dir / topic
        write_memory_section(filepath, meta, intent.content_summary)

        # write-through index（confidence 优先使用 intent.confidence 保真值）
        _write_index_entry(self.root_dir, record_id, {
            "file": topic,
            "memory_type": memory_type,
            "scope": intent.scope.value if intent.scope else "session",
            "source_type": intent.source_type,
            "approval_status": intent.confirmation_status.value
                if hasattr(intent.confirmation_status, "value")
                else str(intent.confirmation_status),
            "confidence": (
                intent.confidence
                if intent.confidence is not None
                else (0.85 if intent.confirmation_status.value == "approved" else 0.5)
            ),
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

    def _apply_use_once(
        self, intent: MemoryOperationIntent, audit_id: str
    ) -> MemoryStoreApplyResult:
        record_id = derive_memory_record_id(intent.source_summary)
        meta = _meta_from_intent(intent, audit_id, record_id)
        meta["approval_status"] = "session_only"
        # Metadata Continuity (RFC §14.5): 使用 intent.memory_type，不 fallback
        memory_type = intent.memory_type
        topic = _route_topic(memory_type, intent.scope or MemoryScope.USER)
        filepath = self.root_dir / topic
        write_memory_section(filepath, meta, intent.content_summary)

        _write_index_entry(self.root_dir, record_id, {
            "file": topic,
            "memory_type": memory_type,
            "scope": intent.scope.value if intent.scope else "session",
            "source_type": "explicit_user_request",
            "approval_status": "session_only",
            # confidence metadata continuity：优先保真值，None 时 legacy fallback
            "confidence": intent.confidence if intent.confidence is not None else 0.5,
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
        # 按 content 匹配，而非依赖 source_summary 派生的不稳定 identity
        target = find_record_by_content(intent.content_summary, self.list_records())
        if target is None:
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.NOT_FOUND,
                operation_type=intent.operation_type,
                record=None,
                audit_id=audit_id,
                message="memory record not found for forget (按 content 未匹配到任何 record)",
            )
        record_id = target.id
        entry = self._index.get(record_id)
        if entry is None:
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.NOT_FOUND,
                operation_type=intent.operation_type,
                record=None,
                audit_id=audit_id,
                message="memory record not found for forget (content 匹配到但 index 缺失)",
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
