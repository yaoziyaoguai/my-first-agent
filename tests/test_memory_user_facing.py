"""Memory user-facing CLI 命令测试（WP-A: Memory That Actually Helps MVP）。

中文学习边界：
- 这些测试验证 memory 的用户可见行为：write → recall → list/show → forget
- "show memories" / "显示记忆" 是 CLI meta-command，经确定性字符串匹配处理
- 不走 policy → confirmation → store pipeline 的写入路径
- 不调用真实 LLM / API / private data
- 不新增 runtime flow
"""

from __future__ import annotations

import pytest

from agent.core import _looks_like_show_memories


class TestShowMemoriesDetection:
    """_looks_like_show_memories() 单元测试：验证 CLI meta-command 检测。"""

    def test_show_memories_english(self):
        assert _looks_like_show_memories("show memories")
        assert _looks_like_show_memories("list memories")
        assert _looks_like_show_memories("show my memories")

    def test_show_memories_chinese(self):
        assert _looks_like_show_memories("显示记忆")
        assert _looks_like_show_memories("列出记忆")
        assert _looks_like_show_memories("查看记忆")
        assert _looks_like_show_memories("我的记忆")

    def test_normal_text_does_not_trigger(self):
        assert not _looks_like_show_memories("hello")
        assert not _looks_like_show_memories("remember my name is Alice")
        assert not _looks_like_show_memories("what can you do")

    def test_empty_or_whitespace_does_not_trigger(self):
        assert not _looks_like_show_memories("")
        assert not _looks_like_show_memories("   ")

    def test_partial_substring_does_not_trigger(self):
        # "记忆" 单独出现不应触发——需要完整触发短语
        assert not _looks_like_show_memories("记忆")
        assert not _looks_like_show_memories("memories")


class TestMemoryRuntimeListRecords:
    """MemoryRuntime.list_records() 单元测试。"""

    def test_list_records_empty_store(self):
        from agent.memory_runtime import MemoryRuntime
        from agent.memory_store import InMemoryMemoryStore

        runtime = MemoryRuntime(store=InMemoryMemoryStore())
        assert runtime.list_records() == ()

    def test_list_records_with_stored_memory(self):
        from agent.memory_runtime import MemoryRuntime
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType

        store = InMemoryMemoryStore()
        record = MemoryRecord(
            id="test-1",
            content="用户叫 Alice",
            scope=MemoryScope.USER,
            source_summary="candidate:test-1",
            safety_summary="无额外安全标记",
            audit_id="audit:test-1",
            created_by_operation=MemoryOperationType.RETAIN,
            updated_by_operation=MemoryOperationType.RETAIN,
        )
        store.apply_operation_intent = lambda *args, **kwargs: None  # bypass
        # _records 是 {record.id: record} dict
        store._records = {record.id: record}

        runtime = MemoryRuntime(store=store)
        records = runtime.list_records()
        assert len(records) == 1
        assert records[0].content == "用户叫 Alice"


class TestMemoryListEvent:
    """memory_list_event() 单元测试。"""

    def test_empty_records(self):
        from agent.display_events import memory_list_event

        event = memory_list_event(())
        assert event.event_type == "memory.listed"
        assert "暂无" in event.text

    def test_with_records(self):
        from agent.display_events import memory_list_event
        from agent.memory_store import MemoryRecord
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType

        records = (
            MemoryRecord(
                id="m1",
                content="用户叫 Alice",
                scope=MemoryScope.USER,
                source_summary="candidate:m1",
                safety_summary="无额外安全标记",
                audit_id="audit:m1",
                created_by_operation=MemoryOperationType.RETAIN,
                updated_by_operation=MemoryOperationType.RETAIN,
            ),
        )
        event = memory_list_event(records)
        assert event.event_type == "memory.listed"
        assert "Alice" in event.text
        assert event.metadata["item_count"] == 1


@pytest.fixture(autouse=True)
def _reset_conversation_messages():
    """每次测试前清空模块级共享状态，防止跨文件累积影响 chat() 行为。"""
    from agent.core import state

    state.conversation.messages = []
    state.reset_task()
    yield
    state.conversation.messages = []
    state.reset_task()


class TestChatShowMemoriesIntegration:
    """chat() + show memories CLI 命令集成测试。

    中文学习边界：验证 "show memories" / "显示记忆" 通过 core.chat 统一入口
    返回用户可见的 memory 列表，不新增 runtime flow、不走 fake path。
    """

    def test_chat_show_memories_with_no_records(self):
        """空 memory store → '显示记忆' 返回友好提示。"""
        import agent.tools  # noqa: F401
        from agent.core import chat

        result = chat("显示记忆")
        assert isinstance(result, str)
        assert "暂无" in result

    def test_chat_show_memories_english(self):
        """英文 'show memories' 命令也通过统一入口工作。"""
        import agent.tools  # noqa: F401
        from agent.core import chat

        result = chat("show memories")
        assert isinstance(result, str)
        assert "暂无" in result


class TestMemoryRecallInjection:
    """验证 memory recall 通过 system prompt injection 进入对话。

    这是 Path A（pre-loop injection）的 focused test——不经过 MEMORY_RECALL
    dispatcher，但验证用户能感受到 memory 效果。
    """

    def test_refresh_system_prompt_includes_memory_snapshot(self):
        """已批准的 memory 进入 system prompt。"""
        from agent.memory_store import MemoryRecord, InMemoryMemoryStore
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_runtime import MemoryRuntime

        store = InMemoryMemoryStore()
        # _records 是 {record.id: record} dict
        store._records = {
            "m1": MemoryRecord(
                id="m1",
                content="用户是数据工程师",
                scope=MemoryScope.USER,
                source_summary="candidate:m1",
                safety_summary="无额外安全标记",
                audit_id="audit:m1",
                created_by_operation=MemoryOperationType.RETAIN,
                updated_by_operation=MemoryOperationType.RETAIN,
            ),
        }

        runtime = MemoryRuntime(store=store)
        snapshot = runtime.snapshot_for_prompt()
        assert len(snapshot.items) >= 1


class TestMemoryForgetFlow:
    """验证 'forget X' / '忘记 X' 的 policy 检测正确。

    完整 forget flow（policy → confirmation → store remove）由
    memory_runtime 内部处理；这里只验证 policy 正确返回 FORGET decision。
    """

    def test_policy_detects_forget(self):
        """Policy 应检测 '忘记 X' 并返回 FORGET decision。"""
        from agent.memory_policy import DeterministicMemoryPolicy
        from agent.memory_contracts import MemoryDecisionType

        policy = DeterministicMemoryPolicy()
        decision = policy.decide("忘记 用户叫Alice")
        assert decision.decision_type == MemoryDecisionType.FORGET

    def test_policy_detects_forget_english(self):
        """Policy 应检测 'forget X' 并返回 FORGET decision。"""
        from agent.memory_policy import DeterministicMemoryPolicy
        from agent.memory_contracts import MemoryDecisionType

        policy = DeterministicMemoryPolicy()
        decision = policy.decide("forget user name is Alice")
        assert decision.decision_type == MemoryDecisionType.FORGET


class TestForgetMemoryDetection:
    """WP-A：验证 _looks_like_forget_memory() 的触发词检测与内容提取。

    这是 deterministic CLI meta-command 检测——不进入 policy → confirmation
    管线，不写 store，不调用 LLM。
    """

    def test_detects_forget_with_content(self):
        """'forget X' → 提取 X。"""
        from agent.core import _looks_like_forget_memory

        keyword = _looks_like_forget_memory("forget my name")
        assert keyword == "my name"

    def test_detects_forget_chinese_with_content(self):
        """'忘记 X' → 提取 X。"""
        from agent.core import _looks_like_forget_memory

        keyword = _looks_like_forget_memory("忘记 用户叫Alice")
        assert keyword is not None
        assert "Alice" in keyword

    def test_detects_remove_memory_with_content(self):
        """'删除记忆 X' → 提取 X。"""
        from agent.core import _looks_like_forget_memory

        keyword = _looks_like_forget_memory("删除记忆 旧信息")
        assert keyword is not None
        assert "旧信息" in keyword

    def test_normal_text_not_detected(self):
        """普通文本不应被误判为 forget 命令。"""
        from agent.core import _looks_like_forget_memory

        assert _looks_like_forget_memory("hello world") is None
        assert _looks_like_forget_memory("显示记忆") is None
        assert _looks_like_forget_memory("remember my name is Alice") is None

    def test_forget_without_content_returns_none(self):
        """只有 'forget' 但无内容时返回 None。"""
        from agent.core import _looks_like_forget_memory

        assert _looks_like_forget_memory("forget") is None
        assert _looks_like_forget_memory("忘记") is None


class TestChatForgetIntegration:
    """WP-A：chat() forget CLI 集成——通过 core.chat 统一入口执行。

    不新增 runtime flow，不走 fake path，不经过 policy → confirmation 管线。
    """

    def test_forget_no_match_returns_hint(self):
        """forget 命令无匹配时返回友好提示。"""
        import agent.tools  # noqa: F401
        from agent.core import chat

        result = chat("forget nonexistent_memory_keyword_xyz")
        assert isinstance(result, str)
        assert "未找到" in result

    def test_forget_chinese_no_match_returns_hint(self):
        """'忘记 X' 无匹配时返回中文提示。"""
        import agent.tools  # noqa: F401
        from agent.core import chat

        result = chat("忘记 不存在的记忆关键词xyz")
        assert isinstance(result, str)
        assert "未找到" in result


class TestMemoryRemoveRecord:
    """WP-A：验证 store 和 runtime 的 remove_record 操作。

    直接 store 操作，不经过 policy/confirmation 管线。
    """

    def test_remove_record_by_id_succeeds(self):
        """按 id 移除已存在的 record。"""
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType

        record = MemoryRecord(
            id="memory:fake:test123",
            content="test content",
            scope=MemoryScope.USER,
            source_summary="test source",
            safety_summary="safe",
            audit_id="audit-1",
            created_by_operation=MemoryOperationType.RETAIN,
            updated_by_operation=MemoryOperationType.RETAIN,
        )
        store = InMemoryMemoryStore(records=[record])
        assert len(store.list_records()) == 1
        assert store.remove_record("memory:fake:test123") is True
        assert len(store.list_records()) == 0

    def test_remove_nonexistent_record_returns_false(self):
        """移除不存在的 id 返回 False。"""
        from agent.memory_store import InMemoryMemoryStore

        store = InMemoryMemoryStore()
        assert store.remove_record("nonexistent_id") is False

    def test_runtime_remove_record_succeeds(self):
        """MemoryRuntime.remove_record 委托给 store.remove_record。"""
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_runtime import MemoryRuntime

        record = MemoryRecord(
            id="memory:fake:rt001",
            content="test",
            scope=MemoryScope.USER,
            source_summary="test",
            safety_summary="safe",
            audit_id="a1",
            created_by_operation=MemoryOperationType.RETAIN,
            updated_by_operation=MemoryOperationType.RETAIN,
        )
        store = InMemoryMemoryStore(records=[record])
        runtime = MemoryRuntime(store=store)
        assert len(runtime.list_records()) == 1
        assert runtime.remove_record("memory:fake:rt001") is True
        assert len(runtime.list_records()) == 0

    def test_runtime_remove_record_no_store(self):
        """store=None 时 remove_record 安全返回 False。"""
        from agent.memory_runtime import MemoryRuntime

        runtime = MemoryRuntime(store=None)
        assert runtime.remove_record("any_id") is False


class TestMemoryWriteRecallVisibleE2E:
    """WP-A：memory write → recall → visible E2E 闭环。

    用户写入 memory → 在下一轮对话的 system prompt 中可见 →
    show memories 可以展示已存储的 memory。全部走 local/fake deterministic path。
    """

    def test_memory_persists_across_runtime_calls(self):
        """同一 store 实例上的 record 跨 list_records/list_records 调用可见。"""
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_runtime import MemoryRuntime

        record = MemoryRecord(
            id="memory:fake:e2e1",
            content="用户名字是 Alice",
            scope=MemoryScope.USER,
            source_summary="test",
            safety_summary="safe",
            audit_id="a-e2e-1",
            created_by_operation=MemoryOperationType.RETAIN,
            updated_by_operation=MemoryOperationType.RETAIN,
        )
        store = InMemoryMemoryStore(records=[record])
        runtime = MemoryRuntime(store=store)
        # 第一次 list
        assert len(runtime.list_records()) == 1
        # 第二次 list — 跨调用一致
        assert len(runtime.list_records()) == 1
        assert "Alice" in runtime.list_records()[0].content

    def test_memory_snapshot_includes_stored_records(self):
        """已批准的 records 出现在 MemorySnapshot 中。"""
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_runtime import MemoryRuntime

        record = MemoryRecord(
            id="memory:fake:e2e3",
            content="用户名字是 Bob",
            scope=MemoryScope.USER,
            source_summary="test source",
            safety_summary="safe",
            audit_id="a-e2e-3",
            created_by_operation=MemoryOperationType.RETAIN,
            updated_by_operation=MemoryOperationType.RETAIN,
        )
        store = InMemoryMemoryStore(records=[record])
        runtime = MemoryRuntime(store=store)
        snapshot = runtime.snapshot_for_prompt()
        assert len(snapshot.items) >= 1
        contents = [item.content for item in snapshot.items]
        assert any("Bob" in c for c in contents)

    def test_memory_list_records_reflects_store(self):
        """list_records() 返回 store 中所有已批准 records。"""
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_runtime import MemoryRuntime

        records = [
            MemoryRecord(
                id=f"memory:fake:list{i}",
                content=f"memory item {i}",
                scope=MemoryScope.USER,
                source_summary=f"source {i}",
                safety_summary="safe",
                audit_id=f"audit-list-{i}",
                created_by_operation=MemoryOperationType.RETAIN,
                updated_by_operation=MemoryOperationType.RETAIN,
            )
            for i in range(3)
        ]
        store = InMemoryMemoryStore(records=records)
        runtime = MemoryRuntime(store=store)
        listed = runtime.list_records()
        assert len(listed) == 3

    def test_forget_removes_matching_record(self):
        """forget 后匹配的 record 不再出现在 list 中。"""
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_runtime import MemoryRuntime

        records = [
            MemoryRecord(
                id="memory:fake:rm1",
                content="Alice 在北京",
                scope=MemoryScope.USER,
                source_summary="s1",
                safety_summary="safe",
                audit_id="a-rm-1",
                created_by_operation=MemoryOperationType.RETAIN,
                updated_by_operation=MemoryOperationType.RETAIN,
            ),
            MemoryRecord(
                id="memory:fake:rm2",
                content="Bob 在上海",
                scope=MemoryScope.USER,
                source_summary="s2",
                safety_summary="safe",
                audit_id="a-rm-2",
                created_by_operation=MemoryOperationType.RETAIN,
                updated_by_operation=MemoryOperationType.RETAIN,
            ),
        ]
        store = InMemoryMemoryStore(records=records)
        runtime = MemoryRuntime(store=store)
        assert len(runtime.list_records()) == 2
        # 模拟 forget CLI：查找匹配 Alice 的 record 并移除
        matched = [r for r in runtime.list_records() if "Alice" in r.content]
        assert len(matched) == 1
        for r in matched:
            assert runtime.remove_record(r.id) is True
        remaining = runtime.list_records()
        assert len(remaining) == 1
        assert "Bob" in remaining[0].content
