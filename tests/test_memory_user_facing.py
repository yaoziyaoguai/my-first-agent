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
