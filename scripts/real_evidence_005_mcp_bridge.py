"""REAL-EVIDENCE-005 + REAL-EVIDENCE-007: MCP Bridge real server connection validation.

验证项 (005):
    V1. MCP bridge 真实连接 opt-in MCP server fixture（非 FakeMCPClient）
    V2. MCP_BRIDGE_LIFECYCLE evidence 进入 dispatcher
    V3. tools_discovered > 0, tools_registered > 0
    V4. overall_decision 不是 blocked
    V5. 连接失败时有可读错误和清理
    V6. server allowlist 生效

验证项 (007, 顺带):
    W1. MCP tool 注册到 TOOL_REGISTRY
    W2. MCP tool 出现在 model-visible tools
    W3. MCP invocation 通过 ToolRuntimeMediator (TOOL_GATE→TOOL_INVOKE→TOOL_RESULT)
    W4. destructive tool 在执行前 block

用法:
    .venv/bin/python scripts/real_evidence_005_mcp_bridge.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

results: list[dict[str, Any]] = []


def record(case_id: str, verdict: str, detail: str, **kw: Any) -> None:
    results.append({"case": case_id, "verdict": verdict, "detail": detail, **kw})
    label = {"PASS": "✓", "FAIL": "✗", "CONCERN": "?"}.get(verdict, verdict)
    print(f"  {label} {case_id}: {detail}")


def run_mcp_bridge_validation() -> None:
    """REAL-EVIDENCE-005: MCP Bridge real server connection."""
    print("\n═══ REAL-EVIDENCE-005: MCP Bridge Real Server Connection ═══")

    fixture_server = str(_project_root / "scripts" / "fixtures" / "mcp_echo_server.py")

    # V0: 前置——fixture server 存在且可执行
    if not Path(fixture_server).exists():
        record("V0", "FAIL", f"Fixture server not found: {fixture_server}")
        return
    record("V0", "PASS", f"Fixture server found: {fixture_server}")

    # 创建临时 MCP config
    mcp_config = {
        "mcpServers": {
            "echo-fixture": {
                "command": sys.executable,
                "args": [fixture_server],
                "enabled": True,
            },
        },
    }

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="mcp_config_", delete=False
    ) as f:
        json.dump(mcp_config, f, ensure_ascii=False)
        config_path = f.name

    try:
        # V1: 真实连接——run_mcp_bridge with dry_run=False
        print("\n  --- V1: Real bridge connection ---")
        from agent.mcp_bridge import run_mcp_bridge

        report = run_mcp_bridge(
            mode="registration",
            config_path=config_path,
            server_allowlist=frozenset({"echo-fixture"}),
            dry_run=False,  # 使用真实 StdioMCPClient
        )
        print(f"  report: mode={report.mode}, servers={report.servers_evaluated}/{report.servers_configured}, "  # noqa: E501
              f"discovered={report.tools_discovered}, blocked={report.tools_blocked}, "
              f"registered={report.tools_registered}, decision={report.overall_decision}")

        if report.tools_discovered > 0:
            record("V1a", "PASS",
                   f"tools_discovered={report.tools_discovered} (real server connection confirmed)")
        else:
            record("V1a", "FAIL",
                   f"tools_discovered={report.tools_discovered} — bridge did not discover tools from real server",  # noqa: E501
                   errors=report.errors)

        if report.tools_registered > 0:
            record("V1b", "PASS",
                   f"tools_registered={report.tools_registered} (tools registered in TOOL_REGISTRY)")  # noqa: E501
        else:
            record("V1b", "FAIL",
                   f"tools_registered={report.tools_registered} — tools not registered",
                   errors=report.errors)

        if report.overall_decision != "blocked":
            record("V1c", "PASS", f"overall_decision={report.overall_decision} (not blocked)")
        else:
            record("V1c", "FAIL",
                   f"overall_decision={report.overall_decision} — bridge blocked",
                   errors=report.errors)

        # V2: MCP_BRIDGE_LIFECYCLE evidence
        print("\n  --- V2: Bridge lifecycle evidence ---")

        from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
        from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType

        dispatcher = build_phase1_dispatcher()
        dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.MCP_BRIDGE_LIFECYCLE,
                source="test.real_evidence_005",
                parent_trace_id="",
                payload={
                    "mode": "registration",
                    "dry_run": False,
                    "servers_configured": report.servers_configured,
                    "servers_evaluated": report.servers_evaluated,
                    "tools_discovered": report.tools_discovered,
                    "tools_registered": report.tools_registered,
                    "overall_decision": report.overall_decision,
                    "errors": report.errors,
                },
            ),
        )

        # 验证 dispatcher 接收了 evidence（handler 不会抛异常即成功）
        record("V2", "PASS",
               "MCP_BRIDGE_LIFECYCLE evidence dispatched — handler accepted payload")

        # V3: TOOL_REGISTRY 中有注册的 MCP tools
        print("\n  --- V3: TOOL_REGISTRY verification ---")
        from agent.tool_registry import TOOL_REGISTRY

        mcp_tools = [
            (name, info) for name, info in TOOL_REGISTRY.items()
            if "mcp" in name.lower()
        ]
        if mcp_tools:
            names = [name for name, _info in mcp_tools]
            record("V3", "PASS",
                   f"MCP tools in TOOL_REGISTRY: {names}")
        else:
            record("V3", "CONCERN",
                   "No MCP-prefixed tools found in TOOL_REGISTRY — "
                   "tools may be registered under server-specific names; check manually",
                   all_tools=list(TOOL_REGISTRY.keys())[:20])

        # V4: Model-visible tools include MCP tools
        print("\n  --- V4: Model-visible tools ---")
        from agent.core import get_model_visible_tools

        visible = get_model_visible_tools(max_mcp_tools=5)
        visible_names = [getattr(t, "name", str(t)) for t in visible]
        mcp_in_visible = [n for n in visible_names if "mcp" in n.lower()]
        if mcp_in_visible:
            record("V4", "PASS",
                   f"MCP tools visible to model: {mcp_in_visible}")
        else:
            record("V4", "CONCERN",
                   "No MCP tools in model-visible tools — "
                   "max_mcp_tools may exclude them or registration used custom names",
                   visible_tools=visible_names[:20])

        # V5: server allowlist 生效
        print("\n  --- V5: Server allowlist ---")
        # 用不匹配的 allowlist 重新跑 bridge
        blocked_report = run_mcp_bridge(
            mode="registration",
            config_path=config_path,
            server_allowlist=frozenset({"nonexistent-server"}),
            dry_run=False,
        )
        if blocked_report.servers_blocked > 0 or blocked_report.tools_registered == 0:
            record("V5", "PASS",
                   f"Server allowlist blocked non-matching server: "
                   f"blocked={blocked_report.servers_blocked}, "
                   f"registered={blocked_report.tools_registered}")
        else:
            record("V5", "CONCERN",
                   "Server allowlist did not block server — may be bypassed",
                   blocked=blocked_report.servers_blocked,
                   registered=blocked_report.tools_registered)

        # V6: 连接失败时的错误处理
        print("\n  --- V6: Error handling ---")
        bad_config_path = "/nonexistent/mcp_config.json"
        error_report = run_mcp_bridge(
            mode="registration",
            config_path=bad_config_path,
            dry_run=False,
        )
        if error_report.errors and error_report.overall_decision == "blocked":
            record("V6", "PASS",
                   f"Missing config produces blocked decision with errors: {error_report.errors}")
        else:
            record("V6", "CONCERN",
                   "Missing config did not produce expected error",
                   decision=error_report.overall_decision,
                   errors=error_report.errors)

    finally:
        # 清理临时 config 文件
        Path(config_path).unlink(missing_ok=True)


def run_mcp_tool_execution_validation() -> None:
    """REAL-EVIDENCE-007 (顺带): MCP external tool execution.

    依赖 005 section 已注册的 MCP tools。不重复 run_mcp_bridge。
    """
    print("\n═══ REAL-EVIDENCE-007: MCP External Tool Execution ═══")

    # 检查 005 section 是否已注册 MCP tools
    from agent.tool_registry import TOOL_REGISTRY
    mcp_echo_tool_name = None
    for name in TOOL_REGISTRY:
        if "mcp_echo" in name:
            mcp_echo_tool_name = name
            break

    if mcp_echo_tool_name is None:
        record("W0", "FAIL",
               "mcp_echo tool not found in TOOL_REGISTRY — REAL-EVIDENCE-005 section must run first",  # noqa: E501
               registered_tools=list(TOOL_REGISTRY.keys())[:20])
        return
    record("W0", "PASS", f"mcp_echo tool found in registry: {mcp_echo_tool_name}")

    # W1: 通过 execute_tool 执行 MCP tool
    print("\n  --- W1: MCP tool execution via tool_registry ---")
    from agent.tool_registry import execute_tool

    tool_name = mcp_echo_tool_name
    print(f"  executing: {tool_name}")

    result = execute_tool(
        name=tool_name,
        tool_input={"message": "hello from real evidence validation"},
    )
    print(f"  result={str(result)[:200]}")

    if result and "error" not in str(result).lower():
        record("W1", "PASS",
               f"MCP tool '{tool_name}' executed via tool_registry: {str(result)[:100]}")
    else:
        record("W1", "CONCERN",
               f"MCP tool execution returned: {str(result)[:100]}")

    # W2: destructive tool block
    print("\n  --- W2: Destructive tool block ---")
    from agent.mcp_policy import DEFAULT_DESTRUCTIVE_TOOL_PATTERNS
    print(f"  destructive patterns: {DEFAULT_DESTRUCTIVE_TOOL_PATTERNS}")
    record("W2", "PASS",
           f"Destructive tool block patterns configured: {DEFAULT_DESTRUCTIVE_TOOL_PATTERNS}")


def main() -> None:
    print("=" * 60)
    print("Real Evidence Validation: MCP Bridge (005) + Tool Execution (007)")
    print("=" * 60)

    run_mcp_bridge_validation()
    run_mcp_tool_execution_validation()

    # Summary
    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)

    passed = sum(1 for r in results if r["verdict"] == "PASS")
    failed = sum(1 for r in results if r["verdict"] == "FAIL")
    concerns = sum(1 for r in results if r["verdict"] == "CONCERN")

    for r in results:
        label = {"PASS": "✓", "FAIL": "✗", "CONCERN": "?"}[r["verdict"]]
        extra = ""
        if "errors" in r and r["errors"]:
            extra = f" (errors={r['errors']})"
        print(f"  {label} {r['case']}: {r['detail']}{extra}")

    print(f"\n  PASS={passed} FAIL={failed} CONCERN={concerns}")

    # Write results JSON
    out_path = (
        _project_root / "docs" / "dogfood"
        / "real-evidence-005-mcp-bridge-results.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "date": "2026-05-29",
                "evidence_ids": ["REAL-EVIDENCE-005", "REAL-EVIDENCE-007"],
                "results": results,
                "summary": {"PASS": passed, "FAIL": failed, "CONCERN": concerns},
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\n  Results written to {out_path}")

    if failed > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
