"""MCPBridgeLifecycle RuntimeAction handler — dispatcher-mediated MCP bridge evidence.

Loop 2.4: 将 run_mcp_bridge() 的 lifecycle 纳入 dispatcher evidence，
使 MCP bridge 的 discover/register 阶段不再只是 CLI print 副作用。
"""

from __future__ import annotations

from agent.runtime_integration.dispatcher import RuntimeActionContext
from agent.runtime_integration.schema import RuntimeActionRequest


class MCPBridgeLifecycleHandler:
    """MCP bridge lifecycle 通过 dispatcher 中介，产生 RuntimeAction evidence。

    不重写 run_mcp_bridge 逻辑，只在其外围包裹 dispatcher evidence。
    handler 在 disposable dispatcher 中运行（main.py 启动阶段）。
    """

    def handle(self, request: RuntimeActionRequest, context: RuntimeActionContext):
        payload = dict(request.payload)
        mode = str(payload.get("mode") or "disabled")
        dry_run = bool(payload.get("dry_run", True))
        servers_configured = int(payload.get("servers_configured") or 0)
        servers_evaluated = int(payload.get("servers_evaluated") or 0)
        tools_discovered = int(payload.get("tools_discovered") or 0)
        tools_registered = int(payload.get("tools_registered") or 0)
        overall_decision = str(payload.get("overall_decision") or "blocked")
        errors = tuple(payload.get("errors") or ())

        observed = context.invoke_registered_target(
            target_module="MCPBridgeLifecycle",
            operation="initialize",
            payload={
                "mode": mode,
                "dry_run": dry_run,
                "servers_configured": servers_configured,
                "servers_evaluated": servers_evaluated,
                "tools_discovered": tools_discovered,
                "tools_registered": tools_registered,
            },
        )

        evidence_extra = {
            "mode": mode,
            "dry_run": dry_run,
            "servers_configured": servers_configured,
            "servers_evaluated": servers_evaluated,
            "tools_discovered": tools_discovered,
            "tools_registered": tools_registered,
            "overall_decision": overall_decision,
            "bridge_mediated": True,
            "capability_type": "mcp_bridge_lifecycle",
            "production_capability": True,
        }

        if errors:
            evidence_extra["errors"] = list(errors)

        if tools_registered > 0:
            return context.success(
                handler_name=type(self).__name__,
                target_module="MCPBridgeLifecycle",
                payload={
                    "tools_registered": tools_registered,
                    "mode": mode,
                    "overall_decision": overall_decision,
                },
                observed_call=observed,
                evidence_extra=evidence_extra,
            )

        return context.failed(
            handler_name=type(self).__name__,
            target_module="MCPBridgeLifecycle",
            payload={
                "tools_registered": 0,
                "mode": mode,
                "overall_decision": overall_decision,
            },
            observed_call=observed,
            evidence_extra=evidence_extra,
            error_safe_preview=f"MCP bridge lifecycle: mode={mode}, registered=0",
        )
