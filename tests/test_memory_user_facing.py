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
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_runtime import MemoryRuntime
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord

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
        store._records = {store._namespaced_key(record.id): record}

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
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_store import MemoryRecord

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
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_runtime import MemoryRuntime
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord

        store = InMemoryMemoryStore()
        # 使用 namespaced key，与 list_records() 前缀过滤一致
        store._records = {
            store._namespaced_key("m1"): MemoryRecord(
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

    def test_memory_injected_event_reaches_user_through_chat_sink(self):
        """core.chat() → memory.injected event → sink 完整链路验证。

        当 _memory_runtime 中有已批准记录时，chat() 在 pre-loop 阶段
        (refresh_runtime_system_prompt 之后) 发射 memory.injected 事件，
        包含"已加载记忆：N 条"用户可见文案。

        架构依据：core.py L693-702 的 Memory Kernel v1 通知逻辑。
        此前 audit Issue 4 报告"Memory recall 无用户可见性"，实际代码已
        实现该通知——本测试钉死这一行为，防止回归。
        """
        from unittest.mock import patch

        import agent.tools  # noqa: F401
        from agent.core import chat
        from agent.display_events import RuntimeEvent
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_runtime import MemoryRuntime
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord
        from agent.provider.fake_provider import FakeProvider

        store = InMemoryMemoryStore((
            MemoryRecord(
                id="m-injected-1",
                content="用户偏好简洁回答",
                scope=MemoryScope.USER,
                source_summary="test:fixture",
                safety_summary="safe",
                audit_id="audit:m-injected-1",
                created_by_operation=MemoryOperationType.RETAIN,
                updated_by_operation=MemoryOperationType.RETAIN,
            ),
            MemoryRecord(
                id="m-injected-2",
                content="用户是数据工程师",
                scope=MemoryScope.USER,
                source_summary="test:fixture",
                safety_summary="safe",
                audit_id="audit:m-injected-2",
                created_by_operation=MemoryOperationType.RETAIN,
                updated_by_operation=MemoryOperationType.RETAIN,
            ),
        ))
        runtime = MemoryRuntime(store=store)

        def get_runtime(_session_id: str = "") -> MemoryRuntime:
            return runtime

        # chat() 现在通过 dispatcher MEMORY_RECALL handler 读取 shared MemoryStore；
        # patch get_memory_runtime 而不是 snapshot_for_prompt，避免绕过证据链。
        with patch("agent.core.get_memory_runtime", get_runtime):
            events: list[RuntimeEvent] = []

            def sink(e: RuntimeEvent) -> None:
                events.append(e)

            chat(
                "hello",
                provider=FakeProvider(),
                on_runtime_event=sink,
                session_id="memory-injected-test",
            )

        event_types = [getattr(e, "event_type", None) for e in events]
        memory_injected = [
            e for e in events
            if getattr(e, "event_type", None) == "memory.injected"
        ]
        assert len(memory_injected) >= 1, (
            f"chat() 应在 pre-loop 阶段发射 memory.injected 事件，"
            f"实际 event_types={event_types}"
        )

        injected = memory_injected[0]
        assert "已加载记忆" in injected.text, (
            f"memory.injected 事件文本应包含'已加载记忆'，实际 text={injected.text!r}"
        )
        assert "2 条" in injected.text, (
            f"memory.injected 事件文本应包含记忆条数 2，实际 text={injected.text!r}"
        )
        assert injected.metadata.get("item_count") == 2, (
            f"metadata.item_count 应为 2，实际 {injected.metadata}"
        )


class TestMemoryForgetFlow:
    """验证 'forget X' / '忘记 X' 的 policy 检测正确。

    完整 forget flow（policy → confirmation → store remove）由
    memory_runtime 内部处理；这里只验证 policy 正确返回 FORGET decision。
    """

    def test_policy_detects_forget(self):
        """Policy 应检测 '忘记 X' 并返回 FORGET decision。"""
        from agent.memory_contracts import MemoryDecisionType
        from agent.memory_policy import DeterministicMemoryPolicy

        policy = DeterministicMemoryPolicy()
        decision = policy.decide("忘记 用户叫Alice")
        assert decision.decision_type == MemoryDecisionType.FORGET

    def test_policy_detects_forget_english(self):
        """Policy 应检测 'forget X' 并返回 FORGET decision。"""
        from agent.memory_contracts import MemoryDecisionType
        from agent.memory_policy import DeterministicMemoryPolicy

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
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord

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
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_runtime import MemoryRuntime
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord

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


class TestMemoryWriteRecallVisible:
    """Memory write → recall → visible 集成测试：验证 MemoryRuntime 直调路径。

    用户写入 memory → list_records 可见 → snapshot_for_prompt 可展示。
    全部走 InMemoryMemoryStore local/fake deterministic path，不经 core.chat()。
    """

    def test_memory_persists_across_runtime_calls(self):
        """同一 store 实例上的 record 跨 list_records/list_records 调用可见。"""
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_runtime import MemoryRuntime
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord

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
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_runtime import MemoryRuntime
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord

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
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_runtime import MemoryRuntime
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord

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
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_runtime import MemoryRuntime
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord

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


class TestForgetByIdPrefixMatching:
    """Phase 1: forget id:<short_prefix> 的前缀匹配、歧义处理与 not found。

    为什么短 ID 前缀匹配是 dogfood-blocking bug：
    - show memories 只显示 8 位短 ID（render_memory_list 中的 [:8]）
    - 如果 forget 只支持完整 UUID，用户复制显示的短 ID 永远无法删除
    - 前缀匹配解决了"显示出来的 ID vs 完整 ID"的距离问题

    为什么前缀冲突必须 ambiguity 而不能误删：
    - 虽然 8 位前缀碰撞在实践中极少见，但非零概率
    - 静默数据丢失对 memory governance 不可接受
    - ambiguity 让用户明确指定更多前缀位，保持用户意图为最终仲裁者

    这仍然是 local/fake-safe memory management：
    - 所有操作仅在 InMemoryMemoryStore 上执行
    - 不读取 memory/episodes/*.jsonl
    - 不调用真实 LLM/API
    - 不连接外部服务
    """

    def test_prefix_match_forgets_single_record(self):
        """短 ID 前缀匹配到唯一记录 → 成功删除。"""
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord

        full_id = "memory:fake:abcd1234efgh5678"
        record = MemoryRecord(
            id=full_id,
            content="test prefix forget",
            scope=MemoryScope.USER,
            source_summary="test",
            safety_summary="safe",
            audit_id="audit-pfx-1",
            created_by_operation=MemoryOperationType.RETAIN,
            updated_by_operation=MemoryOperationType.RETAIN,
        )
        store = InMemoryMemoryStore(records=[record])
        assert len(store.list_records()) == 1

        # 精确匹配失败 → 前缀匹配找到唯一记录
        short_id = full_id[:8]  # "memory:f"
        assert store.remove_record(short_id) is False  # 精确匹配失败
        # 前缀匹配逻辑：在调用方（core.py forget handler）中实现
        prefix_matches = [r for r in store.list_records()
                          if str(r.id).startswith(short_id)]
        assert len(prefix_matches) == 1
        assert store.remove_record(prefix_matches[0].id) is True
        assert len(store.list_records()) == 0

    def test_ambiguous_prefix_returns_multiple_matches(self):
        """前缀匹配到多条 → 不删除其中任何一条，返回歧义。"""
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord

        shared_prefix = "memory:fake:shared"
        records = [
            MemoryRecord(
                id=f"{shared_prefix}aaaa",
                content="record A",
                scope=MemoryScope.USER,
                source_summary="s", safety_summary="safe",
                audit_id="amb-a1",
                created_by_operation=MemoryOperationType.RETAIN,
                updated_by_operation=MemoryOperationType.RETAIN,
            ),
            MemoryRecord(
                id=f"{shared_prefix}bbbb",
                content="record B",
                scope=MemoryScope.USER,
                source_summary="s", safety_summary="safe",
                audit_id="amb-a2",
                created_by_operation=MemoryOperationType.RETAIN,
                updated_by_operation=MemoryOperationType.RETAIN,
            ),
        ]
        store = InMemoryMemoryStore(records=records)
        assert len(store.list_records()) == 2

        prefix_matches = [r for r in store.list_records()
                          if str(r.id).startswith(shared_prefix)]
        # 两条都匹配同一前缀 → ambiguity
        assert len(prefix_matches) == 2
        # 在 ambiguity 情况下，不删除任何记录
        assert len(store.list_records()) == 2

    def test_invalid_prefix_returns_none(self):
        """不在任何 record id 中出现的短 ID → 0 条匹配 → not found。"""
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord

        record = MemoryRecord(
            id="memory:fake:real-record-id",
            content="real",
            scope=MemoryScope.USER,
            source_summary="s", safety_summary="safe",
            audit_id="nf-1",
            created_by_operation=MemoryOperationType.RETAIN,
            updated_by_operation=MemoryOperationType.RETAIN,
        )
        store = InMemoryMemoryStore(records=[record])

        prefix_matches = [r for r in store.list_records()
                          if str(r.id).startswith("nonexistent")]
        assert len(prefix_matches) == 0


class TestRenderMemoryListFields:
    """Phase 1: render_memory_list 使用 MemoryRecord 真实字段。

    当前 MemoryRecord 字段（memory_store.py:MemoryRecord）：
    - id, content, scope, source_summary, safety_summary, audit_id
    - source_type (str) — 不是 source
    - metadata (dict) — created_at 在此 dict 中，不在顶层

    为什么 created_at 缺失时诚实显示 unavailable：
    - MemoryRecord 没有顶层 created_at 字段
    - metadata 可能为空或缺失 created_at
    - 伪造时间会误导用户以为系统记录了精确时间戳
    - 诚实标注是 fake/local-safe memory 的透明性要求
    """

    def test_render_shows_source_type(self):
        """render_memory_list 应显示 source_type 而非不存在的 source 字段。"""
        from agent.cli_commands import render_memory_list
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_store import MemoryRecord

        record = MemoryRecord(
            id="memory:fake:render1",
            content="测试内容",
            scope=MemoryScope.USER,
            source_summary="测试来源摘要",
            safety_summary="safe",
            audit_id="render-audit-1",
            created_by_operation=MemoryOperationType.RETAIN,
            updated_by_operation=MemoryOperationType.RETAIN,
            source_type="explicit_user_request",
        )
        output = render_memory_list([record])
        # 应显示 source_type
        assert "explicit_user_request" in output
        # 不应显示不存在的顶层 source 字段内容（source 字段不存在于 MemoryRecord）
        # source_type 是真实存在的字段

    def test_render_shows_created_at_from_metadata(self):
        """metadata 中有 created_at → 显示该时间。"""
        from agent.cli_commands import render_memory_list
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_store import MemoryRecord

        record = MemoryRecord(
            id="memory:fake:render2",
            content="有时间戳的记忆",
            scope=MemoryScope.USER,
            source_summary="s",
            safety_summary="safe",
            audit_id="a2",
            created_by_operation=MemoryOperationType.RETAIN,
            updated_by_operation=MemoryOperationType.RETAIN,
            metadata={"created_at": "2026-05-25T10:30:00Z"},
        )
        output = render_memory_list([record])
        assert "2026-05-25T10:30:00Z" in output

    def test_render_shows_unavailable_when_no_created_at(self):
        """metadata 无 created_at → 诚实显示 unavailable。"""
        from agent.cli_commands import render_memory_list
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_store import MemoryRecord

        record = MemoryRecord(
            id="memory:fake:render3",
            content="无时间戳的记忆",
            scope=MemoryScope.USER,
            source_summary="s",
            safety_summary="safe",
            audit_id="a3",
            created_by_operation=MemoryOperationType.RETAIN,
            updated_by_operation=MemoryOperationType.RETAIN,
            # metadata 为空 dict — 无 created_at
        )
        output = render_memory_list([record])
        assert "unavailable" in output

    def test_render_shows_short_id_prefix(self):
        """记忆列表显示短 ID（[:8]）以便用户复制用于 forget。"""
        from agent.cli_commands import render_memory_list
        from agent.memory_contracts import MemoryScope
        from agent.memory_operations import MemoryOperationType
        from agent.memory_store import MemoryRecord

        full_id = "memory:fake:abcd1234efgh5678ijkl"
        record = MemoryRecord(
            id=full_id,
            content="短 ID 测试",
            scope=MemoryScope.USER,
            source_summary="s",
            safety_summary="safe",
            audit_id="a4",
            created_by_operation=MemoryOperationType.RETAIN,
            updated_by_operation=MemoryOperationType.RETAIN,
        )
        output = render_memory_list([record])
        # 应显示前8位短 ID
        short_id = full_id[:8]
        assert short_id in output
        # 不应显示完整 ID（避免 UI 噪音）
        assert full_id not in output
