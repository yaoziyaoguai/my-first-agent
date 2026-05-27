"""Loop 1.3 Tool Path Unification — 方案 2 contract 测试。

验证 dispatcher-mediated tool execution contract：
- TOOL_GATE 参与真实执行生命周期
- TOOL_INVOKE 包住真实执行
- TOOL_RESULT 记录真实执行结果
- tool_result 仍进入 conversation context
- _safe_noop / probe 不被误判为真实 capability completion
"""

from __future__ import annotations

import pytest

# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def mediator_dispatcher():
    """构造含 TOOL_GATE / TOOL_INVOKE / TOOL_RESULT handler 的 dispatcher。"""
    from agent.runtime_integration import (
        ActionHandlerRegistry,
        RuntimeActionDispatcher,
        RuntimeActionType,
    )
    from agent.runtime_integration.evidence import RuntimeActionModuleObserver
    from agent.runtime_integration.tool_gate import ToolGateHandler
    from agent.runtime_integration.tool_invoke import ToolInvokeHandler
    from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler

    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
    registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
    registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


@pytest.fixture
def mediator_state(monkeypatch, tmp_path):
    """构造最小可用的 state / turn_state / messages 假对象。"""
    from unittest.mock import MagicMock

    state = MagicMock()
    state.task.tool_execution_log = {}
    state.task.current_step_index = 0
    state.task.pending_tool = None
    state.task.status = "running"
    state.task.pending_user_input_request = None
    state.task.loop_iterations = 0
    state.task.consecutive_end_turn_without_progress = 0
    state.task.current_plan = None
    state.task.tool_call_count = 0
    state.conversation.messages = []

    turn_state = MagicMock()
    turn_state.round_tool_traces = []
    turn_state.on_display_event = None
    turn_state.on_runtime_event = None
    turn_state.on_trace_event = None

    messages: list = []

    return state, turn_state, messages


def _make_tool_use_block(tool_name="echo_task_summary", tool_input=None):
    """构造一个模拟的 Anthropic tool_use block。"""
    from unittest.mock import MagicMock

    block = MagicMock()
    block.type = "tool_use"
    block.id = f"toolu_test_{tool_name}_001"
    block.name = tool_name
    block.input = tool_input or {"message": "hello"}
    return block


# ═════════════════════════════════════════════════════════════════════════════
# 方案 2 contract tests
# ═════════════════════════════════════════════════════════════════════════════


class TestToolRuntimeMediatorContract:
    """ToolRuntimeMediator 的方案 2 contract 验证。"""

    def test_t1_mediate_dispatches_tool_gate_before_execution(
        self, mediator_dispatcher, mediator_state
    ):
        """TOOL_GATE 在 execute_single_tool 之前被 dispatch。

        验证：调用 mediate() 后 dispatcher.action_log 中第一条 TOOL_GATE event
        的 action_type 确为 TOOL_GATE，且在 TOOL_INVOKE 之前。
        """
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        state, turn_state, messages = mediator_state
        mediator = ToolRuntimeMediator(
            mediator_dispatcher,
            state=state,
            turn_state=turn_state,
            turn_context={},
            messages=messages,
        )

        block = _make_tool_use_block("echo_task_summary", {"message": "hello"})
        mediator.mediate(block)

        log = mediator_dispatcher.action_log

        # 至少有 TOOL_GATE 和 TOOL_INVOKE 两条 event
        gate_events = [e for e in log if str(e.action_type) == "tool.gate"]
        invoke_events = [e for e in log if str(e.action_type) == "tool.invoke"]
        result_events = [e for e in log if str(e.action_type) == "tool.result"]

        assert len(gate_events) >= 1, "mediate() 必须 dispatch TOOL_GATE"
        assert len(invoke_events) >= 1, "mediate() 必须 dispatch TOOL_INVOKE"
        assert len(result_events) >= 1, "mediate() 必须 dispatch TOOL_RESULT"

    def test_t2_tool_gate_dispatched_before_tool_invoke(
        self, mediator_dispatcher, mediator_state
    ):
        """TOOL_GATE event 在 TOOL_INVOKE event 之前出现。

        验证 dispatcher-mediated lifecycle 顺序：GATE → INVOKE → RESULT。
        """
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        state, turn_state, messages = mediator_state
        mediator = ToolRuntimeMediator(
            mediator_dispatcher,
            state=state,
            turn_state=turn_state,
            turn_context={},
            messages=messages,
        )

        block = _make_tool_use_block("echo_task_summary", {"message": "hello"})
        mediator.mediate(block)

        log = mediator_dispatcher.action_log
        gate_idx = next(
            i for i, e in enumerate(log) if str(e.action_type) == "tool.gate"
        )
        invoke_idx = next(
            i for i, e in enumerate(log) if str(e.action_type) == "tool.invoke"
        )
        result_idx = next(
            i for i, e in enumerate(log) if str(e.action_type) == "tool.result"
        )

        assert (
            gate_idx < invoke_idx < result_idx
        ), f"顺序错误: GATE@{gate_idx} → INVOKE@{invoke_idx} → RESULT@{result_idx}"

    def test_t3_handle_tool_use_response_uses_mediator_when_dispatcher_available(
        self, mediator_dispatcher, mediator_state, monkeypatch
    ):
        """handle_tool_use_response 在有 dispatcher 时走 mediator 路径。

        验证：传入 runtime_action_dispatcher 后，工具执行路径经过 mediator，
        dispatcher.action_log 产生 TOOL_GATE / TOOL_INVOKE / TOOL_RESULT。
        """
        from unittest.mock import MagicMock

        from agent.response_handlers import handle_tool_use_response

        state, turn_state, messages = mediator_state

        # 构造一个假的 model response（含 tool_use block）
        block = _make_tool_use_block("echo_task_summary", {"message": "test"})
        response = MagicMock()
        response.stop_reason = "tool_use"
        response.content = [block]

        def fake_extract_text(content):
            return ""

        result = handle_tool_use_response(
            response,
            state=state,
            turn_state=turn_state,
            messages=messages,
            extract_text_fn=fake_extract_text,
            runtime_action_dispatcher=mediator_dispatcher,
        )

        log = mediator_dispatcher.action_log
        gate_events = [e for e in log if str(e.action_type) == "tool.gate"]
        invoke_events = [e for e in log if str(e.action_type) == "tool.invoke"]
        result_events = [e for e in log if str(e.action_type) == "tool.result"]

        assert len(gate_events) >= 1, (
            "handle_tool_use_response 在有 dispatcher 时必须 dispatch TOOL_GATE"
        )
        assert len(invoke_events) >= 1, (
            "handle_tool_use_response 在有 dispatcher 时必须 dispatch TOOL_INVOKE"
        )
        assert len(result_events) >= 1, (
            "handle_tool_use_response 在有 dispatcher 时必须 dispatch TOOL_RESULT"
        )
        # 不应返回 FORCE_STOP 或 AWAITING_USER（echo_task_summary 不需要确认）
        assert result is None or result == "", (
            f"普通工具执行不应返回 sentinel，实际返回: {result!r}"
        )

    def test_t4_handle_tool_use_response_falls_back_without_dispatcher(
        self, mediator_state
    ):
        """handle_tool_use_response 在无 dispatcher 时回退到裸调 execute_single_tool。

        验证向后兼容：不传 runtime_action_dispatcher 时，函数不崩溃。
        """
        from unittest.mock import MagicMock

        from agent.response_handlers import handle_tool_use_response

        state, turn_state, messages = mediator_state

        block = _make_tool_use_block("echo_task_summary", {"message": "test"})
        response = MagicMock()
        response.stop_reason = "tool_use"
        response.content = [block]

        def fake_extract_text(content):
            return ""

        # 不传 runtime_action_dispatcher：应回退到直接调用 execute_single_tool
        result = handle_tool_use_response(
            response,
            state=state,
            turn_state=turn_state,
            messages=messages,
            extract_text_fn=fake_extract_text,
            # 不传 runtime_action_dispatcher
        )

        # 不应崩溃
        assert result is None or result == ""

    def test_t5_tool_result_in_conversation_after_mediation(
        self, mediator_dispatcher, mediator_state
    ):
        """append_tool_result 在 mediator 路径后仍写入 messages。

        验证 conversation context 不受 mediator 影响。
        """
        from unittest.mock import MagicMock

        from agent.response_handlers import handle_tool_use_response

        state, turn_state, messages = mediator_state

        block = _make_tool_use_block("echo_task_summary", {"message": "test"})
        response = MagicMock()
        response.stop_reason = "tool_use"
        response.content = [block]

        def fake_extract_text(content):
            return ""

        handle_tool_use_response(
            response,
            state=state,
            turn_state=turn_state,
            messages=messages,
            extract_text_fn=fake_extract_text,
            runtime_action_dispatcher=mediator_dispatcher,
        )

        # tool_result 应写入 messages（execute_single_tool 通过 append_tool_result）
        tool_results = [
            m
            for m in messages
            if m.get("role") == "user"
            and any(
                c.get("type") == "tool_result" for c in m.get("content", [])
            )
        ]
        assert len(tool_results) >= 1, (
            "mediate() 后 messages 中必须有 tool_result，"
            f"当前 messages: {messages}"
        )

    def test_t6_execute_single_tool_still_called_for_confirmation_audit(
        self, mediator_dispatcher, mediator_state
    ):
        """execute_single_tool 仍负责 confirmation / policy / audit。

        验证 mediator.mediate() 确实调用了 execute_single_tool（通过
        tool_execution_log 的写入来确认）。
        """
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        state, turn_state, messages = mediator_state

        mediator = ToolRuntimeMediator(
            mediator_dispatcher,
            state=state,
            turn_state=turn_state,
            turn_context={},
            messages=messages,
        )

        block = _make_tool_use_block("echo_task_summary", {"message": "test"})
        mediator.mediate(block)

        # execute_single_tool 应写入 tool_execution_log
        assert len(state.task.tool_execution_log) >= 1, (
            "mediate() 必须通过 execute_single_tool 写入 tool_execution_log"
        )

        log_entry = list(state.task.tool_execution_log.values())[0]
        # 工具名可能被 _normalize_tool_name 加上 namespace 前缀
        assert "echo_task_summary" in log_entry.get("tool", ""), (
            f"tool_execution_log 应记录工具名（含 echo_task_summary），实际: {log_entry}"
        )


class Test方案2防呆:
    """方案 3（执行后补 evidence）不会被误判为方案 2 的 guard tests。"""

    def test_t7_dispatcher_is_mediator_not_post_hoc_logger(self):
        """ToolRuntimeMediator 在 execute_single_tool 之前调用 dispatcher。

        方案 3 的特征是 dispatcher 调用在所有执行完成后才发生。
        方案 2 的 mediator 在 execute_single_tool 之前就 dispatch TOOL_GATE/TOOL_INVOKE。

        此测试通过代码结构验证（非运行时）：ToolRuntimeMediator.mediate() 方法中
        TOOL_GATE dispatch 代码在 execute_single_tool 调用之前。
        """
        import inspect

        from agent.tool_runtime_mediator import ToolRuntimeMediator

        source = inspect.getsource(ToolRuntimeMediator.mediate)
        # 搜索实际调用（含括号），避免 docstring 中出现的函数名干扰
        gate_pos = source.find("_route_gate(")
        invoke_pos = source.find("_route_invoke(")
        exec_pos = source.find("execute_single_tool(")

        assert gate_pos >= 0, "mediate() 必须包含 _route_gate() 调用"
        assert invoke_pos >= 0, "mediate() 必须包含 _route_invoke() 调用"
        assert exec_pos >= 0, "mediate() 必须包含 execute_single_tool() 调用"
        assert gate_pos < exec_pos, (
            "TOOL_GATE (_route_gate) 必须在 execute_single_tool 之前调用，"
            "否则退化为方案 3"
        )
        assert invoke_pos < exec_pos, (
            "TOOL_INVOKE (_route_invoke) 必须在 execute_single_tool 之前调用，"
            "否则退化为方案 3"
        )

    def test_t8_handle_tool_use_response_no_longer_bare_calls_execute_single_tool(
        self,
    ):
        """handle_tool_use_response 在有 mediator 时不裸调 execute_single_tool。

        方案 3 的特征：handle_tool_use_response 仍直接调用 execute_single_tool，
        dispatcher 在事后补 evidence。方案 2：通过 mediator.mediate() 调用。

        验证 mediator 路径存在且 execute_single_tool 调用在 else 分支（回退路径）。
        """
        import inspect

        from agent.response_handlers import handle_tool_use_response

        source = inspect.getsource(handle_tool_use_response)
        # mediator.mediate 调用应在 execute_single_tool 直接调用之前
        mediate_pos = source.find("_mediator.mediate")
        exec_pos = source.find("execute_single_tool(")

        assert mediate_pos >= 0, (
            "handle_tool_use_response 应包含 _mediator.mediate() 调用"
        )
        assert exec_pos >= 0, (
            "handle_tool_use_response 仍包含 execute_single_tool 回退路径"
        )
        assert mediate_pos < exec_pos, (
            "mediator.mediate() 应在 execute_single_tool 直接调用之前出现，"
            "否则说明 mediator 路径不是主路径"
        )


class TestSafeNoopNotCapabilityCompletion:
    """_safe_noop / probe 不应被误判为真实 Tool capability completion。"""

    def test_t9_turn_end_pipeline_still_uses_safe_noop_by_default(self):
        """LoopDependencies.tool_gate_tool_name 默认值为 _safe_noop。

        _safe_noop 是 pipeline 心跳，不应该被当成 Tool capability completion。
        turn-end _dispatch_tool_pipeline 接收 tool_gate_tool_name 参数，
        默认值由 LoopDependencies 提供。
        """
        import inspect

        from agent.loop import LoopDependencies

        source = inspect.getsource(LoopDependencies)
        # LoopDependencies 的 tool_gate_tool_name 字段默认值应为 _safe_noop
        assert '"_safe_noop"' in source, (
            "LoopDependencies.tool_gate_tool_name 默认应为 _safe_noop，"
            "它是 pipeline 心跳，不应被移除"
        )

    def test_t10_dispatcher_action_log_distinguishes_business_vs_probe(self):
        """dispatcher action_log 中 business TOOL_INVOKE 和 probe TOOL_INVOKE 来源不同。

        business TOOL_INVOKE 来自 handle_tool_use_response / ToolRuntimeMediator；
        probe TOOL_INVOKE 来自 turn-end _dispatch_tool_pipeline。

        两者 source 字段不同，不应混淆。
        """
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.evidence import RuntimeActionModuleObserver
        from agent.runtime_integration.schema import RuntimeActionRequest
        from agent.runtime_integration.tool_gate import ToolGateHandler
        from agent.runtime_integration.tool_invoke import ToolInvokeHandler
        from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler

        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
        registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver()
        )

        # business call：source 来自 ToolRuntimeMediator
        dispatcher.route_from_runtime_loop(
            RuntimeActionRequest(
                action_type=RuntimeActionType.TOOL_INVOKE,
                source="ToolRuntimeMediator",
                parent_trace_id="test_biz_001",
                payload={"tool_name": "echo_task_summary", "tool_input": {}},
            ),
            core_entrypoint="core.chat",
            runtime_hook_name="handle_tool_use_response",
        )

        # probe call：source 来自 turn-end hook
        dispatcher.route_from_runtime_loop(
            RuntimeActionRequest(
                action_type=RuntimeActionType.TOOL_INVOKE,
                source="turn_end_hook",
                parent_trace_id="test_probe_001",
                payload={"tool_name": "_safe_noop", "tool_input": {}},
            ),
            core_entrypoint="core.chat",
            runtime_hook_name="loop.turn_end",
        )

        biz_events = [
            e
            for e in dispatcher.action_log
            if e.evidence.get("tool_name") == "echo_task_summary"
        ]
        probe_events = [
            e
            for e in dispatcher.action_log
            if e.evidence.get("tool_name") == "_safe_noop"
        ]

        assert len(biz_events) == 1, "business tool 应有自己的 event"
        assert len(probe_events) == 1, "_safe_noop probe 应有自己的 event"
        # 来源不同，不会混淆
        assert biz_events[0].source != probe_events[0].source, (
            "business event 和 probe event 的 source 必须不同"
        )


def inspect_getsource(obj):
    """兼容的 getsource wrapper。"""
    import inspect
    return inspect.getsource(obj)
