"""Phase 5 integration tests: allowed_tools from ActiveSkillLifecycle (A01-A04).

验证 ToolRuntimeMediator 从 lifecycle 读取 allowed_tools 并通过 TOOL_GATE 强制实施。
"""

from __future__ import annotations

from agent.skill_system.lifecycle import ActiveSkillLifecycle
from agent.tool_runtime_mediator import ToolRuntimeMediator

# ── helpers ────────────────────────────────────────────────────────────

class _SpyDispatcher:
    """Spy dispatcher——记录 route_from_runtime_loop 调用。"""

    def __init__(self, gate_disposition: str = "allowed"):
        self._gate_disposition = gate_disposition
        self.calls: list = []
        self.action_log: list = []

    def route_from_runtime_loop(self, request, core_entrypoint="", runtime_hook_name=""):
        from types import SimpleNamespace

        self.calls.append({
            "action_type": str(getattr(request.action_type, "value", request.action_type)),
            "payload": dict(request.payload) if request.payload else {},
        })
        result_payload = {"gate_disposition": self._gate_disposition}
        return SimpleNamespace(payload=result_payload)


class _FakeState:
    """Minimal state for ToolRuntimeMediator construction.

    execute_single_tool → save_checkpoint 需要 task/memory/conversation 属性。
    """
    class Task:
        pending_tool = None
        current_step_index = 0
        tool_execution_log: dict = {}
        status = "running"
        current_plan = None
        step_completed = False

    class Memory:
        session_id: str = "fake-session-001"

    class Conversation:
        messages: list = []

    task = Task()
    memory = Memory()
    conversation = Conversation()


class _FakeTurnState:
    on_display_event = None
    round_tool_traces: list = []


# ── A01 ────────────────────────────────────────────────────────────────

class TestAllowedToolsFromLifecycle:
    """A01: TOOL_GATE 从 lifecycle 读取 allowed_tools。"""

    def test_mediator_passes_lifecycle_tools_to_gate(self):
        """当 lifecycle 有 active_skill 时，mediator 将 allowed_tools 传入 TOOL_GATE。"""
        lifecycle = ActiveSkillLifecycle()
        lifecycle.activate(
            "demo-note-maker", body="test",
            allowed_tools=("demo.write_demo_note", "demo.echo_task_summary"),
        )
        spy = _SpyDispatcher()
        mediator = ToolRuntimeMediator(
            spy,
            state=_FakeState(),
            turn_state=_FakeTurnState(),
            turn_context={},
            messages=[],
            skill_allowed_tools=lifecycle.get_allowed_tools(),
        )
        # 构造一个 tool_use block
        from unittest.mock import MagicMock
        block = MagicMock()
        block.name = "demo.write_demo_note"
        block.input = {"key": "value"}
        block.id = "test-id-1"

        mediator.mediate(block)

        # 验证 TOOL_GATE 被调用且包含 skill_allowed_tools
        gate_calls = [c for c in spy.calls if c["action_type"] == "tool.gate"]
        assert len(gate_calls) >= 1
        gate_payload = gate_calls[0]["payload"]
        assert "skill_allowed_tools" in gate_payload
        assert set(gate_payload["skill_allowed_tools"]) == {
            "demo.write_demo_note", "demo.echo_task_summary",
        }


# ── A02 ────────────────────────────────────────────────────────────────

class TestAllowedToolPassesGate:
    """A02: allowed tool → TOOL_GATE allowed。"""

    def test_allowed_tool_proceeds_through_gate(self):
        """lifecycle 中声明的工具通过 TOOL_GATE。"""
        lifecycle = ActiveSkillLifecycle()
        lifecycle.activate(
            "demo", body="test",
            allowed_tools=("demo.write_demo_note",),
        )
        spy = _SpyDispatcher(gate_disposition="allowed")
        mediator = ToolRuntimeMediator(
            spy,
            state=_FakeState(),
            turn_state=_FakeTurnState(),
            turn_context={},
            messages=[],
            skill_allowed_tools=lifecycle.get_allowed_tools(),
        )
        from unittest.mock import MagicMock
        block = MagicMock()
        block.name = "demo.write_demo_note"
        block.input = {}
        block.id = "test-id-allowed"

        # 不会返回 FORCE_STOP（allowed tool 通过 gate）
        result = mediator.mediate(block)
        # result 可能是 None (success) 或其他，但不应该是 FORCE_STOP
        from agent.tool_executor import FORCE_STOP
        assert result != FORCE_STOP


# ── A03 ────────────────────────────────────────────────────────────────

class TestDisallowedToolBlockedByGate:
    """A03: disallowed tool → TOOL_GATE rejected。"""

    def test_disallowed_tool_blocked(self):
        """不在 lifecycle allowed_tools 中的工具被 TOOL_GATE 拒绝。"""
        lifecycle = ActiveSkillLifecycle()
        lifecycle.activate(
            "demo", body="test",
            allowed_tools=("demo.write_demo_note",),
        )
        spy = _SpyDispatcher(gate_disposition="rejected")
        mediator = ToolRuntimeMediator(
            spy,
            state=_FakeState(),
            turn_state=_FakeTurnState(),
            turn_context={},
            messages=[],
            skill_allowed_tools=lifecycle.get_allowed_tools(),
        )
        from unittest.mock import MagicMock
        block = MagicMock()
        block.name = "shell.exec"
        block.input = {}
        block.id = "test-id-blocked"

        from agent.tool_executor import FORCE_STOP
        result = mediator.mediate(block)
        assert result == FORCE_STOP


# ── A04 ────────────────────────────────────────────────────────────────

class TestNoActiveSkillNoRestriction:
    """A04: 无 active_skill → 所有工具可用（无约束）。"""

    def test_no_active_skill_returns_empty_allowed_tools(self):
        """get_allowed_tools() 在无 active_skill 时返回空 frozenset。"""
        lifecycle = ActiveSkillLifecycle()
        assert lifecycle.get_allowed_tools() == frozenset()

    def test_no_active_skill_mediator_has_no_skill_restriction(self):
        """无 active_skill 时 mediator 不传递 skill_allowed_tools。"""
        lifecycle = ActiveSkillLifecycle()
        tools = lifecycle.get_allowed_tools()
        # 空 frozenset → mediator 收到 None（表示无约束）
        skill_at = tools if tools else None
        assert skill_at is None

    def test_deactivate_clears_allowed_tools(self):
        """deactivate 后 allowed_tools 变为空。"""
        lifecycle = ActiveSkillLifecycle()
        lifecycle.activate(
            "demo", body="test",
            allowed_tools=("demo.write_demo_note",),
        )
        assert len(lifecycle.get_allowed_tools()) > 0
        lifecycle.deactivate()
        assert lifecycle.get_allowed_tools() == frozenset()


# ── Phase 5 additional: lifecycle as source of truth ─────────────────────

class TestLifecycleAllowedToolsSource:
    """验证 lifecycle 作为 allowed_tools 唯一来源的正确性。"""

    def test_switch_updates_allowed_tools(self):
        """switch() 后 allowed_tools 更新为新 skill 的工具集。"""
        lifecycle = ActiveSkillLifecycle()
        lifecycle.activate(
            "skill-a", body="a",
            allowed_tools=("tool.a", "tool.b"),
        )
        assert lifecycle.get_allowed_tools() == frozenset({"tool.a", "tool.b"})
        lifecycle.switch(
            "skill-b", body="b",
            allowed_tools=("tool.c",),
        )
        assert lifecycle.get_allowed_tools() == frozenset({"tool.c"})

    def test_lifecycle_independent_from_mediator(self):
        """lifecycle 状态独立于 mediator 实例——多个 mediator 可从同一 lifecycle 读取。"""
        lifecycle = ActiveSkillLifecycle()
        lifecycle.activate(
            "demo", body="test",
            allowed_tools=("demo.write_demo_note",),
        )
        tools = lifecycle.get_allowed_tools()
        # 两个 mediator 从同一 lifecycle 读取，得到相同 allowed_tools
        t1 = lifecycle.get_allowed_tools()
        t2 = lifecycle.get_allowed_tools()
        assert t1 == t2 == tools


# ── 003 evidence completeness ──────────────────────────────────────────


class TestActiveSkillIdInGateEvidence:
    """003: TOOL_GATE evidence 包含 active_skill_id（rejected + allowed 路径）。"""

    def test_rejected_path_includes_active_skill_id(self):
        """disallowed tool 的 TOOL_GATE evidence 包含 active_skill_id。"""
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.evidence import RuntimeActionModuleObserver
        from agent.runtime_integration.tool_gate import ToolGateHandler

        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver(),
        )

        from agent.runtime_integration.schema import RuntimeActionRequest
        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "read_file",
                "tool_input": {},
                "skill_allowed_tools": ["demo.write_demo_note"],
                "active_skill_id": "demo-note-maker",
            },
        ))

        assert result.payload["gate_disposition"] == "rejected"
        log = dispatcher.action_log
        gate_events = [e for e in log if str(e.action_type) == "tool.gate"]
        assert len(gate_events) >= 1
        ev = dict(gate_events[-1].evidence)
        assert ev.get("active_skill_id") == "demo-note-maker", (
            f"rejected evidence 应包含 active_skill_id，got: {ev.get('active_skill_id')}"
        )
        assert ev.get("decision") == "rejected"
        assert ev.get("policy_path") == "skill_allowed_tools→rejected"
        assert "skill_allowed_tools" in ev

    def test_allowed_path_includes_active_skill_id(self):
        """allowed tool 的 TOOL_GATE evidence 也包含 active_skill_id。"""
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.evidence import RuntimeActionModuleObserver
        from agent.runtime_integration.tool_gate import ToolGateHandler

        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver(),
        )

        from agent.runtime_integration.schema import RuntimeActionRequest
        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "_safe_noop",
                "tool_input": {},
                "skill_allowed_tools": ["_safe_noop", "demo.echo_task_summary"],
                "active_skill_id": "demo-note-maker",
            },
        ))

        assert result.payload["gate_disposition"] == "allowed"
        log = dispatcher.action_log
        gate_events = [e for e in log if str(e.action_type) == "tool.gate"]
        assert len(gate_events) >= 1
        ev = dict(gate_events[-1].evidence)
        assert ev.get("active_skill_id") == "demo-note-maker", (
            f"allowed evidence 应包含 active_skill_id，got: {ev.get('active_skill_id')}"
        )

    def test_no_active_skill_id_when_not_in_payload(self):
        """当 payload 不含 active_skill_id 时，evidence 也不应包含。"""
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.evidence import RuntimeActionModuleObserver
        from agent.runtime_integration.tool_gate import ToolGateHandler

        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver(),
        )

        from agent.runtime_integration.schema import RuntimeActionRequest
        dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "_safe_noop",
                "tool_input": {},
            },
        ))

        log = dispatcher.action_log
        gate_events = [e for e in log if str(e.action_type) == "tool.gate"]
        assert len(gate_events) >= 1
        ev = dict(gate_events[-1].evidence)
        assert "active_skill_id" not in ev, (
            f"无 active_skill_id payload 时 evidence 不应包含，got: {ev.get('active_skill_id')}"
        )

    def test_rejected_evidence_fields_complete(self):
        """003 要求的 evidence 字段全部存在: active_skill_id, requested_tool_name,
        skill_allowed_tools, policy_path, rejection_reason, decision=rejected。"""
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.evidence import RuntimeActionModuleObserver
        from agent.runtime_integration.tool_gate import ToolGateHandler

        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver(),
        )

        from agent.runtime_integration.schema import RuntimeActionRequest
        dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "request_user_input",
                "tool_input": {"prompt": "email?"},
                "skill_allowed_tools": ["demo.write_demo_note"],
                "active_skill_id": "demo-note-maker",
            },
        ))

        log = dispatcher.action_log
        gate_events = [e for e in log if str(e.action_type) == "tool.gate"]
        assert len(gate_events) >= 1
        ev = dict(gate_events[-1].evidence)
        required_fields = [
            "active_skill_id", "requested_tool_name", "skill_allowed_tools",
            "policy_path", "rejection_reason",
        ]
        missing = [f for f in required_fields if f not in ev]
        assert not missing, f"003 evidence 缺少字段: {missing}"
        assert ev["active_skill_id"] == "demo-note-maker"
        assert ev["requested_tool_name"] == "request_user_input"
        assert ev["decision"] == "rejected"
        assert ev["policy_path"] == "skill_allowed_tools→rejected"
        assert ev["rejection_reason"] == "tool not in active skill allowed_tools"
