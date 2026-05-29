#!/usr/bin/env python3
"""REAL-EVIDENCE-002 验证脚本：模型自主选择 Skill 路径。

验证：
1. SKILL_SELECT 注册为 TOOL_REGISTRY 标准工具
2. SKILL_SELECT 出现在 get_model_visible_tools()
3. SKILL_SELECT tool_use → ToolRuntimeMediator pipeline (gate/invoke/result)
4. _skill_selected_by_model flag 在 tool func 调用后正确设置
5. selected_skill.allowed_tools 绑定到 mediator
6. keyword fallback 仍作为 fallback 保留
7. 结果不依赖 direct-call（走 mediator pipeline）

用法：
  python scripts/real_evidence_002_skill_model_selection.py
  python scripts/real_evidence_002_skill_model_selection.py --json   # JSON 输出
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock


def _make_mock_state():
    """构造完整的 mock state，所有数值字段设置为实际 int 值。"""
    state = MagicMock()
    state.task.tool_execution_log = {}
    state.task.current_step_index = 0
    state.task.pending_tool = None
    state.task.status = "running"
    state.task.pending_user_input_request = None
    state.task.loop_iterations = 0
    state.task.consecutive_end_turn_without_progress = 0
    state.task.current_plan = None
    state.task.tool_call_count = 0
    state.conversation.messages = []
    return state

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── 输出格式 ────────────────────────────────────────────────────────────────

_results: list[dict[str, Any]] = []


def _record(check_id: str, passed: bool, detail: str = "") -> None:
    _results.append({"check": check_id, "passed": passed, "detail": detail})
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {check_id}: {detail}")


# ── 验证逻辑 ────────────────────────────────────────────────────────────────


def check_v1_skill_select_in_registry() -> None:
    """V1: SKILL_SELECT 在 TOOL_REGISTRY 中注册。"""
    from agent.skill_system.skill_tool import _ensure_skill_select_registered
    from agent.tool_registry import TOOL_REGISTRY

    _ensure_skill_select_registered()
    if "SKILL_SELECT" not in TOOL_REGISTRY:
        return _record("V1", False, "SKILL_SELECT 不在 TOOL_REGISTRY 中")

    entry = TOOL_REGISTRY["SKILL_SELECT"]
    ok = all([
        entry["name"] == "SKILL_SELECT",
        callable(entry["func"]),
        entry["confirmation"] == "never",
        entry["capability"] == "skill_lifecycle",
    ])
    _record("V1", ok, f"name={entry['name']}, callable={callable(entry['func'])}")


def check_v2_visible_in_model_tools() -> None:
    """V2: SKILL_SELECT 在 get_model_visible_tools() 返回列表中。"""
    from agent.skill_system.skill_tool import _ensure_skill_select_registered
    from agent.tool_registry import get_model_visible_tools

    _ensure_skill_select_registered()
    names = {t["name"] for t in get_model_visible_tools()}
    _record("V2", "SKILL_SELECT" in names,
            f"visible tools={len(names)}, SKILL_SELECT present={'SKILL_SELECT' in names}")


def check_v3_tool_func_valid_skill() -> None:
    """V3: 有效 skill_id → tool func 返回激活确认。"""
    from agent.skill_system.skill_tool import _skill_select_tool_func

    result = _skill_select_tool_func("demo-note-maker")
    ok = "已激活" in result and "demo-note-maker" in result
    _record("V3", ok, f"result preview: {result[:100]}")


def check_v4_tool_func_unknown_skill() -> None:
    """V4: 未知 skill_id → 返回错误信息，不 crash。"""
    from agent.skill_system.skill_tool import _skill_select_tool_func

    result = _skill_select_tool_func("non-existent-skill-xyz")
    ok = "已激活" not in result
    _record("V4", ok, f"result preview: {result[:100]}")


def check_v5_skill_selected_flag() -> None:
    """V5: _skill_selected_by_model 在 tool func 后为 True。"""
    import agent.core as _core
    from agent.skill_system.skill_tool import _skill_select_tool_func

    _core._skill_selected_by_model = False
    _skill_select_tool_func("demo-note-maker")
    _record("V5", _core._skill_selected_by_model is True,
            f"flag={_core._skill_selected_by_model}")


def check_v6_mediator_pipeline() -> None:
    """V6: SKILL_SELECT tool_use → mediate() → gate/invoke/result evidence。"""
    from agent.runtime_integration import (
        ActionHandlerRegistry,
        RuntimeActionDispatcher,
        RuntimeActionType,
    )
    from agent.runtime_integration.evidence import RuntimeActionModuleObserver
    from agent.runtime_integration.tool_gate import ToolGateHandler
    from agent.runtime_integration.tool_invoke import ToolInvokeHandler
    from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler
    from agent.skill_system.skill_tool import _ensure_skill_select_registered
    from agent.tool_runtime_mediator import ToolRuntimeMediator

    _ensure_skill_select_registered()

    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
    registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
    registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
    dispatcher = RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )

    state = _make_mock_state()
    turn_state = MagicMock()
    turn_state.round_tool_traces = []

    mediator = ToolRuntimeMediator(
        dispatcher, state=state, turn_state=turn_state,
        turn_context={}, messages=[],
    )

    block = MagicMock()
    block.type = "tool_use"
    block.id = "toolu_002_test"
    block.name = "SKILL_SELECT"
    block.input = {"skill_id": "demo-note-maker", "reason": "validation"}

    result = mediator.mediate(block)

    action_types = [str(e.action_type) for e in dispatcher.action_log]
    has_gate = "tool.gate" in action_types
    has_invoke = "tool.invoke" in action_types
    has_result = "tool.result" in action_types

    ok = result is None and has_gate and has_invoke and has_result
    _record("V6", ok,
            f"result={result!r}, gate={has_gate}, invoke={has_invoke}, result={has_result}")


def check_v7_active_skill_after_mediator() -> None:
    """V7: mediator 执行后 _active_skill 正确填充。"""
    import agent.core as _core
    from agent.runtime_integration import (
        ActionHandlerRegistry,
        RuntimeActionDispatcher,
        RuntimeActionType,
    )
    from agent.runtime_integration.evidence import RuntimeActionModuleObserver
    from agent.runtime_integration.tool_gate import ToolGateHandler
    from agent.runtime_integration.tool_invoke import ToolInvokeHandler
    from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler
    from agent.skill_system.skill_tool import _ensure_skill_select_registered
    from agent.tool_runtime_mediator import ToolRuntimeMediator

    _ensure_skill_select_registered()
    _core._active_skill = {}

    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
    registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
    registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
    dispatcher = RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )

    state = _make_mock_state()
    turn_state = MagicMock()
    turn_state.round_tool_traces = []

    mediator = ToolRuntimeMediator(
        dispatcher, state=state, turn_state=turn_state,
        turn_context={}, messages=[],
    )

    block = MagicMock()
    block.type = "tool_use"
    block.id = "toolu_002_v7"
    block.name = "SKILL_SELECT"
    block.input = {"skill_id": "demo-note-maker", "reason": "validation"}

    mediator.mediate(block)

    ok = (
        _core._active_skill.get("skill_id") == "demo-note-maker"
        and len(_core._active_skill.get("body", "")) > 0
        and "demo.echo_task_summary" in _core._active_skill.get("allowed_tools", frozenset())
    )
    _record("V7", ok,
            f"skill_id={_core._active_skill.get('skill_id')}, "
            f"body_len={len(_core._active_skill.get('body', ''))}")


def check_v8_keyword_fallback_preserved() -> None:
    """V8: keyword matching fallback 仍可用。"""
    from agent.skill_selection import select_skill_for_real_provider
    from agent.skill_system.registry import SkillRegistry

    registry = SkillRegistry(roots=[Path("skills")])
    visible = registry.list_visible()
    result = select_skill_for_real_provider("用 demo 写笔记", visible)
    ok = result is not None and result["selected_skill_id"] == "demo-note-maker"
    _record("V8", ok,
            f"selected={result['selected_skill_id'] if result else None}, "
            f"confidence={result.get('selection_confidence') if result else None}")


def check_v9_model_owned_vs_fallback_distinct() -> None:
    """V9: model-owned path 和 keyword fallback path 可区分。"""
    import agent.core as _core
    from agent.skill_system.skill_tool import _skill_select_tool_func

    # model-owned path sets flag
    _core._skill_selected_by_model = False
    _skill_select_tool_func("demo-note-maker")
    flag_after_model = _core._skill_selected_by_model

    # keyword fallback path does NOT set flag
    _core._skill_selected_by_model = False
    from agent.skill_selection import select_skill_for_real_provider
    from agent.skill_system.registry import SkillRegistry

    registry = SkillRegistry(roots=[Path("skills")])
    visible = registry.list_visible()
    select_skill_for_real_provider("写笔记", visible)
    flag_after_fallback = _core._skill_selected_by_model

    ok = flag_after_model is True and flag_after_fallback is False
    _record("V9", ok,
            f"flag_after_model={flag_after_model}, flag_after_fallback={flag_after_fallback}")


def check_v10_allowed_tools_mediation() -> None:
    """V10: skill_allowed_tools 约束通过 mediator 生效。"""
    from agent.runtime_integration import (
        ActionHandlerRegistry,
        RuntimeActionDispatcher,
        RuntimeActionType,
    )
    from agent.runtime_integration.evidence import RuntimeActionModuleObserver
    from agent.runtime_integration.tool_gate import ToolGateHandler
    from agent.runtime_integration.tool_invoke import ToolInvokeHandler
    from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler
    from agent.tool_executor import FORCE_STOP
    from agent.tool_runtime_mediator import ToolRuntimeMediator

    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
    registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
    registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
    dispatcher = RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )

    state = _make_mock_state()
    turn_state = MagicMock()
    turn_state.round_tool_traces = []

    mediator = ToolRuntimeMediator(
        dispatcher, state=state, turn_state=turn_state,
        turn_context={}, messages=[],
        skill_allowed_tools=frozenset(["demo.echo_task_summary"]),
    )

    # 不在 allowed_tools 中的工具 → FORCE_STOP
    blocked = MagicMock()
    blocked.type = "tool_use"
    blocked.id = "toolu_blocked"
    blocked.name = "demo.write_demo_note"
    blocked.input = {"title": "test", "body": "test"}
    blocked_result = mediator.mediate(blocked)

    # 在 allowed_tools 中的工具 → None（成功）
    allowed = MagicMock()
    allowed.type = "tool_use"
    allowed.id = "toolu_allowed"
    allowed.name = "demo.echo_task_summary"
    allowed.input = {"task_summary": "test"}
    allowed_result = mediator.mediate(allowed)

    ok = blocked_result == FORCE_STOP and allowed_result is None
    _record("V10", ok,
            f"blocked={blocked_result!r}, allowed={allowed_result!r}")


# ── 入口 ─────────────────────────────────────────────────────────────────────


def main() -> int:
    print("=" * 60)
    print("REAL-EVIDENCE-002 Validation: Model-Owned Skill Selection")
    print("=" * 60)
    print()

    checks = [
        ("V1", check_v1_skill_select_in_registry),
        ("V2", check_v2_visible_in_model_tools),
        ("V3", check_v3_tool_func_valid_skill),
        ("V4", check_v4_tool_func_unknown_skill),
        ("V5", check_v5_skill_selected_flag),
        ("V6", check_v6_mediator_pipeline),
        ("V7", check_v7_active_skill_after_mediator),
        ("V8", check_v8_keyword_fallback_preserved),
        ("V9", check_v9_model_owned_vs_fallback_distinct),
        ("V10", check_v10_allowed_tools_mediation),
    ]

    for name, func in checks:
        try:
            func()
        except Exception as exc:
            _record(name, False, f"exception: {exc}")

    print()
    passed = sum(1 for r in _results if r["passed"])
    total = len(_results)
    all_pass = passed == total

    if "--json" in sys.argv:
        print(json.dumps({"results": _results, "summary": f"{passed}/{total}"}, indent=2))
    else:
        print(f"Results: {passed}/{total} passed")
        if not all_pass:
            failed = [r for r in _results if not r["passed"]]
            for f in failed:
                print(f"  FAIL {f['check']}: {f['detail']}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
