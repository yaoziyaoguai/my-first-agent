from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRun,
    CompletionClaim,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    EvidenceOracleKind,
    ExecutingIntentRecord,
    FactKind,
    GoalStatus,
    ModelResponse,
    ModelTextBlock,
    RunStatus,
    SubmitMessage,
    ToolCall,
)
from agent.runtime.evidence import ClosedEvidenceRegistry, EvidenceVerificationError
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from tests.continuity.test_contracts import _goal
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider

CONTENT = "verified report\n"
CONTENT_DIGEST = hashlib.sha256(CONTENT.encode()).hexdigest()
EVIDENCE_ID = "evidence:goal:1:1:criterion:report-exists"


def _facts(*, fake: bool = False) -> tuple[ConversationFact, ...]:
    return (
        ConversationFact(
            fact_id="fact:user:1",
            kind=FactKind.USER_MESSAGE,
            content={"text": "write the exact verified report"},
        ),
        ConversationFact(
            fact_id="fact:calls:1",
            kind=FactKind.TOOL_CALLS,
            content={
                "calls": [
                    {
                        "tool_call_id": "read-1",
                        "name": "read_file",
                        "arguments": {"path": "reports/final.md"},
                    }
                ]
            },
        ),
        ConversationFact(
            fact_id="fact:read-result:1",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": "read-1",
                "text": CONTENT,
                "is_error": False,
                "executed": True,
                "metadata": {"fake": fake},
            },
        ),
    )


def _state(*, fake: bool = False) -> ConversationState:
    goal = _goal()
    criterion = goal.admitted_criteria[0]
    criterion = replace(
        criterion,
        predicate={"path": "reports/final.md", "sha256": CONTENT_DIGEST},
    )
    return ConversationState(
        conversation_id="conversation-1",
        facts=_facts(fake=fake),
        goal=replace(
            goal,
            admitted_criteria=(criterion,),
            status=GoalStatus.GOAL_READY,
        ),
    )


def _claim() -> CompletionClaim:
    return CompletionClaim(
        correlation_id="claim-1",
        goal_id="goal:1",
        goal_revision=1,
        criterion_evidence_refs=(EVIDENCE_ID,),
    )


def _runtime(state: ConversationState, response: ModelResponse):
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(response)
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=3_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-evidence",
    )
    action = SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-verify",
        message="verify completion",
    )
    return runtime, store, action


def test_text_done_and_model_completion_claim_cannot_self_verify() -> None:
    runtime, store, action = _runtime(
        _state(),
        ModelResponse((ModelTextBlock("done"),)),
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    assert store.state.goal.status is GoalStatus.GOAL_READY
    assert store.state.evidence_records == ()


def test_deterministic_receipts_bound_to_all_mandatory_criteria_verify_goal() -> None:
    runtime, store, action = _runtime(_state(), ModelResponse((), control=_claim()))

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    assert store.state.goal.status is GoalStatus.VERIFIED_DONE
    assert store.state.evidence_records[0].evidence_id == EVIDENCE_ID
    assert store.state.evidence_records[0].source_fact_ids == (
        "fact:calls:1",
        "fact:read-result:1",
    )


def test_filesystem_oracle_rederives_exact_path_and_content_digest_from_raw_facts() -> None:
    records = ClosedEvidenceRegistry().derive(
        _state(),
        _claim(),
        observed_at="2026-08-02T02:00:00Z",
    )
    assert records[0].passed is True
    assert records[0].oracle_identity == "filesystem-digest:v1"


def test_missing_failed_stale_or_tampered_evidence_rejects_verified_done() -> None:
    bad_claim = CompletionClaim(
        correlation_id="claim-bad",
        goal_id="goal:1",
        goal_revision=1,
        criterion_evidence_refs=("model-invented-evidence",),
    )
    with pytest.raises(EvidenceVerificationError, match="not exact"):
        ClosedEvidenceRegistry().derive(
            _state(),
            bad_claim,
            observed_at="2026-08-02T02:00:00Z",
        )


def test_fake_or_mock_receipt_cannot_satisfy_real_external_criterion() -> None:
    with pytest.raises(EvidenceVerificationError, match="read-back"):
        ClosedEvidenceRegistry().derive(
            _state(fake=True),
            _claim(),
            observed_at="2026-08-02T02:00:00Z",
        )


def test_tampered_stored_evidence_is_rederived_and_rejected() -> None:
    state = _state()
    derived = ClosedEvidenceRegistry().derive(
        state,
        _claim(),
        observed_at="2026-08-02T02:00:00Z",
    )[0]
    tampered = replace(derived, source_digest="tampered-source")

    with pytest.raises(EvidenceVerificationError, match="does not match raw"):
        ClosedEvidenceRegistry().derive(
            replace(state, evidence_records=(tampered,)),
            _claim(),
            observed_at="later",
        )


def test_unknown_effect_blocks_verified_done() -> None:
    state = _state()
    state = replace(
        state,
        active_run=ActiveRun(
            run_id="run-unknown",
            phase=ContinuationPhase.EXECUTING,
            owner_invocation_id="invocation-unknown",
            tool_calls=(
                ToolCall("write-1", "write_file", {"path": "reports/final.md"}),
            ),
            executing_intent=ExecutingIntentRecord(
                tool_call_id="write-1",
                intent_digest="intent-1",
                idempotency_key="key-1",
            ),
        ),
    )

    with pytest.raises(EvidenceVerificationError, match="unknown effect"):
        ClosedEvidenceRegistry().derive(
            state,
            _claim(),
            observed_at="2026-08-02T02:00:00Z",
        )


def test_subjective_criterion_requires_exact_user_confirmation() -> None:
    state = _state()
    assert state.goal is not None
    criterion = replace(
        state.goal.admitted_criteria[0],
        oracle_kind=EvidenceOracleKind.USER_CONFIRMATION,
        predicate={"confirmed": True},
    )
    state = replace(state, goal=replace(state.goal, admitted_criteria=(criterion,)))

    with pytest.raises(EvidenceVerificationError, match="user confirmation"):
        ClosedEvidenceRegistry().derive(
            state,
            _claim(),
            observed_at="2026-08-02T02:00:00Z",
        )

    confirmation = ConversationFact(
        fact_id="action:2:criterion-confirmation",
        kind=FactKind.USER_MESSAGE,
        content={"criterion_id": criterion.criterion_id, "confirmed": True},
    )
    records = ClosedEvidenceRegistry().derive(
        replace(state, facts=(*state.facts, confirmation)),
        _claim(),
        observed_at="2026-08-02T02:00:00Z",
    )
    assert records[0].oracle_identity == "user-confirmation:v1"


def test_zero_or_weakened_mandatory_criteria_cannot_verify() -> None:
    state = _state()
    assert state.goal is not None
    optional = replace(state.goal.admitted_criteria[0], mandatory=False)
    state = replace(state, goal=replace(state.goal, admitted_criteria=(optional,)))

    with pytest.raises(EvidenceVerificationError, match="no mandatory"):
        ClosedEvidenceRegistry().derive(
            state,
            _claim(),
            observed_at="2026-08-02T02:00:00Z",
        )
