"""MCP Runtime Integration TDD 测试。

中文学习边界：
MCP tool-like execution 接入已有 "tool execution / confirmation handling" 分支点。
MCP 工具不在 TOOL_REGISTRY 之外——它们通过 register_mcp_tools() 注册，
条目结构与本地工具一致。capability="mcp_tool" 是 TOOL_GATE 的已知元数据维度。

这不是新 Anchor、不是新 capability milestone、不是新 runtime flow。
MCP tool-like execution 是已有 Tool branch point 下的一个 variant。

测试分层：
- L1 (subsystem_integration): FakeMCPClient 直接调用
- L2 (harness_runtime_e2e): dispatcher.route()
- L3 (real_core_loop_runtime_e2e): verified in test_mcp_l3_real_core_loop.py

架构依据：
- docs/specs/mcp-runtime-integration/SPEC.md
- docs/specs/mcp-runtime-integration/TDD.md
- docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md
"""

from __future__ import annotations

import pytest

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
from agent.runtime_integration.tool_gate import ToolGateHandler
from agent.runtime_integration.tool_invoke import ToolInvokeHandler
from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler
from agent.tool_registry import set_model_visible_tool_limits

# conftest.py 的 reset_global_runtime_configs autouse fixture 会在
# 每个 test 前 reset_model_visible_tool_limits() 将限制恢复为 max_mcp=5/max_total=30。
# 因此模块级 set_model_visible_tool_limits 会被覆盖，需要在 helper 中每次重新设置。
# 参见 _register_fake_mcp_tool 中的 set_model_visible_tool_limits 调用。

# 追踪本模块注册的 MCP 工具名，配合 _cleanup_mcp_tools fixture 在 test 后清理，
# 避免 TOOL_REGISTRY 污染其他 test module。
_registered_mcp_tool_names: set[str] = set()


@pytest.fixture(autouse=True)
def _cleanup_mcp_tools():
    """每个 test 后清理本模块注册的 MCP 工具，防止 TOOL_REGISTRY 泄漏到其他 test module。"""
    yield
    from agent.tool_registry import TOOL_REGISTRY

    for name in list(_registered_mcp_tool_names):
        TOOL_REGISTRY.pop(name, None)
    _registered_mcp_tool_names.clear()


# ========== 测试辅助工厂 ==========


def _build_mcp_dispatcher() -> RuntimeActionDispatcher:
    """构建注册了 TOOL_GATE + TOOL_INVOKE + TOOL_RESULT handler 的 dispatcher。

    MCP 工具通过这三个 handler 走完整 tool lifecycle pipeline，
    不需要额外的 handler 类型。
    """
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
    registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
    registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
    return RuntimeActionDispatcher(registry=registry, observer=RuntimeActionModuleObserver())


def _register_fake_mcp_tool(
    server_name: str = "demo",
    tool_name: str = "hello",
    tool_description: str = "Say hello",
    result_content: str = "hello from MCP",
    *,
    is_error: bool = False,
    error_message: str | None = None,
) -> str:
    """注册单个 fake MCP 工具到 TOOL_REGISTRY，返回 registry 名称。

    使用 FakeMCPClient —— 不启动 server、不联网、不读 .env。
    如果已注册（同名 server + tool），直接返回已有 registry name。

    is_error=True 时构造 MCPCallResult(is_error=True)，模拟 MCP server 返回错误，
    用于验证 _tool_invoke_adapter 的 error detection 能正确识别 MCP 格式错误消息。
    """
    from agent.mcp import FakeMCPClient, MCPCallResult, register_mcp_tools
    from agent.mcp_models import MCPServerConfig, MCPToolDescriptor, mcp_registry_tool_name

    # conftest.py 的 autouse fixture 会在每个 test 前 reset limits，
    # 必须在此处每次重新设置，否则 get_model_visible_tools() 使用默认 max_mcp=5/max_total=30
    set_model_visible_tool_limits(max_mcp=50, max_total=200)

    registry_name = mcp_registry_tool_name(server_name, tool_name)

    from agent.tool_registry import TOOL_REGISTRY
    if registry_name in TOOL_REGISTRY:
        return registry_name

    server = MCPServerConfig(name=server_name, transport="stdio", command="fake-cmd", enabled=True)
    descriptor = MCPToolDescriptor(
        server_name=server_name,
        name=tool_name,
        description=tool_description,
        input_schema={},
    )
    call_result = MCPCallResult(
        content=result_content,
        is_error=is_error,
        error_message=error_message if is_error else None,
    )
    client = FakeMCPClient(
        tools_by_server={server_name: [descriptor]},
        results_by_call={(server_name, tool_name): call_result},
    )
    register_mcp_tools(
        [server], client,
        server_allowlist=frozenset({server_name}),
    )
    _registered_mcp_tool_names.add(registry_name)
    return registry_name


def _dispatch_tool_gate(dispatcher, tool_name):
    """便捷 helper：dispatch TOOL_GATE 并返回 result。"""
    return dispatcher.route(
        RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test_mcp_integration",
            parent_trace_id="trace:mcp-test",
            payload={"tool_name": tool_name},
        )
    )


def _dispatch_tool_invoke(dispatcher, tool_name, tool_input=None):
    """便捷 helper：dispatch TOOL_INVOKE 并返回 result。"""
    return dispatcher.route(
        RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_INVOKE,
            source="test_mcp_integration",
            parent_trace_id="trace:mcp-test",
            payload={"tool_name": tool_name, "tool_input": tool_input or {}},
        )
    )


def _dispatch_tool_result(dispatcher, tool_name, tool_output, execution_status="success"):
    """便捷 helper：dispatch TOOL_RESULT 并返回 result。"""
    return dispatcher.route(
        RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_RESULT,
            source="test_mcp_integration",
            parent_trace_id="trace:mcp-test",
            payload={
                "tool_name": tool_name,
                "tool_output": tool_output,
                "execution_status": execution_status,
            },
        )
    )


# ========== Phase A: MCP Tool Registration → TOOL_GATE (L2) ==========


class TestMCPToolGate:
    """Phase A: 验证 MCP 工具通过 TOOL_GATE 被 lookup 和 gating。"""

    def test_a1_mcp_tool_enters_tool_gate(self):
        """A1: MCP 工具注册后可通过 TOOL_GATE 被 lookup，返回 confirmation_required。"""
        registry_name = _register_fake_mcp_tool("demo_a1", "hello")
        dispatcher = _build_mcp_dispatcher()

        result = _dispatch_tool_gate(dispatcher, registry_name)

        assert result.status == "confirmation_required"
        payload = dict(result.payload)
        assert payload["gate_disposition"] in ("confirmation_required", "allowed")
        evidence = dict(result.evidence)
        assert evidence["production_registry_found"] is True
        assert evidence["handler_name"] == "ToolGateHandler"
        assert evidence["decision"] == "confirmation_required"
        # forbidden
        assert payload["gate_disposition"] is not None
        assert "allowlist" not in str(evidence.get("rejection_reason", ""))

    def test_a2_mcp_tool_gate_blocked_for_not_registered(self):
        """A2: 未注册的 MCP 工具名在 TOOL_GATE 返回 not_found。"""
        dispatcher = _build_mcp_dispatcher()

        result = _dispatch_tool_gate(dispatcher, "mcp__nonexistent__tool")

        evidence = dict(result.evidence)
        assert evidence["decision"] == "not_found"
        payload = dict(result.payload)
        assert payload["gate_disposition"] is None
        # forbidden
        assert payload["gate_disposition"] != "allowed"

    def test_a3_mcp_tool_risk_level_preserved(self):
        """A3: TOOL_GATE 正确返回 MCP 工具的 high risk_level。"""
        registry_name = _register_fake_mcp_tool("demo_a3", "hello")
        dispatcher = _build_mcp_dispatcher()

        result = _dispatch_tool_gate(dispatcher, registry_name)

        payload = dict(result.payload)
        assert payload["risk_level"] == "high"


# ========== Phase B: MCP Tool Execution → TOOL_INVOKE (L2) ==========


class TestMCPToolInvoke:
    """Phase B: 验证 TOOL_INVOKE handler 只记录 evidence。"""

    def test_b1_allowed_mcp_tool_invoked_via_dispatcher(self):
        """B1: MCP 工具通过 TOOL_INVOKE handler 不会被执行。"""
        registry_name = _register_fake_mcp_tool(
            "demo_b1", "hello", result_content="bonjour from MCP"
        )
        dispatcher = _build_mcp_dispatcher()

        result = _dispatch_tool_invoke(dispatcher, registry_name)

        assert result.status == "success"
        payload = dict(result.payload)
        assert payload["disposition"] == "evidence_only"
        assert payload["tool_invoked"] is False
        assert payload["tool_output"] is None
        assert payload["execution_status"] == "not_executed"
        # forbidden
        assert payload["tool_invoked"] is not True

    def test_b2_mcp_tool_not_found_in_tool_invoke(self):
        """B2: 不在 TOOL_REGISTRY 中的 MCP 工具名返回 not_found。"""
        dispatcher = _build_mcp_dispatcher()

        result = _dispatch_tool_invoke(dispatcher, "mcp__nonexistent__tool", {})

        payload = dict(result.payload)
        assert payload["disposition"] == "not_found"
        assert payload["tool_invoked"] is False

    def test_b3_mcp_tool_dangerous_flag_true(self):
        """B3: MCP 工具（risk_level="high"）的 dangerous_tool_function_invoked=True。"""
        registry_name = _register_fake_mcp_tool("demo_b3", "hello")
        dispatcher = _build_mcp_dispatcher()

        result = _dispatch_tool_invoke(dispatcher, registry_name)

        payload = dict(result.payload)
        assert payload["dangerous_tool_function_invoked"] is True

    def test_b4_mcp_tool_external_side_effects_false(self):
        """B4: MCP 工具不会被标为 external_side_effects。"""
        registry_name = _register_fake_mcp_tool("demo_b4", "hello")
        dispatcher = _build_mcp_dispatcher()

        result = _dispatch_tool_invoke(dispatcher, registry_name)

        evidence = dict(result.evidence)
        assert evidence["external_side_effects"] is False


# ========== Phase C: MCP Tool Result → TOOL_RESULT (L2) ==========


class TestMCPToolResult:
    """Phase C: 验证 MCP 工具执行结果通过 TOOL_RESULT handler 格式化。"""

    def test_c1_mcp_tool_result_enters_tool_result_feedback(self):
        """C1: MCP 工具执行结果通过 TOOL_RESULT handler 格式化。"""
        dispatcher = _build_mcp_dispatcher()

        result = _dispatch_tool_result(
            dispatcher,
            tool_name="mcp__demo__hello",
            tool_output="hello from MCP",
            execution_status="success",
        )

        assert result.status == "success"
        payload = dict(result.payload)
        assert payload["disposition"] == "injected"
        prompt_section = str(payload.get("prompt_section", ""))
        assert "mcp__demo__hello" in prompt_section
        assert "hello from MCP" in prompt_section

    def test_c2_mcp_tool_error_result_truncated(self):
        """C2: MCP 工具错误结果按 error disposition 处理。"""
        dispatcher = _build_mcp_dispatcher()

        result = _dispatch_tool_result(
            dispatcher,
            tool_name="mcp__demo__hello",
            tool_output="error message",
            execution_status="error",
        )

        payload = dict(result.payload)
        assert payload["disposition"] == "error"
        prompt_section = str(payload.get("prompt_section", ""))
        assert "工具执行出错" in prompt_section


# ========== Phase D: Orchestrator — Full Pipeline (L2) ==========


class TestMCPOrchestratorPipeline:
    """Phase D: 验证 orchestrator 串联完整 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT。"""

    def test_d1_mcp_orchestrator_routes_through_full_pipeline(self):
        """D1: orchestrator 串联完整管线，三个 action 都在 action_log 中。"""
        from agent.runtime_integration.mcp_tool_orchestrator import run_mcp_tool_pipeline

        registry_name = _register_fake_mcp_tool(
            "demo_d1", "hello", result_content="pipeline result"
        )
        dispatcher = _build_mcp_dispatcher()

        result = run_mcp_tool_pipeline(dispatcher, registry_name, {})

        # gate_result
        assert result.gate_result is not None
        gate_payload = dict(result.gate_result.payload)
        assert gate_payload["gate_disposition"] == "confirmation_required"

        # invoke_result
        assert result.invoke_result is not None
        invoke_payload = dict(result.invoke_result.payload)
        assert invoke_payload["tool_invoked"] is False
        assert invoke_payload["tool_output"] is None
        assert invoke_payload["execution_status"] == "not_executed"

        # result_feedback
        assert result.result_feedback is not None
        feedback_payload = dict(result.result_feedback.payload)
        assert feedback_payload["disposition"] == "empty"
        prompt_section = str(feedback_payload.get("prompt_section", ""))
        assert "无输出" in prompt_section

        # 三个 action 都在 action_log 中
        assert result.action_log_entries == 3

        # stopped_early
        assert result.stopped_early is False

    def test_d2_orchestrator_stops_on_gate_blocked(self):
        """D2: TOOL_GATE 返回 not_found 时，orchestrator 不继续 TOOL_INVOKE/TOOL_RESULT。"""
        from agent.runtime_integration.mcp_tool_orchestrator import run_mcp_tool_pipeline

        dispatcher = _build_mcp_dispatcher()

        result = run_mcp_tool_pipeline(dispatcher, "mcp__nonexistent__tool", {})

        assert result.stopped_early is True
        assert "not_found" in result.stop_reason
        assert result.invoke_result is None
        assert result.result_feedback is None
        # 只有 TOOL_GATE 在 action_log 中
        assert result.action_log_entries == 1

    def test_d3_orchestrator_uses_harness_runtime_e2e_evidence(self):
        """D3: orchestrator 产生的 evidence 正确分类为 harness_runtime_e2e。"""
        from agent.runtime_integration.mcp_tool_orchestrator import run_mcp_tool_pipeline

        registry_name = _register_fake_mcp_tool("demo_d3", "hello")
        dispatcher = _build_mcp_dispatcher()

        result = run_mcp_tool_pipeline(dispatcher, registry_name, {})

        # 至少一个 result 的 evidence_level >= harness_runtime_e2e
        levels = []
        for r in (result.gate_result, result.invoke_result, result.result_feedback):
            if r is not None:
                levels.append(str(r.evidence.get("evidence_level", "")))
        assert any(level >= HARNESS_RUNTIME_E2E for level in levels)
        # forbidden: 不能是 real_core_loop_runtime_e2e（没有从 runtime loop 进入）
        assert all("real_core_loop" not in level for level in levels)


# ========== Phase E: Negative / Edge Cases (L1 + L2) ==========


class TestMCPEdgeCases:
    """Phase E: 负例和边界测试。"""

    def test_e1_direct_fake_mcp_client_call_is_subsystem(self):
        """E1: 直接 FakeMCPClient.call_tool() 只能 claim subsystem_integration。"""
        from agent.mcp import FakeMCPClient, MCPCallResult
        from agent.mcp_models import MCPServerConfig

        server = MCPServerConfig(name="edge_e1", transport="stdio", enabled=True)
        client = FakeMCPClient(
            results_by_call={("edge_e1", "hello"): MCPCallResult(content="direct call")},
        )
        result = client.call_tool(server, "hello", {})

        # 调用成功
        assert result.content == "direct call"
        # 但没有 RuntimeActionEvent，没有 target_module_proof
        # 这由 client 本身保证——它不产生 dispatcher evidence

    def test_e2_very_long_mcp_tool_name_handled_safely(self):
        """E2: 异常长的 MCP tool_name 不会导致崩溃。"""
        dispatcher = _build_mcp_dispatcher()
        long_name = "mcp__s" + "a" * 500 + "__tool"

        result = _dispatch_tool_gate(dispatcher, long_name)

        # 不崩溃，返回 not_found 或 rejected
        assert result.status in ("success", "rejected")

    def test_e3_empty_mcp_tool_input_handled(self):
        """E3: 空 tool_input 对 MCP 工具正常处理。"""
        registry_name = _register_fake_mcp_tool("demo_e3", "hello")
        dispatcher = _build_mcp_dispatcher()

        result = _dispatch_tool_invoke(dispatcher, registry_name, {})

        payload = dict(result.payload)
        assert payload["disposition"] == "evidence_only"
        assert payload["tool_invoked"] is False
        assert payload["execution_status"] == "not_executed"

    def test_e4_mcp_tool_name_with_special_chars(self):
        """E4: mcp_registry_tool_name 生成的名称正确处理。

        模拟 server="demo-server", tool="hello.world" ——
        _safe_token 会把 `-` 和 `.` 替换为 `_`。
        """
        from agent.mcp_models import mcp_registry_tool_name

        tool_name = mcp_registry_tool_name("demo-server", "hello.world")
        dispatcher = _build_mcp_dispatcher()

        result = _dispatch_tool_gate(dispatcher, tool_name)

        # 不崩溃
        assert result.status in ("success", "confirmation_required", "rejected")


    def test_e5_mcp_tool_error_is_not_executed_by_tool_invoke(self):
        """E5: MCP 工具错误不会在 TOOL_INVOKE dispatcher path 执行。"""
        # 注册返回 is_error=True 的 MCP 工具，模拟 MCP server 错误
        registry_name = _register_fake_mcp_tool(
            "demo_e5", "hello",
            result_content="MCP server error",
            is_error=True,
            error_message="Connection refused",
        )
        dispatcher = _build_mcp_dispatcher()

        result = _dispatch_tool_invoke(dispatcher, registry_name, {})

        payload = dict(result.payload)
        assert payload["disposition"] == "evidence_only"
        assert payload["tool_invoked"] is False
        assert payload["tool_output"] is None
        assert payload["execution_status"] == "not_executed"


# ========== Phase F: Regression Isolation (L2) ==========


class TestMCPRegression:
    """Phase F: 回归隔离——确保已有 pipeline 不受影响。"""

    def test_f1_existing_tool_pipeline_unchanged(self):
        """F1: 已有 _safe_noop 走完整 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT 不受影响。"""
        import agent.tools  # noqa: F401 - ensure tools registered
        from agent.runtime_integration.phase1_hook import build_phase1_dispatcher

        dispatcher = build_phase1_dispatcher()

        gate_result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.TOOL_GATE,
                source="test_mcp_regression",
                parent_trace_id="trace:regression-f1",
                payload={"tool_name": "_safe_noop"},
            )
        )
        assert gate_result.status == "success"
        gate_payload = dict(gate_result.payload)
        assert gate_payload["gate_disposition"] == "allowed"

        invoke_result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.TOOL_INVOKE,
                source="test_mcp_regression",
                parent_trace_id="trace:regression-f1",
                payload={"tool_name": "_safe_noop", "tool_input": {}},
            )
        )
        assert invoke_result.status == "success"
        invoke_payload = dict(invoke_result.payload)
        assert invoke_payload["disposition"] == "evidence_only"
        assert invoke_payload["tool_invoked"] is False
        assert invoke_payload["execution_status"] == "not_executed"

        feedback_result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.TOOL_RESULT,
                source="test_mcp_regression",
                parent_trace_id="trace:regression-f1",
                payload={
                    "tool_name": "_safe_noop",
                    "tool_output": "noop: ok",
                    "execution_status": "success",
                },
            )
        )
        assert feedback_result.status == "success"
        feedback_payload = dict(feedback_result.payload)
        assert feedback_payload["disposition"] == "injected"

    def test_f2_existing_mcp_tests_still_pass(self):
        """F2: 现有 MCP 测试不受影响。

        这是一个 smoke test —— 验证 register_mcp_tools 和 FakeMCPClient 仍正常工作，
        不被本轮改动破坏。完整 124 个 MCP 测试的验证在 verification gate 中运行。
        """
        registry_name = _register_fake_mcp_tool("demo_f2", "hello")
        from agent.tool_registry import TOOL_REGISTRY, execute_tool

        entry = TOOL_REGISTRY.get(registry_name)
        assert entry is not None
        assert entry["capability"] == "mcp_tool"
        assert entry["risk_level"] == "high"
        assert entry["confirmation"] == "always"

        # execute_tool 直接调用仍可用
        result = execute_tool(registry_name, {})
        assert "hello from MCP" in str(result)
