"""Loop 3.4: Advanced Scheduler contract tests.

验证 ActionScheduler 的 dataclass 不变式、plan 加载、node 推进、失败恢复、
dispatcher evidence 产生、RuntimeDecisionFrame 集成和 not-fakeable guard。
"""

from agent.action_scheduler import (
    ActionNode,
    ActionPlan,
    ActionRecoveryPolicy,
    ActionScheduler,
    SchedulerState,
    build_action_plan_from_dict,
)
from agent.runtime_decision_frame import (
    build_decision_frame,
    build_decision_frame_from_chat_params,
)
from agent.runtime_integration.action_scheduler_handler import ActionSchedulerHandler
from agent.runtime_integration.dispatcher import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
)
from agent.runtime_integration.evidence import RuntimeActionModuleObserver
from agent.runtime_integration.schema import RuntimeActionType

# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _build_dispatcher():
    """构建注册了所有 5 个 scheduler action type 的 dispatcher。"""
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


def _node(**kwargs):
    """快捷构造 ActionNode。"""
    defaults = {
        "node_id": "step_1",
        "action_type": "TOOL_CALL",
        "target": "test_tool",
    }
    defaults.update(kwargs)
    return ActionNode(**defaults)


def _success_executor(result_extra=None):
    """返回总是成功的 ActionExecutor。"""
    def _exec(node, state):
        base = {"success": True, "node_id": node.node_id, "target": node.target}
        if result_extra:
            base.update(result_extra)
        return base
    return _exec


def _failing_executor(error="test failure"):
    """返回总是失败的 ActionExecutor。"""
    def _exec(node, state):
        return {"success": False, "error": error, "node_id": node.node_id}
    return _exec


def _simple_plan(plan_id="test_plan", nodes=None, entry_node_id=None):
    """构造简单 ActionPlan。entry_node_id 默认取自第一个 node。"""
    if nodes is None:
        nodes = (_node(node_id="step_1"),)
    nodes = tuple(nodes)
    if entry_node_id is None:
        entry_node_id = nodes[0].node_id
    return ActionPlan(
        plan_id=plan_id,
        nodes=nodes,
        entry_node_id=entry_node_id,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# T1-T3: Core — dataclass validation, plan loading, node ordering
# ═══════════════════════════════════════════════════════════════════════════════


class TestActionSchedulerCore:
    """T1-T3: plan 加载、has_active_plan、next_node 拓扑顺序。"""

    # ── T1: load valid plan → has_active_plan=True ──────────────────────────

    def test_load_plan_activates_scheduler(self):
        """T1: load_plan 后 scheduler.has_active_plan() 返回 True。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher)
        assert not scheduler.has_active_plan()

        scheduler.load_plan(_simple_plan())
        assert scheduler.has_active_plan()
        assert scheduler.state.status == "running"

    def test_load_plan_resets_previous_state(self):
        """load_plan 重置之前的 state。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher)
        scheduler.load_plan(_simple_plan(plan_id="first"))
        scheduler.state.completed_nodes.add("step_1")
        scheduler.state.node_results["step_1"] = {"success": True}

        scheduler.load_plan(_simple_plan(plan_id="second"))
        assert scheduler.state.current_plan.plan_id == "second"
        assert len(scheduler.state.completed_nodes) == 0
        assert len(scheduler.state.node_results) == 0

    # ── T2: next_node returns entry node when no deps ──────────────────────

    def test_next_node_returns_entry_node_no_deps(self):
        """T2: 无依赖时 next_node() 返回 entry node。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        plan = _simple_plan(
            nodes=(
                _node(node_id="step_1", depends_on=()),
                _node(node_id="step_2", depends_on=()),
            ),
            entry_node_id="step_1",
        )
        scheduler.load_plan(plan)

        node = scheduler.next_node()
        assert node is not None
        assert node.node_id == "step_1"

    # ── T3: next_node respects dependency order ────────────────────────────

    def test_next_node_respects_depends_on(self):
        """T3: depends_on 满足后才返回对应 node。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        plan = _simple_plan(
            nodes=(
                _node(node_id="step_1", depends_on=()),
                _node(node_id="step_2", depends_on=("step_1",)),
                _node(node_id="step_3", depends_on=("step_2",)),
            ),
            entry_node_id="step_1",
        )
        scheduler.load_plan(plan)

        # 第一轮：只有 step_1 满足
        n1 = scheduler.next_node()
        assert n1.node_id == "step_1"

        # 执行 step_1 后 step_2 才可用
        scheduler.execute_node(n1)
        n2 = scheduler.next_node()
        assert n2.node_id == "step_2"

        # 执行 step_2 后 step_3 才可用
        scheduler.execute_node(n2)
        n3 = scheduler.next_node()
        assert n3.node_id == "step_3"

    def test_next_node_returns_none_when_deps_unsatisfied(self):
        """有 node 但 depends_on 不满足时 next_node 返回 None。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        plan = _simple_plan(
            nodes=(
                _node(node_id="step_a", depends_on=("step_b",)),
                _node(node_id="step_b", depends_on=("step_a",)),
            ),
            entry_node_id="step_a",
        )
        scheduler.load_plan(plan)

        # 两个 node 互相依赖 → 都无法执行
        node = scheduler.next_node()
        assert node is None

    def test_entry_node_not_first_works_with_deps(self):
        """entry_node 不必是 nodes[0]——只要无 depends_on 就能返回。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        plan = _simple_plan(
            nodes=(
                _node(node_id="step_2", depends_on=("step_1",)),
                _node(node_id="step_1", depends_on=()),
            ),
            entry_node_id="step_1",
        )
        scheduler.load_plan(plan)

        node = scheduler.next_node()
        assert node.node_id == "step_1"


# ═══════════════════════════════════════════════════════════════════════════════
# T4-T6: Execution — executor integration, plan completion
# ═══════════════════════════════════════════════════════════════════════════════


class TestActionSchedulerExecution:
    """T4-T6: executor 调用、node 执行、plan 完成。"""

    # ── T4: execute TOOL_CALL node → calls executor ────────────────────────

    def test_execute_node_delegates_to_executor(self):
        """T4: execute_node 通过注入的 executor 执行，返回 result。"""
        dispatcher = _build_dispatcher()
        called = []

        def _record_exec(node, state):
            called.append((node.node_id, node.action_type, node.target))
            return {"success": True}

        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_record_exec)
        plan = _simple_plan(nodes=(_node(
            node_id="step_1", action_type="TOOL_CALL", target="web_search",
        ),))
        scheduler.load_plan(plan)

        node = scheduler.next_node()
        result = scheduler.execute_node(node)

        assert result["success"] is True
        assert len(called) == 1
        assert called[0] == ("step_1", "TOOL_CALL", "web_search")

    def test_execute_node_no_executor_returns_failure(self):
        """executor 未注入时 execute_node 返回 failure。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher)  # 无 executor
        plan = _simple_plan()
        scheduler.load_plan(plan)

        node = scheduler.next_node()
        result = scheduler.execute_node(node)

        assert result["success"] is False
        assert "no executor" in str(result.get("error", ""))

    def test_execute_node_catches_executor_exception(self):
        """executor 抛异常时 execute_node catch 并返回 failure。"""
        dispatcher = _build_dispatcher()

        def _crash(node, state):
            raise RuntimeError("boom")

        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_crash)
        plan = _simple_plan(nodes=(_node(
            node_id="crash_node",
            recovery=ActionRecoveryPolicy(on_failure="skip"),
        ),))
        scheduler.load_plan(plan)

        node = scheduler.next_node()
        result = scheduler.execute_node(node)

        assert result["success"] is False
        assert "RuntimeError" in str(result.get("error", ""))
        # crash 被 catch，不向上传播
        # skip 策略下 status 不会是 halted
        assert scheduler.state.status != "halted"

    # ── T5: execute MEMORY_RETAIN node → executor called ──────────────────

    def test_execute_memory_retain_node(self):
        """T5: MEMORY_RETAIN node 通过 executor 执行，参数正确传递。"""
        dispatcher = _build_dispatcher()
        captured_params = []

        def _exec(node, state):
            captured_params.append(dict(node.params))
            return {"success": True}

        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_exec)
        plan = _simple_plan(nodes=(_node(
            node_id="mem_1",
            action_type="MEMORY_RETAIN",
            target="user.memory",
            params={"key": "name", "value": "Alice"},
        ),))
        scheduler.load_plan(plan)

        node = scheduler.next_node()
        result = scheduler.execute_node(node)

        assert result["success"] is True
        assert len(captured_params) == 1
        assert captured_params[0] == {"key": "name", "value": "Alice"}

    # ── T6: complete_plan transitions status → completed ──────────────────

    def test_complete_plan_transitions_to_completed(self):
        """T6: 所有 node 完成后 complete_plan() 将 status 转为 completed。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        plan = _simple_plan(nodes=(
            _node(node_id="step_1"),
            _node(node_id="step_2"),
        ))
        scheduler.load_plan(plan)

        # 执行所有 node
        while True:
            node = scheduler.next_node()
            if node is None:
                break
            scheduler.execute_node(node)

        scheduler.complete_plan()
        assert scheduler.state.status == "completed"

    def test_complete_plan_produces_evidence(self):
        """complete_plan 在 dispatcher action_log 中产生 evidence。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        plan = _simple_plan(nodes=(_node(node_id="step_1"),))
        scheduler.load_plan(plan)
        # 查看 load_plan 产生的 evidence
        assert len(dispatcher.action_log) >= 1  # ACTION_PLAN_START

        node = scheduler.next_node()
        scheduler.execute_node(node)
        scheduler.complete_plan()

        # 至少应有: ACTION_PLAN_START + NODE_ENTER + NODE_EXIT + ACTION_PLAN_COMPLETE
        assert len(dispatcher.action_log) >= 4


# ═══════════════════════════════════════════════════════════════════════════════
# T7-T9: Recovery — halt/skip/fallback
# ═══════════════════════════════════════════════════════════════════════════════


class TestActionSchedulerRecovery:
    """T7-T9: 失败恢复策略（halt/skip/fallback）。"""

    # ── T7: node failure with on_failure=halt → halt_plan ──────────────────

    def test_failure_halt_stops_plan(self):
        """T7: on_failure=halt 时 halt_plan，后续 node 不执行。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_failing_executor("boom"))
        plan = _simple_plan(nodes=(
            _node(node_id="step_1", recovery=ActionRecoveryPolicy(on_failure="halt")),
            _node(node_id="step_2", depends_on=("step_1",)),
        ))
        scheduler.load_plan(plan)

        node = scheduler.next_node()
        assert node.node_id == "step_1"
        result = scheduler.execute_node(node)
        assert result["success"] is False

        # halt 后 has_active_plan 为 False
        assert scheduler.state.status == "halted"
        assert not scheduler.has_active_plan()

    # ── T8: node failure with on_failure=skip → continue to next ──────────

    def test_failure_skip_continues_to_next(self):
        """T8: on_failure=skip 时继续下一个无依赖 node。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_failing_executor("skip me"))
        plan = _simple_plan(nodes=(
            _node(node_id="step_1", recovery=ActionRecoveryPolicy(on_failure="skip")),
            _node(node_id="step_2", depends_on=("step_1",)),
        ))
        scheduler.load_plan(plan)

        # step_1 失败但 skip → step_1 标记 completed
        n1 = scheduler.next_node()
        scheduler.execute_node(n1)
        assert "step_1" in scheduler.state.completed_nodes

        # step_2 仍然可以执行（step_1 已 marked completed）
        n2 = scheduler.next_node()
        assert n2 is not None
        assert n2.node_id == "step_2"

    # ── T9: fallback_node_id → execute fallback on failure ────────────────

    def test_failure_fallback_node_available(self):
        """T9: on_failure=fallback 时 fallback_node 可被 next_node 返回。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(
            dispatcher=dispatcher, executor=_failing_executor("need fallback")
        )
        plan = _simple_plan(nodes=(
            _node(
                node_id="step_1",
                recovery=ActionRecoveryPolicy(
                    on_failure="fallback",
                    fallback_node_id="step_fb",
                ),
            ),
            _node(node_id="step_fb", depends_on=()),
        ))
        scheduler.load_plan(plan)

        # step_1 失败 → marked completed, fallback=step_fb 可用
        n1 = scheduler.next_node()
        scheduler.execute_node(n1)
        assert "step_1" in scheduler.state.completed_nodes

        # next_node 应该返回 step_fb
        n2 = scheduler.next_node()
        assert n2 is not None
        assert n2.node_id == "step_fb"

    def test_fallback_requires_fallback_node_id(self):
        """on_failure=fallback 但无 fallback_node_id 时构造失败。"""
        import pytest
        with pytest.raises(ValueError, match="fallback_node_id"):
            ActionRecoveryPolicy(on_failure="fallback")

    def test_invalid_on_failure_raises(self):
        """非法 on_failure 值构造时抛异常。"""
        import pytest
        with pytest.raises(ValueError, match="invalid on_failure"):
            ActionRecoveryPolicy(on_failure="retry")


# ═══════════════════════════════════════════════════════════════════════════════
# T10-T12: Dispatcher evidence
# ═══════════════════════════════════════════════════════════════════════════════


class TestActionSchedulerEvidence:
    """T10-T12: dispatcher evidence — plan start, node enter/exit, node failure。"""

    # ── T10: action_plan_start dispatcher evidence ────────────────────────

    def test_plan_start_produces_evidence(self):
        """T10: load_plan 触发 ACTION_PLAN_START evidence。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher)
        scheduler.load_plan(_simple_plan(plan_id="evidence_test"))

        # 检查 action_log 中有 ACTION_PLAN_START
        plan_starts = [
            e for e in dispatcher.action_log
            if str(e.action_type) == "scheduler.action_plan_start"
        ]
        assert len(plan_starts) >= 1, "load_plan 应产生 ACTION_PLAN_START evidence"
        evidence = dict(plan_starts[0].evidence)
        assert evidence.get("plan_id") == "evidence_test", (
            f"evidence 应含 plan_id='evidence_test'，实际: {evidence.get('plan_id')}"
        )

    # ── T11: node_enter/exit dispatcher evidence per node ─────────────────

    def test_node_enter_and_exit_evidence(self):
        """T11: 每个 node 的 enter/exit 产生 evidence。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        plan = _simple_plan(nodes=(_node(node_id="n1"), _node(node_id="n2")))
        scheduler.load_plan(plan)

        while True:
            node = scheduler.next_node()
            if node is None:
                break
            scheduler.execute_node(node)

        enters = [
            e for e in dispatcher.action_log
            if str(e.action_type) == "scheduler.node_enter"
        ]
        exits = [
            e for e in dispatcher.action_log
            if str(e.action_type) == "scheduler.node_exit"
        ]
        assert len(enters) == 2, f"应有 2 个 NODE_ENTER，实际 {len(enters)}"
        assert len(exits) == 2, f"应有 2 个 NODE_EXIT，实际 {len(exits)}"

    def test_node_exit_evidence_has_disposition(self):
        """NODE_EXIT evidence 含 disposition='completed'。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        plan = _simple_plan()
        scheduler.load_plan(plan)

        node = scheduler.next_node()
        scheduler.execute_node(node)

        exits = [
            e for e in dispatcher.action_log
            if str(e.action_type) == "scheduler.node_exit"
        ]
        assert len(exits) >= 1
        evidence = dict(exits[0].evidence)
        assert evidence.get("disposition") == "completed"

    # ── T12: node_failure dispatcher evidence ─────────────────────────────

    def test_node_failure_produces_evidence(self):
        """T12: node 失败时产生 NODE_FAILURE evidence（含 error）。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(
            dispatcher=dispatcher,
            executor=_failing_executor("specific error msg"),
        )
        plan = _simple_plan(nodes=(_node(
            node_id="will_fail",
            recovery=ActionRecoveryPolicy(on_failure="skip"),
        ),))
        scheduler.load_plan(plan)

        node = scheduler.next_node()
        scheduler.execute_node(node)

        failures = [
            e for e in dispatcher.action_log
            if str(e.action_type) == "scheduler.node_failure"
        ]
        assert len(failures) >= 1, "node 失败应产生 NODE_FAILURE evidence"
        evidence = dict(failures[0].evidence)
        assert "specific error" in str(evidence.get("error", "")), (
            f"evidence error 应含 'specific error'，实际: {evidence.get('error')}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# T13: RuntimeDecisionFrame reflects scheduler state
# ═══════════════════════════════════════════════════════════════════════════════


class TestActionSchedulerDecisionFrame:
    """T13: RuntimeDecisionFrame 正确反映 scheduler 状态。"""

    def test_decision_frame_includes_scheduler_fields(self):
        """RuntimeDecisionFrame 含 scheduler_active/plan_id/node_id 等字段。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        plan = _simple_plan(plan_id="df_test_plan", nodes=(
            _node(node_id="n1"),
            _node(node_id="n2"),
            _node(node_id="n3"),
        ))
        scheduler.load_plan(plan)

        frame = build_decision_frame_from_chat_params(
            "test input",
            action_scheduler=scheduler,
        )

        assert frame.scheduler_active is True
        assert frame.current_plan_id == "df_test_plan"
        assert frame.total_nodes == 3
        assert frame.completed_nodes == 0

    def test_decision_frame_scheduler_inactive_by_default(self):
        """无 scheduler 注入时 scheduler_active=False。"""
        frame = build_decision_frame_from_chat_params("test input")
        assert frame.scheduler_active is False
        assert frame.current_plan_id == ""
        assert frame.total_nodes == 0

    def test_decision_frame_reflects_completed_nodes(self):
        """completed_nodes 和 current_node_id 正确反映执行进度。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        plan = _simple_plan(nodes=(
            _node(node_id="a"),
            _node(node_id="b"),
        ))
        scheduler.load_plan(plan)

        # 执行第一个 node
        node = scheduler.next_node()
        scheduler.execute_node(node)

        frame = build_decision_frame_from_chat_params(
            "test input",
            action_scheduler=scheduler,
        )
        assert frame.completed_nodes == 1
        assert frame.current_node_id == "a"

    def test_scheduler_branch_points_in_all_branch_point_ids(self):
        """scheduler branch points 出现在 all_branch_point_ids() 中。"""
        frame = build_decision_frame("test")
        all_ids = frame.all_branch_point_ids()
        assert "scheduler.action_plan_start" in all_ids
        assert "scheduler.node_enter" in all_ids
        assert "scheduler.node_exit" in all_ids
        assert "scheduler.node_failure" in all_ids
        assert "scheduler.action_plan_complete" in all_ids


# ═══════════════════════════════════════════════════════════════════════════════
# T14-T15: Regression — model loop + guard check
# ═══════════════════════════════════════════════════════════════════════════════


class TestActionSchedulerRegression:
    """T14-T15: scheduler 不破坏现有 model loop 和 guard check。"""

    # ── T14: scheduler None → model loop 正常运行 ─────────────────────────

    def test_scheduler_none_does_not_break_loop(self):
        """T14: scheduler=None 时 has_active_plan() 等价于无 scheduler。"""
        # 验证无 scheduler 注入时不影响 loop
        scheduler = ActionScheduler()  # 无 dispatcher, 无 executor
        assert not scheduler.has_active_plan()
        assert scheduler.next_node() is None

        # 空 plan 不应 crash
        scheduler.state.reset()
        assert scheduler.state.status == "idle"

    # ── T15: guard check 仍然生效 ─────────────────────────────────────────

    def test_scheduler_stops_on_max_iterations_does_not_bypass_guard(self):
        """T15: scheduler 不绕过 max loop iterations guard check。"""
        # scheduler 使用 continue 跳过 model 调用，但 while True 仍然存在
        # 此处验证 scheduler 自身不引入无限循环——has_active_plan 在 plan 完成后为 False
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        plan = _simple_plan(nodes=(
            _node(node_id="s1"),
            _node(node_id="s2"),
            _node(node_id="s3"),
        ))
        scheduler.load_plan(plan)

        iterations = 0
        max_iterations = 100
        while scheduler.has_active_plan() and iterations < max_iterations:
            node = scheduler.next_node()
            if node is None:
                scheduler.complete_plan()
                break
            scheduler.execute_node(node)
            iterations += 1

        # 应该在有限迭代内完成（3 node → 3 次 execute_node）
        assert iterations <= 3, f"scheduler 不应无限循环，用了 {iterations} 次迭代"
        assert scheduler.state.status == "completed"


# ═══════════════════════════════════════════════════════════════════════════════
# T16-T18: Not fakeable guards
# ═══════════════════════════════════════════════════════════════════════════════


class TestActionSchedulerNotFakeable:
    """T16-T18: not fakeable — 不通过 direct call 冒充、不 crash-only、有 evidence。"""

    # ── T16: not fakeable — no direct-call-only ───────────────────────────

    def test_not_direct_call_only(self):
        """T16: execute_node 必须返回业务 outcome，不只是 noop。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        plan = _simple_plan()
        scheduler.load_plan(plan)

        node = scheduler.next_node()
        result = scheduler.execute_node(node)

        # 必须有明确的 success outcome
        assert result.get("success") is True
        # 必须有 node_id 追踪
        assert result.get("node_id") == "step_1"
        # dispatcher 必须有 evidence
        node_enters = [
            e for e in dispatcher.action_log
            if str(e.action_type) == "scheduler.node_enter"
        ]
        assert len(node_enters) >= 1, "NODE_ENTER 应有 dispatcher evidence"

    # ── T17: not fakeable — no crash-only ─────────────────────────────────

    def test_not_crash_only(self):
        """T17: execute_node 必须验证业务 outcome，不是只不 crash。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(
            dispatcher=dispatcher,
            executor=_failing_executor("business error"),
        )
        plan = _simple_plan(nodes=(_node(
            node_id="business_fail",
            recovery=ActionRecoveryPolicy(on_failure="skip"),
        ),))
        scheduler.load_plan(plan)

        node = scheduler.next_node()
        result = scheduler.execute_node(node)

        # 不 crash
        assert result is not None
        # 但业务失败：success=False
        assert result.get("success") is False
        # 错误信息必须具体
        assert "business error" in str(result.get("error", ""))
        # failure evidence 必须存在
        failures = [
            e for e in dispatcher.action_log
            if str(e.action_type) == "scheduler.node_failure"
        ]
        assert len(failures) >= 1, "业务失败应有 NODE_FAILURE evidence"

    # ── T18: not fakeable — dispatcher evidence present ───────────────────

    def test_dispatcher_evidence_present(self):
        """T18: 所有 scheduler action 必须有 dispatcher evidence。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        plan = _simple_plan(nodes=(_node(node_id="ev_n1"), _node(node_id="ev_n2")))
        scheduler.load_plan(plan)

        while True:
            node = scheduler.next_node()
            if node is None:
                break
            scheduler.execute_node(node)
        scheduler.complete_plan()

        # 验证所有 5 种 action type 都有 evidence
        action_types_found = {
            str(e.action_type) for e in dispatcher.action_log
        }
        expected = {
            "scheduler.action_plan_start",
            "scheduler.node_enter",
            "scheduler.node_exit",
            "scheduler.action_plan_complete",
        }
        missing = expected - action_types_found
        assert not missing, (
            f"缺少 dispatcher evidence: {missing}；已找到: {action_types_found}"
        )

    def test_no_dispatcher_still_executes(self):
        """dispatcher=None 时 scheduler 仍可运行（不 crash, 不产生 evidence）。"""
        scheduler = ActionScheduler(dispatcher=None, executor=_success_executor())
        scheduler.load_plan(_simple_plan())

        node = scheduler.next_node()
        result = scheduler.execute_node(node)

        assert result["success"] is True
        # 无 dispatcher → 无 crash，但不声称有 evidence
        # （无 action_log 可查，所以此测试只验证不 crash）


# ═══════════════════════════════════════════════════════════════════════════════
# T19-T20: Edge cases — condition flags, empty plan, boundary
# ═══════════════════════════════════════════════════════════════════════════════


class TestActionSchedulerEdge:
    """T19-T20: condition flags, empty plan, dataclass 不变式。"""

    # ── T19: condition flag → skip node ───────────────────────────────────

    def test_condition_flag_skips_node(self):
        """T19: condition_flags 匹配时跳过 node。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        plan = _simple_plan(nodes=(
            _node(node_id="step_1"),
            _node(node_id="step_2", condition="skip_step_2"),
        ))
        scheduler.load_plan(plan)
        # 设置 condition flag
        scheduler.state.condition_flags["skip_step_2"] = True

        # 执行 step_1
        n1 = scheduler.next_node()
        scheduler.execute_node(n1)

        # step_2 应该因 condition flag 被跳过
        n2 = scheduler.next_node()
        assert n2 is None  # 没有剩余的 node
        assert "step_2" in scheduler.state.completed_nodes
        assert scheduler.state.node_results["step_2"]["skipped"] is True

    def test_condition_flag_false_does_not_skip(self):
        """condition flag=False 时不跳过 node。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        plan = _simple_plan(nodes=(
            _node(node_id="step_1"),
            _node(node_id="step_2", condition="flag_x"),
        ))
        scheduler.load_plan(plan)
        scheduler.state.condition_flags["flag_x"] = False

        n1 = scheduler.next_node()
        scheduler.execute_node(n1)

        n2 = scheduler.next_node()
        assert n2 is not None
        assert n2.node_id == "step_2"  # 未跳过

    def test_condition_skip_produces_node_exit_evidence(self):
        """condition skip 时产生 NODE_EXIT evidence（disposition=skipped）。"""
        dispatcher = _build_dispatcher()
        scheduler = ActionScheduler(dispatcher=dispatcher, executor=_success_executor())
        plan = _simple_plan(nodes=(_node(
            node_id="skip_me", condition="skip",
        ),))
        scheduler.load_plan(plan)
        scheduler.state.condition_flags["skip"] = True

        # next_node 触发 skip
        node = scheduler.next_node()
        assert node is None  # 被跳过

        exits = [
            e for e in dispatcher.action_log
            if str(e.action_type) == "scheduler.node_exit"
        ]
        skip_exits = [
            e for e in exits
            if dict(e.evidence).get("disposition") == "skipped"
        ]
        assert len(skip_exits) >= 1, "skip 应有 NODE_EXIT disposition=skipped evidence"

    # ── T20: empty plan → no-op, no crash ─────────────────────────────────

    def test_empty_plan_raises_on_construction(self):
        """T20: 空 nodes 在 ActionPlan 构造时抛异常。"""
        import pytest
        with pytest.raises(ValueError, match="nodes"):
            ActionPlan(plan_id="empty", nodes=(), entry_node_id="x")

    def test_empty_nodes_in_dict_raises(self):
        """build_action_plan_from_dict 空 nodes 抛异常。"""
        import pytest
        with pytest.raises(ValueError, match="nodes"):
            build_action_plan_from_dict({"plan_id": "x", "nodes": [], "entry_node_id": "x"})

    # ── Dataclass 不变式 ──────────────────────────────────────────────────

    def test_action_node_empty_node_id_raises(self):
        """node_id 为空时 ActionNode 构造抛异常。"""
        import pytest
        with pytest.raises(ValueError, match="node_id"):
            ActionNode(node_id="", action_type="X", target="Y")

    def test_action_node_empty_action_type_raises(self):
        """action_type 为空时 ActionNode 构造抛异常。"""
        import pytest
        with pytest.raises(ValueError, match="action_type"):
            ActionNode(node_id="x", action_type="", target="Y")

    def test_action_node_empty_target_raises(self):
        """target 为空时 ActionNode 构造抛异常。"""
        import pytest
        with pytest.raises(ValueError, match="target"):
            ActionNode(node_id="x", action_type="X", target="")

    def test_action_plan_invalid_entry_node_raises(self):
        """entry_node_id 不在 nodes 中时抛异常。"""
        import pytest
        with pytest.raises(ValueError, match="entry_node_id"):
            ActionPlan(
                plan_id="p",
                nodes=(_node(node_id="real_node"),),
                entry_node_id="ghost_node",
            )

    def test_action_plan_invalid_depends_on_raises(self):
        """depends_on 引用不存在的 node 时抛异常。"""
        import pytest
        with pytest.raises(ValueError, match="depends_on"):
            ActionPlan(
                plan_id="p",
                nodes=(_node(node_id="n1", depends_on=("n2",)),),
                entry_node_id="n1",
            )

    def test_action_plan_invalid_status_raises(self):
        """非法 status 时 ActionPlan 构造抛异常。"""
        import pytest
        with pytest.raises(ValueError, match="status"):
            ActionPlan(
                plan_id="p",
                nodes=(_node(),),
                entry_node_id="step_1",
                status="invalid_status",
            )

    # ── build_action_plan_from_dict factory ────────────────────────────────

    def test_build_plan_from_dict_minimal(self):
        """最小 dict 构造完整 ActionPlan。"""
        plan = build_action_plan_from_dict({
            "plan_id": "minimal",
            "entry_node_id": "n1",
            "nodes": [
                {"node_id": "n1", "action_type": "TOOL_CALL", "target": "echo"},
            ],
        })
        assert plan.plan_id == "minimal"
        assert len(plan.nodes) == 1
        assert plan.nodes[0].node_id == "n1"

    def test_build_plan_from_dict_full(self):
        """完整 dict（含 depends_on, recovery, condition, description）构造。"""
        plan = build_action_plan_from_dict({
            "plan_id": "full",
            "entry_node_id": "n1",
            "description": "test plan",
            "nodes": [
                {
                    "node_id": "n1",
                    "action_type": "MEMORY_RETAIN",
                    "target": "user.memory",
                    "params": {"key": "v"},
                    "depends_on": [],
                    "recovery": {"on_failure": "skip", "max_retries": 0},
                    "condition": None,
                    "description": "retain user memory",
                },
                {
                    "node_id": "n2",
                    "action_type": "TOOL_CALL",
                    "target": "search",
                    "depends_on": ["n1"],
                },
            ],
        })
        assert plan.plan_id == "full"
        assert plan.description == "test plan"
        assert len(plan.nodes) == 2
        assert plan.nodes[0].recovery.on_failure == "skip"
        assert plan.nodes[1].depends_on == ("n1",)

    # ── Scheduler state ────────────────────────────────────────────────────

    def test_scheduler_reset_clears_all_state(self):
        """reset() 清空所有 per-turn 状态。"""
        state = SchedulerState()
        state.current_plan = _simple_plan()
        state.current_node_id = "n1"
        state.completed_nodes.add("n1")
        state.failed_nodes["n1"] = 1
        state.condition_flags["f"] = True
        state.node_results["n1"] = {"success": True}
        state.status = "running"

        state.reset()

        assert state.current_plan is None
        assert state.current_node_id is None
        assert len(state.completed_nodes) == 0
        assert len(state.failed_nodes) == 0
        assert len(state.condition_flags) == 0
        assert len(state.node_results) == 0
        assert state.status == "idle"

    def test_has_active_plan_only_when_running(self):
        """has_active_plan 仅在 current_plan 非 None 且 status='running' 时为 True。"""
        state = SchedulerState()
        assert not state.has_active_plan

        state.current_plan = _simple_plan()
        state.status = "running"
        assert state.has_active_plan

        state.status = "completed"
        assert not state.has_active_plan

        state.status = "halted"
        assert not state.has_active_plan
