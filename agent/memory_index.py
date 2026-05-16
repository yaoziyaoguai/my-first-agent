"""Filesystem memory index verification and repair helpers.

本模块只处理 `_meta/index.json` 这个派生 cache，不读取真实 sessions/runs，
不接触 memory governance，也不修改 Markdown record 正文。filesystem `.md`
文件仍是 source-of-truth。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agent.memory_fs_store import build_fs_index, parse_memory_file


@dataclass(frozen=True, slots=True)
class MemoryIndexValidationResult:
    """index 与 Markdown source-of-truth 的轻量一致性结果。"""

    ok: bool
    indexed_ids: tuple[str, ...]
    actual_ids: tuple[str, ...]
    stale_index_ids: tuple[str, ...]
    missing_index_ids: tuple[str, ...]
    duplicate_record_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MemoryIndexRepairResult:
    """index repair 的 dry-run/apply 结果。"""

    dry_run: bool
    would_write: bool
    written: bool
    before: MemoryIndexValidationResult
    after: MemoryIndexValidationResult | None = None


def _load_index_records(memory_root: Path) -> dict[str, dict]:
    index_path = memory_root / "_meta" / "index.json"
    if not index_path.exists():
        return {}
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    records = payload.get("records", {})
    return records if isinstance(records, dict) else {}


def _scan_source_records(memory_root: Path) -> tuple[dict[str, str], tuple[str, ...]]:
    actual: dict[str, str] = {}
    seen: set[str] = set()
    duplicates: set[str] = set()
    if not memory_root.exists():
        return {}, ()

    for md_file in sorted(memory_root.rglob("*.md")):
        rel = str(md_file.relative_to(memory_root))
        if rel.startswith("_meta"):
            continue
        try:
            records = parse_memory_file(md_file)
        except Exception:
            continue
        for record in records:
            record_id = str(record.get("id", "")).strip()
            if not record_id:
                continue
            if record_id in seen:
                duplicates.add(record_id)
            seen.add(record_id)
            actual.setdefault(record_id, rel)
    return actual, tuple(sorted(duplicates))


def validate_memory_index(memory_root: Path | str) -> MemoryIndexValidationResult:
    """验证 `_meta/index.json` 是否匹配 Markdown source-of-truth。

    这是只读 helper：不 rebuild、不 repair、不修改 record。它只检查 P3 所需的
    基本一致性：stale entry、missing entry、duplicate id。
    """

    root = Path(memory_root)
    index = _load_index_records(root)
    actual, duplicates = _scan_source_records(root)
    indexed_ids = set(index)
    actual_ids = set(actual)

    stale_ids: set[str] = set()
    for record_id, entry in index.items():
        rel = str(entry.get("file", "")).strip()
        if record_id not in actual_ids or (rel and not (root / rel).exists()):
            stale_ids.add(record_id)

    missing_ids = actual_ids - indexed_ids
    return MemoryIndexValidationResult(
        ok=not stale_ids and not missing_ids and not duplicates,
        indexed_ids=tuple(sorted(indexed_ids)),
        actual_ids=tuple(sorted(actual_ids)),
        stale_index_ids=tuple(sorted(stale_ids)),
        missing_index_ids=tuple(sorted(missing_ids)),
        duplicate_record_ids=duplicates,
    )


def repair_memory_index(
    memory_root: Path | str,
    *,
    dry_run: bool = True,
) -> MemoryIndexRepairResult:
    """重建派生 index。

    dry-run 是默认值；apply 只调用现有 `build_fs_index()` 重建 `_meta/index.json`，
    不修改 Markdown memory record 内容、不改变 approval/governance metadata。
    """

    root = Path(memory_root)
    before = validate_memory_index(root)
    if dry_run:
        return MemoryIndexRepairResult(
            dry_run=True,
            would_write=not before.ok,
            written=False,
            before=before,
        )

    build_fs_index(root)
    after = validate_memory_index(root)
    return MemoryIndexRepairResult(
        dry_run=False,
        would_write=not before.ok,
        written=True,
        before=before,
        after=after,
    )

