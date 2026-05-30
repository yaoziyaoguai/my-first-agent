#!/usr/bin/env python3
"""REAL-EVIDENCE-002 硬化验证。

非引导式 prompt、多 skill 竞争、无匹配 skill、空 visible_skills、稳定性。


验证链路:
  core.chat()
  → real provider 自主决定是否调用 SKILL_SELECT
  → ToolRuntimeMediator → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT
  → evidence 区分 model-owned vs keyword fallback

Case Groups:
  G1 (R12-R14): Non-steered prompt — 不提及 demo 或具体 skill_id
  G2 (R15-R17): Multi-skill competition — ≥2 个候选 skill
  G3 (R18-R20): No suitable skill — 完全无关的 prompt
  G4 (R21-R23): Empty visible_skills — 无可用 skill
  G5 (R24-R26): Stability — 相同 prompt 运行 ≥3 次

用法:
  python scripts/real_evidence_002_hardening.py
  python scripts/real_evidence_002_hardening.py --json
"""

from __future__ import annotations

import json
import sys
import tempfile
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


def _clear_action_log(dispatcher) -> None:
    """清空 dispatcher action_log。"""
    if hasattr(dispatcher, "_action_log"):
        dispatcher._action_log.clear()


def _run_chat_and_collect(prompt: str, provider, dispatcher) -> tuple[str, dict]:
    """运行 core.chat() 并返回 (result_text, evidence_by_type)。"""
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


# ── G1: Non-steered prompt (R12-R14) ─────────────────────────────────────────


def validate_g1_non_steered_prompt(provider, dispatcher) -> bool:
    """G1: 不提及 demo 或具体 skill_id 的自然 prompt。

    返回 True 表示 skill 被合理选中（可继续 G2/G5）。
    """
    import agent.core as _core

    print("\n═══ G1: Non-Steered Prompt Skill Selection ═══\n")

    # 自然的笔记请求，不出现 "demo" 字样
    prompt = "帮我记一下今天的待办事项：买菜、洗车、取快递"
    print(f"  Prompt: {prompt}")

    chat_result, evidence_by_type = _run_chat_and_collect(prompt, provider, dispatcher)
    print(f"  chat result: {chat_result[:200]}")

    # R12: core.chat() 不 crash，返回有意义响应
    r12_ok = len(chat_result) > 10
    record("R12", "PASS" if r12_ok else "FAIL",
           f"core.chat() completed: result_len={len(chat_result)}, "
           f"meaningful={'yes' if r12_ok else 'no'}")

    # R13: SKILL_SELECT evidence — 模型自主选择 skill
    skill_select_events = evidence_by_type.get("skill.select", [])
    # Debug: print evidence keys for diagnosis
    if skill_select_events:
        ev_keys = list(skill_select_events[0].get("evidence", {}).keys())
        print(f"  [DEBUG] skill.select evidence keys: {ev_keys}")
        print(f"  [DEBUG] skill.select evidence: {skill_select_events[0].get('evidence', {})}")
    if skill_select_events:
        ev = skill_select_events[0].get("evidence", {})
        selected_id = ev.get("selected_skill_id") or ev.get("skill_id", "?")
        decision = ev.get("decision", "")
        if selected_id and selected_id != "?":
            record("R13", "PASS",
                   f"Non-steered prompt → SKILL_SELECT: selected={selected_id}")
            r13_pass = True
        elif decision == "no_suitable_skill":
            record("R13", "CONCERN",
                   f"Non-steered prompt → SKILL_SELECT dispatched but "
                   f"no_suitable_skill. Evidence keys: {list(ev.keys())}")
            r13_pass = False
        else:
            record("R13", "CONCERN",
                   f"Non-steered prompt → SKILL_SELECT event present but "
                   f"no selected_skill_id. Evidence: {ev}")
            r13_pass = False
    else:
        # 检查是否有 skill.no_suitable_skill 事件
        no_match_events = evidence_by_type.get("skill.no_suitable_skill", [])
        keyword_events = evidence_by_type.get("skill.keyword_match", [])
        if no_match_events:
            record("R13", "FAIL",
                   "Non-steered prompt → skill.no_suitable_skill: "
                   "model did not select any skill for note-taking request")
            r13_pass = False
        elif keyword_events:
            record("R13", "CONCERN",
                   f"Non-steered prompt → keyword fallback (not model-owned). "
                   f"keyword_match events: {len(keyword_events)}")
            r13_pass = False
        else:
            all_types = sorted(evidence_by_type.keys())
            record("R13", "FAIL",
                   f"Non-steered prompt → no SKILL_SELECT. "
                   f"Event types: {all_types}. "
                   f"Model did not recognize note-taking intent.")
            r13_pass = False

    # R14: _active_skill populated correctly
    active = dict(_core._active_skill) if _core._active_skill else {}
    skill_id = active.get("skill_id", "")
    body_len = len(active.get("body", ""))
    allowed = active.get("allowed_tools", frozenset())
    r14_ok = bool(skill_id) and body_len > 0 and len(allowed) > 0
    record("R14", "PASS" if r14_ok else "FAIL",
           f"skill_id={skill_id}, body_len={body_len}, "
           f"allowed_tools={set(allowed) if allowed else 'EMPTY'}")

    return r13_pass and r14_ok


# ── G2: Multi-skill competition (R15-R17) ─────────────────────────────────────


def _create_temp_second_skill() -> str:
    """在临时目录创建一个最小化的第二 skill descriptor。

    返回临时目录路径。调用方负责清理。
    """
    tmpdir = tempfile.mkdtemp(prefix="mfa_test_skill_")
    skill_dir = Path(tmpdir) / "quick-translator"
    skill_dir.mkdir(parents=True)

    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("""---
name: quick-translator
description: 快速翻译工具。当用户要求"翻译"、"translate"、"汉译英"、"英译汉"时匹配。
version: 0.1.0
status: active
risk_level: low
tags:
  - translate
  - language
  - utility
allowed_tools:
  - demo.echo_task_summary
memory_scope: none
---

# Quick Translator

你是一个快速翻译工具。当用户要求翻译内容时，使用 demo.echo_task_summary 输出翻译结果。
""", encoding="utf-8")

    return tmpdir


def validate_g2_multi_skill_competition(provider, dispatcher) -> None:
    """G2: 多 skill 竞争 — 至少 2 个候选 skill 时模型正确选择。

    NOTE: core.chat() 内部构建自己的 skill_registry，无法从外部注入额外 skill。
    本测试通过直接调用 select_skill_for_real_provider() 验证多 skill 竞争逻辑，
    并用 core.chat() 验证单 skill 场景下的模型行为。
    """

    print("\n═══ G2: Multi-Skill Competition ═══\n")

    # ── R15: 多 skill 竞争逻辑验证（select_skill_for_real_provider 直接调用）──
    from agent.skill_selection import select_skill_for_real_provider
    from agent.skill_system.descriptor import SkillDescriptor

    candidates = [
        SkillDescriptor(
            name="demo-note-maker",
            description="围绕 demo 工具创建本地任务笔记。当用户要求写笔记、记录任务时匹配。",
            version="0.1.0", status="active", risk_level="low",
            tags=("demo", "note", "local"),
            allowed_tools=("demo.echo_task_summary", "demo.write_demo_note"),
            memory_scope="none", root=None, manifest_path=None,
        ),
        SkillDescriptor(
            name="quick-translator",
            description="快速翻译工具。当用户要求翻译、translate、汉译英、英译汉时匹配。",
            version="0.1.0", status="active", risk_level="low",
            tags=("translate", "language", "utility"),
            allowed_tools=("demo.echo_task_summary",),
            memory_scope="none", root=None, manifest_path=None,
        ),
    ]

    # 笔记请求 → 应选 demo-note-maker
    note_decision = select_skill_for_real_provider("帮我写个笔记记录今天的会议", candidates)
    if note_decision and note_decision["selected_skill_id"] == "demo-note-maker":
        nd_score = note_decision["match_score"]
        nd_reason = note_decision["selection_reason"]
        record("R15a", "PASS",
               "Note request → demo-note-maker selected "
               f"(score={nd_score}, reason={nd_reason})")
    elif note_decision:
        nd_sid = note_decision["selected_skill_id"]
        nd_score = note_decision["match_score"]
        record("R15a", "CONCERN",
               f"Note request → {nd_sid} selected "
               f"instead of demo-note-maker (score={nd_score})")
    else:
        record("R15a", "FAIL",
               "Note request → no skill selected (should match demo-note-maker)")

    # 翻译请求 → 应选 quick-translator
    trans_decision = select_skill_for_real_provider("帮我把这段话翻译成英文", candidates)
    if trans_decision and trans_decision["selected_skill_id"] == "quick-translator":
        td_score = trans_decision["match_score"]
        td_reason = trans_decision["selection_reason"]
        record("R15b", "PASS",
               "Translation request → quick-translator selected "
               f"(score={td_score}, reason={td_reason})")
    elif trans_decision:
        td_sid = trans_decision["selected_skill_id"]
        td_score = trans_decision["match_score"]
        record("R15b", "CONCERN",
               f"Translation request → {td_sid} selected "
               f"instead of quick-translator (score={td_score})")
    else:
        record("R15b", "FAIL",
               "Translation request → no skill selected (should match quick-translator)")

    # ── R16: 多 skill 竞争 — core.chat() 实测（仅 1 skill 限制）──
    print("\n  R16: core.chat() 实测 — 当前仅 demo-note-maker 在 registry 中。")
    print("  多 skill 竞争的 core.chat() E2E 需向 registry 注入第二个 skill。")
    record("R16", "CONCERN",
           "LIMITATION: core.chat() builds its own skill_registry internally; "
           "cannot inject second skill without production code change. "
           "Multi-skill competition validated at select_skill_for_real_provider() "
           "level only (R15a/R15b). Full core.chat() E2E multi-skill requires "
           "plumbing skill_registry as a chat() parameter (B7/B8 scope).")

    # ── R17: 当前单 skill 场景下，模型仍应合理选择 ──
    # 使用中性的笔记请求
    prompt = "帮我记录一下：明天下午3点开会讨论项目进度"
    print(f"\n  R17 prompt: {prompt}")
    chat_result, evidence_by_type = _run_chat_and_collect(prompt, provider, dispatcher)

    skill_select_events = evidence_by_type.get("skill.select", [])
    if skill_select_events:
        ev = skill_select_events[0].get("evidence", {})
        selected_id = ev.get("selected_skill_id", "?")
        record("R17", "PASS",
               f"Single-skill scenario: model selected {selected_id} "
               f"for note-taking request")
    else:
        record("R17", "CONCERN",
               f"Single-skill scenario: no SKILL_SELECT. "
               f"Model may have answered directly without using skill. "
               f"Event types: {sorted(evidence_by_type.keys())}")


# ── G3: No suitable skill (R18-R20) ───────────────────────────────────────────


def validate_g3_no_suitable_skill(provider, dispatcher) -> None:
    """G3: 完全无关的 prompt — 模型不应选择 demo-note-maker。"""
    import agent.core as _core

    print("\n═══ G3: No Suitable Skill ═══\n")

    # 数学问题 — 与笔记完全无关
    prompt = "1+1等于多少？请直接回答。"
    print(f"  Prompt: {prompt}")

    chat_result, evidence_by_type = _run_chat_and_collect(prompt, provider, dispatcher)
    print(f"  chat result: {chat_result[:200]}")

    # R18: core.chat() 不 crash，返回有意义响应
    r18_ok = len(chat_result) > 5 and ("2" in chat_result or "二" in chat_result)
    record("R18", "PASS" if r18_ok else "CONCERN",
           f"core.chat() completed: result_len={len(chat_result)}, "
           f"answer_contains_2={'yes' if r18_ok else 'no'}")

    # R19: 不应有 SKILL_SELECT（数学问题不应匹配笔记 skill）
    skill_select_events = evidence_by_type.get("skill.select", [])
    keyword_events = evidence_by_type.get("skill.keyword_match", [])

    if not skill_select_events and not keyword_events:
        record("R19", "PASS",
               "No SKILL_SELECT or keyword_match for unrelated math question — "
               "model correctly did not select a skill")
    elif skill_select_events:
        ev = skill_select_events[0].get("evidence", {})
        selected_id = ev.get("selected_skill_id", "?")
        record("R19", "CONCERN",
               f"MODEL_BEHAVIOR_CONCERN: model called SKILL_SELECT({selected_id}) "
               f"for math question. Model may be over-eager to use skills.")
    elif keyword_events:
        record("R19", "CONCERN",
               "keyword_match triggered for math question — "
               "keyword fallback matched but shouldn't for unrelated input")

    # R20: _active_skill 不应被填充（非 skill 请求）
    active = dict(_core._active_skill) if _core._active_skill else {}
    skill_id = active.get("skill_id", "")
    if not skill_id:
        record("R20", "PASS",
               "_active_skill not populated for non-skill request")
    else:
        record("R20", "CONCERN",
               f"_active_skill populated with {skill_id} for unrelated request — "
               f"may indicate false positive skill matching")


# ── G4: Empty visible_skills (R21-R23) ────────────────────────────────────────


def validate_g4_empty_visible_skills(provider, dispatcher) -> None:
    """G4: 空 visible_skills — 不应触发 SKILL_SELECT。

    NOTE: core.chat() 内部构建自己的 skill_registry，无法注入空 registry。
    本测试验证 select_skill_for_real_provider() 对空 candidates 的处理。
    """
    print("\n═══ G4: Empty visible_skills ═══\n")

    from agent.skill_selection import select_skill_for_real_provider

    # R21: select_skill_for_real_provider() 空 candidates → None
    decision = select_skill_for_real_provider("帮我写个笔记", [])
    if decision is None:
        record("R21", "PASS",
               "select_skill_for_real_provider([]) → None — "
               "empty candidates handled safely")
    else:
        record("R21", "FAIL",
               f"select_skill_for_real_provider([]) → {decision} — "
               f"should return None for empty candidates")

    # R22: 空 registry — core.chat() E2E limitation
    print("\n  R22: core.chat() E2E with empty visible_skills — LIMITATION.")
    print("  core.chat() builds its own skill_registry via build_skill_registry().")
    print("  Cannot inject empty registry without production code change.")
    record("R22", "CONCERN",
           "LIMITATION: core.chat() always builds its own skill_registry with "
           "skills/ directory. Empty visible_skills E2E requires chat() to accept "
           "skill_registry parameter (production code change — B7/B8 scope). "
           "Unit-level safety verified at R21.")

    # R23: 正常请求在空 registry 下的行为 — 验证不会 crash
    # 通过构建空 registry 的 dispatcher 验证 handler 路径
    from agent.skill_system.registry import SkillRegistry

    empty_registry = SkillRegistry()
    # 不添加任何 root → list_visible() 返回空
    visible = empty_registry.list_visible()
    if len(visible) == 0:
        record("R23", "PASS",
               f"Empty SkillRegistry: list_visible()={visible} — "
               f"handler should receive empty candidates and return no_suitable_skill")
    else:
        record("R23", "FAIL",
               f"Empty SkillRegistry returned {len(visible)} visible skills — "
               f"unexpected")


# ── G5: Stability (R24-R26) ───────────────────────────────────────────────────


def validate_g5_stability(provider, dispatcher) -> None:
    """G5: 相同 prompt 运行 ≥3 次，记录稳定性。"""
    import agent.core as _core

    print("\n═══ G5: Stability (3 runs) ═══\n")

    prompt = "帮我记一下今天的待办事项：买菜、洗车、取快递"
    runs = []

    for i in range(3):
        print(f"\n  ── Run {i+1}/3 ──")
        _cleanup_skill_state()
        _clear_action_log(dispatcher)

        try:
            chat_result = core.chat(
                prompt,
                provider=provider,
                runtime_action_dispatcher=dispatcher,
            )
        except Exception as exc:
            record(f"R24-RUN{i+1}", "FAIL",
                   f"Run {i+1} crashed: {type(exc).__name__}: {exc}")
            runs.append({"run": i+1, "crashed": True, "skill_selected": None})
            continue

        evidence_by_type = _extract_evidence(dispatcher)
        skill_select_events = evidence_by_type.get("skill.select", [])
        active = dict(_core._active_skill) if _core._active_skill else {}
        skill_selected = active.get("skill_id", None) if active else None

        run_info = {
            "run": i + 1,
            "crashed": False,
            "skill_selected": skill_selected,
            "skill_select_events": len(skill_select_events),
            "result_len": len(chat_result),
            "event_types": sorted(evidence_by_type.keys()),
        }
        runs.append(run_info)

        if skill_selected:
            print(f"    skill_selected={skill_selected}, "
                  f"result_len={len(chat_result)}, "
                  f"events={sorted(evidence_by_type.keys())}")
        else:
            print(f"    no skill selected, result_len={len(chat_result)}, "
                  f"events={sorted(evidence_by_type.keys())}")

    # R24: 所有 run 不 crash
    crashes = [r for r in runs if r["crashed"]]
    r24_ok = len(crashes) == 0
    record("R24", "PASS" if r24_ok else "FAIL",
           f"All 3 runs completed without crash: "
           f"crashes={len(crashes)}/3")

    # R25: skill 选择一致性
    selected_skills = [r["skill_selected"] for r in runs if not r["crashed"]]
    unique_skills = set(s for s in selected_skills if s)
    if len(unique_skills) == 1 and None not in unique_skills:
        record("R25", "PASS",
               f"Consistent skill selection across runs: "
               f"skills={unique_skills}, runs={len(selected_skills)}")
    elif len(unique_skills) > 1:
        record("R25", "CONCERN",
               f"MODEL_BEHAVIOR_CONCERN: inconsistent skill selection: "
               f"skills={unique_skills} across {len(selected_skills)} runs. "
               f"Model behavior is non-deterministic for same prompt.")
    elif None in unique_skills or not unique_skills:
        record("R25", "CONCERN",
               f"No skill selected in some runs: "
               f"skills_per_run={selected_skills}")

    # R26: 所有 run 产生 SKILL_SELECT evidence
    select_counts = [r["skill_select_events"] for r in runs if not r["crashed"]]
    all_have_select = all(c > 0 for c in select_counts)
    record("R26", "PASS" if all_have_select else "CONCERN",
           f"SKILL_SELECT evidence per run: {select_counts} "
           f"(all_have_select={all_have_select})")

    # 附加 debug 信息
    record("R26-DEBUG", "PASS",
           f"Stability detail: {json.dumps(runs, ensure_ascii=False, default=str)}")


# ── Entry ─────────────────────────────────────────────────────────────────────


def main() -> int:
    print("=" * 64)
    print("REAL-EVIDENCE-002 Hardening: Natural Skill Selection Validation")
    print("=" * 64)

    # ── Pre-flight ──
    provider = _build_provider()
    if provider is None:
        print("\n  ENV_CONCERN: No real provider configured.")
        record("ENV", "CONCERN",
               "ENV_CONCERN: no real provider configured. "
               "Cannot validate 002 hardening cases.")
        _write_results(tag="env-concern")
        return 1

    print(f"\n  Provider: {type(provider).__name__}")

    dispatcher = _build_dispatcher()
    _cleanup_skill_state()

    # ── G1: Non-steered prompt ──
    g1_pass = validate_g1_non_steered_prompt(provider, dispatcher)

    if not g1_pass:
        print("\n  ⚠ G1 did not fully pass — remaining groups may be affected.")

    # ── G2: Multi-skill competition ──
    validate_g2_multi_skill_competition(provider, dispatcher)

    # ── G3: No suitable skill ──
    validate_g3_no_suitable_skill(provider, dispatcher)

    # ── G4: Empty visible_skills ──
    validate_g4_empty_visible_skills(provider, dispatcher)

    # ── G5: Stability x3 ──
    validate_g5_stability(provider, dispatcher)

    # ── Cleanup ──
    _cleanup_skill_state()

    # ── Summary ──
    print("\n" + "=" * 64)
    print("Results Summary — REAL-EVIDENCE-002 Hardening")
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
        / "real-evidence-002-hardening-results.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "date": "2026-05-30",
                "evidence_id": "REAL-EVIDENCE-002",
                "method": "Real provider core.chat() E2E via ToolRuntimeMediator — "
                         "002 hardening: non-steered prompt, multi-skill competition, "
                         "no suitable skill, empty visible_skills, stability",
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


# 延迟 import 以允许 path setup
import agent.core as core  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
