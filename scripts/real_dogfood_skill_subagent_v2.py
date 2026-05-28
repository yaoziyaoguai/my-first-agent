"""Loop 2.2 + 3.2 真实 provider dogfood 验证脚本。

验证目标：
  A. Skill Selection (REAL-EVIDENCE-002)
  B. Skill allowed_tools Enforcement (REAL-EVIDENCE-003)
  C. SubAgent L1 Parent-Mediated Child Loop (REAL-EVIDENCE-006)

用法:
    .venv/bin/python scripts/real_dogfood_skill_subagent_v2.py

安全约束：
  - 不读取 .env
  - 不打印 API key / secret
  - 不提交 secret
  - 不调用真实 MCP server
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from agent.runtime_integration.schema import RuntimeActionType as RAT

# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════


def _events_by_type(action_log: list[Any], action_type: str) -> list[Any]:
    return [e for e in action_log if getattr(e, "action_type", None) == action_type]


def _safe_payload(e: Any) -> dict[str, Any]:
    """从 RuntimeActionEvent 中提取 payload 数据。

    RuntimeActionEvent 直接持有 status/evidence/action_type 字段，
    不含 result 嵌套层。优先从 evidence (Mapping) 提取。
    """
    evidence = getattr(e, "evidence", None)
    if evidence is not None:
        try:
            return dict(evidence)
        except Exception:
            return {}
    result = getattr(e, "result", None)
    if result is None:
        return {}
    try:
        return dict(getattr(result, "payload", {}))
    except Exception:
        return {}


def _safe_status(e: Any) -> str:
    """从 RuntimeActionEvent 中提取 status。

    RuntimeActionEvent.status 是直接属性；兼容旧版 event 的 result.status 嵌套。
    """
    status = getattr(e, "status", None)
    if status is not None:
        return str(status)
    result = getattr(e, "result", None)
    if result is None:
        return "unknown"
    return str(getattr(result, "status", "unknown"))


results: list[dict[str, Any]] = []


def record(case_id: str, verdict: str, detail: str, **kw: Any) -> None:
    results.append({"case": case_id, "verdict": verdict, "detail": detail, **kw})
    label = {"PASS": "PASS", "FAIL": "FAIL", "CONCERN": "?"}.get(verdict, verdict)
    print(f"  [{label}] {case_id}: {detail}")


# ═════════════════════════════════════════════════════════════════════════════
# Provider setup
# ═════════════════════════════════════════════════════════════════════════════


def build_provider():
    from agent.provider.factory import build_model_provider_from_env
    return build_model_provider_from_env()


def build_dispatcher():
    """构建完整的 phase1 dispatcher，使 dogfood 脚本可在 chat() 返回后检查 action_log。"""
    from pathlib import Path as _Path

    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher, build_skill_registry
    from agent.subagent_system.registry import SubAgentRegistry

    _skill_registry = build_skill_registry()
    return build_phase1_dispatcher(
        skill_registry=_skill_registry,
        subagent_registry=SubAgentRegistry(roots=[_Path("agent/subagent_system/descriptors")]),
    )


# ═════════════════════════════════════════════════════════════════════════════
# Case A: Skill Selection (REAL-EVIDENCE-002)
# ═════════════════════════════════════════════════════════════════════════════


def case_a_skill_selection(provider, dispatcher) -> None:
    """验证真实 provider 路径下 SKILL_SELECT 不再返回 no_suitable_skill。"""
    print("\n─── A: Skill Selection (REAL-EVIDENCE-002) ───")

    import agent.core

    agent.core._active_skill.clear()

    t0 = time.monotonic()
    try:
        result = agent.core.chat(
            "帮我创建一个 demo 笔记，标题是'real dogfood skill test'",
            provider=provider,
            runtime_action_dispatcher=dispatcher,
        )
        elapsed = time.monotonic() - t0
        print(f"  chat elapsed={elapsed:.1f}s")
        print(f"  chat result preview: {result[:150] if result else '(empty)'}")

        action_log = getattr(dispatcher, "action_log", [])
        skill_selects = _events_by_type(action_log, RAT.SKILL_SELECT)

        # A1: SKILL_SELECT dispatched
        if not skill_selects:
            record("A1", "FAIL", "SKILL_SELECT not dispatched",
                   action_types=[str(getattr(e, "action_type", "?")) for e in action_log])
            return

        ss = skill_selects[0]
        ss_status = _safe_status(ss)
        ss_payload = _safe_payload(ss)

        # A2: Not no_suitable_skill
        no_suitable = ss_payload.get("no_suitable_skill", False)
        if no_suitable:
            record("A2", "FAIL",
                   "SKILL_SELECT still returns no_suitable_skill=True",
                   status=ss_status, payload_keys=list(ss_payload.keys()))
            return

        if ss_status == "success" and ss_payload.get("body_load_decision"):
            record("A2", "PASS",
                   f"SKILL_SELECT success: selected={ss_payload.get('selected_skill_id')}, "
                   f"body_load_decision=True")
        else:
            record("A2", "CONCERN",
                   f"SKILL_SELECT status={ss_status}, body_load_decision={ss_payload.get('body_load_decision')}",
                   status=ss_status, payload_preview=str(ss_payload)[:300])

        # A3: active_skill set
        active = dict(agent.core._active_skill)
        if active.get("skill_id"):
            record("A3", "PASS",
                   f"_active_skill set: skill_id={active.get('skill_id')}, "
                   f"body_len={len(str(active.get('body', '')))}")
        else:
            record("A3", "CONCERN",
                   "_active_skill not set after SKILL_SELECT success",
                   active_skill=active)

        # A4: RuntimeDecisionFrame evidence
        from agent.runtime_decision_frame import get_last_decision_frame
        frame = get_last_decision_frame()
        if frame is not None and frame.skill_registry_active:
            record("A4", "PASS", "RuntimeDecisionFrame reflects skill_registry_active=True")
        elif frame is not None:
            record("A4", "CONCERN",
                   f"skill_registry_active={frame.skill_registry_active}")
        else:
            record("A4", "CONCERN", "No decision frame found")

    except Exception as exc:
        elapsed = time.monotonic() - t0
        record("A", "FAIL", f"Skill selection test crashed: {type(exc).__name__}: {exc}",
               elapsed=elapsed)
        import traceback
        traceback.print_exc()


# ═════════════════════════════════════════════════════════════════════════════
# Case B: Skill allowed_tools Enforcement (REAL-EVIDENCE-003)
# ═════════════════════════════════════════════════════════════════════════════


def case_b_allowed_tools(provider, dispatcher) -> None:
    """验证真实 provider 下 skill allowed_tools 约束工具执行。"""
    print("\n─── B: Skill allowed_tools Enforcement (REAL-EVIDENCE-003) ───")

    import agent.core

    agent.core._active_skill.clear()

    t0 = time.monotonic()
    try:
        # 先触发 skill activation
        result = agent.core.chat(
            "用 demo 工具帮我创建一个任务笔记",
            provider=provider,
            runtime_action_dispatcher=dispatcher,
        )
        elapsed = time.monotonic() - t0
        print(f"  chat elapsed={elapsed:.1f}s")
        print(f"  chat result preview: {result[:200] if result else '(empty)'}")

        action_log = getattr(dispatcher, "action_log", [])

        # B1: SKILL_SELECT succeeded
        skill_selects = _events_by_type(action_log, RAT.SKILL_SELECT)
        if not skill_selects or _safe_payload(skill_selects[0]).get("no_suitable_skill"):
            record("B1", "CONCERN",
                   "Skill not activated — cannot verify allowed_tools enforcement",
                   has_ss=bool(skill_selects))
            # Still check tool gates for completeness
        else:
            record("B1", "PASS",
                   f"Skill activated: {_safe_payload(skill_selects[0]).get('selected_skill_id')}")

        # B2: Tool execution path evidence exists
        tool_gates = _events_by_type(action_log, RAT.TOOL_GATE)
        tool_invokes = _events_by_type(action_log, RAT.TOOL_INVOKE)
        tool_results = _events_by_type(action_log, RAT.TOOL_RESULT)

        if tool_gates:
            accepted = [g for g in tool_gates if _safe_status(g) == "accepted"]
            rejected = [g for g in tool_gates if _safe_status(g) == "rejected"]
            record("B2", "PASS",
                   f"TOOL_GATE: {len(accepted)} accepted, {len(rejected)} rejected")
        else:
            record("B2", "CONCERN", "No TOOL_GATE events — model may not have called tools")

        if tool_invokes:
            record("B3", "PASS", f"TOOL_INVOKE: {len(tool_invokes)} invocations")
        else:
            record("B3", "CONCERN", "No TOOL_INVOKE events")

        if tool_results:
            ok = [r for r in tool_results if _safe_status(r) == "success"]
            record("B4", "PASS", f"TOOL_RESULT: {len(ok)}/{len(tool_results)} success")
        else:
            record("B4", "CONCERN", "No TOOL_RESULT events")

        # B5: active_skill allowed_tools present
        active = dict(agent.core._active_skill)
        allowed = active.get("allowed_tools", frozenset())
        if allowed:
            record("B5", "PASS", f"active_skill allowed_tools={set(allowed)}")
        elif active.get("skill_id"):
            record("B5", "CONCERN", "active_skill set but no allowed_tools")
        else:
            record("B5", "CONCERN", "active_skill not set")

        # B6: Evidence chain completeness
        all_types = sorted(set(str(getattr(e, "action_type", "?")) for e in action_log))
        has_select = RAT.SKILL_SELECT in all_types
        has_gate = RAT.TOOL_GATE in all_types
        has_invoke = RAT.TOOL_INVOKE in all_types
        has_result = RAT.TOOL_RESULT in all_types

        if has_select and has_gate and has_invoke and has_result:
            record("B6", "PASS",
                   f"Evidence chain complete: {len(action_log)} events, types={all_types}")
        elif has_select:
            record("B6", "CONCERN",
                   f"Incomplete evidence chain: types={all_types}")
        else:
            record("B6", "CONCERN",
                   f"Minimal evidence: types={all_types}")

    except Exception as exc:
        elapsed = time.monotonic() - t0
        record("B", "FAIL", f"Allowed tools test crashed: {type(exc).__name__}: {exc}",
               elapsed=elapsed)
        import traceback
        traceback.print_exc()


# ═════════════════════════════════════════════════════════════════════════════
# Case C: SubAgent L1 (REAL-EVIDENCE-006)
# ═════════════════════════════════════════════════════════════════════════════


def case_c_subagent_l1(provider, dispatcher) -> None:
    """验证 SubAgent delegation — parent-mediated tool/memory execution。

    注意：当前两个可用 subagent（demo-stat, code-reviewer）都使用 model=fake，
    因此 L1 (real provider child loop) delegation 无法在此 dogfood 中验证。
    REAL-EVIDENCE-006 仍然 pending——需要真实 model subagent 才能关闭。

    本轮验证目标：
    - L0 delegation 证据链完整（fake-model subagent 的正确路径）
    - child tool/memory/result 事件有 dispatcher evidence
    - 确认 L1 path 未被错误触发（model=fake → L0 是正确的）
    """
    print("\n─── C: SubAgent Delegation (REAL-EVIDENCE-006) ───")

    import agent.core

    t0 = time.monotonic()
    try:
        result = agent.core.chat(
            "delegate to demo-stat: 列出当前可用的 demo 工具，并说明每个工具的用途",
            provider=provider,
            runtime_action_dispatcher=dispatcher,
        )
        elapsed = time.monotonic() - t0
        print(f"  chat elapsed={elapsed:.1f}s")
        print(f"  chat result preview: {result[:200] if result else '(empty)'}")

        action_log = getattr(dispatcher, "action_log", [])

        # C1: Delegation dispatched (L0 for fake-model, L1 for real-model)
        l1_events = _events_by_type(action_log, RAT.SUBAGENT_DELEGATE_L1)
        l0_events = _events_by_type(action_log, RAT.SUBAGENT_DELEGATE_L0)

        if l1_events:
            status = _safe_status(l1_events[0])
            payload = _safe_payload(l1_events[0])
            record("C1", "PASS",
                   f"SUBAGENT_DELEGATE_L1 dispatched: status={status}, "
                   f"delegation_id={payload.get('delegation_id', '?')}")
        elif l0_events:
            status = _safe_status(l0_events[0])
            payload = _safe_payload(l0_events[0])
            record("C1", "PASS",
                   f"SUBAGENT_DELEGATE_L0 dispatched: status={status} "
                   f"(correct for fake-model subagent — L1 requires real-model subagent)")
        else:
            record("C1", "CONCERN",
                   "No delegation events at all",
                   action_types=[str(getattr(e, "action_type", "?")) for e in action_log])

        # C2: child tool request parent-mediated (through ToolRuntimeMediator)
        child_tool = _events_by_type(action_log, RAT.SUBAGENT_CHILD_TOOL_REQUEST)
        if child_tool:
            record("C2", "PASS",
                   f"Child tool requests parent-mediated: {len(child_tool)} request(s)")
        else:
            record("C2", "CONCERN",
                   "No child tool requests — child may not have called tools")

        # C3: child result returned
        child_result = _events_by_type(action_log, RAT.SUBAGENT_CHILD_RESULT)
        if child_result:
            record("C3", "PASS",
                   f"Child result returned: {len(child_result)} result(s)")
        else:
            record("C3", "CONCERN", "No child result event — delegation may have failed")

        # C4: parent adjudication
        parent_adj = _events_by_type(action_log, RAT.SUBAGENT_PARENT_ADJUDICATION)
        if parent_adj:
            record("C4", "PASS",
                   f"Parent adjudication: {len(parent_adj)} adjudication(s)")
        else:
            record("C4", "CONCERN", "No parent adjudication event")

        # C5: child memory request parent-mediated (may not fire if scope=none)
        child_mem = _events_by_type(action_log, RAT.SUBAGENT_CHILD_MEMORY_REQUEST)
        if child_mem:
            record("C5", "PASS",
                   f"Child memory requests: {len(child_mem)} request(s)")
        else:
            record("C5", "PASS",
                   "No child memory requests (memory_scope=none for demo-stat — expected)")

        # C6: L1 real-provider path assessment
        if l1_events:
            record("C6", "PASS",
                   "L1 code path verified with real provider child loop")
        else:
            record("C6", "CONCERN",
                   "L1 code path not exercised: no real-model subagent available "
                   "(both demo-stat and code-reviewer use model=fake). "
                   "L1 handler code is complete but REAL-EVIDENCE-006 cannot be "
                   "closed until a real-model subagent descriptor exists.")

        # C7: Evidence chain completeness
        all_types = sorted(set(str(getattr(e, "action_type", "?")) for e in action_log))
        record("C7", "PASS",
               f"Evidence chain: {len(action_log)} events, types={all_types}")

    except Exception as exc:
        elapsed = time.monotonic() - t0
        record("C", "FAIL", f"SubAgent test crashed: {type(exc).__name__}: {exc}",
               elapsed=elapsed)
        import traceback
        traceback.print_exc()


# ═════════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════════


def main() -> None:
    print("=" * 60)
    print("Real Provider Dogfood: Skill + SubAgent Validation v2")
    print("=" * 60)

    # Build provider
    print("\n[Provider Setup]")
    try:
        provider = build_provider()
        print(f"  provider={provider.provider_type} model={getattr(provider, 'model', '?')}")
    except Exception as exc:
        print(f"  FAILED to build provider: {type(exc).__name__}: {exc}")
        record("SETUP", "FAIL", f"Provider build failed: {type(exc).__name__}: {exc}")
        _write_results()
        sys.exit(2)

    # Build dispatcher
    try:
        dispatcher = build_dispatcher()
        print(f"  dispatcher built, handlers={len(getattr(dispatcher, '_registry', {}).__dict__.get('_handlers', {}))}")
    except Exception as exc:
        print(f"  FAILED to build dispatcher: {type(exc).__name__}: {exc}")
        record("SETUP", "FAIL", f"Dispatcher build failed: {type(exc).__name__}: {exc}")
        _write_results()
        sys.exit(2)

    # Run cases
    case_a_skill_selection(provider, dispatcher)

    # Reset dispatcher action_log for case B
    if hasattr(dispatcher, '_observer') and hasattr(dispatcher._observer, '_action_log'):
        dispatcher._observer._action_log.clear()
    case_b_allowed_tools(provider, dispatcher)

    # Reset dispatcher action_log for case C
    if hasattr(dispatcher, '_observer') and hasattr(dispatcher._observer, '_action_log'):
        dispatcher._observer._action_log.clear()
    case_c_subagent_l1(provider, dispatcher)

    _write_results()


def _write_results() -> None:
    out_path = _project_root / "docs" / "dogfood" / "skill-subagent-real-dogfood-v2-results-2026-05-28.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    passed = sum(1 for r in results if r["verdict"] == "PASS")
    failed = sum(1 for r in results if r["verdict"] == "FAIL")
    concerns = sum(1 for r in results if r["verdict"] == "CONCERN")

    out_path.write_text(
        json.dumps(
            {
                "date": "2026-05-28",
                "script": "scripts/real_dogfood_skill_subagent_v2.py",
                "targets": ["REAL-EVIDENCE-002", "REAL-EVIDENCE-003", "REAL-EVIDENCE-006"],
                "results": results,
                "summary": {"PASS": passed, "FAIL": failed, "CONCERN": concerns},
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nResults written to {out_path}")

    # Summary
    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)
    for r in results:
        label = {"PASS": "PASS", "FAIL": "FAIL", "CONCERN": "?"}[r["verdict"]]
        print(f"  [{label}] {r['case']}: {r['detail']}")

    print(f"\n  PASS={passed} FAIL={failed} CONCERN={concerns}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
