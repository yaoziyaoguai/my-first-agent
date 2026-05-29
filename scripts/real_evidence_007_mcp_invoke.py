"""REAL-EVIDENCE-007: MCP Runtime-Mediated Invocation — main runtime path validation.

验证目标:
    V1. MCP bridge 通过真实 StdioMCPClient 注册工具到 TOOL_REGISTRY
    V2. MCP 工具在 get_model_visible_tools() 中可见
    V3. FakeProvider 生成 MCP 工具 tool_use → 进入 main runtime path
    V4. TOOL_GATE 被 MCP 工具命中（证明进入统一 ToolRuntimeMediator pipeline）
    V5. Pipeline trace: TOOL_GATE→(confirmation_required|TOOL_INVOKE)→TOOL_RESULT
    V6. 不是 direct-call（有 runtime hook provenance）

为什么用 FakeProvider:
    - Real provider 依赖模型自主选择工具 → 不可控（旧脚本 4 CONCERN）
    - FakeProvider 按策略 1 精确匹配工具名 → 确定性 tool_use
    - FakeProvider 的 tool_use 和 real provider 走完全相同的 main runtime path

安全约束:
    - MCP echo fixture server（scripts/fixtures/mcp_echo_server.py）是安全本地进程
    - 使用 FakeProvider（不调用真实 API）
    - 不读 .env / config.yaml
    - 不访问网络

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
    """V1-V6: MCP runtime-mediated invocation through unified Tool pipeline."""
    print("\n═══ REAL-EVIDENCE-007: MCP Runtime-Mediated Invocation (Main Path) ═══")

    from agent.runtime_integration.phase1_hook import (
        build_phase1_dispatcher,
        build_skill_registry,
    )
    from agent.runtime_integration.schema import RuntimeActionType as RAT  # noqa: N817

    fixture_server = str(_project_root / "scripts" / "fixtures" / "mcp_echo_server.py")

    # ── V0: 前置——fixture server 存在 ──
    if not Path(fixture_server).exists():
        record("V0", "FAIL", f"Fixture server not found: {fixture_server}")
        return
    record("V0", "PASS", f"Fixture server found: {fixture_server}")

    # ── V1: MCP bridge 真实连接 + 注册工具 ──
    print("\n  --- V1: MCP bridge registration (real StdioMCPClient) ---")
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
            record("V1", "PASS",
                   f"MCP bridge registered {report.tools_registered} tool(s) "
                   f"via real StdioMCPClient → echo fixture, "
                   f"decision={report.overall_decision}")
        else:
            record("V1", "FAIL",
                   f"MCP bridge registered {report.tools_registered} tools "
                   f"(decision={report.overall_decision}, "
                   f"errors={report.errors})")
            return

    finally:
        Path(config_path).unlink(missing_ok=True)

    # ── V2: MCP 工具在 TOOL_REGISTRY 和 model-visible tools 中可见 ──
    print("\n  --- V2: MCP tools in TOOL_REGISTRY + model-visible tools ---")
    from agent.core import get_model_visible_tools
    from agent.tool_registry import TOOL_REGISTRY

    mcp_tool_names = sorted(
        [name for name in TOOL_REGISTRY if name.startswith("mcp__")]
    )
    if mcp_tool_names:
        record("V2a", "PASS",
               f"MCP tools in TOOL_REGISTRY: {mcp_tool_names}")
    else:
        record("V2a", "FAIL",
               "No MCP tools in TOOL_REGISTRY — bridge may not have registered them")
        return

    visible = get_model_visible_tools(max_mcp_tools=5)
    # get_model_visible_tools() returns list[dict], not list of objects
    visible_names = [
        t["name"] if isinstance(t, dict) else getattr(t, "name", str(t))
        for t in visible
    ]
    mcp_in_visible = [n for n in visible_names if n.startswith("mcp__")]
    if mcp_in_visible:
        record("V2b", "PASS",
               f"MCP tools visible to model: {mcp_in_visible}")
    else:
        record("V2b", "FAIL",
               "No MCP tools in model-visible tools — "
               "max_mcp_tools may exclude them",
               visible_tools=visible_names[:20])
        return

    # ── 选一个 MCP tool 作为验证目标 ──
    target_mcp_tool = mcp_tool_names[0]
    print(f"\n  Target MCP tool: {target_mcp_tool}")

    # ── Setup: dispatcher + skill_registry ──
    skill_registry = build_skill_registry()
    dispatcher = build_phase1_dispatcher(skill_registry=skill_registry)

    import agent.core
    agent.core._active_skill.clear()

    # ── V3-V4: FakeProvider 生成 MCP 工具 tool_use → main runtime path ──
    print("\n  --- V3-V4: FakeProvider emits tool_use for MCP tool ---")
    from agent.provider.fake_provider import FakeProvider

    provider = FakeProvider()
    user_msg = f"请使用 {target_mcp_tool} 帮我 echo 一条消息"
    print(f"  User message: '{user_msg}'")
    print("  Provider: FakeProvider (deterministic tool matching)")

    try:
        result = agent.core.chat(
            user_msg,
            provider=provider,
            runtime_action_dispatcher=dispatcher,
        )
        print(f"  chat result preview: {result[:200] if result else '(empty)'}")
    except Exception as exc:
        record("V3", "FAIL", f"core.chat() crashed: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return

    # ── Evidence analysis ──
    action_log = getattr(dispatcher, "action_log", [])

    def _payload(e: Any) -> dict[str, Any]:
        evidence = getattr(e, "evidence", None)
        if evidence is not None:
            try:
                return dict(evidence)
            except Exception:
                return {}
        return {}

    def _status(e: Any) -> str:
        s = getattr(e, "status", None)
        if s is not None:
            return str(s)
        return "unknown"

    # 分类 events
    tool_gates = [
        e for e in action_log
        if str(getattr(e, "action_type", "")) == str(RAT.TOOL_GATE)
    ]
    tool_invokes = [
        e for e in action_log
        if str(getattr(e, "action_type", "")) == str(RAT.TOOL_INVOKE)
    ]
    tool_results = [
        e for e in action_log
        if str(getattr(e, "action_type", "")) == str(RAT.TOOL_RESULT)
    ]

    # ── V3: 验证 MCP tool_use 被 FakeProvider 生成 → 进入 TOOL_GATE ──
    mcp_gate_events = [
        e for e in tool_gates
        if any(n in str(_payload(e)) for n in mcp_tool_names)
    ]

    if mcp_gate_events:
        record("V3", "PASS",
               f"FakeProvider generated tool_use for MCP tool → "
               f"entered TOOL_GATE via main runtime path "
               f"({len(mcp_gate_events)} gate event(s) for MCP tool)")
    else:
        all_gate_tools = [str(_payload(e).get("requested_tool_name", "?"))
                          for e in tool_gates]
        record("V3", "FAIL",
               f"No TOOL_GATE for MCP tool. "
               f"All gate tools: {all_gate_tools}. "
               f"FakeProvider may not have matched {target_mcp_tool}")
        return

    # ── V4: TOOL_GATE 对 MCP 工具的具体处理 ──
    gate = mcp_gate_events[0]
    gate_evidence = _payload(gate)
    gate_status = _status(gate)
    gate_decision = gate_evidence.get("decision", "?")
    gate_tool = gate_evidence.get(
        "tool_name", gate_evidence.get("requested_tool_name", "?")
    )

    if gate_status == "success" and gate_decision == "allowed":
        record("V4", "PASS",
               f"TOOL_GATE allowed MCP tool {gate_tool}: "
               f"status={gate_status}, decision={gate_decision} — "
               f"MCP tool entered unified pipeline and passed gate")
    elif gate_status in ("pending", "confirmation_required"):
        record("V4", "PASS",
               f"TOOL_GATE engaged for MCP tool {gate_tool}: "
               f"status={gate_status} (confirmation_required) — "
               f"pipeline entry confirmed; execution blocked by "
               f"confirmation='always' policy, not by MCP-specific path")
    elif gate_status == "rejected":
        record("V4", "CONCERN",
               f"TOOL_GATE rejected MCP tool {gate_tool}: "
               f"status=rejected, decision={gate_decision} — "
               f"MCP tool was REJECTED (not just confirmation_required)")
    else:
        record("V4", "CONCERN",
               f"TOOL_GATE unexpected status for MCP tool: "
               f"status={gate_status}, decision={gate_decision}")

    # ── V5: Pipeline trace ──
    mcp_invoke_events = [
        e for e in tool_invokes
        if any(n in str(_payload(e)) for n in mcp_tool_names)
    ]
    mcp_result_events = [
        e for e in tool_results
        if any(n in str(_payload(e)) for n in mcp_tool_names)
    ]

    if mcp_invoke_events:
        record("V5a", "PASS",
               "TOOL_INVOKE dispatched for MCP tool — "
               "full pipeline TOOL_GATE→TOOL_INVOKE→TOOL_RESULT engaged")
    else:
        record("V5a", "CONCERN",
               "No TOOL_INVOKE for MCP tool — "
               "confirmation='always' blocked execution (expected for MCP)")

    if mcp_result_events:
        result_evidence = _payload(mcp_result_events[0])
        record("V5b", "PASS",
               f"TOOL_RESULT dispatched for MCP tool: "
               f"status={_status(mcp_result_events[0])}, "
               f"evidence_keys={sorted(result_evidence.keys())[:8]}")
    else:
        record("V5b", "CONCERN",
               "No TOOL_RESULT for MCP tool — "
               "mediator _route_result may have failed silently")

    # ── V6: 不是 direct-call ──
    _all_types_set = set(
        str(getattr(e, "action_type", "?")) for e in action_log
    )
    if str(RAT.TOOL_GATE) in _all_types_set:
        gate_source = str(getattr(mcp_gate_events[0], "source", ""))
        if "ToolRuntimeMediator" in gate_source:
            record("V6", "PASS",
                   f"Evidence through main runtime path: "
                   f"TOOL_GATE source={gate_source}, "
                   f"not a direct dispatcher.route() call")
        else:
            record("V6", "CONCERN",
                   f"TOOL_GATE source={gate_source}")
    else:
        record("V6", "CONCERN",
               "Cannot verify main-path provenance")

    # 清理
    agent.core._active_skill.clear()


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
                "method": ("FakeProvider deterministic tool_use + "
                           "real StdioMCPClient bridge + main runtime path"),
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
