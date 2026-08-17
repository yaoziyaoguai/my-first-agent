"""U4 Goal safe-boundary controls 的行为合同。"""

from __future__ import annotations

from dataclasses import replace

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRun,
    ApprovalPolicy,
    BlockedClaim,
    CancelGoal,
    ContinuationPhase,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    GoalDelta,
    GoalDeltaProposal,
    GoalProgress,
    GoalStatus,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    OutputPolicy,
    PauseGoal,
    ResumeGoal,
    RunStatus,
    SideEffectClass,
    SubmitMessage,
    ToolCall,
    ToolDefinition,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.control import (
    ControlBinding,
    ControlInbox,
    ControlInboxRequest,
    ControlRequestKind,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
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
                execution_authority=ExecutionAuthorityClass.IN_PROCESS,
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


def test_noop_goal_delta_replans_without_requesting_user_authority() -> None:
    state = conversation_with_active_goal()
    assert state.goal is not None
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=GoalDeltaProposal(
                correlation_id="delta-noop",
                delta=GoalDelta(
                    goal_id=state.goal.goal_id,
                    expected_revision=state.goal.revision,
                    reason="the Goal already matches",
                    updates={"targets": list(state.goal.targets)},
                ),
            ),
        ),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="blocked-after-noop-delta",
                goal_id=state.goal.goal_id,
                goal_revision=state.goal.revision,
                blocker="required fixture source is unavailable",
                safe_attempts=("kept the trusted Goal unchanged",),
                resume_condition="provide the fixture source",
            ),
        ),
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
        run_id="run-delta-noop",
        message="continue the existing goal",
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    assert store.state.goal is not None
    assert store.state.goal.revision == state.goal.revision
    assert store.state.goal.status is GoalStatus.BLOCKED
    assert any(
        fact.content.get("code") == "no_progress_replan_required"
        for fact in store.state.facts
    )
    assert all(
        receipt.control_kind != "goal_delta_proposal"
        for receipt in store.state.control_receipts
    )


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


# F3(fresh review 78c54a88):PAUSED Goal 的安全合同。暂停后普通问答仍然可用;
# 任何任务推进(goal 控制)或 effectful tool 都必须先显式 ResumeGoal;
# prose 只结束本次 run,不得改变仍然暂停的 Goal。


def _paused_state():
    state = conversation_with_active_goal()
    assert state.goal is not None
    return replace(state, goal=replace(state.goal, status=GoalStatus.PAUSED))


def _submit_text(state, message: str = "What is this workspace for?") -> SubmitMessage:
    return SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-paused-qa",
        message=message,
    )


def _paused_runtime(state, *responses, registrations=()):
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(*responses)
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=4_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(registrations),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-paused",
    )
    return runtime, store, provider


def test_paused_goal_still_answers_plain_questions_without_goal_mutation() -> None:
    state = _paused_state()
    runtime, store, provider = _paused_runtime(
        state,
        ModelResponse((ModelTextBlock("paused answer"),)),
        ModelResponse((ModelTextBlock("paused answer"),)),
    )

    result = runtime.run_turn(_submit_text(state), store.load())

    assert result.status is RunStatus.COMPLETED
    assert result.message == "paused answer"
    # 一次提问恰好一次模型调用:没有 active_goal_requires_control 修复循环。
    assert len(provider.calls) == 1
    assert store.state.goal is not None
    assert store.state.goal.status is GoalStatus.PAUSED
    assert store.state.goal.revision == state.goal.revision


def test_paused_goal_rejects_model_progress_until_explicit_resume() -> None:
    state = _paused_state()
    runtime, store, provider = _paused_runtime(
        state,
        ModelResponse(
            (),
            control=GoalProgress(
                correlation_id="ctl-paused-progress",
                goal_id=state.goal.goal_id,
                goal_revision=state.goal.revision,
                summary="silently resuming the task",
                next_step="keep going",
            ),
        ),
        ModelResponse((ModelTextBlock("understood, the task stays paused"),)),
    )

    result = runtime.run_turn(_submit_text(state), store.load())

    assert result.status is RunStatus.COMPLETED
    assert store.state.goal is not None
    assert store.state.goal.status is GoalStatus.PAUSED
    assert store.state.goal.next_step != "keep going"
    assert all(
        receipt.correlation_id != "ctl-paused-progress"
        for receipt in store.state.control_receipts
    )


def test_paused_goal_fails_closed_before_effectful_tool_prepare() -> None:
    executed: list[str] = []
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="write_fixture",
        version="1",
        description="Write a fixture",
        input_schema={
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={},
        output_limit_chars=50,
    )
    state = _paused_state()
    runtime, store, provider = _paused_runtime(
        state,
        ModelResponse((ModelToolCall("call-paused-1", "write_fixture", {"content": "x"}),)),
        registrations=(
            RegisteredTool(spec, lambda intent: executed.append("ran") or "written"),
        ),
    )

    result = runtime.run_turn(_submit_text(state, "please continue the task"), store.load())

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "effectful_tool_requires_resumed_goal"
    assert executed == []
    assert store.state.goal is not None
    assert store.state.goal.status is GoalStatus.PAUSED


def test_paused_goal_context_hides_effectful_tools_and_control_schema() -> None:
    state = _paused_state()
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=8_000, output_reserve=500),
    )
    read_definition = ToolDefinition(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="read_file",
        description="Read one bounded file",
        input_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    write_definition = ToolDefinition(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="write_file",
        description="Write one bounded file",
        input_schema={"type": "object"},
        side_effect=SideEffectClass.WRITE,
    )

    pack = manager.build(state, _submit_text(state), (read_definition, write_definition))

    # 模型可见能力层:暂停时 effectful callable 与 goal 控制 schema 都不可见,
    # strict adapter 因而不会强制 tool_choice,普通问答可以 prose 收尾。
    assert tuple(tool.name for tool in pack.tools) == ("read_file",)
    assert pack.control_schema is None
