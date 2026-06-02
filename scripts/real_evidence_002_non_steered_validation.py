#!/usr/bin/env python3
"""REAL-EVIDENCE-002 D-09: Non-prompt-steered semantic skill selection real validation.

验证链路:
  real provider → core.chat() → model sees skill descriptions → model decides
  whether to call SKILL_SELECT → skill activated or not → evidence collected.

非 prompt-steered 意味着:
  - 不直接说"用xx技能"、"activate skill X"
  - 用自然语言描述需求
  - 让模型自己判断是否需要 skill

Cases:
  C1-C3: 中文自然表达 (笔记/博客/模糊)
  C4-C5: 英文表达
  C6: negative trigger (数学 → demo-note-maker 排除)
  C7: no-skill (不应该选)
  C8: ambiguous (模型应澄清或跳过)

用法:
  python scripts/real_evidence_002_non_steered_validation.py
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


def _build_provider():
    from agent.provider.factory import build_model_provider_from_env
    provider = build_model_provider_from_env()
    if provider is None:
        return None
    from agent.provider.fake_provider import FakeProvider
    if isinstance(provider, FakeProvider):
        return None
    return provider


def _build_dispatcher():
    from agent.runtime_integration.phase1_hook import (
        build_phase1_dispatcher,
        build_skill_registry,
    )
    registry = build_skill_registry()
    return build_phase1_dispatcher(skill_registry=registry)


def _reset_chat_state():
    import agent.core as _core
    st = _core.get_state()
    st.task.status = "idle"
    st.task.current_plan = None
    st.task.user_goal = None
    st.task.current_step_index = 0
    st.task.pending_tool = None
    st.task.pending_user_input_request = None
    st.task.effective_review_request = False
    st.task.retry_count = 0
    st.task.last_error = None
    st.conversation.messages.clear()


def _cleanup_skill_state():
    import agent.core as _core
    _core._active_skill.clear()
    _core._skill_selected_by_model = False
    from agent.skill_system.lifecycle import get_default_lifecycle
    get_default_lifecycle().deactivate()


def _clear_action_log(dispatcher) -> None:
    if hasattr(dispatcher, "_action_log"):
        dispatcher._action_log.clear()


def _extract_evidence(dispatcher) -> dict[str, list[dict[str, Any]]]:
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


def run_case(prompt: str, provider, dispatcher) -> tuple[str, dict]:
    import agent.core as core
    _reset_chat_state()
    _cleanup_skill_state()
    _clear_action_log(dispatcher)

    try:
        chat_result = core.chat(
            prompt,
            provider=provider,
            runtime_action_dispatcher=dispatcher,
        )
    except Exception as exc:
        return f"CRASH:{type(exc).__name__}:{exc}", {}

    # auto-confirm plans
    attempts = 0
    while chat_result == "awaiting_plan_confirmation" and attempts < 3:
        attempts += 1
        try:
            chat_result = core.chat(
                "y", provider=provider,
                runtime_action_dispatcher=dispatcher,
            )
        except Exception:
            break

    evidence = _extract_evidence(dispatcher)
    return str(chat_result), evidence


def get_selected_skill(evidence: dict) -> str | None:
    """Extract selected skill_id from evidence."""
    skill_selects = evidence.get("skill.select", [])
    for s in skill_selects:
        sid = s.get("evidence", {}).get("selected_skill_id", "")
        if sid:
            return sid
    # also check for tool-based SKILL_SELECT
    tool_results = evidence.get("tool.result", [])
    for t in tool_results:
        sid = t.get("evidence", {}).get("selected_skill_id", "")
        if sid:
            return sid
    return None


def has_skill_select(evidence: dict) -> bool:
    return "skill.select" in evidence or "tool.invoke" in evidence


# ── Validation Cases ─────────────────────────────────────────────────────────


def validate(provider, dispatcher):
    print("\n" + "=" * 60)
    print("REAL-EVIDENCE-002 D-09: Non-Prompt-Steered Skill Selection")
    print("=" * 60)

    # ── C1: 中文 — 明确笔记需求 ──
    print("\n── C1: Chinese — note-making intent ──")
    prompt = "我今天开会讨论了很多内容，能帮我把关键点整理记录下来吗？"
    print(f"  Prompt: {prompt}")
    result, evidence = run_case(prompt, provider, dispatcher)
    skill = get_selected_skill(evidence)
    has_sel = has_skill_select(evidence)
    if skill == "demo-note-maker":
        record("C1", "PASS", "Correctly selected demo-note-maker", skill=skill, prompt=prompt)
    elif skill and skill != "demo-note-maker":
        record("C1", "CONCERN", f"Selected wrong skill: {skill}", skill=skill, prompt=prompt)
    elif has_sel:
        record("C1", "PARTIAL", "Skill selection triggered but skill_id unclear", prompt=prompt)
    else:
        record("C1", "CONCERN", "No skill selected for clear note-making request", prompt=prompt)

    # ── C2: 中文 — 明确博客需求 ──
    print("\n── C2: Chinese — blog-writing intent ──")
    prompt = "我最近学了一个新技术，想写一篇文章分享给团队，你能帮我吗？"
    print(f"  Prompt: {prompt}")
    result, evidence = run_case(prompt, provider, dispatcher)
    skill = get_selected_skill(evidence)
    has_sel = has_skill_select(evidence)
    if skill == "blog-writing":
        record("C2", "PASS", "Correctly selected blog-writing", skill=skill, prompt=prompt)
    elif skill and skill != "blog-writing":
        record("C2", "CONCERN", f"Selected wrong skill: {skill}", skill=skill, prompt=prompt)
    elif has_sel:
        record("C2", "PARTIAL", "Skill selection triggered but skill_id unclear", prompt=prompt)
    else:
        record("C2", "CONCERN", "No skill selected for blog-writing intent", prompt=prompt)

    # ── C3: 中文 — 模糊表达 ──
    print("\n── C3: Chinese — ambiguous request ──")
    prompt = "帮我写点东西"
    print(f"  Prompt: {prompt}")
    result, evidence = run_case(prompt, provider, dispatcher)
    skill = get_selected_skill(evidence)
    has_sel = has_skill_select(evidence)
    if not has_sel:
        record("C3", "PASS", "Correctly did NOT force-skill on ambiguous prompt", prompt=prompt)
    elif skill:
        record("C3", "CONCERN",
               f"Selected skill '{skill}' on ambiguous prompt — acceptable if reasonable",
               skill=skill, prompt=prompt)
    else:
        record("C3", "CONCERN", "Skill selection triggered on ambiguous prompt", prompt=prompt)

    # ── C4: 英文 — note intent ──
    print("\n── C4: English — note-making intent ──")
    prompt = "I need to jot down some todos from today's standup meeting."
    print(f"  Prompt: {prompt}")
    result, evidence = run_case(prompt, provider, dispatcher)
    skill = get_selected_skill(evidence)
    has_sel = has_skill_select(evidence)
    if skill == "demo-note-maker":
        record("C4", "PASS",
               "Correctly selected demo-note-maker for English prompt",
               skill=skill, prompt=prompt)
    elif skill:
        record("C4", "CONCERN", f"Selected different skill: {skill}", skill=skill, prompt=prompt)
    elif has_sel:
        record("C4", "PARTIAL", "Selection triggered, skill unclear", prompt=prompt)
    else:
        record("C4", "CONCERN", "No skill selected for note-making in English", prompt=prompt)

    # ── C5: 中英混合 ──
    print("\n── C5: Mixed — 中英混杂表达 ──")
    prompt = "我想 create a technical blog about Rust async programming，能帮我组织文章结构吗？"
    print(f"  Prompt: {prompt}")
    result, evidence = run_case(prompt, provider, dispatcher)
    skill = get_selected_skill(evidence)
    has_sel = has_skill_select(evidence)
    if skill == "blog-writing":
        record("C5", "PASS",
               "Correctly selected blog-writing for mixed-language prompt",
               skill=skill, prompt=prompt)
    elif skill:
        record("C5", "CONCERN", f"Selected different skill: {skill}", skill=skill, prompt=prompt)
    elif has_sel:
        record("C5", "PARTIAL", "Selection triggered, skill unclear", prompt=prompt)
    else:
        record("C5", "CONCERN", "No skill selected for clear blog request", prompt=prompt)

    # ── C6: 中文 — negative trigger (数学) ──
    print("\n── C6: Chinese — negative trigger (数学 → not demo-note-maker) ──")
    prompt = "帮我把今天学的数学公式整理成笔记"
    print(f"  Prompt: {prompt}")
    result, evidence = run_case(prompt, provider, dispatcher)
    skill = get_selected_skill(evidence)
    has_sel = has_skill_select(evidence)
    if skill == "demo-note-maker":
        record("C6", "FAIL",
               "demo-note-maker selected despite negative trigger '数学'",
               skill=skill, prompt=prompt)
    elif not has_sel:
        record("C6", "PASS",
               "Correctly avoided selecting blocked skill for math-related prompt",
               prompt=prompt)
    elif skill and skill != "demo-note-maker":
        record("C6", "PASS",
               f"Selected non-blocked skill '{skill}' instead of demo-note-maker",
               skill=skill, prompt=prompt)
    else:
        record("C6", "CONCERN", "Unclear selection behavior", prompt=prompt)

    # ── C7: 不应该选 skill 的场景 ──
    print("\n── C7: No-skill — general conversation ──")
    prompt = "你好，请问今天是什么日期？"
    print(f"  Prompt: {prompt}")
    result, evidence = run_case(prompt, provider, dispatcher)
    skill = get_selected_skill(evidence)
    has_sel = has_skill_select(evidence)
    if not has_sel:
        record("C7", "PASS", "Correctly did NOT select any skill for general chat", prompt=prompt)
    elif skill:
        record("C7", "CONCERN",
               f"Unexpectedly selected '{skill}' for general greeting",
               skill=skill, prompt=prompt)
    else:
        record("C7", "CONCERN", "Selection triggered on general chat", prompt=prompt)

    # ── C8: 中文 — 博客写作 (非 prompt-steered) ──
    print("\n── C8: Chinese — blog writing (non-steered) ──")
    prompt = "我最近在学 Rust，想分享一下学习心得"
    print(f"  Prompt: {prompt}")
    result, evidence = run_case(prompt, provider, dispatcher)
    skill = get_selected_skill(evidence)
    has_sel = has_skill_select(evidence)
    if skill == "blog-writing":
        record("C8", "PASS",
               "Correctly selected blog-writing for sharing intent",
               skill=skill, prompt=prompt)
    elif skill:
        record("C8", "CONCERN", f"Selected different skill: {skill}", skill=skill, prompt=prompt)
    elif has_sel:
        record("C8", "PARTIAL", "Selection triggered, skill unclear", prompt=prompt)
    else:
        record("C8", "CONCERN",
               "No skill selected — model may have responded directly",
               prompt=prompt)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("REAL-EVIDENCE-002 D-09 Non-Prompt-Steered Validation")
    print(f"Timestamp: {time.strftime('%Y-%m-%dT%H:%M:%S')}")

    provider = _build_provider()
    if provider is None:
        print("\nHARD_STOP: No real provider available.")
        record("PREFLIGHT", "FAIL", "No real provider", reason="ENV_CONCERN")
        return 1

    provider_type = type(provider).__name__
    record("PREFLIGHT", "PASS", f"Real provider built: {provider_type}", provider=provider_type)

    dispatcher = _build_dispatcher()
    record("PREFLIGHT", "PASS", "Dispatcher built")

    validate(provider, dispatcher)

    # ── Summary ──
    passes = sum(1 for r in _results if r["verdict"] == "PASS")
    fails = sum(1 for r in _results if r["verdict"] == "FAIL")
    concerns = sum(1 for r in _results if r["verdict"] == "CONCERN")
    partials = sum(1 for r in _results if r["verdict"] == "PARTIAL")
    total = len(_results)

    print(f"\n{'=' * 60}")
    print(
        f"Summary: {passes} PASS / {fails} FAIL / "
        f"{concerns} CONCERN / {partials} PARTIAL (total {total})"
    )
    print(f"{'=' * 60}")

    # Save results
    output_path = _PROJECT_ROOT / "docs" / "dogfood" / "real-evidence-002-non-steered-results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump({
            "evidence_id": "REAL-EVIDENCE-002",
            "phase": "D-09 non-prompt-steered semantic validation",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "provider_type": provider_type,
            "summary": {
                "pass": passes, "fail": fails,
                "concern": concerns, "partial": partials, "total": total,
            },
            "cases": _results,
        }, f, ensure_ascii=False, indent=2)

    print(f"\nResults saved to: {output_path}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
