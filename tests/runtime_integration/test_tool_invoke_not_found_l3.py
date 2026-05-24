"""Tool Invoke not_found L3 TDD 测试。

not_found 是 TOOL_INVOKE 的防御性 branch behavior——即使 TOOL_GATE 返回
"allowed"，TOOL_INVOKE handler 仍然二次检查工具是否在 TOOL_REGISTRY 中。

测试通过 spy 拦截 gate→invoke pipeline：TOOL_GATE 返回 allowed 后立即从
TOOL_REGISTRY 移除工具，触发 TOOL_INVOKE not_found。

归属已有 TOOL_INVOKE branch point，不新增 Anchor、不新增 branch point。

架构依据：
- docs/specs/tool-invoke-not-found-l3/SPEC.md
- docs/specs/tool-invoke-not-found-l3/TDD.md
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

_DUMMY_TOOL_NAME = "notfound_dummy_tool"


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


class _NotfoundPipelineSpy:
    """拦截 gate→invoke pipeline。

    TOOL_GATE 返回 allowed 后、TOOL_INVOKE 触发前从 TOOL_REGISTRY 移除
    目标工具，模拟 gate→invoke 间竞态，触发 TOOL_INVOKE not_found。
    """

    def __init__(self, real: RuntimeActionDispatcher, tool_name: str) -> None:
        self._real = real
        self._tool_name = tool_name
        self._gate_result: Any = None
        self._invoke_result: Any = None
        self._result_feedback: Any = None
        self.captured: list[tuple[str, RuntimeActionRequest, Any]] = []

    def route(self, request: RuntimeActionRequest) -> Any:
        result = self._real.route(request)
        self.captured.append(("route", request, result))
        return result

    def route_from_runtime_loop(self, request: RuntimeActionRequest) -> Any:
        from agent.tool_registry import TOOL_REGISTRY

        result = self._real.route_from_runtime_loop(request)
        self.captured.append(("route_from_runtime_loop", request, result))

        if request.action_type == RuntimeActionType.TOOL_GATE:
            self._gate_result = result
            gate_payload = dict(getattr(result, "payload", {}) or {})
            if gate_payload.get("gate_disposition") == "allowed":
                # 移除工具以触发 TOOL_INVOKE not_found
                TOOL_REGISTRY.pop(self._tool_name, None)

        if request.action_type == RuntimeActionType.TOOL_INVOKE:
            self._invoke_result = result

        if request.action_type == RuntimeActionType.TOOL_RESULT:
            self._result_feedback = result

        return result

    @property
    def action_log(self):
        return self._real.action_log


def _register_dummy_tool():
    """注册 dummy tool（confirmation="never" → TOOL_GATE allowed）。"""
    from agent.tool_registry import register_tool

    @register_tool(
        name=_DUMMY_TOOL_NAME,
        description="dummy tool for not_found L3 test",
        parameters={},
        confirmation="never",
        capability="local_action",
        risk_level="low",
    )
    def _dummy_func():
        return "dummy output"


# ===== T1: core.chat() TOOL_INVOKE not_found L3 =====


class TestCoreChatToolInvokeNotfoundL3:
    def test_t1_core_chat_tool_invoke_not_found_l3(self):
        """T1: TOOL_GATE allowed → spy 移除工具 → TOOL_INVOKE not_found → L3 evidence。"""
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        _register_dummy_tool()

        real_dispatcher = _build_pipeline_dispatcher()
        spy = _NotfoundPipelineSpy(real_dispatcher, _DUMMY_TOOL_NAME)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
            tool_gate_tool_name=_DUMMY_TOOL_NAME,
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
            f"dummy tool 应被 gate 放行 (confirmation='never')，"
            f"实际 {gate_payload.get('gate_disposition')!r}"
        )

        # TOOL_INVOKE 必须触发并返回 not_found
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
            f"TOOL_INVOKE not_found 应达到 L3，实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("runtime_loop_invoked") is True

        # TOOL_INVOKE payload: disposition="not_found"
        invoke_payload = dict(invoke_result.payload)
        assert invoke_payload.get("disposition") == "not_found", (
            f"not_found path disposition 应为 'not_found'，"
            f"实际 {invoke_payload.get('disposition')!r}"
        )
        assert invoke_payload.get("tool_invoked") is False
        assert invoke_payload.get("dangerous_tool_function_invoked") is False
        assert invoke_payload.get("tool_output") is None


# ===== T2: TOOL_RESULT 在 not_found 后仍触发 =====


class TestToolResultAfterNotfound:
    def test_t2_tool_result_triggers_after_not_found(self):
        """T2: TOOL_INVOKE not_found 后 TOOL_RESULT 仍触发——不中断 pipeline。"""
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        _register_dummy_tool()

        real_dispatcher = _build_pipeline_dispatcher()
        spy = _NotfoundPipelineSpy(real_dispatcher, _DUMMY_TOOL_NAME)

        chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
            tool_gate_tool_name=_DUMMY_TOOL_NAME,
        )

        pipeline_actions = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type in (
                RuntimeActionType.TOOL_GATE,
                RuntimeActionType.TOOL_INVOKE,
                RuntimeActionType.TOOL_RESULT,
            )
        ]
        action_types = [r.action_type.value for _, r, _ in pipeline_actions]

        assert "tool.result" in action_types, (
            f"TOOL_RESULT 应在 TOOL_INVOKE not_found 后触发，"
            f"实际: {action_types}"
        )
        result_entries = [
            (m, r, res) for m, r, res in pipeline_actions
            if r.action_type == RuntimeActionType.TOOL_RESULT
        ]
        assert len(result_entries) == 1
        _, _, result_fb = result_entries[0]
        assert result_fb.status == "success"


# ===== T3: L2 direct dispatcher baseline =====


class TestDirectDispatcherNotfoundL2:
    def test_t3_direct_dispatcher_route_tool_invoke_not_found_is_l2(self):
        """T3: 直接 dispatcher.route() TOOL_INVOKE not_found → L2。

        已有 test_b3_tool_not_found 覆盖此路径，这里确保 spy 不干扰
        正常 L2 断言。
        """
        import agent.tools  # noqa: F401
        _register_dummy_tool()

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
                "tool_name": "nonexistent_tool_xyz",
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

        invoke_payload = dict(result.payload)
        assert invoke_payload.get("disposition") == "not_found"
        assert invoke_payload.get("tool_invoked") is False


# ===== T4: no real API / .env =====


class TestNoRealAPIOrEnv:
    def test_t4_no_real_api_or_env_access(self):
        """T4: not_found pipeline 不读 .env、不调用真实 API。"""
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        _register_dummy_tool()

        real_dispatcher = _build_pipeline_dispatcher()
        spy = _NotfoundPipelineSpy(real_dispatcher, _DUMMY_TOOL_NAME)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
            tool_gate_tool_name=_DUMMY_TOOL_NAME,
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
        assert invoke_payload.get("disposition") == "not_found"
