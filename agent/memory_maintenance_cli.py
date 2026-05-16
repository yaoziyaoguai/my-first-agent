"""Memory filesystem maintenance CLI.

这是 `main.py memory ...` 的薄入口层：只调用 filesystem-first 运维 helper，
不读取 `.env`、不读取 agent_log/sessions/runs 正文、不参与 memory governance。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from agent.memory_archive import export_memory_archive, import_memory_archive
from agent.memory_index import repair_memory_index, validate_memory_index
from agent.memory_review import _resolve_memory_root


def _memory_root_arg(value: str | None) -> Path:
    return Path(value) if value else Path(_resolve_memory_root())


def run_memory_maintenance_cli(argv: list[str] | None = None) -> int:
    """运行最小 memory maintenance CLI。

    支持：
    - `memory index verify`
    - `memory index repair --dry-run|--apply`
    - `memory archive export <output>`
    - `memory archive import <archive> --dry-run|--apply`
    """

    parser = argparse.ArgumentParser(prog="python main.py memory")
    parser.add_argument("--root", default=None, help="memory root，默认使用项目配置优先级")
    subparsers = parser.add_subparsers(dest="area", required=True)

    index_parser = subparsers.add_parser("index")
    index_sub = index_parser.add_subparsers(dest="action", required=True)
    index_sub.add_parser("verify")
    repair_parser = index_sub.add_parser("repair")
    repair_group = repair_parser.add_mutually_exclusive_group()
    repair_group.add_argument("--dry-run", action="store_true", default=True)
    repair_group.add_argument("--apply", action="store_true")

    archive_parser = subparsers.add_parser("archive")
    archive_sub = archive_parser.add_subparsers(dest="action", required=True)
    export_parser = archive_sub.add_parser("export")
    export_parser.add_argument("output")
    import_parser = archive_sub.add_parser("import")
    import_parser.add_argument("archive")
    import_group = import_parser.add_mutually_exclusive_group()
    import_group.add_argument("--dry-run", action="store_true", default=True)
    import_group.add_argument("--apply", action="store_true")

    args = parser.parse_args(argv)
    root = _memory_root_arg(args.root)

    if args.area == "index" and args.action == "verify":
        result = validate_memory_index(root)
        print(
            "memory index verify: "
            f"ok={result.ok} indexed={len(result.indexed_ids)} actual={len(result.actual_ids)} "
            f"stale={len(result.stale_index_ids)} missing={len(result.missing_index_ids)} "
            f"duplicates={len(result.duplicate_record_ids)}"
        )
        return 0 if result.ok else 1

    if args.area == "index" and args.action == "repair":
        dry_run = not bool(args.apply)
        result = repair_memory_index(root, dry_run=dry_run)
        print(
            "memory index repair: "
            f"dry_run={result.dry_run} would_write={result.would_write} "
            f"written={result.written}"
        )
        return 0

    if args.area == "archive" and args.action == "export":
        result = export_memory_archive(root, Path(args.output))
        print(
            "memory archive export: "
            f"written={result.written} files={result.file_count} "
            f"excluded={result.excluded_count}"
        )
        return 0

    if args.area == "archive" and args.action == "import":
        dry_run = not bool(args.apply)
        result = import_memory_archive(Path(args.archive), root, dry_run=dry_run)
        print(
            "memory archive import: "
            f"dry_run={result.dry_run} would_write={result.would_write} "
            f"written={result.written} files={result.file_count}"
        )
        return 0

    parser.print_help()
    return 2

