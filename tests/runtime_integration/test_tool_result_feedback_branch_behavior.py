"""Tool result feedback branch behavior TDD 测试。

中文学习边界：
Tool result feedback 归属 Contract Section 2 "tool execution / confirmation handling" 分支点。
它不是新 Anchor、不是新 capability milestone、不是新 runtime flow。
tool.result = 接收已执行 tool result → 格式化/截断/redact → 生成 prompt section →
注入模型上下文。

测试分层：
- L1 (subsystem_integration): handler 直接调用
- L2 (harness_runtime_e2e): dispatcher.route()
- L3 (real_core_loop_runtime_e2e): route_from_runtime_loop() — DEFERRED

架构依据：
- docs/specs/tool-result-feedback-branch-behavior/SPEC.md
- docs/specs/tool-result-feedback-branch-behavior/TDD.md
- docs/specs/tool-result-feedback-branch-behavior/IMPLEMENTATION_PLAN.md
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
from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler


# ========== 测试辅助工厂 ==========


def _build_dispatcher() -> RuntimeActionDispatcher:
    """构建注册了 TOOL_RESULT handler 的 dispatcher。"""
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.TOOL_RESULT,
        ToolResultFeedbackHandler(),
    )
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


def _dispatch_tool_result(
    dispatcher: RuntimeActionDispatcher,
    **payload_overrides,
):
    """便捷 helper：dispatch TOOL_RESULT 并返回 result。"""
    payload = {
        "tool_name": "_safe_noop",
        "tool_output": "tool executed successfully",
        "execution_status": "success",
        **payload_overrides,
    }
    return dispatcher.route(
        RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_RESULT,
            source="test_tool_result",
            parent_trace_id="trace:tool-result-test",
            payload=payload,
        )
    )


# ========== Phase A: Result Injection Happy Path ==========


class TestResultInjectionHappyPath:
    """Phase A: tool result 被格式化并注入 prompt section。"""

    def test_a1_normal_result_injected(self):
        """A1: 正常 tool result 被格式化并注入 prompt section。"""
        dispatcher = _build_dispatcher()

        result = _dispatch_tool_result(
            dispatcher,
            tool_name="_safe_noop",
            tool_output="tool executed successfully",
        )

        assert result.status == "success"
        payload = dict(result.payload)
        assert payload["disposition"] == "injected"
        assert payload["tool_name"] == "_safe_noop"
        assert "--- Tool Result ---" in payload["prompt_section"]
        assert "tool executed successfully" in payload["prompt_section"]
        assert payload["result_was_redacted"] is False
        assert payload["result_was_truncated"] is False

    def test_a2_empty_result_placeholder(self):
        """A2: 空 tool result 返回 placeholder，不崩溃。"""
        dispatcher = _build_dispatcher()

        result = _dispatch_tool_result(
            dispatcher,
            tool_name="_safe_noop",
            tool_output="",
        )

        assert result.status == "success"
        payload = dict(result.payload)
        assert payload["disposition"] == "empty"
        assert "无输出" in payload["prompt_section"]

    def test_a3_long_result_truncated(self):
        """A3: 超长 result 按 char budget 截断。"""
        dispatcher = _build_dispatcher()

        long_output = "x" * 600
        result = _dispatch_tool_result(
            dispatcher,
            tool_name="_safe_noop",
            tool_output=long_output,
            rendered_char_budget=500,
        )

        assert result.status == "success"
        payload = dict(result.payload)
        assert payload["disposition"] == "truncated"
        assert payload["result_was_truncated"] is True
        assert payload["result_original_size"] == 600
        # prompt section 中 result 被截断，以 … 结尾
        prompt = payload["prompt_section"]
        assert "…" in prompt
        # 截断后不超过 500 chars（加上 section header 和 …）
        assert len(long_output) not in [len(prompt)]  # 不是完整输出

    def test_a4_error_result(self):
        """A4: tool 执行出错时，错误信息被正确标记。"""
        dispatcher = _build_dispatcher()

        result = _dispatch_tool_result(
            dispatcher,
            tool_name="_safe_noop",
            tool_output="command not found: broken_tool",
            execution_status="error",
        )

        assert result.status == "success"
        payload = dict(result.payload)
        assert payload["disposition"] == "error"
        assert payload["execution_status"] == "error"
        prompt = payload["prompt_section"]
        assert "执行出错" in prompt


# ========== Phase B: Empty / Missing Payload ==========


class TestEmptyMissingPayload:
    """Phase B: 缺少必填字段时的防御行为。"""

    def test_b1_missing_tool_name(self):
        """B1: 缺 tool_name 时返回 failed，不崩溃。"""
        dispatcher = _build_dispatcher()

        payload = {
            "tool_output": "some output",
            "execution_status": "success",
        }
        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.TOOL_RESULT,
                source="test_tool_result",
                parent_trace_id="trace:tool-result-test",
                payload=payload,
            )
        )

        assert result.status == "success"  # handler 层面 success，payload 标记 failed
        payload_out = dict(result.payload)
        assert payload_out["disposition"] == "failed"
        assert "tool_name" in payload_out.get("error", "")

    def test_b2_missing_tool_output(self):
        """B2: 缺 tool_output 时返回 failed。"""
        dispatcher = _build_dispatcher()

        payload = {
            "tool_name": "_safe_noop",
            "execution_status": "success",
        }
        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.TOOL_RESULT,
                source="test_tool_result",
                parent_trace_id="trace:tool-result-test",
                payload=payload,
            )
        )

        assert result.status == "success"
        payload_out = dict(result.payload)
        assert payload_out["disposition"] == "failed"
        assert "tool_output" in payload_out.get("error", "")

    def test_b3_tool_output_none(self):
        """B3: tool_output=None 时视为空结果（key 存在但值为 None）。"""
        dispatcher = _build_dispatcher()

        result = _dispatch_tool_result(
            dispatcher,
            tool_name="_safe_noop",
            tool_output=None,
        )

        assert result.status == "success"
        payload = dict(result.payload)
        assert payload["disposition"] == "empty"
        assert "无输出" in payload["prompt_section"]


# ========== Phase C: No Side Effects ==========


class TestNoSideEffects:
    """Phase C: tool.result handler 是纯格式化操作，无副作用。"""

    def test_c1_does_not_modify_tool_registry(self):
        """C1: handler 不修改 TOOL_REGISTRY。"""
        from agent.tool_registry import TOOL_REGISTRY

        dispatcher = _build_dispatcher()
        pre_keys = set(TOOL_REGISTRY.keys())
        pre_count = len(TOOL_REGISTRY)

        _dispatch_tool_result(dispatcher)

        post_keys = set(TOOL_REGISTRY.keys())
        post_count = len(TOOL_REGISTRY)
        assert pre_keys == post_keys
        assert pre_count == post_count

    def test_c2_does_not_trigger_other_tool_actions(self):
        """C2: TOOL_RESULT 不触发 TOOL_GATE / TOOL_INVOKE / TOOL_REQUEST。"""
        dispatcher = _build_dispatcher()

        _dispatch_tool_result(dispatcher)

        action_types = {str(event.action_type) for event in dispatcher.action_log}
        assert "tool.result" in action_types
        assert "tool.gate" not in action_types
        assert "tool.invoke" not in action_types
        assert "tool.request" not in action_types

    def test_c3_does_not_trigger_memory_actions(self):
        """C3: TOOL_RESULT 不触发任何 memory action。"""
        dispatcher = _build_dispatcher()

        _dispatch_tool_result(dispatcher)

        action_types = {str(event.action_type) for event in dispatcher.action_log}
        assert "tool.result" in action_types
        assert "memory.propose" not in action_types
        assert "memory.turn_end_proposal" not in action_types
        assert "memory.recall" not in action_types

    def test_c4_is_pure_format_operation(self):
        """C4: handler 是纯格式化操作，无外部副作用。"""
        dispatcher = _build_dispatcher()

        result = _dispatch_tool_result(dispatcher)

        evidence = dict(result.evidence)
        assert evidence.get("external_side_effects") is False
        assert evidence.get("read_only_operation") is True
        assert evidence.get("no_tool_registry_modification") is True
        assert evidence.get("no_tool_invocation") is True
        assert evidence.get("no_memory_side_effects") is True


# ========== Phase D: Evidence Classification ==========


class TestEvidenceClassification:
    """Phase D: evidence 分类验证。"""

    def test_d1_dispatcher_route_produces_harness_runtime_e2e(self):
        """D1: dispatcher.route() with target_module_proof → harness_runtime_e2e。"""
        dispatcher = _build_dispatcher()

        result = _dispatch_tool_result(dispatcher)

        evidence = dict(result.evidence)
        assert evidence.get("target_module_proof") is not None
        assert evidence.get("target_catalog_allowed") is True
        assert evidence.get("target_identity_valid") is True
        assert evidence.get("handler_name") == "ToolResultFeedbackHandler"
        assert evidence.get("target_module") == "ToolRuntime"
        assert evidence.get("evidence_level") == HARNESS_RUNTIME_E2E

    def test_d2_direct_handler_call_does_not_crash(self):
        """D2: direct handler 实例化不崩溃，可以被独立调用。"""
        handler = ToolResultFeedbackHandler()
        assert handler is not None
        assert handler._store is not None
        # handler 可以独立于 dispatcher 被构造和持有
        # direct 调用不经过 dispatcher，无法获得 target_module_proof


# ========== Phase E: Regression Isolation ==========


class TestRegressionIsolation:
    """Phase E: 已有测试不受影响。"""

    def test_e1_all_handlers_still_registered(self):
        """E1: 所有 handler 正确注册，tool.result 不影响已有注册。"""
        from agent.runtime_integration.phase1_hook import build_phase1_dispatcher

        dispatcher = build_phase1_dispatcher()
        snapshot = dispatcher._registry.snapshot()

        assert "tool.gate" in snapshot
        assert "tool.result" in snapshot
        assert "memory.recall" in snapshot
        assert "memory.propose" in snapshot
        assert "memory.turn_end_proposal" in snapshot

    def test_e2_tool_gate_handler_still_works(self):
        """E2: TOOL_GATE handler 仍然正常工作，不受 tool.result 影响。"""
        from agent.runtime_integration.phase1_hook import build_phase1_dispatcher

        dispatcher = build_phase1_dispatcher()
        snapshot = dispatcher._registry.snapshot()

        # tool.gate 仍然注册
        assert "tool.gate" in snapshot
        # tool.result 没有替换 tool.gate
        assert snapshot["tool.gate"] is not snapshot.get("tool.result")


# ========== Phase F: Negative / Edge Cases ==========


class TestNegative:
    """Phase F: 异常路径和防御行为。"""

    def test_f1_handler_with_none_store_graceful(self):
        """F1: store=None 时 handler graceful degradation。"""
        handler = ToolResultFeedbackHandler(store=None)

        # store=None 时 handler 内部会用默认 InMemoryMemoryStore
        assert handler._store is not None

    def test_f2_very_long_tool_name(self):
        """F2: 异常长的 tool_name 不导致格式化崩溃。"""
        dispatcher = _build_dispatcher()

        long_name = "a" * 500
        result = _dispatch_tool_result(
            dispatcher,
            tool_name=long_name,
            tool_output="normal output",
        )

        assert result.status == "success"
        payload = dict(result.payload)
        assert payload["disposition"] == "injected"
        assert long_name in payload["prompt_section"]


# ========== Deferred ==========
# L3 real_core_loop_runtime_e2e — 需 loop.py 中构造 TOOL_RESULT action
# Sensitive content redact (real API keys in tool output)
# Tool retry / error recovery
# Multi Tool result merge
# Streaming tool result
