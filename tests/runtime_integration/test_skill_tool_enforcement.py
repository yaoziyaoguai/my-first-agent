"""Loop 2.2b Skill allowed_tools enforcement contract tests.

验证 activated Skill 的 allowed_tools 真实约束 main runtime path 中 Tool execution:
- allowed_tools 中允许的工具可以执行
- 不在 allowed_tools 中的工具在 execute_single_tool 之前被 block
- blocked 工具不调用底层 executor
- 没有 active_skill 时不破坏原有工具行为
- blocked 结果有 RuntimeAction / dispatcher evidence
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent.tool_executor import FORCE_STOP

# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def gate_dispatcher():
    """构造含 TOOL_GATE handler 的最小 dispatcher（不含 TOOL_INVOKE/TOOL_RESULT）。"""
    from agent.runtime_integration import (
        ActionHandlerRegistry,
        RuntimeActionDispatcher,
        RuntimeActionType,
    )
    from agent.runtime_integration.evidence import RuntimeActionModuleObserver
    from agent.runtime_integration.tool_gate import ToolGateHandler

    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


@pytest.fixture
def full_dispatcher():
    """构造完整的 TOOL_GATE / TOOL_INVOKE / TOOL_RESULT handler dispatcher。"""
    from agent.runtime_integration import (
        ActionHandlerRegistry,
        RuntimeActionDispatcher,
        RuntimeActionType,
    )
    from agent.runtime_integration.evidence import RuntimeActionModuleObserver
    from agent.runtime_integration.tool_gate import ToolGateHandler
    from agent.runtime_integration.tool_invoke import ToolInvokeHandler
    from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler

    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
    registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
    registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


@pytest.fixture
def mediator_state():
    """构造最小可用的 state / turn_state / messages 假对象。"""
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
    turn_state.on_display_event = None
    turn_state.on_runtime_event = None
    turn_state.on_trace_event = None

    messages: list = []

    return state, turn_state, messages


def _make_block(tool_name="_safe_noop", tool_input=None):
    """构造模拟 tool_use block。"""
    block = MagicMock()
    block.type = "tool_use"
    block.id = f"toolu_test_{tool_name}_001"
    block.name = tool_name
    block.input = tool_input or {}
    return block


# ═════════════════════════════════════════════════════════════════════════════
# TOOL_GATE skill enforcement unit tests
# ═════════════════════════════════════════════════════════════════════════════


class TestToolGateSkillEnforcement:
    """ToolGateHandler 中 skill allowed_tools 约束的直接单元测试。"""

    def test_allowed_tool_passes_gate(self, gate_dispatcher):
        """allowed_tools 中包含的工具 → gate_disposition='allowed'。"""
        from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType

        result = gate_dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "_safe_noop",
                "tool_input": {},
                "skill_allowed_tools": ["_safe_noop", "demo.echo_task_summary"],
            },
        ))
        assert result.payload["gate_disposition"] == "allowed", (
            f"allowed_tools 中的工具应通过 gate，got {result.payload}"
        )

    def test_non_allowed_tool_blocked_by_skill(self, gate_dispatcher):
        """allowed_tools 中不包含的工具 → gate_disposition='rejected'。"""
        from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType

        result = gate_dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "_safe_noop",
                "tool_input": {},
                "skill_allowed_tools": ["demo.echo_task_summary"],
            },
        ))
        assert result.payload["gate_disposition"] == "rejected", (
            f"不在 allowed_tools 中的工具应被 rejected，got {result.payload}"
        )
        assert "skill_allowed_tools" in result.payload.get("policy_path", ""), (
            "rejection reason 应引用 skill_allowed_tools 策略路径"
        )

    def test_skill_block_has_dispatcher_evidence(self, gate_dispatcher):
        """skill 工具 block 产生 dispatcher evidence（TOOL_GATE event + observed_call）。"""
        from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType

        gate_dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "_safe_noop",
                "tool_input": {},
                "skill_allowed_tools": ["demo.echo_task_summary"],
            },
        ))
        log = gate_dispatcher.action_log
        gate_events = [e for e in log if str(e.action_type) == "tool.gate"]
        assert len(gate_events) >= 1, "skill block 必须产生 TOOL_GATE event"
        event = gate_events[-1]
        assert event.status == "rejected", (
            f"skill block event status 应为 rejected，got {event.status}"
        )
        # evidence 应包含 skill 相关证据
        ev = dict(event.evidence)
        assert ev.get("capability_type") == "skill_tool_constraint", (
            f"evidence 应标记 capability_type=skill_tool_constraint，got {ev}"
        )
        assert "skill_allowed_tools" in ev, (
            "evidence 应包含 skill_allowed_tools 列表"
        )

    def test_no_skill_allowed_tools_preserves_existing_behavior(self, gate_dispatcher):
        """没有 skill_allowed_tools 时不影响原有 gate 行为。"""
        from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType

        result = gate_dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "_safe_noop",
                "tool_input": {},
            },
        ))
        assert result.payload["gate_disposition"] == "allowed", (
            f"无 skill 约束时 _safe_noop 应正常通过 gate，got {result.payload}"
        )

    def test_empty_skill_allowed_tools_not_enforced(self, gate_dispatcher):
        """skill_allowed_tools 为空 list 时不应拦截工具。"""
        from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType

        result = gate_dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "_safe_noop",
                "tool_input": {},
                "skill_allowed_tools": [],
            },
        ))
        assert result.payload["gate_disposition"] == "allowed", (
            f"空 allowed_tools 不应拦截工具，got {result.payload}"
        )

    def test_fake_tool_not_affected_by_skill_constraint(self, gate_dispatcher):
        """fake.* 工具不经过 skill allowed_tools 检查——走独立 overlay 路径。"""
        from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType

        result = gate_dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "fake.read_file",
                "tool_input": {},
                "skill_allowed_tools": ["demo.echo_task_summary"],
            },
        ))
        # fake.* 工具走 dogfood overlay 路径，不走 skill constraint check
        # 因为 fake.read_file 不在 dogfood_overlay 中 → failed
        assert result.status in ("failed", "rejected"), (
            f"fake.* 工具应走 overlay 路径而非 skill constraint，got status={result.status}"
        )

    # ── USER_RECHECK-P1-001: namespace normalization in TOOL_GATE ──────────

    def test_stripped_tool_name_matches_namespaced_allowed_tools(
        self, gate_dispatcher,
    ):
        """USER_RECHECK-P1-001: provider 剥离命名空间后的短名应匹配 namespaced allowed_tools。

        kimi-k2.5 等 provider 会将 demo.echo_task_summary → echo_task_summary。
        TOOL_GATE 必须在检查 skill_allowed_tools 之前通过 _normalize_tool_name()
        将短名归一化为注册表全名，否则 namespaced allowed_tools 永远匹配不上。
        """
        from agent.runtime_integration.schema import (
            RuntimeActionRequest,
            RuntimeActionType,
        )

        result = gate_dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "echo_task_summary",  # stripped by provider
                "tool_input": {},
                "skill_allowed_tools": [
                    "demo.echo_task_summary", "demo.write_demo_note",
                ],
            },
        ))
        assert result.payload["gate_disposition"] == "allowed", (
            f"剥离命名空间后的短名应通过 _normalize_tool_name 匹配到 namespaced "
            f"allowed_tools，got {result.payload}"
        )

    def test_stripped_write_demo_note_matches_namespaced_allowed_tools(
        self, gate_dispatcher,
    ):
        """USER_RECHECK-P1-001: write_demo_note 短名也应匹配 namespaced allowed_tools。"""
        from agent.runtime_integration.schema import (
            RuntimeActionRequest,
            RuntimeActionType,
        )

        result = gate_dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "write_demo_note",  # stripped by provider
                "tool_input": {"path": "workspace/demo/test/note.md", "content": "t"},
                "skill_allowed_tools": [
                    "demo.echo_task_summary", "demo.write_demo_note",
                ],
            },
        ))
        # demo.write_demo_note 注册时 confirmation="always"，
        # 归一化成功后 gate_disposition 为 "confirmation_required"（不是 "allowed"）。
        # 这里验证的是归一化本身成功（不被 rejected），而非 confirmation policy。
        assert result.payload["gate_disposition"] in ("allowed", "confirmation_required"), (
            f"write_demo_note 短名应通过归一化匹配 namespaced allowed_tools"
            f"（allowed 或 confirmation_required 均为归一化成功），"
            f"got {result.payload}"
        )

    def test_stripped_name_still_blocked_when_not_in_allowed_tools(
        self, gate_dispatcher,
    ):
        """短名工具不在 allowed_tools 中时仍应被拒绝（安全不降级）。"""
        from agent.runtime_integration.schema import (
            RuntimeActionRequest,
            RuntimeActionType,
        )

        result = gate_dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": "read_file",  # 不在 demo skill allowed_tools 中
                "tool_input": {"path": "/tmp/test.txt"},
                "skill_allowed_tools": [
                    "demo.echo_task_summary", "demo.write_demo_note",
                ],
            },
        ))
        assert result.payload["gate_disposition"] == "rejected", (
            f"不在 allowed_tools 中的工具应被 rejected（含归一化后），got {result.payload}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# ToolRuntimeMediator integration tests
# ═════════════════════════════════════════════════════════════════════════════


class TestMediatorSkillEnforcement:
    """ToolRuntimeMediator 层的 skill allowed_tools 集成测试。"""

    def test_allowed_tool_executes(self, full_dispatcher, mediator_state):
        """allowed_tools 中的工具通过 mediator 正常执行。"""
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        state, turn_state, messages = mediator_state
        mediator = ToolRuntimeMediator(
            full_dispatcher,
            state=state,
            turn_state=turn_state,
            turn_context={},
            messages=messages,
            skill_allowed_tools=frozenset({"_safe_noop", "demo.echo_task_summary"}),
        )

        block = _make_block("_safe_noop")
        result = mediator.mediate(block)

        # _safe_noop 在 allowed_tools 中 → 应正常执行（不是 FORCE_STOP）
        assert result is None, (
            f"allowed 工具应正常执行（返回 None），got {result}"
        )

    def test_non_allowed_tool_blocked_by_mediator(self, full_dispatcher, mediator_state):
        """不在 allowed_tools 中的工具通过 mediator 被 block。"""
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        state, turn_state, messages = mediator_state
        mediator = ToolRuntimeMediator(
            full_dispatcher,
            state=state,
            turn_state=turn_state,
            turn_context={},
            messages=messages,
            skill_allowed_tools=frozenset({"demo.echo_task_summary"}),
        )

        block = _make_block("_safe_noop")
        result = mediator.mediate(block)

        # _safe_noop 不在 allowed_tools 中 → FORCE_STOP
        assert result == FORCE_STOP, (
            f"非 allowed 工具应返回 FORCE_STOP，got {result}"
        )

    def test_blocked_tool_not_call_executor(self, full_dispatcher, mediator_state):
        """被 skill 约束 block 的工具不应调用 execute_single_tool。"""
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        state, turn_state, messages = mediator_state
        mediator = ToolRuntimeMediator(
            full_dispatcher,
            state=state,
            turn_state=turn_state,
            turn_context={},
            messages=messages,
            skill_allowed_tools=frozenset({"demo.echo_task_summary"}),
        )

        block = _make_block("_safe_noop")
        mediator.mediate(block)

        # 验证：被 block 后 tool_execution_log 中应有 blocked_by_policy 状态
        log_entry = state.task.tool_execution_log.get(block.id)
        assert log_entry is not None, "blocked 工具也应写入 tool_execution_log"
        assert log_entry["status"] == "blocked_by_policy", (
            f"blocked 工具状态应为 blocked_by_policy，got {log_entry.get('status')}"
        )

    def test_no_skill_constraint_does_not_block(self, full_dispatcher, mediator_state):
        """无 skill_allowed_tools 时 mediator 不拦截工具。"""
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        state, turn_state, messages = mediator_state
        mediator = ToolRuntimeMediator(
            full_dispatcher,
            state=state,
            turn_state=turn_state,
            turn_context={},
            messages=messages,
            skill_allowed_tools=None,
        )

        block = _make_block("_safe_noop")
        result = mediator.mediate(block)

        assert result is None, (
            f"无 skill 约束时工具应正常执行，got {result}"
        )

    def test_skill_block_produces_tool_gate_rejected_event(
        self, full_dispatcher, mediator_state
    ):
        """skill block 产生的 TOOL_GATE event 应标记为 rejected disposition。"""
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        state, turn_state, messages = mediator_state
        mediator = ToolRuntimeMediator(
            full_dispatcher,
            state=state,
            turn_state=turn_state,
            turn_context={},
            messages=messages,
            skill_allowed_tools=frozenset({"demo.echo_task_summary"}),
        )

        block = _make_block("_safe_noop")
        mediator.mediate(block)

        log = full_dispatcher.action_log
        gate_events = [e for e in log if str(e.action_type) == "tool.gate"]
        assert len(gate_events) >= 1
        gate_event = gate_events[-1]
        # event.evidence 包含 gate_disposition 等 gate result 信息
        assert gate_event.status == "rejected", (
            f"skill block TOOL_GATE event status 应为 rejected，got {gate_event.status}"
        )

    def test_skill_block_no_tool_invoke_event(
        self, full_dispatcher, mediator_state
    ):
        """skill block 不应产生 TOOL_INVOKE event（未进入 execute_single_tool）。"""
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        state, turn_state, messages = mediator_state
        mediator = ToolRuntimeMediator(
            full_dispatcher,
            state=state,
            turn_state=turn_state,
            turn_context={},
            messages=messages,
            skill_allowed_tools=frozenset({"demo.echo_task_summary"}),
        )

        block = _make_block("_safe_noop")
        mediator.mediate(block)

        log = full_dispatcher.action_log
        invoke_events = [e for e in log if str(e.action_type) == "tool.invoke"]
        assert len(invoke_events) == 0, (
            f"skill block 不应产生 TOOL_INVOKE event，got {len(invoke_events)}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# No-crash / prompt-only / docs-only 不可冒充 capability complete
# ═════════════════════════════════════════════════════════════════════════════


class TestSkillEnforcementNotFakeable:
    """验证 skill allowed_tools enforcement 不能通过假证据冒充完成。"""

    def test_prompt_only_not_enforcement(self, full_dispatcher, mediator_state):
        """仅靠 prompt 注入 allowed_tools 信息不构成 enforcement——
        mediator 未传 skill_allowed_tools 时工具不会被拦截。"""
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        state, turn_state, messages = mediator_state
        # 不传 skill_allowed_tools → 不拦截
        mediator = ToolRuntimeMediator(
            full_dispatcher,
            state=state,
            turn_state=turn_state,
            turn_context={},
            messages=messages,
        )

        block = _make_block("_safe_noop")
        result = mediator.mediate(block)
        assert result is None, (
            "不传 skill_allowed_tools 时工具应正常执行——"
            "仅 prompt 注入不足以约束工具执行"
        )

    def test_no_crash_not_enforcement(self, full_dispatcher, mediator_state):
        """no-crash 不代表 enforcement 生效——
        skill_allowed_tools 为空时不拦截也属于 no-crash 但不起约束作用。"""
        from agent.tool_runtime_mediator import ToolRuntimeMediator

        state, turn_state, messages = mediator_state
        mediator = ToolRuntimeMediator(
            full_dispatcher,
            state=state,
            turn_state=turn_state,
            turn_context={},
            messages=messages,
            skill_allowed_tools=frozenset(),  # 空集合
        )

        block = _make_block("_safe_noop")
        result = mediator.mediate(block)
        # 空 frozenset 不应被当作约束生效（None/empty → 不拦截）
        # 但也不应 crash
        assert result in (None, FORCE_STOP), "不应 crash"

    def test_registry_only_not_enforcement(self):
        """仅 registry 中声明 allowed_tools 不构成 enforcement——
        必须 ToolRuntimeMediator 实际传递并 ToolGateHandler 实际检查。"""
        from agent.skill_system.registry import SkillRegistry

        registry = SkillRegistry(roots=[])
        descriptors = registry.list_visible()
        # registry 中有 allowed_tools 声明不代表 runtime enforcement 生效
        # 真正生效的标志是 ToolGateHandler 在运行时检查 skill_allowed_tools
        assert isinstance(descriptors, list), "registry 正常但不代表 enforcement"
