"""F3 测试共用 helper：构造本次合成 state 的 typed 终态与 durable facts。"""

from __future__ import annotations

from dataclasses import replace

from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.contracts import (
    AdmittedCriterion,
    ConversationFact,
    ConversationState,
    EvidenceOracleKind,
    EvidenceRecord,
    ExecutionAuthorityClass,
    FactKind,
    GoalFrame,
    GoalStatus,
    ProcessOutcome,
    ProcessReceiptV1,
    ProposedCriterion,
)

CONVERSATION = "conversation-f3"
GOAL_ID = "goal-f3"
HEX = "a" * 64


def goal(
    status: GoalStatus,
    *,
    workspace_identity_digest: str = "w" * 64,
    with_process_criterion: bool = True,
) -> GoalFrame:
    criteria = []
    if with_process_criterion:
        criteria.append(
            AdmittedCriterion(
                criterion_id="criterion:required-local-process:f3",
                description="run the candidate tests",
                source_fact_id="fact-user",
                oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
                predicate={
                    "receipt_kind": "process_v1",
                    "command_fingerprint": HEX,
                    "outcome": "exited",
                    "exit_code": 0,
                },
                required_evidence_class="process_receipt",
                admission_digest="m" * 64,
                mandatory=True,
            )
        )
    return GoalFrame(
        goal_id=GOAL_ID, revision=1,
        created_from_fact_ids=("fact-user",),
        workspace_identity_digest=workspace_identity_digest,
        user_outcome="fix and verify",
        beneficiary="user",
        targets=("artifact.txt",),
        scope=("workspace",),
        non_goals=(), assumptions=(),
        proposed_criteria=tuple(
            ProposedCriterion(
                criterion_id=item.criterion_id,
                description=item.description,
                oracle_kind=item.oracle_kind,
            )
            for item in criteria
        ),
        admitted_criteria=tuple(criteria),
        authority_snapshot="fixed",
        status=status,
        created_at="2026-10-02T00:00:00Z",
        updated_at="2026-10-02T00:00:00Z",
    )


def evidence_record(criterion_id: str, *, passed: bool = True) -> EvidenceRecord:
    from agent.runtime.contracts import canonical_json_digest
    from agent.runtime.evidence import ClosedEvidenceRegistry

    predicate = {
        "receipt_kind": "process_v1",
        "command_fingerprint": HEX,
        "outcome": "exited",
        "exit_code": 0,
    }
    return EvidenceRecord(
        evidence_id=ClosedEvidenceRegistry.evidence_id(GOAL_ID, 1, criterion_id),
        goal_id=GOAL_ID,
        goal_revision=1,
        criterion_id=criterion_id,
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate_digest=canonical_json_digest(predicate),
        source_fact_ids=(f"fact:process:{criterion_id}",),
        source_digest=HEX,
        oracle_identity="process-receipt:v1",
        passed=passed,
        observed_at="2026-10-02T00:00:00Z",
    )


def state(
    *,
    status: GoalStatus = GoalStatus.VERIFIED_DONE,
    facts: tuple[ConversationFact, ...] = (),
    evidence: tuple[EvidenceRecord, ...] = (),
    with_process_criterion: bool = True,
    with_claim: bool = True,
) -> ConversationState:
    from agent.runtime.contracts import CompletionClaim

    claim = None
    evidence_records = evidence
    if status is GoalStatus.VERIFIED_DONE and with_claim:
        criterion_id = "criterion:required-local-process:f3"
        record = evidence_record(criterion_id)
        claim = CompletionClaim(
            correlation_id="claim-f3",
            goal_id=GOAL_ID,
            goal_revision=1,
            criterion_evidence_refs=(record.evidence_id,),
        )
        evidence_records = evidence if evidence else (record,)
    return ConversationState(
        completion_claim=claim,
        conversation_id=CONVERSATION,
        facts=facts,
        goal=goal(status, with_process_criterion=with_process_criterion),
        evidence_records=evidence_records,
    )


def checkpoint(path, *, status: GoalStatus = GoalStatus.VERIFIED_DONE) -> None:
    """在真实 open_workspace_session 已建的 checkpoint 上设置 Goal 终态。"""

    store = LocalCheckpointStore(path)
    snapshot = store.load()
    lease = store.try_acquire(snapshot.state.conversation_id)
    assert lease is not None
    try:
        binding = snapshot.state.workspace_binding
        target = replace(
            snapshot.state,
            goal=goal(
                status,
                workspace_identity_digest=(
                    binding.workspace_identity_digest if binding else "w" * 64
                ),
            ),
        )
        store.compare_and_swap(snapshot, target)
    finally:
        lease.release()


def process_receipt_fact(
    label: str,
    *,
    exit_code: int = 0,
    goal_id: str = GOAL_ID,
    is_error: bool = False,
) -> ConversationFact:
    receipt = ProcessReceiptV1.create(
        lease_id=f"process-lease:{label}",
        lease_digest=label.encode().hex().ljust(64, "0")[:64],
        use_ordinal=1,
        goal_id=goal_id,
        goal_revision=1,
        workspace_identity_digest="w" * 64,
        tool_identity="c" * 64,
        intent_digest=HEX,
        executable_digest="e" * 64,
        argv_digest=HEX,
        cwd_digest="1" * 64,
        resource_profile="standard",
        environment_policy_digest="2" * 64,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        outcome=ProcessOutcome.EXITED,
        exit_code=exit_code,
        signal=None,
        started_at="1.0",
        ended_at="2.0",
        duration_seconds=1.0,
        stdout_digest="3" * 64,
        stderr_digest="4" * 64,
        stdout_bytes=0,
        stderr_bytes=0,
        stdout_truncated=False,
        stderr_truncated=False,
        group_cleanup_claim="unconfirmed",
        command_fingerprint=HEX,
    )
    return ConversationFact(
        fact_id=f"fact:process:{label}",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": label,
            "text": "local_process exited",
            "is_error": is_error or exit_code != 0,
            "executed": True,
            "metadata": {
                "process_receipt_kind": "process_v1",
                "process_receipt": receipt.to_json(),
                "receipt_digest": receipt.receipt_digest,
                "execution_authority": "local_same_uid_process",
                "outcome": "exited",
                "exit_code": exit_code,
                "command_fingerprint": HEX,
                "stdout_truncated": False,
                "stderr_truncated": False,
                "duration_seconds": 1.0,
                "resource_profile": "standard",
                "stdout_digest": "3" * 64,
                "stderr_digest": "4" * 64,
                "lease_id": f"process-lease:{label}",
                "use_ordinal": 1,
                "tool_identity": "c" * 64,
            },
        },
    )




def derived_state(facts: tuple[ConversationFact, ...] = ()) -> ConversationState:
    """VERIFIED_DONE state：evidence 经 ClosedEvidenceRegistry 真实 derive 生成。"""

    from agent.runtime.contracts import CompletionClaim
    from agent.runtime.evidence import ClosedEvidenceRegistry

    criterion_id = "criterion:required-local-process:f3"
    claim = CompletionClaim(
        correlation_id="claim-f3",
        goal_id=GOAL_ID,
        goal_revision=1,
        criterion_evidence_refs=(
            ClosedEvidenceRegistry.evidence_id(GOAL_ID, 1, criterion_id),
        ),
    )
    base = ConversationState(
        completion_claim=None,
        conversation_id=CONVERSATION,
        facts=facts,
        goal=goal(GoalStatus.GOAL_READY),
    )
    records = ClosedEvidenceRegistry().derive(
        base, claim, observed_at="2026-10-03T00:00:00Z"
    )
    return replace(
        base,
        completion_claim=claim,
        evidence_records=records,
        goal=goal(GoalStatus.VERIFIED_DONE),
    )
