"""Loop 3.3 — Real MCP External Flight code-path completion contract tests.

证明 MCP external flight 代码语义路径已完整（code path complete），
仅剩真实外部 MCP server 连接验证（REAL-EVIDENCE-007）。

测试分层：
- opt-in activation: 默认不启用，dry_run 与 real flight 语义区分
- config/policy: server_allowlist 生效，destructive tool 执行前 block
- discovery/registration: safe local fixture → TOOL_REGISTRY → model-visible
- invocation main path: ToolRuntimeMediator → TOOL_GATE/INVOKE/RESULT
- dispatcher/decision frame: evidence + mcp_available 动态化
- not-fakeable guards: 不是 SDD-only / bridge-only / dry-run / direct-call / no-crash

架构依据：
- docs/design/mcp-real-external-flight-contract.md
- docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md
"""

from __future__ import annotations

from typing import Any

import pytest

from agent.mcp_models import MCPServerConfig
from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
)
from agent.runtime_integration.evidence import RuntimeActionModuleObserver

# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

_registered_mcp_tool_names: set[str] = set()


@pytest.fixture(autouse=True)
def _cleanup_mcp_tools():
    """每个 test 后清理注册的 MCP 工具。"""
    yield
    from agent.tool_registry import TOOL_REGISTRY

    for name in list(_registered_mcp_tool_names):
        TOOL_REGISTRY.pop(name, None)
    _registered_mcp_tool_names.clear()


@pytest.fixture(autouse=True)
def _reset_bridge_state():
    """每个 test 后重置 bridge module-level state。"""
    yield
    from agent.mcp_bridge import set_mcp_bridge_result

    set_mcp_bridge_result(0)


def _safe_fake_client(
    server_name: str = "demo",
    tools: list[dict[str, Any]] | None = None,
    results: dict[tuple[str, str], Any] | None = None,
):
    """构建安全 local fixture FakeMCPClient，不连接外部 server。"""
    from agent.mcp import FakeMCPClient, MCPCallResult
    from agent.mcp_models import MCPToolDescriptor

    if tools is None:
        tools = [
            {
                "name": "hello",
                "description": "Say hello from MCP server",
                "input_schema": {"type": "object", "properties": {}},
            },
        ]

    descriptors = [
        MCPToolDescriptor(
            server_name=server_name,
            name=t["name"],
            description=t["description"],
            input_schema=t.get("input_schema", {"type": "object", "properties": {}}),
        )
        for t in tools
    ]

    if results is None:
        results = {
            (server_name, t["name"]): MCPCallResult(
                content=f"result from {server_name}/{t['name']}"
            )
            for t in tools
        }

    return FakeMCPClient(
        tools_by_server={server_name: descriptors},
        results_by_call=results,
    )


def _safe_server_config(
    name: str = "demo",
    command: str = "fake-safe-cmd",
    enabled: bool = True,
) -> MCPServerConfig:
    return MCPServerConfig(
        name=name,
        transport="stdio",
        command=command,
        args=("--safe-fixture",),
        enabled=enabled,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level bridge status
# ═══════════════════════════════════════════════════════════════════════════════


class TestBridgeModuleState:
    """set_mcp_bridge_result / is_mcp_active / get_mcp_bridge_tools_registered 的契约。"""

    def test_is_mcp_active_false_by_default(self):
        """默认未运行 bridge 时 is_mcp_active() 返回 False。"""
        from agent.mcp_bridge import is_mcp_active, set_mcp_bridge_result

        set_mcp_bridge_result(0)
        assert not is_mcp_active(), "默认未运行 bridge 时 is_mcp_active() 应为 False"

    def test_is_mcp_active_true_after_registration(self):
        """bridge 注册工具后 is_mcp_active() 返回 True。"""
        from agent.mcp_bridge import is_mcp_active, set_mcp_bridge_result

        set_mcp_bridge_result(3)
        assert is_mcp_active(), "注册 3 个工具后 is_mcp_active() 应为 True"

    def test_get_tools_registered_roundtrip(self):
        """set → get 往返一致。"""
        from agent.mcp_bridge import get_mcp_bridge_tools_registered, set_mcp_bridge_result

        set_mcp_bridge_result(5)
        assert get_mcp_bridge_tools_registered() == 5

    def test_set_zero_resets(self):
        """set(0) 重置状态。"""
        from agent.mcp_bridge import (
            get_mcp_bridge_tools_registered,
            is_mcp_active,
            set_mcp_bridge_result,
        )

        set_mcp_bridge_result(3)
        set_mcp_bridge_result(0)
        assert get_mcp_bridge_tools_registered() == 0
        assert not is_mcp_active()


# ═══════════════════════════════════════════════════════════════════════════════
# Decision frame — dynamic mcp_available
# ═══════════════════════════════════════════════════════════════════════════════


class TestDecisionFrameMCPAvailable:
    """RuntimeDecisionFrame.mcp_available 由 is_mcp_active() 动态驱动。"""

    def test_mcp_available_false_when_bridge_not_run(self):
        """bridge 未运行时 mcp_available=False。"""
        from agent.mcp_bridge import set_mcp_bridge_result
        from agent.runtime_decision_frame import build_decision_frame_from_chat_params

        set_mcp_bridge_result(0)
        frame = build_decision_frame_from_chat_params("test")
        assert not frame.mcp_available, "bridge 未运行时 mcp_available 应为 False"

    def test_mcp_available_true_after_bridge_registration(self):
        """bridge 注册工具后 mcp_available=True。"""
        from agent.mcp_bridge import set_mcp_bridge_result
        from agent.runtime_decision_frame import build_decision_frame_from_chat_params

        set_mcp_bridge_result(2)
        frame = build_decision_frame_from_chat_params("test")
        assert frame.mcp_available, (
            "bridge 注册 2 个工具后 mcp_available 应为 True"
        )

    def test_mcp_available_not_hardcoded(self):
        """mcp_available 不是硬编码常量——bridge 状态改变后跟随变化。"""
        from agent.mcp_bridge import set_mcp_bridge_result
        from agent.runtime_decision_frame import build_decision_frame_from_chat_params

        set_mcp_bridge_result(0)
        frame1 = build_decision_frame_from_chat_params("test")
        assert not frame1.mcp_available

        set_mcp_bridge_result(1)
        frame2 = build_decision_frame_from_chat_params("test")
        assert frame2.mcp_available, (
            "mcp_available 不应硬编码——bridge 状态改变后应跟随变化"
        )

    def test_chat_decision_frame_mcp_not_available_by_default(self):
        """默认 chat 路径 MCP 应标不可用（未 opt-in）。"""
        import agent.core as core
        from agent.runtime_decision_frame import get_last_decision_frame

        core.state.reset_task()
        core.chat("test mcp default")
        frame = get_last_decision_frame()
        assert frame is not None
        assert not frame.mcp_available, (
            "默认 chat MCP 不可用——需显式 opt-in MY_FIRST_AGENT_MCP_ENABLE=1"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Registration path — FakeMCPClient → TOOL_REGISTRY → model-visible tools
# ═══════════════════════════════════════════════════════════════════════════════


class TestMCPRegistrationPath:
    """MCP tool 通过 register_mcp_tools() 注册进 TOOL_REGISTRY 并进入 model-visible。"""

    def test_register_mcp_tools_adds_to_registry(self):
        """register_mcp_tools 将 tools 加入 TOOL_REGISTRY。"""
        from agent.mcp import register_mcp_tools
        from agent.tool_registry import TOOL_REGISTRY

        server = _safe_server_config("demo")
        client = _safe_fake_client("demo")

        registered = register_mcp_tools(
            [server],
            client,
            server_allowlist=frozenset({"demo"}),
            dry_run=True,
        )
        _registered_mcp_tool_names.update(registered)

        assert len(registered) >= 1, "应至少注册 1 个 MCP tool"
        registry_name = "mcp__demo__hello"
        assert registry_name in TOOL_REGISTRY, (
            f"{registry_name} 应在 TOOL_REGISTRY 中"
        )

    def test_registered_mcp_tool_in_model_visible(self):
        """注册的 MCP tool 出现在 model-visible tools 中。"""
        from agent.mcp import register_mcp_tools
        from agent.tool_registry import get_model_visible_tools, set_model_visible_tool_limits

        set_model_visible_tool_limits(max_mcp=50, max_total=200)

        server = _safe_server_config("demo")
        client = _safe_fake_client("demo")

        registered = register_mcp_tools(
            [server],
            client,
            server_allowlist=frozenset({"demo"}),
            dry_run=True,
        )
        _registered_mcp_tool_names.update(registered)

        visible = get_model_visible_tools()
        visible_names = [t["name"] for t in visible]
        assert "mcp__demo__hello" in visible_names, (
            f"注册的 MCP tool 应在 model-visible tools 中，实际: {visible_names}"
        )

    def test_registered_mcp_tool_has_correct_metadata(self):
        """注册的 MCP tool 有正确的 capability/confirmation/risk 元数据。"""
        from agent.mcp import register_mcp_tools
        from agent.tool_registry import TOOL_REGISTRY

        server = _safe_server_config("demo")
        client = _safe_fake_client("demo")

        registered = register_mcp_tools(
            [server],
            client,
            server_allowlist=frozenset({"demo"}),
            dry_run=True,
        )
        _registered_mcp_tool_names.update(registered)

        tool = TOOL_REGISTRY["mcp__demo__hello"]
        assert tool["capability"] == "mcp_tool", (
            f"MCP tool capability 应为 mcp_tool，实际 {tool['capability']!r}"
        )
        assert tool["confirmation"] == "always", (
            f"MCP tool 默认 confirmation=always，实际 {tool['confirmation']!r}"
        )
        assert tool["risk_level"] == "high", (
            f"MCP tool 默认 risk_level=high，实际 {tool['risk_level']!r}"
        )

    def test_multiple_tools_registered(self):
        """多个 tools 从同一 server 注册。"""
        from agent.mcp import register_mcp_tools

        server = _safe_server_config("multi")
        client = _safe_fake_client("multi", tools=[
            {"name": "tool_a", "description": "Tool A"},
            {"name": "tool_b", "description": "Tool B"},
            {"name": "tool_c", "description": "Tool C"},
        ])

        registered = register_mcp_tools(
            [server], client, server_allowlist=frozenset({"multi"}), dry_run=True,
        )
        _registered_mcp_tool_names.update(registered)

        assert len(registered) == 3, f"应注册 3 个 tools，实际 {len(registered)}"


# ═══════════════════════════════════════════════════════════════════════════════
# Policy enforcement
# ═══════════════════════════════════════════════════════════════════════════════


class TestMCPServerAllowlist:
    """server_allowlist 在 register_mcp_tools 中生效。"""

    def test_allowlisted_server_registers_tools(self):
        """在 allowlist 中的 server 可以注册 tools。"""
        from agent.mcp import register_mcp_tools

        server = _safe_server_config("allowlisted")
        client = _safe_fake_client("allowlisted")

        registered = register_mcp_tools(
            [server],
            client,
            server_allowlist=frozenset({"allowlisted"}),
            dry_run=True,
        )
        _registered_mcp_tool_names.update(registered)

        assert len(registered) >= 1, (
            "allowlisted server 应能注册 tools"
        )

    def test_non_allowlisted_server_blocked(self):
        """不在 allowlist 中的 server 被 block，tools 不注册。"""
        from agent.mcp import register_mcp_tools

        server = _safe_server_config("not_allowed")
        client = _safe_fake_client("not_allowed")

        registered = register_mcp_tools(
            [server],
            client,
            server_allowlist=frozenset({"only_this_one"}),
            dry_run=True,
        )
        _registered_mcp_tool_names.update(registered)

        assert len(registered) == 0, (
            "不在 allowlist 中的 server 不应注册任何 tool"
        )

    def test_none_allowlist_blocks_all_servers(self):
        """None allowlist（未配置）→ 所有 server 被 block —— secure default。"""
        from agent.mcp import register_mcp_tools

        server = _safe_server_config("any_server")
        client = _safe_fake_client("any_server")

        registered = register_mcp_tools(
            [server],
            client,
            server_allowlist=None,
            dry_run=True,
        )
        _registered_mcp_tool_names.update(registered)

        assert len(registered) == 0, (
            "None allowlist（未配置）应 block 所有 server —— secure default"
        )


class TestMCPDestructiveToolBlock:
    """destructive tool name 在 policy 层被执行前 block。"""

    def test_destructive_tool_not_registered(self):
        """名字匹配 destructive pattern 的 tool 不会注册到 TOOL_REGISTRY。"""
        from agent.mcp import register_mcp_tools
        from agent.tool_registry import TOOL_REGISTRY

        server = _safe_server_config("bad_server")
        client = _safe_fake_client("bad_server", tools=[
            {"name": "write_file", "description": "Write a file to disk"},
        ])

        registered = register_mcp_tools(
            [server], client,
            server_allowlist=frozenset({"bad_server"}),
            dry_run=True,
        )
        _registered_mcp_tool_names.update(registered)

        registry_name = "mcp__bad_server__write_file"
        assert registry_name not in TOOL_REGISTRY, (
            f"destructive tool {registry_name} 不应在 TOOL_REGISTRY 中"
        )
        assert len(registered) == 0, (
            "destructive tool 不应被注册"
        )

    def test_normal_tool_not_blocked_by_destructive_check(self):
        """非 destructive tool 不被误伤。"""
        from agent.mcp import register_mcp_tools
        from agent.tool_registry import TOOL_REGISTRY

        server = _safe_server_config("safe_server")
        client = _safe_fake_client("safe_server", tools=[
            {"name": "query_data", "description": "Query data safely"},
        ])

        registered = register_mcp_tools(
            [server], client,
            server_allowlist=frozenset({"safe_server"}),
            dry_run=True,
        )
        _registered_mcp_tool_names.update(registered)

        registry_name = "mcp__safe_server__query_data"
        assert registry_name in TOOL_REGISTRY, (
            f"非 destructive tool {registry_name} 应在 TOOL_REGISTRY 中"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Invocation main path — ToolRuntimeMediator + TOOL_GATE/INVOKE/RESULT
# ═══════════════════════════════════════════════════════════════════════════════


class TestMCPInvocationMainPath:
    """MCP tool invocation 复用统一 Tool pipeline。"""

    def test_mcp_tool_goes_through_gate_invoke_result(self, monkeypatch):
        """MCP tool 经过 TOOL_GATE → invoke_started evidence → TOOL_RESULT。"""
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider
        from agent.runtime_integration.tool_gate import ToolGateHandler
        from agent.runtime_integration.tool_invoke import ToolInvokeHandler
        from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler
        from agent.tool_registry import set_model_visible_tool_limits

        set_model_visible_tool_limits(max_mcp=50, max_total=200)

        # 注册测试 MCP tool（confirmation="never" 允许 gate 通过）
        registry_name = _register_test_mcp_tool_direct("demo", "hello", confirmation="never")
        invoke_started_events: list[dict[str, Any]] = []

        def _capture_record_evidence(**kwargs):
            if kwargs.get("operation") == "invoke_started":
                invoke_started_events.append(kwargs)
            return {"data": kwargs}

        monkeypatch.setattr(
            "agent.evidence_recorder.record_evidence",
            _capture_record_evidence,
        )

        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
        registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver(),
        )

        # spy dispatcher 捕获 pipeline 调用
        captured: list[tuple[str, Any]] = []

        class _SpyDispatcher:
            def __init__(self, real):
                self._real = real

            def route_from_runtime_loop(self, request, **kwargs: object):
                result = self._real.route_from_runtime_loop(request)
                captured.append(("route_from_runtime_loop", request, result))
                return result

            @property
            def action_log(self):
                return self._real.action_log

        spy = _SpyDispatcher(dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
            tool_gate_tool_name=registry_name,
        )
        assert isinstance(result, str)

        action_types = [
            r.action_type.value for _, r, _ in captured
            if r.action_type in (
                RuntimeActionType.TOOL_GATE,
                RuntimeActionType.TOOL_INVOKE,
                RuntimeActionType.TOOL_RESULT,
            )
        ]
        assert "tool.gate" in action_types, f"应有 TOOL_GATE，实际: {action_types}"
        assert "tool.result" in action_types, f"应有 TOOL_RESULT，实际: {action_types}"
        assert invoke_started_events, "应记录 invoke_started evidence"
        assert any(
            e.get("metadata", {}).get("tool_name") == registry_name
            for e in invoke_started_events
        ), f"invoke_started evidence 应包含 MCP tool={registry_name}"

        # 新语义：真实执行由 mediator → tool_executor 完成；TOOL_INVOKE 不再
        # 作为 dispatcher 执行入口参与顺序断言。只验证主路径 gate 在 result 前。
        gate_idx = action_types.index("tool.gate")
        result_idx = action_types.index("tool.result")
        assert gate_idx < result_idx, (
            f"顺序应为 GATE<RESULT，实际 GATE={gate_idx} RESULT={result_idx}"
        )

    def test_mcp_tool_with_confirmation_always_blocked_at_gate(self):
        """confirmation='always' 的 MCP tool 在 gate 被拦截——不进 execute_single_tool。"""
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider
        from agent.runtime_integration.tool_gate import ToolGateHandler
        from agent.runtime_integration.tool_invoke import ToolInvokeHandler
        from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler
        from agent.tool_registry import set_model_visible_tool_limits

        set_model_visible_tool_limits(max_mcp=50, max_total=200)

        # 使用 confirmation="always"（生产行为）
        registry_name = _register_test_mcp_tool_direct("demo", "hello", confirmation="always")

        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
        registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver(),
        )

        captured: list[tuple[str, Any]] = []

        class _SpyDispatcher:
            def __init__(self, real):
                self._real = real

            def route_from_runtime_loop(self, request, **kwargs: object):
                result = self._real.route_from_runtime_loop(request)
                captured.append(("route_from_runtime_loop", request, result))
                return result

            @property
            def action_log(self):
                return self._real.action_log

        spy = _SpyDispatcher(dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
            tool_gate_tool_name=registry_name,
        )
        assert isinstance(result, str)

        invoke_entries = [
            (r, res) for _, r, res in captured
            if r.action_type == RuntimeActionType.TOOL_INVOKE
        ]
        assert len(invoke_entries) == 0, (
            f"confirmation=always 不应触发 TOOL_INVOKE，实际 {len(invoke_entries)} 个"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Not-fakeable guards
# ═══════════════════════════════════════════════════════════════════════════════


class TestMCPNotFakeable:
    """Loop 3.3 code-path completion 不是 SDD-only / bridge-only / dry-run / no-crash。"""

    def test_not_sdd_only__code_changed(self):
        """代码确实被修改（不只是 SDD 文档）——module-level bridge state 新增。"""
        from agent.mcp_bridge import (
            get_mcp_bridge_tools_registered,
            is_mcp_active,
            set_mcp_bridge_result,
        )
        # 三个函数必须可调用且来自 mcp_bridge
        set_mcp_bridge_result(1)
        assert is_mcp_active()
        assert get_mcp_bridge_tools_registered() == 1

    def test_not_bridge_lifecycle_only__registration_path_exists(self):
        """不只是 bridge lifecycle evidence——registration path 有代码实现。"""
        from agent.mcp import register_mcp_tools

        server = _safe_server_config("reg_test")
        client = _safe_fake_client("reg_test")
        registered = register_mcp_tools(
            [server], client, server_allowlist=frozenset({"reg_test"}), dry_run=True,
        )
        _registered_mcp_tool_names.update(registered)
        assert len(registered) >= 1, (
            "register_mcp_tools 应注册 tool——不只是 bridge lifecycle evidence"
        )

    def test_not_dry_run_only__registration_with_real_semantics(self):
        """dry_run=True 时不连接 real server 但仍执行完整 registration 语义。"""
        from agent.mcp import register_mcp_tools
        from agent.tool_registry import TOOL_REGISTRY

        server = _safe_server_config("test_dry")
        client = _safe_fake_client("test_dry", tools=[
            {"name": "data_query", "description": "Query data"},
        ])
        registered = register_mcp_tools(
            [server], client, server_allowlist=frozenset({"test_dry"}), dry_run=True,
        )
        _registered_mcp_tool_names.update(registered)

        # dry_run=True 不应阻止 registration——只阻止连接真实 server
        registry_name = "mcp__test_dry__data_query"
        assert registry_name in TOOL_REGISTRY, (
            f"{registry_name} 应在 TOOL_REGISTRY 中（dry_run 只影响 client 类型）"
        )

    def test_not_direct_call_only__goes_through_tool_pipeline(self):
        """MCP tool 不只 direct call——经过 ToolRuntimeMediator pipeline。"""
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider
        from agent.runtime_integration.tool_gate import ToolGateHandler
        from agent.runtime_integration.tool_invoke import ToolInvokeHandler
        from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler
        from agent.tool_registry import set_model_visible_tool_limits

        set_model_visible_tool_limits(max_mcp=50, max_total=200)
        registry_name = _register_test_mcp_tool_direct("pipe", "test", confirmation="never")

        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
        registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver(),
        )

        pipeline_triggered = []

        class _Spy:
            def __init__(self, real):
                self._real = real

            def route_from_runtime_loop(self, request, **kwargs: object):
                result = self._real.route_from_runtime_loop(request)
                if request.action_type in (
                    RuntimeActionType.TOOL_GATE,
                    RuntimeActionType.TOOL_RESULT,
                ):
                    pipeline_triggered.append(True)
                return result

            @property
            def action_log(self):
                return self._real.action_log

        spy = _Spy(dispatcher)
        chat("hello", provider=FakeProvider(), runtime_action_dispatcher=spy,
            tool_gate_tool_name=registry_name)

        assert len(pipeline_triggered) >= 2, (
            "MCP tool 应经过 ToolRuntimeMediator 的 gate/result pipeline，"
            "不是 direct-call-only"
        )

    def test_not_no_crash__has_business_assertions(self):
        """不 crash 不等于 code path complete——有正向业务断言。"""
        from agent.mcp import register_mcp_tools
        from agent.tool_registry import TOOL_REGISTRY

        server = _safe_server_config("biz_test")
        client = _safe_fake_client("biz_test", tools=[
            {"name": "query", "description": "Business query tool"},
        ])

        registered = register_mcp_tools(
            [server], client, server_allowlist=frozenset({"biz_test"}), dry_run=True,
        )
        _registered_mcp_tool_names.update(registered)

        # 正向断言：tool 被注册 + 元数据正确
        assert len(registered) == 1
        tool = TOOL_REGISTRY["mcp__biz_test__query"]
        assert tool["capability"] == "mcp_tool"
        assert tool["confirmation"] == "always"
        # 不是 no-crash——有一系列业务语义断言
        assert tool["description"] and len(tool["description"]) > 0

    def test_mcp_available_is_dynamic_not_hardcoded(self):
        """mcp_available 由 is_mcp_active() 动态驱动，不是硬编码常量。"""
        from agent.mcp_bridge import set_mcp_bridge_result
        from agent.runtime_decision_frame import build_decision_frame_from_chat_params

        # Scenario 1: bridge 未运行
        set_mcp_bridge_result(0)
        f1 = build_decision_frame_from_chat_params("s1")
        assert not f1.mcp_available

        # Scenario 2: bridge 运行并注册工具
        set_mcp_bridge_result(5)
        f2 = build_decision_frame_from_chat_params("s2")
        assert f2.mcp_available

        # Scenario 3: bridge 运行但 0 工具
        set_mcp_bridge_result(0)
        f3 = build_decision_frame_from_chat_params("s3")
        assert not f3.mcp_available

        # 证明是动态的——三个场景三种不同结果
        assert f1.mcp_available != f2.mcp_available, (
            "mcp_available 应随 bridge 状态变化，不是硬编码常量"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Decision frame — branch point status
# ═══════════════════════════════════════════════════════════════════════════════


class TestMCPBranchPointStatus:
    """mcp.discover / mcp.invoke branch points 状态诚实。"""

    def test_mcp_discover_is_partial_not_ready(self):
        """mcp.discover 标 PARTIAL——code path complete, real validation pending。"""
        from agent.runtime_decision_frame import BranchPointStatus, get_branch_point

        bp = get_branch_point("mcp.discover")
        assert bp is not None
        assert bp.status == BranchPointStatus.PARTIAL, (
            f"mcp.discover 应为 PARTIAL，实际 {bp.status}"
        )
        assert not bp.is_capability_complete(), (
            "mcp.discover 不应标 capability complete——缺 real server 验证"
        )
        assert "REAL-EVIDENCE-007" in str(bp.decision_meta.get("why_partial", "")), (
            "mcp.discover 的 why_partial 必须引用 REAL-EVIDENCE-007"
        )

    def test_mcp_invoke_is_partial_not_ready(self):
        """mcp.invoke 标 PARTIAL——code path complete, real validation pending。"""
        from agent.runtime_decision_frame import BranchPointStatus, get_branch_point

        bp = get_branch_point("mcp.invoke")
        assert bp is not None
        assert bp.status == BranchPointStatus.PARTIAL, (
            f"mcp.invoke 应为 PARTIAL，实际 {bp.status}"
        )
        assert not bp.is_capability_complete(), (
            "mcp.invoke 不应标 capability complete——缺 real server 验证"
        )
        assert "REAL-EVIDENCE-007" in str(bp.decision_meta.get("why_partial", "")), (
            "mcp.invoke 的 why_partial 必须引用 REAL-EVIDENCE-007"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Opt-in activation
# ═══════════════════════════════════════════════════════════════════════════════


class TestMCPOptInActivation:
    """默认不启用 external MCP flight；需显式 opt-in。"""

    def test_default_state_mcp_not_active(self):
        """模块初始状态 is_mcp_active()=False。"""
        from agent.mcp_bridge import is_mcp_active

        assert not is_mcp_active(), (
            "默认 is_mcp_active() 应为 False——需显式 opt-in"
        )

    def test_dry_run_does_not_imply_real_connection(self):
        """dry_run=True 的 registration 不连接真实 server。"""
        from agent.mcp import register_mcp_tools
        from agent.tool_registry import TOOL_REGISTRY

        server = _safe_server_config("dry_test")
        client = _safe_fake_client("dry_test")

        # dry_run=True 用 FakeMCPClient——不启动 stdio 进程
        registered = register_mcp_tools(
            [server], client, server_allowlist=frozenset({"dry_test"}), dry_run=True,
        )
        _registered_mcp_tool_names.update(registered)

        # 验证 tool 注册成功（但来自 safe fixture，不是 real server）
        assert "mcp__dry_test__hello" in TOOL_REGISTRY

    def test_mcp_register_preserves_confirmation_always(self):
        """MCP tool 的 confirmation='always' 不被测试 hack 掩盖。"""
        from agent.mcp import register_mcp_tools
        from agent.tool_registry import TOOL_REGISTRY

        server = _safe_server_config("confirm_test")
        client = _safe_fake_client("confirm_test")

        registered = register_mcp_tools(
            [server], client, server_allowlist=frozenset({"confirm_test"}), dry_run=True,
        )
        _registered_mcp_tool_names.update(registered)

        tool = TOOL_REGISTRY["mcp__confirm_test__hello"]
        assert tool["confirmation"] == "always", (
            f"MCP tool confirmation 应为 'always'（不被测试 hack 掩盖），"
            f"实际 {tool['confirmation']!r}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _register_test_mcp_tool_direct(
    server_name: str = "demo",
    tool_name: str = "hello",
    *,
    confirmation: str = "never",
) -> str:
    """通过 register_tool() 直接注册测试 MCP tool（不经过 register_mcp_tools）。"""
    from agent.mcp import FakeMCPClient, MCPCallResult
    from agent.mcp_models import MCPServerConfig, MCPToolDescriptor
    from agent.tool_registry import TOOL_REGISTRY, register_tool, set_model_visible_tool_limits

    set_model_visible_tool_limits(max_mcp=50, max_total=200)

    registry_name = f"mcp__{server_name}__{tool_name}"
    if registry_name in TOOL_REGISTRY:
        return registry_name

    server = MCPServerConfig(
        name=server_name, transport="stdio", command="fake-cmd", enabled=True,
    )
    descriptor = MCPToolDescriptor(
        server_name=server_name,
        name=tool_name,
        description=f"MCP test tool: {server_name}/{tool_name}",
        input_schema={"type": "object", "properties": {}},
    )
    call_result = MCPCallResult(content=f"result from {server_name}/{tool_name}")
    client = FakeMCPClient(
        tools_by_server={server_name: [descriptor]},
        results_by_call={(server_name, tool_name): call_result},
    )

    def _call_mcp_tool(tool_input=None):
        result = client.call_tool(server, descriptor.name, tool_input or {})
        return result.to_legacy_tool_result(
            server_name=server.name, tool_name=descriptor.name,
        )

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
