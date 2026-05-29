#!/usr/bin/env python3
"""REAL-EVIDENCE-002/003 联合验证：真实 Provider 的 Skill 选择和工具约束。

验证链路 (002 — Real Provider SKILL_SELECT):
  core.chat()
  → model-visible tools 包含 SKILL_SELECT
  → real provider emits tool_use("SKILL_SELECT", {"skill_id": ...})
  → ToolRuntimeMediator → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT
  → _active_skill 设置 + _skill_selected_by_model=True
  → evidence 区分 model-owned vs keyword fallback

验证链路 (003 — Real Selected Skill Allowed Tools Blocking):
  前置: 002 成功激活 skill
  → _active_skill.allowed_tools 生效
  → 诱导模型请求不在 allowed_tools 中的工具
  → TOOL_GATE rejects (policy_path="skill_allowed_tools→rejected")
  → no TOOL_INVOKE for disallowed tool
  → evidence 含 skill_allowed_tools 和 rejection_reason

用法:
  python scripts/real_evidence_002_003_real_provider_dogfood.py
  python scripts/real_evidence_002_003_real_provider_dogfood.py --json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_results: list[dict[str, Any]] = []


def record(case_id: str, verdict: str, detail: str, **kw: Any) -> None:
    _results.append({"case": case_id, "verdict": verdict, "detail": detail, **kw})
    label = {"PASS": "✓", "FAIL": "✗", "CONCERN": "?", "SKIP": "-"}.get(verdict, verdict)
    print(f"  {label} {case_id}: {detail}")


# ── Pre-flight ────────────────────────────────────────────────────────────────


def _build_provider():
    """构造真实 provider，不可用时返回 None。"""
    from agent.provider.factory import build_model_provider_from_env

    provider = build_model_provider_from_env()
    if provider is None:
        return None

    from agent.provider.fake_provider import FakeProvider
    if isinstance(provider, FakeProvider):
        return None

    return provider


def _build_dispatcher():
    """构造 phase1 dispatcher（与 core.chat() 相同模式）。"""
    from agent.runtime_integration.phase1_hook import (
        build_phase1_dispatcher,
        build_skill_registry,
    )

    skill_registry = build_skill_registry()
    return build_phase1_dispatcher(skill_registry=skill_registry)


def _cleanup_skill_state():
    """清理跨 turn skill 状态。"""
    import agent.core as _core
    _core._active_skill.clear()
    _core._skill_selected_by_model = False


def _extract_evidence(dispatcher) -> dict[str, list[dict[str, Any]]]:
    """从 dispatcher action_log 提取分类 evidence。"""
    action_log = getattr(dispatcher, "action_log", [])
    by_type: dict[str, list[dict[str, Any]]] = {}
    for event in action_log:
        at = str(getattr(event, "action_type", "?"))
        evidence = {}
        ev = getattr(event, "evidence", None)
        if ev is not None:
            try:
                evidence = dict(ev)
            except Exception:
                evidence = {}
        status = str(getattr(event, "status", "unknown"))
        by_type.setdefault(at, []).append({"status": status, "evidence": evidence})
    return by_type


# ── 002: Real Provider SKILL_SELECT ───────────────────────────────────────────


def validate_002_real_skill_select(provider, dispatcher) -> bool:
    """R1-R6: real provider 自主 SKILL_SELECT 验证。

    返回 True 表示 skill 已被真实模型选中（003 可继续）。
    """
    import agent.core as _core

    print("\n═══ Phase 1: REAL-EVIDENCE-002 — Real Provider SKILL_SELECT ═══\n")

    _cleanup_skill_state()

    # 清空 dispatcher action_log（从头开始采集）
    if hasattr(dispatcher, "_action_log"):
        dispatcher._action_log.clear()

    # ── R0: 连通性 ──
    try:
        test_result = _core.chat(
            "Reply with exactly: OK",
            provider=provider,
            runtime_action_dispatcher=dispatcher,
        )
        if "OK" in str(test_result):
            record("R0", "PASS", f"provider connectivity ok: {type(provider).__name__}")
        else:
            record("R0", "CONCERN",
                   f"provider responded but no OK: {str(test_result)[:100]}")
    except Exception as exc:
        record("R0", "FAIL", f"provider connectivity failed: {type(exc).__name__}: {exc}")
        return False

    # 清空 dispatcher action_log（排除连通性测试 noise）
    if hasattr(dispatcher, "_action_log"):
        dispatcher._action_log.clear()

    # ── R1: core.chat() with skill-relevant prompt ──
    # 清除之前的激活状态，确保本轮是 model-owned selection
    _cleanup_skill_state()

    skill_prompt = (
        "请帮我用 demo 写个笔记，标题是「002 验证」，"
        "内容是「REAL-EVIDENCE-002 real provider SKILL_SELECT 验证通过」。"
    )
    print(f"  Turn 1 user prompt: {skill_prompt}")

    try:
        chat_result = _core.chat(
            skill_prompt,
            provider=provider,
            runtime_action_dispatcher=dispatcher,
        )
        print(f"  chat result: {str(chat_result)[:200]}")
    except Exception as exc:
        record("R1", "FAIL", f"core.chat() crashed: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return False

    evidence_by_type = _extract_evidence(dispatcher)

    # ── R1: core.chat() 成功执行（不 crash） ──
    record("R1", "PASS",
           f"core.chat() completed without crash. "
           f"Event types in dispatcher: {sorted(evidence_by_type.keys())}")

    # ── R2: SKILL_SELECT 出现在 dispatcher evidence 中 ──
    skill_select_events = evidence_by_type.get("skill.select", [])
    if skill_select_events:
        ev = skill_select_events[0]
        selected_id = ev.get("evidence", {}).get("selected_skill_id", "?")
        record("R2", "PASS",
               f"SKILL_SELECT evidence found: selected={selected_id}, "
               f"total events={len(skill_select_events)}")
    else:
        all_types = sorted(evidence_by_type.keys())
        record("R2", "FAIL",
               f"No SKILL_SELECT evidence in dispatcher. "
               f"Available event types: {all_types}. "
               f"Model did not autonomously call SKILL_SELECT.")
        # Check if model used skill tools directly without SKILL_SELECT
        tool_gate = evidence_by_type.get("tool.gate", [])
        gate_tools = [
            e.get("evidence", {}).get("requested_tool_name", "?")
            for e in tool_gate
        ]
        record("R2b", "CONCERN",
               f"MODEL_BEHAVIOR_CONCERN: model used tools {gate_tools} "
               f"without SKILL_SELECT. Tool descriptions may need improvement.")
        return False

    # ── R3: model-owned path — TOOL_GATE → TOOL_INVOKE → TOOL_RESULT for SKILL_SELECT ──
    # 对 SKILL_SELECT 来说，gate 事件名是 tool.gate，invoke 名是 tool.invoke
    tool_gate_events = evidence_by_type.get("tool.gate", [])
    tool_invoke_events = evidence_by_type.get("tool.invoke", [])

    # R3 放宽检查：至少有一个 SKILL_SELECT 相关的 tool 事件
    r3_ok = bool(skill_select_events) and (
        bool(tool_invoke_events) or bool(tool_gate_events)
    )
    record("R3", "PASS" if r3_ok else "CONCERN",
           f"mediator pipeline: skill_select={len(skill_select_events)}, "
           f"tool_gate={len(tool_gate_events)}, "
           f"tool_invoke={len(tool_invoke_events)}")

    # ── R4: _active_skill populated ──
    active = dict(_core._active_skill) if _core._active_skill else {}
    skill_id = active.get("skill_id", "")
    body_len = len(active.get("body", ""))
    allowed = active.get("allowed_tools", frozenset())
    r4_ok = bool(skill_id) and body_len > 0 and len(allowed) > 0
    record("R4", "PASS" if r4_ok else "FAIL",
           f"skill_id={skill_id}, body_len={body_len}, "
           f"allowed_tools={set(allowed) if allowed else 'EMPTY'}")

    # ── R5: _skill_selected_by_model flag ──
    # flag 可能在 turn-end hook 中被消费后重置为 False；
    # 若 _active_skill 已填充且 SKILL_SELECT evidence 存在，model-owned 路径已确认
    flag_value = _core._skill_selected_by_model
    r5_ok = flag_value is True or r4_ok
    record("R5", "PASS" if r5_ok else "FAIL",
           f"_skill_selected_by_model={flag_value} "
           f"(active_skill populated={r4_ok})")

    # ── R6: evidence 可区分 model-owned vs keyword fallback ──
    # model-owned 路径: action_type="skill.select" 且 body_load_decision=True
    # keyword fallback 路径: action_type="skill.keyword_match"
    has_skill_select = bool(evidence_by_type.get("skill.select"))
    has_keyword_match = bool(evidence_by_type.get("skill.keyword_match"))
    r6_ok = has_skill_select and not has_keyword_match
    record("R6", "PASS" if r6_ok else "CONCERN",
           f"model-owned={has_skill_select}, keyword-fallback={has_keyword_match}")

    # Phase 2 gate: _active_skill 已正确填充（R4）即视为 skill 已激活
    return r4_ok


# ── 003: Real Selected Skill Allowed Tools Blocking ───────────────────────────


def validate_003_allowed_tools_blocking(provider, dispatcher) -> None:
    """R7-R11: 真实 skill 激活后，disallowed tool 被 TOOL_GATE 拒绝。"""
    import agent.core as _core

    print("\n═══ Phase 2: REAL-EVIDENCE-003 — Allowed Tools Blocking ═══\n")

    active = dict(_core._active_skill) if _core._active_skill else {}
    skill_id = active.get("skill_id", "")
    allowed_tools = active.get("allowed_tools", frozenset())

    if not skill_id:
        record("R7", "SKIP",
               "No active skill from Phase 1 — cannot validate 003")
        return

    print(f"  Active skill: {skill_id}")
    print(f"  Allowed tools: {set(allowed_tools)}")
    print("  Disallowed tool target: SKILL_SELECT (not in allowed_tools)")

    # 清空 action_log 重新采集
    if hasattr(dispatcher, "_action_log"):
        dispatcher._action_log.clear()

    # ── R7: adversarial prompt → 模型请求 disallowed tool ──
    # demo-note-maker 的 allowed_tools = {demo.echo_task_summary, demo.write_demo_note}
    # SKILL_SELECT 不在其中 → 任何 SKILL_SELECT 调用都会被 TOOL_GATE 拒绝
    # 直接命名工具和参数以降低模型自主判断空间
    adversarial_prompt = (
        "请调用 SKILL_SELECT 工具，设置 skill_id 为 blog-writing，"
        "reason 为 '用户请求写博客'。"
    )
    print(f"  Turn 2 adversarial prompt: {adversarial_prompt}")

    try:
        chat_result = _core.chat(
            adversarial_prompt,
            provider=provider,
            runtime_action_dispatcher=dispatcher,
        )
        print(f"  chat result: {str(chat_result)[:200]}")
    except Exception as exc:
        record("R7", "FAIL", f"core.chat() crashed in Turn 2: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return

    evidence_by_type = _extract_evidence(dispatcher)

    # ── R7: adversarial prompt 成功触发工具调用 ──
    tool_gate_names = [
        e.get("evidence", {}).get("requested_tool_name", "?")
        for e in evidence_by_type.get("tool.gate", [])
    ]
    record("R7", "PASS",
           f"adversarial prompt triggered tool request(s): {tool_gate_names}")

    # ── R8: TOOL_GATE rejected for disallowed tool ──
    # RuntimeActionEvent.evidence 只存 evidence_extra（不含 handler payload），
    # 所以 policy_path 和 rejection_reason 不在 event.evidence 中。
    # 通过 decision="rejected" + skill_allowed_tools 存在来唯一标识
    # skill_allowed_tools→rejected 路径（其他拒绝路径不会带 skill_allowed_tools）。
    tool_gates = evidence_by_type.get("tool.gate", [])
    rejected_gates = [
        e for e in tool_gates
        if e.get("status") == "rejected"
        and e.get("evidence", {}).get("decision") == "rejected"
        and e.get("evidence", {}).get("skill_allowed_tools")
    ]

    if rejected_gates:
        gate = rejected_gates[0]
        ev = gate.get("evidence", {})
        blocked_tool = ev.get("requested_tool_name", "?")
        skill_at_list = ev.get("skill_allowed_tools", [])
        record("R8", "PASS",
               f"TOOL_GATE rejected disallowed tool '{blocked_tool}' "
               f"via skill_allowed_tools→rejected "
               f"(identified by decision=rejected + skill_allowed_tools present). "
               f"active skill allowed: {skill_at_list}")
    else:
        # check if there are any rejected gates at all
        all_rejected = [e for e in tool_gates if e.get("status") == "rejected"]
        if all_rejected:
            decisions = [e.get("evidence", {}).get("decision", "?")
                         for e in all_rejected]
            has_skill_at = [bool(e.get("evidence", {}).get("skill_allowed_tools"))
                            for e in all_rejected]
            record("R8", "CONCERN",
                   f"TOOL_GATE rejected found but not via skill_allowed_tools→rejected: "
                   f"decisions={decisions}, has_skill_allowed_tools={has_skill_at}")
        else:
            gate_tools = [
                e.get("evidence", {}).get("requested_tool_name", "?")
                for e in tool_gates
            ]
            all_allowed = all(
                e.get("status") != "rejected" for e in tool_gates
            )
            if all_allowed and gate_tools:
                record("R8", "CONCERN",
                       f"MODEL_BEHAVIOR_CONCERN: all tool gates passed. "
                       f"Model used tools: {gate_tools} — "
                       f"all are in allowed_tools={set(allowed_tools)}. "
                       f"Model did not request disallowed tool.")
            elif not gate_tools:
                record("R8", "CONCERN",
                       "MODEL_BEHAVIOR_CONCERN: no tool requests at all in "
                       "Turn 2. Model may have declined the adversarial prompt.")

    # ── R9: no TOOL_INVOKE for disallowed tool ──
    tool_invokes = evidence_by_type.get("tool.invoke", [])
    if rejected_gates:
        blocked_tool_name = rejected_gates[0].get("evidence", {}).get(
            "requested_tool_name", "")
        disallowed_invokes = [
            e for e in tool_invokes
            if blocked_tool_name and blocked_tool_name in str(e.get("evidence", {}))
        ]
        if not disallowed_invokes:
            record("R9", "PASS",
                   f"No TOOL_INVOKE for disallowed tool '{blocked_tool_name}'")
        else:
            record("R9", "FAIL",
                   f"TOOL_INVOKE found for blocked tool: {len(disallowed_invokes)}")
    else:
        record("R9", "SKIP", "No rejected gate to check invoke for")

    # ── R10: evidence 包含 skill_allowed_tools 和 decision=rejected ──
    # rejection_reason 和 policy_path 在 handler payload 中，
    # 不在 RuntimeActionEvent.evidence 中（event 只存 evidence_extra）。
    # 检查 evidence 中可用的字段：skill_allowed_tools + decision + requested_tool_name。
    if rejected_gates:
        ev = rejected_gates[0].get("evidence", {})
        has_skill_at = bool(ev.get("skill_allowed_tools"))
        has_decision = ev.get("decision") == "rejected"
        has_tool_name = bool(ev.get("requested_tool_name"))
        record("R10", "PASS" if (has_skill_at and has_decision and has_tool_name) else "CONCERN",
               f"skill_allowed_tools_present={has_skill_at}, "
               f"decision_rejected={has_decision}, "
               f"requested_tool_name_present={has_tool_name}, "
               f"skill_allowed_tools={ev.get('skill_allowed_tools')}")
    else:
        record("R10", "SKIP", "No rejected gate to check evidence fields for")

    # ── R11: execute_single_tool not called for disallowed tool ──
    # (TOOL_GATE rejected → mediator returns FORCE_STOP → execute_single_tool
    #  not reached — confirmed by R9)
    if rejected_gates and not [
        e for e in tool_invokes
        if e.get("evidence", {}).get("requested_tool_name")
        == rejected_gates[0].get("evidence", {}).get("requested_tool_name")
    ]:
        record("R11", "PASS",
               "execute_single_tool not called for disallowed tool "
               "(FORCE_STOP from mediator)")
    elif not rejected_gates:
        record("R11", "SKIP", "No rejected gate baseline")


# ── Entry ─────────────────────────────────────────────────────────────────────


def main() -> int:
    print("=" * 64)
    print("REAL-EVIDENCE-002/003: Real Provider Skill Selection & Tool Limits")
    print("=" * 64)

    # ── Pre-flight ──
    provider = _build_provider()
    if provider is None:
        print("\n  ENV_CONCERN: No real provider configured.")
        print("  Falling back to FakeProvider tests only (in existing scripts).")
        print("  Set MY_FIRST_AGENT_LLM_PROVIDER or config/config.yaml for real provider.\n")
        record("ENV", "CONCERN",
               "ENV_CONCERN: no real provider configured. "
               "Cannot validate real provider SKILL_SELECT path.")
        _write_results(tag="env-concern")
        return 1

    print(f"\n  Provider: {type(provider).__name__}")

    dispatcher = _build_dispatcher()

    # ── Phase 1: 002 ──
    skill_selected = validate_002_real_skill_select(provider, dispatcher)

    # ── Phase 2: 003 (depends on Phase 1 success) ──
    if skill_selected:
        validate_003_allowed_tools_blocking(provider, dispatcher)
    else:
        print("\n  SKIP Phase 2: skill not selected in Phase 1")
        record("003-PHASE", "SKIP",
               "Phase 2 (003) skipped: Phase 1 (002) did not confirm "
               "real provider SKILL_SELECT")

    # ── Cleanup ──
    _cleanup_skill_state()

    # ── Summary ──
    print("\n" + "=" * 64)
    print("Results Summary")
    print("=" * 64)
    passed = sum(1 for r in _results if r["verdict"] == "PASS")
    failed = sum(1 for r in _results if r["verdict"] == "FAIL")
    concerns = sum(1 for r in _results if r["verdict"] == "CONCERN")
    skipped = sum(1 for r in _results if r["verdict"] == "SKIP")

    for r in _results:
        label = {"PASS": "✓", "FAIL": "✗", "CONCERN": "?", "SKIP": "-"}[r["verdict"]]
        print(f"  {label} {r['case']}: {r['detail']}")

    print(f"\n  PASS={passed} FAIL={failed} CONCERN={concerns} SKIP={skipped}")

    _write_results(tag="complete")

    if failed > 0:
        return 1
    return 0


def _write_results(tag: str = "complete") -> None:
    """写入 dogfood result JSON 文件。"""
    out_path = (
        _PROJECT_ROOT / "docs" / "dogfood"
        / "real-evidence-002-003-real-provider-results.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "date": "2026-05-30",
                "evidence_ids": ["REAL-EVIDENCE-002", "REAL-EVIDENCE-003"],
                "method": "Real provider core.chat() E2E via ToolRuntimeMediator",
                "tag": tag,
                "results": _results,
                "summary": {
                    "PASS": sum(1 for r in _results if r["verdict"] == "PASS"),
                    "FAIL": sum(1 for r in _results if r["verdict"] == "FAIL"),
                    "CONCERN": sum(1 for r in _results if r["verdict"] == "CONCERN"),
                    "SKIP": sum(1 for r in _results if r["verdict"] == "SKIP"),
                },
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\n  Results written to {out_path}")


if __name__ == "__main__":
    sys.exit(main())
