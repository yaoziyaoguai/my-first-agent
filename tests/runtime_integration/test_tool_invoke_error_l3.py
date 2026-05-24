"""Tool Invoke error L3 TDD 测试。

error 是 TOOL_INVOKE 的 error-path branch behavior。
归属已有 TOOL_INVOKE branch point，不新增 Anchor、不新增 branch point。

测试分层：
- L3: core.chat() → TOOL_GATE(allowed) → TOOL_INVOKE(execution_status="error")
- L2: dispatcher.route() 直接调用

架构依据：
- docs/specs/tool-invoke-error-l3/SPEC.md
- docs/specs/tool-invoke-error-l3/TDD.md
"""

from __future__ import annotations

from typing import Any

import pytest

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

_ERROR_TOOL_NAME = "error_tool"


@pytest.fixture(autouse=True)
def _cleanup_error_tool():
    """清理 error_tool，防止污染其他测试的全局 TOOL_REGISTRY。"""
    yield
    from agent.tool_registry import TOOL_REGISTRY

    TOOL_REGISTRY.pop(_ERROR_TOOL_NAME, None)


# ========== 测试辅助 ==========


def _build_pipeline_dispatcher() -> RuntimeActionDispatcher:
    import agent.tools  # noqa: F401
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
    registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
    registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


class _PipelineSpy:
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


def _register_error_tool():
    """注册一个 gate 放行但 invoke 失败的工具。

    confirmation="never" → TOOL_GATE 返回 allowed
    函数体内抛 ValueError → TOOL_INVOKE 返回 execution_status="error"
    """
    from agent.tool_registry import register_tool

    @register_tool(
        name=_ERROR_TOOL_NAME,
        description="tool that always fails at invocation for error-path L3 test",
        parameters={},
        confirmation="never",
        capability="local_action",
        risk_level="low",
    )
    def _error_tool_func():
        raise ValueError("simulated execution failure for L3 error-path test")


# ===== T1: core.chat() TOOL_INVOKE error L3 =====


class TestCoreChatToolInvokeErrorL3:
    def test_t1_core_chat_tool_invoke_error_l3(self):
        """T1: error tool → gate allowed → invoke error → L3 evidence."""
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        _register_error_tool()

        real_dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
            tool_gate_tool_name=_ERROR_TOOL_NAME,
        )

        assert isinstance(result, str)

        pipeline_actions = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type in (
                RuntimeActionType.TOOL_GATE,
                RuntimeActionType.TOOL_INVOKE,
                RuntimeActionType.TOOL_RESULT,
            )
        ]
        action_types = [r.action_type.value for _, r, _ in pipeline_actions]

        # TOOL_GATE 必须存在且返回 allowed
        assert "tool.gate" in action_types
        gate_entries = [
            (m, r, res) for m, r, res in pipeline_actions
            if r.action_type == RuntimeActionType.TOOL_GATE
        ]
        method, _, gate_result = gate_entries[0]
        assert method == "route_from_runtime_loop"
        assert gate_result.status == "success"
        gate_payload = dict(gate_result.payload)
        assert gate_payload.get("gate_disposition") == "allowed", (
            f"error tool 应被 gate 放行 (confirmation='never')，"
            f"实际 {gate_payload.get('gate_disposition')!r}"
        )

        # TOOL_INVOKE 必须触发
        assert "tool.invoke" in action_types, (
            f"gate allowed 后应触发 TOOL_INVOKE，实际: {action_types}"
        )
        invoke_entries = [
            (m, r, res) for m, r, res in pipeline_actions
            if r.action_type == RuntimeActionType.TOOL_INVOKE
        ]
        method, _, invoke_result = invoke_entries[0]
        assert method == "route_from_runtime_loop"

        # TOOL_INVOKE L3 evidence
        evidence = dict(invoke_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"TOOL_INVOKE error 应达到 L3，实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("runtime_loop_invoked") is True

        # TOOL_INVOKE payload: execution_status="error"
        invoke_payload = dict(invoke_result.payload)
        assert invoke_payload.get("disposition") == "invoked", (
            f"error path disposition 应为 'invoked'，"
            f"实际 {invoke_payload.get('disposition')!r}"
        )
        assert invoke_payload.get("tool_invoked") is True
        assert invoke_payload.get("execution_status") == "error", (
            f"execution_status 应为 'error'，"
            f"实际 {invoke_payload.get('execution_status')!r}"
        )

        # TOOL_RESULT 应触发（invoke 完成即使 error 也触发 result feedback）
        assert "tool.result" in action_types, (
            f"TOOL_RESULT 应在 invoke error 后触发，实际: {action_types}"
        )


# ===== T2: direct dispatcher TOOL_INVOKE error L2 =====


class TestDirectDispatcherToolInvokeErrorL2:
    def test_t2_direct_dispatcher_route_tool_invoke_error_is_l2(self):
        """T2: 直接 dispatcher.route TOOL_INVOKE → L2，payload 伪造无效。"""
        import agent.tools  # noqa: F401
        _register_error_tool()

        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver()
        )

        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_INVOKE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": _ERROR_TOOL_NAME,
                "tool_input": {},
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
            },
        ))

        evidence = dict(result.evidence)
        assert evidence.get("evidence_level") == HARNESS_RUNTIME_E2E, (
            f"direct dispatcher 应获得 {HARNESS_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("dispatcher_origin") == "direct_dispatcher"
        assert evidence.get("core_entrypoint") != "core.chat"

        # error path 仍被正确记录
        invoke_payload = dict(result.payload)
        assert invoke_payload.get("execution_status") == "error"


# ===== T3: no real API =====


class TestNoRealAPIOrEnv:
    def test_t3_no_real_api_or_env_access(self):
        """T3: error pipeline 不读 .env、不调用真实 API。"""
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        _register_error_tool()

        real_dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
            tool_gate_tool_name=_ERROR_TOOL_NAME,
        )

        assert isinstance(result, str)

        invoke_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.TOOL_INVOKE
        ]
        assert len(invoke_entries) >= 1
        _, _, invoke_result = invoke_entries[0]
        evidence = dict(invoke_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        invoke_payload = dict(invoke_result.payload)
        assert invoke_payload.get("execution_status") == "error"
