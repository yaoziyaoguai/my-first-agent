"""B7 Slice 2: Namespace Injection — focused contract tests.

覆盖 ActiveSkillLifecycle namespace、InMemoryMemoryStore namespace、
MCP bridge session-scoped、ToolRuntimeMediator identity injection。
"""

from __future__ import annotations

# ── RED-2.1: ActiveSkillLifecycle namespace ─────────────────────────────


class TestActiveSkillLifecycleNamespace:
    def test_lifecycle_namespace_isolation(self):
        """两个不同 namespace 的 lifecycle 实例互不影响。"""
        from agent.skill_system.lifecycle import ActiveSkillLifecycle
        ns1 = ActiveSkillLifecycle(namespace="ns1")
        ns2 = ActiveSkillLifecycle(namespace="ns2")

        ns1.activate("skill-a", "body-a", allowed_tools=("tool-x",))
        assert ns1.is_active()
        assert not ns2.is_active()

    def test_get_default_lifecycle_returns_namespaced(self):
        """get_default_lifecycle(session_id=...) 返回独立 lifecycle 实例。"""
        from agent.skill_system.lifecycle import get_default_lifecycle
        lc1 = get_default_lifecycle(session_id="s1")
        lc2 = get_default_lifecycle(session_id="s2")
        # 不同 session 的 lifecycle 不是同一个对象
        assert lc1 is not lc2

    def test_get_default_lifecycle_default_backward_compat(self):
        """get_default_lifecycle() 无参数返回默认 namespace 实例。"""
        from agent.skill_system.lifecycle import get_default_lifecycle
        lc = get_default_lifecycle()
        assert lc is not None
        assert lc.namespace == "default"

    def test_lifecycle_allowed_tools_per_namespace(self):
        """ns1 激活 skill 后有 allowed_tools，ns2 保持为空。"""
        from agent.skill_system.lifecycle import get_default_lifecycle
        lc1 = get_default_lifecycle(session_id="ns-a")
        lc2 = get_default_lifecycle(session_id="ns-b")

        lc1.activate("skill-x", "body-x", allowed_tools=("read",))
        assert lc1.get_allowed_tools() == frozenset({"read"})
        assert lc2.get_allowed_tools() == frozenset()

        # cleanup
        lc1.deactivate()

    def test_lifecycle_to_dict_includes_namespace(self):
        """to_dict() 输出包含 namespace 字段。"""
        from agent.skill_system.lifecycle import ActiveSkillLifecycle
        lc = ActiveSkillLifecycle(namespace="test-ns")
        lc.activate("skill-y", "body-y")
        d = lc.to_dict()
        assert d["namespace"] == "test-ns"

    def test_reset_default_lifecycle_still_works(self):
        """reset_default_lifecycle() 向后兼容。"""
        from agent.skill_system.lifecycle import (
            get_default_lifecycle,
            reset_default_lifecycle,
        )
        lc_before = get_default_lifecycle()
        reset_default_lifecycle()
        lc_after = get_default_lifecycle()
        # 重置后返回新的实例
        assert lc_after is not lc_before
        assert lc_after.namespace == "default"


# ── RED-2.2: InMemoryMemoryStore namespace ───────────────────────────────


class TestInMemoryMemoryStoreNamespace:
    def test_store_namespace_isolation(self):
        """ns1 存入的记录 ns2 不可见。"""
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord

        store1 = InMemoryMemoryStore(namespace="ns1")
        store2 = InMemoryMemoryStore(namespace="ns2")

        rec = MemoryRecord(
            id="rec-1",
            content="test content",
            scope=None,
            source_summary="test source",
            safety_summary="safe",
            audit_id="audit-1",
            created_by_operation=None,  # type: ignore[arg-type]
            updated_by_operation=None,  # type: ignore[arg-type]
        )
        store1._records["ns1:rec-1"] = rec
        assert store1.get_record("rec-1") is not None
        assert store2.get_record("rec-1") is None

    def test_store_list_records_per_namespace(self):
        """list_records() 只返回本 namespace 的记录。"""
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord

        store = InMemoryMemoryStore(namespace="ns-a")
        rec1 = MemoryRecord(
            id="r1", content="c1", scope=None,
            source_summary="s1", safety_summary="safe",
            audit_id="a1",
            created_by_operation=None, updated_by_operation=None,  # type: ignore[arg-type]
        )
        rec2 = MemoryRecord(
            id="r2", content="c2", scope=None,
            source_summary="s2", safety_summary="safe",
            audit_id="a2",
            created_by_operation=None, updated_by_operation=None,  # type: ignore[arg-type]
        )

        store._records["ns-a:r1"] = rec1
        store._records["other:r2"] = rec2
        records = store.list_records()
        assert len(records) == 1
        assert records[0].id == "r1"

    def test_store_default_namespace(self):
        """不传 namespace 时使用 "default"。 """
        from agent.memory_store import InMemoryMemoryStore

        store = InMemoryMemoryStore()
        assert store._namespace == "default"

    def test_store_forget_record_per_namespace(self):
        """ns1 的 forget 不影响 ns2 的同 key 记录。"""
        from agent.memory_store import InMemoryMemoryStore, MemoryRecord

        store1 = InMemoryMemoryStore(namespace="ns1")
        store2 = InMemoryMemoryStore(namespace="ns2")

        rec1 = MemoryRecord(
            id="rec-x", content="c1", scope=None,
            source_summary="s1", safety_summary="safe",
            audit_id="a1",
            created_by_operation=None, updated_by_operation=None,  # type: ignore[arg-type]
        )
        rec2 = MemoryRecord(
            id="rec-x", content="c2", scope=None,
            source_summary="s2", safety_summary="safe",
            audit_id="a2",
            created_by_operation=None, updated_by_operation=None,  # type: ignore[arg-type]
        )

        store1._records["ns1:rec-x"] = rec1
        store2._records["ns2:rec-x"] = rec2
        assert store1.get_record("rec-x") is not None
        assert store2.get_record("rec-x") is not None

        # ns1 中删除 rec-x
        store1.remove_record("rec-x")
        assert store1.get_record("rec-x") is None
        # ns2 不受影响
        assert store2.get_record("rec-x") is not None


# ── RED-2.3: MCP bridge session-scoped ───────────────────────────────────


class TestMCPBridgeSessionScoped:
    def test_bridge_tools_registered_per_session(self):
        """两个 session 的工具注册数独立。"""
        from agent.mcp_bridge import (
            get_mcp_bridge_tools_registered,
            set_mcp_bridge_result,
        )
        set_mcp_bridge_result(tools_registered=5, session_id="s1")
        set_mcp_bridge_result(tools_registered=3, session_id="s2")
        assert get_mcp_bridge_tools_registered(session_id="s1") == 5
        assert get_mcp_bridge_tools_registered(session_id="s2") == 3
        # 无参数回退到 "default"
        assert get_mcp_bridge_tools_registered() == 0

    def test_bridge_disabled_default_no_registry_leak(self):
        """disabled 模式不会向 session registry 写入。"""
        from agent.mcp_bridge import (
            get_mcp_bridge_tools_registered,
            is_mcp_active,
        )
        assert get_mcp_bridge_tools_registered(session_id="default") == 0
        assert is_mcp_active(session_id="default") is False

    def test_is_mcp_active_per_session(self):
        """is_mcp_active 按 session 独立判断。"""
        from agent.mcp_bridge import (
            is_mcp_active,
            set_mcp_bridge_result,
        )
        set_mcp_bridge_result(tools_registered=2, session_id="active-session")
        set_mcp_bridge_result(tools_registered=0, session_id="empty-session")
        assert is_mcp_active(session_id="active-session") is True
        assert is_mcp_active(session_id="empty-session") is False
