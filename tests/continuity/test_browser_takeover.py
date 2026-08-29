"""018 Task 5 Step 2：takeover 状态机 Reds（先 Red）。

pending 状态在任何 user-facing 暴露之前持久化；期间 state 无 provider/tool
活动、context 只 advertise complete/cancel；complete 校验 exact request/
session/profile、递增 expected revision、清 pending、要求 fresh observe、
不铸 commit approval；cancel 清 pending。
"""

import pytest

from agent.runtime.contracts import BrowserTakeoverRequestV1
from agent.runtime.state import (
    begin_browser_takeover,
    cancel_browser_takeover,
    complete_browser_takeover,
)
from tests.kernel.fakes import conversation_with_active_goal

REQUEST = BrowserTakeoverRequestV1(
    request_id="takeover-1",
    session_ref="session-0123456789abcdef",
    profile_ref="profile-0123456789abcdef",
    profile_revision=3,
    browser_identity_digest="a" * 64,
    goal_id="goal-1",
    goal_revision=1,
    requested_at="2026-08-28T10:00:00+00:00",
)


def test_takeover_pending_persisted_in_state():
    state = conversation_with_active_goal()
    updated = begin_browser_takeover(state, REQUEST)
    assert updated.browser_takeover_pending == REQUEST
    # 持久化本身推进 revision（CAS 语义），不动 facts/active_run。
    assert updated.revision == state.revision + 1
    assert updated.facts == state.facts
    assert updated.active_run == state.active_run


def test_second_takeover_fails_closed():
    state = conversation_with_active_goal()
    updated = begin_browser_takeover(state, REQUEST)
    with pytest.raises(ValueError):
        begin_browser_takeover(updated, REQUEST)


def test_takeover_request_must_bind_current_goal():
    from dataclasses import replace

    state = conversation_with_active_goal()
    with pytest.raises(ValueError, match="goal identity"):
        begin_browser_takeover(state, replace(REQUEST, goal_id="goal-other"))
    with pytest.raises(ValueError, match="goal identity"):
        begin_browser_takeover(state, replace(REQUEST, goal_revision=2))


def test_pending_period_has_zero_provider_tool_activity():
    state = conversation_with_active_goal()
    updated = begin_browser_takeover(state, REQUEST)
    # pending 期间不产生任何 run/tool/provider 副作用：无新增 fact、
    # 无 tool_calls、无 active_run 状态迁移。
    assert updated.active_run is state.active_run or (
        updated.active_run == state.active_run
    )
    assert len(updated.facts) == len(state.facts)


def test_context_advertises_only_complete_cancel_controls():
    from agent.runtime.context import advertised_browser_controls

    state = conversation_with_active_goal()
    assert advertised_browser_controls(state) == ()
    pending_state = begin_browser_takeover(state, REQUEST)
    assert advertised_browser_controls(pending_state) == ("/browser-done", "/cancel")


def test_complete_validates_exact_identity():
    state = conversation_with_active_goal()
    updated = begin_browser_takeover(state, REQUEST)
    with pytest.raises(ValueError):
        complete_browser_takeover(
            updated,
            request_id="takeover-other",
            session_ref=REQUEST.session_ref,
            expected_profile_revision=REQUEST.profile_revision,
        )
    with pytest.raises(ValueError):
        complete_browser_takeover(
            updated,
            request_id=REQUEST.request_id,
            session_ref="session-ffffffffffffffff",
            expected_profile_revision=REQUEST.profile_revision,
        )
    with pytest.raises(ValueError):
        complete_browser_takeover(
            updated,
            request_id=REQUEST.request_id,
            session_ref=REQUEST.session_ref,
            expected_profile_revision=99,
        )


def test_complete_clears_pending_and_requires_fresh_observe():
    state = conversation_with_active_goal()
    from dataclasses import replace

    lease_state = replace(state, browser_leases=())
    updated = begin_browser_takeover(lease_state, REQUEST)
    completed, outcome = complete_browser_takeover(
        updated,
        request_id=REQUEST.request_id,
        session_ref=REQUEST.session_ref,
        expected_profile_revision=REQUEST.profile_revision,
    )
    assert completed.browser_takeover_pending is None
    # profile revision 期望递增；fresh observe 强制；不铸 commit approval。
    assert outcome.expected_profile_revision == REQUEST.profile_revision + 1
    assert outcome.requires_observe is True
    assert completed.browser_leases == lease_state.browser_leases


def test_cancel_clears_pending():
    state = conversation_with_active_goal()
    updated = begin_browser_takeover(state, REQUEST)
    cancelled = cancel_browser_takeover(updated, request_id=REQUEST.request_id)
    assert cancelled.browser_takeover_pending is None


# --------------------------------------------------------------------------- #
# Task 5 二轮审计：typed actions 进 run_turn、ToolResult takeover 持久化、
# pending 零 provider/tool、ContextManager 实际投影
# --------------------------------------------------------------------------- #


def _takeover_runtime(state=None, *, responses=(), browser_takeover_complete=None):
    from agent.runtime.context import ContextLimits, KernelContextManager
    from agent.runtime.loop import AgentRuntime, InvocationLimits
    from tests.kernel.fakes import (
        CollectingSink,
        InMemoryCheckpointStore,
        ScriptedProvider,
    )

    provider = ScriptedProvider(*responses)
    store = InMemoryCheckpointStore(state or conversation_with_active_goal())
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="Be concise.",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=None,
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
        browser_takeover_complete=(
            browser_takeover_complete
            or (lambda request: request.profile_revision + 1)
        ),
    )
    return runtime, provider, store


def _complete_action(state, request):
    from agent.runtime.contracts import CompleteBrowserTakeover

    return CompleteBrowserTakeover(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_id=request.request_id,
        session_ref=request.session_ref,
        expected_profile_revision=request.profile_revision,
    )


def _cancel_action(state, request):
    from agent.runtime.contracts import CancelBrowserTakeover

    return CancelBrowserTakeover(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_id=request.request_id,
    )


def test_typed_actions_are_part_of_action_union():

    from agent.runtime.contracts import (
        CancelBrowserTakeover,
        CompleteBrowserTakeover,
        canonical_action_digest,
    )

    assert canonical_action_digest(
        CompleteBrowserTakeover(
            conversation_id="c",
            action_seq=1,
            expected_revision=0,
            request_id="t-1",
            session_ref="s",
            expected_profile_revision=1,
        )
    )
    assert canonical_action_digest(
        CancelBrowserTakeover(
            conversation_id="c", action_seq=1, expected_revision=0, request_id="t-1",
        )
    )


def test_run_turn_completes_pending_takeover():
    from agent.runtime.contracts import RunStatus

    state = begin_browser_takeover(conversation_with_active_goal(), REQUEST)
    runtime, _provider, _store = _takeover_runtime(state)
    result = runtime.run_turn(_complete_action(state, REQUEST), _store.load())
    assert result.status is RunStatus.COMPLETED
    assert result.state.browser_takeover_pending is None


def test_run_turn_cancels_pending_takeover():
    from agent.runtime.contracts import RunStatus

    state = begin_browser_takeover(conversation_with_active_goal(), REQUEST)
    runtime, _provider, _store = _takeover_runtime(state)
    result = runtime.run_turn(_cancel_action(state, REQUEST), _store.load())
    assert result.status is RunStatus.COMPLETED
    assert result.state.browser_takeover_pending is None


def test_unknown_effect_blocks_takeover_completion_before_browser_adapter_call():
    from dataclasses import replace

    from agent.runtime.contracts import (
        ActiveRun,
        ContinuationPhase,
        ExecutingIntentRecord,
        ExecutionAuthorityClass,
        RunStatus,
        ToolCall,
    )

    pending = begin_browser_takeover(conversation_with_active_goal(), REQUEST)
    state = replace(
        pending,
        active_run=ActiveRun(
            run_id="run-takeover",
            phase=ContinuationPhase.EXECUTING,
            executing_intent=ExecutingIntentRecord(
                tool_call_id="call-takeover",
                intent_digest="intent-takeover",
                idempotency_key="idempotency-takeover",
                execution_authority=ExecutionAuthorityClass.IN_PROCESS,
                operation="browser_begin_takeover",
            ),
            tool_calls=(ToolCall("call-takeover", "browser_begin_takeover", {}),),
        ),
    )
    completion_calls = 0

    def complete_browser(_request):  # noqa: ANN001, ANN202
        nonlocal completion_calls
        completion_calls += 1
        return REQUEST.profile_revision + 1

    runtime, _provider, store = _takeover_runtime(
        state,
        browser_takeover_complete=complete_browser,
    )

    result = runtime.run_turn(_complete_action(state, REQUEST), store.load())

    assert result.status is RunStatus.CONFLICT
    assert result.error_code == "unknown_effect_recovery_required"
    assert result.state == state
    assert completion_calls == 0


def test_pending_period_zero_provider_and_tool_calls():
    from agent.runtime.contracts import SubmitMessage

    state = begin_browser_takeover(conversation_with_active_goal(), REQUEST)
    runtime, provider, store = _takeover_runtime(state)
    snapshot = store.load()
    submit = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-x",
        message="continue",
    )
    result = runtime.run_turn(submit, snapshot)
    assert result.state.browser_takeover_pending == REQUEST
    assert provider.calls == []


def test_context_manager_projects_only_complete_cancel():
    from agent.runtime.context import ContextLimits, KernelContextManager
    from agent.runtime.contracts import SubmitMessage

    manager = KernelContextManager(
        system_policy="Be concise.",
        limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
    )
    state = begin_browser_takeover(conversation_with_active_goal(), REQUEST)
    action = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=1,
        expected_revision=0,
        run_id="run-1",
        message="hi",
    )
    pack = manager.build(state, action, tools=())
    system_text = pack.system
    assert "/browser-done" in system_text and "/cancel" in system_text
    idle_pack = manager.build(conversation_with_active_goal(), action, tools=())
    assert "/browser-done" not in idle_pack.system
