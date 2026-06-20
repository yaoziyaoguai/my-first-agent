"""Phase 6 source evidence loader 的边界测试。

这些测试验证 RFC Phase 6 source evidence loader 的只读 evidence 装载边界，
不验证 semantic consolidation quality，也不运行 detector。

测试覆盖：
- 从 filesystem store 加载 episodic record 为 EpisodicEvidence
- 非 episodic record 被过滤
- rejected / pending / session_only / ephemeral / sensitive 记录被过滤
- malformed record 被跳过并产生 warning
- content 为空的记录被跳过
- confidence / created_at / tags 等 metadata 保留
- loader 只读，不写 store，不调 detector，不调 LLM
"""

from pathlib import Path

import pytest

from agent.memory_consolidation import EpisodicEvidence
from agent.memory_consolidation_loader import (
    SourceEvidenceLoadResult,
    _should_skip,
    _to_episodic_evidence,
    load_episodic_evidence,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _write_memory_file(
    root: Path,
    rel_path: str,
    sections: list[dict],
) -> Path:
    """在 filesystem store 根目录下写入一个 .md 文件。

    每个 section 是一个 dict：key 为 frontmatter 字段（不含 _content），
    特殊键 '_content' 为 body 文本。

    Args:
        root: store 根目录
        rel_path: 相对于 root 的 .md 文件路径
        sections: frontmatter dict 列表，每个 dict 的 '_content' 键为 body

    Returns:
        写入的文件路径
    """
    filepath = root / rel_path
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # MemoryRecord 强制字段的测试默认值（_record_from_frontmatter 要求非空）
    _record_defaults = {
        "source_summary": "test-source",
        "safety_summary": "safe",
        "audit_id": "audit:test:0000",
    }

    parts: list[str] = []
    for meta in sections:
        # 为缺失的 MemoryRecord 强制字段注入默认值，避免 _record_from_frontmatter 抛 ValueError
        for key, default_val in _record_defaults.items():
            if key not in meta:
                meta[key] = default_val
        content = meta.pop("_content", "")
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
        parts.append("\n".join(lines))

    filepath.write_text("\n\n---\n\n".join(parts), encoding="utf-8")
    return filepath


def _make_fs_store(tmp_path: Path, sections_by_file: dict[str, list[dict]] | None = None):
    """创建测试用 FilesystemMemoryStore。

    Args:
        tmp_path: pytest tmp_path fixture
        sections_by_file: {文件路径: [section dicts]}，如果 None 则创建空 store

    Returns:
        FilesystemMemoryStore 实例
    """
    from agent.memory_fs_store import FilesystemMemoryStore

    root = tmp_path / "memory_store"
    root.mkdir(parents=True, exist_ok=True)

    if sections_by_file:
        for rel_path, sections in sections_by_file.items():
            _write_memory_file(root, rel_path, sections)

    return FilesystemMemoryStore(root_dir=root)


@pytest.fixture
def empty_store(tmp_path: Path):
    """空 filesystem store（无任何记录）。"""
    return _make_fs_store(tmp_path)


@pytest.fixture
def store_with_episodic(tmp_path: Path):
    """含一条标准 episodic record 的 store。"""
    return _make_fs_store(tmp_path, {
        "episodic/2026-05-13.md": [{
            "id": "ep-001",
            "memory_type": "episodic",
            "scope": "user",
            "source_type": "session_end_extraction",
            "approval_status": "auto_retained",
            "confidence": 0.78,
            "stability": "stable",
            "created_at": "2026-05-13T10:00:00Z",
            "updated_at": "2026-05-13T10:00:00Z",
            "tags": "pytest,testing",
            "_content": "用户偏好使用 pytest 作为 Python 测试框架",
        }],
    })


# ── 加载结果结构 ──────────────────────────────────────────────────────────────


class TestSourceEvidenceLoadResult:
    """SourceEvidenceLoadResult 数据结构的正确性。"""

    def test_empty_result(self):
        result = SourceEvidenceLoadResult(evidence=(), skipped_count=0, warnings=())
        assert result.total_loaded == 0
        assert result.total_seen == 0
        assert result.evidence == ()

    def test_with_evidence(self):
        ev = EpisodicEvidence(record_id="ep-1", content="test")
        result = SourceEvidenceLoadResult(
            evidence=(ev,), skipped_count=2, warnings=("w1", "w2"),
        )
        assert result.total_loaded == 1
        assert result.total_seen == 3
        assert len(result.warnings) == 2

    def test_frozen_immutable(self):
        from dataclasses import FrozenInstanceError
        result = SourceEvidenceLoadResult(evidence=(), skipped_count=0, warnings=())
        with pytest.raises(FrozenInstanceError):
            result.skipped_count = 5  # type: ignore[misc]


# ── 基本装载 ──────────────────────────────────────────────────────────────────


class TestBasicLoading:
    """从 filesystem store 基本装载 episodic evidence。"""

    def test_loads_episodic_record(self, store_with_episodic):
        """episodic record 被正确转换为 EpisodicEvidence。"""
        result = load_episodic_evidence(store_with_episodic)
        assert result.total_loaded == 1
        assert result.skipped_count == 0
        ev = result.evidence[0]
        assert ev.record_id == "ep-001"
        assert "pytest" in ev.content
        assert ev.scope == "user"

    def test_empty_store_returns_empty(self, empty_store):
        """空 store 返回空 evidence 列表。"""
        result = load_episodic_evidence(empty_store)
        assert result.total_loaded == 0
        assert result.skipped_count == 0

    def test_confidence_preserved(self, tmp_path):
        """confidence 从 metadata 正确传递到 EpisodicEvidence。"""
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [{
                "id": "ep-conf",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "confidence": 0.85,
                "stability": "stable",
                "created_at": "2026-05-13T10:00:00Z",
                "_content": "test content",
            }],
        })
        result = load_episodic_evidence(store)
        assert result.total_loaded == 1
        assert result.evidence[0].confidence == 0.85

    def test_confidence_none_when_missing(self, tmp_path):
        """metadata 无 confidence 时 EpisodicEvidence.confidence 为 store 默认值。

        注：FilesystemMemoryStore._record_from_frontmatter 会为缺失的 confidence
        填充默认值 0.5，因此 loader 层面看到的是 0.5 而非 None。
        真正缺失 confidence 的场景需要 store 层支持 nullable confidence。
        """
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [{
                "id": "ep-no-conf",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "stability": "stable",
                "_content": "test content",
                # 不写 confidence 字段 → store 默认 0.5
            }],
        })
        result = load_episodic_evidence(store)
        assert result.total_loaded == 1
        # store 默认填充 confidence=0.5
        assert result.evidence[0].confidence == 0.5

    def test_created_at_preserved(self, tmp_path):
        """created_at 从 metadata 正确传递。"""
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [{
                "id": "ep-time",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "stability": "stable",
                "created_at": "2026-05-12T08:30:00Z",
                "_content": "test content",
            }],
        })
        result = load_episodic_evidence(store)
        assert result.evidence[0].created_at == "2026-05-12T08:30:00Z"

    def test_tags_preserved(self, tmp_path):
        """tags 从 metadata 正确传递为 tuple。"""
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [{
                "id": "ep-tags",
                "memory_type": "episodic",
                "scope": "project",
                "approval_status": "auto_retained",
                "stability": "stable",
                "created_at": "2026-05-13T10:00:00Z",
                "tags": "pytest, testing, ci",
                "_content": "test content",
            }],
        })
        result = load_episodic_evidence(store)
        assert result.total_loaded == 1
        # 当前实现：string tags 作为单个 tuple 元素
        assert len(result.evidence[0].tags) > 0

    def test_multiple_episodic_records(self, tmp_path):
        """多条 episodic record 全部加载。"""
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-12.md": [{
                "id": "ep-a",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "stability": "stable",
                "created_at": "2026-05-12T10:00:00Z",
                "_content": "event A",
            }],
            "episodic/2026-05-13.md": [{
                "id": "ep-b",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "stability": "stable",
                "created_at": "2026-05-13T10:00:00Z",
                "_content": "event B",
            }],
        })
        result = load_episodic_evidence(store)
        assert result.total_loaded == 2
        ids = {e.record_id for e in result.evidence}
        assert ids == {"ep-a", "ep-b"}

    def test_max_items_limit(self, tmp_path):
        """max_items 限制返回 evidence 数量。"""
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [{
                "id": f"ep-{i}",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "stability": "stable",
                "created_at": f"2026-05-13T10:0{i}:00Z",
                "_content": f"event {i}",
            } for i in range(5)],
        })
        result = load_episodic_evidence(store, max_items=2)
        assert result.total_loaded == 2


# ── 过滤：非 episodic ────────────────────────────────────────────────────────


class TestNonEpisodicFiltered:
    """非 episodic 类型的 record 不应进入 evidence。"""

    def test_semantic_excluded(self, tmp_path):
        """semantic record 被跳过。"""
        store = _make_fs_store(tmp_path, {
            "semantic/user_preferences.md": [{
                "id": "sem-001",
                "memory_type": "semantic",
                "scope": "user",
                "approval_status": "approved",
                "_content": "用户偏好 pytest",
            }],
        })
        result = load_episodic_evidence(store)
        assert result.total_loaded == 0
        assert result.skipped_count == 1
        assert any("non episodic" in w.lower() or "semantic" in w for w in result.warnings)

    def test_procedural_excluded(self, tmp_path):
        """procedural record 被跳过。"""
        store = _make_fs_store(tmp_path, {
            "procedural/learned.md": [{
                "id": "proc-001",
                "memory_type": "procedural",
                "scope": "user",
                "approval_status": "approved",
                "_content": "以后必须先跑测试再提交",
            }],
        })
        result = load_episodic_evidence(store)
        assert result.total_loaded == 0
        assert result.skipped_count == 1


# ── 过滤：approval_status ───────────────────────────────────────────────────


class TestRejectedFiltered:
    """rejected 记录不进入 evidence。"""

    def test_rejected_excluded(self, tmp_path):
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [{
                "id": "ep-rej",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "rejected",
                "stability": "stable",
                "_content": "被拒绝的 episodic",
            }],
        })
        result = load_episodic_evidence(store)
        assert result.total_loaded == 0
        assert result.skipped_count == 1


class TestPendingFiltered:
    """pending proposal 不进入 evidence。"""

    def test_pending_excluded(self, tmp_path):
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [{
                "id": "ep-pend",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "pending",
                "stability": "stable",
                "_content": "待确认的 episodic proposal",
            }],
        })
        result = load_episodic_evidence(store)
        assert result.total_loaded == 0
        assert result.skipped_count == 1


class TestSessionOnlyFiltered:
    """session_only（USE_ONCE / transient）记录不进入 evidence。"""

    def test_session_only_excluded(self, tmp_path):
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [{
                "id": "ep-so",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "session_only",
                "stability": "stable",
                "_content": "仅当次会话有效的 episodic",
            }],
        })
        result = load_episodic_evidence(store)
        assert result.total_loaded == 0
        assert result.skipped_count == 1


# ── 过滤：ephemeral / transient ──────────────────────────────────────────────


class TestEphemeralFiltered:
    """ephemeral stability 记录不进入 evidence。"""

    def test_ephemeral_excluded(self, tmp_path):
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [{
                "id": "ep-eph",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "stability": "ephemeral",
                "_content": "一次性 episodic",
            }],
        })
        result = load_episodic_evidence(store)
        assert result.total_loaded == 0
        assert result.skipped_count == 1


# ── 过滤：sensitive / secret ─────────────────────────────────────────────────


class TestSensitiveFiltered:
    """sensitive_redacted 记录不进入 evidence。"""

    def test_sensitive_redacted_excluded(self, tmp_path):
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [{
                "id": "ep-sens",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "stability": "stable",
                "sensitive_redacted": True,
                "_content": "涉密 episodic",
            }],
        })
        result = load_episodic_evidence(store)
        assert result.total_loaded == 0
        assert result.skipped_count == 1

    def test_sensitive_redacted_false_not_excluded(self, tmp_path):
        """sensitive_redacted=False 的记录不被过滤。"""
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [{
                "id": "ep-ok",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "stability": "stable",
                "sensitive_redacted": False,
                "_content": "普通 episodic",
            }],
        })
        result = load_episodic_evidence(store)
        assert result.total_loaded == 1


# ── 过滤：空 content ─────────────────────────────────────────────────────────


class TestEmptyContentFiltered:
    """content 为空的记录被跳过。"""

    def test_empty_content_skipped(self, tmp_path):
        """空 content 的记录在 parse_memory_file 层被自然过滤。

        FilesystemMemoryStore.parse_memory_file 的 ``if meta and content:`` 检查
        会将空 content 的 section 直接丢弃，不进入 index。
        因此 loader 层面看不到这些记录——这是 store 解析层的自然行为。
        loader 的 _should_skip 仍保留空 content 检查作为 defense-in-depth。
        """
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [{
                "id": "ep-empty",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "stability": "stable",
                "_content": "",
            }],
        })
        result = load_episodic_evidence(store)
        # 空 content 被 parse_memory_file 的自然过滤行为拦截，不在 index 中
        assert result.total_loaded == 0
        # parser 层自然过滤，不产生 warning
        assert result.skipped_count == 0

    def test_whitespace_content_skipped(self, tmp_path):
        """纯空白 content 同样被 parse_memory_file 层自然过滤。"""
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [{
                "id": "ep-ws",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "stability": "stable",
                "_content": "   ",
            }],
        })
        result = load_episodic_evidence(store)
        assert result.total_loaded == 0
        assert result.skipped_count == 0


# ── malformed records ────────────────────────────────────────────────────────


class TestMalformedRecords:
    """malformed record 被跳过并产生 warning，不导致整个 load 失败。"""

    def test_missing_id_skipped(self, tmp_path):
        """缺少 id 的记录（index 中不会有 entry，所以不会被 list_records 返回）。

        实际上 index 构建时会过滤无 id 的 section，所以这类记录根本不会出现在
        list_records() 结果中——loader 天然不会见到它们。
        """
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [
                {
                    "id": "ep-ok",
                    "memory_type": "episodic",
                    "scope": "user",
                    "approval_status": "auto_retained",
                    "stability": "stable",
                    "created_at": "2026-05-13T10:00:00Z",
                    "_content": "正常记录",
                },
                {
                    # 无 id —— index 构建时自然跳过
                    "memory_type": "episodic",
                    "scope": "user",
                    "approval_status": "auto_retained",
                    "stability": "stable",
                    "_content": "无 id 的记录",
                },
            ],
        })
        result = load_episodic_evidence(store)
        # 只有有 id 的那条被加载
        assert result.total_loaded == 1
        assert result.evidence[0].record_id == "ep-ok"

    def test_mixed_valid_and_invalid(self, tmp_path):
        """混合有效和无效记录，有效记录正常加载，无效记录不影响。"""
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [
                {
                    "id": "ep-ok",
                    "memory_type": "episodic",
                    "scope": "user",
                    "approval_status": "auto_retained",
                    "stability": "stable",
                    "created_at": "2026-05-13T10:00:00Z",
                    "_content": "正常记录",
                },
                {
                    "id": "ep-rej",
                    "memory_type": "episodic",
                    "scope": "user",
                    "approval_status": "rejected",
                    "stability": "stable",
                    "_content": "被拒绝的记录",
                },
            ],
        })
        result = load_episodic_evidence(store)
        assert result.total_loaded == 1
        assert result.evidence[0].record_id == "ep-ok"
        assert result.skipped_count == 1


# ── store 只读 ───────────────────────────────────────────────────────────────


class TestStoreReadOnly:
    """loader 不写 store，不修改 index.json，不做任何变更。"""

    def test_store_unchanged_after_load(self, tmp_path):
        """loader 调用后 store 的 index 和文件均不变。"""
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [{
                "id": "ep-001",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "stability": "stable",
                "created_at": "2026-05-13T10:00:00Z",
                "_content": "test content",
            }],
        })
        record_count_before = len(store.list_records())
        index_before = dict(store._index) if hasattr(store, "_index") else None

        load_episodic_evidence(store)

        # 验证 record 数量未变
        assert len(store.list_records()) == record_count_before
        # 验证 index 未被修改
        if index_before is not None:
            assert store._index == index_before

    def test_no_new_files_created(self, tmp_path):
        """loader 不在 store 目录下创建新文件。"""
        store = _make_fs_store(tmp_path, {
            "episodic/2026-05-13.md": [{
                "id": "ep-001",
                "memory_type": "episodic",
                "scope": "user",
                "approval_status": "auto_retained",
                "stability": "stable",
                "created_at": "2026-05-13T10:00:00Z",
                "_content": "test content",
            }],
        })
        files_before = set(
            str(p.relative_to(store.root_dir))
            for p in store.root_dir.rglob("*")
            if p.is_file()
        )

        load_episodic_evidence(store)

        files_after = set(
            str(p.relative_to(store.root_dir))
            for p in store.root_dir.rglob("*")
            if p.is_file()
        )
        assert files_after == files_before


# ── 不调 detector / LLM ─────────────────────────────────────────────────────


class TestNoDetectorOrLLM:
    """loader 不调用 detector，不调用 LLM。"""

    def test_no_detector_import(self):
        """loader 模块不 import detector。"""
        import ast
        with open("agent/memory_consolidation_loader.py") as f:
            tree = ast.parse(f.read())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        assert "agent.memory_consolidation_engine" not in imports

    def test_no_llm_import(self):
        """loader 不 import anthropic / openai。"""
        import ast
        with open("agent/memory_consolidation_loader.py") as f:
            tree = ast.parse(f.read())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        assert "anthropic" not in imports
        assert "openai" not in imports


# ── _should_skip 单元测试 ───────────────────────────────────────────────────


class TestShouldSkipUnit:
    """_should_skip 过滤函数的单元测试。"""

    def test_episodic_auto_retained_not_skipped(self):
        """episodic + auto_retained 记录不应被跳过。"""
        from dataclasses import dataclass

        @dataclass
        class FakeRecord:
            memory_type: str = "episodic"
            approval_status: str = "auto_retained"
            sensitive_redacted: bool = False
            id: str = "f1"
            content: str = "test content"
            metadata: dict | None = None

        skip, reason = _should_skip(FakeRecord())
        assert skip is False
        assert reason is None

    def test_semantic_skipped(self):
        from dataclasses import dataclass

        @dataclass
        class FakeRecord:
            memory_type: str = "semantic"
            approval_status: str = "approved"
            sensitive_redacted: bool = False
            id: str = "f2"
            content: str = "test"
            metadata: dict | None = None

        skip, reason = _should_skip(FakeRecord())
        assert skip is True
        assert reason is not None

    def test_rejected_skipped(self):
        from dataclasses import dataclass

        @dataclass
        class FakeRecord:
            memory_type: str = "episodic"
            approval_status: str = "rejected"
            sensitive_redacted: bool = False
            id: str = "f3"
            content: str = "test"
            metadata: dict | None = None

        skip, reason = _should_skip(FakeRecord())
        assert skip is True

    def test_pending_skipped(self):
        from dataclasses import dataclass

        @dataclass
        class FakeRecord:
            memory_type: str = "episodic"
            approval_status: str = "pending"
            sensitive_redacted: bool = False
            id: str = "f4"
            content: str = "test"
            metadata: dict | None = None

        skip, reason = _should_skip(FakeRecord())
        assert skip is True

    def test_session_only_skipped(self):
        from dataclasses import dataclass

        @dataclass
        class FakeRecord:
            memory_type: str = "episodic"
            approval_status: str = "session_only"
            sensitive_redacted: bool = False
            id: str = "f5"
            content: str = "test"
            metadata: dict | None = None

        skip, reason = _should_skip(FakeRecord())
        assert skip is True

    def test_ephemeral_stability_skipped(self):
        from dataclasses import dataclass, field

        @dataclass
        class FakeRecord:
            memory_type: str = "episodic"
            approval_status: str = "auto_retained"
            sensitive_redacted: bool = False
            id: str = "f6"
            content: str = "test"
            metadata: dict = field(default_factory=dict)

        skip, reason = _should_skip(FakeRecord(metadata={"stability": "ephemeral"}))
        assert skip is True

    def test_sensitive_redacted_skipped(self):
        from dataclasses import dataclass

        @dataclass
        class FakeRecord:
            memory_type: str = "episodic"
            approval_status: str = "auto_retained"
            sensitive_redacted: bool = True
            id: str = "f7"
            content: str = "test"
            metadata: dict | None = None

        skip, reason = _should_skip(FakeRecord())
        assert skip is True

    def test_empty_content_skipped(self):
        from dataclasses import dataclass

        @dataclass
        class FakeRecord:
            memory_type: str = "episodic"
            approval_status: str = "auto_retained"
            sensitive_redacted: bool = False
            id: str = "f8"
            content: str = ""
            metadata: dict | None = None

        skip, reason = _should_skip(FakeRecord())
        assert skip is True


# ── _to_episodic_evidence 单元测试 ──────────────────────────────────────────


class TestToEpisodicEvidence:
    """_to_episodic_evidence 字段映射单元测试。"""

    def test_basic_mapping(self):
        from dataclasses import dataclass

        @dataclass
        class FakeScope:
            value: str = "user"

        @dataclass
        class FakeRecord:
            id: str = "ep-map"
            content: str = "mapped content"
            scope: object | None = None
            metadata: dict | None = None
            sensitive_redacted: bool = False

        record = FakeRecord(scope=FakeScope("project"))
        ev = _to_episodic_evidence(record)
        assert ev.record_id == "ep-map"
        assert ev.content == "mapped content"
        assert ev.scope == "project"

    def test_scope_none(self):
        from dataclasses import dataclass

        @dataclass
        class FakeRecord:
            id: str = "ep-noscope"
            content: str = "content"
            scope: object | None = None
            metadata: dict | None = None
            sensitive_redacted: bool = False

        ev = _to_episodic_evidence(FakeRecord())
        assert ev.scope is None

    def test_confidence_from_metadata(self):
        from dataclasses import dataclass

        @dataclass
        class FakeRecord:
            id: str = "ep-conf"
            content: str = "content"
            scope: object | None = None
            metadata: dict | None = None
            sensitive_redacted: bool = False

        record = FakeRecord(metadata={"confidence": 0.92})
        ev = _to_episodic_evidence(record)
        assert ev.confidence == 0.92

    def test_created_at_from_metadata(self):
        from dataclasses import dataclass

        @dataclass
        class FakeRecord:
            id: str = "ep-time"
            content: str = "content"
            scope: object | None = None
            metadata: dict | None = None
            sensitive_redacted: bool = False

        record = FakeRecord(metadata={"created_at": "2026-05-13T09:00:00Z"})
        ev = _to_episodic_evidence(record)
        assert ev.created_at == "2026-05-13T09:00:00Z"
