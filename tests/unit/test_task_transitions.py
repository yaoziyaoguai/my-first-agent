"""Phase 1A Task Transition API unit tests.

覆盖 apply_task_transition() 的：
- 合法 transition（plan accept / tool accept/reject/feedback）
- expected_from_status mismatch → denied
- invalid transition → denied
- denied 时不修改状态
- checkpoint_action per-rule 正确
- Phase 1A table 不含 feedback_intent / origin_status restore rules
- transition table coverage 只检查 Phase 1A covered statuses
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.confirmation.dispatcher import ConfirmationContext
from agent.confirmation.tool import handle_tool_confirmation
from agent.transitions import (
    CheckpointAction,
    TaskTransitionRequest,
    TransitionEvent,
    apply_task_transition,
    validate_task_transition,
)

# ---------------------------------------------------------------------------
# 最小 state stub — 只暴露 task.status，不依赖完整 AgentState
# ---------------------------------------------------------------------------


@dataclass
class _TaskStub:
    status: str


@dataclass
class _StateStub:
    task: _TaskStub


def _make_state(status: str) -> _StateStub:
    return _StateStub(task=_TaskStub(status=status))


# ============================================================================
# A. apply_task_transition core tests
# ============================================================================


class TestApplyTaskTransitionValid:
    """合法 transition 测试。"""

    def test_plan_accept(self):
        state = _make_state("awaiting_plan_confirmation")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_ACCEPTED,
            owner="confirmation.plan.accept",
            expected_from_status="awaiting_plan_confirmation",
        ))
        assert result.allowed is True
        assert result.next_status == "running"
        assert result.previous_status == "awaiting_plan_confirmation"
        assert result.checkpoint_action == CheckpointAction.SAVE
        assert state.task.status == "running"

    def test_tool_accept(self):
        state = _make_state("awaiting_tool_confirmation")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_ACCEPTED,
            owner="confirmation.tool.accept_success",
            expected_from_status="awaiting_tool_confirmation",
        ))
        assert result.allowed is True
        assert result.next_status == "running"
        assert result.checkpoint_action == CheckpointAction.SAVE
        assert state.task.status == "running"

    def test_tool_reject(self):
        state = _make_state("awaiting_tool_confirmation")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_REJECTED,
            owner="confirmation.tool.reject",
            expected_from_status="awaiting_tool_confirmation",
        ))
        assert result.allowed is True
        assert result.next_status == "running"
        assert result.checkpoint_action == CheckpointAction.SAVE
        assert state.task.status == "running"

    def test_tool_feedback(self):
        state = _make_state("awaiting_tool_confirmation")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_FEEDBACK,
            owner="confirmation.tool.feedback",
            expected_from_status="awaiting_tool_confirmation",
        ))
        assert result.allowed is True
        assert result.next_status == "running"
        assert result.checkpoint_action == CheckpointAction.SAVE
        assert state.task.status == "running"

    def test_without_expected_from_status(self):
        """expected_from_status=None 时跳过断言，正常 transition。"""
        state = _make_state("awaiting_tool_confirmation")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_ACCEPTED,
            owner="test",
        ))
        assert result.allowed is True
        assert result.next_status == "running"


class TestApplyTaskTransitionDenied:
    """denied transition 测试。"""

    def test_expected_from_status_mismatch(self):
        state = _make_state("awaiting_tool_confirmation")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_ACCEPTED,
            owner="test",
            expected_from_status="awaiting_plan_confirmation",
        ))
        assert result.allowed is False
        assert result.next_status is None
        assert result.checkpoint_action == CheckpointAction.NONE
        assert "mismatch" in result.reason.lower()
        # 状态未被修改
        assert state.task.status == "awaiting_tool_confirmation"

    def test_invalid_transition_no_rule(self):
        """running + USER_ACCEPTED 不在 Phase 1A table 中。"""
        state = _make_state("running")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_ACCEPTED,
            owner="test",
        ))
        assert result.allowed is False
        assert result.next_status is None
        assert result.checkpoint_action == CheckpointAction.NONE
        assert "no transition rule" in result.reason.lower()
        assert state.task.status == "running"

    def test_invalid_transition_wrong_event(self):
        """awaiting_plan_confirmation + USER_REJECTED 不在 Phase 1A table 中。"""
        state = _make_state("awaiting_plan_confirmation")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_REJECTED,
            owner="test",
        ))
        assert result.allowed is False
        assert result.next_status is None

    def test_denied_no_state_mutation(self):
        """所有 denied 路径都不应修改 state.task.status。"""
        test_cases = [
            ("running", TransitionEvent.USER_ACCEPTED, None),
            ("done", TransitionEvent.USER_ACCEPTED, None),
            ("awaiting_plan_confirmation", TransitionEvent.USER_REJECTED, None),
            ("awaiting_tool_confirmation", TransitionEvent.USER_ACCEPTED,
             "awaiting_plan_confirmation"),  # expected mismatch
        ]
        for from_status, event, expected in test_cases:
            state = _make_state(from_status)
            original = state.task.status
            result = apply_task_transition(state, TaskTransitionRequest(
                event=event,
                owner="test",
                expected_from_status=expected,
            ))
            assert result.allowed is False, f"expected denied for {from_status}+{event}"
            assert state.task.status == original, (
                f"state mutated after denied: {original} → {state.task.status}"
            )

    def test_denied_checkpoint_action_is_none(self):
        """所有 denied 结果 checkpoint_action 必须为 NONE。"""
        denied_cases = [
            ("running", TransitionEvent.USER_ACCEPTED, None),
            ("done", TransitionEvent.USER_ACCEPTED, None),
            ("awaiting_plan_confirmation", TransitionEvent.USER_REJECTED, None),
        ]
        for from_status, event, expected in denied_cases:
            state = _make_state(from_status)
            result = apply_task_transition(state, TaskTransitionRequest(
                event=event,
                owner="test",
                expected_from_status=expected,
            ))
            assert result.checkpoint_action == CheckpointAction.NONE, (
                f"checkpoint_action should be NONE for denied {from_status}+{event}"
            )


# ============================================================================
# B. transition table coverage tests
# ============================================================================


# Phase 1A covered statuses
PHASE_1A_COVERED_STATUSES = {
    "awaiting_plan_confirmation",
    "awaiting_tool_confirmation",
}

# deferred statuses — 允许无 transition rule
DEFERRED_STATUSES = {
    "awaiting_resume_choice",
    "awaiting_interrupt_choice",
    "awaiting_user_input",
    "awaiting_step_confirmation",
    "awaiting_feedback_intent",
    "idle",
    "planning",
    "running",
    "done",
    "failed",
    "cancelled",
}


class TestPhase1ACoverage:
    """transition table coverage — 只检查 Phase 1A covered statuses。"""

    def test_all_phase1a_covered_statuses_have_rules(self):
        """Phase 1A 覆盖的每个 status 至少有一条 outgoing transition。"""
        from agent.transitions import _TRANSITION_TABLE

        covered_with_rules: set[str] = set()
        for (from_status, _event), _rule in _TRANSITION_TABLE.items():
            if from_status in PHASE_1A_COVERED_STATUSES:
                covered_with_rules.add(from_status)

        missing = PHASE_1A_COVERED_STATUSES - covered_with_rules
        assert missing == set(), (
            f"Phase 1A covered statuses missing transition rules: {missing}"
        )

    def test_deferred_statuses_allowed_no_rules(self):
        """deferred statuses 允许无 transition rule。"""

        for status in DEFERRED_STATUSES:
            # 不要求每个 deferred status 都有 rule
            # 这里只验证它们确实不在 Phase 1A covered set 中
            assert status not in PHASE_1A_COVERED_STATUSES, (
                f"{status} is in DEFERRED_STATUSES but also in "
                f"PHASE_1A_COVERED_STATUSES — inconsistency"
            )

    def test_no_feedback_intent_rules_in_phase1a(self):
        """Phase 1A table 不含 feedback_intent / origin_status restore rules。"""
        from agent.transitions import _TRANSITION_TABLE

        for (from_status, event), _rule in _TRANSITION_TABLE.items():
            assert from_status != "awaiting_feedback_intent", (
                f"Phase 1A table must not contain awaiting_feedback_intent rule: "
                f"({from_status!r}, {event!r})"
            )
            assert from_status != "running" or event not in (
                TransitionEvent.FEEDBACK_INTENT_REQUIRED,
            ), (
                f"Phase 1A table must not contain feedback_intent rule: "
                f"({from_status!r}, {event!r})"
            )

    def test_no_origin_status_restore_in_phase1a(self):
        """Phase 1A table 中 to_status 不含 sentinel。"""
        from agent.transitions import _TRANSITION_TABLE

        for (from_status, event), rule in _TRANSITION_TABLE.items():
            assert rule.to_status != "<origin_status>", (
                f"Phase 1A table must not contain origin_status sentinel: "
                f"({from_status!r}, {event!r}) → {rule.to_status!r}"
            )

    def test_transition_table_keys_exact_phase1a(self):
        """_TRANSITION_TABLE 键恰好等于 Phase 1A 四条规则。"""
        from agent.transitions import _TRANSITION_TABLE

        expected_keys = {
            ("awaiting_plan_confirmation", TransitionEvent.USER_ACCEPTED),
            ("awaiting_tool_confirmation", TransitionEvent.USER_ACCEPTED),
            ("awaiting_tool_confirmation", TransitionEvent.USER_REJECTED),
            ("awaiting_tool_confirmation", TransitionEvent.USER_FEEDBACK),
        }
        actual_keys = set(_TRANSITION_TABLE.keys())
        assert actual_keys == expected_keys, (
            f"Phase 1A table keys mismatch.\n"
            f"Extra: {actual_keys - expected_keys}\n"
            f"Missing: {expected_keys - actual_keys}"
        )


# ============================================================================
# C. CheckpointAction per-rule 正确性
# ============================================================================


class TestCheckpointActionPerRule:
    """验证每条 Phase 1A rule 的 checkpoint_action 正确。"""

    def test_all_phase1a_rules_have_save_checkpoint(self):
        """Phase 1A 所有 rule 的 checkpoint_action 均为 SAVE。"""
        from agent.transitions import _TRANSITION_TABLE

        for (from_status, event), rule in _TRANSITION_TABLE.items():
            if from_status in PHASE_1A_COVERED_STATUSES:
                assert rule.checkpoint_action == CheckpointAction.SAVE, (
                    f"Phase 1A rule ({from_status!r}, {event!r}) "
                    f"expected SAVE, got {rule.checkpoint_action}"
                )

    def test_checkpoint_action_not_both_save_and_clear(self):
        """单一 CheckpointAction 不可能同时为 SAVE 和 CLEAR（enum 互斥）。"""
        # enum 值互斥，此测试确认 NONE/SAVE/CLEAR 各不相同
        values = {CheckpointAction.NONE, CheckpointAction.SAVE, CheckpointAction.CLEAR}
        assert len(values) == 3


# ============================================================================
# D. TransitionRule invariants
# ============================================================================


class TestTransitionRuleInvariants:
    """TransitionRule 基本不变量。"""

    def test_to_status_is_non_empty(self):
        from agent.transitions import _TRANSITION_TABLE

        for key, rule in _TRANSITION_TABLE.items():
            assert rule.to_status, (
                f"TransitionRule.to_status must be non-empty for key={key}"
            )

    def test_all_to_status_values_are_known(self):
        """to_status 值应为当前已知合法 status。"""
        from agent.transitions import _TRANSITION_TABLE

        known = {
            "idle", "planning", "running",
            "awaiting_plan_confirmation", "awaiting_step_confirmation",
            "awaiting_tool_confirmation", "awaiting_user_input",
            "awaiting_feedback_intent", "awaiting_resume_choice",
            "awaiting_interrupt_choice",
            "done", "failed", "cancelled",
        }
        for key, rule in _TRANSITION_TABLE.items():
            assert rule.to_status in known, (
                f"Unknown to_status={rule.to_status!r} in rule for key={key}"
            )


# ============================================================================
# E. TaskTransitionRequest / TaskTransitionResult 结构测试
# ============================================================================


class TestTaskTransitionRequestStructure:
    """TaskTransitionRequest 不包含权威 from_status。"""

    def test_no_from_status_field(self):
        """TaskTransitionRequest 不应有 from_status 字段。"""
        import dataclasses
        fields = {f.name for f in dataclasses.fields(TaskTransitionRequest)}
        assert "from_status" not in fields, (
            "TaskTransitionRequest must not expose from_status — "
            "actual previous_status is read from state.task.status internally"
        )
        assert "expected_from_status" in fields
        assert "event" in fields
        assert "owner" in fields


class TestTaskTransitionResultStructure:
    """TaskTransitionResult 结构完整性。"""

    def test_allowed_false_has_next_status_none(self):
        state = _make_state("running")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_ACCEPTED,
            owner="test",
        ))
        assert result.allowed is False
        assert result.next_status is None

    def test_allowed_true_has_next_status_set(self):
        state = _make_state("awaiting_tool_confirmation")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_ACCEPTED,
            owner="test",
        ))
        assert result.allowed is True
        assert result.next_status is not None

    def test_result_contains_owner_and_event(self):
        state = _make_state("awaiting_tool_confirmation")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_ACCEPTED,
            owner="confirmation.tool.accept_success",
        ))
        assert result.owner == "confirmation.tool.accept_success"
        assert result.event == TransitionEvent.USER_ACCEPTED


# ============================================================================
# F. validate_task_transition 测试
# ============================================================================


class TestValidateTaskTransition:
    """validate_task_transition() 只读验证，不修改状态。"""

    def test_validate_allowed_does_not_mutate(self):
        state = _make_state("awaiting_tool_confirmation")
        original = state.task.status
        result = validate_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_ACCEPTED,
            owner="test",
            expected_from_status="awaiting_tool_confirmation",
        ))
        assert result.allowed is True
        assert result.next_status == "running"
        assert state.task.status == original, (
            "validate_task_transition must not mutate state.task.status"
        )

    def test_validate_denied_mismatch(self):
        state = _make_state("running")
        result = validate_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_ACCEPTED,
            owner="test",
            expected_from_status="awaiting_tool_confirmation",
        ))
        assert result.allowed is False
        assert "mismatch" in result.reason.lower()

    def test_validate_denied_no_rule(self):
        state = _make_state("running")
        result = validate_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_ACCEPTED,
            owner="test",
        ))
        assert result.allowed is False
        assert "no transition rule" in result.reason.lower()

    def test_validate_returns_same_checkpoint_action(self):
        state = _make_state("awaiting_tool_confirmation")
        result = validate_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_ACCEPTED,
            owner="test",
            expected_from_status="awaiting_tool_confirmation",
        ))
        assert result.allowed is True
        assert result.checkpoint_action == CheckpointAction.SAVE


# ============================================================================
# G. Stale state preflight 拒绝测试
# ============================================================================


class TestStaleStatePreflightDenied:
    """stale/non-awaiting state 下 preflight 拒绝且无副作用。"""

    def test_accept_stale_state_rejected_no_tool_executed(self):
        """running 状态下 tool accept 不应执行工具。"""
        state = _make_state("running")
        preflight = validate_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_ACCEPTED,
            owner="test",
            expected_from_status="awaiting_tool_confirmation",
        ))
        assert preflight.allowed is False
        assert state.task.status == "running"

    def test_reject_stale_state_rejected_no_side_effects(self):
        """running 状态下 tool reject 不应通过 preflight。"""
        state = _make_state("running")
        preflight = validate_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_REJECTED,
            owner="test",
            expected_from_status="awaiting_tool_confirmation",
        ))
        assert preflight.allowed is False
        assert state.task.status == "running"

    def test_feedback_stale_state_rejected_no_side_effects(self):
        """running 状态下 tool feedback 不应通过 preflight。"""
        state = _make_state("running")
        preflight = validate_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_FEEDBACK,
            owner="test",
            expected_from_status="awaiting_tool_confirmation",
        ))
        assert preflight.allowed is False
        assert state.task.status == "running"


# ============================================================================
# H. Handler-level stale-state tests — 真实 handler 覆盖
# ============================================================================
# 以下测试调用真实 handle_tool_confirmation() 而非仅 validate_task_transition()，
# 验证 handler 中前置验证未被移除或移动。即使 validate_task_transition() 单元测试
# 通过，若 handler 中前置验证被删除，以下测试仍会因副作用而失败。


def _make_handler_state(status: str):
    """构造 handler 所需最小 state，含 pending_tool、messages。"""
    from types import SimpleNamespace
    state = SimpleNamespace()
    state.task = SimpleNamespace()
    state.task.status = status
    state.task.pending_tool = {
        "tool": "write_file",
        "tool_use_id": "toolu_stale_test",
        "input": {"path": "test.txt"},
    }
    state.task.tool_execution_log = {}
    state.conversation = SimpleNamespace()
    state.conversation.messages = []
    return state


def _make_handler_ctx(state):
    """构造 ConfirmationContext with no-op continue_fn。"""
    from types import SimpleNamespace
    turn_state = SimpleNamespace()
    turn_state.on_display_event = lambda _e: None
    return ConfirmationContext(
        state=state,
        turn_state=turn_state,
        client=None,
        model_name="test-model",
        continue_fn=lambda ts: "continued",
    )


class TestStaleStateHandlerRejects:
    """真实 handler 级：stale/non-awaiting state 下拒绝执行且无副作用。"""

    def test_accept_stale_state_handler_rejects(self):
        """running 下调用 handle_tool_confirmation("y") → 拒绝，无工具执行。"""
        state = _make_handler_state("running")
        ctx = _make_handler_ctx(state)
        original_pending = dict(state.task.pending_tool)
        original_messages_len = len(state.conversation.messages)

        result = handle_tool_confirmation("y", ctx)

        # handler 返回错误信息
        assert "前置验证失败" in result
        # pending_tool 未被清理
        assert state.task.pending_tool == original_pending
        # messages 未被修改
        assert len(state.conversation.messages) == original_messages_len
        # 状态未变
        assert state.task.status == "running"

    def test_reject_stale_state_handler_rejects(self):
        """running 下调用 handle_tool_confirmation("n") → 拒绝，无副作用。"""
        state = _make_handler_state("running")
        ctx = _make_handler_ctx(state)
        original_pending = dict(state.task.pending_tool)
        original_messages_len = len(state.conversation.messages)

        result = handle_tool_confirmation("n", ctx)

        assert "前置验证失败" in result
        assert state.task.pending_tool == original_pending
        assert len(state.conversation.messages) == original_messages_len
        assert state.task.status == "running"

    def test_feedback_stale_state_handler_rejects(self):
        """running 下调用 handle_tool_confirmation("feedback") → 拒绝，无副作用。"""
        state = _make_handler_state("running")
        ctx = _make_handler_ctx(state)
        original_pending = dict(state.task.pending_tool)
        original_messages_len = len(state.conversation.messages)

        result = handle_tool_confirmation("请改用 read_file", ctx)

        assert "前置验证失败" in result
        assert state.task.pending_tool == original_pending
        assert len(state.conversation.messages) == original_messages_len
        assert state.task.status == "running"

    def test_non_awaiting_accept_does_not_call_continue_fn(self):
        """stale state 下 accept 不触发 continue_fn。"""
        state = _make_handler_state("running")
        called = []

        def _track_continue(ts):
            called.append(1)
            return "continued"

        from types import SimpleNamespace
        turn_state = SimpleNamespace()
        turn_state.on_display_event = lambda _e: None
        ctx = ConfirmationContext(
            state=state,
            turn_state=turn_state,
            client=None,
            model_name="test-model",
            continue_fn=_track_continue,
        )

        handle_tool_confirmation("y", ctx)
        assert len(called) == 0, "stale state 下 accept 不应触发 continue_fn"

    def test_non_awaiting_reject_does_not_call_continue_fn(self):
        """stale state 下 reject 不触发 continue_fn。"""
        state = _make_handler_state("running")
        called = []

        def _track_continue(ts):
            called.append(1)
            return "continued"

        from types import SimpleNamespace
        turn_state = SimpleNamespace()
        turn_state.on_display_event = lambda _e: None
        ctx = ConfirmationContext(
            state=state,
            turn_state=turn_state,
            client=None,
            model_name="test-model",
            continue_fn=_track_continue,
        )

        handle_tool_confirmation("n", ctx)
        assert len(called) == 0, "stale state 下 reject 不应触发 continue_fn"
