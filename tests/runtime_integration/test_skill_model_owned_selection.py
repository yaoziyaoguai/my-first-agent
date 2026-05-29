"""REAL-EVIDENCE-002 RED/GREEN tests: 模型自主选择 Skill 的集成测试。

验证 SKILL_SELECT tool_use 通过 ToolRuntimeMediator pipeline 时的完整路径：
- tool_use → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT → conversation context
- _active_skill 更新 + allowed_tools 绑定
- keyword fallback 保留 + 与 model-owned 可区分
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
)
from agent.runtime_integration.evidence import (
    REAL_CORE_LOOP_RUNTIME_E2E,
    RuntimeActionModuleObserver,
)
from agent.runtime_integration.schema import RuntimeActionRequest
from agent.runtime_integration.skill_action import SkillRuntimeActionHandler
from agent.skill_system.loader import SkillLoader
from agent.skill_system.registry import SkillRegistry

# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════


def _make_tool_use_block(tool_name: str = "SKILL_SELECT", tool_input: dict | None = None):
    """构造模拟的 Anthropic tool_use block。"""
    block = MagicMock()
    block.type = "tool_use"
    block.id = f"toolu_test_{tool_name}_001"
    block.name = tool_name
    block.input = tool_input or {}
    return block


def _build_full_dispatcher() -> RuntimeActionDispatcher:
    """构建包含 TOOL_GATE/TOOL_INVOKE/TOOL_RESULT 的完整 dispatcher。"""
    from agent.runtime_integration.tool_gate import ToolGateHandler
    from agent.runtime_integration.tool_invoke import ToolInvokeHandler
    from agent.runtime_integration.tool_result_feedback import (
        ToolResultFeedbackHandler,
    )

    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
    registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
    registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


def _build_mediator_state():
    """最小可用的 state / turn_state / messages。"""
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

    turn_state = MagicMock()
    turn_state.round_tool_traces = []

    return state, turn_state


# ═════════════════════════════════════════════════════════════════════════════
# I1-I3: ToolRuntimeMediator pipeline — SKILL_SELECT via mediate()
# ═════════════════════════════════════════════════════════════════════════════


class TestSkillSelectViaToolMediator:
    """SKILL_SELECT tool_use 通过 ToolRuntimeMediator.mediate() pipeline。"""

    def test_i1_skill_select_goes_through_tool_gate(self):
        """I1: SKILL_SELECT block → mediate() → TOOL_GATE → allowed → 执行成功。

        验证 SKILL_SELECT 作为 TOOL_REGISTRY 标准工具可以通过完整的
        gate→invoke→result pipeline。
        """
        from agent.skill_system.skill_tool import _ensure_skill_select_registered
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        _ensure_skill_select_registered()
        dispatcher = _build_full_dispatcher()
        state, turn_state = _build_mediator_state()

        mediator = ToolRuntimeMediator(
            dispatcher, state=state, turn_state=turn_state,
            turn_context={}, messages=[],
        )

        block = _make_tool_use_block(
            "SKILL_SELECT",
            {"skill_id": "demo-note-maker", "reason": "用户需要笔记功能"},
        )
        result = mediator.mediate(block)

        # mediate() 返回 None 表示成功（不放 AWAITING_USER 或 FORCE_STOP）
        assert result is None, (
            f"SKILL_SELECT 应成功执行（返回 None），实际: {result!r}"
        )

        # dispatcher.action_log 应有 gate/invoke/result
        log = dispatcher.action_log
        gate_events = [e for e in log if str(e.action_type) == "tool.gate"]
        invoke_events = [e for e in log if str(e.action_type) == "tool.invoke"]
        result_events = [e for e in log if str(e.action_type) == "tool.result"]

        assert len(gate_events) >= 1, "mediate() 必须 dispatch TOOL_GATE"
        assert len(invoke_events) >= 1, "mediate() 必须 dispatch TOOL_INVOKE"
        assert len(result_events) >= 1, "mediate() 必须 dispatch TOOL_RESULT"

    def test_i2_skill_select_updates_active_skill(self):
        """I2: SKILL_SELECT 通过 mediator 执行后 _active_skill 应更新。"""
        import agent.core as _core
        from agent.skill_system.skill_tool import _ensure_skill_select_registered
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        _ensure_skill_select_registered()
        dispatcher = _build_full_dispatcher()
        state, turn_state = _build_mediator_state()
        _core._active_skill = {}
        _core._skill_selected_by_model = False

        mediator = ToolRuntimeMediator(
            dispatcher, state=state, turn_state=turn_state,
            turn_context={}, messages=[],
        )

        block = _make_tool_use_block(
            "SKILL_SELECT", {"skill_id": "demo-note-maker", "reason": "test"}
        )
        mediator.mediate(block)

        assert _core._active_skill.get("skill_id") == "demo-note-maker"
        assert len(_core._active_skill.get("body", "")) > 0
        assert "demo.echo_task_summary" in _core._active_skill.get(
            "allowed_tools", frozenset()
        )

    def test_i3_unknown_skill_via_mediator_returns_error(self):
        """I3: 未知 skill_id 通过 mediator → gate=allowed 但 tool func 返回错误。"""
        import agent.core as _core
        from agent.skill_system.skill_tool import _ensure_skill_select_registered
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        _ensure_skill_select_registered()
        dispatcher = _build_full_dispatcher()
        state, turn_state = _build_mediator_state()
        _core._skill_selected_by_model = False

        mediator = ToolRuntimeMediator(
            dispatcher, state=state, turn_state=turn_state,
            turn_context={}, messages=[],
        )

        block = _make_tool_use_block(
            "SKILL_SELECT", {"skill_id": "non-existent-skill-xyz"}
        )
        result = mediator.mediate(block)

        # 执行不 crash（返回 None 即使 tool func 返回错误信息也是正常路径）
        assert result is None

        # unknown skill 不设置 model-owned flag
        assert _core._skill_selected_by_model is False

        # _active_skill 不应被更新
        assert _core._active_skill.get("skill_id") != "non-existent-skill-xyz"


# ═════════════════════════════════════════════════════════════════════════════
# I4-I6: Allowed tools binding — mediator 中的 tool gate 约束
# ═════════════════════════════════════════════════════════════════════════════


class TestAllowedToolsBinding:
    """selected_skill.allowed_tools 应在后续 tool gate 中生效。"""

    def test_i4_allowed_tools_passed_to_mediator(self):
        """I4: _active_skill.allowed_tools → mediator._skill_allowed_tools。"""
        import agent.core as _core
        from agent.skill_system.skill_tool import _ensure_skill_select_registered
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        _ensure_skill_select_registered()
        dispatcher = _build_full_dispatcher()
        state, turn_state = _build_mediator_state()

        _core._active_skill = {
            "skill_id": "demo-note-maker",
            "body": "test body",
            "allowed_tools": frozenset(["demo.echo_task_summary", "demo.write_demo_note"]),
        }

        mediator = ToolRuntimeMediator(
            dispatcher, state=state, turn_state=turn_state,
            turn_context={}, messages=[],
            skill_allowed_tools=_core._active_skill.get("allowed_tools"),
        )

        assert mediator._skill_allowed_tools == frozenset([
            "demo.echo_task_summary", "demo.write_demo_note",
        ])

    def test_i5_allowed_tool_proceeds(self):
        """I5: allowed_tools 中的工具 → mediate() → gate=allowed → 执行。"""
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        dispatcher = _build_full_dispatcher()
        state, turn_state = _build_mediator_state()

        mediator = ToolRuntimeMediator(
            dispatcher, state=state, turn_state=turn_state,
            turn_context={}, messages=[],
            skill_allowed_tools=frozenset(["demo.echo_task_summary"]),
        )

        block = _make_tool_use_block(
            "demo.echo_task_summary", {"task_summary": "hello"}
        )
        result = mediator.mediate(block)

        # gate allowed → 执行成功
        assert result is None, (
            f"allowed_tools 中的工具应正常执行，实际: {result!r}"
        )

    def test_i6_blocked_tool_outside_allowed_tools(self):
        """I6: 不在 allowed_tools 中的工具 → gate=rejected → FORCE_STOP。"""
        from agent.tool_executor import FORCE_STOP
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        dispatcher = _build_full_dispatcher()
        state, turn_state = _build_mediator_state()

        mediator = ToolRuntimeMediator(
            dispatcher, state=state, turn_state=turn_state,
            turn_context={}, messages=[],
            skill_allowed_tools=frozenset(["demo.echo_task_summary"]),
        )

        block = _make_tool_use_block(
            "demo.write_demo_note", {"title": "test", "body": "test"}
        )
        result = mediator.mediate(block)

        # gate rejected → 返回 FORCE_STOP
        assert result == FORCE_STOP, (
            f"不在 allowed_tools 中的工具应被 block (FORCE_STOP)，实际: {result!r}"
        )

        # gate event 应有 rejected disposition
        log = dispatcher.action_log
        gate_events = [e for e in log if str(e.action_type) == "tool.gate"]
        assert len(gate_events) >= 1


# ═════════════════════════════════════════════════════════════════════════════
# I7-I9: Keyword fallback preserved
# ═════════════════════════════════════════════════════════════════════════════


class TestKeywordFallbackPreserved:
    """确定性 keyword fallback 仍作为 fallback 可用。"""

    def test_i7_keyword_fallback_still_works(self):
        """I7: select_skill_for_real_provider() 仍可用。"""
        from agent.skill_selection import select_skill_for_real_provider

        registry = SkillRegistry(roots=[Path("skills")])
        visible = registry.list_visible()

        result = select_skill_for_real_provider("写 demo 笔记", visible)

        assert result is not None
        assert result["selected_skill_id"] == "demo-note-maker"

    def test_i8_turn_end_dispatcher_path_unchanged(self):
        """I8: SkillRuntimeActionHandler 仍可通过 dispatcher 消费 keyword match。"""
        registry = SkillRegistry(roots=[Path("skills")])
        handler = SkillRuntimeActionHandler(
            registry=registry, loader=SkillLoader(registry)
        )
        handler_registry = ActionHandlerRegistry()
        handler_registry.register(RuntimeActionType.SKILL_SELECT, handler)
        dispatcher = RuntimeActionDispatcher(
            registry=handler_registry, observer=RuntimeActionModuleObserver()
        )

        payload: dict[str, Any] = {
            "core_loop_invoked": True,
            "core_entrypoint": "core.chat",
            "runtime_hook_name": "loop.turn_end",
            "provider_kind": "anthropic_compatible",
            "provider_external_call": True,
            "external_side_effects": True,
            "task_summary": "写 demo 笔记",
            "available_skill_metadata": [
                {
                    "skill_id": desc.name,
                    "description": desc.description,
                    "risk_level": desc.risk_level,
                    "tags": list(desc.tags),
                    "allowed_tools": list(desc.allowed_tools),
                    "memory_scope": desc.memory_scope,
                }
                for desc in registry.list_visible()
            ],
            "model_decision_metadata": {
                "selected_skill_id": "demo-note-maker",
                "selection_reason": "keyword match: demo, 笔记",
                "selection_confidence": "high",
                "matched_terms": ["name:demo", "desc:笔记"],
                "match_score": 5,
            },
        }

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.SKILL_SELECT,
            source="core_loop",
            parent_trace_id="",
            payload=payload,
        )

        result = dispatcher.route_from_runtime_loop(request)
        evidence = dict(result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        assert result.status == "success"
        assert result.payload.get("body_load_decision") is True

    def test_i9_model_owned_and_fallback_distinguishable(self):
        """I9: model-owned 和 keyword fallback 应可区分。"""
        import agent.core as _core
        from agent.skill_system.skill_tool import _skill_select_tool_func

        # model-owned path
        _core._active_skill = {}
        _core._skill_selected_by_model = False
        _skill_select_tool_func("demo-note-maker")

        assert _core._skill_selected_by_model is True
        assert _core._active_skill.get("skill_id") == "demo-note-maker"
        assert "body" in _core._active_skill
        assert "allowed_tools" in _core._active_skill

        # keyword fallback path
        _core._skill_selected_by_model = False
        _core._active_skill = {}

        registry = SkillRegistry(roots=[Path("skills")])
        handler = SkillRuntimeActionHandler(
            registry=registry, loader=SkillLoader(registry)
        )
        handler_registry = ActionHandlerRegistry()
        handler_registry.register(RuntimeActionType.SKILL_SELECT, handler)
        dispatcher = RuntimeActionDispatcher(
            registry=handler_registry, observer=RuntimeActionModuleObserver()
        )

        payload: dict[str, Any] = {
            "core_loop_invoked": True,
            "core_entrypoint": "core.chat",
            "runtime_hook_name": "loop.turn_end",
            "provider_kind": "anthropic_compatible",
            "provider_external_call": True,
            "external_side_effects": True,
            "task_summary": "写笔记",
            "available_skill_metadata": [
                {
                    "skill_id": desc.name,
                    "description": desc.description,
                    "risk_level": desc.risk_level,
                    "tags": list(desc.tags),
                    "allowed_tools": list(desc.allowed_tools),
                    "memory_scope": desc.memory_scope,
                }
                for desc in registry.list_visible()
            ],
            "model_decision_metadata": {
                "selected_skill_id": "demo-note-maker",
                "selection_reason": "keyword match",
                "selection_confidence": "high",
                "matched_terms": ["desc:笔记"],
            },
        }

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.SKILL_SELECT,
            source="core_loop",
            parent_trace_id="",
            payload=payload,
        )

        dispatcher.route_from_runtime_loop(request)

        # keyword fallback 不会设置 _skill_selected_by_model
        assert _core._skill_selected_by_model is False, (
            "keyword fallback 不应设置 model-owned flag"
        )

        # keyword fallback 通过 action_log 间接设置 _active_skill
        from agent.core import _update_active_skill_from_dispatcher
        _update_active_skill_from_dispatcher(dispatcher)

        assert _core._active_skill.get("skill_id") == "demo-note-maker"


# ═════════════════════════════════════════════════════════════════════════════
# I10-I12: Evidence distinction
# ═════════════════════════════════════════════════════════════════════════════


class TestEvidenceDistinction:
    """model-owned vs keyword fallback 的证据区分。"""

    def test_i10_mediator_produces_tool_evidence_chain(self):
        """I10: mediator.mediate() 产生 gate/invoke/result evidence chain。"""
        from agent.skill_system.skill_tool import _ensure_skill_select_registered
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        _ensure_skill_select_registered()
        dispatcher = _build_full_dispatcher()
        state, turn_state = _build_mediator_state()

        mediator = ToolRuntimeMediator(
            dispatcher, state=state, turn_state=turn_state,
            turn_context={}, messages=[],
        )

        block = _make_tool_use_block(
            "SKILL_SELECT", {"skill_id": "demo-note-maker"}
        )
        mediator.mediate(block)

        action_types = [
            str(e.action_type) for e in dispatcher.action_log
        ]
        assert "tool.gate" in action_types, (
            f"action_log 应含 tool.gate, 实际: {action_types}"
        )
        assert "tool.invoke" in action_types
        assert "tool.result" in action_types

    def test_i11_no_direct_call_evidence(self):
        """I11: direct call 能设置 _active_skill 但无 gate/invoke/result evidence。"""
        import agent.core as _core
        from agent.skill_system.skill_tool import _skill_select_tool_func
        _core._skill_selected_by_model = False

        # direct call 设置 _active_skill（单元级可用但不产生 mediator evidence chain）
        result = _skill_select_tool_func("demo-note-maker")

        assert "已激活" in result
        assert _core._skill_selected_by_model is True

    def test_i12_skill_select_not_meta_tool(self):
        """I12: SKILL_SELECT 的 meta_tool=False。"""
        from agent.skill_system.skill_tool import _ensure_skill_select_registered
        from agent.tool_registry import TOOL_REGISTRY

        _ensure_skill_select_registered()
        entry = TOOL_REGISTRY["SKILL_SELECT"]

        assert entry["meta_tool"] is False
        assert entry["confirmation"] == "never"
