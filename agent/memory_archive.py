"""Filesystem-first memory archive export/import helpers.

Archive tooling is intentionally narrow: it backs up/restores a filesystem
memory root and excludes sensitive/runtime paths. It is not a cross-backend
migration layer and does not change memory governance.
"""

from __future__ import annotations

import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_EXCLUDED_NAMES = {".env", "agent_log.jsonl", "sessions", "runs"}


@dataclass(frozen=True, slots=True)
class MemoryArchiveResult:
    """export/import 的脱敏摘要，不包含 record 正文。"""

    dry_run: bool
    would_write: bool
    written: bool
    file_count: int
    excluded_count: int = 0


def _is_excluded(rel_path: Path) -> bool:
    return any(part in _EXCLUDED_NAMES for part in rel_path.parts)


def export_memory_archive(
    memory_root: Path | str,
    output_path: Path | str,
    *,
    dry_run: bool = False,
) -> MemoryArchiveResult:
    """将 filesystem memory root 打包为 tar.gz。

    默认排除 `.env`、`agent_log.jsonl`、`sessions/`、`runs/`，并且返回值只包含
    计数，不打印任何 memory 正文或 secret-like fixture。
    """

    root = Path(memory_root)
    output = Path(output_path)
    included: list[Path] = []
    excluded_count = 0
    if root.exists():
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if _is_excluded(rel):
                excluded_count += 1
                continue
            included.append(path)

    if dry_run:
        return MemoryArchiveResult(
            dry_run=True,
            would_write=bool(included),
            written=False,
            file_count=len(included),
            excluded_count=excluded_count,
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as tf:
        for path in included:
            tf.add(path, arcname=str(path.relative_to(root)))
    return MemoryArchiveResult(
        dry_run=False,
        would_write=bool(included),
        written=True,
        file_count=len(included),
        excluded_count=excluded_count,
    )


def _validate_archive_member(name: str) -> PurePosixPath:
    member = PurePosixPath(name)
    if member.is_absolute() or ".." in member.parts:
        raise ValueError(f"unsafe archive member: {name}")
    if any(part in _EXCLUDED_NAMES for part in member.parts):
        raise ValueError(f"unsafe archive member: {name}")
    return member


def import_memory_archive(
    archive_path: Path | str,
    memory_root: Path | str,
    *,
    dry_run: bool = True,
) -> MemoryArchiveResult:
    """从 archive 恢复到指定 memory root。

    import 默认 dry-run；apply 需要 `dry_run=False`。恢复路径会逐个校验 archive
    member，禁止绝对路径、`..` traversal 和敏感/runtime 路径。
    """

    archive = Path(archive_path)
    root = Path(memory_root)
    with tarfile.open(archive, "r:gz") as tf:
        members = [m for m in tf.getmembers() if m.isfile()]
        rel_members = [_validate_archive_member(m.name) for m in members]
        if dry_run:
            return MemoryArchiveResult(
                dry_run=True,
                would_write=bool(rel_members),
                written=False,
                file_count=len(rel_members),
            )

        root.mkdir(parents=True, exist_ok=True)
        for member, rel in zip(members, rel_members, strict=True):
            target = root / Path(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = tf.extractfile(member)
            if source is None:
                continue
            target.write_bytes(source.read())

    return MemoryArchiveResult(
        dry_run=False,
        would_write=bool(members),
        written=True,
        file_count=len(members),
    )

