from dataclasses import FrozenInstanceError, asdict

import pytest

from agent.runtime.contracts import (
    AcknowledgeProviderDisclosure,
    ActiveRun,
    ActiveRunStatus,
    AdmittedCriterion,
    AuthoritySourceKind,
    BlockedClaim,
    CancelGoal,
    ClarificationRequest,
    CompletionClaim,
    ConfirmCriterion,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    CriterionAdmissionBinding,
    EvidenceOracleKind,
    EvidenceRecord,
    ExecutingIntentRecord,
    FactAdmissionBinding,
    FactAdmissionClass,
    FactKind,
    GoalAuthorizationBinding,
    GoalDelta,
    GoalDeltaProposal,
    GoalFrame,
    GoalProgress,
    GoalProposal,
    GoalStatus,
    ModelResponse,
    ModelToolCall,
    PauseGoal,
    ProposedCriterion,
    ProviderDescriptor,
    RecoveryRequest,
    ResumeGoal,
    SelectGoal,
    ToolCall,
    canonical_action_digest,
    canonical_json_digest,
)
from agent.runtime.state import (
    GoalRevisionConflictError,
    apply_goal_delta,
    cancel_goal,
    complete_run,
    create_goal,
    pause_goal,
    record_completion_claim,
    record_goal_progress,
    resume_goal,
    verify_goal_completion,
)


def _criterion() -> AdmittedCriterion:
    return AdmittedCriterion(
        criterion_id="criterion:report-exists",
        description="报告文件存在且内容匹配",
        source_fact_id="fact:user:1",
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        predicate={"path": "reports/final.md", "sha256": "a" * 64},
        required_evidence_class="workspace_file",
        admission_digest="b" * 64,
    )


def _goal(**overrides) -> GoalFrame:
    values = {
        "goal_id": "goal:1",
        "revision": 1,
        "created_from_fact_ids": ("fact:user:1",),
        "workspace_identity_digest": "workspace:v1:" + "c" * 64,
        "user_outcome": "生成一份可验收的报告",
        "beneficiary": "owner",
        "targets": ("reports/final.md",),
        "scope": ("workspace",),
        "non_goals": ("不发送到外部服务",),
        "assumptions": (),
        "proposed_criteria": (
            ProposedCriterion(
                criterion_id="criterion:report-exists",
                description="报告文件存在且内容匹配",
            ),
        ),
        "admitted_criteria": (_criterion(),),
        "authority_snapshot": "authority:v1:" + "d" * 64,
        "status": GoalStatus.GOAL_READY,
        "created_at": "2026-08-02T00:00:00Z",
        "updated_at": "2026-08-02T00:00:00Z",
    }
    values.update(overrides)
    return GoalFrame(**values)


def _evidence(*, passed: bool = True) -> EvidenceRecord:
    criterion = _criterion()
    return EvidenceRecord(
        evidence_id="evidence:1",
        goal_id="goal:1",
        goal_revision=1,
        criterion_id=criterion.criterion_id,
        oracle_kind=criterion.oracle_kind,
        predicate_digest=canonical_json_digest(criterion.predicate),
        source_fact_ids=("fact:tool:1",),
        source_digest="f" * 64,
        oracle_identity="filesystem-digest:v1",
        passed=passed,
        observed_at="2026-08-02T00:01:00Z",
    )


def test_goal_frame_requires_stable_identity_scope_authority_and_criteria() -> None:
    goal = _goal()

    assert goal.goal_id == "goal:1"
    assert goal.admitted_criteria[0].criterion_id == "criterion:report-exists"
    with pytest.raises(FrozenInstanceError):
        goal.revision = 2  # type: ignore[misc]

    invalid_overrides = (
        {"goal_id": ""},
        {"revision": 0},
        {"created_from_fact_ids": ()},
        {"workspace_identity_digest": ""},
        {"user_outcome": ""},
        {"beneficiary": ""},
        {"targets": ()},
        {"scope": ()},
        {"proposed_criteria": (), "admitted_criteria": ()},
        {"authority_snapshot": ""},
    )
    for overrides in invalid_overrides:
        with pytest.raises(ValueError):
            _goal(**overrides)


def test_goal_delta_is_bound_to_goal_revision_and_invalidates_stale_claims() -> None:
    evidence = EvidenceRecord(
        evidence_id="evidence:1",
        goal_id="goal:1",
        goal_revision=1,
        criterion_id="criterion:report-exists",
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        predicate_digest="e" * 64,
        source_fact_ids=("fact:tool:1",),
        source_digest="f" * 64,
        oracle_identity="filesystem-digest:v1",
        passed=True,
        observed_at="2026-08-02T00:01:00Z",
    )
    claim = CompletionClaim(
        correlation_id="control:claim:1",
        goal_id="goal:1",
        goal_revision=1,
        criterion_evidence_refs=("evidence:1",),
    )
    state = ConversationState(
        conversation_id="conversation:1",
        goal=_goal(),
        evidence_records=(evidence,),
        completion_claim=claim,
    )
    delta = GoalDelta(
        goal_id="goal:1",
        expected_revision=1,
        reason="用户修正交付目录",
        updates={"targets": ["deliverables/final.md"]},
    )

    updated = apply_goal_delta(state, delta)

    assert updated.goal is not None
    assert updated.goal.revision == 2
    assert updated.goal.targets == ("deliverables/final.md",)
    assert updated.goal.status is GoalStatus.NEEDS_AUTHORITY
    assert updated.evidence_records == ()
    assert updated.completion_claim is None
    with pytest.raises(GoalRevisionConflictError):
        apply_goal_delta(updated, delta)


def test_run_completed_is_not_goal_verified_done() -> None:
    state = ConversationState(
        conversation_id="conversation:1",
        active_run=ActiveRun(run_id="run:1"),
        goal=_goal(),
    )

    completed_run = complete_run(state, message="本轮安全结束")

    assert completed_run.last_safe_result is not None
    assert completed_run.last_safe_result.status.value == "completed"
    assert completed_run.goal is not None
    assert completed_run.goal.status is GoalStatus.GOAL_READY
    with pytest.raises(ValueError, match="VERIFIED_DONE"):
        ConversationState(
            conversation_id="conversation:1",
            goal=_goal(status=GoalStatus.VERIFIED_DONE),
        )


def test_model_control_variants_are_closed_and_mutually_exclusive() -> None:
    variants = (
        ClarificationRequest(
            correlation_id="control:clarify:1",
            question="报告交付给谁？",
            boundary_code="beneficiary_missing",
            missing_fields=("beneficiary",),
            safe_assumptions=(),
        ),
        GoalProposal(correlation_id="control:goal:1", goal_frame=_goal()),
        GoalProgress(
            correlation_id="control:progress:1",
            goal_id="goal:1",
            goal_revision=1,
            summary="已完成资料收集",
            next_step="生成报告",
        ),
        GoalDeltaProposal(
            correlation_id="control:delta:1",
            delta=GoalDelta(
                goal_id="goal:1",
                expected_revision=1,
                reason="用户修正目标",
                updates={"targets": ["deliverables/final.md"]},
            ),
        ),
        CompletionClaim(
            correlation_id="control:claim:1",
            goal_id="goal:1",
            goal_revision=1,
            criterion_evidence_refs=(),
        ),
        BlockedClaim(
            correlation_id="control:blocked:1",
            goal_id="goal:1",
            goal_revision=1,
            blocker="缺少用户选择的目标格式",
            safe_attempts=("检查 workspace 现有格式",),
            resume_condition="用户确认格式",
        ),
    )

    for control in variants:
        assert ModelResponse(blocks=(), control=control).control is control

    with pytest.raises(TypeError, match="control"):
        ModelResponse(blocks=(), control=variants[:2])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="control.*tool"):
        ModelResponse(
            blocks=(ModelToolCall("call:1", "read_file", {"path": "README.md"}),),
            control=variants[0],
        )


def test_goal_authorization_requires_user_authoritative_source_binding() -> None:
    binding = GoalAuthorizationBinding.create(
        binding_id="authority-binding:1",
        goal_id="goal:1",
        goal_revision=1,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        operation="write_file",
        normalized_target="reports/final.md",
        source_kind=AuthoritySourceKind.USER_FACT,
        source_id="fact:user:1",
        source_digest="a" * 64,
    )

    assert binding.authorizes(
        goal_id="goal:1",
        goal_revision=1,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        operation="write_file",
        normalized_target="reports/final.md",
    )
    assert not binding.authorizes(
        goal_id="goal:1",
        goal_revision=1,
        workspace_identity_digest="workspace:v1:" + "d" * 64,
        operation="write_file",
        normalized_target="reports/final.md",
    )
    with pytest.raises(ValueError, match="authoritative"):
        GoalAuthorizationBinding.create(
            binding_id="authority-binding:forged",
            goal_id="goal:1",
            goal_revision=1,
            workspace_identity_digest="workspace:v1:" + "c" * 64,
            operation="write_file",
            normalized_target="reports/final.md",
            source_kind="model_output",  # type: ignore[arg-type]
            source_id="control:goal:1",
            source_digest="b" * 64,
        )
    with pytest.raises(ValueError, match="digest"):
        GoalAuthorizationBinding(
            binding_id=binding.binding_id,
            goal_id=binding.goal_id,
            goal_revision=binding.goal_revision,
            workspace_identity_digest=binding.workspace_identity_digest,
            operation=binding.operation,
            normalized_target=binding.normalized_target,
            source_kind=binding.source_kind,
            source_id=binding.source_id,
            source_digest=binding.source_digest,
            binding_digest="forged",
        )


def test_criterion_admission_binds_user_outcome_and_closed_predicate() -> None:
    predicate = {"path": "reports/final.md", "sha256": "a" * 64}
    binding = CriterionAdmissionBinding.create(
        binding_id="criterion-admission:1",
        goal_id="goal:1",
        goal_revision=1,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        criterion_id="criterion:report-exists",
        user_outcome_fact_id="fact:user:1",
        user_outcome_digest="d" * 64,
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        predicate=predicate,
        required_evidence_class="workspace_file",
    )

    admitted = binding.admit("报告文件存在且内容匹配")

    assert admitted.source_fact_id == "fact:user:1"
    assert admitted.admission_digest == binding.binding_digest
    assert binding.matches(
        goal_id="goal:1",
        goal_revision=1,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        criterion_id="criterion:report-exists",
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        predicate=predicate,
    )
    assert not binding.matches(
        goal_id="goal:1",
        goal_revision=1,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        criterion_id="criterion:report-exists",
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        predicate={"path": "reports/other.md", "sha256": "a" * 64},
    )
    with pytest.raises(ValueError, match="digest"):
        CriterionAdmissionBinding(
            binding_id=binding.binding_id,
            goal_id=binding.goal_id,
            goal_revision=binding.goal_revision,
            workspace_identity_digest=binding.workspace_identity_digest,
            criterion_id=binding.criterion_id,
            user_outcome_fact_id=binding.user_outcome_fact_id,
            user_outcome_digest=binding.user_outcome_digest,
            oracle_kind=binding.oracle_kind,
            predicate=binding.predicate,
            required_evidence_class=binding.required_evidence_class,
            binding_digest="forged",
        )


def test_fact_admission_binding_rejects_forged_or_cross_workspace_source() -> None:
    binding = FactAdmissionBinding.create(
        binding_id="fact-admission:1",
        fact_id="fact:tool:1",
        fact_kind=FactKind.TOOL_RESULT,
        fact_digest="a" * 64,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        goal_id="goal:1",
        goal_revision=1,
        admission_class=FactAdmissionClass.WORKSPACE_FACT,
    )

    assert binding.matches(
        fact_id="fact:tool:1",
        fact_digest="a" * 64,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        goal_id="goal:1",
        goal_revision=1,
    )
    assert not binding.matches(
        fact_id="fact:tool:1",
        fact_digest="a" * 64,
        workspace_identity_digest="workspace:v1:" + "d" * 64,
        goal_id="goal:1",
        goal_revision=1,
    )
    with pytest.raises(ValueError, match="digest"):
        FactAdmissionBinding(
            binding_id=binding.binding_id,
            fact_id=binding.fact_id,
            fact_kind=binding.fact_kind,
            fact_digest=binding.fact_digest,
            workspace_identity_digest=binding.workspace_identity_digest,
            goal_id=binding.goal_id,
            goal_revision=binding.goal_revision,
            admission_class=binding.admission_class,
            binding_digest="forged",
        )


def test_provider_descriptor_is_immutable_non_secret_and_canonical() -> None:
    descriptor = ProviderDescriptor(
        family="openai",
        model="example-model",
        canonical_destination="https://api.example.com/v1",
        trust_profile="remote-https-v1",
        remote=True,
    )

    assert descriptor.identity_digest
    assert set(asdict(descriptor)) == {
        "family",
        "model",
        "canonical_destination",
        "trust_profile",
        "remote",
    }
    with pytest.raises(FrozenInstanceError):
        descriptor.model = "changed"  # type: ignore[misc]

    unsafe_destinations = (
        "http://api.example.com/v1",
        "https://user:pass@api.example.com/v1",
        "https://api.example.com/v1?token=secret",
        "https://api.example.com/v1#fragment",
        "HTTPS://api.example.com/v1",
        "https://api.example.com/v1/",
    )
    for destination in unsafe_destinations:
        with pytest.raises(ValueError, match="canonical"):
            ProviderDescriptor(
                family="openai",
                model="example-model",
                canonical_destination=destination,
                trust_profile="remote-https-v1",
                remote=True,
            )


def test_goal_reducers_create_and_progress_only_from_bound_facts() -> None:
    user_fact = ConversationFact(
        fact_id="fact:user:1",
        kind=FactKind.USER_MESSAGE,
        content={"text": "生成一份可验收的报告"},
    )
    state = ConversationState(conversation_id="conversation:1", facts=(user_fact,))

    created = create_goal(state, _goal())
    progressed = record_goal_progress(
        created,
        GoalProgress(
            correlation_id="control:progress:1",
            goal_id="goal:1",
            goal_revision=1,
            summary="资料已收集",
            next_step="生成报告",
        ),
    )

    assert created.goal is not None
    assert created.revision == state.revision + 1
    assert progressed.goal is not None
    assert progressed.goal.status is GoalStatus.EXECUTING
    assert progressed.goal.progress_summary == "资料已收集"
    with pytest.raises(ValueError, match="source fact"):
        create_goal(ConversationState.new("conversation:2"), _goal())
    with pytest.raises(GoalRevisionConflictError):
        record_goal_progress(
            progressed,
            GoalProgress(
                correlation_id="control:progress:stale",
                goal_id="goal:1",
                goal_revision=2,
                summary="stale",
                next_step="stale",
            ),
        )


def test_typed_goal_actions_bind_conversation_state_and_goal_revision() -> None:
    common = {
        "conversation_id": "conversation:1",
        "expected_revision": 5,
    }
    actions = (
        AcknowledgeProviderDisclosure(
            **common,
            action_seq=2,
            request_digest="a" * 64,
            acknowledged_at="2026-08-02T00:00:00Z",
        ),
        SelectGoal(**common, action_seq=3, goal_id="goal:1"),
        PauseGoal(**common, action_seq=4, goal_id="goal:1", goal_revision=1),
        ResumeGoal(**common, action_seq=5, goal_id="goal:1", goal_revision=1),
        CancelGoal(**common, action_seq=6, goal_id="goal:1", goal_revision=1),
        ConfirmCriterion(
            **common,
            action_seq=7,
            goal_id="goal:1",
            goal_revision=1,
            criterion_id="criterion:report-exists",
            admission_binding_digest="b" * 64,
            confirmed=True,
        ),
    )

    assert len({canonical_action_digest(action) for action in actions}) == len(actions)
    with pytest.raises(ValueError, match="goal"):
        PauseGoal(**common, action_seq=8, goal_id="", goal_revision=1)
    with pytest.raises(ValueError, match="revision"):
        ResumeGoal(**common, action_seq=9, goal_id="goal:1", goal_revision=0)


def test_goal_lifecycle_reducers_reject_stale_and_preserve_unknown_effect() -> None:
    state = ConversationState(conversation_id="conversation:1", goal=_goal())

    paused = pause_goal(state, goal_id="goal:1", expected_revision=1)
    resumed = resume_goal(paused, goal_id="goal:1", expected_revision=1)
    cancelled = cancel_goal(resumed, goal_id="goal:1", expected_revision=1)

    assert paused.goal is not None and paused.goal.status is GoalStatus.PAUSED
    assert resumed.goal is not None and resumed.goal.status is GoalStatus.GOAL_READY
    assert cancelled.goal is not None and cancelled.goal.status is GoalStatus.CANCELLED
    with pytest.raises(GoalRevisionConflictError):
        pause_goal(state, goal_id="goal:1", expected_revision=2)

    call = ToolCall("call:1", "write_file", {"path": "reports/final.md"})
    intent = ExecutingIntentRecord("call:1", "intent:1", "idempotency:1")
    executing = ActiveRun(
        run_id="run:1",
        phase=ContinuationPhase.EXECUTING,
        executing_intent=intent,
        tool_calls=(call,),
    )
    recovering = ActiveRun(
        run_id="run:1",
        status=ActiveRunStatus.AWAITING_RECOVERY,
        phase=ContinuationPhase.EXECUTING,
        pending_request=RecoveryRequest(
            request_id="recovery:1",
            run_id="run:1",
            tool_call_id="call:1",
            binding_digest="intent:1",
            summary="write outcome unknown",
        ),
        executing_intent=intent,
        tool_calls=(call,),
    )

    for active_run in (executing, recovering):
        unsafe = ConversationState(
            conversation_id="conversation:1",
            goal=_goal(status=GoalStatus.EXECUTING),
            active_run=active_run,
        )
        with pytest.raises(ValueError, match="unknown effect"):
            pause_goal(unsafe, goal_id="goal:1", expected_revision=1)
        with pytest.raises(ValueError, match="unknown effect"):
            cancel_goal(unsafe, goal_id="goal:1", expected_revision=1)


def test_goal_completion_requires_current_claimed_evidence_and_no_unknown_effect() -> None:
    evidence = _evidence()
    claim = CompletionClaim(
        correlation_id="control:claim:1",
        goal_id="goal:1",
        goal_revision=1,
        criterion_evidence_refs=(evidence.evidence_id,),
    )
    state = ConversationState(
        conversation_id="conversation:1",
        goal=_goal(status=GoalStatus.EXECUTING),
        evidence_records=(evidence,),
    )

    claimed = record_completion_claim(state, claim)
    verified = verify_goal_completion(claimed)

    assert claimed.completion_claim is claim
    assert claimed.goal is not None and claimed.goal.status is GoalStatus.EXECUTING
    assert verified.goal is not None
    assert verified.goal.status is GoalStatus.VERIFIED_DONE
    assert verified.goal.next_step is None

    failed = ConversationState(
        conversation_id="conversation:1",
        goal=_goal(status=GoalStatus.EXECUTING),
        evidence_records=(_evidence(passed=False),),
        completion_claim=claim,
    )
    with pytest.raises(ValueError, match="mandatory criterion"):
        verify_goal_completion(failed)
    with pytest.raises(GoalRevisionConflictError):
        record_completion_claim(
            state,
            CompletionClaim(
                correlation_id="control:claim:stale",
                goal_id="goal:1",
                goal_revision=2,
                criterion_evidence_refs=(evidence.evidence_id,),
            ),
        )

    call = ToolCall("call:1", "write_file", {"path": "reports/final.md"})
    unsafe = ConversationState(
        conversation_id="conversation:1",
        goal=_goal(status=GoalStatus.EXECUTING),
        evidence_records=(evidence,),
        completion_claim=claim,
        active_run=ActiveRun(
            run_id="run:1",
            phase=ContinuationPhase.EXECUTING,
            executing_intent=ExecutingIntentRecord(
                "call:1", "intent:1", "idempotency:1"
            ),
            tool_calls=(call,),
        ),
    )
    with pytest.raises(ValueError, match="unknown effect"):
        verify_goal_completion(unsafe)
