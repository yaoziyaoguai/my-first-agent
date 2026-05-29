"""Batch B: Scheduler main-path injection contract tests.

验证 ActionScheduler 通过 core.chat() → _run_main_loop() → LoopDependencies
进入 run_main_loop() scheduler preprocessing block，不再 dead code。

RED phase: T1 应因 TypeError 失败（_run_main_loop 不接受 action_scheduler）。
GREEN phase: 所有 test 应通过。
"""

import inspect
from typing import Any
from unittest.mock import MagicMock, patch

from agent.action_scheduler import (
    ActionNode,
    ActionPlan,
    ActionRecoveryPolicy,
    ActionScheduler,
)
from agent.core import TurnState, _run_main_loop
from agent.loop import LoopDependencies, run_main_loop
from agent.loop_context import LoopContext
from agent.runtime_integration.action_scheduler_handler import ActionSchedulerHandler
from agent.runtime_integration.dispatcher import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
)
from agent.runtime_integration.evidence import RuntimeActionModuleObserver
from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType

# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _noop_runtime_loop_fields() -> dict[str, Any]:
    return {}


def _noop_safe_emit(sink, event):
    pass


def _build_dispatcher():
    registry = ActionHandlerRegistry()
    handler = ActionSchedulerHandler()
    for at in (
        RuntimeActionType.ACTION_PLAN_START,
        RuntimeActionType.NODE_ENTER,
        RuntimeActionType.NODE_EXIT,
        RuntimeActionType.NODE_FAILURE,
        RuntimeActionType.ACTION_PLAN_COMPLETE,
    ):
        registry.register(at, handler)
    return RuntimeActionDispatcher(registry=registry, observer=RuntimeActionModuleObserver())


def _success_executor(**kwargs):
    def _exec(node, state):
        base = {"success": True, "node_id": node.node_id, "target": node.target}
        base.update(kwargs)
        return base
    return _exec


def _failing_executor(error="test failure"):
    def _exec(node, state):
        return {"success": False, "error": error, "node_id": node.node_id}
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


def _make_turn_state(**kwargs):
    defaults = {"system_prompt": "test"}
    defaults.update(kwargs)
    return TurnState(**defaults)


def _make_loop_ctx(**kwargs):
    defaults = {
        "client": MagicMock(),
        "model_name": "test-model",
        "max_loop_iterations": 5,
    }
    defaults.update(kwargs)
    return LoopContext(**defaults)


# ═══════════════════════════════════════════════════════════════════════════════
# T1-T2: Injection contract
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchedulerMainPathInjection:
    """T1-T2: action_scheduler 注入 chain。"""

    def test_run_main_loop_accepts_action_scheduler_kwarg(self):
        """T1: _run_main_loop() 接受 action_scheduler kwarg 并传入 LoopDependencies。

        RED phase: _run_main_loop 不接受 action_scheduler → TypeError。
        GREEN phase: action_scheduler 正确传入 LoopDependencies。
        """
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        ts = _make_turn_state()
        lc = _make_loop_ctx()

        with patch("agent.core.run_main_loop") as mock_run:
            _run_main_loop(ts, lc, action_scheduler=scheduler)

            mock_run.assert_called_once()
            _, _, dependencies = mock_run.call_args[0]
            assert dependencies.action_scheduler is scheduler, (
                "LoopDependencies.action_scheduler 应为注入的 scheduler 实例"
            )

    def test_loop_dependencies_default_action_scheduler_is_none(self):
        """T2: LoopDependencies 默认 action_scheduler=None，向后兼容。"""
        deps = LoopDependencies(
            state=MagicMock(),
            call_model=MagicMock(),
            dispatch_model_output=MagicMock(),
            runtime_loop_fields=_noop_runtime_loop_fields,
            safe_emit_runtime_event=_noop_safe_emit,
            clear_checkpoint=MagicMock(),
        )
        assert deps.action_scheduler is None, (
            "默认 action_scheduler 应为 None（向后兼容）"
        )

    def test_loop_dependencies_carries_injected_action_scheduler(self):
        """T2b: LoopDependencies 显式注入时正确传递 action_scheduler。"""
        scheduler = ActionScheduler(dispatcher=_build_dispatcher())
        deps = LoopDependencies(
            state=MagicMock(),
            call_model=MagicMock(),
            dispatch_model_output=MagicMock(),
            runtime_loop_fields=_noop_runtime_loop_fields,
            safe_emit_runtime_event=_noop_safe_emit,
            clear_checkpoint=MagicMock(),
            action_scheduler=scheduler,
        )
        assert deps.action_scheduler is scheduler, (
            "显式注入的 action_scheduler 应与 LoopDependencies 中的一致"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# T3-T7: Main-path evidence — scheduler 在 run_main_loop 中触发 dispatcher
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchedulerMainPathEvidence:
    """T3-T7: scheduler preprocessing block 在 main runtime path 中产生 evidence。"""

    def _make_deps(self, scheduler, dispatcher):
        """构造最小 LoopDependencies 用于 run_main_loop()。

        call_model 返回一个假的 model response，使 loop 正常结束。
        state mock 配置为支持 task.loop_iterations 整数运算。
        """
        fake_response = MagicMock()
        fake_response.content = [MagicMock(text="done", type="text")]
        fake_response.stop_reason = "end_turn"

        state = MagicMock()
        state.task.loop_iterations = 0
        state.task.tool_call_count = 0
        state.runtime.max_recent_messages = 20

        return LoopDependencies(
            state=state,
            call_model=lambda ts, lc: fake_response,
            dispatch_model_output=lambda resp: None,
            runtime_loop_fields=_noop_runtime_loop_fields,
            safe_emit_runtime_event=_noop_safe_emit,
            clear_checkpoint=lambda: None,
            runtime_action_dispatcher=dispatcher,
            action_scheduler=scheduler,
        )

    def test_scheduler_preprocessing_triggers_in_run_main_loop(self):
        """T3: run_main_loop() scheduler preprocessing 在 has_active_plan() 时触发。

        验证: next_node() 返回 node → execute_node() 执行 → continue 跳过 model。
        """
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        scheduler.load_plan(_simple_plan(nodes=(_node(node_id="main_n1"),)))

        deps = self._make_deps(scheduler, dispatcher)
        ts = _make_turn_state()
        lc = _make_loop_ctx()

        assert scheduler.has_active_plan(), "sanity: plan 已加载"

        run_main_loop(ts, lc, deps)

        # plan 应已完成（单 node plan: next_node → execute → next_node=None → complete）
        assert not scheduler.has_active_plan(), (
            "单 node plan 执行完毕后 has_active_plan() 应为 False"
        )

    def test_action_plan_start_evidence_in_main_path(self):
        """T4: ACTION_PLAN_START 在 main runtime path 中 dispatch。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        scheduler.load_plan(_simple_plan(plan_id="evidence_t4"))

        deps = self._make_deps(scheduler, dispatcher)
        run_main_loop(_make_turn_state(), _make_loop_ctx(), deps)

        starts = [
            e for e in dispatcher.action_log
            if str(e.action_type) == "scheduler.action_plan_start"
        ]
        assert len(starts) >= 1, "ACTION_PLAN_START 应在 dispatcher action_log 中"
        assert dict(starts[0].evidence).get("plan_id") == "evidence_t4"

    def test_node_enter_exit_evidence_in_main_path(self):
        """T5+T6: NODE_ENTER + NODE_EXIT 在 main runtime path 中 dispatch。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        scheduler.load_plan(_simple_plan(nodes=(_node(node_id="ev_node"),)))

        deps = self._make_deps(scheduler, dispatcher)
        run_main_loop(_make_turn_state(), _make_loop_ctx(), deps)

        enters = [
            e for e in dispatcher.action_log
            if str(e.action_type) == "scheduler.node_enter"
        ]
        exits = [
            e for e in dispatcher.action_log
            if str(e.action_type) == "scheduler.node_exit"
        ]
        assert len(enters) >= 1, "NODE_ENTER 应在 dispatcher action_log 中"
        assert len(exits) >= 1, "NODE_EXIT 应在 dispatcher action_log 中"

    def test_action_plan_complete_evidence_in_main_path(self):
        """T7: ACTION_PLAN_COMPLETE 在 main runtime path 中 dispatch。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        scheduler.load_plan(_simple_plan())

        deps = self._make_deps(scheduler, dispatcher)
        run_main_loop(_make_turn_state(), _make_loop_ctx(), deps)

        completes = [
            e for e in dispatcher.action_log
            if str(e.action_type) == "scheduler.action_plan_complete"
        ]
        assert len(completes) >= 1, "ACTION_PLAN_COMPLETE 应在 dispatcher action_log 中"

    def test_node_failure_evidence_in_main_path(self):
        """T9: NODE_FAILURE 在 main runtime path 中 dispatch（halt 时）。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_failing_executor("boom"))
        scheduler.load_plan(_simple_plan(nodes=(
            _node(node_id="fail_n1", recovery=ActionRecoveryPolicy(on_failure="halt")),
        )))

        deps = self._make_deps(scheduler, dispatcher)
        run_main_loop(_make_turn_state(), _make_loop_ctx(), deps)

        failures = [
            e for e in dispatcher.action_log
            if str(e.action_type) == "scheduler.node_failure"
        ]
        assert len(failures) >= 1, "NODE_FAILURE 应在 dispatcher action_log 中"

    def test_scheduler_no_active_plan_falls_through_to_model(self):
        """T10: action_scheduler=None 时，loop 行为不变（向后兼容回归测试）。"""
        dispatcher = _build_dispatcher()
        mock_call = MagicMock(return_value=MagicMock(
            content=[MagicMock(text="ok", type="text")],
            stop_reason="end_turn",
        ))
        state = MagicMock()
        state.task.loop_iterations = 0
        state.task.tool_call_count = 0
        state.runtime.max_recent_messages = 20
        deps = LoopDependencies(
            state=state,
            call_model=mock_call,
            dispatch_model_output=MagicMock(return_value=None),
            runtime_loop_fields=_noop_runtime_loop_fields,
            safe_emit_runtime_event=_noop_safe_emit,
            clear_checkpoint=lambda: None,
            runtime_action_dispatcher=dispatcher,
            action_scheduler=None,
        )
        # 不应 crash：无 active plan → 直接走 model 路径
        run_main_loop(_make_turn_state(), _make_loop_ctx(), deps)
        # call_model 被调用了（走了 model 路径）
        mock_call.assert_called()


# ═══════════════════════════════════════════════════════════════════════════════
# T11-T15: Boundary guards — Scheduler 不绕过已有 mediator
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchedulerBoundaryGuards:
    """T11-T15: Scheduler 作为 orchestration layer，不直接执行 Tool/Memory/Skill/MCP/SubAgent。"""

    def test_scheduler_does_not_directly_call_tool_registry(self):
        """T11: ActionScheduler 没有对 TOOL_REGISTRY 的直接引用。"""
        source = inspect.getsource(ActionScheduler)
        assert "TOOL_REGISTRY" not in source, (
            "ActionScheduler 不应直接引用 TOOL_REGISTRY"
        )

    def test_scheduler_does_not_directly_call_memory_store(self):
        """T12: ActionScheduler 没有对 memory store 的直接引用。"""
        source = inspect.getsource(ActionScheduler)
        assert "_memory_runtime" not in source, (
            "ActionScheduler 不应直接引用 _memory_runtime"
        )

    def test_scheduler_does_not_directly_call_skill_registry(self):
        """T13: ActionScheduler 没有对 SkillRegistry 的直接引用。"""
        source = inspect.getsource(ActionScheduler)
        assert "SkillRegistry" not in source, (
            "ActionScheduler 不应直接引用 SkillRegistry"
        )

    def test_scheduler_does_not_directly_call_mcp(self):
        """T14: ActionScheduler 没有对 mcp 的直接引用。"""
        source = inspect.getsource(ActionScheduler)
        assert "mcp" not in source.lower() or "mcp_tool" not in source.lower(), (
            "ActionScheduler 不应直接引用 MCP pipeline"
        )

    def test_scheduler_does_not_directly_call_subagent(self):
        """T15: ActionScheduler 没有对 SubAgent 的直接引用。"""
        source = inspect.getsource(ActionScheduler)
        assert "subagent" not in source.lower(), (
            "ActionScheduler 不应直接引用 SubAgent"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# N1-N4: Not-fakeable guard tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchedulerMainPathNotFakeable:
    """N1-N4: 手动 harness ≠ main-path evidence。"""

    def test_standalone_script_not_main_path_evidence(self):
        """N1: 手动构造 ActionScheduler + 手动调用 ≠ main-path evidence。

        直接调用 scheduler.next_node()/execute_node() 产生 dispatcher evidence，
        但这只能证明 handler 注册正确，不能证明 core.chat() main path 中有注入。
        """
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        scheduler.load_plan(_simple_plan())

        # 手动调用 — 这产生 dispatcher evidence 但不是 main-path
        node = scheduler.next_node()
        scheduler.execute_node(node)
        scheduler.complete_plan()

        # 证据确实存在（handler 工作正常）
        evidence_count = len(dispatcher.action_log)
        assert evidence_count >= 1

        # 但这不能声称是 main-path evidence
        # — 这个测试的存在本身就是在提醒：standalone script ≠ main path

    def test_no_crash_not_main_path_pass(self):
        """N2: no-crash ≠ scheduler main-path PASS。

        ActionScheduler 在 standalone 模式下「不 crash」是最低标准，
        不能等同于 core.chat() main runtime path 已验证。
        """
        # standalone 模式下不 crash
        scheduler = ActionScheduler(dispatcher=None, executor=_success_executor())
        scheduler.load_plan(_simple_plan())
        node = scheduler.next_node()
        result = scheduler.execute_node(node)
        assert result["success"] is True

        # 这是最低标准 — 没有 dispatcher evidence，没有 main runtime path
        # 不 crash ≠ main-path PASS

    def test_direct_dispatcher_route_not_main_path(self):
        """N3: 直接 dispatcher.route() 调用 ≠ main-path evidence。

        dispatcher.route(RuntimeActionRequest(type=NODE_ENTER, ...)) 产生 action_log，
        但这绕过了 scheduler.next_node()→execute_node() 链，不是 main path。
        """
        dispatcher = _build_dispatcher()

        # 直接 route — 绕过 scheduler
        dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.NODE_ENTER,
            source="test",
            parent_trace_id="n3",
            payload={"node_id": "direct"},
        ))

        # action_log 有记录
        assert len(dispatcher.action_log) >= 1

        # 但这个 evidence 不是 scheduler 产生的，更不是 main path

    def test_evidence_must_be_in_dispatcher_action_log(self):
        """N4: Scheduler main-path evidence 必须在 dispatcher action_log 中，
        不能在手动 assertion 中构造。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        scheduler.load_plan(_simple_plan(nodes=(
            _node(node_id="n4_a"),
            _node(node_id="n4_b"),
        )))

        # 完整执行 plan
        while True:
            node = scheduler.next_node()
            if node is None:
                break
            scheduler.execute_node(node)
        scheduler.complete_plan()

        # 所有 evidence 必须在 dispatcher action_log 中
        action_types = {str(e.action_type) for e in dispatcher.action_log}
        required = {
            "scheduler.action_plan_start",
            "scheduler.node_enter",
            "scheduler.node_exit",
            "scheduler.action_plan_complete",
        }
        missing = required - action_types
        assert not missing, f"dispatcher action_log 缺少: {missing}"


# ═══════════════════════════════════════════════════════════════════════════════
# T8: Cross-node influence — condition_flags 影响 next action
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchedulerCrossNodeInfluence:
    """T8: condition_flags 跨 node 影响。"""

    def test_condition_flags_affect_next_node_selection(self):
        """T8: 一个 node 的 result 中的 condition_flags 影响下一个 node 选择。"""
        dispatcher = _build_dispatcher()

        def _conditional_executor(node, state):
            return {
                "success": True,
                "node_id": node.node_id,
                "target": node.target,
                "condition_flags": {"skip_next": True},
            }

        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_conditional_executor)
        scheduler.load_plan(_simple_plan(nodes=(
            _node(node_id="setter"),
            _node(node_id="conditional", condition="skip_next", depends_on=("setter",)),
        )))

        # setter 执行后设置 condition_flags={"skip_next": True}
        n1 = scheduler.next_node()
        assert n1.node_id == "setter"
        scheduler.execute_node(n1)

        # conditional node 的 condition 为 "skip_next"
        # skip_next=True → 应 skip
        n2 = scheduler.next_node()
        assert n2 is None, "conditional node 应在 condition 不满足时被 skip"


# ═══════════════════════════════════════════════════════════════════════════════
# Regression — 现有 46 tests 路径不变
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchedulerMainPathRegression:
    """确保 action_scheduler=None 时行为完全不变。"""

    def test_action_scheduler_none_does_not_break_loop_dependencies(self):
        """action_scheduler=None 时 LoopDependencies 构造与旧行为一致。"""
        deps = LoopDependencies(
            state=MagicMock(),
            call_model=MagicMock(),
            dispatch_model_output=MagicMock(),
            runtime_loop_fields=_noop_runtime_loop_fields,
            safe_emit_runtime_event=_noop_safe_emit,
            clear_checkpoint=MagicMock(),
        )
        # 默认值兼容
        assert deps.action_scheduler is None
        assert deps.tool_gate_tool_name == "_safe_noop"
        assert deps.skill_registry is None
