"""FilesystemMemoryStore TDD contract tests.

覆盖:
  - parser (valid / malformed / empty / multi-section)
  - index rebuild
  - apply_operation_intent (RETAIN / UPDATE / FORGET / USE_ONCE)
  - get_record / list_records
  - recall API (scope / recency / memory_type / hybrid)
  - grouped topic file 组织
  - 与 MemoryStoreProtocol 兼容
  - 与 build_memory_snapshot_from_store 集成
  - 回退 / fallback behavior
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from agent.memory_contracts import MemoryScope
from agent.memory_operations import (
    MemoryAuditSummary,
    MemoryConfirmationChoice,
    MemoryConfirmationStatus,
    MemoryDecisionType,
    MemoryOperationIntent,
    MemoryOperationType,
)


# ── helpers ────────────────────────────────────────────────────────────────

def _make_intent(*, operation_type=MemoryOperationType.RETAIN, content="test content",
                 scope=MemoryScope.USER, source_summary="test source",
                 safety_summary="safe", user_visible="test summary",
                 confirmation=MemoryConfirmationStatus.APPROVED,
                 decision_type=MemoryDecisionType.RETAIN,
                 sensitive=False,
                 user_choice=MemoryConfirmationChoice.ACCEPT) -> MemoryOperationIntent:
    return MemoryOperationIntent(
        operation_type=operation_type,
        decision_type=decision_type,
        content_summary=content,
        scope=scope,
        source_summary=source_summary,
        safety_summary=safety_summary,
        user_visible_summary=user_visible,
        confirmation_status=confirmation,
        sensitive_redacted=sensitive,
        user_choice=user_choice,
    )


def _make_audit(intent: MemoryOperationIntent, user_choice="accept") -> MemoryAuditSummary:
    return MemoryAuditSummary(
        operation_type=intent.operation_type.value,
        decision_type=intent.decision_type.value,
        source_summary=intent.source_summary,
        safety_summary=intent.safety_summary,
        user_visible_summary=intent.user_visible_summary,
        sensitive_redacted=intent.sensitive_redacted,
        user_choice=user_choice,
    )


@pytest.fixture
def tmp_store_dir():
    """每次测试使用独立 temp dir，避免 cross-test 污染。"""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


# ── lazy import (避免模块不存在时 import 失败) ────────────────────────────

@pytest.fixture
def FSStore(tmp_store_dir):
    """返回 FilesystemMemoryStore 实例（如果模块存在）。"""
    try:
        from agent.memory_fs_store import FilesystemMemoryStore
    except ImportError:
        pytest.skip("FilesystemMemoryStore 尚未实现")
    return FilesystemMemoryStore(root_dir=tmp_store_dir)


@pytest.fixture
def FSParser():
    """返回 frontmatter parser 函数。"""
    try:
        from agent.memory_fs_store import parse_frontmatter
    except ImportError:
        pytest.skip("parse_frontmatter 尚未实现")
    return parse_frontmatter


# ═══════════════════════════════════════════════════════════════════════════
# 1. Parser tests
# ═══════════════════════════════════════════════════════════════════════════

class TestParseFrontmatter:
    """YAML frontmatter parser — 只依赖 stdlib，不引入 pyyaml。"""

    def test_parse_valid(self, FSParser):
        text = """---
id: "mem:abc123"
memory_type: "semantic"
scope: "user"
---

用户喜欢用 pytest。"""
        meta, body = FSParser(text)
        assert meta["id"] == "mem:abc123"
        assert meta["memory_type"] == "semantic"
        assert meta["scope"] == "user"
        assert "pytest" in body

    def test_parse_no_frontmatter(self, FSParser):
        meta, body = FSParser("只是一段纯文本，没有 frontmatter。")
        assert meta == {}
        assert "纯文本" in body

    def test_parse_empty(self, FSParser):
        meta, body = FSParser("")
        assert meta == {}
        assert body == ""

    def test_parse_only_dashes(self, FSParser):
        meta, body = FSParser("---\n---")
        assert meta == {}
        assert body == ""

    def test_parse_numeric_values(self, FSParser):
        text = """---
id: "mem:001"
confidence: 0.85
---
高置信度记忆。"""
        meta, body = FSParser(text)
        assert meta["confidence"] == 0.85

    def test_parse_boolean_values(self, FSParser):
        text = """---
id: "mem:001"
sensitive_redacted: false
---
安全内容。"""
        meta, body = FSParser(text)
        assert meta["sensitive_redacted"] is False

    def test_parse_multi_section_file(self, FSParser, tmp_store_dir):
        """一个文件包含多个 --- 分隔的 memory section。"""
        from agent.memory_fs_store import write_memory_section
        filepath = tmp_store_dir / "test.md"

        section1 = dict(id="mem:001", memory_type="semantic", scope="user")
        section2 = dict(id="mem:002", memory_type="episodic", scope="project")
        write_memory_section(filepath, section1, "用户喜欢 pytest。")
        write_memory_section(filepath, section2, "上次忘记检查 None 导致空指针。")

        from agent.memory_fs_store import parse_memory_file
        records = parse_memory_file(filepath)
        assert len(records) == 2
        assert records[0]["id"] == "mem:001"
        assert records[1]["id"] == "mem:002"

    def test_parse_chinese_content(self, FSParser):
        text = """---
id: "mem:cn"
memory_type: "procedural"
scope: "user"
---

用户要求所有解释用简体中文，但代码保持英文。"""
        meta, body = FSParser(text)
        assert "简体中文" in body
        assert meta["memory_type"] == "procedural"

    def test_parse_special_characters(self, FSParser):
        text = """---
id: "mem:spec"
memory_type: "semantic"
---

Content with: colons, "quotes", 'apostrophes', dashes -- and arrows ->."""
        meta, body = FSParser(text)
        assert "colons" in body
        assert "quotes" in body

    def test_malformed_frontmatter_no_closing(self, FSParser):
        """只有开头的 --- 没有结尾的 ---."""
        text = """---
id: "mem:bad"
memory_type: "semantic"
scope: "user"
没有结尾的 frontmatter。"""
        meta, body = FSParser(text)
        # 应该返回空 meta，所有内容视为 body
        assert "id" not in meta or meta == {}

    def test_empty_frontmatter_body(self, FSParser):
        text = """---
id: "mem:empty"
---

"""
        meta, body = FSParser(text)
        assert meta["id"] == "mem:empty"
        assert body.strip() == ""


# ═══════════════════════════════════════════════════════════════════════════
# 2. Index tests
# ═══════════════════════════════════════════════════════════════════════════

class TestIndex:
    """Index build / rebuild / consistency。"""

    def test_build_index_from_empty_dir(self, FSStore, tmp_store_dir):
        from agent.memory_fs_store import build_fs_index
        index = build_fs_index(tmp_store_dir)
        assert index == {}
        # build_fs_index always writes index.json (even for empty directories)
        index_path = tmp_store_dir / "_meta" / "index.json"
        assert index_path.exists()
        import json
        payload = json.loads(index_path.read_text())
        assert payload["total"] == 0

    def test_build_index_from_files(self, FSStore, tmp_store_dir):
        """从已存在的 .md 文件重建 index。"""
        # 先写入几个 memory section
        from agent.memory_fs_store import write_memory_section
        filepath = tmp_store_dir / "semantic" / "user_preferences.md"
        filepath.parent.mkdir(parents=True, exist_ok=True)

        section1 = dict(id="mem:a", memory_type="semantic", scope="user",
                        source_type="agent_suggested", approval_status="approved",
                        confidence=0.8, stability="stable",
                        created_at="2026-05-11T10:00:00Z", updated_at="2026-05-11T10:00:00Z",
                        sensitive_redacted="false",
                        created_by_operation="retain", updated_by_operation="retain",
                        source_summary="test a", safety_summary="safe", audit_id="audit:1")
        section2 = dict(id="mem:b", memory_type="semantic", scope="user",
                        source_type="explicit_user_request", approval_status="approved",
                        confidence=0.9, stability="stable",
                        created_at="2026-05-10T10:00:00Z", updated_at="2026-05-10T10:00:00Z",
                        sensitive_redacted="false",
                        created_by_operation="retain", updated_by_operation="retain",
                        source_summary="test b", safety_summary="safe", audit_id="audit:2")

        write_memory_section(filepath, section1, "喜欢 pytest")
        write_memory_section(filepath, section2, "喜欢中文解释架构")

        from agent.memory_fs_store import build_fs_index
        index = build_fs_index(tmp_store_dir)
        assert len(index) == 2
        assert "mem:a" in index
        assert "mem:b" in index
        assert index["mem:a"]["file"] == "semantic/user_preferences.md"

    def test_index_json_written_on_build(self, FSStore, tmp_store_dir):
        """build_fs_index 应写出 _meta/index.json。"""
        from agent.memory_fs_store import build_fs_index, write_memory_section
        filepath = tmp_store_dir / "semantic" / "user_facts.md"
        filepath.parent.mkdir(parents=True, exist_ok=True)
        section = dict(id="mem:x", memory_type="semantic", scope="user",
                       source_type="agent_suggested", approval_status="approved",
                       confidence=0.7, stability="stable",
                       created_at="2026-05-11T10:00:00Z", updated_at="2026-05-11T10:00:00Z",
                       sensitive_redacted="false",
                       created_by_operation="retain", updated_by_operation="retain",
                       source_summary="test", safety_summary="safe", audit_id="audit:x")
        write_memory_section(filepath, section, "content x")

        build_fs_index(tmp_store_dir)
        index_path = tmp_store_dir / "_meta" / "index.json"
        assert index_path.exists()
        loaded = json.loads(index_path.read_text())
        assert loaded["total"] == 1

    def test_rebuild_index_repairs_corruption(self, FSStore, tmp_store_dir):
        """如果 index.json 被破坏，rebuild 应从 .md 文件恢复。"""
        from agent.memory_fs_store import build_fs_index, write_memory_section
        # 创建 memory 文件
        filepath = tmp_store_dir / "semantic" / "project_rules.md"
        filepath.parent.mkdir(parents=True, exist_ok=True)
        section = dict(id="mem:rule1", memory_type="semantic", scope="project",
                       source_type="heuristic", approval_status="approved",
                       confidence=0.75, stability="stable",
                       created_at="2026-05-11T10:00:00Z", updated_at="2026-05-11T10:00:00Z",
                       sensitive_redacted="false",
                       created_by_operation="retain", updated_by_operation="retain",
                       source_summary="rule", safety_summary="safe", audit_id="audit:r")
        write_memory_section(filepath, section, "所有 API 必须 version prefix")

        # 先建好 index
        build_fs_index(tmp_store_dir)

        # 破坏 index.json
        (tmp_store_dir / "_meta" / "index.json").write_text("{corrupted json")

        # rebuild 应从文件恢复
        index = build_fs_index(tmp_store_dir)
        assert len(index) == 1
        assert "mem:rule1" in index


# ═══════════════════════════════════════════════════════════════════════════
# 3. Store operations tests
# ═══════════════════════════════════════════════════════════════════════════

class TestStoreOperations:
    """apply_operation_intent / get_record / list_records。"""

    def test_retain_creates_file(self, FSStore):
        intent = _make_intent(content="用户偏好 pytest", scope=MemoryScope.USER)
        audit = _make_audit(intent)
        result = FSStore.apply_operation_intent(intent, audit)
        assert result.status.value == "applied"

        # 验证文件已创建
        records = FSStore.list_records()
        assert len(records) == 1
        assert "pytest" in records[0].content

    def test_get_record(self, FSStore):
        intent = _make_intent(content="用户是数据工程师", scope=MemoryScope.USER)
        audit = _make_audit(intent)
        result = FSStore.apply_operation_intent(intent, audit)
        record_id = result.record.id
        retrieved = FSStore.get_record(record_id)
        assert retrieved is not None
        assert "数据工程师" in retrieved.content

    def test_get_record_not_found(self, FSStore):
        assert FSStore.get_record("nonexistent") is None

    def test_forget_removes_record(self, FSStore):
        intent = _make_intent(content="临时信息")
        audit = _make_audit(intent)
        result = FSStore.apply_operation_intent(intent, audit)
        record_id = result.record.id
        assert FSStore.get_record(record_id) is not None

        forget_intent = _make_intent(
            operation_type=MemoryOperationType.FORGET,
            content="临时信息",
            source_summary="test source",
        )
        forget_audit = _make_audit(forget_intent, user_choice="accept")
        forget_result = FSStore.apply_operation_intent(forget_intent, forget_audit)

        assert forget_result.status.value == "applied"
        assert FSStore.get_record(record_id) is None

    def test_update_modifies_content(self, FSStore):
        intent = _make_intent(content="原始内容", scope=MemoryScope.USER)
        audit = _make_audit(intent)
        result = FSStore.apply_operation_intent(intent, audit)
        record_id = result.record.id

        update_intent = _make_intent(
            operation_type=MemoryOperationType.UPDATE,
            content="更新后的内容",
            scope=MemoryScope.USER,
            source_summary="test source",
        )
        update_audit = _make_audit(update_intent, user_choice="accept")
        update_result = FSStore.apply_operation_intent(update_intent, update_audit)

        assert update_result.status.value == "applied"
        updated = FSStore.get_record(record_id)
        assert updated is not None
        assert "更新后" in updated.content

    def test_use_once_stores_session_only(self, FSStore):
        intent = _make_intent(
            operation_type=MemoryOperationType.USE_ONCE,
            content="仅本次会话",
            confirmation=MemoryConfirmationStatus.SESSION_ONLY,
            user_choice=MemoryConfirmationChoice.SESSION_ONLY,
        )
        audit = _make_audit(intent, user_choice=MemoryConfirmationChoice.SESSION_ONLY.value)
        result = FSStore.apply_operation_intent(intent, audit)
        assert result.status.value == "applied"
        assert result.record.approval_status == "session_only"

    def test_list_records_persists_across_instances(self, tmp_store_dir):
        """写完后创建新的 store 实例，应能通过 index rebuild 读到数据。"""
        try:
            from agent.memory_fs_store import FilesystemMemoryStore
        except ImportError:
            pytest.skip("FilesystemMemoryStore 尚未实现")

        store1 = FilesystemMemoryStore(root_dir=tmp_store_dir)
        intent = _make_intent(content="跨实例持久化测试", scope=MemoryScope.USER)
        audit = _make_audit(intent)
        result = store1.apply_operation_intent(intent, audit)
        assert result.status.value == "applied"

        # 创建新实例（模拟 process restart）
        store2 = FilesystemMemoryStore(root_dir=tmp_store_dir)
        records = store2.list_records()
        assert len(records) == 1
        assert "跨实例持久化" in records[0].content

    def test_skip_non_writing_operations(self, FSStore):
        intent = _make_intent(operation_type=MemoryOperationType.REJECT, content="不应该写入",
                              user_choice=MemoryConfirmationChoice.REJECT)
        audit = _make_audit(intent, user_choice=MemoryConfirmationChoice.REJECT.value)
        result = FSStore.apply_operation_intent(intent, audit)
        assert result.status.value == "skipped"

    def test_reject_mutating_without_approval(self, FSStore):
        intent = _make_intent(
            operation_type=MemoryOperationType.RETAIN,
            content="未批准",
            confirmation=MemoryConfirmationStatus.NEEDS_CLARIFICATION,
            user_choice=MemoryConfirmationChoice.CLARIFY,
        )
        audit = _make_audit(intent, user_choice=MemoryConfirmationChoice.CLARIFY.value)
        audit = MemoryAuditSummary(
            operation_type=audit.operation_type,
            decision_type=audit.decision_type,
            source_summary=audit.source_summary,
            safety_summary=audit.safety_summary,
            user_visible_summary=audit.user_visible_summary,
            sensitive_redacted=audit.sensitive_redacted,
            user_choice=MemoryConfirmationChoice.CLARIFY.value,
        )
        result = FSStore.apply_operation_intent(intent, audit)
        assert result.status.value == "rejected"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Recall API tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRecall:
    """scope / recency / memory_type recall。"""

    @pytest.fixture
    def populated_store(self, tmp_store_dir):
        """写入 5 条不同 scope 和 type 的 memory。"""
        try:
            from agent.memory_fs_store import FilesystemMemoryStore
        except ImportError:
            pytest.skip("FilesystemMemoryStore 尚未实现")
        store = FilesystemMemoryStore(root_dir=tmp_store_dir)

        memories = [
            (_make_intent(content="用户喜欢 pytest", scope=MemoryScope.USER, source_summary="偏好 pytest"), None),
            (_make_intent(content="项目禁止 any type", scope=MemoryScope.PROJECT, source_summary="禁止 any"), None),
            (_make_intent(content="repo 用 black 格式化", scope=MemoryScope.REPO, source_summary="black 格式化"), None),
            (_make_intent(content="用户用 macOS", scope=MemoryScope.USER, source_summary="macOS 偏好"), None),
            (_make_intent(content="项目选 FastAPI", scope=MemoryScope.PROJECT, source_summary="FastAPI 选择"), None),
        ]
        for intent, _ in memories:
            audit = _make_audit(intent)
            store.apply_operation_intent(intent, audit)
        return store

    def test_recall_by_scope(self, populated_store):
        results = populated_store.recall(scope=MemoryScope.USER, max_items=10)
        assert len(results) == 2
        for r in results:
            assert r.scope == MemoryScope.USER

    def test_recall_by_memory_type(self, populated_store):
        results = populated_store.recall(memory_type="semantic", max_items=10)
        assert len(results) == 5  # all are semantic by default

    def test_recall_max_items(self, populated_store):
        results = populated_store.recall(max_items=2)
        assert len(results) == 2

    def test_recall_empty_result(self, populated_store):
        results = populated_store.recall(scope=MemoryScope.SESSION, max_items=10)
        assert len(results) == 0

    def test_recall_recency_order(self, populated_store):
        """最近写入的 memory 应排在前面。"""
        results = populated_store.recall(max_items=5)
        assert len(results) >= 2
        # 最近写入的是 "项目选 FastAPI"（最后一个）
        # 但由于 scope 和 sort key 可能不同，只验证排序是稳定的
        created_ats = [r.metadata.get("created_at", "") for r in results]
        assert created_ats == sorted(created_ats, reverse=True)

    def test_recall_hybrid(self, populated_store):
        results = populated_store.recall(scope=MemoryScope.PROJECT, memory_type="semantic", max_items=5)
        assert len(results) == 2
        for r in results:
            assert r.scope == MemoryScope.PROJECT
            assert r.memory_type == "semantic"


# ═══════════════════════════════════════════════════════════════════════════
# 5. MemoryStoreProtocol compatibility
# ═══════════════════════════════════════════════════════════════════════════

class TestProtocolCompatibility:
    """确保 FS store 可以作为 drop-in replacement for InMemoryMemoryStore。"""

    def test_conforms_to_protocol(self, FSStore):
        # MemoryStoreProtocol is not @runtime_checkable, verify duck-typing
        assert hasattr(FSStore, "apply_operation_intent")
        assert hasattr(FSStore, "get_record")
        assert hasattr(FSStore, "list_records")
        assert callable(FSStore.apply_operation_intent)
        assert callable(FSStore.get_record)
        assert callable(FSStore.list_records)

    def test_works_with_snapshot_generator(self, FSStore):
        """确保 build_memory_snapshot_from_store 可以消费 FS store。"""
        from agent.memory_snapshot_generator import (
            MemorySnapshotBuildOptions,
            build_memory_snapshot_from_store,
        )

        intent = _make_intent(content="快照测试内容", scope=MemoryScope.USER)
        audit = _make_audit(intent)
        FSStore.apply_operation_intent(intent, audit)

        options = MemorySnapshotBuildOptions(selection_reason="test", max_items=10)
        snapshot = build_memory_snapshot_from_store(FSStore, options)
        assert len(snapshot.items) == 1
        assert "快照测试" in snapshot.items[0].content

    def test_list_records_signature_match(self, FSStore):
        """list_records 返回类型应兼容现有调用方。"""
        records = FSStore.list_records()
        assert isinstance(records, tuple)
        for r in records:
            from agent.memory_store import MemoryRecord
            assert isinstance(r, MemoryRecord)


# ═══════════════════════════════════════════════════════════════════════════
# 6. Topic routing tests
# ═══════════════════════════════════════════════════════════════════════════

class TestTopicRouting:
    """memory 按 memory_type + scope 路由到正确的 grouped topic file。"""

    def test_semantic_user_routes_to_user_preferences(self, FSStore, tmp_store_dir):
        intent = _make_intent(content="用户喜欢 pytest", scope=MemoryScope.USER)
        audit = _make_audit(intent)
        FSStore.apply_operation_intent(intent, audit)
        assert (tmp_store_dir / "semantic" / "user_preferences.md").exists()

    def test_semantic_project_routes_to_project_rules(self, FSStore, tmp_store_dir):
        intent = _make_intent(content="项目禁止 any type", scope=MemoryScope.PROJECT)
        audit = _make_audit(intent)
        FSStore.apply_operation_intent(intent, audit)
        assert (tmp_store_dir / "semantic" / "project_rules.md").exists()

    def test_semantic_repo_routes_to_repo_conventions(self, FSStore, tmp_store_dir):
        intent = _make_intent(content="用 black 格式化", scope=MemoryScope.REPO)
        audit = _make_audit(intent)
        FSStore.apply_operation_intent(intent, audit)
        assert (tmp_store_dir / "semantic" / "repo_conventions.md").exists()

    def test_episodic_routes_to_date_file(self, FSStore):
        from agent.memory_fs_store import _route_topic
        path = _route_topic("episodic", MemoryScope.PROJECT)
        assert path.startswith("episodic/")
        assert path.endswith(".md")

    def test_procedural_routes_to_learned(self, FSStore):
        from agent.memory_fs_store import _route_topic
        path = _route_topic("procedural", MemoryScope.USER)
        assert path == "procedural/learned.md"


# ═══════════════════════════════════════════════════════════════════════════
# 7. Edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """边界和异常场景。"""

    def test_empty_store_list(self, FSStore):
        records = FSStore.list_records()
        assert records == ()

    def test_non_existent_dir_created(self, tmp_store_dir):
        try:
            from agent.memory_fs_store import FilesystemMemoryStore
        except ImportError:
            pytest.skip("FilesystemMemoryStore 尚未实现")
        new_dir = tmp_store_dir / "new_subdir" / "memory"
        FilesystemMemoryStore(root_dir=new_dir)
        assert new_dir.exists()

    def test_utf8_content(self, FSStore):
        content = "用户喜欢用 🦀 Rust 写系统工具，但日常用 🐍 Python。"
        intent = _make_intent(content=content, scope=MemoryScope.USER)
        audit = _make_audit(intent)
        result = FSStore.apply_operation_intent(intent, audit)
        record = FSStore.get_record(result.record.id)
        assert "🦀" in record.content or "Rust" in record.content

    def test_very_long_content(self, FSStore):
        content = "长内容。" * 500  # ~2000 chars
        intent = _make_intent(content=content, scope=MemoryScope.USER)
        audit = _make_audit(intent)
        result = FSStore.apply_operation_intent(intent, audit)
        record = FSStore.get_record(result.record.id)
        assert len(record.content) > 1000

    def test_special_yaml_chars_in_content(self, FSStore):
        """content 中的 : # { } [ ] 不应破坏 YAML parsing。"""
        content = '用户说: "用 dict[key] = {a: 1, b: 2} 这种写法" — 注意冒号和花括号。'
        intent = _make_intent(content=content, scope=MemoryScope.USER)
        audit = _make_audit(intent)
        result = FSStore.apply_operation_intent(intent, audit)
        record = FSStore.get_record(result.record.id)
        assert "dict[key]" in record.content

    def test_forget_then_rebuild_index(self, FSStore, tmp_store_dir):
        """删除后 rebuild index，确认记录消失。"""
        from agent.memory_fs_store import build_fs_index

        intent = _make_intent(content="待删除内容")
        audit = _make_audit(intent)
        result = FSStore.apply_operation_intent(intent, audit)
        record_id = result.record.id

        forget_intent = _make_intent(
            operation_type=MemoryOperationType.FORGET,
            content="待删除内容",
            source_summary="test source",
        )
        forget_audit = _make_audit(forget_intent, user_choice="accept")
        FSStore.apply_operation_intent(forget_intent, forget_audit)

        # rebuild index
        index = build_fs_index(tmp_store_dir)
        assert record_id not in index
