"""U4 Goal safe-boundary controls 的行为合同。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from agent.provider.normalize import context_to_openai_messages
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.context_control import goal_correction_pending
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    AdmittedCriterion,
    ApprovalPolicy,
    ApprovalRequest,
    BlockedClaim,
    CancelGoal,
    ClarificationRequest,
    ContinuationPhase,
    ConversationFact,
    EvidenceOracleKind,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    FactKind,
    GoalDelta,
    GoalDeltaProposal,
    GoalProgress,
    GoalStatus,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    OutputPolicy,
    PauseGoal,
    ProposedCriterion,
    ResolveApproval,
    ResumeGoal,
    RunStatus,
    SideEffectClass,
    SubmitMessage,
    ToolCall,
    ToolDefinition,
    ToolPrepareContext,
    ToolResult,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.control import (
    ControlBinding,
    ControlInbox,
    ControlInboxRequest,
    ControlRequestKind,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits, RetryableProviderError
from agent.runtime.state import accept_action, accept_goal_delta_proposal
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


def test_repeated_noop_delta_after_consumed_correction_repairs_instead_of_fatal() -> None:
    # 首个 delta 消费 correction 后，goal_delta_proposal 已从 advertised schema
    # 消失。即使 scripted provider 绕过 wire schema 重发，Runtime 也只把它作为
    # 未授权 control 有界修复，不能再次进入 GoalDelta reducer 或变成 fatal。
    state = conversation_with_active_goal()
    assert state.goal is not None
    goal = state.goal
    store = InMemoryCheckpointStore(state)

    def _delta(expected_revision: int, correlation_id: str) -> GoalDeltaProposal:
        return GoalDeltaProposal(
            correlation_id=correlation_id,
            delta=GoalDelta(
                goal_id=goal.goal_id,
                expected_revision=expected_revision,
                reason="user changed the target",
                updates={"targets": ["reports/brief.md"]},
            ),
        )

    provider = ScriptedProvider(
        ModelResponse((), control=_delta(goal.revision, "delta-first")),
        ModelResponse(
            (),
            control=_delta(goal.revision + 1, "delta-repeat"),
        ),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="blocked-after-delta",
                goal_id=goal.goal_id,
                goal_revision=goal.revision + 1,
                blocker="fixture tool is intentionally absent",
                safe_attempts=("accepted the user's correction",),
                resume_condition="provide the fixture tool",
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
        run_id="run-delta-repeat",
        message="change the target to reports/brief.md",
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    assert result.error_code != "runtime_failure"
    assert any(
        getattr(fact.kind, "value", None) == "policy_result"
        and "Control kind goal_delta_proposal is not currently available"
        in str(fact.content.get("text", ""))
        for fact in store.state.facts
    )
    assert sum(
        receipt.control_kind == "goal_delta_proposal"
        for receipt in store.state.control_receipts
    ) == 1
    assert store.state.goal is not None
    assert store.state.goal.revision == 2
    assert store.state.goal.targets == ("reports/brief.md",)
    assert store.state.goal.status is GoalStatus.BLOCKED


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
        ),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="blocked-after-delta",
                goal_id=state.goal.goal_id,
                goal_revision=state.goal.revision + 1,
                blocker="fixture tool is intentionally absent",
                safe_attempts=("accepted the user's correction",),
                resume_condition="provide the fixture tool",
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
        run_id="run-delta",
        message="change the target to reports/brief.md",
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    assert store.state.goal is not None
    assert store.state.goal.revision == 2
    assert store.state.goal.targets == ("reports/brief.md",)
    assert store.state.goal.status is GoalStatus.BLOCKED
    correction_fact = next(
        fact
        for fact in store.state.facts
        if fact.content.get("control") == "goal_correction"
    )
    assert store.state.goal.created_from_fact_ids[-1] == correction_fact.fact_id
    assert store.state.goal.next_step == "provide the fixture tool"
    assert store.state.completion_claim is None
    assert store.state.evidence_records == ()
    assert len(provider.calls) == 2


def test_consumed_correction_error_distinguishes_already_corrected_goal() -> None:
    # 016 真实 E3 J11:模型在 delta 已成功受理后重发 delta,错误若仍报
    # "requires one unconsumed user correction",修复消息会误导模型继续重发,
    # 而不是基于已修正的 Goal 继续工作。已消费与从未存在必须可区分。
    state = conversation_with_active_goal()
    assert state.goal is not None
    correction = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-consumed-correction",
        message="write final.md instead",
    )
    corrected = accept_action(state, correction).state
    accepted = accept_goal_delta_proposal(
        corrected,
        GoalDeltaProposal(
            correlation_id="delta-first",
            delta=GoalDelta(
                goal_id=state.goal.goal_id,
                expected_revision=state.goal.revision,
                reason="user changed the target",
                updates={"targets": ["final.md"]},
            ),
        ),
    )
    assert accepted.goal is not None

    with pytest.raises(ValueError) as raised:
        accept_goal_delta_proposal(
            accepted,
            GoalDeltaProposal(
                correlation_id="delta-second",
                delta=GoalDelta(
                    goal_id=accepted.goal.goal_id,
                    expected_revision=accepted.goal.revision,
                    reason="duplicate correction attempt",
                    updates={"scope": ["final.md"]},
                ),
            ),
        )

    message = str(raised.value)
    assert "already been consumed" in message
    assert "unconsumed" not in message


def test_interleaved_success_does_not_exhaust_invalid_repair_budget() -> None:
    # 016 真实 E3 J11:correction 后 malformed control → 成功受理的 delta →
    # 再次 malformed → 澄清收尾。invalid_repairs 必须因真实受理的 control 重置;
    # 跨成功累计会把健康推进中的对话错误地判成 fatal。
    from agent.runtime.ports import InvalidProviderResponseError

    state = conversation_with_active_goal()
    assert state.goal is not None
    goal = state.goal
    pending = ApprovalRequest(
        request_id="approval-interleaved",
        run_id="run-interleaved",
        tool_call_id="write-interleaved",
        binding_digest="binding-interleaved",
        preview="write draft.md",
        tool_name="write_file",
    )
    state = replace(
        state,
        active_run=ActiveRun(
            run_id="run-interleaved",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            pending_request=pending,
            tool_calls=(
                ToolCall(
                    "write-interleaved",
                    "write_file",
                    {"path": "draft.md", "content": "draft"},
                ),
            ),
        ),
    )
    correction = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-interleaved",
        message="write final.md instead",
    )
    provider = ScriptedProvider(
        InvalidProviderResponseError("malformed_control"),
        ModelResponse(
            (),
            control=GoalDeltaProposal(
                correlation_id="delta-interleaved",
                delta=GoalDelta(
                    goal_id=goal.goal_id,
                    expected_revision=goal.revision,
                    reason="user changed the target",
                    updates={"targets": ["final.md"]},
                ),
            ),
        ),
        InvalidProviderResponseError("malformed_control"),
        ModelResponse(
            (),
            control=ClarificationRequest(
                correlation_id="ctl-interleaved-final",
                question="Should the corrected final.md include the sources?",
                boundary_code="direction_boundary",
                missing_fields=("final_scope",),
                safe_assumptions=(),
            ),
        ),
    )
    store = InMemoryCheckpointStore(state)
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_invalid_repairs=1),
        invocation_id_factory=lambda: "invocation-interleaved",
    )

    result = runtime.run_turn(correction, store.load())

    assert result.status is RunStatus.COMPLETED, result.error_code
    assert store.state.goal is not None
    assert store.state.goal.targets == ("final.md",)


def test_goal_delta_requires_one_unconsumed_user_correction() -> None:
    state = conversation_with_active_goal()
    assert state.goal is not None

    with pytest.raises(ValueError, match="unconsumed user correction"):
        accept_goal_delta_proposal(
            state,
            GoalDeltaProposal(
                correlation_id="delta-without-user-authority",
                delta=GoalDelta(
                    goal_id=state.goal.goal_id,
                    expected_revision=state.goal.revision,
                    reason="model tried to change assumptions",
                    updates={"assumptions": ["model supplied"]},
                ),
            ),
        )


def test_non_authority_correction_is_consumed_once() -> None:
    state = conversation_with_active_goal()
    assert state.goal is not None
    correction = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-assumption-correction",
        message="also assume the fixture stays local",
    )
    corrected = accept_action(state, correction).state
    updated = accept_goal_delta_proposal(
        corrected,
        GoalDeltaProposal(
            correlation_id="delta-assumption-correction",
            delta=GoalDelta(
                goal_id=state.goal.goal_id,
                expected_revision=state.goal.revision,
                reason="user added an assumption",
                updates={"assumptions": ["fixture stays local"]},
            ),
        ),
    )

    assert updated.goal is not None
    assert updated.goal.created_from_fact_ids[-1] == corrected.facts[-1].fact_id
    assert updated.goal.status is GoalStatus.GOAL_READY
    with pytest.raises(ValueError, match="already been consumed"):
        accept_goal_delta_proposal(
            updated,
            GoalDeltaProposal(
                correlation_id="delta-reuses-correction",
                delta=GoalDelta(
                    goal_id=updated.goal.goal_id,
                    expected_revision=updated.goal.revision,
                    reason="reuse is forbidden",
                    updates={"assumptions": ["second model change"]},
                ),
            ),
        )


def test_user_correction_at_pending_approval_authorizes_one_goal_delta() -> None:
    state = conversation_with_active_goal()
    assert state.goal is not None
    pending = ApprovalRequest(
        request_id="approval-draft",
        run_id="run-draft",
        tool_call_id="write-draft",
        binding_digest="binding-draft",
        preview="write draft.md",
        tool_name="write_file",
    )
    state = replace(
        state,
        active_run=ActiveRun(
            run_id="run-draft",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            pending_request=pending,
            tool_calls=(
                ToolCall(
                    "write-draft",
                    "write_file",
                    {"path": "draft.md", "content": "draft"},
                ),
            ),
        ),
    )
    correction = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-correction",
        message="write final.md instead",
    )

    corrected = accept_action(state, correction).state
    updated = accept_goal_delta_proposal(
        corrected,
        GoalDeltaProposal(
            correlation_id="delta-from-user-correction",
            delta=GoalDelta(
                goal_id=state.goal.goal_id,
                expected_revision=state.goal.revision,
                reason="user changed the target",
                updates={"targets": ["final.md"]},
            ),
        ),
    )

    assert updated.goal is not None
    assert updated.goal.targets == ("final.md",)
    assert updated.goal.status is GoalStatus.GOAL_READY
    assert updated.goal.created_from_fact_ids[-1] == corrected.facts[-1].fact_id


def test_path_correction_rejects_partial_delta_before_consuming_user_authority() -> None:
    state = conversation_with_active_goal()
    assert state.goal is not None
    state = replace(
        state,
        goal=replace(
            state.goal,
            targets=("draft.md",),
            proposed_criteria=(
                ProposedCriterion(
                    "criterion-draft",
                    "draft.md contains the requested result",
                    oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                    artifact_path="draft.md",
                ),
            ),
            admitted_criteria=(
                AdmittedCriterion(
                    criterion_id="criterion-draft",
                    description="draft.md contains the requested result",
                    source_fact_id=state.goal.created_from_fact_ids[0],
                    oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                    predicate={"path": "draft.md", "sha256": "a" * 64},
                    required_evidence_class="workspace_file",
                    admission_digest="b" * 64,
                ),
            ),
        ),
        active_run=ActiveRun(
            run_id="run-draft",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            pending_request=ApprovalRequest(
                request_id="approval-draft-path",
                run_id="run-draft",
                tool_call_id="write-draft-path",
                binding_digest="binding-draft-path",
                preview="write draft.md",
                tool_name="write_file",
            ),
            tool_calls=(
                ToolCall(
                    "write-draft-path",
                    "write_file",
                    {"path": "draft.md", "content": "draft"},
                ),
            ),
        ),
    )
    correction = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-correction",
        message="write final.md instead",
    )
    corrected = accept_action(state, correction).state

    with pytest.raises(ValueError, match="artifact criteria must match corrected targets"):
        accept_goal_delta_proposal(
            corrected,
            GoalDeltaProposal(
                correlation_id="delta-partial-path",
                delta=GoalDelta(
                    goal_id=state.goal.goal_id,
                    expected_revision=state.goal.revision,
                    reason="user changed the path",
                    updates={"targets": ["final.md"]},
                ),
            ),
        )

    accepted = accept_goal_delta_proposal(
        corrected,
        GoalDeltaProposal(
            correlation_id="delta-complete-path",
            delta=GoalDelta(
                goal_id=state.goal.goal_id,
                expected_revision=state.goal.revision,
                reason="user changed the path",
                updates={
                    "targets": ["final.md"],
                    "proposed_criteria": [
                        {
                            "criterion_id": "criterion-final",
                            "description": "final.md contains the requested result",
                            "oracle_kind": "filesystem_digest",
                            "artifact_path": "final.md",
                        }
                    ],
                },
            ),
        ),
    )

    assert accepted.goal is not None
    assert accepted.goal.targets == ("final.md",)
    assert accepted.goal.proposed_criteria[0].artifact_path == "final.md"
    assert accepted.goal.admitted_criteria == ()


def test_user_correction_closes_every_unfinished_tool_call_on_provider_wire() -> None:
    state = conversation_with_active_goal()
    calls = (
        ToolCall("search-before-correction", "web_search", {"query": "pathlib"}),
        ToolCall(
            "write-before-correction",
            "write_file",
            {"path": "draft.md", "content": "draft"},
        ),
    )
    pending = ApprovalRequest(
        request_id="approval-draft",
        run_id="run-draft",
        tool_call_id="write-before-correction",
        binding_digest="binding-draft",
        preview="write draft.md",
        tool_name="write_file",
    )
    state = replace(
        state,
        facts=(
            *state.facts,
            ConversationFact(
                fact_id="tool-batch-before-correction",
                kind=FactKind.TOOL_CALLS,
                content={
                    "calls": [
                        {
                            "tool_call_id": call.tool_call_id,
                            "name": call.name,
                            "arguments": call.arguments,
                        }
                        for call in calls
                    ]
                },
            ),
            ConversationFact(
                fact_id="search-result-before-correction",
                kind=FactKind.TOOL_RESULT,
                content={
                    "tool_call_id": calls[0].tool_call_id,
                    "text": "search completed",
                    "is_error": False,
                },
            ),
        ),
        active_run=ActiveRun(
            run_id="run-draft",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            batch_cursor=1,
            pending_request=pending,
            tool_calls=calls,
        ),
    )
    correction = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-correction",
        message="write final.md instead",
    )

    corrected = accept_action(state, correction).state
    tool = ToolDefinition(
        name="read_file",
        description="read one file",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
    )
    pack = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=8_000, output_reserve=500),
    ).build(corrected, correction, (tool,))
    wire = context_to_openai_messages(pack)
    assistant_index = next(
        index for index, message in enumerate(wire) if message.get("tool_calls")
    )

    assert [
        message["tool_call_id"] for message in wire[assistant_index + 1 : assistant_index + 3]
    ] == [call.tool_call_id for call in calls]
    assert wire[assistant_index + 2]["content"] == (
        "Tool call was not executed because the user corrected the Goal."
    )
    assert wire[assistant_index + 3]["role"] == "user"
    assert "write final.md instead" in wire[assistant_index + 3]["content"]
    assert pack.tools == ()
    assert pack.control_schema is not None
    assert pack.control_schema["input_schema"]["properties"]["kind"]["enum"] == [
        "goal_delta_proposal"
    ]


def test_pending_goal_correction_rejects_product_tool_before_invoke() -> None:
    invoked: list[str] = []
    runtime = KernelToolRuntime(
        (
            RegisteredTool(
                spec=ToolSpec(
                    execution_authority=ExecutionAuthorityClass.IN_PROCESS,
                    name="read_file",
                    version="1.0.0",
                    description="read one file",
                    input_schema={
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                    risk=ToolRisk.LOW,
                    side_effect=SideEffectClass.READ_ONLY,
                    output_policy=OutputPolicy.BOUNDED_TEXT,
                    approval_policy=ApprovalPolicy.NEVER,
                    safety_policy={},
                    output_limit_chars=1_000,
                ),
                func=lambda _intent: invoked.append("called") or "content",
            ),
        )
    )

    result = runtime.prepare(
        ToolCall("read-before-correction", "read_file", {"path": "final.md"}),
        ToolPrepareContext(
            conversation_id="conversation-correction",
            run_id="run-correction",
            state_revision=1,
            goal_correction_pending=True,
        ),
    )

    assert isinstance(result, ToolResult)
    assert result.metadata["code"] == "goal_correction_required"
    assert invoked == []


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
    assert any(
        receipt.control_kind == "goal_delta_proposal"
        for receipt in store.state.control_receipts
    )
    correction_fact = next(
        fact
        for fact in store.state.facts
        if fact.content.get("control") == "goal_correction"
    )
    assert correction_fact.fact_id in store.state.goal.created_from_fact_ids


def test_noop_goal_delta_cannot_consume_a_new_runtime_obligation() -> None:
    state = conversation_with_active_goal()
    assert state.goal is not None
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=GoalDeltaProposal(
                correlation_id="delta-add-process-lower-bound",
                delta=GoalDelta(
                    goal_id=state.goal.goal_id,
                    expected_revision=state.goal.revision,
                    reason="the existing target stays unchanged",
                    updates={"targets": list(state.goal.targets)},
                ),
            ),
        ),
        RetryableProviderError("stop after observing the corrected Goal"),
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
        run_id="run-add-process-lower-bound",
        message="另外运行 ./check-report。",
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert store.state.goal is not None
    assert store.state.goal.revision == state.goal.revision + 1
    assert any(
        item.criterion_id.startswith("criterion:required-local-process:")
        and item.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
        for item in store.state.goal.proposed_criteria
    )


def test_blocked_claim_projects_exact_resume_condition_and_stops() -> None:
    state = conversation_with_active_goal()
    assert state.goal is not None
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=GoalDeltaProposal(
                correlation_id="continue-noop",
                delta=GoalDelta(
                    goal_id=state.goal.goal_id,
                    expected_revision=state.goal.revision,
                    reason="the user asked to continue the existing Goal",
                    updates={"targets": list(state.goal.targets)},
                ),
            ),
        ),
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


def test_blocked_claim_without_product_attempt_is_rejected_when_tool_is_available() -> None:
    state = conversation_with_active_goal()
    assert state.goal is not None
    calls: list[str] = []
    spec = ToolSpec(
        name="web_search",
        version="1",
        description="search the public Web",
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={},
        output_limit_chars=100,
    )
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=GoalDeltaProposal(
                correlation_id="continue-tool-noop",
                delta=GoalDelta(
                    goal_id=state.goal.goal_id,
                    expected_revision=state.goal.revision,
                    reason="the user asked to continue the existing Goal",
                    updates={"targets": list(state.goal.targets)},
                ),
            ),
        ),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="false-blocked",
                goal_id=state.goal.goal_id,
                goal_revision=state.goal.revision,
                blocker="no product tools are available",
                safe_attempts=(),
                resume_condition="install a product tool",
            ),
        ),
        ModelResponse(
            (ModelToolCall("search-1", "web_search", {"query": "csv format"}),)
        ),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="observed-blocked",
                goal_id=state.goal.goal_id,
                goal_revision=state.goal.revision,
                blocker="the available source did not answer the question",
                safe_attempts=("searched the public Web",),
                resume_condition="provide a different public source",
            ),
        ),
    )
    store = InMemoryCheckpointStore(state)
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=4_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(
            (
                RegisteredTool(
                    spec,
                    lambda intent: calls.append(intent.arguments["query"]) or "searched",
                ),
            )
        ),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
    )
    action = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-blocked-tool-available",
        message="continue",
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    assert calls == ["csv format"]
    assert any(
        fact.content.get("code") == "blocked_claim_not_verified"
        and "web_search" in fact.content.get("text", "")
        for fact in store.state.facts
    )
    assert store.state.goal is not None
    assert store.state.goal.status is GoalStatus.BLOCKED


def test_unrelated_read_does_not_authorize_blocked_with_pending_runtime_web() -> None:
    """无关的 workspace read 不能冒充 Runtime-owned Web 义务的安全尝试。"""

    state = conversation_with_active_goal()
    assert state.goal is not None
    web_requirement = ProposedCriterion(
        criterion_id="criterion:required-public-web:fixture",
        description="the requested public Web source was actually retrieved",
        oracle_kind=EvidenceOracleKind.WEB_SOURCE_RECEIPT,
    )
    process_requirement = ProposedCriterion(
        criterion_id="criterion:required-local-process:fixture",
        description="the requested local validator exits successfully",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
    )
    state = replace(
        state,
        goal=replace(
            state.goal,
            proposed_criteria=(
                *state.goal.proposed_criteria,
                web_requirement,
                process_requirement,
            ),
        ),
    )
    calls: list[str] = []

    def _spec(name: str, properties: dict, required: list[str]) -> ToolSpec:
        return ToolSpec(
            name=name,
            version="1",
            description=name,
            execution_authority=ExecutionAuthorityClass.IN_PROCESS,
            input_schema={
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
            risk=ToolRisk.LOW,
            side_effect=SideEffectClass.READ_ONLY,
            output_policy=OutputPolicy.BOUNDED_TEXT,
            approval_policy=ApprovalPolicy.NEVER,
            safety_policy={},
            output_limit_chars=100,
        )

    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=GoalDeltaProposal(
                correlation_id="continue-runtime-web-noop",
                delta=GoalDelta(
                    goal_id=state.goal.goal_id,
                    expected_revision=state.goal.revision,
                    reason="the user asked to continue the existing Goal",
                    updates={"targets": list(state.goal.targets)},
                ),
            ),
        ),
        ModelResponse((ModelToolCall("list-1", "list_files", {}),)),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="false-blocked-after-read",
                goal_id=state.goal.goal_id,
                goal_revision=state.goal.revision,
                blocker="public research is unavailable",
                safe_attempts=("listed the workspace",),
                resume_condition="provide a public source",
            ),
        ),
        ModelResponse(
            (ModelToolCall("search-1", "web_search", {"query": "csv format"}),)
        ),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="observed-blocked-after-web",
                goal_id=state.goal.goal_id,
                goal_revision=state.goal.revision,
                blocker="the public search returned no useful result",
                safe_attempts=("searched the public Web",),
                resume_condition="provide a different public source",
            ),
        ),
    )
    store = InMemoryCheckpointStore(state)
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=4_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(
            (
                RegisteredTool(
                    _spec("list_files", {}, []),
                    lambda _intent: calls.append("list_files") or "data.csv",
                ),
                RegisteredTool(
                    _spec(
                        "web_search",
                        {"query": {"type": "string"}},
                        ["query"],
                    ),
                    lambda _intent: calls.append("web_search") or "no useful result",
                ),
                RegisteredTool(
                    _spec("local_process", {}, []),
                    lambda _intent: calls.append("local_process") or "unexpected",
                ),
            )
        ),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
    )
    action = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-runtime-web-blocked",
        message="continue",
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    assert calls == ["list_files", "web_search"]
    repair = next(
        fact
        for fact in store.state.facts
        if fact.content.get("code") == "blocked_claim_not_verified"
    )
    assert "web_search" in repair.content.get("text", "")
    assert "local_process" not in repair.content.get("text", "")
    assert store.state.goal is not None
    assert store.state.goal.status is GoalStatus.BLOCKED


def test_rejected_unrelated_process_does_not_authorize_blocked() -> None:
    state = conversation_with_active_goal()
    assert state.goal is not None
    source = replace(
        state.facts[0],
        content={
            "text": (
                "运行这个项目的测试并汇报结果；如果不能运行，"
                "给出基于只读分析的准确说明。"
            )
        },
    )
    process_requirement = ProposedCriterion(
        criterion_id="criterion:required-local-process:exact-validator",
        description="the explicitly requested local validator exits successfully",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
    )
    state = replace(
        state,
        facts=(source,),
        goal=replace(
            state.goal,
            user_outcome="运行 exact check-greet validator",
            proposed_criteria=(*state.goal.proposed_criteria, process_requirement),
        ),
    )
    invoked: list[str] = []
    process_spec = ToolSpec(
        name="local_process",
        version="1",
        description="run one exact local validator",
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        input_schema={
            "type": "object",
            "properties": {"executable": {"type": "string"}},
            "required": ["executable"],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={},
        output_limit_chars=100,
    )
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=GoalDeltaProposal(
                correlation_id="continue-exact-validator",
                delta=GoalDelta(
                    goal_id=state.goal.goal_id,
                    expected_revision=state.goal.revision,
                    reason="the existing Goal already matches",
                    updates={"targets": list(state.goal.targets)},
                ),
            ),
        ),
        ModelResponse(
            (ModelToolCall("wrong-process", "local_process", {"executable": "/bin/ls"}),)
        ),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="blocked-after-wrong-process",
                goal_id=state.goal.goal_id,
                goal_revision=state.goal.revision,
                blocker="the validator was rejected",
                safe_attempts=("requested an unrelated process",),
                resume_condition="allow a validator",
            ),
        ),
        ModelResponse(
            (
                ModelToolCall(
                    "exact-process",
                    "local_process",
                    {"executable": "./check-greet"},
                ),
            )
        ),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="blocked-after-exact-process-refusal",
                goal_id=state.goal.goal_id,
                goal_revision=state.goal.revision,
                blocker="the validator completed successfully",
                safe_attempts=("ran the validator",),
                resume_condition="nothing remains",
            ),
        ),
    )
    store = InMemoryCheckpointStore(state)
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=4_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(
            (
                RegisteredTool(
                    process_spec,
                    lambda intent: invoked.append(intent.arguments["executable"]),
                ),
            )
        ),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
    )
    first = runtime.run_turn(
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-exact-validator",
            message="continue",
        ),
        store.load(),
    )
    assert first.status is RunStatus.AWAITING_APPROVAL
    assert first.request is not None
    assert first.request.tool_call_id == "wrong-process"

    second = runtime.run_turn(
        ResolveApproval(
            conversation_id=state.conversation_id,
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            request_id=first.request.request_id,
            binding_digest=first.request.binding_digest,
            approved=False,
        ),
        store.load(),
    )

    assert second.status is RunStatus.AWAITING_APPROVAL
    assert second.request is not None
    assert second.request.tool_call_id == "exact-process"
    assert invoked == []
    assert any(
        fact.content.get("code") == "blocked_claim_not_verified"
        and "local_process" in fact.content.get("text", "")
        for fact in store.state.facts
    )
    assert store.state.goal is not None
    assert store.state.goal.status is not GoalStatus.BLOCKED

    third = runtime.run_turn(
        ResolveApproval(
            conversation_id=state.conversation_id,
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            request_id=second.request.request_id,
            binding_digest=second.request.binding_digest,
            approved=False,
        ),
        store.load(),
    )

    assert third.status is RunStatus.COMPLETED
    assert third.message == (
        "The requested local process was not run because you declined approval. "
        "No process was started, so the task remains blocked."
    )
    assert invoked == []
    assert store.state.goal is not None
    assert store.state.goal.status is GoalStatus.BLOCKED
    assert store.state.goal.next_step == "approve the exact requested local process"
    assert store.state.facts[-1].content == {
        "code": "blocked_claim",
        "blocker": third.message,
        "safe_attempts": [
            "requested the exact local process and recorded the denial without starting it"
        ],
        "resume_condition": "approve the exact requested local process",
    }


@pytest.mark.parametrize(
    ("has_process_obligation", "executed"),
    ((False, False), (True, True)),
)
def test_process_refusal_grounding_requires_obligation_and_zero_execution(
    has_process_obligation: bool,
    executed: bool,
) -> None:
    state = conversation_with_active_goal()
    assert state.goal is not None
    if has_process_obligation:
        state = replace(
            state,
            goal=replace(
                state.goal,
                proposed_criteria=(
                    *state.goal.proposed_criteria,
                    ProposedCriterion(
                        criterion_id="criterion:required-local-process:grounding",
                        description="the requested validator exits successfully",
                        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
                    ),
                ),
            ),
        )
    state = accept_action(
        state,
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-process-grounding",
            message="continue",
        ),
    ).state
    assert state.active_run is not None
    state = replace(
        state,
        facts=(
            *state.facts,
            ConversationFact(
                fact_id="run:run-process-grounding:tool-calls",
                kind=FactKind.TOOL_CALLS,
                content={
                    "calls": [
                        {
                            "tool_call_id": "process-grounding-call",
                            "name": "local_process",
                            "arguments": {"executable": "./check-greet"},
                        }
                    ]
                },
            ),
            ConversationFact(
                fact_id="run:run-process-grounding:tool-result",
                kind=FactKind.TOOL_RESULT,
                content={
                    "tool_call_id": "process-grounding-call",
                    "rejected": True,
                    "executed": executed,
                },
            ),
        ),
    )
    claim = BlockedClaim(
        correlation_id="untrusted-process-summary",
        goal_id=state.goal.goal_id,
        goal_revision=state.goal.revision,
        blocker="the process completed",
        safe_attempts=("ran it",),
        resume_condition="none",
    )

    grounded = AgentRuntime._ground_rejected_process_blocker(state, claim)

    assert grounded is claim


def test_process_refusal_grounding_ignores_stale_and_unrelated_rejections() -> None:
    state = conversation_with_active_goal()
    assert state.goal is not None
    source = replace(state.facts[0], content={"text": "运行 ./check-greet 验证结果。"})
    state = replace(
        state,
        facts=(source,),
        goal=replace(
            state.goal,
            created_from_fact_ids=(source.fact_id,),
            proposed_criteria=(
                *state.goal.proposed_criteria,
                ProposedCriterion(
                    criterion_id="criterion:required-local-process:exact-grounding",
                    description="the exact validator exits successfully",
                    oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
                ),
            ),
        ),
    )
    state = accept_action(
        state,
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-current-process-grounding",
            message="continue",
        ),
    ).state
    assert state.active_run is not None
    state = replace(
        state,
        facts=(
            *state.facts,
            ConversationFact(
                fact_id="run:old-process-grounding:stale-result",
                kind=FactKind.TOOL_RESULT,
                content={
                    "tool_call_id": "reused-exact-call",
                    "rejected": True,
                    "executed": False,
                },
            ),
            ConversationFact(
                fact_id="run:run-current-process-grounding:tool-calls",
                kind=FactKind.TOOL_CALLS,
                content={
                    "calls": [
                        {
                            "tool_call_id": "unrelated-call",
                            "name": "local_process",
                            "arguments": {"executable": "/bin/ls"},
                        },
                        {
                            "tool_call_id": "reused-exact-call",
                            "name": "local_process",
                            "arguments": {"executable": "./check-greet"},
                        },
                    ]
                },
            ),
            ConversationFact(
                fact_id="run:run-current-process-grounding:unrelated-result",
                kind=FactKind.TOOL_RESULT,
                content={
                    "tool_call_id": "unrelated-call",
                    "rejected": True,
                    "executed": False,
                },
            ),
            ConversationFact(
                fact_id="run:run-current-process-grounding:exact-result",
                kind=FactKind.TOOL_RESULT,
                content={
                    "tool_call_id": "reused-exact-call",
                    "rejected": False,
                    "executed": False,
                    "is_error": True,
                },
            ),
        ),
    )
    claim = BlockedClaim(
        correlation_id="technical-process-failure",
        goal_id=state.goal.goal_id,
        goal_revision=state.goal.revision,
        blocker="the exact validator could not start",
        safe_attempts=("requested the exact validator",),
        resume_condition="fix the local process environment",
    )

    grounded = AgentRuntime._ground_rejected_process_blocker(state, claim)

    assert grounded is claim


def test_process_refusal_grounding_keeps_executed_fact_across_reused_call_id() -> None:
    state = conversation_with_active_goal()
    assert state.goal is not None
    source = replace(state.facts[0], content={"text": "运行 ./check-greet 验证结果。"})
    state = replace(
        state,
        facts=(source,),
        goal=replace(
            state.goal,
            created_from_fact_ids=(source.fact_id,),
            proposed_criteria=(
                *state.goal.proposed_criteria,
                ProposedCriterion(
                    criterion_id="criterion:required-local-process:reused-call",
                    description="the exact validator exits successfully",
                    oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
                ),
            ),
        ),
    )
    state = accept_action(
        state,
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-reused-process-call",
            message="continue",
        ),
    ).state
    state = replace(
        state,
        facts=(
            *state.facts,
            ConversationFact(
                fact_id="run:run-reused-process-call:first-batch",
                kind=FactKind.TOOL_CALLS,
                content={
                    "calls": [
                        {
                            "tool_call_id": "reused-process-call",
                            "name": "local_process",
                            "arguments": {"executable": "./check-greet"},
                        }
                    ]
                },
            ),
            ConversationFact(
                fact_id="run:run-reused-process-call:first-result",
                kind=FactKind.TOOL_RESULT,
                content={
                    "tool_call_id": "reused-process-call",
                    "rejected": False,
                    "executed": True,
                },
            ),
            ConversationFact(
                fact_id="run:run-reused-process-call:second-batch",
                kind=FactKind.TOOL_CALLS,
                content={
                    "calls": [
                        {
                            "tool_call_id": "reused-process-call",
                            "name": "local_process",
                            "arguments": {"executable": "./check-greet"},
                        }
                    ]
                },
            ),
            ConversationFact(
                fact_id="action:reused-process-rejection",
                kind=FactKind.TOOL_RESULT,
                content={
                    "tool_call_id": "reused-process-call",
                    "rejected": True,
                    "executed": False,
                },
            ),
        ),
    )
    claim = BlockedClaim(
        correlation_id="reused-process-summary",
        goal_id=state.goal.goal_id,
        goal_revision=state.goal.revision,
        blocker="the validator ran before a later refusal",
        safe_attempts=("ran the validator once",),
        resume_condition="inspect the executed result",
    )

    grounded = AgentRuntime._ground_rejected_process_blocker(state, claim)

    assert grounded is claim


def test_process_refusal_grounding_invalidates_reused_id_for_non_process_call() -> None:
    state = conversation_with_active_goal()
    assert state.goal is not None
    source = replace(state.facts[0], content={"text": "运行 ./check-greet 验证结果。"})
    state = replace(
        state,
        facts=(source,),
        goal=replace(
            state.goal,
            created_from_fact_ids=(source.fact_id,),
            proposed_criteria=(
                *state.goal.proposed_criteria,
                ProposedCriterion(
                    criterion_id="criterion:required-local-process:cross-tool-call",
                    description="the exact validator exits successfully",
                    oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
                ),
            ),
        ),
    )
    state = accept_action(
        state,
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-cross-tool-call",
            message="continue",
        ),
    ).state
    state = replace(
        state,
        facts=(
            *state.facts,
            ConversationFact(
                fact_id="run:run-cross-tool-call:process-batch",
                kind=FactKind.TOOL_CALLS,
                content={
                    "calls": [
                        {
                            "tool_call_id": "cross-tool-call",
                            "name": "local_process",
                            "arguments": {"executable": "./check-greet"},
                        }
                    ]
                },
            ),
            ConversationFact(
                fact_id="run:run-cross-tool-call:process-result",
                kind=FactKind.TOOL_RESULT,
                content={
                    "tool_call_id": "cross-tool-call",
                    "rejected": False,
                    "executed": False,
                    "is_error": True,
                },
            ),
            ConversationFact(
                fact_id="run:run-cross-tool-call:file-batch",
                kind=FactKind.TOOL_CALLS,
                content={
                    "calls": [
                        {
                            "tool_call_id": "cross-tool-call",
                            "name": "write_file",
                            "arguments": {"path": "report.md", "content": "x"},
                        }
                    ]
                },
            ),
            ConversationFact(
                fact_id="action:cross-tool-call-rejection",
                kind=FactKind.TOOL_RESULT,
                content={
                    "tool_call_id": "cross-tool-call",
                    "rejected": True,
                    "executed": False,
                },
            ),
        ),
    )
    claim = BlockedClaim(
        correlation_id="cross-tool-process-summary",
        goal_id=state.goal.goal_id,
        goal_revision=state.goal.revision,
        blocker="the exact validator failed before it could start",
        safe_attempts=("requested the exact validator",),
        resume_condition="fix the validator environment",
    )

    grounded = AgentRuntime._ground_rejected_process_blocker(state, claim)

    assert grounded is claim


def test_process_refusal_grounding_uses_latest_relevant_process_outcome() -> None:
    state = conversation_with_active_goal()
    assert state.goal is not None
    source = replace(state.facts[0], content={"text": "运行 ./check-greet 验证结果。"})
    state = replace(
        state,
        facts=(source,),
        goal=replace(
            state.goal,
            created_from_fact_ids=(source.fact_id,),
            proposed_criteria=(
                *state.goal.proposed_criteria,
                ProposedCriterion(
                    criterion_id="criterion:required-local-process:latest-outcome",
                    description="the exact validator exits successfully",
                    oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
                ),
            ),
        ),
    )
    state = accept_action(
        state,
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-latest-process-outcome",
            message="continue",
        ),
    ).state
    state = replace(
        state,
        facts=(
            *state.facts,
            ConversationFact(
                fact_id="run:run-latest-process-outcome:first-batch",
                kind=FactKind.TOOL_CALLS,
                content={
                    "calls": [
                        {
                            "tool_call_id": "first-process-attempt",
                            "name": "local_process",
                            "arguments": {"executable": "./check-greet"},
                        }
                    ]
                },
            ),
            ConversationFact(
                fact_id="action:first-process-refusal",
                kind=FactKind.TOOL_RESULT,
                content={
                    "tool_call_id": "first-process-attempt",
                    "rejected": True,
                    "executed": False,
                },
            ),
            ConversationFact(
                fact_id="run:run-latest-process-outcome:retry-batch",
                kind=FactKind.TOOL_CALLS,
                content={
                    "calls": [
                        {
                            "tool_call_id": "approved-process-retry",
                            "name": "local_process",
                            "arguments": {"executable": "./check-greet"},
                        }
                    ]
                },
            ),
            ConversationFact(
                fact_id="run:run-latest-process-outcome:retry-result",
                kind=FactKind.TOOL_RESULT,
                content={
                    "tool_call_id": "approved-process-retry",
                    "rejected": False,
                    "executed": False,
                    "is_error": True,
                },
            ),
        ),
    )
    claim = BlockedClaim(
        correlation_id="approved-process-technical-failure",
        goal_id=state.goal.goal_id,
        goal_revision=state.goal.revision,
        blocker="the approved validator could not start",
        safe_attempts=("retried the exact validator with approval",),
        resume_condition="fix the validator environment",
    )

    grounded = AgentRuntime._ground_rejected_process_blocker(state, claim)

    assert grounded is claim


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
    assert goal_correction_pending(store.state) is False
    assert any(
        fact.content == {"text": "What is this workspace for?"}
        for fact in store.state.facts
    )


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


def test_paused_goal_denies_unadvertised_effectful_tool_before_prepare() -> None:
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
        ModelResponse((ModelTextBlock("The Goal is still paused."),)),
        registrations=(
            RegisteredTool(spec, lambda intent: executed.append("ran") or "written"),
        ),
    )

    result = runtime.run_turn(_submit_text(state, "please continue the task"), store.load())

    assert result.status is RunStatus.COMPLETED
    assert result.message == "The Goal is still paused."
    assert executed == []
    assert any(
        fact.content.get("code") == "unadvertised_tool"
        for fact in store.state.facts
    )
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
