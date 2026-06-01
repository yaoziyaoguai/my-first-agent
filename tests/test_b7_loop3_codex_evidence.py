"""B7 Loop 3 — Codex counter-evidence Red/Green tests.

证明 Codex 审计发现的 P1 问题确实存在，以及修复后的 Green contract。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.runtime_identity import RuntimeIdentity

# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

FIXED_ID = RuntimeIdentity(
    session_id="review-session",
    run_id="review-run",
    instance_id="review-instance",
)


def _make_mock_registry(manifests=None):
    """构造一个 mock SkillRegistry，返回 SkillDescriptor-like 对象。

    list_visible() → list of descriptors with .name, .is_visible()
    list_visible_manifests() → list of manifest-like with .name, .description,
      .triggers, .aliases, .negative_triggers, .tags
    """
    descriptors = []
    manifest_objs = []

    for m in manifests or []:
        name = m.get("name", "test-skill")
        desc = SimpleNamespace(
            name=name,
            description=m.get("description", "test description"),
            version="0.1.0",
            status="active",
            risk_level="low",
            tags=tuple(m.get("tags", [])),
            allowed_tools=(),
            memory_scope="none",
            aliases=tuple(m.get("aliases", [])),
            is_visible=lambda: True,
        )
        descriptors.append(desc)

        manifest_obj = SimpleNamespace(
            name=name,
            description=m.get("description", "test description"),
            triggers=tuple(m.get("triggers", [])),
            aliases=tuple(m.get("aliases", [])),
            negative_triggers=tuple(m.get("negative_triggers", [])),
            tags=tuple(m.get("tags", [])),
        )
        manifest_objs.append(manifest_obj)

    registry = SimpleNamespace()
    registry.list_visible = lambda: descriptors
    registry.list_visible_manifests = lambda: manifest_objs

    return registry


# ═══════════════════════════════════════════════════════════════════════
# Counter-Evidence 1: Turn-start identity propagation RED
# ═══════════════════════════════════════════════════════════════════════


class TestRedTurnStartIdentityMissing:
    """证明 turn-start dispatch path 缺少 identity 传播。

    refresh_runtime_system_prompt() 内部 dispatch 以下事件时
    不传入 identity → RuntimeActionEvent 的 identity 字段全为空。
    """

    def test_skill_selection_entered_identity_empty(self):
        """RED — SKILL_SELECTION_ENTERED 的 session_id/run_id/instance_id 为空。"""
        from agent.core import refresh_runtime_system_prompt
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
        )
        from agent.runtime_integration.schema import RuntimeActionType

        registry = _make_mock_registry([])
        action_registry = ActionHandlerRegistry()
        dispatcher = RuntimeActionDispatcher(registry=action_registry)

        refresh_runtime_system_prompt(
            dispatcher=dispatcher, skill_registry=registry, user_input="test",
        )

        events = [
            a for a in dispatcher.action_log
            if a.action_type == RuntimeActionType.SKILL_SELECTION_ENTERED
        ]
        assert events, "必须有 SKILL_SELECTION_ENTERED event"
        ev = events[0]
        assert ev.session_id == "", f"RED: session_id 为空, 实际 {ev.session_id!r}"
        assert ev.run_id == "", f"RED: run_id 为空, 实际 {ev.run_id!r}"
        assert ev.instance_id == "", f"RED: instance_id 为空, 实际 {ev.instance_id!r}"

    def test_skill_candidates_built_identity_empty(self):
        """RED — SKILL_CANDIDATES_BUILT 的 identity 为空。"""
        from agent.core import refresh_runtime_system_prompt
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
        )
        from agent.runtime_integration.schema import RuntimeActionType

        registry = _make_mock_registry([{
            "name": "test", "triggers": ("trigger",), "tags": ("test",),
        }])
        action_registry = ActionHandlerRegistry()
        dispatcher = RuntimeActionDispatcher(registry=action_registry)

        refresh_runtime_system_prompt(
            dispatcher=dispatcher, skill_registry=registry, user_input="trigger",
        )

        events = [
            a for a in dispatcher.action_log
            if a.action_type == RuntimeActionType.SKILL_CANDIDATES_BUILT
        ]
        assert events, "必须有 SKILL_CANDIDATES_BUILT event"
        ev = events[0]
        assert ev.session_id == "", f"RED: session_id 为空, 实际 {ev.session_id!r}"
        assert ev.run_id == "", f"RED: run_id 为空, 实际 {ev.run_id!r}"
        assert ev.instance_id == "", f"RED: instance_id 为空, 实际 {ev.instance_id!r}"

    def test_memory_recall_identity_empty(self):
        """RED — MEMORY_RECALL 的 identity 为空。"""
        from agent.core import refresh_runtime_system_prompt
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
        )
        from agent.runtime_integration.schema import RuntimeActionType

        registry = _make_mock_registry([])
        action_registry = ActionHandlerRegistry()
        dispatcher = RuntimeActionDispatcher(registry=action_registry)

        refresh_runtime_system_prompt(
            dispatcher=dispatcher, skill_registry=registry, user_input="hello",
        )

        events = [
            a for a in dispatcher.action_log
            if a.action_type == RuntimeActionType.MEMORY_RECALL
        ]
        assert events, "必须有 MEMORY_RECALL event"
        ev = events[0]
        assert ev.session_id == "", f"RED: session_id 为空, 实际 {ev.session_id!r}"
        assert ev.run_id == "", f"RED: run_id 为空, 实际 {ev.run_id!r}"
        assert ev.instance_id == "", f"RED: instance_id 为空, 实际 {ev.instance_id!r}"


# ═══════════════════════════════════════════════════════════════════════
# Counter-Evidence 2: MCP Decision Frame Session Lookup RED
# ═══════════════════════════════════════════════════════════════════════


class TestRedMCPDecisionFrameDefaultSession:
    """RuntimeDecisionFrame 在 per-session MCP 下仍读 default。

    MCP bridge registry 已支持 per-session，但 build_decision_frame_from_chat_params
    调用 is_mcp_active() 时不传 session_id。
    """

    def test_per_session_mcp_ignored_by_decision_frame(self):
        """RED — session 级 MCP 注册不影响 decision frame。

        set_mcp_bridge_result(2, session_id='review-session') 后
        is_mcp_active(session_id='review-session') == True
        但 build_decision_frame_from_chat_params(user_input='test').mcp_available == False
        """
        from agent.mcp_bridge import is_mcp_active, set_mcp_bridge_result
        from agent.runtime_decision_frame import build_decision_frame_from_chat_params

        set_mcp_bridge_result(0)
        set_mcp_bridge_result(2, session_id="review-session")

        try:
            assert is_mcp_active(session_id="review-session") is True
            assert is_mcp_active() is False

            frame = build_decision_frame_from_chat_params("test")
            assert frame.mcp_available is False, (
                "RED: review-session MCP 有 2 tools registered, "
                "但 decision frame 读 default → mcp_available=False, "
                f"实际 {frame.mcp_available}"
            )
        finally:
            set_mcp_bridge_result(0)
            set_mcp_bridge_result(0, session_id="review-session")

    def test_two_sessions_mcp_isolated_but_decision_frame_ignores_both(self):
        """RED — session A/B 隔离正确，但 decision frame 忽略两者。"""
        from agent.mcp_bridge import is_mcp_active, set_mcp_bridge_result
        from agent.runtime_decision_frame import build_decision_frame_from_chat_params

        set_mcp_bridge_result(0)
        set_mcp_bridge_result(3, session_id="session-a")
        set_mcp_bridge_result(0, session_id="session-b")

        try:
            assert is_mcp_active(session_id="session-a") is True
            assert is_mcp_active(session_id="session-b") is False

            frame = build_decision_frame_from_chat_params("test")
            assert frame.mcp_available is False, (
                "RED: session-a 有 3 tools, session-b 有 0, "
                "decision frame 读 default (0 tools) → mcp_available=False"
            )
        finally:
            set_mcp_bridge_result(0)
            set_mcp_bridge_result(0, session_id="session-a")
            set_mcp_bridge_result(0, session_id="session-b")


# ═══════════════════════════════════════════════════════════════════════
# Green contracts — 修复后应全部 PASS
# ═══════════════════════════════════════════════════════════════════════


class TestGreenTurnStartIdentityPropagation:
    """修复后 identity 传入 refresh_runtime_system_prompt → events 携带正确 identity。

    当前 identity 参数不存在 → GREEN tests skip。
    实现 identity 参数后 skip 变为 assertion。
    """

    def test_identity_on_skill_selection_entered(self):
        """GREEN — SKILL_SELECTION_ENTERED 携带传入的 identity。"""
        from agent.core import refresh_runtime_system_prompt
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
        )
        from agent.runtime_integration.schema import RuntimeActionType

        registry = _make_mock_registry([])
        action_registry = ActionHandlerRegistry()
        dispatcher = RuntimeActionDispatcher(registry=action_registry)

        try:
            refresh_runtime_system_prompt(
                dispatcher=dispatcher, skill_registry=registry,
                user_input="test", identity=FIXED_ID,
            )
        except TypeError as e:
            if "unexpected keyword argument" in str(e):
                pytest.skip(f"GREEN — identity 参数尚未添加: {e}")
            raise

        events = [
            a for a in dispatcher.action_log
            if a.action_type == RuntimeActionType.SKILL_SELECTION_ENTERED
        ]
        assert events
        ev = events[0]
        assert ev.session_id == "review-session", (
            f"GREEN: session_id={ev.session_id!r}"
        )
        assert ev.run_id == "review-run"
        assert ev.instance_id == "review-instance"

    def test_identity_on_skill_candidates_built(self):
        """GREEN — SKILL_CANDIDATES_BUILT 携带 identity。"""
        from agent.core import refresh_runtime_system_prompt
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
        )
        from agent.runtime_integration.schema import RuntimeActionType

        registry = _make_mock_registry([{
            "name": "test", "triggers": ("trigger",), "tags": ("test",),
        }])
        action_registry = ActionHandlerRegistry()
        dispatcher = RuntimeActionDispatcher(registry=action_registry)

        try:
            refresh_runtime_system_prompt(
                dispatcher=dispatcher, skill_registry=registry,
                user_input="trigger", identity=FIXED_ID,
            )
        except TypeError as e:
            if "unexpected keyword argument" in str(e):
                pytest.skip(f"GREEN — identity 参数尚未添加: {e}")
            raise

        events = [
            a for a in dispatcher.action_log
            if a.action_type == RuntimeActionType.SKILL_CANDIDATES_BUILT
        ]
        assert events
        ev = events[0]
        assert ev.session_id == "review-session"
        assert ev.run_id == "review-run"
        assert ev.instance_id == "review-instance"

    def test_identity_on_memory_recall(self):
        """GREEN — MEMORY_RECALL 携带 identity。"""
        from agent.core import refresh_runtime_system_prompt
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
        )
        from agent.runtime_integration.schema import RuntimeActionType

        registry = _make_mock_registry([])
        action_registry = ActionHandlerRegistry()
        dispatcher = RuntimeActionDispatcher(registry=action_registry)

        try:
            refresh_runtime_system_prompt(
                dispatcher=dispatcher, skill_registry=registry,
                user_input="hello", identity=FIXED_ID,
            )
        except TypeError as e:
            if "unexpected keyword argument" in str(e):
                pytest.skip(f"GREEN — identity 参数尚未添加: {e}")
            raise

        events = [
            a for a in dispatcher.action_log
            if a.action_type == RuntimeActionType.MEMORY_RECALL
        ]
        assert events
        ev = events[0]
        assert ev.session_id == "review-session"
        assert ev.run_id == "review-run"
        assert ev.instance_id == "review-instance"


class TestGreenMCPDecisionFrameSessionLookup:
    """修复后 decision frame 使用 session_id 查询 MCP bridge。"""

    def test_decision_frame_with_session_id(self):
        """GREEN — 传入 session_id 后 mcp_available 反映该 session 的 MCP 状态。"""
        from agent.mcp_bridge import set_mcp_bridge_result
        from agent.runtime_decision_frame import build_decision_frame_from_chat_params

        set_mcp_bridge_result(0)
        set_mcp_bridge_result(2, session_id="review-session")

        try:
            try:
                frame = build_decision_frame_from_chat_params(
                    "test", session_id="review-session",
                )
            except TypeError as e:
                if "unexpected keyword argument" in str(e):
                    pytest.skip(f"GREEN — session_id 参数尚未添加: {e}")
                raise

            assert frame.mcp_available is True, (
                f"GREEN: review-session 有 2 tools, "
                f"mcp_available 应为 True, 实际 {frame.mcp_available}"
            )
        finally:
            set_mcp_bridge_result(0)
            set_mcp_bridge_result(0, session_id="review-session")

    def test_session_b_inactive_with_session_id(self):
        """GREEN — session_b MCP 0 tools → mcp_available=False。"""
        from agent.mcp_bridge import set_mcp_bridge_result
        from agent.runtime_decision_frame import build_decision_frame_from_chat_params

        set_mcp_bridge_result(0)
        set_mcp_bridge_result(3, session_id="session-a")
        set_mcp_bridge_result(0, session_id="session-b")

        try:
            try:
                frame = build_decision_frame_from_chat_params(
                    "test", session_id="session-b",
                )
            except TypeError:
                pytest.skip("GREEN — session_id 参数尚未添加")
                return

            assert frame.mcp_available is False
        finally:
            set_mcp_bridge_result(0)
            set_mcp_bridge_result(0, session_id="session-a")
            set_mcp_bridge_result(0, session_id="session-b")
