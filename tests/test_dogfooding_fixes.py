"""Dogfooding Fix Pass 1 测试：dedup / parser robustness / forget identity。

本轮只修 dogfooding 暴露出的确定性、低风险问题，不改变 governance、不引入新 architecture。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.memory_contracts import MemoryDecisionType, MemoryScope
from agent.memory_operations import (
    MemoryOperationIntent,
    MemoryOperationType,
    build_memory_audit_summary,
)
from agent.memory_confirmation import MemoryConfirmationChoice, MemoryConfirmationStatus
from agent.memory_fs_store import (
    FilesystemMemoryStore,
    parse_memory_file,
    write_memory_section,
)
from agent.memory_store import (
    InMemoryMemoryStore,
    MemoryRecord,
    MemoryStoreApplyStatus,
    MemoryStoreApplyResult,
    find_duplicate_record,
    find_record_by_content,
)
from agent.memory_snapshot_generator import (
    MemorySnapshotBuildOptions,
    build_memory_snapshot_from_store,
)


# ═══════════════════════════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _retain_intent(
    content: str,
    *,
    memory_type: str = "semantic",
    source_type: str = "explicit_user_request",
    scope: MemoryScope = MemoryScope.USER,
    source_summary: str | None = None,
) -> MemoryOperationIntent:
    """构造一个已确认的 RETAIN intent，用于直接测试 store 层。"""
    return MemoryOperationIntent(
        operation_type=MemoryOperationType.RETAIN,
        decision_type=MemoryDecisionType.RETAIN,
        content_summary=content,
        scope=scope,
        source_summary=source_summary or f"test:{content[:30]}",
        safety_summary="safe",
        user_visible_summary=f"记住: {content[:30]}",
        confirmation_status=MemoryConfirmationStatus.APPROVED,
        sensitive_redacted=False,
        user_choice=MemoryConfirmationChoice.ACCEPT,
        memory_type=memory_type,
        source_type=source_type,
    )


def _apply_retain(store, content: str, **kwargs) -> MemoryStoreApplyResult:
    intent = _retain_intent(content, **kwargs)
    audit = build_memory_audit_summary(intent)
    return store.apply_operation_intent(intent, audit)


# ═══════════════════════════════════════════════════════════════════════════════
# Fix 1: Dedup
# ═══════════════════════════════════════════════════════════════════════════════


class TestDedupInMemory:
    """InMemoryMemoryStore 的去重行为。"""

    def test_duplicate_semantic_retain_returns_existing(self) -> None:
        """相同 content + memory_type + scope 的 retain 不重复写入。"""
        store = InMemoryMemoryStore()
        r1 = _apply_retain(store, "用户偏好 pytest")
        assert r1.status is MemoryStoreApplyStatus.APPLIED
        assert len(store.list_records()) == 1

        # 第二次 retain 相同内容 → dedup hit
        r2 = _apply_retain(store, "用户偏好 pytest")
        assert r2.status is MemoryStoreApplyStatus.APPLIED
        assert "dedup_hit" in r2.message
        assert r2.record is r1.record  # 返回已有 record
        assert len(store.list_records()) == 1  # 未增加

    def test_different_memory_type_not_deduped(self) -> None:
        """不同 memory_type 的相同内容视为不同 record。"""
        store = InMemoryMemoryStore()
        # 不同 source_summary 避免 InMemory store 的 record_id 碰撞
        r1 = _apply_retain(store, "项目规范：用 black", memory_type="procedural",
                           source_summary="suggestion:procedural:black")
        r2 = _apply_retain(store, "项目规范：用 black", memory_type="semantic",
                           source_summary="explicit:semantic:black")
        assert r1.status is MemoryStoreApplyStatus.APPLIED
        assert r2.status is MemoryStoreApplyStatus.APPLIED
        assert "dedup_hit" not in r2.message
        assert len(store.list_records()) == 2

    def test_different_scope_not_deduped(self) -> None:
        """不同 scope 的相同内容视为不同 record。"""
        store = InMemoryMemoryStore()
        r1 = _apply_retain(store, "项目规范：用 ruff", scope=MemoryScope.USER,
                           source_summary="test:user:ruff")
        r2 = _apply_retain(store, "项目规范：用 ruff", scope=MemoryScope.PROJECT,
                           source_summary="test:project:ruff")
        assert r1.status is MemoryStoreApplyStatus.APPLIED
        assert r2.status is MemoryStoreApplyStatus.APPLIED
        assert "dedup_hit" not in r2.message
        assert len(store.list_records()) == 2

    def test_whitespace_normalization_in_dedup(self) -> None:
        """前后空白不影响去重（内部空白统一）。"""
        store = InMemoryMemoryStore()
        _apply_retain(store, "  用户偏好 pytest  ")
        r2 = _apply_retain(store, "用户偏好 pytest")
        assert "dedup_hit" in r2.message
        assert len(store.list_records()) == 1

    def test_snapshot_no_duplicates_after_dedup(self) -> None:
        """去重后 snapshot 不包含重复 record。"""
        store = InMemoryMemoryStore()
        _apply_retain(store, "偏好 A")
        _apply_retain(store, "偏好 A")  # dedup hit
        _apply_retain(store, "偏好 B")

        options = MemorySnapshotBuildOptions(selection_reason="test", max_items=10)
        snapshot = build_memory_snapshot_from_store(store, options)
        assert len(snapshot.items) == 2
        contents = [item.content for item in snapshot.items]
        assert contents.count("偏好 A") == 1


class TestDedupFilesystem:
    """FilesystemMemoryStore 的去重行为。"""

    @pytest.fixture(autouse=True)
    def tmp_store(self, tmp_path: Path) -> None:
        self.store = FilesystemMemoryStore(root_dir=tmp_path / "memory")

    def test_duplicate_retain_returns_existing(self) -> None:
        r1 = _apply_retain(self.store, "用户偏好 pytest")
        assert "dedup_hit" not in r1.message
        assert len(self.store.list_records()) == 1

        r2 = _apply_retain(self.store, "用户偏好 pytest")
        assert "dedup_hit" in r2.message
        assert r2.record is not None
        assert r2.record.content == "用户偏好 pytest"
        assert len(self.store.list_records()) == 1

    def test_dedup_after_rebuild(self) -> None:
        """重建索引后去重仍然生效。"""
        _apply_retain(self.store, "偏好 vim")

        # 模拟新 session：新建 store 实例（重建索引）
        store2 = FilesystemMemoryStore(root_dir=self.store.root_dir)
        assert len(store2.list_records()) == 1

        r = _apply_retain(store2, "偏好 vim")
        assert "dedup_hit" in r.message
        assert len(store2.list_records()) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Fix 2: Parser robustness
# ═══════════════════════════════════════════════════════════════════════════════


class TestParserRobustness:
    """parse_memory_file 的稳健性。"""

    def test_standard_format(self, tmp_path: Path) -> None:
        """标准格式正常解析。"""
        f = tmp_path / "test.md"
        meta = {"id": "rec1", "memory_type": "semantic", "scope": "user"}
        write_memory_section(f, meta, "body1")
        write_memory_section(f, {"id": "rec2", "memory_type": "semantic", "scope": "user"}, "body2")

        records = parse_memory_file(f)
        assert len(records) == 2
        assert records[0]["_content"] == "body1"
        assert records[1]["_content"] == "body2"

    def test_manual_edit_format_missing_trailing_newline(self, tmp_path: Path) -> None:
        """手动编辑缺少 --- 后的换行时仍能解析。"""
        f = tmp_path / "test.md"
        # 模拟 DOGFOODING 中发现的手动编辑格式：``\\n\\n---\\n`` 而非 ``\\n\\n---\\n\\n``
        f.write_text("""---
id: "rec1"
memory_type: "semantic"
scope: "user"
source_type: "explicit_user_request"
---

body one

---
id: "rec2"
memory_type: "semantic"
scope: "user"
source_type: "explicit_user_request"
---

body two
""")
        records = parse_memory_file(f)
        assert len(records) == 2
        assert records[0]["_content"] == "body one"
        assert records[1]["_content"] == "body two"

    def test_extra_blank_lines_tolerated(self, tmp_path: Path) -> None:
        """多余空行不影响解析。"""
        f = tmp_path / "test.md"
        f.write_text("""---
id: "rec1"
memory_type: "semantic"
scope: "user"
---


body one



---
id: "rec2"
memory_type: "semantic"
scope: "user"
---


body two
""")
        records = parse_memory_file(f)
        assert len(records) == 2

    def test_malformed_section_isolated(self, tmp_path: Path) -> None:
        """一个损坏的 section 不阻止其他 section 解析。"""
        f = tmp_path / "test.md"
        f.write_text("""---
id: "rec1"
memory_type: "semantic"
scope: "user"
---

good body

---
this is not valid yaml at all
---


---
id: "rec2"
memory_type: "semantic"
scope: "user"
---

another good body
""")
        records = parse_memory_file(f)
        # rec1 和 rec2 都应该被解析，中间的损坏 section 被隔离
        assert len(records) >= 2
        contents = [r["_content"] for r in records]
        assert "good body" in contents
        assert "another good body" in contents

    def test_empty_file(self, tmp_path: Path) -> None:
        """空文件不崩溃。"""
        f = tmp_path / "test.md"
        f.write_text("")
        records = parse_memory_file(f)
        assert records == []

    def test_single_section_no_separator(self, tmp_path: Path) -> None:
        """单 section 文件正常解析。"""
        f = tmp_path / "test.md"
        f.write_text("""---
id: "rec1"
memory_type: "semantic"
scope: "user"
---

single body
""")
        records = parse_memory_file(f)
        assert len(records) == 1
        assert records[0]["_content"] == "single body"

    def test_remove_section_uses_robust_split(self, tmp_path: Path) -> None:
        """remove_memory_section 使用稳健分隔符，手动编辑格式仍可删除。"""
        from agent.memory_fs_store import remove_memory_section

        f = tmp_path / "test.md"
        f.write_text("""---
id: "rec1"
memory_type: "semantic"
scope: "user"
---

body one

---
id: "rec2"
memory_type: "semantic"
scope: "user"
---

body two
""")
        removed = remove_memory_section(f, "rec1")
        assert removed
        records = parse_memory_file(f)
        assert len(records) == 1
        assert records[0]["id"] == "rec2"


# ═══════════════════════════════════════════════════════════════════════════════
# Fix 3: Forget identity matching
# ═══════════════════════════════════════════════════════════════════════════════


class TestForgetIdentityMatching:
    """forget 按 content 匹配而非 source_summary 派生 ID。"""

    def test_forget_by_content_match_inmemory(self) -> None:
        """InMemory store：forget 按 content 找到并删除 record。"""
        store = InMemoryMemoryStore()
        _apply_retain(store, "用户喜欢 Python")
        assert len(store.list_records()) == 1

        # 构造 forget intent（content 与存储的 record 一致）
        forget_intent = MemoryOperationIntent(
            operation_type=MemoryOperationType.FORGET,
            decision_type=MemoryDecisionType.FORGET,
            content_summary="用户喜欢 Python",
            scope=MemoryScope.USER,
            source_summary="forget:用户喜欢 Python",
            safety_summary="safe",
            user_visible_summary="忘记: 用户喜欢 Python",
            confirmation_status=MemoryConfirmationStatus.APPROVED,
            sensitive_redacted=False,
            user_choice=MemoryConfirmationChoice.ACCEPT,
        )
        result = store.apply_operation_intent(forget_intent, build_memory_audit_summary(forget_intent))
        assert result.status is MemoryStoreApplyStatus.APPLIED
        assert len(store.list_records()) == 0

    def test_forget_by_content_match_filesystem(self, tmp_path: Path) -> None:
        """Filesystem store：forget 按 content 找到并删除 record。"""
        store = FilesystemMemoryStore(root_dir=tmp_path / "memory")
        _apply_retain(store, "用户喜欢 Python")
        assert len(store.list_records()) == 1

        forget_intent = MemoryOperationIntent(
            operation_type=MemoryOperationType.FORGET,
            decision_type=MemoryDecisionType.FORGET,
            content_summary="用户喜欢 Python",
            scope=MemoryScope.USER,
            source_summary="forget:test",
            safety_summary="safe",
            user_visible_summary="忘记",
            confirmation_status=MemoryConfirmationStatus.APPROVED,
            sensitive_redacted=False,
            user_choice=MemoryConfirmationChoice.ACCEPT,
        )
        result = store.apply_operation_intent(forget_intent, build_memory_audit_summary(forget_intent))
        assert result.status is MemoryStoreApplyStatus.APPLIED
        assert len(store.list_records()) == 0

    def test_forget_not_found_when_content_mismatch(self) -> None:
        """content 不匹配时返回 NOT_FOUND。"""
        store = InMemoryMemoryStore()
        _apply_retain(store, "用户喜欢 Python")

        forget_intent = MemoryOperationIntent(
            operation_type=MemoryOperationType.FORGET,
            decision_type=MemoryDecisionType.FORGET,
            content_summary="用户喜欢 Java",  # 不匹配
            scope=MemoryScope.USER,
            source_summary="forget:test",
            safety_summary="safe",
            user_visible_summary="忘记",
            confirmation_status=MemoryConfirmationStatus.APPROVED,
            sensitive_redacted=False,
            user_choice=MemoryConfirmationChoice.ACCEPT,
        )
        result = store.apply_operation_intent(forget_intent, build_memory_audit_summary(forget_intent))
        assert result.status is MemoryStoreApplyStatus.NOT_FOUND
        assert len(store.list_records()) == 1  # 未被删除

    def test_forget_procedural_memory(self) -> None:
        """procedural memory 的 forget 也按 content 匹配。"""
        store = InMemoryMemoryStore()
        _apply_retain(store, "项目必须用 black", memory_type="procedural")
        assert len(store.list_records()) == 1

        forget_intent = MemoryOperationIntent(
            operation_type=MemoryOperationType.FORGET,
            decision_type=MemoryDecisionType.FORGET,
            content_summary="项目必须用 black",
            scope=MemoryScope.USER,
            source_summary="forget:test",
            safety_summary="safe",
            user_visible_summary="忘记",
            confirmation_status=MemoryConfirmationStatus.APPROVED,
            sensitive_redacted=False,
            user_choice=MemoryConfirmationChoice.ACCEPT,
        )
        result = store.apply_operation_intent(forget_intent, build_memory_audit_summary(forget_intent))
        assert result.status is MemoryStoreApplyStatus.APPLIED
        assert len(store.list_records()) == 0

    def test_forget_deletes_correct_record_when_multiple_exist(self) -> None:
        """多条 record 中 forget 只删除 content 匹配的那一条。"""
        store = InMemoryMemoryStore()
        _apply_retain(store, "偏好 A")
        _apply_retain(store, "偏好 B")
        _apply_retain(store, "偏好 C")
        assert len(store.list_records()) == 3

        forget_intent = MemoryOperationIntent(
            operation_type=MemoryOperationType.FORGET,
            decision_type=MemoryDecisionType.FORGET,
            content_summary="偏好 B",
            scope=MemoryScope.USER,
            source_summary="forget:test",
            safety_summary="safe",
            user_visible_summary="忘记",
            confirmation_status=MemoryConfirmationStatus.APPROVED,
            sensitive_redacted=False,
            user_choice=MemoryConfirmationChoice.ACCEPT,
        )
        result = store.apply_operation_intent(forget_intent, build_memory_audit_summary(forget_intent))
        assert result.status is MemoryStoreApplyStatus.APPLIED
        assert len(store.list_records()) == 2
        contents = [r.content for r in store.list_records()]
        assert "偏好 A" in contents
        assert "偏好 B" not in contents
        assert "偏好 C" in contents


# ═══════════════════════════════════════════════════════════════════════════════
# helper 函数单元测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestHelperFunctions:
    """find_duplicate_record / find_record_by_content 的边界条件。"""

    def test_find_duplicate_returns_None_when_empty(self) -> None:
        assert find_duplicate_record("test", "semantic", MemoryScope.USER, []) is None

    def test_find_record_by_content_whitespace_insensitive(self) -> None:
        records = [
            MemoryRecord(
                id="r1", content="  hello world  ", scope=MemoryScope.USER,
                source_summary="s", safety_summary="s", audit_id="a",
                created_by_operation=MemoryOperationType.RETAIN,
                updated_by_operation=MemoryOperationType.RETAIN,
            )
        ]
        result = find_record_by_content("hello world", records)
        assert result is not None
        assert result.id == "r1"

    def test_find_duplicate_normalizes_internal_whitespace(self) -> None:
        """内部多余空白被统一，不影响去重匹配。"""
        records = [
            MemoryRecord(
                id="r1", content="hello   world", scope=MemoryScope.USER,
                source_summary="s", safety_summary="s", audit_id="a",
                created_by_operation=MemoryOperationType.RETAIN,
                updated_by_operation=MemoryOperationType.RETAIN,
                memory_type="semantic",
            )
        ]
        result = find_duplicate_record("hello  world", "semantic", MemoryScope.USER, records)
        assert result is not None
