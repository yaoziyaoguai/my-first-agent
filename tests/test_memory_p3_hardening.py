"""Memory P3 hardening 的轻量回归测试。

这些测试只覆盖 filesystem-first 下的运维与 dogfood hardening 边界：
index verify/repair、archive export/import、fcntl 降级 warning。它们不改变
memory governance，不写真实 sessions/runs，也不读取 .env / agent_log。
"""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest

from agent.memory_fs_store import build_fs_index, parse_memory_file, write_memory_section


def _write_record(root: Path, rel_path: str, record_id: str, content: str) -> Path:
    filepath = root / rel_path
    write_memory_section(
        filepath,
        {
            "id": record_id,
            "memory_type": "semantic",
            "scope": "user",
            "approval_status": "approved",
            "governance_route": "T1",
            "confidence": 0.7,
        },
        content,
    )
    return filepath


def test_fcntl_unavailable_warns_without_leaking_content(monkeypatch, tmp_path: Path):
    """fcntl 不可用时降级为 best-effort 写入，并给出不含正文的 warning。

    这里验证的是 filesystem RMW 锁的可观测性，不是 memory governance：
    即使锁降级，写入路径仍不能打印 memory 正文或 secret-like 测试串。
    """
    import agent.memory_fs_store as fs

    monkeypatch.setattr(fs, "fcntl", None)
    filepath = tmp_path / "semantic" / "user_preferences.md"
    secret_like = "FAKE_API_KEY_DO_NOT_USE_123"

    with pytest.warns(RuntimeWarning) as captured:
        write_memory_section(
            filepath,
            {"id": "rec1", "memory_type": "semantic", "scope": "user"},
            f"synthetic body {secret_like}",
        )

    assert parse_memory_file(filepath)[0]["id"] == "rec1"
    warning_text = "\n".join(str(w.message) for w in captured)
    assert "fcntl" in warning_text
    assert "best-effort" in warning_text
    assert secret_like not in warning_text
    assert "synthetic body" not in warning_text


def test_index_validate_detects_clean_stale_missing_and_duplicate(tmp_path: Path):
    """index verify 只比较派生 index 与 Markdown source-of-truth，不改正文。"""
    from agent.memory_index import validate_memory_index

    root = tmp_path / "memory"
    _write_record(root, "semantic/user_preferences.md", "rec-a", "A")
    _write_record(root, "semantic/user_preferences.md", "rec-b", "B")
    build_fs_index(root)

    clean = validate_memory_index(root)
    assert clean.ok is True
    assert clean.stale_index_ids == ()
    assert clean.missing_index_ids == ()
    assert clean.duplicate_record_ids == ()

    index_path = root / "_meta" / "index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["records"]["stale-id"] = {"file": "semantic/missing.md"}
    payload["records"].pop("rec-b")
    index_path.write_text(json.dumps(payload), encoding="utf-8")
    _write_record(root, "semantic/other.md", "rec-a", "A duplicate")

    result = validate_memory_index(root)

    assert result.ok is False
    assert result.stale_index_ids == ("stale-id",)
    assert result.missing_index_ids == ("rec-b",)
    assert result.duplicate_record_ids == ("rec-a",)


def test_index_repair_dry_run_and_apply_rebuilds_without_changing_records(tmp_path: Path):
    """repair 默认 dry-run；apply 只重建派生 index，不改 memory record 正文/metadata。"""
    from agent.memory_index import repair_memory_index, validate_memory_index

    root = tmp_path / "memory"
    filepath = _write_record(root, "semantic/user_preferences.md", "rec-a", "original body")
    before = filepath.read_text(encoding="utf-8")
    build_fs_index(root)
    index_path = root / "_meta" / "index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["records"] = {}
    payload["total"] = 0
    index_path.write_text(json.dumps(payload), encoding="utf-8")

    dry_run = repair_memory_index(root, dry_run=True)
    assert dry_run.would_write is True
    assert validate_memory_index(root).missing_index_ids == ("rec-a",)

    applied = repair_memory_index(root, dry_run=False)
    assert applied.written is True
    assert validate_memory_index(root).ok is True
    assert filepath.read_text(encoding="utf-8") == before
    assert parse_memory_file(filepath)[0]["governance_route"] == "T1"


def test_export_import_archive_excludes_sensitive_paths_and_preserves_records(tmp_path: Path):
    """filesystem archive 是备份/恢复工具，不导出敏感路径，不改变 record 内容。"""
    from agent.memory_archive import export_memory_archive, import_memory_archive

    source = tmp_path / "source-memory"
    target = tmp_path / "target-memory"
    archive = tmp_path / "memory.tar.gz"
    _write_record(source, "semantic/user_preferences.md", "rec-a", "synthetic memory")
    (source / ".env").write_text("SHOULD_NOT_EXPORT=1", encoding="utf-8")
    (source / "agent_log.jsonl").write_text("SHOULD_NOT_EXPORT", encoding="utf-8")
    (source / "sessions").mkdir()
    (source / "sessions" / "private.txt").write_text("SHOULD_NOT_EXPORT", encoding="utf-8")
    (source / "runs").mkdir()
    (source / "runs" / "private.txt").write_text("SHOULD_NOT_EXPORT", encoding="utf-8")

    export_result = export_memory_archive(source, archive)
    assert export_result.written is True
    assert archive.exists()
    with tarfile.open(archive, "r:gz") as tf:
        names = set(tf.getnames())
    assert "semantic/user_preferences.md" in names
    assert ".env" not in names
    assert "agent_log.jsonl" not in names
    assert not any(name.startswith("sessions/") for name in names)
    assert not any(name.startswith("runs/") for name in names)

    dry_run = import_memory_archive(archive, target, dry_run=True)
    assert dry_run.would_write is True
    assert not target.exists()

    applied = import_memory_archive(archive, target, dry_run=False)
    assert applied.written is True
    restored = parse_memory_file(target / "semantic" / "user_preferences.md")
    assert restored[0]["id"] == "rec-a"
    assert restored[0]["_content"] == "synthetic memory"


def test_import_archive_rejects_path_traversal(tmp_path: Path):
    """非法 archive 必须 fail closed，不能写出 memory_root。"""
    from agent.memory_archive import import_memory_archive

    archive = tmp_path / "bad.tar.gz"
    outside = tmp_path / "outside.md"
    with tarfile.open(archive, "w:gz") as tf:
        payload = tmp_path / "payload.md"
        payload.write_text("bad", encoding="utf-8")
        tf.add(payload, arcname="../outside.md")

    with pytest.raises(ValueError, match="unsafe archive member"):
        import_memory_archive(archive, tmp_path / "target", dry_run=False)
    assert not outside.exists()
