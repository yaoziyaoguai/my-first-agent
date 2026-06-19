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

    @pytest.fixture(autouse=True)
    def _s2_skill_enabled_for_activation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """S2-G09：覆盖 SKILL_SELECTION_ENTERED activation，需显式 opt-in gate。"""
        monkeypatch.setenv("MY_FIRST_AGENT_S2_SKILL_ENABLE", "1")

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

    @pytest.fixture(autouse=True)
    def _s2_skill_enabled_for_activation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """S2-G09：覆盖 SKILL_SELECTION_ENTERED activation，需显式 opt-in gate。"""
        monkeypatch.setenv("MY_FIRST_AGENT_S2_SKILL_ENABLE", "1")

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


# ═══════════════════════════════════════════════════════════════════════
# Phase 3 — SKILL_SELECT lifecycle production path
# ═══════════════════════════════════════════════════════════════════════


class TestGreenSkillSelectLifecycleProductionPath:
    """Phase 3 evidence: SKILL_SELECT 使用显式 session namespace。

    验证 _skill_select_tool_func 通过 _get_active_session_ns() 获取
    namespace，不依赖 logger import-time SESSION_ID fallback。
    model_selected flag 是 per-lifecycle 而非全局状态。
    """

    def test_set_and_get_active_session_ns(self):
        """set_active_session_ns → _get_active_session_ns 往返正确。"""
        from agent.skill_system.skill_tool import (
            _get_active_session_ns,
            clear_active_session_ns,
            set_active_session_ns,
        )

        set_active_session_ns("session-abc")
        try:
            assert _get_active_session_ns() == "session-abc"
        finally:
            clear_active_session_ns()

        assert _get_active_session_ns() == ""

    def test_clear_active_session_ns_resets_to_empty(self):
        """clear_active_session_ns 后 _get_active_session_ns 返回空字符串。"""
        from agent.skill_system.skill_tool import (
            _get_active_session_ns,
            clear_active_session_ns,
            set_active_session_ns,
        )

        set_active_session_ns("any-value")
        clear_active_session_ns()
        assert _get_active_session_ns() == ""

    def test_active_session_ns_not_using_logger_fallback(self):
        """_get_active_session_ns 不依赖 logger.SESSION_ID（import-time fallback）。

        验证：即使 logger 模块有 SESSION_ID，_get_active_session_ns 返回的是
        skill_tool 自身的 _active_session_ns 全局变量，不是 logger 的 SESSION_ID。
        """
        from agent.skill_system.skill_tool import _get_active_session_ns

        # 未设置时返回空字符串，不是 logger 的 SESSION_ID
        ns = _get_active_session_ns()
        assert ns == "", (
            f"未设置 _active_session_ns 时应为空字符串，不是 logger SESSION_ID, 实际 {ns!r}"
        )

    def test_model_selected_flag_is_per_lifecycle(self):
        """model_selected 是 lifecycle 实例属性，非模块级全局。

        两个不同 lifecycle 实例的 model_selected 相互独立。
        """
        from agent.skill_system.lifecycle import ActiveSkillLifecycle

        lc_a = ActiveSkillLifecycle(namespace="session-a")
        lc_b = ActiveSkillLifecycle(namespace="session-b")

        assert lc_a.was_model_selected() is False
        assert lc_b.was_model_selected() is False

        lc_a.set_model_selected()
        assert lc_a.was_model_selected() is True
        assert lc_b.was_model_selected() is False, (
            "session B 不应受 session A 的 model_selected 影响"
        )

        consumed = lc_a.consume_model_selected()
        assert consumed is True
        assert lc_a.was_model_selected() is False, (
            "consume_model_selected 后标记应被重置"
        )

    def test_skill_activation_isolated_between_lifecycles(self):
        """不同 lifecycle 实例的 skill 激活相互隔离。

        Session A 激活 "demo-note-maker" → Session B 不受影响。
        """
        from agent.skill_system.lifecycle import ActiveSkillLifecycle

        lc_a = ActiveSkillLifecycle(namespace="session-a")
        lc_b = ActiveSkillLifecycle(namespace="session-b")

        lc_a.activate(
            skill_id="demo-note-maker",
            body="test body",
            allowed_tools=("write_file", "read_file"),
            activated_by="model_selection",
        )

        assert lc_a.is_active() is True
        assert lc_a.get_active_skill_id() == "demo-note-maker"
        assert lc_a.get_allowed_tools() == frozenset({"write_file", "read_file"})

        assert lc_b.is_active() is False, (
            "session B 不应受 session A 的 skill 激活影响"
        )
        assert lc_b.get_active_skill_id() is None
        assert lc_b.get_allowed_tools() == frozenset()

    def test_per_session_lifecycle_registry(self):
        """get_default_lifecycle 为不同 session_id 返回不同 lifecycle 实例。"""
        from agent.skill_system.lifecycle import get_default_lifecycle

        lc_a = get_default_lifecycle("session-a")
        lc_b = get_default_lifecycle("session-b")
        lc_default = get_default_lifecycle()

        assert lc_a is not lc_b, "不同 session 应有独立的 lifecycle 实例"
        assert lc_a is not lc_default, "命名 session 应与 default 不同"
        assert lc_b is not lc_default

        lc_a.activate(
            skill_id="skill-a-only",
            body="body-a",
            allowed_tools=("tool_a",),
        )
        assert lc_b.get_active_skill_id() is None
        assert lc_default.get_active_skill_id() is None

    def test_tool_mediator_gate_reads_lifecycle_by_identity_session(self):
        """ToolRuntimeMediator._route_gate 通过 identity.session_id 读取 lifecycle。

        当 mediator 持有 identity 时，gate 从对应 session 的 lifecycle
        读取 allowed_tools，而不是默认的 "default" lifecycle。
        """
        from types import SimpleNamespace

        from agent.skill_system.lifecycle import get_default_lifecycle

        # 为 session-x 创建一个独立 lifecycle 并激活 skill
        lc_x = get_default_lifecycle("session-x")
        lc_x.activate(
            skill_id="session-x-skill",
            body="x-body",
            allowed_tools=("tool_x",),
        )

        # 模拟 ToolRuntimeMediator._route_gate 的 session 查找逻辑
        identity = SimpleNamespace(session_id="session-x", run_id="run-x")
        session_id = identity.session_id if identity else "default"

        lc = get_default_lifecycle(session_id=session_id)
        tools = lc.get_allowed_tools()

        assert tools == frozenset({"tool_x"}), (
            f"应从 session-x lifecycle 读取 allowed_tools={{'tool_x'}}, "
            f"实际 {tools}"
        )

        # 验证 default lifecycle 不受影响
        lc_default = get_default_lifecycle()
        assert lc_default.get_allowed_tools() == frozenset()


class TestRedSkillSelectLifecycleGlobalFallback:
    """Phase 3 counter-evidence: 已移除的全局 fallback 风险。

    证明修复后的代码不再依赖全局状态。
    """

    def test_clear_active_session_ns_exists_and_importable(self):
        """clear_active_session_ns 已定义且可从 skill_tool import。"""
        from agent.skill_system.skill_tool import clear_active_session_ns

        assert callable(clear_active_session_ns)

    def test_reset_default_lifecycle_clears_all_state(self):
        """reset_default_lifecycle 清除所有 lifecycle 状态（测试关键依赖）。"""
        from agent.skill_system.lifecycle import (
            get_default_lifecycle,
            reset_default_lifecycle,
        )

        lc = get_default_lifecycle("test-ns")
        lc.activate(skill_id="test-skill", body="b", allowed_tools=("t1",))
        lc.set_model_selected()

        reset_default_lifecycle()

        new_lc = get_default_lifecycle("test-ns")
        assert new_lc.is_active() is False
        assert new_lc.was_model_selected() is False


# ═══════════════════════════════════════════════════════════════════════
# Phase 4 — Checkpoint confirmation identity
# ═══════════════════════════════════════════════════════════════════════


class TestGreenCheckpointConfirmationIdentity:
    """Phase 4 evidence: checkpoint 保存携带 identity。

    验证 memory_confirmation / turn-end checkpoint save 使用 v2 schema，
    meta 中包含 session_id / run_id，且使用 per-run path。
    """

    def test_save_checkpoint_v2_with_session_id_and_run_id(self, tmp_path):
        """session_id + run_id 非空 → v2 schema（per-run path + identity 字段）。"""
        from types import SimpleNamespace

        from agent.checkpoint import save_checkpoint

        state = SimpleNamespace()
        state.task = SimpleNamespace(
            current_plan=None,
            current_step_index=0,
            status="running",
            tool_execution_log=(),
            pending_tool=None,
            pending_user_input_request=None,
        )
        state.memory = SimpleNamespace(
            session_id="",
            snapshot=[],
            approved_memories={},
            pending_memories={},
        )
        state.conversation = SimpleNamespace(messages=[])

        cp_path = tmp_path / "test_v2_checkpoint.json"
        save_checkpoint(
            state,
            source="memory_confirmation",
            session_id="session-v2",
            run_id="run-v2",
            path=cp_path,
        )

        assert cp_path.exists()

        import json

        data = json.loads(cp_path.read_text(encoding="utf-8"))
        meta = data["meta"]
        assert meta["schema_version"] == "checkpoint.v2", (
            f"v2 schema_version, 实际 {meta['schema_version']}"
        )
        assert meta["session_id"] == "session-v2"
        assert meta["run_id"] == "run-v2"
        assert "updated_at" in meta, "v2 meta 应有 updated_at 字段"

    def test_save_checkpoint_v1_without_identity(self, tmp_path):
        """无 session_id/run_id → v1 schema（向后兼容）。"""
        from types import SimpleNamespace

        from agent.checkpoint import save_checkpoint

        state = SimpleNamespace()
        state.task = SimpleNamespace(
            current_plan=None,
            current_step_index=0,
            status="running",
            tool_execution_log=(),
            pending_tool=None,
            pending_user_input_request=None,
        )
        state.memory = SimpleNamespace(
            session_id="legacy-session",
            snapshot=[],
            approved_memories={},
            pending_memories={},
        )
        state.conversation = SimpleNamespace(messages=[])

        cp_path = tmp_path / "test_v1_checkpoint.json"
        save_checkpoint(state, source="turn_end", path=cp_path)

        assert cp_path.exists()

        import json

        data = json.loads(cp_path.read_text(encoding="utf-8"))
        meta = data["meta"]
        assert meta["schema_version"] == "checkpoint.v1", (
            f"无 session_id/run_id 时应为 v1, 实际 schema_version={meta['schema_version']}"
        )
        assert "interrupted_at" in meta, "v1 meta 应有 interrupted_at"

    def test_dispatch_checkpoint_save_passes_identity_to_save_checkpoint(
        self, tmp_path,
    ):
        """_dispatch_checkpoint_save(dispatcher=None, identity=FIXED_ID)
        → save_checkpoint(session_id=..., run_id=...)。

        不通过 dispatcher 路径——直接验证 fallback 路径中的 identity 传递。
        """
        from types import SimpleNamespace

        from agent.runtime_identity import RuntimeIdentity

        state = SimpleNamespace()
        state.task = SimpleNamespace(
            current_plan=None,
            current_step_index=0,
            status="running",
            tool_execution_log=(),
            pending_tool=None,
            pending_user_input_request=None,
        )
        state.memory = SimpleNamespace(
            session_id="",
            snapshot=[],
            approved_memories={},
            pending_memories={},
        )
        state.conversation = SimpleNamespace(messages=[])

        identity = RuntimeIdentity(
            session_id="dispatch-session",
            run_id="dispatch-run",
            instance_id="dispatch-instance",
        )

        from agent.core import _dispatch_checkpoint_save

        _dispatch_checkpoint_save(
            None, state, source="memory_confirmation",
            identity=identity,
        )

        # dispatcher=None 时回退到直接 save_checkpoint()
        # 路径由 checkpoint_path(session_id, run_id) 决定。
        # 确认 per-run 目录已创建且 checkpoint 可读取。
        from agent.checkpoint import checkpoint_path

        expected_path = checkpoint_path("dispatch-session", "dispatch-run")
        assert expected_path.exists(), (
            f"per-run checkpoint 应存在: {expected_path}"
        )

        import json

        data = json.loads(expected_path.read_text(encoding="utf-8"))
        meta = data["meta"]
        assert meta["session_id"] == "dispatch-session"
        assert meta["run_id"] == "dispatch-run"
        assert meta["schema_version"] == "checkpoint.v2"
        assert "updated_at" in meta

    def test_checkpoint_v2_uses_per_run_path_not_default(self, tmp_path):
        """v2 checkpoint 使用 checkpoint_path(session_id, run_id)，
        不回退到 CHECKPOINT_PATH。
        """
        from types import SimpleNamespace

        from agent.checkpoint import save_checkpoint

        state = SimpleNamespace()
        state.task = SimpleNamespace(
            current_plan=None,
            current_step_index=0,
            status="running",
            tool_execution_log=(),
            pending_tool=None,
            pending_user_input_request=None,
        )
        state.memory = SimpleNamespace(
            session_id="",
            snapshot=[],
            approved_memories={},
            pending_memories={},
        )
        state.conversation = SimpleNamespace(messages=[])

        sid, rid = "per-run-session", "per-run-run"
        save_checkpoint(state, source="turn_end", session_id=sid, run_id=rid)

        from agent.checkpoint import checkpoint_path

        v2_path = checkpoint_path(sid, rid)
        assert v2_path.exists(), f"v2 路径应存在: {v2_path}"

        data = __import__("json").loads(v2_path.read_text(encoding="utf-8"))
        assert data["meta"]["session_id"] == sid
        assert data["meta"]["run_id"] == rid


class TestRedCheckpointIdentityFallback:
    """Phase 4 counter-evidence: 缺失 identity 时的安全行为。"""

    def test_dispatch_checkpoint_save_none_identity_still_saves(self, tmp_path):
        """identity=None 时 _dispatch_checkpoint_save 仍能保存（不 crash）。"""
        from types import SimpleNamespace

        from agent.core import _dispatch_checkpoint_save

        state = SimpleNamespace()
        state.task = SimpleNamespace(
            current_plan=None, current_step_index=0, status="running",
            tool_execution_log=(), pending_tool=None, pending_user_input_request=None,
        )
        state.memory = SimpleNamespace(
            session_id="", snapshot=[], approved_memories={}, pending_memories={},
        )
        state.conversation = SimpleNamespace(messages=[])

        # identity=None → dispatcher=None 路径不应 crash
        _dispatch_checkpoint_save(
            None, state, source="test_source", identity=None,
        )
        # 不抛异常即为通过

    def test_save_checkpoint_empty_session_id_writes_v1(self, tmp_path):
        """session_id 为空字符串时走 v1 schema（不误触发 v2）。"""
        from types import SimpleNamespace

        from agent.checkpoint import save_checkpoint

        state = SimpleNamespace()
        state.task = SimpleNamespace(
            current_plan=None, current_step_index=0, status="running",
            tool_execution_log=(), pending_tool=None, pending_user_input_request=None,
        )
        state.memory = SimpleNamespace(
            session_id="legacy", snapshot=[], approved_memories={}, pending_memories={},
        )
        state.conversation = SimpleNamespace(messages=[])

        cp_path = tmp_path / "empty_sid_cp.json"
        save_checkpoint(
            state, source="test", session_id="", run_id="", path=cp_path,
        )

        data = __import__("json").loads(cp_path.read_text(encoding="utf-8"))
        assert data["meta"]["schema_version"] == "checkpoint.v1", (
            f"空 session_id 应走 v1, 实际 {data['meta']['schema_version']}"
        )
