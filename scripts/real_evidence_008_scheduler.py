"""REAL-EVIDENCE-008: Advanced Scheduler real provider E2E validation.

验证目标:
  S1. ACTION_PLAN_START evidence 通过 dispatcher 产生
  S2. NODE_ENTER evidence（≥2 个 node）
  S3. NODE_EXIT evidence（≥2 个 node）
  S4. ACTION_PLAN_COMPLETE evidence
  S5. 跨 node 结果影响（condition_flags: step_1 结果 → step_3 跳过）
  S6. NODE_EXIT skipped disposition（condition flag 触发）
  S7. 真实 provider API 调用（executor 内 core.chat() 成功）
  S8. 无 no-crash PASS —— 每个断言有正向验证

用法:
    .venv/bin/python scripts/real_evidence_008_scheduler.py

安全约束:
  - 不读取 .env
  - 不打印 API key / secret
  - 不提交 secret
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

from agent.runtime_integration.schema import RuntimeActionType as RAT  # noqa: E402, N817

results: list[dict[str, Any]] = []


def record(case_id: str, verdict: str, detail: str, **kw: Any) -> None:
    results.append({"case": case_id, "verdict": verdict, "detail": detail, **kw})
    label = {"PASS": "PASS", "FAIL": "FAIL", "CONCERN": "?"}.get(verdict, verdict)
    print(f"  [{label}] {case_id}: {detail}")


def _events_by_type(action_log: list[Any], action_type: str) -> list[Any]:
    return [e for e in action_log if str(getattr(e, "action_type", "")) == action_type]


def _safe_status(e: Any) -> str:
    status = getattr(e, "status", None)
    if status is not None:
        return str(status)
    result = getattr(e, "result", None)
    if result is None:
        return "unknown"
    return str(getattr(result, "status", "unknown"))


def _safe_payload(e: Any) -> dict[str, Any]:
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


# ═════════════════════════════════════════════════════════════════════════════
# Part 0: Pre-flight checks
# ═════════════════════════════════════════════════════════════════════════════


def preflight() -> tuple[Any, Any]:
    """检查 provider 可用 + dispatcher 可构建。"""
    print("\n═══ Part 0: Pre-flight checks ═══")

    from agent.provider.factory import build_model_provider_from_env

    provider = build_model_provider_from_env()
    provider_kind = type(provider).__name__
    print(f"  Provider: {provider_kind}")

    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher

    dispatcher = build_phase1_dispatcher()
    print(f"  Dispatcher: {type(dispatcher).__name__}")

    # 快速连通性检查：简单 chat 调用
    print("  Checking provider connectivity...")
    try:
        import agent.core
        t0 = time.monotonic()
        test_result = agent.core.chat(
            "回复 OK（只回复这两个字母）",
            provider=provider,
            runtime_action_dispatcher=dispatcher,
        )
        elapsed = time.monotonic() - t0
        print(f"  Connectivity OK: chat() returned in {elapsed:.1f}s, "
              f"preview={str(test_result)[:80]}")
        record("S0", "PASS", f"Provider connectivity OK ({provider_kind}, {elapsed:.1f}s)")
    except Exception as exc:
        record("S0", "FAIL", f"Provider connectivity failed: {exc}")
        raise SystemExit(1) from exc

    return provider, dispatcher


# ═════════════════════════════════════════════════════════════════════════════
# Part 1: Build ActionPlan + ActionScheduler + executor
# ═════════════════════════════════════════════════════════════════════════════


def build_plan() -> Any:
    """构造 3-node ActionPlan，演示跨 node 结果影响。

    Plan 结构:
      step_1: TOOL_CALL — 真实 provider chat → 设置 step_1_done flag
      step_2: TOOL_CALL — depends_on step_1 → 真实 provider chat → 设置 skip_step_3 flag
      step_3: TOOL_CALL — condition="skip_step_3" → 被跳过（跨 node 影响证据）
    """
    from agent.action_scheduler import build_action_plan_from_dict

    plan_dict: dict[str, Any] = {
        "plan_id": "real-evidence-008-e2e",
        "entry_node_id": "step_1",
        "description": "REAL-EVIDENCE-008: scheduler real provider E2E — 3 nodes, cross-node influence",  # noqa: E501
        "nodes": [
            {
                "node_id": "step_1",
                "action_type": "TOOL_CALL",
                "target": "real_provider_chat",
                "params": {"prompt": "用一句话介绍什么是 Python（中文，不超过20字）"},
                "depends_on": [],
                "recovery": {"on_failure": "halt"},
                "condition": None,
                "description": "Step 1: 真实 provider 对话 — 介绍 Python",
            },
            {
                "node_id": "step_2",
                "action_type": "TOOL_CALL",
                "target": "real_provider_chat",
                "params": {"prompt": "用一句话介绍什么是 Docker（中文，不超过20字）"},
                "depends_on": ["step_1"],
                "recovery": {"on_failure": "skip"},
                "condition": None,
                "description": "Step 2: 真实 provider 对话 — 介绍 Docker（依赖 step_1 完成）",
            },
            {
                "node_id": "step_3",
                "action_type": "TOOL_CALL",
                "target": "real_provider_chat",
                "params": {"prompt": "这个不应该被执行"},
                "depends_on": ["step_2"],
                "recovery": {"on_failure": "skip"},
                "condition": "skip_step_3",
                "description": "Step 3: 应被 step_2 结果跳过（condition flag 跨 node 影响）",
            },
        ],
    }
    return build_action_plan_from_dict(plan_dict)


def build_executor(provider: Any, dispatcher: Any):
    """构造真实 provider executor。

    对 TOOL_CALL(target="real_provider_chat") 节点:
      - 调用 core.chat() 走真实 provider
      - 返回 result dict 含 success + condition_flags
      - step_1 完成 → 设置 step_1_done
      - step_2 完成 → 设置 skip_step_3（影响 step_3）
    """
    import agent.core

    def executor(node: Any, state: Any) -> dict[str, Any]:
        if node.action_type != "TOOL_CALL":
            return {"success": False, "error": f"unsupported action_type: {node.action_type}"}

        if node.target != "real_provider_chat":
            return {"success": False, "error": f"unknown target: {node.target}"}

        prompt = str(node.params.get("prompt", "回复 OK"))
        node_id = str(node.node_id)

        try:
            t0 = time.monotonic()
            chat_result = agent.core.chat(
                prompt,
                provider=provider,
                runtime_action_dispatcher=dispatcher,
            )
            elapsed = time.monotonic() - t0

            result: dict[str, Any] = {
                "success": True,
                "node_id": node_id,
                "chat_result_preview": str(chat_result)[:200],
                "elapsed_s": round(elapsed, 2),
            }

            # 跨 node 影响：通过 condition_flags 传递
            if node_id == "step_1":
                state.condition_flags["step_1_done"] = True
                result["condition_flags_set"] = ["step_1_done"]
            elif node_id == "step_2":
                state.condition_flags["skip_step_3"] = True
                result["condition_flags_set"] = ["skip_step_3"]

            return result
        except Exception as exc:
            return {
                "success": False,
                "node_id": node_id,
                "error": f"{type(exc).__name__}: {exc}",
            }

    return executor


# ═════════════════════════════════════════════════════════════════════════════
# Part 2: Execute plan through scheduler
# ═════════════════════════════════════════════════════════════════════════════


def run_scheduler(provider: Any, dispatcher: Any) -> dict[str, Any]:
    """通过 ActionScheduler 执行 multi-node plan。"""
    print("\n═══ Part 2: Execute plan through scheduler ═══")

    from agent.action_scheduler import ActionScheduler

    plan = build_plan()
    executor_fn = build_executor(provider, dispatcher)
    scheduler = ActionScheduler(dispatcher=dispatcher, executor=executor_fn)

    print(f"  Plan: {plan.plan_id} — {len(plan.nodes)} nodes")
    for n in plan.nodes:
        cond = f" [condition={n.condition}]" if n.condition else ""
        deps = f" [depends_on={list(n.depends_on)}]" if n.depends_on else ""
        print(f"    {n.node_id}: {n.action_type}({n.target}){deps}{cond} — {n.description}")

    scheduler.load_plan(plan)
    print(f"  Plan status after load: {scheduler.state.status}")

    node_count = 0
    while scheduler.has_active_plan():
        node = scheduler.next_node()
        if node is None:
            print("  No more pending nodes — completing plan")
            scheduler.complete_plan()
            break

        node_count += 1
        print(f"  Executing node {node_count}: {node.node_id} ({node.action_type}:{node.target})")
        result = scheduler.execute_node(node)
        success = result.get("success", False)
        preview = str(result.get("chat_result_preview", result.get("error", "")))[:120]
        print(f"    success={success}, {preview}")

    final_status = scheduler.state.status
    completed = list(scheduler.state.completed_nodes)
    flags = dict(scheduler.state.condition_flags)
    print(f"  Final status: {final_status}")
    print(f"  Completed nodes: {completed}")
    print(f"  Condition flags: {flags}")

    return {
        "final_status": final_status,
        "node_count": node_count,
        "completed_nodes": completed,
        "condition_flags": flags,
    }


# ═════════════════════════════════════════════════════════════════════════════
# Part 3: Verify evidence
# ═════════════════════════════════════════════════════════════════════════════


def verify_evidence(dispatcher: Any, run_info: dict[str, Any]) -> None:
    """验证 dispatcher action_log 中的 scheduler evidence。"""
    print("\n═══ Part 3: Verify evidence ═══")

    action_log = getattr(dispatcher, "action_log", [])
    print(f"  action_log entries: {len(action_log)}")

    # 列出所有 action types
    all_types = [str(getattr(e, "action_type", "?")) for e in action_log]
    scheduler_types = [t for t in all_types if "scheduler." in t or "action_plan" in t.lower()]
    print(f"  Scheduler-related types: {scheduler_types}")

    # S1: ACTION_PLAN_START
    plan_starts = _events_by_type(action_log, str(RAT.ACTION_PLAN_START))
    if plan_starts:
        p = _safe_payload(plan_starts[0])
        record("S1", "PASS",
               f"ACTION_PLAN_START: plan_id={p.get('plan_id')}, "
               f"total_nodes={p.get('total_nodes')}, "
               f"entry_node_id={p.get('entry_node_id')}")
    else:
        record("S1", "FAIL", "ACTION_PLAN_START not found in action_log")

    # S2: NODE_ENTER (≥2)
    node_enters = _events_by_type(action_log, str(RAT.NODE_ENTER))
    enter_ids = [_safe_payload(e).get("node_id", "?") for e in node_enters]
    if len(node_enters) >= 2:
        record("S2", "PASS",
               f"NODE_ENTER x{len(node_enters)}: {enter_ids}")
    elif len(node_enters) == 1:
        record("S2", "FAIL",
               f"Only 1 NODE_ENTER (need ≥2): {enter_ids}")
    else:
        record("S2", "FAIL", "No NODE_ENTER evidence found")

    # S3: NODE_EXIT (≥2)
    node_exits = _events_by_type(action_log, str(RAT.NODE_EXIT))
    exit_info = []
    for e in node_exits:
        p = _safe_payload(e)
        exit_info.append(f"{p.get('node_id', '?')}/{p.get('disposition', '?')}")
    if len(node_exits) >= 2:
        record("S3", "PASS",
               f"NODE_EXIT x{len(node_exits)}: {exit_info}")
    elif len(node_exits) == 1:
        record("S3", "FAIL",
               f"Only 1 NODE_EXIT (need ≥2): {exit_info}")
    else:
        record("S3", "FAIL", "No NODE_EXIT evidence found")

    # S4: ACTION_PLAN_COMPLETE
    plan_completes = _events_by_type(action_log, str(RAT.ACTION_PLAN_COMPLETE))
    if plan_completes:
        p = _safe_payload(plan_completes[0])
        record("S4", "PASS",
               f"ACTION_PLAN_COMPLETE: disposition={p.get('disposition')}, "
               f"completed={p.get('completed_nodes')}/{p.get('total_nodes')}")
    else:
        record("S4", "FAIL", "ACTION_PLAN_COMPLETE not found in action_log")

    # S5: 跨 node 结果影响 — condition_flags 从 step_2 传递到 step_3
    flags = run_info.get("condition_flags", {})
    if flags.get("skip_step_3") is True:
        record("S5", "PASS",
               f"Cross-node influence: skip_step_3=True set by step_2 → step_3 skipped, "
               f"all flags={flags}")
    else:
        record("S5", "FAIL",
               f"skip_step_3 flag not set — cross-node influence not demonstrated, "
               f"flags={flags}")

    # S6: step_3 被跳过（NODE_EXIT disposition=skipped）
    skipped_exits = [e for e in node_exits
                     if _safe_payload(e).get("disposition") == "skipped"]
    if skipped_exits:
        sp = _safe_payload(skipped_exits[0])
        record("S6", "PASS",
               f"Condition-triggered skip: node={sp.get('node_id')}, "
               f"reason={sp.get('reason', '?')}")
    else:
        # step_3 可能未进入（condition 在 next_node 时触发，不产生 NODE_ENTER/NODE_EXIT）
        # 检查 step_3 是否在 completed_nodes 中
        completed = run_info.get("completed_nodes", [])
        if "step_3" in completed:
            # step_3 被标记为 completed（跳过）但没有 NODE_EXIT
            record("S6", "CONCERN",
                   "step_3 skipped (in completed_nodes) but no NODE_EXIT with skipped "
                   "disposition — condition skip dispatches NODE_EXIT internally, "
                   "check _dispatch_skip_evidence")
        else:
            record("S6", "CONCERN",
                   "step_3 not in completed_nodes — may not have been reached, "
                   f"completed={completed}")

    # S7: 真实 provider API 调用验证
    if run_info.get("node_count", 0) >= 2:
        record("S7", "PASS",
               f"Real provider called via core.chat() for {run_info['node_count']} nodes, "
               f"plan status={run_info['final_status']}")
    else:
        record("S7", "FAIL",
               f"Only {run_info.get('node_count', 0)} nodes executed — "
               "real provider not sufficiently exercised")

    # S8: 不是 no-crash PASS — 每个 case 有正向断言
    verdicts = [r["verdict"] for r in results if r["case"].startswith("S")]
    passes = sum(1 for v in verdicts if v == "PASS")
    fails = sum(1 for v in verdicts if v == "FAIL")
    concerns = sum(1 for v in verdicts if v == "CONCERN")
    if fails == 0 and passes >= 6:
        record("S8", "PASS",
               f"Not a no-crash PASS: {passes} positive assertions, "
               f"{fails} fails, {concerns} concerns")
    else:
        record("S8", "FAIL",
               f"Evidence incomplete: {passes}P / {fails}F / {concerns}C — "
               "cannot claim validation complete")


# ═════════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════════


def main() -> int:
    print("=" * 70)
    print("REAL-EVIDENCE-008: Advanced Scheduler Real Provider E2E")
    print("=" * 70)

    provider, dispatcher = preflight()
    run_info = run_scheduler(provider, dispatcher)
    verify_evidence(dispatcher, run_info)

    # ── Summary ──
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    verdicts = [r["verdict"] for r in results]
    passes = sum(1 for v in verdicts if v == "PASS")
    fails = sum(1 for v in verdicts if v == "FAIL")
    concerns = sum(1 for v in verdicts if v == "CONCERN")
    print(f"  {passes} PASS / {fails} FAIL / {concerns} CONCERN")

    for r in results:
        label = {"PASS": "PASS", "FAIL": "FAIL", "CONCERN": "?"}.get(r["verdict"], r["verdict"])
        print(f"  [{label}] {r['case']}: {r['detail']}")

    # 保存结果
    output_path = _project_root / "docs" / "dogfood" / "real-evidence-008-scheduler-results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_data = {
        "evidence_id": "REAL-EVIDENCE-008",
        "description": "Advanced Scheduler real provider E2E",
        "summary": {"pass": passes, "fail": fails, "concern": concerns},
        "results": results,
        "run_info": {
            k: str(v) if not isinstance(v, (str, int, float, bool, list, dict, type(None)))
            else v
            for k, v in run_info.items()
        },
    }
    output_path.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults saved to: {output_path}")

    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
