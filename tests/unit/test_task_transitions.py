"""Phase 1A + Phase 1B Task Transition API unit tests.

覆盖 apply_task_transition() 的：
- Phase 1A: plan/tool confirmation transitions
- Phase 1B: feedback_intent request/cancel/as_feedback transitions
- Phase 1B: PLAN_GENERATED transitions (both origin_status paths)
- Phase 1B: origin_status sentinel resolution
- Phase 1B: resolve_origin_status() validation
- expected_from_status mismatch → denied
- invalid transition → denied
- denied 时不修改状态
- checkpoint_action per-rule 正确
- transition table keys exactness (Phase 1A 4 + Phase 1B 6 = 10)
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.confirmation.dispatcher import ConfirmationContext
from agent.confirmation.tool import handle_tool_confirmation
from agent.transitions import (
    _ORIGIN_STATUS_ALLOWLIST,
    CheckpointAction,
    TaskTransitionRequest,
    TransitionEvent,
    apply_task_transition,
    resolve_origin_status,
    validate_task_transition,
)

# ---------------------------------------------------------------------------
# 最小 state stub — 只暴露 task.status，不依赖完整 AgentState
# ---------------------------------------------------------------------------


@dataclass
class _TaskStub:
    status: str
    pending_user_input_request: dict | None = None


@dataclass
class _StateStub:
    task: _TaskStub


def _make_state(status: str, pending: dict | None = None) -> _StateStub:
    return _StateStub(task=_TaskStub(status=status, pending_user_input_request=pending))


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


class TestPhase1BCoverage:
    """transition table coverage — Phase 1A + Phase 1B。"""

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
            assert status not in PHASE_1A_COVERED_STATUSES, (
                f"{status} is in DEFERRED_STATUSES but also in "
                f"PHASE_1A_COVERED_STATUSES — inconsistency"
            )

    def test_phase1b_feedback_intent_rules_present(self):
        """Phase 1B: feedback_intent request rules 存在。"""
        from agent.transitions import _TRANSITION_TABLE

        keys = set(_TRANSITION_TABLE.keys())
        assert ("awaiting_plan_confirmation", TransitionEvent.FEEDBACK_INTENT_REQUIRED) in keys
        assert ("awaiting_step_confirmation", TransitionEvent.FEEDBACK_INTENT_REQUIRED) in keys
        assert ("awaiting_feedback_intent", TransitionEvent.USER_CANCELLED) in keys
        assert ("awaiting_feedback_intent", TransitionEvent.FEEDBACK_INTENT_AS_FEEDBACK) in keys

    def test_phase1b_origin_status_sentinel_rules_use_sentinel(self):
        """Phase 1B: restore origin_status 的 rule 使用 <origin_status> sentinel。"""
        from agent.transitions import _TRANSITION_TABLE

        cancel_rule = _TRANSITION_TABLE[
            ("awaiting_feedback_intent", TransitionEvent.USER_CANCELLED)
        ]
        as_feedback_rule = _TRANSITION_TABLE[
            ("awaiting_feedback_intent", TransitionEvent.FEEDBACK_INTENT_AS_FEEDBACK)
        ]
        assert cancel_rule.to_status == "<origin_status>"
        assert as_feedback_rule.to_status == "<origin_status>"
        assert cancel_rule.checkpoint_action == CheckpointAction.SAVE
        assert as_feedback_rule.checkpoint_action == CheckpointAction.SAVE

    def test_phase1b_plan_generated_rules_present(self):
        """Phase 1B: PLAN_GENERATED rules 覆盖两种 origin。"""
        from agent.transitions import _TRANSITION_TABLE

        keys = set(_TRANSITION_TABLE.keys())
        assert ("awaiting_plan_confirmation", TransitionEvent.PLAN_GENERATED) in keys
        assert ("awaiting_step_confirmation", TransitionEvent.PLAN_GENERATED) in keys

        plan_rule = _TRANSITION_TABLE[
            ("awaiting_plan_confirmation", TransitionEvent.PLAN_GENERATED)
        ]
        step_rule = _TRANSITION_TABLE[
            ("awaiting_step_confirmation", TransitionEvent.PLAN_GENERATED)
        ]
        assert plan_rule.to_status == "awaiting_plan_confirmation"
        assert step_rule.to_status == "awaiting_plan_confirmation"
        assert plan_rule.checkpoint_action == CheckpointAction.SAVE
        assert step_rule.checkpoint_action == CheckpointAction.SAVE

    def test_transition_table_keys_exact(self):
        """_TRANSITION_TABLE 键恰好等于 Phase 1A (4) + Phase 1B (6) = 10 rules。"""
        from agent.transitions import _TRANSITION_TABLE

        expected_keys = {
            # Phase 1A (4)
            ("awaiting_plan_confirmation", TransitionEvent.USER_ACCEPTED),
            ("awaiting_tool_confirmation", TransitionEvent.USER_ACCEPTED),
            ("awaiting_tool_confirmation", TransitionEvent.USER_REJECTED),
            ("awaiting_tool_confirmation", TransitionEvent.USER_FEEDBACK),
            # Phase 1B: feedback_intent request (2)
            ("awaiting_plan_confirmation", TransitionEvent.FEEDBACK_INTENT_REQUIRED),
            ("awaiting_step_confirmation", TransitionEvent.FEEDBACK_INTENT_REQUIRED),
            # Phase 1B: feedback_intent cancel / as_feedback restore (2)
            ("awaiting_feedback_intent", TransitionEvent.USER_CANCELLED),
            ("awaiting_feedback_intent", TransitionEvent.FEEDBACK_INTENT_AS_FEEDBACK),
            # Phase 1B: planner re-generate after feedback (2)
            ("awaiting_plan_confirmation", TransitionEvent.PLAN_GENERATED),
            ("awaiting_step_confirmation", TransitionEvent.PLAN_GENERATED),
        }
        actual_keys = set(_TRANSITION_TABLE.keys())
        assert actual_keys == expected_keys, (
            f"Table keys mismatch.\n"
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
        """to_status 值应为已知合法 status 或 <origin_status> sentinel。"""
        from agent.transitions import _TRANSITION_TABLE

        known = {
            "idle", "planning", "running",
            "awaiting_plan_confirmation", "awaiting_step_confirmation",
            "awaiting_tool_confirmation", "awaiting_user_input",
            "awaiting_feedback_intent", "awaiting_resume_choice",
            "awaiting_interrupt_choice",
            "done", "failed", "cancelled",
            "<origin_status>",  # Phase 1B sentinel
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


# ============================================================================
# I. resolve_origin_status 测试
# ============================================================================


class TestOriginStatusResolver:
    """resolve_origin_status() 的 allowlist 验证。"""

    def test_awaiting_plan_confirmation_allowed(self):
        state = _make_state("running", pending={"origin_status": "awaiting_plan_confirmation"})
        assert resolve_origin_status(state) == "awaiting_plan_confirmation"

    def test_awaiting_step_confirmation_allowed(self):
        state = _make_state("running", pending={"origin_status": "awaiting_step_confirmation"})
        assert resolve_origin_status(state) == "awaiting_step_confirmation"

    def test_missing_key_denied(self):
        state = _make_state("running", pending={})
        assert resolve_origin_status(state) is None

    def test_none_denied(self):
        state = _make_state("running", pending={"origin_status": None})
        assert resolve_origin_status(state) is None

    def test_empty_string_denied(self):
        state = _make_state("running", pending={"origin_status": ""})
        assert resolve_origin_status(state) is None

    def test_unknown_status_denied(self):
        state = _make_state("running", pending={"origin_status": "unknown_status"})
        assert resolve_origin_status(state) is None

    def test_done_denied(self):
        state = _make_state("running", pending={"origin_status": "done"})
        assert resolve_origin_status(state) is None

    def test_failed_denied(self):
        state = _make_state("running", pending={"origin_status": "failed"})
        assert resolve_origin_status(state) is None

    def test_cancelled_denied(self):
        state = _make_state("running", pending={"origin_status": "cancelled"})
        assert resolve_origin_status(state) is None

    def test_awaiting_resume_choice_denied(self):
        state = _make_state("running", pending={"origin_status": "awaiting_resume_choice"})
        assert resolve_origin_status(state) is None

    def test_awaiting_interrupt_choice_denied(self):
        state = _make_state("running", pending={"origin_status": "awaiting_interrupt_choice"})
        assert resolve_origin_status(state) is None

    def test_running_denied(self):
        state = _make_state("running", pending={"origin_status": "running"})
        assert resolve_origin_status(state) is None

    def test_idle_denied(self):
        state = _make_state("running", pending={"origin_status": "idle"})
        assert resolve_origin_status(state) is None

    def test_awaiting_tool_confirmation_denied(self):
        state = _make_state("running", pending={"origin_status": "awaiting_tool_confirmation"})
        assert resolve_origin_status(state) is None

    def test_no_pending_attr_denied(self):
        """state.task 没有 pending_user_input_request 属性时返回 None。"""
        state = _make_state("running")
        state.task.pending_user_input_request = None  # type: ignore
        assert resolve_origin_status(state) is None


# ============================================================================
# J. Phase 1B transition rule 功能测试
# ============================================================================


class TestPhase1BFeedbackIntentTransitions:
    """Phase 1B: feedback_intent request / cancel / as_feedback transition。"""

    def test_feedback_intent_request_from_plan_confirmation(self):
        state = _make_state("awaiting_plan_confirmation")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.FEEDBACK_INTENT_REQUIRED,
            owner="confirmation.dispatcher.feedback_intent_request",
            expected_from_status="awaiting_plan_confirmation",
        ))
        assert result.allowed is True
        assert result.next_status == "awaiting_feedback_intent"
        assert result.checkpoint_action == CheckpointAction.SAVE
        assert state.task.status == "awaiting_feedback_intent"

    def test_feedback_intent_request_from_step_confirmation(self):
        state = _make_state("awaiting_step_confirmation")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.FEEDBACK_INTENT_REQUIRED,
            owner="confirmation.dispatcher.feedback_intent_request",
            expected_from_status="awaiting_step_confirmation",
        ))
        assert result.allowed is True
        assert result.next_status == "awaiting_feedback_intent"
        assert result.checkpoint_action == CheckpointAction.SAVE
        assert state.task.status == "awaiting_feedback_intent"

    def test_feedback_intent_request_wrong_from_status_denied(self):
        state = _make_state("running")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.FEEDBACK_INTENT_REQUIRED,
            owner="test",
            expected_from_status="awaiting_plan_confirmation",
        ))
        assert result.allowed is False
        assert state.task.status == "running"


class TestPhase1BFeedbackIntentCancel:
    """Phase 1B: cancel path — origin_status sentinel restore。"""

    def test_cancel_restores_plan_confirmation_origin(self):
        state = _make_state(
            "awaiting_feedback_intent",
            pending={"origin_status": "awaiting_plan_confirmation"},
        )
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_CANCELLED,
            owner="confirmation.plan.feedback_intent_cancel",
            expected_from_status="awaiting_feedback_intent",
        ))
        assert result.allowed is True
        assert result.next_status == "awaiting_plan_confirmation"
        assert result.checkpoint_action == CheckpointAction.SAVE
        assert state.task.status == "awaiting_plan_confirmation"

    def test_cancel_restores_step_confirmation_origin(self):
        state = _make_state(
            "awaiting_feedback_intent",
            pending={"origin_status": "awaiting_step_confirmation"},
        )
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_CANCELLED,
            owner="confirmation.plan.feedback_intent_cancel",
            expected_from_status="awaiting_feedback_intent",
        ))
        assert result.allowed is True
        assert result.next_status == "awaiting_step_confirmation"
        assert state.task.status == "awaiting_step_confirmation"

    def test_cancel_invalid_origin_denied(self):
        state = _make_state(
            "awaiting_feedback_intent",
            pending={"origin_status": "unknown"},
        )
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_CANCELLED,
            owner="confirmation.plan.feedback_intent_cancel",
            expected_from_status="awaiting_feedback_intent",
        ))
        assert result.allowed is False
        assert "origin_status sentinel resolution failed" in result.reason.lower()
        assert result.checkpoint_action == CheckpointAction.NONE
        assert state.task.status == "awaiting_feedback_intent"

    def test_cancel_missing_origin_denied(self):
        state = _make_state("awaiting_feedback_intent")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_CANCELLED,
            owner="confirmation.plan.feedback_intent_cancel",
            expected_from_status="awaiting_feedback_intent",
        ))
        assert result.allowed is False
        assert "origin_status sentinel resolution failed" in result.reason.lower()

    def test_cancel_wrong_from_status_denied(self):
        state = _make_state("running")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.USER_CANCELLED,
            owner="test",
            expected_from_status="awaiting_feedback_intent",
        ))
        assert result.allowed is False
        assert "mismatch" in result.reason.lower()


class TestPhase1BFeedbackIntentAsFeedback:
    """Phase 1B: as_feedback path — restore + plan_generated。"""

    def test_as_feedback_restore_plan_confirmation_origin(self):
        state = _make_state(
            "awaiting_feedback_intent",
            pending={"origin_status": "awaiting_plan_confirmation"},
        )
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.FEEDBACK_INTENT_AS_FEEDBACK,
            owner="confirmation.plan.feedback_intent_as_feedback_restore",
            expected_from_status="awaiting_feedback_intent",
        ))
        assert result.allowed is True
        assert result.next_status == "awaiting_plan_confirmation"
        assert result.checkpoint_action == CheckpointAction.SAVE
        assert state.task.status == "awaiting_plan_confirmation"

    def test_as_feedback_restore_step_confirmation_origin(self):
        state = _make_state(
            "awaiting_feedback_intent",
            pending={"origin_status": "awaiting_step_confirmation"},
        )
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.FEEDBACK_INTENT_AS_FEEDBACK,
            owner="confirmation.plan.feedback_intent_as_feedback_restore",
            expected_from_status="awaiting_feedback_intent",
        ))
        assert result.allowed is True
        assert result.next_status == "awaiting_step_confirmation"
        assert state.task.status == "awaiting_step_confirmation"

    def test_as_feedback_invalid_origin_denied(self):
        state = _make_state(
            "awaiting_feedback_intent",
            pending={"origin_status": "done"},
        )
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.FEEDBACK_INTENT_AS_FEEDBACK,
            owner="confirmation.plan.feedback_intent_as_feedback_restore",
            expected_from_status="awaiting_feedback_intent",
        ))
        assert result.allowed is False
        assert state.task.status == "awaiting_feedback_intent"


class TestPhase1BPlanGenerated:
    """Phase 1B: PLAN_GENERATED transition — 覆盖两种 origin。"""

    def test_plan_generated_from_plan_confirmation(self):
        state = _make_state("awaiting_plan_confirmation")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.PLAN_GENERATED,
            owner="confirmation.plan.feedback_intent_as_feedback_enter",
            expected_from_status=None,
        ))
        assert result.allowed is True
        assert result.next_status == "awaiting_plan_confirmation"
        assert result.checkpoint_action == CheckpointAction.SAVE
        assert state.task.status == "awaiting_plan_confirmation"

    def test_plan_generated_from_step_confirmation(self):
        state = _make_state("awaiting_step_confirmation")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.PLAN_GENERATED,
            owner="confirmation.plan.feedback_intent_as_feedback_enter",
            expected_from_status=None,
        ))
        assert result.allowed is True
        assert result.next_status == "awaiting_plan_confirmation"
        assert result.checkpoint_action == CheckpointAction.SAVE
        assert state.task.status == "awaiting_plan_confirmation"

    def test_plan_generated_from_running_denied(self):
        state = _make_state("running")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.PLAN_GENERATED,
            owner="test",
            expected_from_status=None,
        ))
        assert result.allowed is False

    def test_plan_generated_denied_no_state_mutation(self):
        state = _make_state("running")
        result = apply_task_transition(state, TaskTransitionRequest(
            event=TransitionEvent.PLAN_GENERATED,
            owner="test",
            expected_from_status=None,
        ))
        assert result.allowed is False
        assert result.checkpoint_action == CheckpointAction.NONE
        assert state.task.status == "running"


class TestPhase1BAllowlist:
    """Phase 1B: _ORIGIN_STATUS_ALLOWLIST 常量测试。"""

    def test_allowlist_contains_expected_values(self):
        expected = {"awaiting_plan_confirmation", "awaiting_step_confirmation"}
        assert expected == _ORIGIN_STATUS_ALLOWLIST

    def test_allowlist_is_frozenset(self):
        assert isinstance(_ORIGIN_STATUS_ALLOWLIST, frozenset)
