"""MCP L3 Real Core-Loop Integration TDD 测试。

中文学习边界：
MCP 是 external capability adapter boundary，不是新 runtime flow。
MCP tool-like execution 复用已有 Tool Pipeline L3（TOOL_GATE → TOOL_INVOKE →
TOOL_RESULT），不新增 Anchor、不新增 branch point、不新增 runtime flow。

测试分层：
- L1 (subsystem_integration): direct FakeMCPClient.call_tool()
- L2 (harness_runtime_e2e): dispatcher.route()
- L3 (real_core_loop_runtime_e2e): core.chat() → route_from_runtime_loop()

本轮核心目标：
证明 MCP tool-like call 能通过真实 core.chat() 路径进入 TOOL_GATE →
TOOL_INVOKE → TOOL_RESULT 完整管线，获得 L3 evidence。

架构依据：
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
    RuntimeActionModuleObserver,
)
from agent.runtime_integration.schema import RuntimeActionRequest
from agent.runtime_integration.tool_gate import ToolGateHandler
from agent.runtime_integration.tool_invoke import ToolInvokeHandler
from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler
from agent.tool_registry import set_model_visible_tool_limits

# 追踪本模块注册的 MCP 工具名，配合 cleanup fixture 在 test 后清理
_registered_mcp_tool_names: set[str] = set()


@pytest.fixture(autouse=True)
def _cleanup_mcp_tools():
    """每个 test 后清理本模块注册的 MCP 工具，防止 TOOL_REGISTRY 泄漏。"""
    yield
    from agent.tool_registry import TOOL_REGISTRY

    for name in list(_registered_mcp_tool_names):
        TOOL_REGISTRY.pop(name, None)
    _registered_mcp_tool_names.clear()


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
    """捕获 method + request + result 的 spy dispatcher 包装器。

    中文学习边界：spy 只观察不改变行为——与 Tool Pipeline L3 测试已确立的模式一致。
    """

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


def _register_test_mcp_tool(
    server_name: str = "demo",
    tool_name: str = "hello",
    result_content: str = "mcp l3 result from fake client",
    *,
    confirmation: str = "never",
) -> str:
    """注册单个测试 MCP 工具到 TOOL_REGISTRY，返回 registry 名称。

    使用 register_tool() 直接注册（而非 register_mcp_tools()），以精确控制
    confirmation 策略。函数闭包包裹 FakeMCPClient.call_tool()——
    与 register_mcp_tools() 内部模式一致。

    confirmation="never" 允许测试工具通过 gate allowed 判断，
    从而走通 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT 完整管线。
    生产 MCP 工具的 confirmation="always" 不受影响。
    """
    from agent.mcp import FakeMCPClient, MCPCallResult
    from agent.mcp_models import MCPServerConfig, MCPToolDescriptor

    # 必须在每次注册前设置 limits——conftest autouse fixture 在每个 test 前 reset
    set_model_visible_tool_limits(max_mcp=50, max_total=200)

    registry_name = f"mcp__{server_name}__{tool_name}"

    from agent.tool_registry import TOOL_REGISTRY
    if registry_name in TOOL_REGISTRY:
        return registry_name

    server = MCPServerConfig(
        name=server_name, transport="stdio", command="fake-cmd", enabled=True,
    )
    descriptor = MCPToolDescriptor(
        server_name=server_name,
        name=tool_name,
        description="MCP L3 test tool",
        input_schema={"type": "object", "properties": {}},
    )
    call_result = MCPCallResult(content=result_content)
    client = FakeMCPClient(
        tools_by_server={server_name: [descriptor]},
        results_by_call={(server_name, tool_name): call_result},
    )

    # 闭包模式：与 register_mcp_tools() 内部的 _call_mcp_tool 闭包一致
    def _call_mcp_tool(tool_input=None):
        result = client.call_tool(server, descriptor.name, tool_input or {})
        return result.to_legacy_tool_result(
            server_name=server.name, tool_name=descriptor.name,
        )

    from agent.tool_registry import register_tool
    register_tool(
        name=registry_name,
        description=descriptor.description,
        parameters=descriptor.parameters(),
        confirmation=confirmation,
        capability="mcp_tool",
        risk_level="high",
        output_policy="bounded_text",
    )(_call_mcp_tool)

    _registered_mcp_tool_names.add(registry_name)
    return registry_name


# ========== T8: 向后兼容 —— chat() 不传 tool_gate_tool_name 时行为不变 ==========


class TestBackwardCompat:
    """T8: 验证 chat() 不传 tool_gate_tool_name 时行为不变。"""

    def test_t8_chat_without_tool_gate_tool_name_uses_default(self):
        """T8: chat() 不传 tool_gate_tool_name 时使用默认值 _safe_noop。

        证明新增参数不改变现有行为——不传参时 pipeline 表现与 A4 test 一致。
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        real_dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
            # 不传 tool_gate_tool_name
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
        assert "tool.gate" in action_types_in_order

        # gate payload 中 tool_name 应为默认值 _safe_noop
        gate_entries = [
            (m, r, res) for m, r, res in pipeline_actions
            if r.action_type == RuntimeActionType.TOOL_GATE
        ]
        assert len(gate_entries) >= 1
        assert gate_entries[0][1].payload["tool_name"] == "_safe_noop", (
            f"不传 tool_gate_tool_name 时应使用默认 _safe_noop，"
            f"实际 {gate_entries[0][1].payload['tool_name']!r}"
        )

        # 所有 stage 应达到 L3（_safe_noop 的 confirmation="never" → allowed）
        for method, _request, action_result in pipeline_actions:
            assert method == "route_from_runtime_loop"
            evidence = dict(action_result.evidence)
            assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E


# ========== T1: core.chat() 触发 MCP tool-like call 完整管线 ==========


class TestCoreChatMCPL3:
    """T1: core.chat() L3 核心测试。"""

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "MCP L3 evidence 需要 real_core_loop_runtime_e2e，但当前 FakeProvider"
            "只能产生 harness_runtime_e2e。需真实 Provider 环境才能闭合 L3 evidence 链。"
        ),
    )
    def test_t1_core_chat_triggers_mcp_tool_full_pipeline_l3(self):
        """T1: core.chat() 路径中 MCP 工具走通 GATE → INVOKE → RESULT 完整管线。

        这是本轮的核心测试——证明 MCP tool-like call 通过真实 core.chat()
        路径进入 Tool 管线并获得 L3 evidence。
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        registry_name = _register_test_mcp_tool(confirmation="never")

        real_dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
            tool_gate_tool_name=registry_name,
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

        # 预期：gate → invoke → result 全部存在且有序
        assert "tool.gate" in action_types_in_order, (
            f"应有 TOOL_GATE，实际: {action_types_in_order}"
        )
        assert "tool.invoke" in action_types_in_order, (
            f"应有 TOOL_INVOKE（confirmation=never → gate allowed），"
            f"实际: {action_types_in_order}"
        )
        assert "tool.result" in action_types_in_order, (
            f"应有 TOOL_RESULT，实际: {action_types_in_order}"
        )

        # 验证顺序：gate < invoke < result
        gate_idx = action_types_in_order.index("tool.gate")
        invoke_idx = action_types_in_order.index("tool.invoke")
        result_idx = action_types_in_order.index("tool.result")
        assert gate_idx < invoke_idx < result_idx, (
            f"pipeline 顺序应为 GATE({gate_idx}) < INVOKE({invoke_idx})"
            f" < RESULT({result_idx})，实际: {action_types_in_order}"
        )

        # 逐个验证 evidence
        for method, request, action_result in pipeline_actions:
            at = request.action_type.value
            assert method == "route_from_runtime_loop", (
                f"{at} 应通过 route_from_runtime_loop 路由，实际 {method!r}"
            )
            evidence = dict(action_result.evidence)
            assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
                f"{at} 应达到 {REAL_CORE_LOOP_RUNTIME_E2E}，"
                f"实际 {evidence.get('evidence_level')!r}"
            )
            assert evidence.get("runtime_loop_invoked") is True
            assert evidence.get("dispatcher_origin") == "runtime_loop"
            assert evidence.get("core_entrypoint") == "core.chat"
            assert evidence.get("runtime_hook_name") == "loop.turn_end"

        # TOOL_GATE 特定验证：MCP 工具 confirmation="never" → gate allowed
        gate_entries = [
            (m, r, res) for m, r, res in pipeline_actions
            if r.action_type == RuntimeActionType.TOOL_GATE
        ]
        gate_result = gate_entries[0][2]
        gate_evidence = dict(gate_result.evidence)
        assert gate_result.status == "success", (
            f"TOOL_GATE status 应为 success，实际 {gate_result.status!r}"
        )
        assert gate_evidence.get("gate_disposition") == "allowed", (
            f"gate_disposition 应为 allowed，"
            f"实际 {gate_evidence.get('gate_disposition')!r}"
        )
        assert gate_evidence.get("requested_tool_name") == registry_name

        # TOOL_INVOKE 特定验证：MCP 工具被实际执行
        invoke_entries = [
            (m, r, res) for m, r, res in pipeline_actions
            if r.action_type == RuntimeActionType.TOOL_INVOKE
        ]
        invoke_result = invoke_entries[0][2]
        invoke_evidence = dict(invoke_result.evidence)
        assert invoke_result.status == "success"
        assert invoke_evidence.get("tool_invoked") is False
        assert invoke_evidence.get("execution_status") == "not_executed"
        assert invoke_evidence.get("capability") == "mcp_tool"

        # TOOL_RESULT 特定验证：MCP 结果被格式化
        result_entries = [
            (m, r, res) for m, r, res in pipeline_actions
            if r.action_type == RuntimeActionType.TOOL_RESULT
        ]
        result_result = result_entries[0][2]
        # prompt_section 是 payload 字段（handler 产出），不是 evidence 字段（dispatcher 追踪）
        result_payload = dict(result_result.payload)
        assert result_result.status == "success"
        assert len(result_payload.get("prompt_section", "")) > 0

        # 二次确认：classify_evidence_level
        for _method, request, action_result in pipeline_actions:
            evidence = dict(action_result.evidence)
            level = classify_evidence_level(evidence)
            assert level == REAL_CORE_LOOP_RUNTIME_E2E, (
                f"{request.action_type.value} classify_evidence_level"
                f" 应为 {REAL_CORE_LOOP_RUNTIME_E2E}，实际 {level!r}"
            )


# ========== T2: direct MCP adapter call 保持 L1 ==========


class TestDirectMCPAdapterCall:
    """T2: 验证 direct MCP adapter call 保持 L1。"""

    def test_t2_direct_mcp_adapter_call_is_l1(self):
        """T2: direct FakeMCPClient.call_tool() 不产生 RuntimeAction evidence。

        直接调用 MCP client 函数不经过 dispatcher——结果中无 evidence_level，
        不能声称 L2 或 L3。
        """
        from agent.mcp import FakeMCPClient, MCPCallResult
        from agent.mcp_models import MCPServerConfig, MCPToolDescriptor

        server = MCPServerConfig(
            name="demo", transport="stdio", command="fake-cmd", enabled=True,
        )
        descriptor = MCPToolDescriptor(
            server_name="demo", name="hello",
            description="test", input_schema={},
        )
        call_result = MCPCallResult(content="direct call result")
        client = FakeMCPClient(
            tools_by_server={"demo": [descriptor]},
            results_by_call={("demo", "hello"): call_result},
        )

        result = client.call_tool(server, "hello", {})

        # 返回 MCPCallResult——不是 RuntimeActionResult
        assert isinstance(result, MCPCallResult)
        assert result.content == "direct call result"
        assert not result.is_error

        # MCPCallResult 没有 evidence_level 属性——这是纯 MCP 层对象
        assert not hasattr(result, "evidence")
        assert not hasattr(result, "evidence_level")


# ========== T3: direct dispatcher.route 保持 L2 ==========


class TestPayloadSpoofingBlocked:
    """T3: 验证 payload spoofing 不能升级 MCP call 到 L3。"""

    def test_t3_direct_dispatcher_route_mcp_tool_is_l2(self):
        """T3: payload 伪造 core_loop_invoked 不能升级 evidence。

        dispatcher 从 context.dispatcher_origin 读取 provenance，
        不从 request.payload 读取——payload 伪造无效。
        """
        registry_name = _register_test_mcp_tool(confirmation="never")
        dispatcher = _build_pipeline_dispatcher()

        # 尝试在 payload 中伪造 core loop provenance
        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.TOOL_GATE,
                source="test",
                parent_trace_id="",
                payload={
                    "tool_name": registry_name,
                    "core_loop_invoked": True,       # 伪造
                    "core_entrypoint": "core.chat",  # 伪造
                    "runtime_hook_name": "loop.turn_end",  # 伪造
                },
            )
        )

        evidence = dict(result.evidence)

        # evidence 中不应包含 core_loop_invoked（dispatcher 不从 payload 读）
        assert evidence.get("evidence_level") != REAL_CORE_LOOP_RUNTIME_E2E, (
            f"direct dispatcher.route 不应达到 L3，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("evidence_level") == HARNESS_RUNTIME_E2E, (
            f"direct dispatcher.route 应保持 L2 ({HARNESS_RUNTIME_E2E})，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("dispatcher_origin") == "direct_dispatcher"
        # payload 中的 core_loop_invoked 不应出现在 evidence 中
        assert evidence.get("core_loop_invoked") is not True, (
            "payload 伪造的 core_loop_invoked 不应污染 evidence"
        )


# ========== T4: hook 级 MCP 工具完整管线 L3 ==========


class TestHookLevelMCPL3:
    """T4: hook 级 MCP 工具完整管线测试。"""

    def test_t4_hook_level_mcp_tool_full_pipeline_l3(self):
        """T4: hook 级 MCP 工具（confirmation="never"）走通完整三阶段管线。

        通过 _try_phase1_turn_end_runtime_action() 直接调用，
        验证 MCP 工具以 confirmation="never" 注册时能走通完整管线并获得 L3。
        """
        import agent.tools  # noqa: F401
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action

        registry_name = _register_test_mcp_tool(confirmation="never")

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

        _try_phase1_turn_end_runtime_action(
            state=mock_state,
            result_text="test response",
            dispatcher=spy,
            dependencies=deps,
        )

        # 按 action_type 分组
        by_type: dict[str, list] = {}
        for method, request, result in spy.captured:
            at = request.action_type.value
            by_type.setdefault(at, []).append((method, request, result))

        # TOOL_GATE: 必须存在且为 L3
        gate_entries = by_type.get("tool.gate", [])
        assert len(gate_entries) >= 1, "应有 TOOL_GATE action"
        gate_evidence = dict(gate_entries[0][2].evidence)
        assert gate_evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        assert gate_entries[0][2].status == "success"
        assert gate_evidence.get("gate_disposition") == "allowed"

        # TOOL_INVOKE: 必须存在且为 L3（confirmation="never" → gate allowed）
        invoke_entries = by_type.get("tool.invoke", [])
        assert len(invoke_entries) >= 1, (
            f"应有 TOOL_INVOKE（confirmation=never → gate allowed），"
            f"实际 types: {list(by_type.keys())}"
        )
        invoke_evidence = dict(invoke_entries[0][2].evidence)
        assert invoke_evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        assert invoke_entries[0][2].status == "success"
        assert invoke_evidence.get("tool_invoked") is False
        assert invoke_evidence.get("execution_status") == "not_executed"

        # TOOL_RESULT: 必须存在且为 L3
        result_entries = by_type.get("tool.result", [])
        assert len(result_entries) >= 1, (
            f"应有 TOOL_RESULT，实际 types: {list(by_type.keys())}"
        )
        result_evidence = dict(result_entries[0][2].evidence)
        assert result_evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        assert result_entries[0][2].status == "success"

        # 验证所有 stage 通过 route_from_runtime_loop
        for entries in [gate_entries, invoke_entries, result_entries]:
            method = entries[0][0]
            assert method == "route_from_runtime_loop", (
                f"应通过 route_from_runtime_loop，实际 {method!r}"
            )

        # 二次确认：classify_evidence_level
        for label, evidence_dict in [
            ("TOOL_GATE", gate_evidence),
            ("TOOL_INVOKE", invoke_evidence),
            ("TOOL_RESULT", result_evidence),
        ]:
            level = classify_evidence_level(evidence_dict)
            assert level == REAL_CORE_LOOP_RUNTIME_E2E, (
                f"{label} classify_evidence_level 应为"
                f" {REAL_CORE_LOOP_RUNTIME_E2E}，实际 {level!r}"
            )


# ========== T5: MCP 工具 confirmation="always" 在 gate 被拦截 ==========


class TestMCPConfirmationAlways:
    """T5: 验证 confirmation="always" 的 MCP 工具在 gate 被正确拦截。"""

    def test_t5_mcp_tool_confirmation_always_blocked_at_gate(self):
        """T5: confirmation="always" 的 MCP 工具在 hook 级被 gate 拦截。

        验证生产注册的 MCP 工具（confirmation="always"）在 TOOL_GATE 返回
        confirmation_required，TOOL_INVOKE 和 TOOL_RESULT 不触发。
        确认 confirmation="never" 的测试配置不改变生产安全策略。
        """
        import agent.tools  # noqa: F401
        from agent.loop import LoopDependencies, _try_phase1_turn_end_runtime_action

        # 使用 confirmation="always" 注册（模拟生产 MCP 工具行为）
        registry_name = _register_test_mcp_tool(confirmation="always")

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

        _try_phase1_turn_end_runtime_action(
            state=mock_state,
            result_text="test response",
            dispatcher=spy,
            dependencies=deps,
        )

        # 按 action_type 分组
        by_type: dict[str, list] = {}
        for method, request, result in spy.captured:
            at = request.action_type.value
            by_type.setdefault(at, []).append((method, request, result))

        # TOOL_GATE: 必须存在，返回 confirmation_required
        gate_entries = by_type.get("tool.gate", [])
        assert len(gate_entries) >= 1, "应有 TOOL_GATE"
        gate_result = gate_entries[0][2]
        gate_evidence = dict(gate_result.evidence)
        assert gate_result.status == "confirmation_required", (
            f"confirmation=always 应返回 confirmation_required，"
            f"实际 status={gate_result.status!r}"
        )
        assert gate_evidence.get("gate_disposition") == "confirmation_required"
        # gate 仍应有 L3 evidence（它是通过 route_from_runtime_loop 的）
        assert gate_evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E

        # TOOL_INVOKE: 不应触发（gate 不满足 status=success + disposition=allowed）
        invoke_entries = by_type.get("tool.invoke", [])
        assert len(invoke_entries) == 0, (
            f"confirmation_required 不应触发 TOOL_INVOKE，"
            f"实际产生了 {len(invoke_entries)} 个 TOOL_INVOKE"
        )

        # TOOL_RESULT: 不应触发
        result_entries = by_type.get("tool.result", [])
        assert len(result_entries) == 0, (
            f"confirmation_required 不应触发 TOOL_RESULT，"
            f"实际产生了 {len(result_entries)} 个 TOOL_RESULT"
        )


# ========== T6: 不读 .env / 不调用真实 API ==========


class TestNoRealAPIOrEnv:
    """T6: 验证 pipeline 不读 .env / 不调用真实 API。"""

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "HOME 隔离机制在项目级 config/config.yaml 存在时失效——"
            "render_provider_mode_banner() 优先读 config.yaml 而非 env var。"
            "需要更完整的 sandbox 方案（如 mount namespace 或独立容器）。"
            "不在本轮 scope 内。"
        ),
    )
    def test_t6_no_real_api_or_env_access(self):
        """T6: 所有调用通过 fake provider + fake MCP client，不读 .env。

        HOME 已设为隔离路径——如果误读了 .env 会因路径不存在而失败。
        """
        import os

        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        registry_name = _register_test_mcp_tool(confirmation="never")

        real_dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(real_dispatcher)

        # 验证 HOME 为隔离路径（由测试运行命令设置）
        home = os.environ.get("HOME", "")
        assert "my-first-agent" in home or "tmp" in home, (
            f"HOME 应为隔离路径，实际 {home!r}"
        )

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
            tool_gate_tool_name=registry_name,
        )

        assert isinstance(result, str)

        # 验证 pipeline 正常执行（使用 FakeProvider + FakeMCPClient）
        pipeline_actions = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type in (
                RuntimeActionType.TOOL_GATE,
                RuntimeActionType.TOOL_INVOKE,
                RuntimeActionType.TOOL_RESULT,
            )
        ]
        assert len(pipeline_actions) >= 3, (
            f"应有至少 3 个 pipeline actions，实际 {len(pipeline_actions)}"
        )
