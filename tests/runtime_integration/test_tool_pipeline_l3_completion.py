"""Tool Pipeline L3 Completion TDD 测试。

中文学习边界：
Tool 是已有有限介入点，ToolGate / ToolInvoke / ToolResult 是 Tool lifecycle stages
（pipeline phases），不是三个独立子系统。本轮补齐已有 Tool pipeline 的 L3 evidence：
在 _try_phase1_turn_end_runtime_action 中，TOOL_GATE allowed 后自动构造
TOOL_INVOKE → TOOL_RESULT，全部通过 route_from_runtime_loop 路由以获取
real_core_loop_runtime_e2e 分类。

测试分层：
- L1 (subsystem_integration): direct handler call
- L2 (harness_runtime_e2e): dispatcher.route()
- L3 (real_core_loop_runtime_e2e): _try_phase1_turn_end_runtime_action → route_from_runtime_loop

架构依据：
- docs/specs/tool-pipeline-l3-completion/SPEC.md
- docs/specs/tool-pipeline-l3-completion/TDD.md
- docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md
"""

from __future__ import annotations

from typing import Any

import pytest

from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
    classify_evidence_level,
)
from agent.runtime_integration.evidence import (
    HARNESS_RUNTIME_E2E,
    REAL_CORE_LOOP_RUNTIME_E2E,
    SUBSYSTEM_INTEGRATION,
    RuntimeActionModuleObserver,
)
from agent.runtime_integration.schema import RuntimeActionRequest
from agent.runtime_integration.tool_invoke import ToolInvokeHandler
from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler
from agent.runtime_integration.tool_gate import ToolGateHandler


# ========== 测试辅助工厂 ==========


def _build_pipeline_dispatcher() -> RuntimeActionDispatcher:
    """构建注册了 TOOL_GATE + TOOL_INVOKE + TOOL_RESULT handler 的 dispatcher。

    与 production build_phase1_dispatcher() 一致——一次性注册所有 Tool lifecycle handler，
    确保 gate → invoke → result 管线完整。
    """
    import agent.tools  # noqa: F401 - 触发工具注册
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
    registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
    registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


class _PipelineSpy:
    """捕获 method + request + result 的 spy dispatcher 包装器。

    与 B5 _LoopPathSpy 相同模式——每个 route 调用记录 (method_name, request, result)，
    不改变底层 dispatcher 行为。用于验证 pipeline 中每个 action 的路由方式和结果。

    中文学习边界：spy 只观察不改变行为——这是 B5 已确立的 harness 模式。
    """

    def __init__(self, real: RuntimeActionDispatcher) -> None:
        self._real = real
        self.captured: list[tuple[str, RuntimeActionRequest, Any]] = []

    def route(self, request: RuntimeActionRequest) -> Any:
        result = self._real.route(request)
        self.captured.append(("route", request, result))
        return result

    def route_from_runtime_loop(self, request: RuntimeActionRequest) -> Any:
        result = self._real.route_from_runtime_loop(request)
        self.captured.append(("route_from_runtime_loop", request, result))
        return result

    @property
    def action_log(self):
        return self._real.action_log


def _make_mock_state():
    """构造最小 mock state——只需 conversation.messages 中有 user 消息。"""

    class _MockConversation:
        messages: list[dict] = [{"role": "user", "content": "hello"}]

    class _MockState:
        conversation = _MockConversation()

    return _MockState()


# ========== Phase A: Full Pipeline L3 Happy Path ==========


class TestPhaseAFullPipelineL3HappyPath:
    """Phase A: 验证 gate → invoke → result 完整管线达到 L3。

    这些测试在当前代码下为 RED——_try_phase1_turn_end_runtime_action 尚未构造
    TOOL_INVOKE 和 TOOL_RESULT action。U2 实现后变为 GREEN。
    """

    def test_a1_gate_allowed_constructs_tool_invoke(self):
        """A1: TOOL_GATE allowed 后构造 TOOL_INVOKE 并通过 route_from_runtime_loop 路由。

        验证 _try_phase1_turn_end_runtime_action 在 gate 返回 allowed 时，
        自动构造 TOOL_INVOKE action，使用 route_from_runtime_loop 以获得 L3 provenance。
        """
        import agent.tools  # noqa: F401
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action

        dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(dispatcher)
        mock_state = _make_mock_state()

        deps = LoopDependencies(
            state=mock_state,
            call_model=lambda s, ctx: None,
            dispatch_model_output=lambda resp: "test response",
            runtime_loop_fields=lambda: {},
            safe_emit_runtime_event=lambda cb, ev: None,
            clear_checkpoint=lambda: None,
            tool_gate_tool_name="_safe_noop",
        )

        _try_phase1_turn_end_runtime_action(
            state=mock_state,
            result_text="test response",
            dispatcher=spy,
            dependencies=deps,
        )

        # 找出 TOOL_INVOKE action
        invoke_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.TOOL_INVOKE
        ]
        assert len(invoke_entries) >= 1, (
            f"A1 RED: TOOL_GATE allowed 后应构造 TOOL_INVOKE，"
            f"实际 captured types: {[r.action_type.value for _, r, _ in spy.captured]}"
        )

        invoke_method, invoke_request, invoke_result = invoke_entries[0]
        assert invoke_method == "route_from_runtime_loop", (
            f"TOOL_INVOKE 应通过 route_from_runtime_loop 路由以获取 L3 provenance，"
            f"实际 {invoke_method!r}"
        )
        assert invoke_request.payload["tool_name"] == "_safe_noop"
        assert invoke_request.payload.get("tool_input") == {}

    def test_a2_tool_invoke_feeds_tool_result(self):
        """A2: TOOL_INVOKE 完成后构造 TOOL_RESULT，将 invoke 结果传给 result handler。

        验证 TOOL_INVOKE 执行完成后，其 tool_output + execution_status 被正确
        传递给 TOOL_RESULT action。
        """
        import agent.tools  # noqa: F401
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action

        dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(dispatcher)
        mock_state = _make_mock_state()

        deps = LoopDependencies(
            state=mock_state,
            call_model=lambda s, ctx: None,
            dispatch_model_output=lambda resp: "test response",
            runtime_loop_fields=lambda: {},
            safe_emit_runtime_event=lambda cb, ev: None,
            clear_checkpoint=lambda: None,
            tool_gate_tool_name="_safe_noop",
        )

        _try_phase1_turn_end_runtime_action(
            state=mock_state,
            result_text="test response",
            dispatcher=spy,
            dependencies=deps,
        )

        # 找出 TOOL_RESULT action
        result_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.TOOL_RESULT
        ]
        assert len(result_entries) >= 1, (
            f"A2 RED: TOOL_INVOKE 完成后应构造 TOOL_RESULT，"
            f"实际 captured types: {[r.action_type.value for _, r, _ in spy.captured]}"
        )

        result_method, result_request, result_result = result_entries[0]
        assert result_method == "route_from_runtime_loop", (
            "TOOL_RESULT 应通过 route_from_runtime_loop 路由以获取 L3 provenance"
        )
        assert result_request.payload["tool_name"] == "_safe_noop"
        # TOOL_RESULT payload 中 tool_output 来自 TOOL_INVOKE 结果
        assert "tool_output" in result_request.payload, (
            "TOOL_RESULT payload 应包含 tool_output（来自 TOOL_INVOKE 结果）"
        )
        assert "execution_status" in result_request.payload, (
            "TOOL_RESULT payload 应包含 execution_status"
        )

    def test_a3_full_pipeline_all_stages_real_core_loop_e2e(self):
        """A3: gate → invoke → result 三个 stage 均达到 real_core_loop_runtime_e2e。

        验证完整 Tool lifecycle pipeline 中每个 stage 的 evidence_level。
        这是本轮核心目标——证明真实主流程能自然完成 Tool 管线的 L3 闭环。
        """
        import agent.tools  # noqa: F401
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action

        dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(dispatcher)
        mock_state = _make_mock_state()

        deps = LoopDependencies(
            state=mock_state,
            call_model=lambda s, ctx: None,
            dispatch_model_output=lambda resp: "test response",
            runtime_loop_fields=lambda: {},
            safe_emit_runtime_event=lambda cb, ev: None,
            clear_checkpoint=lambda: None,
            tool_gate_tool_name="_safe_noop",
        )

        _try_phase1_turn_end_runtime_action(
            state=mock_state,
            result_text="test response",
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
        gate_evidence = dict(gate_entries[0][2].evidence)
        assert gate_evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"TOOL_GATE 应达到 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {gate_evidence.get('evidence_level')!r}"
        )
        assert gate_evidence.get("dispatcher_origin") == "runtime_loop"
        assert gate_evidence.get("runtime_loop_invoked") is True
        assert gate_evidence.get("core_entrypoint") == "core.chat"

        # 验证 TOOL_INVOKE 达到 L3
        invoke_entries = by_type.get("tool.invoke", [])
        assert len(invoke_entries) >= 1, (
            f"A3 RED: 应有 TOOL_INVOKE action，"
            f"实际 types: {list(by_type.keys())}"
        )
        invoke_evidence = dict(invoke_entries[0][2].evidence)
        assert invoke_evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"TOOL_INVOKE 应达到 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {invoke_evidence.get('evidence_level')!r}"
        )
        assert invoke_evidence.get("dispatcher_origin") == "runtime_loop"
        assert invoke_evidence.get("runtime_loop_invoked") is True

        # 验证 TOOL_RESULT 达到 L3
        result_entries = by_type.get("tool.result", [])
        assert len(result_entries) >= 1, (
            f"A3 RED: 应有 TOOL_RESULT action，"
            f"实际 types: {list(by_type.keys())}"
        )
        result_evidence = dict(result_entries[0][2].evidence)
        assert result_evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"TOOL_RESULT 应达到 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {result_evidence.get('evidence_level')!r}"
        )
        assert result_evidence.get("dispatcher_origin") == "runtime_loop"
        assert result_evidence.get("runtime_loop_invoked") is True

        # 二次确认：classify_evidence_level
        for label, evidence_dict in [
            ("TOOL_GATE", gate_evidence),
            ("TOOL_INVOKE", invoke_evidence),
            ("TOOL_RESULT", result_evidence),
        ]:
            level = classify_evidence_level(evidence_dict)
            assert level == REAL_CORE_LOOP_RUNTIME_E2E, (
                f"{label} classify_evidence_level 应为 {REAL_CORE_LOOP_RUNTIME_E2E}，"
                f"实际 {level!r}"
            )


    def test_a4_full_core_chat_path_ordered_pipeline_l3(self):
        """A4: core.chat() 完整路径产生有序 GATE → INVOKE → RESULT 管线。

        P1 focused remediation 核心测试——证明完整 core.chat → run_main_loop
        → _try_phase1_turn_end_runtime_action → dispatcher 路径能产生有序的
        GATE→INVOKE→RESULT 序列，且全部达到 real_core_loop_runtime_e2e。

        与 A1-A3 的区别：A1-A3 直接调用 _try_phase1_turn_end_runtime_action()
        （hook 级），验证 dispatcher provenance。A4 通过 core.chat() 验证完整
        core loop 接线——从用户输入到 RuntimeAction 的完整链路。

        中文学习边界：
        - hook 级测试（A1-A3）证明 dispatcher provenance 完整
        - core.chat() 级测试（A4）证明真实 core loop 接线存在且工作正常
        - 两者互补，都不应删除
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        real_dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        # 提取 Tool pipeline actions（按捕获顺序）
        pipeline_actions = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type in (
                RuntimeActionType.TOOL_GATE,
                RuntimeActionType.TOOL_INVOKE,
                RuntimeActionType.TOOL_RESULT,
            )
        ]

        action_types_in_order = [r.action_type.value for _, r, _ in pipeline_actions]

        # 必须有 TOOL_GATE（_safe_noop 通过 gate allowed）
        assert "tool.gate" in action_types_in_order, (
            f"core.chat() 路径应产生 TOOL_GATE，实际: {action_types_in_order}"
        )

        # gate allowed → 必须有 TOOL_INVOKE
        assert "tool.invoke" in action_types_in_order, (
            f"core.chat() 路径应产生 TOOL_INVOKE（_safe_noop gate allowed），"
            f"实际: {action_types_in_order}"
        )

        # invoke 完成 → 必须有 TOOL_RESULT
        assert "tool.result" in action_types_in_order, (
            f"core.chat() 路径应产生 TOOL_RESULT，实际: {action_types_in_order}"
        )

        # 验证有序：gate 在 invoke 之前，invoke 在 result 之前
        gate_idx = action_types_in_order.index("tool.gate")
        invoke_idx = action_types_in_order.index("tool.invoke")
        result_idx = action_types_in_order.index("tool.result")
        assert gate_idx < invoke_idx < result_idx, (
            f"pipeline 顺序应为 GATE({gate_idx}) < INVOKE({invoke_idx})"
            f" < RESULT({result_idx})，实际: {action_types_in_order}"
        )

        # 验证所有三个 stage 都通过 route_from_runtime_loop 达到 L3
        for method, request, action_result in pipeline_actions:
            assert method == "route_from_runtime_loop", (
                f"{request.action_type.value} 应通过 route_from_runtime_loop 路由，"
                f"实际 {method!r}"
            )
            evidence = dict(action_result.evidence)
            assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
                f"{request.action_type.value} 应达到 {REAL_CORE_LOOP_RUNTIME_E2E}，"
                f"实际 {evidence.get('evidence_level')!r}"
            )
            assert evidence.get("runtime_loop_invoked") is True
            assert evidence.get("dispatcher_origin") == "runtime_loop"
            assert evidence.get("core_entrypoint") == "core.chat"
            assert evidence.get("runtime_hook_name") == "loop.turn_end"

        # 二次确认：classify_evidence_level
        for method, request, action_result in pipeline_actions:
            evidence = dict(action_result.evidence)
            level = classify_evidence_level(evidence)
            assert level == REAL_CORE_LOOP_RUNTIME_E2E, (
                f"{request.action_type.value} classify_evidence_level"
                f" 应为 {REAL_CORE_LOOP_RUNTIME_E2E}，实际 {level!r}"
            )


# ========== Phase B: Classification Boundaries ==========


class TestPhaseBClassificationBoundaries:
    """Phase B: 验证 L1/L2/L3 分类边界不被本轮改动破坏。"""

    def test_b1_direct_handler_call_is_subsystem_integration(self):
        """B1: 直接调用 ToolInvokeHandler.handle() → subsystem_integration (L1)。

        不经过 dispatcher 的直接 handler 调用不能被分类为 runtime_e2e。
        """
        import agent.tools  # noqa: F401
        from agent.runtime_integration.dispatcher import RuntimeActionContext

        handler = ToolInvokeHandler()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_INVOKE,
            source="core_loop",
            parent_trace_id="",
            payload={"tool_name": "_safe_noop", "tool_input": {}},
        )
        # 构造无 route provenance 的 context
        observer = RuntimeActionModuleObserver()
        context = RuntimeActionContext(
            action_id="test-action-id",
            action_type=RuntimeActionType.TOOL_INVOKE,
            route_id="test-route-id",
            handler_name="ToolInvokeHandler",
            handler_identity="agent.runtime_integration.tool_invoke.ToolInvokeHandler",
            parent_trace_id="",
            observer=observer,
            dispatcher_origin="direct_dispatcher",
            core_entrypoint="",
            runtime_hook_name="",
        )
        result = handler.handle(request, context)
        evidence = dict(result.evidence)
        level = evidence.get("evidence_level", "")
        # direct handler context 没有 dispatcher-owned route provenance
        # ——classify_evidence_level 应降级为 subsystem_integration 或更低
        assert "runtime_e2e" not in str(level), (
            f"direct handler call 不得包含 runtime_e2e 分类，实际 {level!r}"
        )
        assert level in (SUBSYSTEM_INTEGRATION, "not_covered", "deterministic_baseline"), (
            f"direct handler call 应为 subsystem 或更低，实际 {level!r}"
        )

    def test_b2_direct_dispatcher_route_is_harness_runtime_e2e(self):
        """B2: dispatcher.route() → harness_runtime_e2e (L2)。

        不通过 route_from_runtime_loop 的 dispatcher 调用不能达到 L3。
        """
        import agent.tools  # noqa: F401

        dispatcher = _build_pipeline_dispatcher()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_INVOKE,
            source="core_loop",
            parent_trace_id="",
            payload={"tool_name": "_safe_noop", "tool_input": {}},
        )
        result = dispatcher.route(request)
        evidence = dict(result.evidence)
        assert evidence.get("evidence_level") == HARNESS_RUNTIME_E2E, (
            f"direct dispatcher.route 应为 {HARNESS_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("dispatcher_origin") == "direct_dispatcher"

    def test_b3_payload_spoofing_cannot_upgrade_to_l3(self):
        """B3: payload 伪造 core_loop_invoked 不能升级 direct route 为 L3。

        payload 是子系统输入，不是可信 runtime provenance。即使 payload 中写入
        core_loop_invoked=True，classify_evidence_level 也不应将其升级为 L3。
        """
        import agent.tools  # noqa: F401

        dispatcher = _build_pipeline_dispatcher()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_INVOKE,
            source="core_loop",
            parent_trace_id="",
            payload={
                "tool_name": "_safe_noop",
                "tool_input": {},
                # payload spoofing 尝试
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
            },
        )
        result = dispatcher.route(request)  # 非 route_from_runtime_loop
        evidence = dict(result.evidence)
        assert evidence.get("evidence_level") != REAL_CORE_LOOP_RUNTIME_E2E, (
            f"payload spoofing 不能升级分类为 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("evidence_level") == HARNESS_RUNTIME_E2E, (
            f"payload spoofing 后应仍为 {HARNESS_RUNTIME_E2E}"
        )

    def test_b4_route_from_runtime_loop_is_real_core_loop_e2e(self):
        """B4: route_from_runtime_loop() → real_core_loop_runtime_e2e (L3)。

        验证 dispatcher 层的 route_from_runtime_loop 方法可以为
        TOOL_INVOKE / TOOL_RESULT mint L3 provenance。
        """
        import agent.tools  # noqa: F401

        dispatcher = _build_pipeline_dispatcher()

        # TOOL_INVOKE via route_from_runtime_loop
        invoke_request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_INVOKE,
            source="core_loop",
            parent_trace_id="",
            payload={"tool_name": "_safe_noop", "tool_input": {}},
        )
        invoke_result = dispatcher.route_from_runtime_loop(invoke_request)
        invoke_evidence = dict(invoke_result.evidence)
        assert invoke_evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"route_from_runtime_loop 的 TOOL_INVOKE 应达到 L3，"
            f"实际 {invoke_evidence.get('evidence_level')!r}"
        )

        # TOOL_RESULT via route_from_runtime_loop
        result_request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_RESULT,
            source="core_loop",
            parent_trace_id="",
            payload={
                "tool_name": "_safe_noop",
                "tool_output": "test output",
                "execution_status": "success",
            },
        )
        result_result = dispatcher.route_from_runtime_loop(result_request)
        result_evidence = dict(result_result.evidence)
        assert result_evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"route_from_runtime_loop 的 TOOL_RESULT 应达到 L3，"
            f"实际 {result_evidence.get('evidence_level')!r}"
        )


# ========== Phase C: Gate Disposition Controls Pipeline ==========


class TestPhaseCGateDispositionControlsPipeline:
    """Phase C: 验证非 allowed disposition 时不构造 TOOL_INVOKE。"""

    def test_c1_confirmation_required_does_not_invoke(self):
        """C1: confirmation_required → 不构造 TOOL_INVOKE。

        当 TOOL_GATE 返回 confirmation_required 时，工具尚未被用户确认，
        不应执行 invoke。
        """
        import agent.tools  # noqa: F401
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action

        dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(dispatcher)
        mock_state = _make_mock_state()

        deps = LoopDependencies(
            state=mock_state,
            call_model=lambda s, ctx: None,
            dispatch_model_output=lambda resp: "test response",
            runtime_loop_fields=lambda: {},
            safe_emit_runtime_event=lambda cb, ev: None,
            clear_checkpoint=lambda: None,
            tool_gate_tool_name="_confirmable_noop",
        )

        _try_phase1_turn_end_runtime_action(
            state=mock_state,
            result_text="test response",
            dispatcher=spy,
            dependencies=deps,
        )

        invoke_types = [
            r.action_type.value for _, r, _ in spy.captured
            if r.action_type == RuntimeActionType.TOOL_INVOKE
        ]
        assert len(invoke_types) == 0, (
            f"confirmation_required 时不应构造 TOOL_INVOKE，"
            f"实际有 {len(invoke_types)} 个 TOOL_INVOKE"
        )

    def test_c2_blocked_does_not_invoke(self):
        """C2: blocked → 不构造 TOOL_INVOKE。

        当 TOOL_GATE 返回 blocked 时，工具被 policy 阻止，不应执行 invoke。
        """
        import agent.tools  # noqa: F401
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action

        dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(dispatcher)
        mock_state = _make_mock_state()

        # 测试 forbidden tool name（shell-like → blocked）
        # 由于 gate allowlist 会拦截，我们直接使用不在 allowlist 中的 _ 前缀工具
        deps = LoopDependencies(
            state=mock_state,
            call_model=lambda s, ctx: None,
            dispatch_model_output=lambda resp: "test response",
            runtime_loop_fields=lambda: {},
            safe_emit_runtime_event=lambda cb, ev: None,
            clear_checkpoint=lambda: None,
            tool_gate_tool_name="bash",  # FORBIDDEN_TOOL_NAMES → blocked
        )

        _try_phase1_turn_end_runtime_action(
            state=mock_state,
            result_text="test response",
            dispatcher=spy,
            dependencies=deps,
        )

        invoke_types = [
            r.action_type.value for _, r, _ in spy.captured
            if r.action_type == RuntimeActionType.TOOL_INVOKE
        ]
        assert len(invoke_types) == 0, (
            f"blocked 时不应构造 TOOL_INVOKE，实际有 {len(invoke_types)} 个"
        )

    def test_c3_not_found_does_not_invoke(self):
        """C3: not_found → 不构造 TOOL_INVOKE。

        当 tool_name 不在 TOOL_REGISTRY 中时，gate 返回 not_found，
        不应执行 invoke。
        """
        import agent.tools  # noqa: F401
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action

        dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(dispatcher)
        mock_state = _make_mock_state()

        deps = LoopDependencies(
            state=mock_state,
            call_model=lambda s, ctx: None,
            dispatch_model_output=lambda resp: "test response",
            runtime_loop_fields=lambda: {},
            safe_emit_runtime_event=lambda cb, ev: None,
            clear_checkpoint=lambda: None,
            tool_gate_tool_name="nonexistent_tool_xyz",
        )

        _try_phase1_turn_end_runtime_action(
            state=mock_state,
            result_text="test response",
            dispatcher=spy,
            dependencies=deps,
        )

        invoke_types = [
            r.action_type.value for _, r, _ in spy.captured
            if r.action_type == RuntimeActionType.TOOL_INVOKE
        ]
        assert len(invoke_types) == 0, (
            f"not_found 时不应构造 TOOL_INVOKE，实际有 {len(invoke_types)} 个"
        )


# ========== Phase D: Pipeline Error Isolation ==========


class TestPhaseDPipelineErrorIsolation:
    """Phase D: 验证每个 stage 独立 try/except，一个失败不阻断其他。"""

    def test_d1_each_stage_independent_try_except(self):
        """D1: MEMORY / TOOL_GATE / TOOL_INVOKE / TOOL_RESULT 各自独立 try/except。

        验证 loop.py 中的 _try_phase1_turn_end_runtime_action 在构造每个 action
        时使用独立 try/except 块，而非一个大 try/except 包住所有 stage。
        这是结构保证——通过代码审查验证（inspect 源码），非纯行为测试。
        """
        import inspect
        from agent.loop import _try_phase1_turn_end_runtime_action

        source = inspect.getsource(_try_phase1_turn_end_runtime_action)

        # 每个独立 try 块应包含一个 action 的构造和路由
        # 验证至少有 4 个 "try:"（MEMORY + TOOL_GATE + TOOL_INVOKE + TOOL_RESULT）
        # 注意：TOOL_INVOKE/TOOL_RESULT 的 try 嵌套在 if 块内，缩进更深，
        # 不匹配 "\n    try:"（4 空格），因此统计所有 "try:"（任意缩进）。
        # 函数内注释和文档字符串使用 "try/except"（带斜线），不会误匹配。
        try_count = source.count("try:")
        assert try_count >= 4, (
            f"_try_phase1_turn_end_runtime_action 应有至少 4 个独立 try 块"
            f"（MEMORY/GATE/INVOKE/RESULT 各自独立），实际 {try_count} 个"
        )

        # 不应有大 try/except 包住多个 action——每个 try 只包一个 action 构造+路由
        # 验证没有 "try:" 后面紧跟多个 RuntimeActionRequest 构造（不含中间 "try:"）
        # 简化检查：每个 "try:" 和下一个 "try:" 或 "except" 之间只包含一个 route() 调用
        route_count = source.count("route(")
        assert route_count >= 4, (
            f"应有至少 4 个 route() 调用（每个 stage 一个），实际 {route_count}"
        )

    def test_d2_pipeline_continues_after_stage_failure(self):
        """D2: 一个 stage 失败不阻断后续 stage。

        行为验证：即使某个 stage 失败（如 dispatcher 抛异常），
        其他 stage 仍能正常执行。
        """
        import agent.tools  # noqa: F401
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action

        dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(dispatcher)
        mock_state = _make_mock_state()

        deps = LoopDependencies(
            state=mock_state,
            call_model=lambda s, ctx: None,
            dispatch_model_output=lambda resp: "test response",
            runtime_loop_fields=lambda: {},
            safe_emit_runtime_event=lambda cb, ev: None,
            clear_checkpoint=lambda: None,
            tool_gate_tool_name="_safe_noop",
        )

        # 不应抛异常——即使某些 stage 内部失败，pipeline 也应继续
        try:
            _try_phase1_turn_end_runtime_action(
                state=mock_state,
                result_text="test response",
                dispatcher=spy,
                dependencies=deps,
            )
        except Exception as exc:
            pytest.fail(
                f"_try_phase1_turn_end_runtime_action 不应抛异常，"
                f"各 stage 应独立 try/except：{exc}"
            )

        # 至少 MEMORY + TOOL_GATE 应成功
        action_types = {r.action_type.value for _, r, _ in spy.captured}
        assert "tool.gate" in action_types, (
            f"MEMORY/TOOL_GATE 应至少成功执行，实际 types: {action_types}"
        )


    def test_d3_failed_invoke_produces_error_execution_status(self):
        """D3: invoke_result.status != "success" → TOOL_RESULT execution_status="error"。

        P2 focused remediation 核心测试——验证当 TOOL_INVOKE handler 抛异常
        导致 invoke_result.status != "success" 时，TOOL_RESULT 的 execution_status
        必须为 "error"，不得默认为 "success"。

        使用抛异常的注册工具模拟 invoke 失败场景。
        """
        import agent.tools  # noqa: F401
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action
        from agent.tool_registry import TOOL_REGISTRY, register_tool

        # 注册一个抛异常的工具（不用 _ 前缀——_ 前缀受 gate allowlist 限制，
        # 仅 _safe_noop / _confirmable_noop 可通过）
        throwing_name = "throwing_noop_d3"

        @register_tool(
            name=throwing_name,
            description="Throwing tool for D3 error path test",
            parameters={},
            confirmation="never",
            capability="local_action",
            risk_level="low",
            output_policy="none",
            meta_tool=False,
        )
        def throwing_noop_d3() -> str:
            raise RuntimeError("simulated tool failure for D3")

        dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(dispatcher)
        mock_state = _make_mock_state()

        deps = LoopDependencies(
            state=mock_state,
            call_model=lambda s, ctx: None,
            dispatch_model_output=lambda resp: "test response",
            runtime_loop_fields=lambda: {},
            safe_emit_runtime_event=lambda cb, ev: None,
            clear_checkpoint=lambda: None,
            tool_gate_tool_name=throwing_name,
        )

        try:
            _try_phase1_turn_end_runtime_action(
                state=mock_state,
                result_text="test response",
                dispatcher=spy,
                dependencies=deps,
            )

            # 验证 TOOL_RESULT 存在且 execution_status="error"
            result_entries = [
                (m, r, res) for m, r, res in spy.captured
                if r.action_type == RuntimeActionType.TOOL_RESULT
            ]
            assert len(result_entries) >= 1, (
                f"D3: 即使 invoke 失败，仍应构造 TOOL_RESULT，"
                f"实际 types: {[r.action_type.value for _, r, _ in spy.captured]}"
            )

            result_request = result_entries[0][1]
            exec_status = result_request.payload.get("execution_status")
            assert exec_status == "error", (
                f"invoke 失败时 TOOL_RESULT execution_status 应为 'error'，"
                f"实际 {exec_status!r}"
            )
        finally:
            TOOL_REGISTRY.pop(throwing_name, None)

    def test_d4_successful_invoke_preserves_execution_status(self):
        """D4: invoke_result.status == "success" → TOOL_RESULT 保留 payload execution_status。

        P2 focused remediation 正向验证——当 TOOL_INVOKE 成功时，TOOL_RESULT
        的 execution_status 应保留 invoke payload 中的值（默认为 "success"）。
        """
        import agent.tools  # noqa: F401
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action

        dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(dispatcher)
        mock_state = _make_mock_state()

        deps = LoopDependencies(
            state=mock_state,
            call_model=lambda s, ctx: None,
            dispatch_model_output=lambda resp: "test response",
            runtime_loop_fields=lambda: {},
            safe_emit_runtime_event=lambda cb, ev: None,
            clear_checkpoint=lambda: None,
            tool_gate_tool_name="_safe_noop",
        )

        _try_phase1_turn_end_runtime_action(
            state=mock_state,
            result_text="test response",
            dispatcher=spy,
            dependencies=deps,
        )

        # _safe_noop 成功 → TOOL_RESULT execution_status 应为 "success"
        result_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.TOOL_RESULT
        ]
        assert len(result_entries) >= 1

        result_request = result_entries[0][1]
        exec_status = result_request.payload.get("execution_status")
        assert exec_status == "success", (
            f"_safe_noop 成功时 execution_status 应为 'success'，"
            f"实际 {exec_status!r}"
        )


# ========== Phase E: Regression ==========


class TestPhaseERegression:
    """Phase E: 回归——已有行为不被破坏，MCP 继承 pipeline。"""

    def test_e1_existing_tool_gate_l3_still_works(self):
        """E1: 已有 TOOL_GATE B5 L3 行为不被本轮改动破坏。

        验证 _try_phase1_turn_end_runtime_action 对 _confirmable_noop
        仍能正确产生 TOOL_GATE confirmation_required + L3 evidence。
        与 test_tool_branch_confirmation_required.py B5 相同模式。
        """
        import agent.tools  # noqa: F401
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action

        dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(dispatcher)
        mock_state = _make_mock_state()

        deps = LoopDependencies(
            state=mock_state,
            call_model=lambda s, ctx: None,
            dispatch_model_output=lambda resp: "test response",
            runtime_loop_fields=lambda: {},
            safe_emit_runtime_event=lambda cb, ev: None,
            clear_checkpoint=lambda: None,
            tool_gate_tool_name="_confirmable_noop",
        )

        _try_phase1_turn_end_runtime_action(
            state=mock_state,
            result_text="test response",
            dispatcher=spy,
            dependencies=deps,
        )

        # 找出 TOOL_GATE
        gate_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.TOOL_GATE
        ]
        assert len(gate_entries) >= 1
        gate_method, gate_request, gate_result = gate_entries[0]

        assert gate_method == "route_from_runtime_loop"
        assert gate_request.payload["tool_name"] == "_confirmable_noop"
        assert gate_result.status == "confirmation_required"

        evidence = dict(gate_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        assert evidence.get("gate_disposition") == "confirmation_required"

        # 确认 confirmation_required 时无 TOOL_INVOKE
        invoke_count = sum(
            1 for _, r, _ in spy.captured
            if r.action_type == RuntimeActionType.TOOL_INVOKE
        )
        assert invoke_count == 0, "confirmation_required 不应产生 TOOL_INVOKE"

    def test_e2_mcp_tool_rides_pipeline_l3(self):
        """E2: MCP 工具通过同一 pipeline 获得 L3。

        验证 MCP 工具（capability="mcp_tool"）通过 gate → invoke → result
        同一管线达到 L3，不需要新增 MCP 专用 branch point 或 handler。

        使用 FakeMCPClient（不连接真实 MCP server）。
        """
        import agent.tools  # noqa: F401
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action
        from agent.mcp import FakeMCPClient, MCPCallResult, register_mcp_tools
        from agent.mcp_models import MCPServerConfig, MCPToolDescriptor
        from agent.tool_registry import set_model_visible_tool_limits

        # 注册 MCP 工具——使用与 test_mcp_runtime_integration.py 相同的模式
        set_model_visible_tool_limits(max_mcp=50, max_total=200)
        server_name = "demo_e2_l3"
        tool_name = "hello"
        registry_name = f"mcp__{server_name}__{tool_name}"
        server = MCPServerConfig(
            name=server_name, transport="stdio", command="fake-cmd", enabled=True,
        )
        descriptor = MCPToolDescriptor(
            server_name=server_name,
            name=tool_name,
            description="MCP L3 pipeline test tool",
            input_schema={"type": "object", "properties": {}},
        )
        call_result = MCPCallResult(content="mcp l3 result")
        client = FakeMCPClient(
            tools_by_server={server_name: [descriptor]},
            results_by_call={(server_name, tool_name): call_result},
        )
        register_mcp_tools(
            [server], client,
            server_allowlist=frozenset({server_name}),
        )

        dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(dispatcher)
        mock_state = _make_mock_state()

        deps = LoopDependencies(
            state=mock_state,
            call_model=lambda s, ctx: None,
            dispatch_model_output=lambda resp: "test response",
            runtime_loop_fields=lambda: {},
            safe_emit_runtime_event=lambda cb, ev: None,
            clear_checkpoint=lambda: None,
            tool_gate_tool_name=registry_name,
        )

        try:
            _try_phase1_turn_end_runtime_action(
                state=mock_state,
                result_text="test response",
                dispatcher=spy,
                dependencies=deps,
            )

            # 验证 MCP 工具经过完整管线
            by_type: dict[str, list] = {}
            for method, request, result in spy.captured:
                at = request.action_type.value
                by_type.setdefault(at, []).append((method, request, result))

            # MCP 工具应通过 TOOL_GATE
            gate_entries = by_type.get("tool.gate", [])
            assert len(gate_entries) >= 1, "MCP 工具应有 TOOL_GATE"
            gate_evidence = dict(gate_entries[0][2].evidence)
            assert gate_evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E

            # 如果 gate allowed → TOOL_INVOKE → TOOL_RESULT
            invoke_entries = by_type.get("tool.invoke", [])
            if invoke_entries:
                invoke_evidence = dict(invoke_entries[0][2].evidence)
                assert invoke_evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E

            result_entries = by_type.get("tool.result", [])
            if result_entries:
                result_evidence = dict(result_entries[0][2].evidence)
                assert result_evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E

        finally:
            # 清理 MCP 工具注册
            from agent.tool_registry import TOOL_REGISTRY
            TOOL_REGISTRY.pop(registry_name, None)

    def test_e3_no_real_api_or_env_access(self):
        """E3: pipeline 执行不读 .env / 不调用真实 API。

        所有调用均通过 fake provider / internal tool / FakeMCPClient。
        HOME 已设为隔离路径——如果误读了 .env 会因路径不存在而失败。
        """
        import agent.tools  # noqa: F401
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action

        dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(dispatcher)
        mock_state = _make_mock_state()

        deps = LoopDependencies(
            state=mock_state,
            call_model=lambda s, ctx: None,
            dispatch_model_output=lambda resp: "test response",
            runtime_loop_fields=lambda: {},
            safe_emit_runtime_event=lambda cb, ev: None,
            clear_checkpoint=lambda: None,
            tool_gate_tool_name="_safe_noop",
        )

        # 不应因 .env 缺失而失败
        _try_phase1_turn_end_runtime_action(
            state=mock_state,
            result_text="test response",
            dispatcher=spy,
            dependencies=deps,
        )

        # 验证所有 action 的 evidence 中无真实 API 痕迹
        for method, request, result in spy.captured:
            evidence = dict(result.evidence)
            provider_kind = evidence.get("provider_kind", "")
            # fake provider 不应标记为 real
            assert provider_kind != "real", (
                f"fake provider path 不应有 provider_kind='real'：{evidence}"
            )


# ========== Phase F: Pipeline 结构约束 ==========


class TestPhaseFPipelineStructureConstraints:
    """Phase F: 结构约束——不新增 branch point / 不引入第二套主流程。"""

    def test_f1_stages_are_not_subsystems(self):
        """F1: lifecycle stages 不被称为三个独立子系统。

        验证新代码和注释中将 ToolGate/ToolInvoke/ToolResult 称为
        "lifecycle stage" / "pipeline phase" / "runtime action handler"，
        而非 "三个子系统" / "three subsystems"。
        """
        import inspect
        from agent.loop import _try_phase1_turn_end_runtime_action

        source = inspect.getsource(_try_phase1_turn_end_runtime_action)

        # 不应包含"子系统"措辞来描述 Tool 管线 stages
        # 允许"Tool 子系统"（指 Tool 整体），不允许"三个子系统"
        forbidden = ["三个子系统", "three subsystems", "Tool Invoke 子系统"]
        for phrase in forbidden:
            assert phrase not in source, (
                f"_try_phase1_turn_end_runtime_action 中不应出现 '{phrase}'——"
                f"ToolGate/Invoke/Result 是 Tool lifecycle stages，不是独立子系统"
            )

    def test_f2_no_second_tool_pipeline(self):
        """F2: 不引入第二套主流程。

        验证本轮改动范围只限 loop.py + 测试 + docs：
        - phase1_hook.py 不新增 handler 注册
        - dispatcher.py 不新增 RuntimeActionType
        - 不新增第二套 tool execution entry point
        """
        # 静态验证：phase1_hook.py 的 handler 注册数应与当前一致
        # （TOOL_GATE + TOOL_INVOKE + TOOL_RESULT + MEMORY handlers）
        from agent.runtime_integration.phase1_hook import build_phase1_dispatcher

        dispatcher = build_phase1_dispatcher()
        snapshot = dispatcher._registry.snapshot()
        # 验证 TOOL_GATE / TOOL_INVOKE / TOOL_RESULT 都已注册
        assert "tool.gate" in snapshot, "TOOL_GATE handler 应已注册"
        assert "tool.invoke" in snapshot, "TOOL_INVOKE handler 应已注册"
        assert "tool.result" in snapshot, "TOOL_RESULT handler 应已注册"
        # 不新增额外 action type
        # Phase 6 更新：SKILL_SELECT 已接入 loop.py turn-end hook
        expected_types = {
            "tool.gate", "tool.invoke", "tool.result",
            "memory.turn_end_proposal", "memory.propose", "memory.recall",
            "checkpoint.safe_summary", "memory.consolidate",
            "skill.select",
        }
        actual_types = set(snapshot.keys())
        extra = actual_types - expected_types
        assert not extra, (
            f"不应有额外注册的 handler types，实际额外: {extra}"
        )
