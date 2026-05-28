"""Loop 2.4: MCP bridge lifecycle dispatcher mediation contract tests.

验证 MCPBridgeLifecycleHandler 通过 dispatcher 产生 RuntimeAction evidence，
证明 MCP bridge 不再只是 CLI print 副作用。
"""

from agent.runtime_integration.dispatcher import ActionHandlerRegistry, RuntimeActionDispatcher
from agent.runtime_integration.evidence import RuntimeActionModuleObserver
from agent.runtime_integration.mcp_bridge_lifecycle import MCPBridgeLifecycleHandler
from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType


def _build_dispatcher():
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.MCP_BRIDGE_LIFECYCLE, MCPBridgeLifecycleHandler())
    return RuntimeActionDispatcher(registry=registry, observer=RuntimeActionModuleObserver())


# ── Handler behavior ────────────────────────────────────────────────────────────


class TestMCPBridgeLifecycleHandler:
    def test_handler_success_on_registration(self):
        """tools_registered > 0 时 handler 返回 success。"""
        dispatcher = _build_dispatcher()
        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.MCP_BRIDGE_LIFECYCLE,
            source="test.mcp_bridge",
            parent_trace_id="",
            payload={
                "mode": "registration",
                "dry_run": True,
                "servers_configured": 1,
                "servers_evaluated": 1,
                "tools_discovered": 3,
                "tools_registered": 2,
                "overall_decision": "allowed",
            },
        ))
        assert result.status == "success", (
            f"tools_registered=2 时应返回 success，实际 {result.status}"
        )
        evidence = dict(result.evidence)
        assert evidence.get("tools_registered") == 2
        assert evidence.get("bridge_mediated") is True
        assert evidence.get("capability_type") == "mcp_bridge_lifecycle"

    def test_handler_failed_on_no_registration(self):
        """tools_registered == 0 时 handler 返回 failed。"""
        dispatcher = _build_dispatcher()
        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.MCP_BRIDGE_LIFECYCLE,
            source="test.mcp_bridge",
            parent_trace_id="",
            payload={
                "mode": "disabled",
                "dry_run": True,
                "servers_configured": 0,
                "servers_evaluated": 0,
                "tools_discovered": 0,
                "tools_registered": 0,
                "overall_decision": "blocked",
            },
        ))
        assert result.status == "failed", (
            f"tools_registered=0 时应返回 failed，实际 {result.status}"
        )

    def test_handler_evidence_has_mode_and_dry_run(self):
        """handler evidence 包含 mode 和 dry_run 字段。"""
        dispatcher = _build_dispatcher()
        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.MCP_BRIDGE_LIFECYCLE,
            source="test.mcp_bridge",
            parent_trace_id="",
            payload={
                "mode": "discovery",
                "dry_run": False,
                "servers_configured": 1,
                "servers_evaluated": 1,
                "tools_discovered": -1,
                "tools_registered": 0,
                "overall_decision": "dry_run_only",
            },
        ))
        evidence = dict(result.evidence)
        assert evidence.get("mode") == "discovery"
        assert evidence.get("dry_run") is False

    def test_handler_produces_action_log_entry(self):
        """handler 执行后在 dispatcher action_log 中有对应条目。"""
        dispatcher = _build_dispatcher()
        before = len(dispatcher.action_log)
        dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.MCP_BRIDGE_LIFECYCLE,
            source="test.mcp_bridge",
            parent_trace_id="",
            payload={
                "mode": "registration",
                "dry_run": True,
                "servers_configured": 2,
                "servers_evaluated": 2,
                "tools_discovered": 5,
                "tools_registered": 3,
                "overall_decision": "allowed",
            },
        ))
        assert len(dispatcher.action_log) > before, (
            "handler 应在 action_log 中产生条目"
        )


# ── Not fakeable ─────────────────────────────────────────────────────────────────


class TestMCPBridgeLifecycleNotFakeable:
    def test_not_just_print_statement(self):
        """MCP bridge lifecycle 产生 dispatcher evidence，不是只 print 了事。"""
        dispatcher = _build_dispatcher()
        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.MCP_BRIDGE_LIFECYCLE,
            source="test.mcp_bridge",
            parent_trace_id="",
            payload={
                "mode": "registration",
                "dry_run": True,
                "servers_configured": 1,
                "servers_evaluated": 1,
                "tools_discovered": 1,
                "tools_registered": 1,
                "overall_decision": "allowed",
            },
        ))
        evidence = dict(result.evidence)
        # 必须有 dispatcher evidence，不能只是 print
        assert evidence.get("bridge_mediated") is True
        assert evidence.get("production_capability") is True
        assert "target_module_proof" in evidence or result.status == "success", (
            "bridge lifecycle 不能只有 print——必须有 dispatcher evidence"
        )

    def test_no_crash_not_main_path_ready(self):
        """handler 不 crash 不等于 main-path ready。"""
        dispatcher = _build_dispatcher()
        # 空 payload 不会 crash
        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.MCP_BRIDGE_LIFECYCLE,
            source="test.mcp_bridge",
            parent_trace_id="",
            payload={},
        ))
        # 不 crash
        assert result.status in ("success", "failed", "rejected")
        # 但 tools_registered=0 → 不是 main-path ready
        evidence = dict(result.evidence)
        assert evidence.get("tools_registered", 0) == 0, (
            "空 payload 不应声称 tools registered"
        )
