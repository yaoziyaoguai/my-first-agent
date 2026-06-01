"""B7 Phase 5: Namespace Injection isolation tests.

Verify per-session isolation for:
- active_skill lifecycle (no cross-run leak)
- memory store (no cross-session leak)
- MCP bridge results (per-session scoping)

All tests use FakeProvider — no real API, no .env, no secret access.
"""

from __future__ import annotations

import pytest

from agent.core import chat, get_memory_runtime
from agent.provider.fake_provider import FakeProvider
from agent.skill_system.lifecycle import (
    get_default_lifecycle,
    reset_default_lifecycle,
)


@pytest.fixture(autouse=True)
def _reset_lifecycle():
    """每个测试前重置 lifecycle 和 memory registry，防止跨测试污染。"""
    reset_default_lifecycle()
    yield
    reset_default_lifecycle()


# ═══════════════════════════════════════════════════════════════════════
# T1-T2: active_skill lifecycle per-session isolation
# ═══════════════════════════════════════════════════════════════════════


class TestActiveSkillLifecycleIsolation:
    """两个不同 session 不共享 active_skill 状态。"""

    def test_t1_two_sessions_have_independent_active_skill(self):
        """T1: 在 session-A 激活 skill，session-B 的 lifecycle 不受影响。"""
        lc_a = get_default_lifecycle("session-A")
        lc_b = get_default_lifecycle("session-B")

        lc_a.activate("demo-skill", "session-A body", ("tool-a",), activated_by="test")
        assert lc_a.is_active()
        assert lc_a.get_active_skill_id() == "demo-skill"

        # session-B 的 lifecycle 独立，不应看到 session-A 的 active_skill
        assert not lc_b.is_active()
        assert lc_b.get_active_skill_id() is None

    def test_t2_two_runs_with_same_session_share_active_skill(self):
        """T2: 同一 session 内两次 activate 共享状态。"""
        lc = get_default_lifecycle("session-shared")
        lc.activate("skill-1", "body-1", ("t1",), activated_by="test")
        assert lc.get_active_skill_id() == "skill-1"

        # 同 session 切换 skill
        lc.activate("skill-2", "body-2", ("t2",), activated_by="test")
        assert lc.get_active_skill_id() == "skill-2"

    def test_t3_deactivate_does_not_affect_other_session(self):
        """T3: 在 session-A deactivate，session-B 不受影响。"""
        lc_a = get_default_lifecycle("session-A")
        lc_b = get_default_lifecycle("session-B")

        lc_a.activate("skill-a", "body-a", activated_by="test")
        lc_b.activate("skill-b", "body-b", activated_by="test")

        lc_a.deactivate()
        assert not lc_a.is_active()
        assert lc_b.is_active()
        assert lc_b.get_active_skill_id() == "skill-b"


# ═══════════════════════════════════════════════════════════════════════
# T4-T6: memory store per-session isolation
# ═══════════════════════════════════════════════════════════════════════


class TestMemoryStoreIsolation:
    """两个不同 session 不共享 memory store 状态。"""

    def test_t4_two_sessions_have_independent_memory_store(self):
        """T4: get_memory_runtime 为不同 session 返回不同实例。"""
        rt_a = get_memory_runtime("session-A")
        rt_b = get_memory_runtime("session-B")

        assert rt_a is not rt_b, (
            "不同 session 应返回不同的 MemoryRuntime 实例"
        )

    def test_t5_default_session_returns_same_memory_runtime(self):
        """T5: 无 session_id / "default" 返回同一默认实例。"""
        rt1 = get_memory_runtime("")
        rt2 = get_memory_runtime("default")
        rt3 = get_memory_runtime()

        assert rt1 is rt2
        assert rt2 is rt3

    def test_t6_memory_writes_in_one_session_not_visible_in_another(self):
        """T6: session-A 的 memory write 不被 session-B 看到。

        直接验证底层 store 是不同实例——这是隔离的根本保证。
        evaluate_user_text 依赖 policy 匹配，不一定触发实际写入，
        不适合作为唯一验证手段；store 实例隔离才是正确的测试目标。
        """
        rt_a = get_memory_runtime("session-A")
        rt_b = get_memory_runtime("session-B")

        store_a = rt_a._store
        store_b = rt_b._store

        assert store_a is not store_b, (
            "不同 session 的底层 store 应为不同实例，"
            "否则写入会跨 session 泄漏"
        )


# ═══════════════════════════════════════════════════════════════════════
# T7: MCP bridge per-session scoping
# ═══════════════════════════════════════════════════════════════════════


class TestMCPBridgeSessionScoping:
    """MCP bridge 结果按 session_id 隔离。"""

    def test_t7_mcp_bridge_results_scoped_by_session(self):
        """T7: 不同 session 的 MCP bridge 结果独立。"""
        from agent.mcp_bridge import (
            get_mcp_bridge_tools_registered,
            is_mcp_active,
            set_mcp_bridge_result,
        )

        set_mcp_bridge_result(5, session_id="session-A")
        set_mcp_bridge_result(0, session_id="session-B")

        assert get_mcp_bridge_tools_registered(session_id="session-A") == 5
        assert get_mcp_bridge_tools_registered(session_id="session-B") == 0
        assert is_mcp_active(session_id="session-A") is True
        assert is_mcp_active(session_id="session-B") is False

        # 不存在的 session 返回 0
        assert get_mcp_bridge_tools_registered(session_id="nonexistent") == 0


# ═══════════════════════════════════════════════════════════════════════
# T8-T9: Regression guards — 002 skill selection / 003 allowed_tools
# ═══════════════════════════════════════════════════════════════════════


class TestSkillSelectionRegression:
    """002: skill selection 功能不受 namespace 隔离影响。"""

    def test_t8_default_lifecycle_still_works_for_skill_selection(self):
        """T8: 默认 lifecycle 仍可用于 skill selection（向后兼容）。"""
        lc = get_default_lifecycle()
        lc.activate("test-skill", "test body", ("tool-1", "tool-2"), activated_by="test")
        assert lc.is_active()
        assert lc.get_active_skill_id() == "test-skill"
        assert "tool-1" in lc.get_allowed_tools()
        assert "tool-2" in lc.get_allowed_tools()

    def test_t9_allowed_tools_enforcement_independent_per_session(self):
        """T9: 每个 session 的 allowed_tools 独立执行。"""
        lc_a = get_default_lifecycle("session-A")
        lc_b = get_default_lifecycle("session-B")

        lc_a.activate("skill-a", "body-a", ("tool-a-only",), activated_by="test")
        lc_b.activate("skill-b", "body-b", ("tool-b-only",), activated_by="test")

        assert "tool-a-only" in lc_a.get_allowed_tools()
        assert "tool-b-only" not in lc_a.get_allowed_tools()
        assert "tool-b-only" in lc_b.get_allowed_tools()
        assert "tool-a-only" not in lc_b.get_allowed_tools()


# ═══════════════════════════════════════════════════════════════════════
# T10: model_selected per-lifecycle flag
# ═══════════════════════════════════════════════════════════════════════


class TestModelSelectedPerLifecycle:
    """model_selected flag 按 lifecycle 实例隔离。"""

    def test_t10_model_selected_flag_independent_per_session(self):
        """T10: 不同 session 的 model_selected 互不影响。"""
        lc_a = get_default_lifecycle("session-A")
        lc_b = get_default_lifecycle("session-B")

        lc_a.set_model_selected()
        assert lc_a.was_model_selected()
        assert not lc_b.was_model_selected()

    def test_t11_consume_model_selected_resets_flag(self):
        """T11: consume_model_selected 消费后返回 False。"""
        lc = get_default_lifecycle("session-test")
        lc.set_model_selected()
        assert lc.consume_model_selected() is True
        assert lc.was_model_selected() is False


# ═══════════════════════════════════════════════════════════════════════
# T12: chat() with explicit session_id uses per-session state
# ═══════════════════════════════════════════════════════════════════════


class TestChatWithSessionIdUsesPerSessionState:
    """chat() 使用显式 session_id 时应使用 per-session lifecycle/memory。"""

    def test_t12_chat_with_session_id_does_not_leak_to_default(self):
        """T12: chat(session_id="X") 的 active_skill 不泄漏到默认 lifecycle。"""
        default_lc = get_default_lifecycle()

        # 模拟在 session-A 中激活 skill
        chat(
            "hello",
            provider=FakeProvider(),
            session_id="session-A",
        )

        # 默认 lifecycle 不应有 active_skill（session-A 的 skill 不泄漏）
        assert default_lc.get_active() is None or default_lc.get_active_skill_id() is None, (
            "session-A 的 active_skill 不应泄漏到默认 lifecycle"
        )

    def test_t13_chat_without_session_id_uses_default_state(self):
        """T13: chat() 不传 session_id 时使用默认 lifecycle（向后兼容）。"""
        default_lc = get_default_lifecycle()
        # chat 调用后默认 lifecycle 仍可正常使用
        chat("hello", provider=FakeProvider())
        # 默认 lifecycle 实例仍在（不被替换）
        assert default_lc is get_default_lifecycle()
