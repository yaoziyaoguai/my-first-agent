"""测试 create_memory_runtime 的 MEMORY_STORE_BACKEND 选择逻辑。"""

from __future__ import annotations

import pytest

from agent.memory_runtime import create_memory_runtime
from agent.memory_store import InMemoryMemoryStore


class TestDefaultBackend:
    """默认 backend 行为。"""

    def test_default_is_in_memory_store(self, monkeypatch):
        monkeypatch.delenv("MEMORY_STORE_BACKEND", raising=False)
        rt = create_memory_runtime()
        assert isinstance(rt._store, InMemoryMemoryStore)

    def test_explicit_memory_is_in_memory_store(self, monkeypatch):
        monkeypatch.setenv("MEMORY_STORE_BACKEND", "memory")
        rt = create_memory_runtime()
        assert isinstance(rt._store, InMemoryMemoryStore)

    def test_in_memory_alias_is_in_memory_store(self, monkeypatch):
        for alias in ("in_memory", "inmemory"):
            monkeypatch.setenv("MEMORY_STORE_BACKEND", alias)
            rt = create_memory_runtime()
            assert isinstance(rt._store, InMemoryMemoryStore)

    def test_explicit_store_param_bypasses_env(self, monkeypatch):
        monkeypatch.setenv("MEMORY_STORE_BACKEND", "filesystem")
        explicit = InMemoryMemoryStore()
        rt = create_memory_runtime(store=explicit)
        assert rt._store is explicit


class TestFilesystemBackend:
    """MEMORY_STORE_BACKEND=filesystem 行为。"""

    def test_filesystem_backend_uses_filesystem_store(self, monkeypatch):
        monkeypatch.setenv("MEMORY_STORE_BACKEND", "filesystem")
        from agent.memory_fs_store import FilesystemMemoryStore

        rt = create_memory_runtime()
        assert isinstance(rt._store, FilesystemMemoryStore)

    def test_memory_fs_alias_uses_filesystem_store(self, monkeypatch):
        monkeypatch.setenv("MEMORY_STORE_BACKEND", "memory_fs")
        from agent.memory_fs_store import FilesystemMemoryStore

        rt = create_memory_runtime()
        assert isinstance(rt._store, FilesystemMemoryStore)

    def test_fs_alias_uses_filesystem_store(self, monkeypatch):
        monkeypatch.setenv("MEMORY_STORE_BACKEND", "fs")
        from agent.memory_fs_store import FilesystemMemoryStore

        rt = create_memory_runtime()
        assert isinstance(rt._store, FilesystemMemoryStore)


class TestInvalidBackend:
    """无效 MEMORY_STORE_BACKEND 值报错。"""

    def test_invalid_backend_raises_value_error(self, monkeypatch):
        monkeypatch.setenv("MEMORY_STORE_BACKEND", "vector_db")
        with pytest.raises(ValueError, match="MEMORY_STORE_BACKEND"):
            create_memory_runtime()

    def test_empty_backend_raises_value_error(self, monkeypatch):
        monkeypatch.setenv("MEMORY_STORE_BACKEND", "")
        with pytest.raises(ValueError, match="MEMORY_STORE_BACKEND"):
            create_memory_runtime()


class TestFilesystemStoreIntegration:
    """Filesystem backend 的读写功能。"""

    def test_filesystem_store_can_write_and_recall(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MEMORY_STORE_BACKEND", "filesystem")
        from agent.memory_confirmation import MemoryConfirmationChoice, MemoryConfirmationStatus
        from agent.memory_contracts import MemoryDecisionType, MemoryScope
        from agent.memory_operations import (
            MemoryOperationIntent,
            MemoryOperationType,
            build_memory_audit_summary,
        )

        # 让 FS store 写到 tmp_path 避免污染真实目录
        import agent.memory_fs_store as mfs

        original_init = mfs.FilesystemMemoryStore.__init__

        def tmp_init(self, root_dir=None):
            original_init(self, root_dir=tmp_path / "memory")

        monkeypatch.setattr(mfs.FilesystemMemoryStore, "__init__", tmp_init)
        rt = create_memory_runtime()

        intent = MemoryOperationIntent(
            operation_type=MemoryOperationType.RETAIN,
            decision_type=MemoryDecisionType.RETAIN,
            content_summary="用户喜欢 pytest",
            scope=MemoryScope.USER,
            source_summary="偏好 pytest",
            safety_summary="safe",
            user_visible_summary="记住偏好",
            confirmation_status=MemoryConfirmationStatus.APPROVED,
            sensitive_redacted=False,
            user_choice=MemoryConfirmationChoice.ACCEPT,
        )
        audit = build_memory_audit_summary(intent)
        rt._store.apply_operation_intent(intent, audit)

        records = rt._store.list_records()
        assert len(records) == 1
        assert "pytest" in records[0].source_summary

        recalled = rt._store.recall(scope="user")
        assert len(recalled) >= 1
        assert recalled[0].source_summary == "偏好 pytest"

        # 验证 .md 文件确实落在磁盘上
        md_files = list((tmp_path / "memory").glob("**/*.md"))
        assert len(md_files) >= 1


class TestMemoryRoot:
    """MEMORY_STORE_ROOT / MEMORY_ROOT 控制 FilesystemMemoryStore 落盘路径。"""

    def test_memory_store_root_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MEMORY_STORE_BACKEND", "filesystem")
        root = tmp_path / "custom_store_root"
        monkeypatch.setenv("MEMORY_STORE_ROOT", str(root))
        from agent.memory_fs_store import FilesystemMemoryStore

        store = FilesystemMemoryStore()
        assert store.root_dir == root
        assert root.exists()

    def test_memory_root_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MEMORY_STORE_BACKEND", "filesystem")
        root = tmp_path / "custom_root"
        monkeypatch.setenv("MEMORY_ROOT", str(root))
        from agent.memory_fs_store import FilesystemMemoryStore

        store = FilesystemMemoryStore()
        assert store.root_dir == root

    def test_explicit_root_overrides_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MEMORY_STORE_BACKEND", "filesystem")
        monkeypatch.setenv("MEMORY_STORE_ROOT", "/ignored")
        explicit = tmp_path / "explicit_root"
        from agent.memory_fs_store import FilesystemMemoryStore

        store = FilesystemMemoryStore(root_dir=explicit)
        assert store.root_dir == explicit

    def test_no_permission_dir_raises_oserror(self, monkeypatch, tmp_path):
        """不可创建的目录抛出 OSError，不静默降级。"""
        monkeypatch.setenv("MEMORY_STORE_BACKEND", "filesystem")
        # /dev/null 是文件不是目录，mkdir(parents=True) 会失败
        monkeypatch.setenv("MEMORY_STORE_ROOT", "/dev/null/memory")
        from agent.memory_fs_store import FilesystemMemoryStore

        with pytest.raises(OSError, match="无法创建"):
            FilesystemMemoryStore()
