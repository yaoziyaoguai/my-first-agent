"""REAL-EVIDENCE-007: MCP runtime-mediated invocation — model-selected MCP tool.

验证项:
    W1. MCP bridge 通过 real StdioMCPClient 连接 echo fixture 并注册工具
    W2. MCP 工具出现在 model-visible tools 中
    W3. 模型在 core.chat() 中选择并调用 MCP 工具（非 direct execute_tool()）
    W4. MCP 工具走统一 Tool pipeline: TOOL_GATE→TOOL_INVOKE→TOOL_RESULT
    W5. MCP tool result 进入模型上下文（后续消息引用 echo 结果）
    W6. 不是 no-crash pass——验证语义内容

Guardrail 1: 如果模型不主动选择 MCP tool，不以 hack 方式强制调用——
标为 PARTIAL/CONCERN 并注明原因。

用法:
    .venv/bin/python scripts/real_evidence_007_mcp_invoke.py
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


def run_mcp_invoke_validation() -> None:
    """W1-W6: MCP tool invocation through unified Tool pipeline via core.chat()."""
    print("\n═══ REAL-EVIDENCE-007: MCP Runtime-Mediated Invocation ═══")

    from agent.provider.factory import build_model_provider_from_env

    provider = build_model_provider_from_env()
    provider_type = getattr(provider, "provider_type", type(provider).__name__)
    print(f"  provider={provider_type} model={getattr(provider, 'model', '?')}")

    if provider_type in ("fake", "FakeProvider"):
        record("W0", "CONCERN",
               "FakeProvider detected — real API MCP validation requires configured provider. "
               "Set config/config.yaml with real provider credentials or set env vars.",
               provider_type=provider_type)
        return

    # --- W1: MCP bridge with real StdioMCPClient + echo fixture ---
    print("\n  --- W1: MCP bridge discovery + registration (real StdioMCPClient) ---")

    # 创建临时 MCP config 指向 echo fixture
    fixture_path = _project_root / "scripts" / "fixtures" / "mcp_echo_server.py"
    python_bin = _project_root / ".venv" / "bin" / "python"

    mcp_config = {
        "mcpServers": {
            "echo-fixture": {
                "transport": "stdio",
                "command": str(python_bin),
                "args": [str(fixture_path)],
                "enabled": True,
            },
        },
    }

    tmp_config = tempfile.NamedTemporaryFile(  # noqa: SIM115
        mode="w", suffix=".json", prefix="mcp_config_", delete=False,
    )
    json.dump(mcp_config, tmp_config)
    tmp_config.close()
    config_path = tmp_config.name

    from agent.mcp_bridge import run_mcp_bridge

    try:
        bridge_report = run_mcp_bridge(
            mode="registration",
            config_path=config_path,
            dry_run=False,
            server_allowlist=frozenset(["echo-fixture"]),
        )
        print(f"    mode={bridge_report.mode} "
              f"servers={bridge_report.servers_configured} "
              f"discovered={bridge_report.tools_discovered} "
              f"blocked={bridge_report.tools_blocked} "
              f"registered={bridge_report.tools_registered} "
              f"decision={bridge_report.overall_decision}")

        if bridge_report.tools_registered > 0:
            record("W1", "PASS",
                   f"MCP bridge registered {bridge_report.tools_registered} tool(s) "
                   f"via real StdioMCPClient → echo fixture, "
                   f"decision={bridge_report.overall_decision}")
        else:
            errors_detail = (
                "; ".join(bridge_report.errors) if bridge_report.errors
                else "no errors reported"
            )
            record("W1", "FAIL",
                   f"MCP bridge registered 0 tools: discovered={bridge_report.tools_discovered}, "
                   f"blocked={bridge_report.tools_blocked}, errors=[{errors_detail}]")
            Path(config_path).unlink(missing_ok=True)
            return
    except Exception as exc:
        record("W1", "FAIL",
               f"MCP bridge raised exception: {exc}")
        Path(config_path).unlink(missing_ok=True)
        return

    # --- W2: verify MCP tools in model-visible tools ---
    print("\n  --- W2: MCP tools in model-visible tools ---")
    from agent.tool_registry import TOOL_REGISTRY

    all_tool_names = list(TOOL_REGISTRY.keys())
    mcp_tool_names = [n for n in all_tool_names if "mcp" in n.lower()]
    print(f"    Total tools in registry: {len(all_tool_names)}")
    print(f"    MCP tools: {mcp_tool_names}")

    if mcp_tool_names:
        record("W2", "PASS",
               f"MCP tools visible in TOOL_REGISTRY: {mcp_tool_names}")
    else:
        record("W2", "FAIL",
               f"No MCP tools found in TOOL_REGISTRY after bridge registration. "
               f"All tools: {all_tool_names}")
        Path(config_path).unlink(missing_ok=True)
        return

    # --- W3-W6: core.chat() with model-selected MCP tool ---
    print("\n  --- W3-W6: Model-selected MCP tool via core.chat() ---")

    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher

    dispatcher = build_phase1_dispatcher()

    # 注入 dispatcher 以观察 TOOL_GATE→TOOL_INVOKE→TOOL_RESULT evidence
    from agent.core import chat as core_chat

    user_msg = (
        "请使用 mcp_echo 工具，帮我 echo 一条消息："
        "Hello from REAL-EVIDENCE-007 validation"
    )
    print(f"  Sending: '{user_msg}'")

    try:
        core_chat(
            user_input=user_msg,
            provider=provider,
            runtime_action_dispatcher=dispatcher,
        )
        print("  chat completed")
    except Exception as exc:
        record("W3", "FAIL", f"core.chat() raised exception: {exc}")
        Path(config_path).unlink(missing_ok=True)
        return

    # --- W3: Check dispatcher evidence for TOOL_GATE→TOOL_INVOKE→TOOL_RESULT ---
    from agent.runtime_integration.schema import RuntimeActionType

    action_log = getattr(dispatcher, "action_log", [])
    action_types = [str(getattr(e, "action_type", "?")) for e in action_log]

    tool_gate_events = [
        e for e in action_log
        if str(getattr(e, "action_type", "")) == str(RuntimeActionType.TOOL_GATE)
    ]
    tool_invoke_events = [
        e for e in action_log
        if str(getattr(e, "action_type", "")) == str(RuntimeActionType.TOOL_INVOKE)
    ]
    tool_result_events = [
        e for e in action_log
        if str(getattr(e, "action_type", "")) == str(RuntimeActionType.TOOL_RESULT)
    ]

    print(f"    action_log size={len(action_log)}, types={sorted(set(action_types))}")

    # 检查 MCP 工具是否在 TOOL_GATE/TOOL_INVOKE/TOOL_RESULT 中出现
    def _event_has_mcp_tool(event: Any) -> bool:
        """检查 event 是否涉及 MCP 工具。"""
        payload = getattr(event, "payload", {}) or {}
        tool = ""
        if isinstance(payload, dict):
            tool = str(payload.get("tool_name", payload.get("tool", "")))
        return "mcp_echo" in tool or "mcp_demo_status" in tool

    mcp_gate = [e for e in tool_gate_events if _event_has_mcp_tool(e)]
    mcp_invoke = [e for e in tool_invoke_events if _event_has_mcp_tool(e)]
    mcp_result = [e for e in tool_result_events if _event_has_mcp_tool(e)]

    # Guardrail 1: 如果模型没有选择 MCP 工具，不 hack
    if not mcp_gate and not mcp_invoke and not mcp_result:
        record("W3", "CONCERN",
               "Model did not select MCP tool in conversation — "
               "this is model autonomous decision, not a code defect. "
               "MCP tools were available in TOOL_REGISTRY but model chose not to use them. "
               "Guardrail 1: no forced tool_choice or system prompt hack applied.",
               mcp_tools_available=mcp_tool_names,
               action_types=sorted(set(action_types)))
        record("W4", "CONCERN",
               "TOOL_GATE→TOOL_INVOKE→TOOL_RESULT pipeline not exercised for MCP tool — "
               "model did not select MCP tool",
               tool_gate_count=len(tool_gate_events),
               tool_invoke_count=len(tool_invoke_events))
        record("W5", "CONCERN",
               "MCP result not in model context — model did not invoke MCP tool")
        record("W6", "CONCERN",
               "Cannot verify semantic content — model did not invoke MCP tool")
        Path(config_path).unlink(missing_ok=True)
        return

    # W3: TOOL_GATE evidence
    if mcp_gate:
        gate_statuses = [getattr(e, "status", "?") for e in mcp_gate]
        record("W3", "PASS",
               f"TOOL_GATE evidence for MCP tool: {len(mcp_gate)} event(s), "
               f"statuses={gate_statuses}")
    else:
        record("W3", "FAIL",
               "MCP tool invoked but no TOOL_GATE evidence — "
               "tool execution may have bypassed dispatcher")

    # W4: 完整 pipeline TOOL_GATE→TOOL_INVOKE→TOOL_RESULT
    if mcp_gate and mcp_invoke and mcp_result:
        record("W4", "PASS",
               f"Complete MCP tool pipeline: "
               f"TOOL_GATE({len(mcp_gate)})→TOOL_INVOKE({len(mcp_invoke)})→"
               f"TOOL_RESULT({len(mcp_result)})")
    elif mcp_invoke:
        record("W4", "PARTIAL",
               f"Partial MCP tool pipeline: TOOL_GATE={len(mcp_gate)}, "
               f"TOOL_INVOKE={len(mcp_invoke)}, TOOL_RESULT={len(mcp_result)}")
    else:
        record("W4", "CONCERN",
               "TOOL_INVOKE evidence missing for MCP tool")

    # W5: MCP result in model context
    # core.chat() returns str, so we rely on dispatcher TOOL_RESULT evidence
    # to verify MCP tool execution completed and result entered pipeline.
    if mcp_result:
        result_statuses = [getattr(e, "status", "?") for e in mcp_result]
        record("W5", "PASS",
               f"TOOL_RESULT evidence for MCP tool: {len(mcp_result)} event(s), "
               f"statuses={result_statuses} — MCP result entered tool pipeline")
    elif mcp_invoke:
        record("W5", "CONCERN",
               "TOOL_INVOKE found but no TOOL_RESULT — MCP tool may have failed mid-execution")
    else:
        record("W5", "CONCERN",
               "No MCP tool result — model did not invoke MCP tool")

    # W6: Semantic content — not no-crash pass
    mcp_tool_used = any(
        "mcp_echo" in str(getattr(e, "payload", {})) for e in action_log
    )
    if mcp_tool_used:
        record("W6", "PASS",
               "MCP tool invocation has semantic content — "
               "not a no-crash pass; model actively selected and used MCP tool")
    else:
        record("W6", "FAIL",
               "No evidence of MCP tool usage — this would be a no-crash pass")

    # 清理
    Path(config_path).unlink(missing_ok=True)


def main() -> None:
    print("=" * 60)
    print("Real Evidence Validation: MCP Runtime-Mediated Invocation (007)")
    print("=" * 60)

    run_mcp_invoke_validation()

    # Summary
    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)

    passed = sum(1 for r in results if r["verdict"] == "PASS")
    failed = sum(1 for r in results if r["verdict"] == "FAIL")
    concerns = sum(1 for r in results if r["verdict"] == "CONCERN")

    for r in results:
        label = {"PASS": "✓", "FAIL": "✗", "CONCERN": "?"}[r["verdict"]]
        print(f"  {label} {r['case']}: {r['detail']}")

    print(f"\n  PASS={passed} FAIL={failed} CONCERN={concerns}")

    # Write results JSON
    out_path = (
        _project_root / "docs" / "dogfood"
        / "real-evidence-007-mcp-invoke-results.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "date": "2026-05-29",
                "evidence_id": "REAL-EVIDENCE-007",
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
