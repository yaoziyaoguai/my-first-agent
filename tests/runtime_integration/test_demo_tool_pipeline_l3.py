"""Demo 工具 L3 dispatch path 验证。

验证 demo.echo_task_summary 可通过 turn-end hook 的 TOOL_GATE → TOOL_INVOKE →
TOOL_RESULT 完整管线执行，达到 real_core_loop_runtime_e2e。

demo.write_demo_note 因 confirmation="always" 走 confirmation_required 分支，
不经过 TOOL_INVOKE（gate_disposition != "allowed"），其 L3 gate 路径在单独测试中验证。

架构依据：
- docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md Section 5.1 (Evidence Label Precision)
- agent/loop.py _try_phase1_turn_end_runtime_action
"""

from __future__ import annotations

from typing import Any

from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
)
from agent.runtime_integration.evidence import (
    REAL_CORE_LOOP_RUNTIME_E2E,
    RuntimeActionModuleObserver,
)
from agent.runtime_integration.schema import RuntimeActionRequest
from agent.runtime_integration.tool_gate import ToolGateHandler
from agent.runtime_integration.tool_invoke import ToolInvokeHandler
from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler

# ========== 测试辅助 ==========


def _build_pipeline_dispatcher() -> RuntimeActionDispatcher:
    """构建注册了 TOOL_GATE + TOOL_INVOKE + TOOL_RESULT handler 的 dispatcher。"""
    import agent.tools  # noqa: F401 - 触发工具注册
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
    registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
    registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


class _PipelineSpy:
    """捕获 route 调用的 spy dispatcher 包装器。"""

    def __init__(self, real: RuntimeActionDispatcher) -> None:
        self._real = real
        self.captured: list[tuple[str, RuntimeActionRequest, Any]] = []

    def route(self, request: RuntimeActionRequest) -> Any:
        result = self._real.route(request)
        self.captured.append(("route", request, result))
        return result

    def route_from_runtime_loop(self, request: RuntimeActionRequest, **kwargs: object) -> Any:
        result = self._real.route_from_runtime_loop(request)
        self.captured.append(("route_from_runtime_loop", request, result))
        return result

    @property
    def action_log(self):
        return self._real.action_log


def _make_mock_state():
    """构造最小 mock state。"""

    class _MockConversation:
        messages: list[dict] = [{"role": "user", "content": "请总结当前任务"}]

    class _MockState:
        conversation = _MockConversation()

    return _MockState()


# ========== D1: demo.echo_task_summary 完整 L3 Pipeline ==========


class TestDemoEchoTaskSummaryL3Pipeline:
    """demo.echo_task_summary 经 turn-end hook 完整管线 (gate → invoke → result) L3 验证。"""

    def test_d1_full_pipeline_l3_echo_task_summary(self):
        """D1: demo.echo_task_summary 通过 turn-end hook 完成 gate → invoke → result。

        验证以 tool_gate_tool_name="demo.echo_task_summary" 调用
        _try_phase1_turn_end_runtime_action 后，TOOL_GATE → TOOL_INVOKE → TOOL_RESULT
        三个 stage 均通过 route_from_runtime_loop 路由，达到 real_core_loop_runtime_e2e。
        """
        import agent.tools  # noqa: F401
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action

        dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(dispatcher)
        mock_state = _make_mock_state()

        deps = LoopDependencies(
            state=mock_state,
            call_model=lambda s, ctx: None,
            dispatch_model_output=lambda resp: "demo response",
            runtime_loop_fields=lambda: {},
            safe_emit_runtime_event=lambda cb, ev: None,
            clear_checkpoint=lambda: None,
            tool_gate_tool_name="demo.echo_task_summary",
        )

        _try_phase1_turn_end_runtime_action(
            state=mock_state,
            result_text="demo response",
            dispatcher=spy,
            dependencies=deps,
        )

        # 按 action_type 分组
        by_type: dict[str, list[tuple[str, RuntimeActionRequest, Any]]] = {}
        for method, request, result in spy.captured:
            at = request.action_type.value
            by_type.setdefault(at, []).append((method, request, result))

        # 验证 TOOL_GATE 达到 L3
        gate_entries = by_type.get("tool.gate", [])
        assert len(gate_entries) >= 1, "应有 TOOL_GATE action"
        gate_method, gate_request, gate_result = gate_entries[0]
        assert gate_method == "route_from_runtime_loop"
        assert gate_request.payload["tool_name"] == "demo.echo_task_summary"
        gate_evidence = dict(gate_result.evidence)
        assert gate_evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"TOOL_GATE 应达到 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {gate_evidence.get('evidence_level')!r}"
        )
        # 确认 gate disposition 是 allowed（confirmation="never"）
        assert gate_result.payload.get("gate_disposition") == "allowed", (
            f"demo.echo_task_summary gate 应为 allowed，"
            f"实际 {gate_result.payload.get('gate_disposition')!r}"
        )

        # 验证 TOOL_INVOKE 达到 L3
        invoke_entries = by_type.get("tool.invoke", [])
        assert len(invoke_entries) >= 1, "gate allowed 后应有 TOOL_INVOKE action"
        invoke_method, invoke_request, invoke_result = invoke_entries[0]
        assert invoke_method == "route_from_runtime_loop"
        assert invoke_request.payload["tool_name"] == "demo.echo_task_summary"
        invoke_evidence = dict(invoke_result.evidence)
        assert invoke_evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E

        # TOOL_INVOKE 只记录 invoke_started evidence，不执行工具
        assert invoke_result.payload.get("disposition") == "evidence_only", (
            f"demo.echo_task_summary 应只记录 evidence_only，"
            f"实际 {invoke_result.payload.get('disposition')!r}"
        )
        assert invoke_result.payload.get("tool_invoked") is False
        assert invoke_result.payload.get("execution_status") == "not_executed"
        assert invoke_result.payload.get("tool_output") is None

        # 验证 TOOL_RESULT 达到 L3
        result_entries = by_type.get("tool.result", [])
        assert len(result_entries) >= 1, "TOOL_INVOKE 后应有 TOOL_RESULT action"
        result_method, result_request, result_result = result_entries[0]
        assert result_method == "route_from_runtime_loop"
        result_evidence = dict(result_result.evidence)
        assert result_evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E

        # 验证 TOOL_RESULT payload 包含正确的工具输出
        assert result_request.payload.get("tool_name") == "demo.echo_task_summary"
        assert "tool_output" in result_request.payload

    def test_d2_echo_task_summary_business_output(self):
        """D2: demo.echo_task_summary 返回有意义的业务输出。

        验证工具输出包含可读的任务摘要，而非仅返回空字符串或固定 noop 文本。
        """
        import agent.tools  # noqa: F401
        from agent.tool_registry import execute_tool

        result = execute_tool("demo.echo_task_summary", {})
        assert isinstance(result, str)
        assert len(result) > 5, f"输出过短: {result!r}"
        # 输出应包含有意义的摘要信息
        assert any(
            keyword in result.lower()
            for keyword in ["demo", "task", "local", "fake", "summary", "agent"]
        ), f"输出缺少预期关键词: {result!r}"


# ========== D3: demo.write_demo_note gate 路径验证 ==========


class TestDemoWriteDemoNoteGateL3:
    """demo.write_demo_note 的 TOOL_GATE L3 路径验证。

    demo.write_demo_note 因 confirmation="always" 走 confirmation_required 分支，
    TOOL_INVOKE 不会被触发（gate_disposition != "allowed"）。
    这验证了 confirmation_required 路径的正确性——工具被 gate 识别但需要用户确认。
    """

    def test_d3_write_demo_note_gate_confirmation_required(self):
        """D3: demo.write_demo_note gate 返回 confirmation_required。

        验证 tool_gate_tool_name="demo.write_demo_note" 时，gate 正确返回
        confirmation_required disposition（因 confirmation="always"）。
        """
        import agent.tools  # noqa: F401
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action

        dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(dispatcher)
        mock_state = _make_mock_state()

        deps = LoopDependencies(
            state=mock_state,
            call_model=lambda s, ctx: None,
            dispatch_model_output=lambda resp: "demo response",
            runtime_loop_fields=lambda: {},
            safe_emit_runtime_event=lambda cb, ev: None,
            clear_checkpoint=lambda: None,
            tool_gate_tool_name="demo.write_demo_note",
        )

        _try_phase1_turn_end_runtime_action(
            state=mock_state,
            result_text="demo response",
            dispatcher=spy,
            dependencies=deps,
        )

        # 找出 TOOL_GATE action
        gate_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.TOOL_GATE
        ]
        assert len(gate_entries) >= 1

        gate_method, gate_request, gate_result = gate_entries[0]
        assert gate_method == "route_from_runtime_loop"
        gate_evidence = dict(gate_result.evidence)
        assert gate_evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E

        # gate 应是 confirmation_required（不是 allowed 也不是 blocked）
        disposition = gate_result.payload.get("gate_disposition")
        assert disposition == "confirmation_required", (
            f"demo.write_demo_note gate 应为 confirmation_required，"
            f"实际 {disposition!r}"
        )

        # 验证 TOOL_INVOKE 没有被触发
        invoke_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.TOOL_INVOKE
        ]
        assert len(invoke_entries) == 0, (
            "confirmation_required 时不应触发 TOOL_INVOKE"
        )
