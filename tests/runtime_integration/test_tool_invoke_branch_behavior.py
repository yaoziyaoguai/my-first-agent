"""Tool invoke branch behavior TDD 测试。

中文学习边界：
Tool invoke 归属 Contract Section 2 "tool execution / confirmation handling" 分支点。
它不是新 Anchor、不是新 capability milestone、不是新 runtime flow。
tool.invoke = 接收 tool_name + tool_input → 查找 TOOL_REGISTRY → 执行工具函数 →
返回 tool_output + evidence。

测试分层：
- L1 (subsystem_integration): handler 直接调用
- L2 (harness_runtime_e2e): dispatcher.route()
- L3 (real_core_loop_runtime_e2e): route_from_runtime_loop() — verified in test_tool_pipeline_l3_completion.py

架构依据：
- docs/specs/tool-invoke-branch-behavior/SPEC.md
- docs/specs/tool-invoke-branch-behavior/TDD.md
- docs/specs/tool-invoke-branch-behavior/IMPLEMENTATION_PLAN.md
- docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md
"""

from __future__ import annotations

from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
)
from agent.runtime_integration.evidence import (
    HARNESS_RUNTIME_E2E,
    RuntimeActionModuleObserver,
)
from agent.runtime_integration.schema import RuntimeActionRequest
from agent.runtime_integration.tool_invoke import ToolInvokeHandler


# ========== 测试辅助工厂 ==========


def _build_dispatcher() -> RuntimeActionDispatcher:
    """构建注册了 TOOL_INVOKE handler 的 dispatcher。"""
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.TOOL_INVOKE,
        ToolInvokeHandler(),
    )
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


def _dispatch_tool_invoke(
    dispatcher: RuntimeActionDispatcher,
    **payload_overrides,
):
    """便捷 helper：dispatch TOOL_INVOKE 并返回 result。"""
    payload = {
        "tool_name": "_safe_noop",
        "tool_input": {},
        **payload_overrides,
    }
    return dispatcher.route(
        RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_INVOKE,
            source="test_tool_invoke",
            parent_trace_id="trace:tool-invoke-test",
            payload=payload,
        )
    )


# ========== Phase A: Happy Path — 工具成功调用 ==========


class TestInvokeHappyPath:
    """Phase A: 工具通过 handler 被实际调用并返回结果。"""

    def test_a1_allowed_tool_invoked(self):
        """A1: allowed tool 被成功 invoke，返回 tool_output。"""
        import agent.tools  # noqa: F401 - ensure tools registered
        dispatcher = _build_dispatcher()

        result = _dispatch_tool_invoke(
            dispatcher,
            tool_name="_safe_noop",
            tool_input={},
        )

        assert result.status == "success"
        payload = dict(result.payload)
        assert payload["disposition"] == "invoked"
        assert payload["tool_invoked"] is True
        assert payload["tool_output"] == "noop: ok"
        assert payload["execution_status"] == "success"
        evidence = dict(result.evidence)
        assert evidence["tool_name"] == "_safe_noop"

    def test_a2_tool_output_matches_actual_return(self):
        """A2: tool_output 内容与工具实际返回值一致。"""
        import agent.tools  # noqa: F401
        dispatcher = _build_dispatcher()

        result = _dispatch_tool_invoke(
            dispatcher,
            tool_name="_safe_noop",
        )

        payload = dict(result.payload)
        assert payload["tool_output"] == "noop: ok"
        assert "noop" in payload["tool_output"]

    def test_a3_confirmable_noop_invoked(self):
        """A3: confirmation="always" 的工具在 gate 放行后仍可 invoke。"""
        import agent.tools  # noqa: F401
        dispatcher = _build_dispatcher()

        result = _dispatch_tool_invoke(
            dispatcher,
            tool_name="_confirmable_noop",
            tool_input={},
        )

        assert result.status == "success"
        payload = dict(result.payload)
        assert payload["disposition"] == "invoked"
        assert payload["tool_invoked"] is True
        assert payload["tool_output"] == "confirmable_noop: ok"

    def test_a4_dangerous_tool_function_invoked_low_risk(self):
        """A4: low risk 工具的 dangerous_tool_function_invoked 为 False。"""
        import agent.tools  # noqa: F401
        dispatcher = _build_dispatcher()

        result = _dispatch_tool_invoke(dispatcher, tool_name="_safe_noop")

        payload = dict(result.payload)
        assert payload["dangerous_tool_function_invoked"] is False

    def test_a5_external_side_effects_noop(self):
        """A5: noop 工具的 external_side_effects 为 False。"""
        import agent.tools  # noqa: F401
        dispatcher = _build_dispatcher()

        result = _dispatch_tool_invoke(dispatcher, tool_name="_safe_noop")

        evidence = dict(result.evidence)
        assert evidence["external_side_effects"] is False


# ========== Phase B: Missing / Invalid Payload ==========


class TestMissingInvalidPayload:
    """Phase B: 缺少必填字段或工具不存在时的防御行为。"""

    def test_b1_missing_tool_name(self):
        """B1: 缺 tool_name 时返回 failed，不崩溃。"""
        dispatcher = _build_dispatcher()

        payload = {"tool_input": {}}
        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.TOOL_INVOKE,
                source="test_tool_invoke",
                parent_trace_id="trace:tool-invoke-test",
                payload=payload,
            )
        )

        assert result.status == "success"
        payload_out = dict(result.payload)
        assert payload_out["disposition"] == "failed"
        assert "tool_name" in payload_out.get("error", "")

    def test_b2_missing_tool_input(self):
        """B2: 缺 tool_input 时返回 failed。"""
        dispatcher = _build_dispatcher()

        payload = {"tool_name": "_safe_noop"}
        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.TOOL_INVOKE,
                source="test_tool_invoke",
                parent_trace_id="trace:tool-invoke-test",
                payload=payload,
            )
        )

        assert result.status == "success"
        payload_out = dict(result.payload)
        assert payload_out["disposition"] == "failed"
        assert "tool_input" in payload_out.get("error", "")

    def test_b3_tool_not_found(self):
        """B3: 工具不在 TOOL_REGISTRY 中返回 not_found。"""
        dispatcher = _build_dispatcher()

        result = _dispatch_tool_invoke(
            dispatcher,
            tool_name="nonexistent_tool_xyz",
            tool_input={},
        )

        assert result.status == "success"
        payload = dict(result.payload)
        assert payload["disposition"] == "not_found"
        assert payload["tool_invoked"] is False
        assert payload["dangerous_tool_function_invoked"] is False
        assert payload["tool_output"] is None


# ========== Phase C: No Side Effects ==========


class TestNoSideEffects:
    """Phase C: handler 是纯执行操作，不修改 TOOL_REGISTRY。"""

    def test_c1_does_not_modify_tool_registry(self):
        """C1: handler 不修改 TOOL_REGISTRY。"""
        import agent.tools  # noqa: F401
        from agent.tool_registry import TOOL_REGISTRY

        dispatcher = _build_dispatcher()
        pre_keys = set(TOOL_REGISTRY.keys())
        pre_count = len(TOOL_REGISTRY)

        _dispatch_tool_invoke(dispatcher)

        post_keys = set(TOOL_REGISTRY.keys())
        post_count = len(TOOL_REGISTRY)
        assert pre_keys == post_keys
        assert pre_count == post_count

    def test_c2_does_not_trigger_other_tool_actions(self):
        """C2: TOOL_INVOKE 不触发 TOOL_GATE / TOOL_RESULT。"""
        import agent.tools  # noqa: F401
        dispatcher = _build_dispatcher()

        _dispatch_tool_invoke(dispatcher)

        action_types = {str(event.action_type) for event in dispatcher.action_log}
        assert "tool.invoke" in action_types
        assert "tool.gate" not in action_types
        assert "tool.result" not in action_types
        assert "tool.request" not in action_types

    def test_c3_evidence_no_registry_modification(self):
        """C3: evidence 正确标记无副作用。"""
        import agent.tools  # noqa: F401
        dispatcher = _build_dispatcher()

        result = _dispatch_tool_invoke(dispatcher)

        evidence = dict(result.evidence)
        assert evidence.get("no_tool_registry_modification") is True
        assert evidence.get("no_memory_side_effects") is True


# ========== Phase D: Evidence Classification ==========


class TestEvidenceClassification:
    """Phase D: evidence 分类验证。"""

    def test_d1_dispatcher_route_harness_runtime_e2e(self):
        """D1: dispatcher.route() with target_module_proof → harness_runtime_e2e。"""
        import agent.tools  # noqa: F401
        dispatcher = _build_dispatcher()

        result = _dispatch_tool_invoke(dispatcher)

        evidence = dict(result.evidence)
        assert evidence.get("target_module_proof") is not None
        assert evidence.get("target_catalog_allowed") is True
        assert evidence.get("target_identity_valid") is True
        assert evidence.get("handler_name") == "ToolInvokeHandler"
        assert evidence.get("target_module") == "ToolRegistry"
        assert evidence.get("evidence_level") == HARNESS_RUNTIME_E2E

    def test_d2_direct_handler_instantiation(self):
        """D2: direct handler 实例化不崩溃。"""
        handler = ToolInvokeHandler()
        assert handler is not None
        assert handler._store is not None


# ========== Phase E: Regression Isolation ==========


class TestRegressionIsolation:
    """Phase E: 已有测试不受影响。"""

    def test_e1_all_handlers_still_registered(self):
        """E1: 所有 handler 正确注册，tool.invoke 不影响已有注册。"""
        from agent.runtime_integration.phase1_hook import build_phase1_dispatcher

        dispatcher = build_phase1_dispatcher()
        snapshot = dispatcher._registry.snapshot()

        assert "tool.gate" in snapshot
        assert "tool.result" in snapshot
        assert "tool.invoke" in snapshot
        assert "memory.recall" in snapshot
        assert "memory.propose" in snapshot
        assert "memory.turn_end_proposal" in snapshot

    def test_e2_tool_gate_handler_still_works(self):
        """E2: TOOL_GATE handler 仍然正常工作。"""
        from agent.runtime_integration.phase1_hook import build_phase1_dispatcher

        dispatcher = build_phase1_dispatcher()

        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.TOOL_GATE,
                source="test_tool_invoke",
                parent_trace_id="trace:regression-test",
                payload={"tool_name": "_safe_noop"},
            )
        )

        assert result.status == "success"
        payload = dict(result.payload)
        assert payload["gate_disposition"] == "allowed"

    def test_e3_tool_result_handler_still_works(self):
        """E3: TOOL_RESULT handler 仍然正常工作。"""
        from agent.runtime_integration.phase1_hook import build_phase1_dispatcher

        dispatcher = build_phase1_dispatcher()

        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.TOOL_RESULT,
                source="test_tool_invoke",
                parent_trace_id="trace:regression-test",
                payload={
                    "tool_name": "_safe_noop",
                    "tool_output": "test output",
                    "execution_status": "success",
                },
            )
        )

        assert result.status == "success"
        payload = dict(result.payload)
        assert payload["disposition"] in {"injected", "empty"}


# ========== Phase F: Negative / Edge Cases ==========


class TestNegative:
    """Phase F: 异常路径和防御行为。"""

    def test_f1_tool_execution_error_not_crash(self):
        """F1: 工具函数执行异常不崩溃。"""
        from agent.tool_registry import TOOL_REGISTRY, register_tool

        # 注册一个会抛异常的工具
        @register_tool(
            name="_test_broken_tool",
            description="Broken tool for error handling test",
            parameters={},
            confirmation="never",
            capability="local_action",
            risk_level="low",
            output_policy="none",
            meta_tool=False,
        )
        def _test_broken_tool() -> str:
            raise RuntimeError("simulated tool failure")

        try:
            dispatcher = _build_dispatcher()

            result = _dispatch_tool_invoke(
                dispatcher,
                tool_name="_test_broken_tool",
                tool_input={},
            )

            assert result.status == "success"  # handler 层面不崩溃
            payload = dict(result.payload)
            assert payload["execution_status"] == "error"
            assert payload["tool_invoked"] is True  # 函数确实被调用了
        finally:
            TOOL_REGISTRY.pop("_test_broken_tool", None)

    def test_f2_very_long_tool_name(self):
        """F2: 异常长的 tool_name 不导致格式化崩溃。"""
        dispatcher = _build_dispatcher()

        long_name = "a" * 500
        result = _dispatch_tool_invoke(
            dispatcher,
            tool_name=long_name,
            tool_input={},
        )

        assert result.status in {"success", "rejected"}

    def test_f3_dangerous_tool_high_risk(self):
        """F3: high risk 工具正确标记。"""
        from agent.tool_registry import TOOL_REGISTRY, register_tool

        @register_tool(
            name="_test_high_risk_tool",
            description="High risk tool for testing",
            parameters={},
            confirmation="always",
            capability="command_execution",
            risk_level="high",
            output_policy="none",
            meta_tool=False,
        )
        def _test_high_risk_tool() -> str:
            return "high risk executed"

        try:
            dispatcher = _build_dispatcher()

            result = _dispatch_tool_invoke(
                dispatcher,
                tool_name="_test_high_risk_tool",
                tool_input={},
            )

            assert result.status == "success"
            payload = dict(result.payload)
            assert payload["dangerous_tool_function_invoked"] is True

            evidence = dict(result.evidence)
            assert evidence["external_side_effects"] is True
        finally:
            TOOL_REGISTRY.pop("_test_high_risk_tool", None)


# ========== Deferred ==========
# L3 real_core_loop_runtime_e2e — 需 loop.py 中构造 TOOL_INVOKE action
# Tool retry / error recovery
# Multi Tool invoke
# Streaming tool invoke
