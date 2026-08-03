"""U4 Goal safe-boundary controls 的行为合同。"""

from __future__ import annotations

from dataclasses import replace

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRun,
    BlockedClaim,
    CancelGoal,
    ContinuationPhase,
    ExecutingIntentRecord,
    GoalDelta,
    GoalDeltaProposal,
    GoalProgress,
    GoalStatus,
    ModelResponse,
    ModelTextBlock,
    PauseGoal,
    ResumeGoal,
    RunStatus,
    SubmitMessage,
    ToolCall,
)
from agent.runtime.control import (
    ControlBinding,
    ControlInbox,
    ControlInboxRequest,
    ControlRequestKind,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    conversation_with_active_goal,
)


def _runtime(state):
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("must not be called"),)))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-control",
    )
    return runtime, store, provider


def _pause(state, *, revision: int | None = None) -> PauseGoal:
    assert state.goal is not None
    return PauseGoal(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        goal_id=state.goal.goal_id,
        goal_revision=state.goal.revision if revision is None else revision,
    )


def test_pause_request_becomes_durable_only_at_safe_boundary() -> None:
    runtime, store, provider = _runtime(conversation_with_active_goal())

    result = runtime.run_turn(_pause(store.state), store.load())

    assert result.status is RunStatus.COMPLETED
    assert store.state.goal is not None
    assert store.state.goal.status is GoalStatus.PAUSED
    assert provider.calls == []


def test_resume_goal_uses_exact_goal_and_revision() -> None:
    state = conversation_with_active_goal()
    assert state.goal is not None
    state = replace(state, goal=replace(state.goal, status=GoalStatus.PAUSED))
    runtime, store, provider = _runtime(state)
    action = ResumeGoal(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        goal_id=state.goal.goal_id,
        goal_revision=state.goal.revision,
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    assert store.state.goal is not None
    assert store.state.goal.status is GoalStatus.GOAL_READY
    assert provider.calls == []


def test_stale_control_action_has_zero_provider_and_tool_calls() -> None:
    runtime, store, provider = _runtime(conversation_with_active_goal())
    initial = store.state

    result = runtime.run_turn(_pause(store.state, revision=99), store.load())

    assert result.status is RunStatus.CONFLICT
    assert result.error_code == "goal_revision_mismatch"
    assert store.state == initial
    assert provider.calls == []


def test_cancel_during_executing_cannot_bypass_unknown_effect_recovery() -> None:
    state = conversation_with_active_goal()
    state = replace(
        state,
        active_run=ActiveRun(
            run_id="run-executing",
            phase=ContinuationPhase.EXECUTING,
            owner_invocation_id="dead-invocation",
            executing_intent=ExecutingIntentRecord(
                tool_call_id="call-1",
                intent_digest="intent-digest",
                idempotency_key="idempotency-1",
            ),
            tool_calls=(ToolCall("call-1", "write_file", {"path": "notes/a.md"}),),
        ),
    )
    runtime, store, provider = _runtime(state)
    assert state.goal is not None
    action = CancelGoal(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        goal_id=state.goal.goal_id,
        goal_revision=state.goal.revision,
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.CONFLICT
    assert result.error_code == "unknown_effect_recovery_required"
    assert store.state == state
    assert provider.calls == []


def test_control_inbox_is_non_mutating_and_binds_invocation_goal_revision() -> None:
    state = conversation_with_active_goal()
    inbox = ControlInbox()
    binding = ControlBinding(
        conversation_id=state.conversation_id,
        goal_id=state.goal.goal_id,
        goal_revision=state.goal.revision,
        invocation_id="invocation-1",
    )
    inbox.open(binding)
    request = ControlInboxRequest(
        request_id="control-1",
        kind=ControlRequestKind.PAUSE,
        conversation_id=binding.conversation_id,
        goal_id=binding.goal_id,
        goal_revision=binding.goal_revision,
        invocation_id=binding.invocation_id,
    )

    inbox.submit(request)

    assert state == conversation_with_active_goal()
    assert inbox.poll(binding) == request
    with __import__("pytest").raises(ValueError, match="active invocation"):
        inbox.submit(replace(request, request_id="stale", goal_revision=2))


class _RequestingProvider:
    def __init__(self, inbox: ControlInbox, kind: ControlRequestKind) -> None:
        self.inbox = inbox
        self.kind = kind
        self.calls = []

    def generate(self, context):  # noqa: ANN001
        self.calls.append(context)
        binding = self.inbox.current("conversation-1")
        assert binding is not None
        self.inbox.submit(
            ControlInboxRequest(
                request_id=f"request-{self.kind.value}",
                kind=self.kind,
                conversation_id=binding.conversation_id,
                goal_id=binding.goal_id,
                goal_revision=binding.goal_revision,
                invocation_id=binding.invocation_id,
                message="change the target to reports/brief.md"
                if self.kind is ControlRequestKind.CORRECT
                else None,
            )
        )
        return ModelResponse(
            (),
            control=GoalProgress(
                correlation_id=f"progress-{self.kind.value}",
                goal_id=binding.goal_id,
                goal_revision=binding.goal_revision,
                summary="working",
                next_step="continue",
            ),
        )


def test_active_pause_correction_and_cancel_apply_only_at_safe_poll_points() -> None:
    for kind, expected_status in (
        (ControlRequestKind.PAUSE, GoalStatus.PAUSED),
        (ControlRequestKind.CORRECT, GoalStatus.NEEDS_AUTHORITY),
        (ControlRequestKind.CANCEL, GoalStatus.CANCELLED),
    ):
        state = conversation_with_active_goal()
        inbox = ControlInbox()
        store = InMemoryCheckpointStore(state)
        provider = _RequestingProvider(inbox, kind)
        runtime = AgentRuntime(
            provider=provider,
            context_manager=KernelContextManager(
                system_policy="policy",
                limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
            ),
            tool_runtime=KernelToolRuntime(()),
            checkpoint_store=store,
            event_sink=CollectingSink(),
            limits=InvocationLimits(),
            invocation_id_factory=lambda kind=kind: f"invocation-{kind.value}",
            control_inbox=inbox,
        )
        action = SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id=f"run-{kind.value}",
            message="continue",
        )

        runtime.run_turn(action, store.load())

        assert len(provider.calls) == 1
        assert store.state.goal is not None
        assert store.state.goal.status is expected_status
        assert store.state.active_run is None
        if kind is ControlRequestKind.CORRECT:
            assert store.state.goal.revision == 2
            assert store.state.completion_claim is None
            assert store.state.facts[-1].content["text"] == "change the target to reports/brief.md"


def test_goal_delta_control_invalidates_stale_work_and_stops_before_effect() -> None:
    state = conversation_with_active_goal()
    assert state.goal is not None
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=GoalDeltaProposal(
                correlation_id="delta-1",
                delta=GoalDelta(
                    goal_id=state.goal.goal_id,
                    expected_revision=state.goal.revision,
                    reason="user changed the target",
                    updates={"targets": ["reports/brief.md"]},
                ),
            ),
        )
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
    )
    action = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-delta",
        message="change the target to reports/brief.md",
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    assert store.state.goal is not None
    assert store.state.goal.revision == 2
    assert store.state.goal.targets == ("reports/brief.md",)
    assert store.state.goal.status is GoalStatus.NEEDS_AUTHORITY
    assert store.state.goal.next_step is None
    assert store.state.completion_claim is None
    assert store.state.evidence_records == ()
    assert len(provider.calls) == 1


def test_blocked_claim_projects_exact_resume_condition_and_stops() -> None:
    state = conversation_with_active_goal()
    assert state.goal is not None
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="blocked-1",
                goal_id=state.goal.goal_id,
                goal_revision=state.goal.revision,
                blocker="required configuration is absent",
                safe_attempts=("checked the explicit configuration contract",),
                resume_condition="provide the named configuration value",
            ),
        )
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
    )
    action = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-blocked",
        message="continue",
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    assert store.state.goal is not None
    assert store.state.goal.status is GoalStatus.BLOCKED
    assert store.state.goal.next_step == "provide the named configuration value"
    assert store.state.active_run is None
    assert store.state.facts[-1].content["code"] == "blocked_claim"
