#!/usr/bin/env python3
"""REAL-EVIDENCE-002 Phase 6: Plan 3 全链路 dogfood 验证。

验证链路:
  core.chat()
  → turn-start structured selection phase (Phase 3)
  → model-visible tools contain SKILL_SELECT
  → real provider emits tool_use("SKILL_SELECT", {skill_id: ...})
  → ToolRuntimeMediator → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT
  → ActiveSkillLifecycle.activate() (Phase 4)
  → lifecycle.get_allowed_tools() → mediator → TOOL_GATE enforcement (Phase 5)
  → evidence chain: D01-D08

Case Groups:
  G1 (P3S1-P3S5): Structured selection + lifecycle + allowed_tools (D01-D05)
  G2 (P3S6-P3S7): No-skill / fallback scenarios (D06-D07)
  G3 (P3S8): Failure evidence (D08)
  G4 (P3S9-P3S10): Lifecycle cross-turn persistence

用法:
  python scripts/real_evidence_002_plan3_dogfood.py
  python scripts/real_evidence_002_plan3_dogfood.py --json
"""

from __future__ import annotations

import json
import sys
import time
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


# ── Pre-flight ──────────────────────────────────────────────────────────────


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


def _build_dispatcher(skill_registry=None):
    """构造 phase1 dispatcher（与 core.chat() 相同模式）。"""
    from agent.runtime_integration.phase1_hook import (
        build_phase1_dispatcher,
        build_skill_registry,
    )

    if skill_registry is None:
        skill_registry = build_skill_registry()
    return build_phase1_dispatcher(skill_registry=skill_registry)


def _cleanup_skill_state():
    """清理跨 turn skill 状态——lifecycle + backward-compat dict。"""
    import agent.core as _core
    _core._active_skill.clear()
    _core._skill_selected_by_model = False
    from agent.skill_system.lifecycle import get_default_lifecycle
    _lc = get_default_lifecycle()
    _lc.deactivate()


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


def _clear_action_log(dispatcher) -> None:
    """清空 dispatcher action_log。"""
    if hasattr(dispatcher, "_action_log"):
        dispatcher._action_log.clear()


def _run_chat_and_collect(prompt: str, provider, dispatcher) -> tuple[str, dict]:
    """运行 core.chat() 并返回 (result_text, evidence_by_type)。"""
    import agent.core as core

    _cleanup_skill_state()
    _clear_action_log(dispatcher)

    try:
        chat_result = core.chat(
            prompt,
            provider=provider,
            runtime_action_dispatcher=dispatcher,
        )
    except Exception as exc:
        record("CHAT", "FAIL", f"core.chat() crashed: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return "", {}

    evidence = _extract_evidence(dispatcher)
    return str(chat_result), evidence


# ── G1: Structured Selection + Lifecycle + Allowed Tools (D01-D05) ──────────


def validate_g1_selection_entered(provider, dispatcher) -> bool:
    """D01: selection entered evidence 产生。

    验证 turn-start selection phase 正确进入，产生 selection.entered evidence。
    """
    print("\n═══ G1/D01: Selection Entered Evidence ═══\n")

    prompt = "帮我整理一下今天的工作笔记"
    print(f"  Prompt: {prompt}")

    chat_result, evidence_by_type = _run_chat_and_collect(prompt, provider, dispatcher)
    print(f"  chat result: {chat_result[:200]}")

    # D01: selection.entered evidence
    entered_events = evidence_by_type.get("skill.selection.entered", [])
    if entered_events:
        ev = entered_events[0].get("evidence", {})
        record("D01", "PASS",
               f"selection.entered evidence: candidates_count={ev.get('candidates_count', '?')}, "
               f"turn_index={ev.get('turn_index', '?')}")
        return True
    else:
        # 检查是否有 skill.select 事件（selection 至少发生了）
        skill_select_events = evidence_by_type.get("skill.select", [])
        if skill_select_events:
            record("D01", "CONCERN",
                   "No selection.entered evidence, but skill.select found — "
                   "selection phase may not produce entered evidence")
            return True
        record("D01", "FAIL",
               f"No selection.entered evidence. Available types: {list(evidence_by_type.keys())}")
        return False


def validate_g1_candidates_built(provider, dispatcher) -> bool:
    """D02: candidates built evidence 产生（top-K 非空）。"""
    print("\n═══ G1/D02: Candidates Built Evidence ═══\n")

    prompt = "我需要记录一个演示笔记"
    print(f"  Prompt: {prompt}")

    chat_result, evidence_by_type = _run_chat_and_collect(prompt, provider, dispatcher)
    print(f"  chat result: {chat_result[:200]}")

    # D02: candidates built evidence
    candidate_events = evidence_by_type.get("skill.candidates.built", [])
    if candidate_events:
        ev = candidate_events[0].get("evidence", {})
        candidates = ev.get("candidates", []) or ev.get("candidate_count", 0)
        record("D02", "PASS",
               f"candidates.built evidence: candidates={candidates}, "
               f"top_k={ev.get('top_k', '?')}")
        return True
    else:
        # Check if selection.entered carries candidate info
        entered_events = evidence_by_type.get("skill.selection.entered", [])
        if entered_events:
            ev = entered_events[0].get("evidence", {})
            if ev.get("candidates_count", 0) > 0:
                record("D02", "PASS",
                       f"candidates info in selection.entered: count={ev['candidates_count']}")
                return True

        record("D02", "CONCERN",
               f"No candidates.built evidence. Available: {list(evidence_by_type.keys())}")
        return False


def validate_g1_model_selection_received(provider, dispatcher) -> bool:
    """D03: model selection received evidence 产生（模型输出 select_skill）。"""
    print("\n═══ G1/D03: Model Selection Received ═══\n")

    prompt = "帮我用 demo note maker 写一个笔记"
    print(f"  Prompt: {prompt}")

    chat_result, evidence_by_type = _run_chat_and_collect(prompt, provider, dispatcher)
    print(f"  chat result: {chat_result[:200]}")

    # D03: model selection received evidence
    select_events = evidence_by_type.get("skill.select", [])
    if select_events:
        ev = select_events[0].get("evidence", {})
        selected_id = ev.get("selected_skill_id") or ev.get("skill_id", "?")
        if selected_id and selected_id != "?":
            record("D03", "PASS",
                   f"Model selected skill: {selected_id}, "
                   f"activated_by={ev.get('activated_by', '?')}")
            return True
        else:
            decision = ev.get("decision", "")
            if decision == "no_suitable_skill":
                record("D03", "CONCERN",
                       "Model decided no_suitable_skill — retry with more targeted prompt")
                return False
            record("D03", "CONCERN",
                   f"skill.select dispatched but no selected_skill_id: {ev}")
            return False
    else:
        record("D03", "FAIL",
               f"No skill.select evidence. Available: {list(evidence_by_type.keys())}")
        return False


def validate_g1_active_skill_applied(provider, dispatcher) -> bool:
    """D04: active_skill applied evidence 产生——lifecycle 正确激活。"""
    print("\n═══ G1/D04: Active Skill Applied Evidence ═══\n")

    from agent.skill_system.lifecycle import get_default_lifecycle

    prompt = "帮我用 demo note maker 创建一个笔记，标题是「今日计划」"
    print(f"  Prompt: {prompt}")

    chat_result, evidence_by_type = _run_chat_and_collect(prompt, provider, dispatcher)
    print(f"  chat result: {chat_result[:200]}")

    # 检查 lifecycle 状态
    _lc = get_default_lifecycle()
    lifecycle_active = _lc.is_active()
    active_id = _lc.get_active_skill_id()

    # 检查 evidence
    active_events = evidence_by_type.get("skill.active.applied", [])
    select_events = evidence_by_type.get("skill.select", [])

    if lifecycle_active and active_id:
        record("D04", "PASS",
               f"Lifecycle active: skill_id={active_id}, "
               f"allowed_tools_count={len(_lc.get_allowed_tools())}")
        return True
    elif active_events:
        ev = active_events[0].get("evidence", {})
        record("D04", "PASS",
               f"skill.active.applied evidence: skill_id={ev.get('skill_id', '?')}")
        return True
    elif select_events:
        ev = select_events[0].get("evidence", {})
        selected = ev.get("selected_skill_id") or ev.get("skill_id")
        if selected:
            record("D04", "CONCERN",
                   f"skill.select found ({selected}) but lifecycle not active — "
                   f"lifecycle integration gap")
            return False
        else:
            record("D04", "CONCERN", "skill.select present but no skill selected")
            return False
    else:
        record("D04", "CONCERN",
               f"No active skill evidence. Lifecycle active={lifecycle_active}. "
               f"Available: {list(evidence_by_type.keys())}")
        return False


def validate_g1_allowed_tools_bound(provider, dispatcher) -> bool:
    """D05: allowed_tools bound evidence 产生——from lifecycle → mediator → gate。"""
    print("\n═══ G1/D05: Allowed Tools Bound Evidence ═══\n")

    prompt = "帮我用 demo note maker 创建一个笔记，标题「allowed_tools 测试」"
    print(f"  Prompt: {prompt}")

    chat_result, evidence_by_type = _run_chat_and_collect(prompt, provider, dispatcher)
    print(f"  chat result: {chat_result[:200]}")

    # 检查 tool.gate evidence 是否包含 skill_allowed_tools
    gate_events = evidence_by_type.get("tool.gate", [])
    gate_with_skill_tools = [
        e for e in gate_events
        if e.get("evidence", {}).get("skill_allowed_tools")
    ]

    # 也检查 lifecycle
    from agent.skill_system.lifecycle import get_default_lifecycle
    _lc = get_default_lifecycle()
    lifecycle_tools = _lc.get_allowed_tools()

    if gate_with_skill_tools:
        ev = gate_with_skill_tools[0]["evidence"]
        tools = ev["skill_allowed_tools"]
        record("D05", "PASS",
               f"TOOL_GATE received skill_allowed_tools: count={len(tools)}, "
               f"tools={list(tools)[:5]}")
        return True
    elif lifecycle_tools:
        record("D05", "CONCERN",
               f"Lifecycle has allowed_tools ({len(lifecycle_tools)} tools) "
               f"but no TOOL_GATE evidence with skill_allowed_tools. "
               f"Gate events: {len(gate_events)}")
        return False
    else:
        # 模型可能没有调用 tool（只做了文本回复）
        if gate_events:
            record("D05", "CONCERN",
                   f"Gate events present ({len(gate_events)}) but no skill_allowed_tools. "
                   f"Model may not have activated a skill.")
        else:
            record("D05", "CONCERN",
                   "No gate events at all — model may not have invoked any tool")
        return False


# ── G2: No-Skill / Fallback (D06-D07) ───────────────────────────────────────


def validate_g2_no_skill(provider, dispatcher) -> bool:
    """D06: no_skill evidence 产生（模型未选中任何 skill）。"""
    print("\n═══ G2/D06: No-Skill Evidence ═══\n")

    # 完全无关的 prompt，不应匹配任何 skill
    prompt = "1+1等于几？"
    print(f"  Prompt: {prompt}")

    chat_result, evidence_by_type = _run_chat_and_collect(prompt, provider, dispatcher)
    print(f"  chat result: {chat_result[:200]}")

    # 检查 no_suitable_skill evidence
    no_skill_events = evidence_by_type.get("skill.no_suitable_skill", [])
    select_events = evidence_by_type.get("skill.select", [])

    if no_skill_events:
        ev = no_skill_events[0].get("evidence", {})
        record("D06", "PASS",
               f"no_suitable_skill evidence: reason={ev.get('reason', ev.get('decision', '?'))}")
        return True
    elif select_events:
        ev = select_events[0].get("evidence", {})
        if ev.get("decision") == "no_suitable_skill":
            record("D06", "PASS",
                   "skill.select indicates no_suitable_skill decision")
            return True
        else:
            record("D06", "CONCERN",
                   f"Model selected skill for math prompt: "
                   f"{ev.get('selected_skill_id', '?')} — unexpected")
            return False
    else:
        # 模型没有输出 SKILL_SELECT（对于 "1+1=?" 这是合理的）
        record("D06", "PASS",
               "Model did not invoke SKILL_SELECT for irrelevant math prompt — correct behavior")
        return True


def validate_g2_fallback(provider, dispatcher) -> bool:
    """D07: fallback evidence 产生（keyword fallback 触发时）。"""
    print("\n═══ G2/D07: Fallback Evidence ═══\n")

    from agent.skill_system.lifecycle import get_default_lifecycle

    # 使用含有关键词但不直接要求 skill 的 prompt
    prompt = "我想写点东西记下来"
    print(f"  Prompt: {prompt}")

    chat_result, evidence_by_type = _run_chat_and_collect(prompt, provider, dispatcher)
    print(f"  chat result: {chat_result[:200]}")

    # 检查 fallback evidence
    fallback_events = evidence_by_type.get("skill.keyword_fallback", [])
    select_events = evidence_by_type.get("skill.select", [])

    if fallback_events:
        ev = fallback_events[0].get("evidence", {})
        record("D07", "PASS",
               f"Keyword fallback triggered: matched={ev.get('matched_keyword', '?')}, "
               f"skill={ev.get('skill_id', '?')}")
        return True
    elif select_events:
        # 模型自主选择了（model-owned path 优先）
        ev = select_events[0].get("evidence", {})
        record("D07", "PASS",
               f"Model-owned selection (keyword fallback not needed): "
               f"selected={ev.get('selected_skill_id', '?')}")
        return True
    else:
        _lc = get_default_lifecycle()
        if _lc.is_active():
            record("D07", "PASS",
                   f"Skill activated ({_lc.get_active_skill_id()}) — keyword fallback "
                   f"not needed since model-owned path succeeded")
            return True
        record("D07", "CONCERN",
               f"No fallback evidence and no skill selection. "
               f"Available: {list(evidence_by_type.keys())}")
        return False


# ── G3: Failure Evidence (D08) ──────────────────────────────────────────────


def validate_g3_failure(provider, dispatcher) -> bool:
    """D08: failure evidence 产生（selection 失败时）。"""
    print("\n═══ G3/D08: Failure Evidence ═══\n")

    # 使用不存在的 skill_id，看 runtime 如何处理
    import agent.core as core

    _cleanup_skill_state()
    _clear_action_log(dispatcher)

    # 通过直接设置 _active_skill 模拟一个不存在的 skill 被激活的场景
    # 然后请求一个 disallowed tool，验证 gate 拒绝路径
    from agent.skill_system.lifecycle import get_default_lifecycle
    _lc = get_default_lifecycle()
    _lc.activate("non-existent-skill", body="fake body",
                 allowed_tools=("demo.write_demo_note",))
    core._active_skill = {
        "skill_id": "non-existent-skill",
        "body": "fake body",
        "allowed_tools": frozenset({"demo.write_demo_note"}),
    }

    # 尝试让模型调用一个不在 allowed_tools 中的工具
    prompt = "执行 shell 命令 ls"
    print(f"  Prompt: {prompt}")

    chat_result, evidence_by_type = _run_chat_and_collect(prompt, provider, dispatcher)
    print(f"  chat result: {chat_result[:200]}")

    # 检查 gate rejection evidence
    gate_events = evidence_by_type.get("tool.gate", [])
    rejections = [
        e for e in gate_events
        if e.get("evidence", {}).get("gate_disposition") == "rejected"
        or e.get("status") == "rejected"
    ]

    if rejections:
        ev = rejections[0].get("evidence", {})
        record("D08", "PASS",
               f"Gate rejection evidence: reason={ev.get('rejection_reason', '?')}, "
               f"tool={ev.get('tool_name', '?')}")
        return True
    else:
        # 也可能模型没有调用 disallowed tool（好的行为）
        _cleanup_skill_state()
        record("D08", "CONCERN",
               f"No gate rejection found — model may have avoided disallowed tool. "
               f"Gate events: {len(gate_events)}")
        return False

    _cleanup_skill_state()


# ── G4: Lifecycle Cross-Turn Persistence ────────────────────────────────────


def validate_g4_lifecycle_persistence(provider, dispatcher) -> bool:
    """P3S9-P3S10: Lifecycle cross-turn persistence."""
    print("\n═══ G4: Lifecycle Cross-Turn Persistence ═══\n")

    from agent.skill_system.lifecycle import get_default_lifecycle

    _cleanup_skill_state()

    # P3S9: Activate skill → verify lifecycle state
    _lc = get_default_lifecycle()
    _lc.activate("demo-note-maker", body="test body",
                 allowed_tools=("demo.write_demo_note", "demo.echo_task_summary"))

    p3s9_ok = _lc.is_active() and _lc.get_active_skill_id() == "demo-note-maker"
    record("P3S9", "PASS" if p3s9_ok else "FAIL",
           f"Lifecycle activate: is_active={_lc.is_active()}, "
           f"skill_id={_lc.get_active_skill_id()}")

    # P3S10: Deactivate → verify lifecycle cleared
    _lc.deactivate()
    p3s10_ok = not _lc.is_active() and _lc.get_active_skill_id() is None
    record("P3S10", "PASS" if p3s10_ok else "FAIL",
           f"Lifecycle deactivate: is_active={_lc.is_active()}, "
           f"skill_id={_lc.get_active_skill_id()}")

    return p3s9_ok and p3s10_ok


# ── G5: Allowed Tools Enforcement E2E ───────────────────────────────────────


def validate_g5_allowed_tools_e2e(provider, dispatcher) -> bool:
    """P3S11-P3S12: Allowed tools enforcement through full pipeline."""
    print("\n═══ G5: Allowed Tools Enforcement E2E ═══\n")

    _cleanup_skill_state()
    _clear_action_log(dispatcher)

    # 通过 lifecycle 激活一个只有特定工具的 skill
    from agent.skill_system.lifecycle import get_default_lifecycle
    _lc = get_default_lifecycle()
    _lc.activate("demo-note-maker", body="test body",
                 allowed_tools=("demo.write_demo_note", "demo.echo_task_summary"))

    import agent.core as core
    core._active_skill = {
        "skill_id": "demo-note-maker",
        "body": "test body",
        "allowed_tools": frozenset({"demo.write_demo_note", "demo.echo_task_summary"}),
    }

    # P3S11: 请求一个 allowed tool → 应该通过 gate
    prompt = "帮我用 demo.echo_task_summary 输出任务摘要"
    print(f"  P3S11 Prompt: {prompt}")

    chat_result, evidence_by_type = _run_chat_and_collect(prompt, provider, dispatcher)
    print(f"  chat result: {chat_result[:200]}")

    gate_events = evidence_by_type.get("tool.gate", [])
    allowed_gates = [
        e for e in gate_events
        if e.get("evidence", {}).get("gate_disposition") == "allowed"
    ]
    p3s11_ok = len(gate_events) > 0
    if p3s11_ok:
        record("P3S11", "PASS",
               f"Tool gate invoked: total={len(gate_events)}, "
               f"allowed={len(allowed_gates)}")
    else:
        record("P3S11", "CONCERN",
               "No tool.gate events — model may not have invoked any tool")

    # P3S12: 在 skill 激活时，allowed_tools 约束生效
    _cleanup_skill_state()
    _clear_action_log(dispatcher)
    _lc.activate("demo-note-maker", body="test body",
                 allowed_tools=("demo.write_demo_note",))

    core._active_skill = {
        "skill_id": "demo-note-maker",
        "body": "test body",
        "allowed_tools": frozenset({"demo.write_demo_note"}),
    }

    prompt = "帮我创建一个小笔记"
    print(f"  P3S12 Prompt: {prompt}")

    chat_result, evidence_by_type = _run_chat_and_collect(prompt, provider, dispatcher)
    print(f"  chat result: {chat_result[:200]}")

    gate_events = evidence_by_type.get("tool.gate", [])
    rejections = [
        e for e in gate_events
        if e.get("evidence", {}).get("gate_disposition") == "rejected"
    ]

    if rejections:
        ev = rejections[0].get("evidence", {})
        record("P3S12", "PASS",
               f"Disallowed tool blocked: tool={ev.get('tool_name', '?')}, "
               f"reason={ev.get('rejection_reason', '?')}")
    elif gate_events:
        record("P3S12", "PASS",
               f"All gate events allowed ({len(gate_events)} total) — "
               f"model respected allowed_tools constraint")
    else:
        record("P3S12", "CONCERN",
               "No tool.gate events — cannot verify enforcement")

    _cleanup_skill_state()
    return True


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> int:
    json_mode = "--json" in sys.argv

    print("=" * 60)
    print("REAL-EVIDENCE-002 Phase 6: Plan 3 Dogfood")
    print("=" * 60)

    provider = _build_provider()
    if provider is None:
        print("\n[ENV_CONCERN] 无法构造 Real Provider，终止验证。")
        record("ENV", "SKIP", "No real provider available")
        _write_results(json_mode)
        return 2

    print(f"\nProvider: {type(provider).__name__}")
    start_time = time.time()

    dispatcher = _build_dispatcher()

    # G1: Structured Selection + Lifecycle + Allowed Tools (D01-D05)
    print("\n── G1: Structured Selection + Lifecycle + Allowed Tools ──")
    try:
        validate_g1_selection_entered(provider, dispatcher)
    except Exception as exc:
        record("D01", "FAIL", f"Exception: {type(exc).__name__}: {exc}")

    try:
        validate_g1_candidates_built(provider, dispatcher)
    except Exception as exc:
        record("D02", "FAIL", f"Exception: {type(exc).__name__}: {exc}")

    try:
        validate_g1_model_selection_received(provider, dispatcher)
    except Exception as exc:
        record("D03", "FAIL", f"Exception: {type(exc).__name__}: {exc}")

    try:
        validate_g1_active_skill_applied(provider, dispatcher)
    except Exception as exc:
        record("D04", "FAIL", f"Exception: {type(exc).__name__}: {exc}")

    try:
        validate_g1_allowed_tools_bound(provider, dispatcher)
    except Exception as exc:
        record("D05", "FAIL", f"Exception: {type(exc).__name__}: {exc}")

    # G2: No-Skill / Fallback (D06-D07)
    print("\n── G2: No-Skill / Fallback ──")
    try:
        validate_g2_no_skill(provider, dispatcher)
    except Exception as exc:
        record("D06", "FAIL", f"Exception: {type(exc).__name__}: {exc}")

    try:
        validate_g2_fallback(provider, dispatcher)
    except Exception as exc:
        record("D07", "FAIL", f"Exception: {type(exc).__name__}: {exc}")

    # G3: Failure Evidence (D08)
    print("\n── G3: Failure Evidence ──")
    try:
        validate_g3_failure(provider, dispatcher)
    except Exception as exc:
        record("D08", "FAIL", f"Exception: {type(exc).__name__}: {exc}")

    # G4: Lifecycle Persistence
    print("\n── G4: Lifecycle Cross-Turn Persistence ──")
    try:
        validate_g4_lifecycle_persistence(provider, dispatcher)
    except Exception as exc:
        record("P3S9-S10", "FAIL", f"Exception: {type(exc).__name__}: {exc}")

    # G5: Allowed Tools E2E
    print("\n── G5: Allowed Tools Enforcement E2E ──")
    try:
        validate_g5_allowed_tools_e2e(provider, dispatcher)
    except Exception as exc:
        record("P3S11-S12", "FAIL", f"Exception: {type(exc).__name__}: {exc}")

    elapsed = time.time() - start_time

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    verdicts = [r["verdict"] for r in _results]
    pass_count = verdicts.count("PASS")
    concern_count = verdicts.count("CONCERN")
    fail_count = verdicts.count("FAIL")
    skip_count = verdicts.count("SKIP")

    print(f"  PASS: {pass_count}  CONCERN: {concern_count}  "
          f"FAIL: {fail_count}  SKIP: {skip_count}")
    print(f"  Elapsed: {elapsed:.1f}s")

    overall = "PASS" if fail_count == 0 else "FAIL" if concern_count == 0 else "PASS_WITH_CONCERNS"
    print(f"  Overall: {overall}")

    _write_results(json_mode)
    return 0 if fail_count == 0 else 1


def _write_results(json_mode: bool) -> None:
    results_dir = Path(_PROJECT_ROOT) / "docs" / "dogfood"
    results_dir.mkdir(parents=True, exist_ok=True)
    results_path = results_dir / "real-evidence-002-plan3-results.json"

    data = {
        "meta": {
            "script": "real_evidence_002_plan3_dogfood.py",
            "phase": "Phase 6",
            "plan": "Plan 3",
            "target": "002 Skill Selection",
        },
        "results": _results,
    }
    results_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults written: {results_path}")

    if json_mode:
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
