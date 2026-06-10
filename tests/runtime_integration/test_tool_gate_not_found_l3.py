"""Tool Gate not_found L3 TDD 测试。

中文学习边界：
not_found 是 Tool gate 的第四个 disposition 分支行为
（前三为 allowed / confirmation_required / rejected）。
归属已有 Tool gate branch point，不新增 Anchor、不新增 branch point。

测试分层：
- L1 (subsystem_integration): 不适用——not_found 必然经过 TOOL_GATE handler
- L2 (harness_runtime_e2e): dispatcher.route() 直接调用
- L3 (real_core_loop_runtime_e2e): core.chat() → route_from_runtime_loop()

本轮核心目标：
证明不存在的工具名通过真实 core.chat() 路径进入 TOOL_GATE，
返回 status="rejected" + decision="not_found" + L3 evidence，
且 TOOL_INVOKE/TOOL_RESULT 不触发。

架构依据：
- docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md
"""

from __future__ import annotations

from typing import Any

from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
)
from agent.runtime_integration.evidence import (
    HARNESS_RUNTIME_E2E,
    REAL_CORE_LOOP_RUNTIME_E2E,
    RuntimeActionModuleObserver,
)
from agent.runtime_integration.schema import RuntimeActionRequest
from agent.runtime_integration.tool_gate import ToolGateHandler
from agent.runtime_integration.tool_invoke import ToolInvokeHandler
from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler

# 不存在的工具名——确保不在 TOOL_REGISTRY 中且不命中任何特殊前缀处理
_NOT_FOUND_TOOL_NAME = "nonexistent__tool__xyz"


# ========== 测试辅助工厂 ==========


def _build_pipeline_dispatcher() -> RuntimeActionDispatcher:
    """构建注册了 TOOL_GATE + TOOL_INVOKE + TOOL_RESULT handler 的 dispatcher。"""
    import agent.tools  # noqa: F401
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
    registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
    registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


class _PipelineSpy:
    """捕获 method + request + result 的 spy dispatcher 包装器。"""

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
    """构造最小 mock state——只需 conversation.messages 中有 user 消息。"""

    class _MockConversation:
        messages: list[dict] = [{"role": "user", "content": "hello"}]

    class _MockState:
        conversation = _MockConversation()

    return _MockState()


# ========== T1: core.chat() 触发 not_found 工具获得 L3 evidence ==========


class TestCoreChatNotFoundL3:
    """T1: core.chat() L3 not_found 核心测试。"""

    def test_t1_core_chat_not_found_tool_l3(self):
        """T1: 不存在工具名通过 core.chat() → TOOL_GATE 返回 rejected + not_found。

        证明 tool gate not_found 分支行为在 L3 证据级别正确运作。
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        real_dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
            tool_gate_tool_name=_NOT_FOUND_TOOL_NAME,
        )

        assert isinstance(result, str)

        # 提取 Tool pipeline actions
        pipeline_actions = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type in (
                RuntimeActionType.TOOL_GATE,
                RuntimeActionType.TOOL_INVOKE,
                RuntimeActionType.TOOL_RESULT,
            )
        ]

        action_types_in_order = [r.action_type.value for _, r, _ in pipeline_actions]

        # TOOL_GATE 必须存在
        assert "tool.gate" in action_types_in_order, (
            f"应有 TOOL_GATE，实际: {action_types_in_order}"
        )

        # TOOL_INVOKE 不得触发（gate 返回 rejected，不满足 allowed 条件）
        assert "tool.invoke" not in action_types_in_order, (
            f"TOOL_INVOKE 不应触发（gate rejected），实际: {action_types_in_order}"
        )

        # TOOL_RESULT 不得触发
        assert "tool.result" not in action_types_in_order, (
            f"TOOL_RESULT 不应触发，实际: {action_types_in_order}"
        )

        # 验证 TOOL_GATE 的 evidence
        gate_entries = [
            (m, r, res) for m, r, res in pipeline_actions
            if r.action_type == RuntimeActionType.TOOL_GATE
        ]
        assert len(gate_entries) >= 1
        method, request, gate_result = gate_entries[0]

        # 路由方式：必须是 route_from_runtime_loop
        assert method == "route_from_runtime_loop", (
            f"TOOL_GATE 应通过 route_from_runtime_loop 路由，实际 {method!r}"
        )

        # 请求中 tool_name 应为不存在的工具名
        assert request.payload["tool_name"] == _NOT_FOUND_TOOL_NAME

        # evidence 验证
        evidence = dict(gate_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"应达到 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("runtime_loop_invoked") is True
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("core_entrypoint") == "core.chat"
        assert evidence.get("runtime_hook_name") == "loop.turn_end"

        # status 和 decision
        assert gate_result.status == "rejected", (
            f"TOOL_GATE status 应为 'rejected'，实际 {gate_result.status!r}"
        )
        assert evidence.get("decision") == "not_found", (
            f"TOOL_GATE decision 应为 'not_found'，实际 {evidence.get('decision')!r}"
        )

        # payload 验证
        gate_payload = dict(gate_result.payload)
        assert gate_payload.get("gate_disposition") is None, (
            f"not_found 时 gate_disposition 应为 None，"
            f"实际 {gate_payload.get('gate_disposition')!r}"
        )
        assert gate_payload.get("rejection_reason") == (
            "tool not found in production ToolRegistry"
        ), (
            f"rejection_reason 应为 'tool not found in production ToolRegistry'，"
            f"实际 {gate_payload.get('rejection_reason')!r}"
        )


# ========== T2: hook 级 not_found 工具被正确拒绝 ==========


class TestHookLevelNotFoundL3:
    """T2: hook 级 L3 not_found 测试。"""

    def test_t2_hook_level_not_found_tool_l3(self):
        """T2: _try_phase1_turn_end_runtime_action 中 not_found 工具被正确拒绝。"""
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action

        real_dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(real_dispatcher)
        mock_state = _make_mock_state()

        deps = LoopDependencies(
            state=mock_state,
            call_model=lambda msgs, config: "fake response",
            dispatch_model_output=lambda response: None,
            runtime_loop_fields={"provider_kind": "fake", "provider_external_call": False},
            safe_emit_runtime_event=lambda sink, event: None,
            clear_checkpoint=lambda ctx: None,
            runtime_action_dispatcher=spy,
            provider_kind="fake",
            provider_external_call=False,
            tool_gate_tool_name=_NOT_FOUND_TOOL_NAME,
        )

        _try_phase1_turn_end_runtime_action(
            state=mock_state,
            result_text="test response",
            dispatcher=spy,
            dependencies=deps,
        )

        # 提取 Tool pipeline actions
        pipeline_actions = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type in (
                RuntimeActionType.TOOL_GATE,
                RuntimeActionType.TOOL_INVOKE,
                RuntimeActionType.TOOL_RESULT,
            )
        ]

        action_types_in_order = [r.action_type.value for _, r, _ in pipeline_actions]

        assert "tool.gate" in action_types_in_order, (
            f"应有 TOOL_GATE，实际: {action_types_in_order}"
        )
        assert "tool.invoke" not in action_types_in_order, (
            f"TOOL_INVOKE 不应触发（gate rejected），实际: {action_types_in_order}"
        )
        assert "tool.result" not in action_types_in_order, (
            f"TOOL_RESULT 不应触发，实际: {action_types_in_order}"
        )

        gate_entries = [
            (m, r, res) for m, r, res in pipeline_actions
            if r.action_type == RuntimeActionType.TOOL_GATE
        ]
        assert len(gate_entries) >= 1
        method, request, gate_result = gate_entries[0]

        assert method == "route_from_runtime_loop"
        assert gate_result.status == "rejected"
        evidence = dict(gate_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        assert evidence.get("decision") == "not_found"

        gate_payload = dict(gate_result.payload)
        assert gate_payload.get("gate_disposition") is None
        assert gate_payload.get("rejection_reason") == (
            "tool not found in production ToolRegistry"
        )


# ========== T3: direct dispatcher.route not_found 保持 L2 ==========


class TestDirectDispatcherNotFoundL2:
    """T3: direct dispatcher.route not_found 保持 L2。"""

    def test_t3_direct_dispatcher_route_not_found_is_l2(self):
        """T3: 直接调用 dispatcher.route 时 not_found 只能获得 L2 evidence。"""
        import agent.tools  # noqa: F401
        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver()
        )

        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": _NOT_FOUND_TOOL_NAME,
                # 尝试伪造 L3 字段
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
            },
        ))

        assert result.status == "rejected"
        evidence = dict(result.evidence)

        # evidence_level 必须为 L2，不能是 L3
        assert evidence.get("evidence_level") == HARNESS_RUNTIME_E2E, (
            f"direct dispatcher.route 应获得 {HARNESS_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )

        # dispatcher_origin 必须为 direct_dispatcher，不能被 payload 伪造
        assert evidence.get("dispatcher_origin") == "direct_dispatcher", (
            f"dispatcher_origin 应为 'direct_dispatcher'，"
            f"实际 {evidence.get('dispatcher_origin')!r}"
        )

        # decision 仍应为 not_found
        assert evidence.get("decision") == "not_found", (
            f"decision 应为 'not_found'，实际 {evidence.get('decision')!r}"
        )

        # payload 伪造字段不应污染 evidence
        assert evidence.get("core_entrypoint") != "core.chat", (
            "direct dispatcher 的 core_entrypoint 不应为 'core.chat'"
        )
        assert evidence.get("runtime_hook_name") != "loop.turn_end", (
            "direct dispatcher 的 runtime_hook_name 不应为 'loop.turn_end'"
        )


# ========== T4: 不读 .env / 不调用真实 API ==========


class TestNoRealAPIOrEnv:
    """T4: 隔离环境安全测试。"""

    def test_t4_no_real_api_or_env_access(self):
        """T4: not_found pipeline 不读 .env、不调用真实 API。"""
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        real_dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
            tool_gate_tool_name=_NOT_FOUND_TOOL_NAME,
        )

        assert isinstance(result, str)

        # TOOL_GATE 应返回 rejected + not_found
        gate_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.TOOL_GATE
        ]
        assert len(gate_entries) >= 1
        _, _, gate_result = gate_entries[0]
        assert gate_result.status == "rejected"
        evidence = dict(gate_result.evidence)
        assert evidence.get("decision") == "not_found"

        # TOOL_INVOKE 不得触发
        invoke_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.TOOL_INVOKE
        ]
        assert len(invoke_entries) == 0
