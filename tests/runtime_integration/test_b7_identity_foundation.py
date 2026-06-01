"""B7 Slice 1: Identity Foundation — focused contract tests.

覆盖 RuntimeIdentity 值对象、RuntimeActionEvent identity 字段、SESSION_ID 迁移、
LoopContext 注入、Dispatcher identity 传播、防伪验证。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent.runtime_identity import RuntimeIdentity
from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionRequest,
    RuntimeActionType,
)

# ── RED-1.1: RuntimeIdentity 值对象 ────────────────────────────────────


class TestRuntimeIdentityValueObject:
    def test_creation(self):
        identity = RuntimeIdentity(session_id="s1", run_id="r1")
        assert identity.session_id == "s1"
        assert identity.run_id == "r1"
        assert identity.instance_id == "s1"

    def test_explicit_instance_id(self):
        identity = RuntimeIdentity(session_id="s1", run_id="r1", instance_id="i1")
        assert identity.instance_id == "i1"

    def test_frozen(self):
        identity = RuntimeIdentity(session_id="s1", run_id="r1")
        with pytest.raises(FrozenInstanceError):
            identity.session_id = "s2"  # type: ignore[misc]

    def test_slots(self):
        identity = RuntimeIdentity(session_id="s1", run_id="r1")
        # frozen=True + slots=True → 非 slot 属性赋值抛出 TypeError
        with pytest.raises(TypeError):
            identity.new_field = 42  # type: ignore[attr-defined]


# ── RED-1.2: RuntimeActionEvent identity 字段 ──────────────────────────


class TestRuntimeActionEventIdentity:
    def test_default_identity_empty(self):
        """新 RuntimeActionEvent 的 identity 字段默认为空字符串。"""
        from agent.runtime_integration.schema import RuntimeActionEvent

        event = RuntimeActionEvent(
            event_id="ev1",
            action_id="act1",
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            status="allowed",
            evidence={},
            parent_trace_id="",
        )
        assert event.session_id == ""
        assert event.run_id == ""
        assert event.instance_id == ""

    def test_event_with_identity(self):
        from agent.runtime_integration.schema import RuntimeActionEvent

        event = RuntimeActionEvent(
            event_id="ev1",
            action_id="act1",
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            status="allowed",
            evidence={},
            parent_trace_id="",
            session_id="s1",
            run_id="r1",
            instance_id="i1",
        )
        assert event.session_id == "s1"
        assert event.run_id == "r1"
        assert event.instance_id == "i1"

    def test_existing_event_construction_unbroken(self):
        """现有构造方式（不传 identity 字段）仍然有效。"""
        from agent.runtime_integration.schema import RuntimeActionEvent

        event = RuntimeActionEvent(
            event_id="ev2",
            action_id="act2",
            action_type=RuntimeActionType.TOOL_REQUEST,
            source="model",
            status="requested",
            evidence={"tool_name": "test_tool"},
            parent_trace_id="trace1",
        )
        assert event.event_id == "ev2"
        assert event.action_id == "act2"
        assert event.parent_trace_id == "trace1"
        assert event.evidence == {"tool_name": "test_tool"}


# ── RED-1.3: SESSION_ID 迁移 ────────────────────────────────────────────


class TestSessionIdMigration:
    def test_import_time_session_id_still_exists(self):
        """向后兼容：模块级 SESSION_ID 仍然存在。"""
        import agent.logger as logger_mod

        assert hasattr(logger_mod, "SESSION_ID")
        assert isinstance(logger_mod.SESSION_ID, str)
        assert len(logger_mod.SESSION_ID) > 0

    def test_set_runtime_session_id_updates_get(self):
        """main.py 调用 set_runtime_session_id() 后 get_runtime_session_id() 返回新值。"""
        from agent.logger import get_runtime_session_id, set_runtime_session_id

        original = get_runtime_session_id()
        try:
            set_runtime_session_id("test-session-001")
            assert get_runtime_session_id() == "test-session-001"
        finally:
            # 恢复
            set_runtime_session_id(original)


# ── RED-1.4: RuntimeIdentity 注入到 LoopContext ────────────────────────


class TestLoopContextIdentity:
    def test_loop_context_has_identity_field(self):
        from agent.loop_context import LoopContext

        ctx = LoopContext(
            client="fake_client",
            model_name="fake-model",
            max_loop_iterations=10,
            runtime_identity=None,
        )
        assert hasattr(ctx, "runtime_identity")
        assert ctx.runtime_identity is None

    def test_loop_context_with_identity(self):
        from agent.loop_context import LoopContext

        identity = RuntimeIdentity(session_id="s1", run_id="r1")
        ctx = LoopContext(
            client="fake_client",
            model_name="fake-model",
            max_loop_iterations=10,
            runtime_identity=identity,
        )
        assert ctx.runtime_identity is identity
        assert ctx.runtime_identity.session_id == "s1"
        assert ctx.runtime_identity.run_id == "r1"


# ── RED-1.5: Identity 写入 RuntimeActionEvent(dispatcher) ──────────────


class _IdentityProbeHandler:
    """不需要 catalog entry 的测试 handler，通过 observe_module_call 产生 evidence。"""

    def handle(self, request, context):  # noqa: ANN001
        observed = context.observe_module_call(
            target_module="FakeTargetModule",
            function_called="FakeTargetModule.ping",
            call_signature="ping()",
            call=lambda: {"value": "pong"},
        )
        return context.success(
            handler_name=type(self).__name__,
            target_module="FakeTargetModule",
            payload={"value": "pong"},
            observed_call=observed,
        )


@pytest.fixture
def dispatcher():
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_GATE, _IdentityProbeHandler())
    return RuntimeActionDispatcher(registry)


class TestDispatcherIdentityPropagation:
    def test_route_from_runtime_loop_writes_identity(self, dispatcher):
        """route_from_runtime_loop() 产生的 event 有正确的 identity 字段。"""
        identity = RuntimeIdentity(session_id="s1", run_id="r1")
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="runtime",
            payload={},
            parent_trace_id="",
        )
        result = dispatcher.route_from_runtime_loop(
            request, identity=identity,
        )
        assert result.status == "success"

        events = dispatcher.action_log
        assert len(events) >= 1
        event = events[-1]
        assert event.session_id == "s1"
        assert event.run_id == "r1"

    def test_direct_route_identity_empty(self, dispatcher):
        """dispatcher.route() 产生的 event 的 identity 字段为空（向后兼容）。"""
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="harness",
            payload={},
            parent_trace_id="",
        )
        result = dispatcher.route(request)
        assert result.status == "success"

        events = dispatcher.action_log
        assert len(events) >= 1
        event = events[-1]
        assert event.session_id == ""
        assert event.run_id == ""

    def test_identity_not_from_payload(self, dispatcher):
        """即使 request.payload 中有 _identity，event 也只来自 dispatcher 参数。"""
        identity = RuntimeIdentity(session_id="real-sid", run_id="real-rid")
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="runtime",
            payload={
                "_identity": {"session_id": "fake-sid", "run_id": "fake-rid"},
            },
            parent_trace_id="",
        )
        result = dispatcher.route_from_runtime_loop(
            request, identity=identity,
        )
        assert result.status == "success"

        events = dispatcher.action_log
        event = events[-1]
        # identity 来自 dispatcher 参数，不是 payload
        assert event.session_id == "real-sid"
        assert event.run_id == "real-rid"
        assert event.session_id != "fake-sid"
