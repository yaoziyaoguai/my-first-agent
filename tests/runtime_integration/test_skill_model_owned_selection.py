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
        assert len(invoke_events) == 0, (
            "mediate() 不应 dispatch TOOL_INVOKE（_route_invoke 改用 record_evidence）"
        )
        assert len(result_events) >= 1, "mediate() 必须 dispatch TOOL_RESULT"

    def test_i2_skill_select_updates_active_skill(self):
        """I2: SKILL_SELECT 通过 mediator 执行后 _active_skill 应更新。"""
        import agent.skill_state as _state
        from agent.skill_system.skill_tool import _ensure_skill_select_registered
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        _ensure_skill_select_registered()
        dispatcher = _build_full_dispatcher()
        state, turn_state = _build_mediator_state()
        _state.set_active_skill({})
        _state.set_skill_selected_by_model(False)

        mediator = ToolRuntimeMediator(
            dispatcher, state=state, turn_state=turn_state,
            turn_context={}, messages=[],
        )

        block = _make_tool_use_block(
            "SKILL_SELECT", {"skill_id": "demo-note-maker", "reason": "test"}
        )
        mediator.mediate(block)

        assert _state.get_active_skill().get("skill_id") == "demo-note-maker"
        assert len(_state.get_active_skill().get("body", "")) > 0
        assert "demo.echo_task_summary" in _state.get_active_skill().get(
            "allowed_tools", frozenset()
        )

    def test_i3_unknown_skill_via_mediator_returns_error(self):
        """I3: 未知 skill_id 通过 mediator → gate=allowed 但 tool func 返回错误。"""
        import agent.skill_state as _state
        from agent.skill_system.skill_tool import _ensure_skill_select_registered
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        _ensure_skill_select_registered()
        dispatcher = _build_full_dispatcher()
        state, turn_state = _build_mediator_state()
        _state.set_skill_selected_by_model(False)

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
        assert _state.get_skill_selected_by_model() is False

        # _active_skill 不应被更新
        assert _state.get_active_skill().get("skill_id") != "non-existent-skill-xyz"


# ═════════════════════════════════════════════════════════════════════════════
# I4-I6: Allowed tools binding — mediator 中的 tool gate 约束
# ═════════════════════════════════════════════════════════════════════════════


class TestAllowedToolsBinding:
    """selected_skill.allowed_tools 应在后续 tool gate 中生效。"""

    def test_i4_allowed_tools_passed_to_mediator(self):
        """I4: _active_skill.allowed_tools → mediator._skill_allowed_tools。"""
        import agent.skill_state as _state
        from agent.skill_system.skill_tool import _ensure_skill_select_registered
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        _ensure_skill_select_registered()
        dispatcher = _build_full_dispatcher()
        state, turn_state = _build_mediator_state()

        _state.set_active_skill({
            "skill_id": "demo-note-maker",
            "body": "test body",
            "allowed_tools": frozenset(["demo.echo_task_summary", "demo.write_demo_note"]),
        })

        mediator = ToolRuntimeMediator(
            dispatcher, state=state, turn_state=turn_state,
            turn_context={}, messages=[],
            skill_allowed_tools=_state.get_active_skill().get("allowed_tools"),
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
        import agent.skill_state as _state
        from agent.skill_system.skill_tool import _skill_select_tool_func

        # model-owned path
        _state.set_active_skill({})
        _state.set_skill_selected_by_model(False)
        _skill_select_tool_func("demo-note-maker")

        assert _state.get_skill_selected_by_model() is True
        assert _state.get_active_skill().get("skill_id") == "demo-note-maker"
        assert "body" in _state.get_active_skill()
        assert "allowed_tools" in _state.get_active_skill()

        # keyword fallback path
        _state.set_skill_selected_by_model(False)
        _state.set_active_skill({})

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
        assert _state.get_skill_selected_by_model() is False, (
            "keyword fallback 不应设置 model-owned flag"
        )

        # keyword fallback 通过 action_log 间接设置 _active_skill
        from agent.core import _update_active_skill_from_dispatcher
        _update_active_skill_from_dispatcher(dispatcher)

        assert _state.get_active_skill().get("skill_id") == "demo-note-maker"


# ═════════════════════════════════════════════════════════════════════════════
# I13-I15: Turn-end hook fallback guard — flag 控制 keyword fallback 的循环级行为
# ═════════════════════════════════════════════════════════════════════════════


class TestTurnEndHookFallbackGuard:
    """turn-end hook 中 _skill_selected_by_model flag 的循环级行为。

    验证 loop.turn_end hook（_try_phase1_turn_end_runtime_action）在 skill
    selection 阶段是否正确检查 flag 来决定是否触发 keyword fallback。
    不绕过 loop 直接调用 tool func——通过完整的 hook 路径验证 loop 级行为。
    """

    @staticmethod
    def _build_skill_dispatcher():
        """构建包含 SKILL_SELECT handler 的 dispatcher。"""
        registry = SkillRegistry(roots=[Path("skills")])
        handler = SkillRuntimeActionHandler(
            registry=registry, loader=SkillLoader(registry)
        )
        handler_registry = ActionHandlerRegistry()
        handler_registry.register(RuntimeActionType.SKILL_SELECT, handler)
        return RuntimeActionDispatcher(
            registry=handler_registry, observer=RuntimeActionModuleObserver()
        )

    @staticmethod
    def _build_dependencies(state, dispatcher):
        """构建包含 skill_registry 的 LoopDependencies。"""

        registry = SkillRegistry(roots=[Path("skills")])
        deps = MagicMock()
        deps.state = state
        deps.provider_kind = "anthropic_compatible"
        deps.provider_external_call = True
        deps.skill_registry = registry
        deps.runtime_action_dispatcher = dispatcher
        deps.tool_gate_tool_name = "_safe_noop"
        deps.streaming_events = []
        return deps

    @staticmethod
    def _build_state_with_user_message(user_text: str):
        """构造包含用户消息的 state。"""
        state = MagicMock()
        state.task.loop_iterations = 0
        state.task.tool_call_count = 0
        state.task.pending_retain_proposals = None
        state.conversation.messages = [
            {"role": "user", "content": user_text},
        ]
        return state

    @staticmethod
    def _capture_skill_selection_decisions(dispatcher) -> list[dict]:
        """从 dispatcher action_log 提取 skill.select 事件的 evidence。

        返回包含 body_load_decision / selected_skill_id 等字段的列表。
        keyword fallback 触发时 body_load_decision=True；
        被 skip 时 handler 返回 validation failure（payload 不含 model_decision_metadata）。
        """
        decisions: list[dict] = []
        for event in dispatcher.action_log:
            if str(getattr(event, "action_type", "")) == "skill.select":
                evidence = getattr(event, "evidence", {}) or {}
                decisions.append({
                    "status": getattr(event, "status", ""),
                    "body_load_decision": evidence.get("body_load_decision"),
                    "selected_skill_id": evidence.get("selected_skill_id"),
                    "selection_reason": evidence.get("selection_reason"),
                })
        return decisions

    def test_i13_flag_true_suppresses_keyword_fallback(self):
        """I13: _skill_selected_by_model=True → turn-end hook 跳过 keyword fallback。

        模型已在当前 turn 通过 tool_use("SKILL_SELECT") 自主选择了 skill，
        turn-end hook 应消费 flag 但不执行 keyword fallback。
        """
        import agent.skill_state as _state
        from agent.loop import _try_phase1_turn_end_runtime_action

        _state.set_skill_selected_by_model(True)
        _state.set_active_skill({})

        dispatcher = self._build_skill_dispatcher()
        state = self._build_state_with_user_message("写 demo 笔记")
        deps = self._build_dependencies(state, dispatcher)

        _try_phase1_turn_end_runtime_action(state, "test result", dispatcher, deps)

        # flag 为 True 时不应触发 keyword fallback → body_load_decision 不为 True
        decisions = self._capture_skill_selection_decisions(dispatcher)
        body_loads = [d for d in decisions if d["body_load_decision"] is True]
        assert len(body_loads) == 0, (
            f"flag=True 时不应加载 skill body (keyword fallback 被 skip), "
            f"实际加载: {body_loads}"
        )

        # flag 应被消费
        assert _state.get_skill_selected_by_model() is False, (
            "flag 应在 turn-end hook 中被消费 (重置为 False)"
        )

    def test_i14_flag_false_allows_keyword_fallback(self):
        """I14: _skill_selected_by_model=False → turn-end hook 正常执行 keyword fallback。

        模型未自主选择 skill，turn-end hook 应通过 keyword matching 尝试匹配。
        """
        import agent.skill_state as _state
        from agent.loop import _try_phase1_turn_end_runtime_action

        _state.set_skill_selected_by_model(False)
        _state.set_active_skill({})

        dispatcher = self._build_skill_dispatcher()
        state = self._build_state_with_user_message("写 demo 笔记")
        deps = self._build_dependencies(state, dispatcher)

        _try_phase1_turn_end_runtime_action(state, "test result", dispatcher, deps)

        # flag 为 False 时 keyword fallback 应触发 → body_load_decision=True
        decisions = self._capture_skill_selection_decisions(dispatcher)
        body_loads = [d for d in decisions if d["body_load_decision"] is True]
        assert len(body_loads) >= 1, (
            f"flag=False 时应触发 keyword fallback 加载 skill body, "
            f"decisions: {decisions}"
        )
        assert body_loads[0]["selected_skill_id"] in {"blog-writing", "demo-note-maker"}, (
            f"keyword fallback 应匹配 blog-writing 或 demo-note-maker, "
            f"实际: {body_loads[0].get('selected_skill_id')}"
        )

    def test_i15_flag_not_leak_across_turns(self):
        """I15: flag 消费后不会跨 turn 泄漏。

        - flag=True → turn-end hook 消费 flag → flag=False
        - 下一 turn flag=False → keyword fallback 正常触发
        验证 flag 不会在消费后保持 True，也不会因其他原因残留。
        """
        import agent.skill_state as _state
        from agent.loop import _try_phase1_turn_end_runtime_action

        # ── Turn 1: model-owned selection ──
        _state.set_skill_selected_by_model(True)
        _state.set_active_skill({})

        dispatcher1 = self._build_skill_dispatcher()
        state1 = self._build_state_with_user_message("写 demo 笔记")
        deps1 = self._build_dependencies(state1, dispatcher1)

        _try_phase1_turn_end_runtime_action(state1, "result turn 1", dispatcher1, deps1)

        # Turn 1 后 flag 应为 False
        assert _state.get_skill_selected_by_model() is False
        decisions1 = self._capture_skill_selection_decisions(dispatcher1)
        body_loads1 = [d for d in decisions1 if d["body_load_decision"] is True]
        assert len(body_loads1) == 0, "Turn 1 (flag=True): 不应触发 keyword fallback"

        # ── Turn 2: 无 model-owned selection ──
        # flag 已为 False，不应被 Turn 1 残留影响
        dispatcher2 = self._build_skill_dispatcher()
        state2 = self._build_state_with_user_message("写 demo 笔记")
        deps2 = self._build_dependencies(state2, dispatcher2)

        _try_phase1_turn_end_runtime_action(state2, "result turn 2", dispatcher2, deps2)

        # Turn 2 后 flag 仍为 False
        assert _state.get_skill_selected_by_model() is False, (
            "flag 在 turn 2 后不应泄漏为 True"
        )
        decisions2 = self._capture_skill_selection_decisions(dispatcher2)
        body_loads2 = [d for d in decisions2 if d["body_load_decision"] is True]
        assert len(body_loads2) >= 1, "Turn 2 (flag=False): keyword fallback 应正常触发"
        assert body_loads2[0]["selected_skill_id"] == "demo-note-maker"

    def test_fake_provider_empty_visible_skills_does_not_index_zero(self):
        """U5: fake provider + 空 visible skill 列表时不访问 _visible[0]。"""
        from agent.loop import _try_phase1_turn_end_runtime_action

        class _EmptySkillRegistry:
            def list_visible(self):
                return []

        dispatcher = self._build_skill_dispatcher()
        state = self._build_state_with_user_message("写 demo 笔记")
        deps = self._build_dependencies(state, dispatcher)
        deps.provider_kind = "fake"
        deps.provider_external_call = False
        deps.skill_registry = _EmptySkillRegistry()

        _try_phase1_turn_end_runtime_action(state, "test result", dispatcher, deps)

        decisions = self._capture_skill_selection_decisions(dispatcher)
        assert all(d["body_load_decision"] is not True for d in decisions)

    def test_fake_provider_visible_skill_auto_selects_first_descriptor(self):
        """U5: fake provider 非空 visible skill 列表仍自动选择第一个 descriptor。"""
        from agent.loop import _try_phase1_turn_end_runtime_action

        dispatcher = self._build_skill_dispatcher()
        state = self._build_state_with_user_message("写 demo 笔记")
        deps = self._build_dependencies(state, dispatcher)
        deps.provider_kind = "fake"
        deps.provider_external_call = False

        _try_phase1_turn_end_runtime_action(state, "test result", dispatcher, deps)

        decisions = self._capture_skill_selection_decisions(dispatcher)
        body_loads = [d for d in decisions if d["body_load_decision"] is True]
        assert len(body_loads) >= 1
        assert body_loads[0]["selected_skill_id"] in {"blog-writing", "demo-note-maker"}


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
        assert "tool.invoke" not in action_types, (
            "mediate() 不应 dispatch TOOL_INVOKE（_route_invoke 改用 record_evidence）"
        )
        assert "tool.result" in action_types

    def test_i11_no_direct_call_evidence(self):
        """I11: direct call 能设置 _active_skill 但无 gate/invoke/result evidence。"""
        import agent.skill_state as _state
        from agent.skill_system.skill_tool import _skill_select_tool_func
        _state.set_skill_selected_by_model(False)

        # direct call 设置 _active_skill（单元级可用但不产生 mediator evidence chain）
        result = _skill_select_tool_func("demo-note-maker")

        assert "已激活" in result
        assert _state.get_skill_selected_by_model() is True

    def test_i12_skill_select_not_meta_tool(self):
        """I12: SKILL_SELECT 的 meta_tool=False。"""
        from agent.skill_system.skill_tool import _ensure_skill_select_registered
        from agent.tool_registry import TOOL_REGISTRY

        _ensure_skill_select_registered()
        entry = TOOL_REGISTRY["SKILL_SELECT"]

        assert entry["meta_tool"] is False
        assert entry["confirmation"] == "never"
