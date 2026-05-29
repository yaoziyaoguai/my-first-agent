"""REAL-EVIDENCE-008 Gap A: Scheduler core.chat E2E validation.

验证 scheduler evidence 从完整 main runtime path 产生:
  _run_main_loop(action_scheduler=scheduler)
  → LoopDependencies(action_scheduler=...)
  → run_main_loop() scheduler preprocessing block
  → ACTION_PLAN_START → NODE_ENTER → NODE_EXIT → ACTION_PLAN_COMPLETE

与旧 scripts/real_evidence_008_scheduler.py 的关键区别:
  - 旧: 手动构造 ActionScheduler，手动调用 scheduler.next_node()/execute_node()
  - 新: 通过 _run_main_loop(action_scheduler=scheduler) 走完整注入链
  - 旧: executor 内部调用 core.chat() — scheduler 不进入主路径
  - 新: scheduler 进入 run_main_loop() preprocessing block → 证据自动产生

Gap A 不修改 production code。使用 FakeProvider + hand-built ActionPlan。

用法:
    .venv/bin/python scripts/real_evidence_008_scheduler_core_chat_e2e.py

安全约束:
  - 不读取 .env
  - 不打印 API key / secret
  - 不提交 secret
  - 不使用真实 provider (FakeProvider only)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from agent.action_scheduler import (  # noqa: E402
    ActionNode,
    ActionPlan,
    ActionRecoveryPolicy,
    ActionScheduler,
)
from agent.core import TurnState, _run_main_loop  # noqa: E402
from agent.loop_context import LoopContext  # noqa: E402
from agent.provider.fake_provider import FakeProvider  # noqa: E402
from agent.runtime_integration.action_scheduler_handler import (  # noqa: E402
    ActionSchedulerHandler,
)
from agent.runtime_integration.dispatcher import (  # noqa: E402
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
)
from agent.runtime_integration.evidence import (  # noqa: E402
    RuntimeActionModuleObserver,
)
from agent.runtime_integration.schema import RuntimeActionType as RAT  # noqa: E402, N817

results: list[dict[str, Any]] = []


def record(case_id: str, verdict: str, detail: str, **kw: Any) -> None:
    results.append({"case": case_id, "verdict": verdict, "detail": detail, **kw})
    label = {
        "PASS": "\033[32mPASS\033[0m",
        "FAIL": "\033[31mFAIL\033[0m",
        "CONCERN": "\033[33m?\033[0m",
    }.get(verdict, verdict)
    print(f"  [{label}] {case_id}: {detail}")


def _events_by_type(action_log: list[Any], action_type: str) -> list[Any]:
    return [e for e in action_log if str(getattr(e, "action_type", "")) == action_type]


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _build_dispatcher():
    """构建注册了 ActionSchedulerHandler 的 dispatcher。"""
    registry = ActionHandlerRegistry()
    handler = ActionSchedulerHandler()
    for at in (
        RAT.ACTION_PLAN_START,
        RAT.NODE_ENTER,
        RAT.NODE_EXIT,
        RAT.NODE_FAILURE,
        RAT.ACTION_PLAN_COMPLETE,
    ):
        registry.register(at, handler)
    return RuntimeActionDispatcher(registry=registry, observer=RuntimeActionModuleObserver())


def _success_executor(**kwargs):
    """成功 executor——返回 success=True 并合并额外 kwargs。"""

    def _exec(node, state):
        base = {"success": True, "node_id": node.node_id, "target": node.target}
        base.update(kwargs)
        return base

    return _exec


def _failing_executor(error="test failure"):
    """失败 executor——返回 success=False。"""

    def _exec(node, state):
        return {"success": False, "error": error, "node_id": node.node_id}

    return _exec


def _conditional_executor(flags: dict[str, bool]):
    """条件 executor——成功并设置 condition_flags。"""

    def _exec(node, state):
        return {
            "success": True,
            "node_id": node.node_id,
            "target": node.target,
            "condition_flags": dict(flags),
        }

    return _exec


def _node(**kwargs):
    defaults = {"node_id": "step_1", "action_type": "TOOL_CALL", "target": "test_tool"}
    defaults.update(kwargs)
    return ActionNode(**defaults)


def _simple_plan(**kwargs):
    nodes = kwargs.pop("nodes", (_node(node_id="step_1"),))
    plan_id = kwargs.pop("plan_id", "test_plan")
    nodes = tuple(nodes)
    entry_node_id = kwargs.pop("entry_node_id", nodes[0].node_id)
    return ActionPlan(plan_id=plan_id, nodes=nodes, entry_node_id=entry_node_id, **kwargs)


def _make_loop_ctx(model_provider, dispatcher, model_name="fake-model"):
    """构造 LoopContext 用于 _run_main_loop()。"""
    return LoopContext(
        client=MagicMock(),  # FakeProvider 不会实际调用 SDK client
        model_name=model_name,
        max_loop_iterations=5,
        model_provider=model_provider,
        runtime_action_dispatcher=dispatcher,
    )


def _make_turn_state(system_prompt="scheduler test"):
    """构造 TurnState 用于 _run_main_loop()。"""
    return TurnState(system_prompt=system_prompt)


def _make_fake_provider(response_text="done"):
    """构造 FakeProvider，返回简单文本响应。"""
    return FakeProvider(response_fn=lambda msgs: response_text)


# ═══════════════════════════════════════════════════════════════════════════════
# Validation Cases
# ═══════════════════════════════════════════════════════════════════════════════


def v1_non_empty_result():
    """V1: _run_main_loop(action_scheduler=...) 返回非空结果字符串。"""
    dispatcher = _build_dispatcher()
    provider = _make_fake_provider("all steps completed")
    scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
    scheduler.load_plan(_simple_plan(plan_id="v1_test"))

    ts = _make_turn_state()
    lc = _make_loop_ctx(provider, dispatcher)

    result = _run_main_loop(ts, lc, action_scheduler=scheduler)

    if result and isinstance(result, str) and len(result) > 0:
        record("V1", "PASS", f"non-empty result: {result[:80]}")
    else:
        record("V1", "FAIL", f"result empty or wrong type: {type(result).__name__}")


def v2_action_plan_start():
    """V2: ACTION_PLAN_START evidence 在 dispatcher action_log 中。"""
    dispatcher = _build_dispatcher()
    provider = _make_fake_provider("plan started ok")
    scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
    scheduler.load_plan(_simple_plan(plan_id="v2_evidence_start"))

    ts = _make_turn_state()
    lc = _make_loop_ctx(provider, dispatcher)

    _run_main_loop(ts, lc, action_scheduler=scheduler)

    starts = _events_by_type(dispatcher.action_log, "scheduler.action_plan_start")
    if len(starts) >= 1:
        evidence = dict(getattr(starts[0], "evidence", {}))
        plan_id = evidence.get("plan_id", "")
        record("V2", "PASS", f"ACTION_PLAN_START: plan_id={plan_id}, total_events={len(starts)}")
    else:
        record("V2", "FAIL", f"no ACTION_PLAN_START found in {len(dispatcher.action_log)} events")


def v3_node_enter_exit():
    """V3: NODE_ENTER + NODE_EXIT evidence 每个 node 至少各一个。"""
    dispatcher = _build_dispatcher()
    provider = _make_fake_provider("nodes done")
    scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
    scheduler.load_plan(_simple_plan(
        plan_id="v3_nodes",
        nodes=(
            _node(node_id="n1", description="first node"),
            _node(node_id="n2", description="second node"),
        ),
    ))

    ts = _make_turn_state()
    lc = _make_loop_ctx(provider, dispatcher)

    _run_main_loop(ts, lc, action_scheduler=scheduler)

    enters = _events_by_type(dispatcher.action_log, "scheduler.node_enter")
    exits = _events_by_type(dispatcher.action_log, "scheduler.node_exit")

    if len(enters) >= 2 and len(exits) >= 2:
        record("V3", "PASS", f"NODE_ENTER={len(enters)}, NODE_EXIT={len(exits)}")
    else:
        record("V3", "FAIL", f"NODE_ENTER={len(enters)}, NODE_EXIT={len(exits)} (need >=2 each)")


def v4_action_plan_complete():
    """V4: ACTION_PLAN_COMPLETE evidence 在 dispatcher action_log 中。"""
    dispatcher = _build_dispatcher()
    provider = _make_fake_provider("plan completed")
    scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
    scheduler.load_plan(_simple_plan(plan_id="v4_complete"))

    ts = _make_turn_state()
    lc = _make_loop_ctx(provider, dispatcher)

    _run_main_loop(ts, lc, action_scheduler=scheduler)

    completes = _events_by_type(dispatcher.action_log, "scheduler.action_plan_complete")
    if len(completes) >= 1:
        evidence = dict(getattr(completes[0], "evidence", {}))
        disposition = evidence.get("disposition", "")
        record("V4", "PASS", f"ACTION_PLAN_COMPLETE: disposition={disposition}")
    else:
        record("V4", "FAIL", f"no ACTION_PLAN_COMPLETE in {len(dispatcher.action_log)} events")


def v5_condition_flags():
    """V5: condition_flags 跨 node 影响——step_1 设置 flag → step_3 条件跳过。"""
    dispatcher = _build_dispatcher()
    provider = _make_fake_provider("conditional plan done")

    # step_1 设置 skip_3=True → step_3 被跳过
    scheduler = ActionScheduler(
        dispatcher=dispatcher,
        executor=_conditional_executor({"skip_step3": True}),
    )
    scheduler.load_plan(_simple_plan(
        plan_id="v5_conditional",
        nodes=(
            _node(node_id="step_1", description="setup"),
            _node(node_id="step_2", description="always run"),
            _node(node_id="step_3", condition="skip_step3", description="conditional"),
        ),
    ))

    ts = _make_turn_state()
    lc = _make_loop_ctx(provider, dispatcher)

    _run_main_loop(ts, lc, action_scheduler=scheduler)

    # step_3 应被跳过: NODE_EXIT 中至少一个 disposition=skipped
    exits = _events_by_type(dispatcher.action_log, "scheduler.node_exit")
    skipped = [
        e for e in exits
        if dict(getattr(e, "evidence", {})).get("disposition") == "skipped"
    ]
    if len(skipped) >= 1:
        record("V5", "PASS", f"condition flag triggered: {len(skipped)} skipped NODE_EXIT")
    else:
        record("V5", "FAIL", f"no skipped NODE_EXIT found in {len(exits)} exits")


def v6_node_failure_halt():
    """V6: NODE_FAILURE evidence + halt 后 ACTION_PLAN_COMPLETE disposition=halted。"""
    dispatcher = _build_dispatcher()
    provider = _make_fake_provider("halt after failure")
    scheduler = ActionScheduler(dispatcher=dispatcher, executor=_failing_executor("boom"))
    scheduler.load_plan(_simple_plan(
        plan_id="v6_failure",
        nodes=(
            _node(node_id="fail_n1", recovery=ActionRecoveryPolicy(on_failure="halt")),
        ),
    ))

    ts = _make_turn_state()
    lc = _make_loop_ctx(provider, dispatcher)

    _run_main_loop(ts, lc, action_scheduler=scheduler)

    failures = _events_by_type(dispatcher.action_log, "scheduler.node_failure")
    completes = _events_by_type(dispatcher.action_log, "scheduler.action_plan_complete")

    fail_ok = len(failures) >= 1
    halt_ok = any(
        dict(getattr(e, "evidence", {})).get("disposition", "").startswith("halted")
        for e in completes
    ) if completes else False

    if fail_ok and halt_ok:
        record("V6", "PASS", f"NODE_FAILURE={len(failures)}, halted disposition confirmed")
    else:
        record("V6", "FAIL", f"NODE_FAILURE={len(failures)}, halted_in_complete={halt_ok}")


def v7_not_no_crash_pass():
    """V7: 每个 assertion 都有正向验证——不是只断言不 crash。"""
    dispatcher = _build_dispatcher()
    provider = _make_fake_provider("not just no-crash")
    scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
    scheduler.load_plan(_simple_plan(plan_id="v7_positive"))

    ts = _make_turn_state()
    lc = _make_loop_ctx(provider, dispatcher)

    _run_main_loop(ts, lc, action_scheduler=scheduler)

    # 正向验证: dispatcher.action_log 非空 → 证据真的产生了
    if len(dispatcher.action_log) == 0:
        record("V7", "FAIL", "dispatcher.action_log 为空——没有证据产生")
        return

    # 验证证据链完整: START → ENTER → EXIT → COMPLETE 四种类型都存在
    event_types = {str(getattr(e, "action_type", "")) for e in dispatcher.action_log}
    required = {
        "scheduler.action_plan_start",
        "scheduler.node_enter",
        "scheduler.node_exit",
        "scheduler.action_plan_complete",
    }
    missing = required - event_types
    if missing:
        record("V7", "FAIL", f"证据链不完整，缺失: {missing}")
    else:
        record("V7", "PASS", f"完整证据链: {sorted(event_types)}")


def v8_not_manual_harness():
    """V8: scheduler 进入 _run_main_loop() preprocessing block，非手动 harness。"""
    dispatcher = _build_dispatcher()
    provider = _make_fake_provider("main path confirmed")
    scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
    scheduler.load_plan(_simple_plan(plan_id="v8_main_path"))

    ts = _make_turn_state()
    lc = _make_loop_ctx(provider, dispatcher)

    # 验证点: _run_main_loop() 内部构造 LoopDependencies(action_scheduler=scheduler)
    # 然后 run_main_loop() 在 scheduler preprocessing block 中自动推进
    result = _run_main_loop(ts, lc, action_scheduler=scheduler)

    # plan 应该已经完成 (preprocessing block 中 complete_plan 被调用)
    if scheduler.has_active_plan():
        record("V8", "FAIL", "plan 未完成——scheduler 未被 preprocessing block 推进")
        return

    # model fallback 被调用——result 来自 FakeProvider 响应
    if "done" not in result.lower() and "main path" not in result.lower():
        record("V8", "CONCERN", f"model fallback result 可能未被调用: {result[:60]}")
        return

    record("V8", "PASS", "scheduler 通过 _run_main_loop() preprocessing block 自动推进")


def v9_multi_node_topological():
    """V9: 多 node 依赖拓扑顺序——n2 depends_on n1，验证 n2 在 n1 完成后执行。"""
    dispatcher = _build_dispatcher()
    provider = _make_fake_provider("topological ok")

    execution_order: list[str] = []

    def _tracking_executor(node, state):
        execution_order.append(node.node_id)
        return {"success": True, "node_id": node.node_id, "target": node.target}

    scheduler = ActionScheduler(dispatcher=dispatcher, executor=_tracking_executor)
    scheduler.load_plan(_simple_plan(
        plan_id="v9_topo",
        nodes=(
            _node(node_id="setup", description="first"),
            _node(node_id="main", depends_on=("setup",), description="second"),
            _node(
                node_id="cleanup",
                depends_on=("setup",),
                description="third (parallel with main)",
            ),
        ),
        entry_node_id="setup",
    ))

    ts = _make_turn_state()
    lc = _make_loop_ctx(provider, dispatcher)

    _run_main_loop(ts, lc, action_scheduler=scheduler)

    # setup 应该最先执行
    if len(execution_order) >= 2 and execution_order[0] == "setup":
        record("V9", "PASS", f"topological order: {execution_order}")
    else:
        record("V9", "FAIL", f"execution order wrong: {execution_order}")


def v10_backward_compat_no_scheduler():
    """V10: 不传 action_scheduler 时，loop 行为不变（向后兼容）。"""
    dispatcher = _build_dispatcher()
    provider = _make_fake_provider("no scheduler, just model")

    ts = _make_turn_state()
    lc = _make_loop_ctx(provider, dispatcher)

    result = _run_main_loop(ts, lc)  # 不传 action_scheduler

    if result and isinstance(result, str) and "no scheduler" in result.lower():
        record("V10", "PASS", "无 scheduler 时正常 fall through 到 model")
    else:
        record("V10", "FAIL", f"无 scheduler 时异常: {result[:80] if result else 'empty'}")


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    print("=== REAL-EVIDENCE-008 Gap A: Scheduler core.chat E2E ===\n")

    v1_non_empty_result()
    v2_action_plan_start()
    v3_node_enter_exit()
    v4_action_plan_complete()
    v5_condition_flags()
    v6_node_failure_halt()
    v7_not_no_crash_pass()
    v8_not_manual_harness()
    v9_multi_node_topological()
    v10_backward_compat_no_scheduler()

    # ── Summary ──
    print()
    passed = sum(1 for r in results if r["verdict"] == "PASS")
    failed = sum(1 for r in results if r["verdict"] == "FAIL")
    concerns = sum(1 for r in results if r["verdict"] == "CONCERN")
    total = len(results)

    print("---")
    print(f"Total: {total} | PASS: {passed} | FAIL: {failed} | CONCERN: {concerns}")
    if failed == 0 and concerns == 0:
        print("Verdict: ALL PASS — Gap A evidence chain closed")
    elif failed == 0:
        print("Verdict: PASS_WITH_CONCERNS")
    else:
        print("Verdict: FAIL — evidence chain incomplete")

    # 写结果文件
    output_path = _project_root / "docs" / "dogfood" / "real-evidence-008-gap-a-results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "evidence_id": "REAL-EVIDENCE-008-GAP-A",
        "description": "Scheduler core.chat E2E via _run_main_loop(action_scheduler=...)",
        "provider": "FakeProvider",
        "action_plan_source": "hand-built ActionPlan fixture",
        "total": total,
        "passed": passed,
        "failed": failed,
        "concerns": concerns,
        "results": results,
    }
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nResults written to: {output_path}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
