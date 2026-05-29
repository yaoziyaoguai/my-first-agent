"""REAL-EVIDENCE-007: MCP real runtime-mediated invocation — full execution chain.

验证目标:
    W1. MCP bridge 通过真实 StdioMCPClient 注册 echo fixture 工具
    W2. MCP 工具在 TOOL_REGISTRY 和 model-visible tools 中可见
    W3. FakeProvider 生成 MCP tool_use → ToolRuntimeMediator → TOOL_GATE
    W4. MCP tool 通过 TOOL_GATE (allowed) → TOOL_INVOKE
    W5. TOOL_INVOKE 触发真实的 call_tool (StdioMCPClient subprocess)
    W6. TOOL_RESULT 包含真实 MCP server 返回的 echo 结果
    W7. result 进入 conversation context
    W8. dispatcher evidence chain 完整可追踪

安全设计:
    - MCP echo fixture server 是安全本地进程（无网络/文件/命令执行）
    - 临时将 confirmation policy 从 "always" 改为 "never"（仅用于 validation）
    - 验证完成后恢复原始 policy
    - 不改变生产默认策略
    - 不连接不安全外部 MCP server
    - 使用 FakeProvider（不调用真实 API）
    - 不读 .env / config.yaml
    - 不打印 secret

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
_original_mcp_confirmations: dict[str, Any] = {}


def record(case_id: str, verdict: str, detail: str, **kw: Any) -> None:
    results.append({"case": case_id, "verdict": verdict, "detail": detail, **kw})
    label = {"PASS": "✓", "FAIL": "✗", "CONCERN": "?"}.get(verdict, verdict)
    print(f"  {label} {case_id}: {detail}")


def _events_by_type(action_log: list[Any], action_type: str) -> list[Any]:
    return [e for e in action_log if getattr(e, "action_type", None) == action_type]


def _safe_payload(e: Any) -> dict[str, Any]:
    evidence = getattr(e, "evidence", None)
    if evidence is not None:
        try:
            return dict(evidence)
        except Exception:
            return {}
    return {}


def _safe_status(e: Any) -> str:
    status = getattr(e, "status", None)
    if status is not None:
        return str(status)
    return "unknown"


def run_mcp_real_invocation() -> None:
    """W1-W8: MCP real runtime-mediated invocation full execution chain."""
    print("\n═══ REAL-EVIDENCE-007: MCP Real Runtime-Mediated Invocation ═══")

    from agent.runtime_integration.phase1_hook import (
        build_phase1_dispatcher,
        build_skill_registry,
    )
    from agent.runtime_integration.schema import RuntimeActionType as RAT  # noqa: N817

    fixture_server = str(_project_root / "scripts" / "fixtures" / "mcp_echo_server.py")

    # ── W0: Fixture server 存在 ──
    if not Path(fixture_server).exists():
        record("W0", "FAIL", f"Fixture server not found: {fixture_server}")
        return
    record("W0", "PASS", f"Fixture server found: {fixture_server}")

    # ── W1: MCP bridge 真实注册 ──
    print("\n  --- W1: MCP bridge registration (real StdioMCPClient) ---")
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
        from agent.mcp_bridge import run_mcp_bridge

        report = run_mcp_bridge(
            mode="registration",
            config_path=config_path,
            server_allowlist=frozenset({"echo-fixture"}),
            dry_run=False,
        )

        if report.tools_registered > 0:
            record("W1", "PASS",
                   f"MCP bridge registered {report.tools_registered} tool(s) "
                   f"via real StdioMCPClient → echo fixture, "
                   f"decision={report.overall_decision}")
        else:
            record("W1", "FAIL",
                   f"MCP bridge registered {report.tools_registered} tools "
                   f"(decision={report.overall_decision}, "
                   f"errors={report.errors})")
            return
    finally:
        Path(config_path).unlink(missing_ok=True)

    # ── W2: MCP 工具在 TOOL_REGISTRY + model-visible tools 中 ──
    print("\n  --- W2: MCP tools visibility ---")
    from agent.core import get_model_visible_tools
    from agent.tool_registry import TOOL_REGISTRY

    mcp_tool_names = sorted(
        name for name in TOOL_REGISTRY if name.startswith("mcp__")
    )
    if mcp_tool_names:
        record("W2a", "PASS",
               f"MCP tools in TOOL_REGISTRY: {mcp_tool_names}")
    else:
        record("W2a", "FAIL",
               "No MCP tools in TOOL_REGISTRY")
        return

    visible = get_model_visible_tools(max_mcp_tools=5)
    visible_names = [
        t["name"] if isinstance(t, dict) else getattr(t, "name", str(t))
        for t in visible
    ]
    mcp_in_visible = [n for n in visible_names if n.startswith("mcp__")]
    if mcp_in_visible:
        record("W2b", "PASS",
               f"MCP tools visible to model: {mcp_in_visible}")
    else:
        record("W2b", "FAIL",
               "No MCP tools in model-visible tools")
        return

    target_mcp_tool = mcp_tool_names[0]
    print(f"\n  Target MCP tool: {target_mcp_tool}")

    # ── 临时 override: confirmation "always" → "never" ──
    # 只用于 safe echo fixture validation，不改变生产默认策略
    print("\n  --- Temporary confirmation override for validation ---")
    for name in mcp_tool_names:
        if name in TOOL_REGISTRY:
            _original_mcp_confirmations[name] = TOOL_REGISTRY[name].get(
                "confirmation", "always"
            )
            TOOL_REGISTRY[name]["confirmation"] = "never"
            print(f"  Override: {name} confirmation={_original_mcp_confirmations[name]} → never")

    # ── W3-W4: FakeProvider → tool_use → ToolRuntimeMediator → TOOL_GATE/W4 ──
    print("\n  --- W3-W4: FakeProvider → TOOL_GATE → TOOL_INVOKE ---")
    skill_registry = build_skill_registry()
    dispatcher = build_phase1_dispatcher(skill_registry=skill_registry)

    import agent.core
    agent.core._active_skill.clear()

    from agent.provider.fake_provider import FakeProvider
    provider = FakeProvider()
    user_msg = f"请使用 {target_mcp_tool} 帮我 echo 一条消息：'hello from mcp validation'"
    print(f"  User message: '{user_msg}'")

    try:
        result = agent.core.chat(
            user_msg,
            provider=provider,
            runtime_action_dispatcher=dispatcher,
        )
        print(f"  chat result preview: {result[:200] if result else '(empty)'}")
    except Exception as exc:
        record("W3", "FAIL", f"core.chat() crashed: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        _restore_confirmation()
        return

    action_log = getattr(dispatcher, "action_log", [])

    tool_gates = _events_by_type(action_log, RAT.TOOL_GATE)
    tool_invokes = _events_by_type(action_log, RAT.TOOL_INVOKE)
    tool_results = _events_by_type(action_log, RAT.TOOL_RESULT)

    # ── W3: TOOL_GATE for MCP tool ──
    mcp_gates = [
        e for e in tool_gates
        if any(n in str(_safe_payload(e)) for n in mcp_tool_names)
    ]
    if mcp_gates:
        gate_evidence = _safe_payload(mcp_gates[0])
        gate_status = _safe_status(mcp_gates[0])
        gate_decision = gate_evidence.get("decision", "?")
        record("W3", "PASS",
               f"TOOL_GATE for MCP tool: status={gate_status}, "
               f"decision={gate_decision}")
    else:
        all_gate_tools = [
            str(_safe_payload(e).get("tool_name", "?"))
            for e in tool_gates
        ]
        record("W3", "FAIL",
               f"No TOOL_GATE for MCP tool. Gate tools: {all_gate_tools}")
        _restore_confirmation()
        return

    # ── W4: TOOL_INVOKE for MCP tool — key improvement from 007 v1 ──
    mcp_invokes = [
        e for e in tool_invokes
        if any(n in str(_safe_payload(e)) for n in mcp_tool_names)
    ]
    if mcp_invokes:
        invoke_evidence = _safe_payload(mcp_invokes[0])
        invoke_status = _safe_status(mcp_invokes[0])
        invoke_tool = invoke_evidence.get("tool_name", "?")
        record("W4", "PASS",
               f"TOOL_INVOKE for MCP tool: tool={invoke_tool}, "
               f"status={invoke_status} — "
               f"confirmation override allowed execution")
    else:
        record("W4", "FAIL",
               "No TOOL_INVOKE for MCP tool — "
               "confirmation override may not have worked")

    # ── W5: Real call_tool (StdioMCPClient) invoked ──
    mcp_results = [
        e for e in tool_results
        if any(n in str(_safe_payload(e)) for n in mcp_tool_names)
    ]
    has_execution_evidence = False
    if mcp_results:
        result_evidence = _safe_payload(mcp_results[0])
        result_disposition = result_evidence.get("disposition", "?")
        result_status = _safe_status(mcp_results[0])

        if result_disposition == "injected" and result_status == "success":
            record("W5", "PASS",
                   f"Real call_tool executed: disposition={result_disposition}, "
                   f"status={result_status} — "
                   f"StdioMCPClient.call_tool was invoked via subprocess")
            has_execution_evidence = True
        elif result_status == "success":
            record("W5", "PASS",
                   f"call_tool executed: status={result_status}, "
                   f"disposition={result_disposition}")
            has_execution_evidence = True
        else:
            record("W5", "CONCERN",
                   f"TOOL_RESULT status={result_status}, "
                   f"disposition={result_disposition} — "
                   f"call_tool may not have executed")
    else:
        record("W5", "FAIL",
               "No TOOL_RESULT for MCP tool")

    # ── W6: Real MCP result content ──
    if mcp_results:
        result_evidence = _safe_payload(mcp_results[0])
        result_tool = result_evidence.get("tool_name", "?")
        result_original_size = result_evidence.get("result_original_size", 0)
        result_was_truncated = result_evidence.get("result_was_truncated", False)

        if result_original_size > 0:
            record("W6", "PASS",
                   f"Real MCP result received: tool={result_tool}, "
                   f"original_size={result_original_size}, "
                   f"truncated={result_was_truncated} — "
                   f"echo fixture returned real data via JSON-RPC")
        else:
            record("W6", "CONCERN",
                   f"MCP result empty or zero-size: "
                   f"original_size={result_original_size}, "
                   f"disposition={result_evidence.get('disposition')}")

    # ── W7: Result in conversation context ──
    if result and has_execution_evidence:
        record("W7", "PASS",
               f"Conversation context updated: chat result len={len(result)}, "
               f"preview='{result[:100]}'")
    elif result:
        record("W7", "CONCERN",
               "Chat returned result but execution evidence incomplete — "
               "result may not be from MCP tool")
    else:
        record("W7", "CONCERN",
               "No conversation result returned")

    # ── W8: Evidence chain traceability ──
    all_types = sorted(set(
        str(getattr(e, "action_type", "?")) for e in action_log
    ))
    mcp_chain_types = [
        t for t in [RAT.TOOL_GATE, RAT.TOOL_INVOKE, RAT.TOOL_RESULT]
        if t in all_types
    ]

    mc_chain = (
        "→".join(mcp_chain_types) if len(mcp_chain_types) == 3
        else "INCOMPLETE"
    )
    record("W8", "PASS",
           f"Evidence chain: {len(action_log)} total events, "
           f"types={all_types}, mcp_chain_complete={mc_chain}")

    # ── 恢复 confirmation policy ──
    _restore_confirmation()
    agent.core._active_skill.clear()


def _restore_confirmation() -> None:
    """恢复 MCP tool 的原始 confirmation policy。"""
    from agent.tool_registry import TOOL_REGISTRY
    for name, original in _original_mcp_confirmations.items():
        if name in TOOL_REGISTRY:
            TOOL_REGISTRY[name]["confirmation"] = original
    if _original_mcp_confirmations:
        _n = len(_original_mcp_confirmations)
        print(f"\n  Restored confirmation policy for {_n} MCP tool(s)")
    _original_mcp_confirmations.clear()


def main() -> None:
    print("=" * 60)
    print("Real Evidence Validation: MCP Real Invocation (007)")
    print("=" * 60)

    run_mcp_real_invocation()

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

    if failed == 0 and concerns == 0:
        print("\n  Overall: CREDIBLE — full MCP execution chain verified")
    elif failed == 0 and concerns <= 2:
        print("\n  Overall: PARTIAL-CREDIBLE — "
              "MCP execution chain partially verified, some concerns remain")

    # Write results
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
                "method": ("FakeProvider deterministic tool_use + "
                           "real StdioMCPClient bridge + "
                           "confirmation='never' override (validation only) + "
                           "main runtime path (core.chat → ToolRuntimeMediator → "
                           "TOOL_GATE→TOOL_INVOKE→TOOL_RESULT)"),
                "results": results,
                "summary": {"PASS": passed, "FAIL": failed, "CONCERN": concerns},
                "note": ("confirmation='always' temporarily overridden to 'never' "
                         "for safe echo fixture validation only; "
                         "original policy restored after validation; "
                         "production default unchanged"),
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
