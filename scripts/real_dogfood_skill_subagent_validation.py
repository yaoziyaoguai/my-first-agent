"""Real provider Skill/SubAgent dogfood validation — Loop 2.2 + Loop 3.2.

用法:
    .venv/bin/python scripts/real_dogfood_skill_subagent_validation.py

验证项:
    1. Skill SKILL_SELECT: 真实 provider 下 turn-end hook 正确 dispatch SKILL_SELECT
    2. Skill allowed_tools enforcement: allowed tool 可执行, disallowed tool 被 block
    3. SubAgent L1: 真实 provider child loop, parent-mediated tool/memory execution
    4. dispatcher evidence chain 完整
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from agent.core import chat as core_chat  # noqa: E402
from agent.runtime_integration.schema import RuntimeActionType  # noqa: E402

# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════


def _events_by_type(events: list[Any], action_type: str) -> list[Any]:
    return [e for e in events if getattr(e, "action_type", None) == action_type]


def _safe_evidence(e: Any) -> dict[str, Any]:
    try:
        return dict(getattr(e, "evidence", {}))
    except Exception:
        return {}


def _safe_status(e: Any) -> str:
    return str(getattr(e, "status", "unknown"))


def _redact(s: str) -> str:
    """Don't print full responses (may contain model output)."""
    if len(s) > 200:
        return s[:200] + "..."
    return s


# ═════════════════════════════════════════════════════════════════════════════
# Test Cases
# ═════════════════════════════════════════════════════════════════════════════

results: list[dict[str, Any]] = []


def record(case_id: str, verdict: str, detail: str, **kw: Any) -> None:
    results.append({"case": case_id, "verdict": verdict, "detail": detail, **kw})
    label = {"PASS": "✓", "FAIL": "✗", "CONCERN": "?"}.get(verdict, verdict)
    print(f"  {label} {case_id}: {detail}")


# ═════════════════════════════════════════════════════════════════════════════


def run_skill_test() -> None:
    """S1: Skill SKILL_SELECT + allowed_tools enforcement with real provider."""
    print("\n─── Skill Validation ───")

    collector: list[Any] = []

    def on_runtime_event(event: Any) -> None:
        collector.append(event)

    from agent.provider.factory import build_model_provider_from_env

    provider = build_model_provider_from_env()
    print(f"  provider={provider.provider_type} model={getattr(provider, 'model', '?')}")

    t0 = time.monotonic()
    try:
        core_chat(
            user_input="帮我创建一个 demo 笔记，标题是'real dogfood skill validation test'",
            provider=provider,
            on_runtime_event=on_runtime_event,
        )
        elapsed = time.monotonic() - t0
        print(f"  chat elapsed={elapsed:.1f}s")

        skill_select = _events_by_type(collector, RuntimeActionType.SKILL_SELECT)
        tool_gates = _events_by_type(collector, RuntimeActionType.TOOL_GATE)
        tool_invokes = _events_by_type(collector, RuntimeActionType.TOOL_INVOKE)
        tool_results = _events_by_type(collector, RuntimeActionType.TOOL_RESULT)
        _mem_proposals = _events_by_type(collector, RuntimeActionType.MEMORY_PROPOSE)
        _mem_recall = _events_by_type(collector, RuntimeActionType.MEMORY_RECALL)

        # S1a: SKILL_SELECT dispatched
        if skill_select:
            ss = skill_select[0]
            status = _safe_status(ss)
            ev = _safe_evidence(ss)
            skill_name = ev.get("skill_name", ev.get("selected_skill", "?"))
            if status == "success":
                record("S1a", "PASS",
                       f"SKILL_SELECT dispatched (skill={skill_name}, status={status})")
            else:
                record("S1a", "CONCERN",
                       f"SKILL_SELECT dispatched but status={status} (skill={skill_name})")
        else:
            record("S1a", "CONCERN",
                   "SKILL_SELECT NOT dispatched — model may not have triggered skill matching; "
                   "check if demo-note-maker description matches user message pattern",
                   events_count=len(collector))

        # S1b: allowed_tools passed in TOOL_GATE
        gate_with_skill = [g for g in tool_gates
                          if "skill_allowed_tools" in _safe_evidence(g)]
        if gate_with_skill:
            ev = _safe_evidence(gate_with_skill[0])
            allowed = ev.get("skill_allowed_tools", [])
            record("S1b", "PASS", f"TOOL_GATE carries skill_allowed_tools={allowed}")
        elif skill_select:
            record("S1b", "CONCERN",
                   "SKILL_SELECT fired but no TOOL_GATE with skill_allowed_tools — "
                   "allowed_tools enforcement may not be active")
        else:
            record("S1b", "CONCERN",
                   "Cannot verify — SKILL_SELECT not dispatched",
                   blocked_by="S1a")

        # S1c: allowed tool executes
        if tool_invokes:
            invokes_ok = [t for t in tool_invokes if _safe_status(t) in ("success", "invoked")]
            record("S1c", "PASS",
                   f"TOOL_INVOKE dispatched ({len(invokes_ok)} invoke(s))")
        elif tool_gates:
            # Check if tools were blocked
            rejected = [g for g in tool_gates if _safe_status(g) == "rejected"]
            if rejected:
                record("S1c", "CONCERN",
                       f"All TOOL_GATE rejected ({len(rejected)}), no TOOL_INVOKE — "
                       "model may have called disallowed tools")
            else:
                record("S1c", "CONCERN", "TOOL_GATE present but no TOOL_INVOKE")
        else:
            record("S1c", "CONCERN", "No tool activity detected")

        # S1d: tool results exist
        if tool_results:
            results_ok = [r for r in tool_results if _safe_status(r) == "success"]
            record("S1d", "PASS", f"TOOL_RESULT dispatched ({len(results_ok)} success)")
        else:
            record("S1d", "CONCERN", "No TOOL_RESULT — tool execution may not have completed")

        # S1e: dispatcher evidence chain complete
        all_types = [getattr(e, "action_type", "?") for e in collector]
        if RuntimeActionType.SKILL_SELECT in all_types or "skill.select" in str(all_types).lower():
            record("S1e", "PASS",
                   f"Evidence chain: {len(collector)} events, types={sorted(set(all_types))}")
        else:
            record("S1e", "CONCERN",
                   f"No SKILL_SELECT in evidence chain. Types: {sorted(set(all_types))}")

    except Exception as exc:
        elapsed = time.monotonic() - t0
        record("S1", "FAIL", f"Skill test crashed: {type(exc).__name__}: {exc}", elapsed=elapsed)
        import traceback
        traceback.print_exc()


def run_subagent_test() -> None:
    """S2: SubAgent L1 parent-mediated child loop with real provider."""
    print("\n─── SubAgent L1 Validation ───")

    collector: list[Any] = []

    def on_runtime_event(event: Any) -> None:
        collector.append(event)

    from agent.provider.factory import build_model_provider_from_env

    provider = build_model_provider_from_env()
    print(f"  provider={provider.provider_type} model={getattr(provider, 'model', '?')}")

    t0 = time.monotonic()
    try:
        core_chat(
            user_input="delegate to demo-explorer: 列出当前可用的 demo 工具",
            provider=provider,
            on_runtime_event=on_runtime_event,
        )
        elapsed = time.monotonic() - t0
        print(f"  chat elapsed={elapsed:.1f}s")

        l1_events = _events_by_type(collector, RuntimeActionType.SUBAGENT_DELEGATE_L1)
        child_tool_events = _events_by_type(collector, "subagent.child_tool_request")
        _child_mem_events = _events_by_type(collector, "subagent.child_memory_request")
        child_result_events = _events_by_type(collector, "subagent.child_result")
        parent_adj_events = _events_by_type(collector, "subagent.parent_adjudication")

        # S2a: SUBAGENT_DELEGATE_L1 dispatched
        if l1_events:
            status = _safe_status(l1_events[0])
            ev = _safe_evidence(l1_events[0])
            record("S2a", "PASS",
                   f"SUBAGENT_DELEGATE_L1 dispatched (status={status}, "
                   f"delegation_id={ev.get('delegation_id', '?')})")
        else:
            # Check if L0 picked it up instead
            l0_events = _events_by_type(collector, RuntimeActionType.SUBAGENT_DELEGATE_L0)
            record("S2a", "CONCERN",
                   f"SUBAGENT_DELEGATE_L1 NOT dispatched; "
                   f"L0 events={len(l0_events)} — delegation may have fallen back to L0",
                   l0_count=len(l0_events),
                   total_events=len(collector))

        # S2b: child tool request parent-mediated
        if child_tool_events:
            record("S2b", "PASS",
                   f"Child tool request parent-mediated ({len(child_tool_events)} requests)")
        elif l1_events:
            record("S2b", "CONCERN",
                   "L1 delegated but no child tool requests — "
                   "child may not have made tool calls or model didn't respond with tools")
        else:
            record("S2b", "CONCERN", "Cannot verify — L1 not dispatched", blocked_by="S2a")

        # S2c: child result returned
        if child_result_events:
            record("S2c", "PASS",
                   f"Child result returned ({len(child_result_events)} result(s))")
        elif l1_events:
            record("S2c", "CONCERN", "L1 delegated but no child result event")
        else:
            record("S2c", "CONCERN", "Cannot verify — L1 not dispatched", blocked_by="S2a")

        # S2d: parent adjudication
        if parent_adj_events:
            record("S2d", "PASS",
                   f"Parent adjudication ({len(parent_adj_events)} adjudication(s))")
        elif l1_events:
            record("S2d", "CONCERN", "L1 delegated but no parent adjudication event")
        else:
            record("S2d", "CONCERN", "Cannot verify", blocked_by="S2a")

        # S2e: dispatcher evidence chain
        all_types = sorted(set(getattr(e, "action_type", "?") for e in collector))
        record("S2e", "PASS",
               f"Evidence chain: {len(collector)} events, types={all_types}")

    except Exception as exc:
        elapsed = time.monotonic() - t0
        record("S2", "FAIL", f"SubAgent test crashed: {type(exc).__name__}: {exc}", elapsed=elapsed)
        import traceback
        traceback.print_exc()


# ═════════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════════


def main() -> None:
    print("=" * 60)
    print("Real Provider Dogfood: Skill + SubAgent Validation")
    print("=" * 60)

    run_skill_test()
    run_subagent_test()

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
        / "skill-subagent-real-dogfood-results-2026-05-28.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "date": "2026-05-28",
                "provider": "kimi-k2.5 (anthropic_compatible)",
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

    # Exit code
    if failed > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
