import json
from dataclasses import replace

import pytest

from agent.runtime.checkpoint import (
    CheckpointCapacityError,
    CheckpointInvariantError,
    CheckpointVersionError,
    LocalCheckpointStore,
)
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    CompletionClaim,
    ContinuationPhase,
    ControlReceipt,
    ConversationState,
    EgressClass,
    EvidenceRecord,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    InteractionState,
    ProposedCriterion,
    ProviderDescriptor,
    ProviderDisclosureRequest,
    RecoveryRequest,
    SideEffectClass,
    ToolCall,
    canonical_json_digest,
)
from tests.continuity.test_contracts import _goal


def test_goal_control_disclosure_and_evidence_round_trip_in_v2(tmp_path) -> None:
    descriptor = ProviderDescriptor(
        family="openai",
        model="example-model",
        canonical_destination="https://api.example.com/v1",
        trust_profile="remote-https-v1",
        remote=True,
    )
    disclosure = ProviderDisclosureRequest.create(
        disclosure_id="disclosure:1",
        provider_descriptor_digest=descriptor.identity_digest,
        canonical_destination=descriptor.canonical_destination,
        model=descriptor.model,
        data_classes=("goal_facts", "user_message"),
    )
    receipt = disclosure.acknowledge(
        receipt_id="disclosure-receipt:1",
        acknowledged_action_seq=2,
        acknowledged_at="2026-08-02T00:00:30Z",
    )
    control_receipt = ControlReceipt.create(
        correlation_id="control:progress:1",
        control_kind="goal_progress",
        goal_id="goal:1",
        goal_revision=1,
        accepted_state_revision=4,
        payload_digest="b" * 64,
    )
    current_goal = _goal()
    goal = replace(
        current_goal,
        proposed_criteria=tuple(
            ProposedCriterion(item.criterion_id, item.description)
            for item in current_goal.proposed_criteria
        ),
    )
    criterion = goal.admitted_criteria[0]
    evidence = EvidenceRecord(
        evidence_id="evidence:1",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        criterion_id=criterion.criterion_id,
        oracle_kind=criterion.oracle_kind,
        predicate_digest=canonical_json_digest(criterion.predicate),
        source_fact_ids=("fact:tool:1",),
        source_digest="c" * 64,
        oracle_identity="filesystem-digest:v1",
        passed=True,
        observed_at="2026-08-02T00:01:00Z",
    )
    claim = CompletionClaim(
        correlation_id="control:claim:1",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        criterion_evidence_refs=(evidence.evidence_id,),
    )
    state = ConversationState(
        conversation_id="conversation:1",
        revision=5,
        goal=replace(goal, progress_summary="报告已生成", next_step="验证报告"),
        interaction_state=InteractionState.CLARIFYING,
        provider_disclosure_request=disclosure,
        provider_disclosure_receipt=receipt,
        control_receipts=(control_receipt,),
        evidence_records=(evidence,),
        completion_claim=claim,
    )

    store = LocalCheckpointStore.initialize(tmp_path / "conversation.json", state)

    assert store.load().state == state
    document = json.loads((tmp_path / "conversation.json").read_text())
    assert document["schema_version"] == 2


def test_answer_intent_and_receipt_round_trip_before_grounding_resumes(tmp_path) -> None:
    """begin_answer 必须先落盘；进程重启后才能继续开放只读能力。"""

    receipt = ControlReceipt.create(
        correlation_id="control:begin-answer:1",
        control_kind="begin_answer",
        goal_id=None,
        goal_revision=None,
        accepted_state_revision=2,
        payload_digest=canonical_json_digest({"interaction_state": "answering"}),
    )
    state = replace(
        ConversationState.new("conversation:answer"),
        revision=2,
        interaction_state=InteractionState.ANSWERING,
        active_run=ActiveRun(
            run_id="run:answer",
            status=ActiveRunStatus.PAUSED_RETRYABLE,
        ),
        control_receipts=(receipt,),
    )

    store = LocalCheckpointStore.initialize(tmp_path / "answer.json", state)

    assert store.load().state == state
    assert store.load().state.control_receipts[0].control_kind == "begin_answer"


def test_v1_checkpoint_is_rejected_without_mutating_source(tmp_path) -> None:
    path = tmp_path / "conversation.json"
    LocalCheckpointStore.initialize(path, ConversationState.new("conversation:1"))
    document = json.loads(path.read_text())
    document["schema_version"] = 1
    source = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(source)

    with pytest.raises(CheckpointVersionError, match="schema version: 1"):
        LocalCheckpointStore(path).load()

    assert path.read_bytes() == source


def test_unknown_fields_and_invalid_goal_invariants_fail_closed(tmp_path) -> None:
    path = tmp_path / "conversation.json"
    LocalCheckpointStore.initialize(
        path,
        ConversationState(conversation_id="conversation:1", goal=_goal()),
    )
    valid_document = json.loads(path.read_text())

    unknown = json.loads(json.dumps(valid_document))
    unknown["state"]["goal"]["unexpected"] = True
    path.write_text(json.dumps(unknown, sort_keys=True, separators=(",", ":")))
    with pytest.raises(CheckpointVersionError, match="unknown fields"):
        LocalCheckpointStore(path).load()

    invalid = json.loads(json.dumps(valid_document))
    invalid["state"]["goal"]["revision"] = 0
    path.write_text(json.dumps(invalid, sort_keys=True, separators=(",", ":")))
    with pytest.raises(CheckpointInvariantError, match="goal revision"):
        LocalCheckpointStore(path).load()


def test_checkpoint_capacity_counts_new_bounded_fields(tmp_path) -> None:
    LocalCheckpointStore.initialize(
        tmp_path / "empty.json",
        ConversationState.new("conversation:1"),
        max_state_bytes=800,
    )

    with pytest.raises(CheckpointCapacityError):
        LocalCheckpointStore.initialize(
            tmp_path / "goal.json",
            ConversationState(conversation_id="conversation:1", goal=_goal()),
            max_state_bytes=800,
        )


def test_public_network_executing_identity_round_trips(tmp_path) -> None:
    state = ConversationState(
        conversation_id="conversation:1",
        revision=4,
        active_run=ActiveRun(
            run_id="run:1",
            status=ActiveRunStatus.AWAITING_RECOVERY,
            phase=ContinuationPhase.EXECUTING,
            tool_calls=(ToolCall("call:1", "web_search", {"query": "bounded"}),),
            executing_intent=ExecutingIntentRecord(
                execution_authority=ExecutionAuthorityClass.IN_PROCESS,
                tool_call_id="call:1",
                intent_digest="intent:1",
                idempotency_key="idempotency:1",
                side_effect=SideEffectClass.READ_ONLY,
                egress=EgressClass.PUBLIC_NETWORK,
                operation="search",
                request_identity="request:1",
            ),
            pending_request=RecoveryRequest(
                request_id="recovery:1",
                run_id="run:1",
                tool_call_id="call:1",
                binding_digest="intent:1",
                summary="observation outcome unknown",
            ),
        ),
    )

    store = LocalCheckpointStore.initialize(tmp_path / "public-network.json", state)

    restored = store.load().state
    document = json.loads((tmp_path / "public-network.json").read_text())
    # 019：current writer 统一写 v8；v6/v7 继续作为 migration source。
    assert document["schema_version"] == 8
    assert restored == state
    assert restored.active_run is not None
    assert restored.active_run.executing_intent is not None
    assert restored.active_run.executing_intent.egress is EgressClass.PUBLIC_NETWORK
