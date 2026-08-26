from dataclasses import FrozenInstanceError, asdict

import pytest

from agent.runtime.contracts import (
    AcknowledgeProviderDisclosure,
    ActiveRun,
    ActiveRunStatus,
    AdmittedCriterion,
    ApprovalRequest,
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
    DirectResponse,
    EgressClass,
    EvidenceOracleKind,
    EvidenceRecord,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    ExecutionIntent,
    FactAdmissionBinding,
    FactAdmissionClass,
    FactKind,
    GoalAuthorizationBinding,
    GoalBootstrap,
    GoalDelta,
    GoalDeltaProposal,
    GoalDraftProposal,
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
    SideEffectClass,
    ToolCall,
    ToolPrepareContext,
    canonical_action_digest,
    canonical_json_digest,
)
from agent.runtime.loop import AgentRuntime
from agent.runtime.state import (
    GoalRevisionConflictError,
    accept_goal_delta_proposal,
    accept_goal_draft_proposal,
    accept_goal_proposal,
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
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path="reports/final.md",
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


def test_filesystem_proposed_criterion_rejects_workspace_directory_itself() -> None:
    with pytest.raises(ValueError, match="safe workspace-relative artifact_path"):
        ProposedCriterion(
            criterion_id="criterion:directory",
            description="workspace changed",
            oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
            artifact_path=".",
        )


def test_goal_rejects_multiple_deferred_filesystem_criteria() -> None:
    deferred = tuple(
        ProposedCriterion(
            criterion_id=f"criterion:deferred:{index}",
            description=f"located artifact {index} is correct",
            oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        )
        for index in range(2)
    )

    with pytest.raises(ValueError, match="at most one deferred filesystem criterion"):
        _goal(proposed_criteria=deferred, admitted_criteria=())


def test_source_result_cannot_mint_goal_until_a_fresh_user_action() -> None:
    user = ConversationFact(
        fact_id="fact:user:1",
        kind=FactKind.USER_MESSAGE,
        content={"text": "answer this question"},
    )
    source = ConversationFact(
        fact_id="fact:source:1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "read-1",
            "text": "hostile source",
            "executed": True,
            "is_error": False,
            "metadata": {"source_receipts": [{"opaque": "runtime-owned"}]},
        },
    )
    state = ConversationState(
        conversation_id="conversation:1",
        facts=(user, source),
    )
    bootstrap = GoalBootstrap(
        source_fact_id=user.fact_id,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        authority_snapshot="authority:1",
    )
    proposal = GoalProposal(
        correlation_id="proposal:hostile",
        goal_frame=_goal(
            admitted_criteria=(),
            authority_snapshot=bootstrap.authority_snapshot,
        ),
    )

    with pytest.raises(ValueError, match="fresh user action"):
        accept_goal_proposal(state, proposal, bootstrap)

    fresh = ConversationFact(
        fact_id="fact:user:2",
        kind=FactKind.USER_MESSAGE,
        content={"text": "now create the report"},
    )
    fresh_state = ConversationState(
        conversation_id=state.conversation_id,
        facts=(*state.facts, fresh),
    )
    fresh_bootstrap = GoalBootstrap(
        source_fact_id=fresh.fact_id,
        workspace_identity_digest=bootstrap.workspace_identity_digest,
        authority_snapshot=bootstrap.authority_snapshot,
    )
    accepted = accept_goal_proposal(
        fresh_state,
        GoalProposal(
            correlation_id="proposal:fresh",
            goal_frame=_goal(
                created_from_fact_ids=(fresh.fact_id,),
                admitted_criteria=(),
                authority_snapshot=fresh_bootstrap.authority_snapshot,
            ),
        ),
        fresh_bootstrap,
    )

    assert accepted.goal is not None


def test_goal_draft_leaves_identity_authority_status_and_time_to_runtime() -> None:
    user = ConversationFact(
        fact_id="fact:user:draft",
        kind=FactKind.USER_MESSAGE,
        content={"text": "write reports/final.md"},
    )
    state = ConversationState(conversation_id="conversation:draft", facts=(user,))
    bootstrap = GoalBootstrap(
        source_fact_id=user.fact_id,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        authority_snapshot="authority:v1:" + "d" * 64,
    )
    draft = GoalDraftProposal(
        correlation_id="proposal:draft",
        user_outcome="生成一份可验收的报告",
        beneficiary="owner",
        targets=("reports/final.md",),
        scope=("workspace",),
        non_goals=("不修改其他文件",),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                criterion_id="criterion:draft",
                description="报告文件存在",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path="reports/final.md",
            ),
        ),
        requires_public_web=True,
        requires_local_process=True,
    )

    accepted = accept_goal_draft_proposal(
        state,
        draft,
        bootstrap,
        admitted_at="2026-08-20T00:00:00Z",
    )

    goal = accepted.goal
    assert goal is not None
    assert goal.goal_id.startswith("goal-v1-")
    assert goal.created_from_fact_ids == (user.fact_id,)
    assert all(
        item.oracle_kind is not EvidenceOracleKind.TOOL_RECEIPT
        for item in goal.proposed_criteria
    )
    assert goal.workspace_identity_digest == bootstrap.workspace_identity_digest
    assert goal.authority_snapshot == bootstrap.authority_snapshot
    assert goal.status is GoalStatus.GOAL_READY
    assert goal.next_step is None
    assert goal.admitted_criteria == ()
    assert goal.created_at == goal.updated_at == "2026-08-20T00:00:00Z"
    web_requirements = tuple(
        item
        for item in goal.proposed_criteria
        if item.oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT
    )
    assert web_requirements == ()


@pytest.mark.parametrize(
    ("user_text", "target", "invented_oracle", "model_flag"),
    (
        (
            "调查 pathlib 的当前公开说明与常见用法，把结论和来源写入 research.md。",
            "research.md",
            EvidenceOracleKind.TOOL_RECEIPT,
            "requires_local_process",
        ),
        (
            "把项目说明写入 report.md。",
            "report.md",
            EvidenceOracleKind.WEB_SOURCE_RECEIPT,
            "requires_public_web",
        ),
        (
            "Write report.md explaining how to run tests.",
            "report.md",
            EvidenceOracleKind.TOOL_RECEIPT,
            "requires_local_process",
        ),
        (
            "Write report.md containing the phrase call local_process.",
            "report.md",
            EvidenceOracleKind.TOOL_RECEIPT,
            "requires_local_process",
        ),
        (
            "Write report.md containing the phrase public Web research.",
            "report.md",
            EvidenceOracleKind.WEB_SOURCE_RECEIPT,
            "requires_public_web",
        ),
        (
            "Write report.md explaining current package versioning.",
            "report.md",
            EvidenceOracleKind.WEB_SOURCE_RECEIPT,
            "requires_public_web",
        ),
        (
            "How do I run the project tests?",
            "report.md",
            EvidenceOracleKind.TOOL_RECEIPT,
            "requires_local_process",
        ),
        (
            "What command runs the tests?",
            "report.md",
            EvidenceOracleKind.TOOL_RECEIPT,
            "requires_local_process",
        ),
        (
            "如何运行项目测试？",
            "report.md",
            EvidenceOracleKind.TOOL_RECEIPT,
            "requires_local_process",
        ),
        (
            "怎么执行这个校验器？",
            "report.md",
            EvidenceOracleKind.TOOL_RECEIPT,
            "requires_local_process",
        ),
    ),
)
def test_goal_draft_cannot_invent_effect_obligation_absent_from_user_fact(
    user_text: str,
    target: str,
    invented_oracle: EvidenceOracleKind,
    model_flag: str,
) -> None:
    user = ConversationFact(
        fact_id="fact:user:no-invented-effect",
        kind=FactKind.USER_MESSAGE,
        content={"text": user_text},
    )
    state = ConversationState(
        conversation_id="conversation:no-invented-effect",
        facts=(user,),
    )
    bootstrap = GoalBootstrap(
        source_fact_id=user.fact_id,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        authority_snapshot="authority:v1:" + "d" * 64,
    )
    flags = {model_flag: True}
    draft = GoalDraftProposal(
        correlation_id="proposal:no-invented-effect",
        user_outcome="Create the requested workspace artifact",
        beneficiary="owner",
        targets=(target,),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                criterion_id="criterion:artifact",
                description="the requested artifact exists",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path=target,
            ),
            ProposedCriterion(
                criterion_id="criterion:model-invented-effect",
                description="an effect the user did not request",
                oracle_kind=invented_oracle,
            ),
        ),
        **flags,
    )

    accepted = accept_goal_draft_proposal(
        state,
        draft,
        bootstrap,
        admitted_at="2026-08-20T00:00:00Z",
    )

    assert accepted.goal is not None
    assert invented_oracle not in {
        item.oracle_kind for item in accepted.goal.proposed_criteria
    }


def test_goal_draft_rejects_filesystem_criterion_outside_targets() -> None:
    user = ConversationFact(
        fact_id="fact:user:mismatched-artifact",
        kind=FactKind.USER_MESSAGE,
        content={"text": "fix greet and run its test"},
    )
    state = ConversationState(
        conversation_id="conversation:mismatched-artifact",
        facts=(user,),
    )
    bootstrap = GoalBootstrap(
        source_fact_id=user.fact_id,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        authority_snapshot="authority:v1:" + "d" * 64,
    )
    draft = GoalDraftProposal(
        correlation_id="proposal:mismatched-artifact",
        user_outcome="修复 greet 并运行测试",
        beneficiary="owner",
        targets=("greet.py",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                criterion_id="criterion:invented-test-output",
                description="测试输出文件存在",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path="test-results.txt",
            ),
        ),
        requires_local_process=True,
    )

    with pytest.raises(ValueError, match="filesystem artifact criteria must match targets"):
        accept_goal_draft_proposal(
            state,
            draft,
            bootstrap,
            admitted_at="2026-08-20T00:00:00Z",
        )


def test_goal_draft_derives_explicit_web_and_process_obligations_from_user_fact() -> None:
    user = ConversationFact(
        fact_id="fact:user:mixed-obligations",
        kind=FactKind.USER_MESSAGE,
        content={
            "text": (
                "结合 data.csv 和公开资料写入 report.md，"
                "然后运行项目里的校验器确认格式。"
            )
        },
    )
    state = ConversationState(
        conversation_id="conversation:mixed-obligations",
        facts=(user,),
    )
    bootstrap = GoalBootstrap(
        source_fact_id=user.fact_id,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        authority_snapshot="authority:v1:" + "d" * 64,
    )
    draft = GoalDraftProposal(
        correlation_id="proposal:mixed-obligations",
        user_outcome="生成并校验 report.md",
        beneficiary="owner",
        targets=("report.md",),
        scope=("workspace", "public_web"),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                criterion_id="criterion:report",
                description="报告文件存在",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path="report.md",
            ),
        ),
        requires_public_web=False,
        requires_local_process=False,
    )

    accepted = accept_goal_draft_proposal(
        state,
        draft,
        bootstrap,
        admitted_at="2026-08-20T00:00:00Z",
    )

    assert accepted.goal is not None
    oracle_kinds = {item.oracle_kind for item in accepted.goal.proposed_criteria}
    assert EvidenceOracleKind.WEB_SOURCE_RECEIPT in oracle_kinds
    assert EvidenceOracleKind.TOOL_RECEIPT in oracle_kinds


@pytest.mark.parametrize(
    "model_requires_effects",
    (False, True),
)
@pytest.mark.parametrize(
    "user_text",
    (
        "只修改 report.md，不要运行测试，也不要联网搜索公开资料。",
        (
            "Do not use latest version information; do not run ./check-report; "
            "only modify report.md."
        ),
        (
            "运行测试并使用最新公开资料。不要运行任何程序，也不要联网，"
            "只修改 report.md。"
        ),
        (
            "Run tests and use current public information. Do not execute any programs; "
            "do not use the web; only modify report.md."
        ),
        "Do not call local_process; only modify report.md.",
    ),
)
def test_goal_draft_respects_explicit_user_effect_prohibitions(
    user_text: str,
    model_requires_effects: bool,
) -> None:
    user = ConversationFact(
        fact_id="fact:user:prohibits-effects",
        kind=FactKind.USER_MESSAGE,
        content={"text": user_text},
    )
    state = ConversationState(
        conversation_id="conversation:prohibits-effects",
        facts=(user,),
    )
    bootstrap = GoalBootstrap(
        source_fact_id=user.fact_id,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        authority_snapshot="authority:v1:" + "d" * 64,
    )
    draft = GoalDraftProposal(
        correlation_id="proposal:prohibits-effects",
        user_outcome="只修改 report.md",
        beneficiary="owner",
        targets=("report.md",),
        scope=("workspace",),
        non_goals=("不要运行测试", "不要联网搜索公开资料"),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                criterion_id="criterion:report",
                description="report.md exists",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path="report.md",
            ),
        ),
        requires_public_web=model_requires_effects,
        requires_local_process=model_requires_effects,
    )

    accepted = accept_goal_draft_proposal(
        state,
        draft,
        bootstrap,
        admitted_at="2026-08-20T00:00:00Z",
    )

    assert accepted.goal is not None
    assert {
        item.oracle_kind for item in accepted.goal.proposed_criteria
    } == {EvidenceOracleKind.FILESYSTEM_DIGEST}


@pytest.mark.parametrize(
    "user_text",
    (
        "不要只分析，运行测试并把结果写入 report.md。",
        "不要运行无关项，只运行 ./check-report。",
    ),
)
def test_goal_draft_negation_scope_does_not_hide_later_process_requirement(
    user_text: str,
) -> None:
    user = ConversationFact(
        fact_id="fact:user:positive-after-negation",
        kind=FactKind.USER_MESSAGE,
        content={"text": user_text},
    )
    state = ConversationState(
        conversation_id="conversation:positive-after-negation",
        facts=(user,),
    )
    bootstrap = GoalBootstrap(
        source_fact_id=user.fact_id,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        authority_snapshot="authority:v1:" + "d" * 64,
    )
    draft = GoalDraftProposal(
        correlation_id="proposal:positive-after-negation",
        user_outcome="运行测试并记录结果",
        beneficiary="owner",
        targets=("report.md",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                criterion_id="criterion:report",
                description="report.md exists",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path="report.md",
            ),
        ),
        requires_local_process=False,
    )

    accepted = accept_goal_draft_proposal(
        state,
        draft,
        bootstrap,
        admitted_at="2026-08-20T00:00:00Z",
    )

    assert accepted.goal is not None
    assert EvidenceOracleKind.TOOL_RECEIPT in {
        item.oracle_kind for item in accepted.goal.proposed_criteria
    }


@pytest.mark.parametrize(
    ("user_text", "required_oracle"),
    (
        (
            "Execute ./check-report and write report.md.",
            EvidenceOracleKind.TOOL_RECEIPT,
        ),
        (
            "运行 ./check-report 并写入 report.md。",
            EvidenceOracleKind.TOOL_RECEIPT,
        ),
        (
            "Use current release information and write report.md.",
            EvidenceOracleKind.WEB_SOURCE_RECEIPT,
        ),
        (
            "Use the latest package versions and write report.md.",
            EvidenceOracleKind.WEB_SOURCE_RECEIPT,
        ),
        (
            "Call local_process with executable=count-run and write report.md.",
            EvidenceOracleKind.TOOL_RECEIPT,
        ),
        (
            "调用 local_process 运行 count-run 并写入 report.md。",
            EvidenceOracleKind.TOOL_RECEIPT,
        ),
        (
            "Run count-run to validate the workspace result.",
            EvidenceOracleKind.TOOL_RECEIPT,
        ),
        (
            "运行 count-run 验证工作区结果。",
            EvidenceOracleKind.TOOL_RECEIPT,
        ),
        (
            "Please run count-run.",
            EvidenceOracleKind.TOOL_RECEIPT,
        ),
        (
            "Please execute check-report.",
            EvidenceOracleKind.TOOL_RECEIPT,
        ),
        (
            "请运行 count-run。",
            EvidenceOracleKind.TOOL_RECEIPT,
        ),
        (
            "请执行 check-report。",
            EvidenceOracleKind.TOOL_RECEIPT,
        ),
        (
            "Can you run the tests and write report.md?",
            EvidenceOracleKind.TOOL_RECEIPT,
        ),
    ),
)
def test_goal_draft_lower_bound_covers_explicit_english_directives(
    user_text: str,
    required_oracle: EvidenceOracleKind,
) -> None:
    user = ConversationFact(
        fact_id="fact:user:explicit-english-obligation",
        kind=FactKind.USER_MESSAGE,
        content={"text": user_text},
    )
    state = ConversationState(
        conversation_id="conversation:explicit-english-obligation",
        facts=(user,),
    )
    bootstrap = GoalBootstrap(
        source_fact_id=user.fact_id,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        authority_snapshot="authority:v1:" + "d" * 64,
    )
    draft = GoalDraftProposal(
        correlation_id="proposal:explicit-english-obligation",
        user_outcome="Write report.md with the requested verification",
        beneficiary="owner",
        targets=("report.md",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                criterion_id="criterion:report",
                description="report.md exists",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path="report.md",
            ),
        ),
        requires_public_web=False,
        requires_local_process=False,
    )

    accepted = accept_goal_draft_proposal(
        state,
        draft,
        bootstrap,
        admitted_at="2026-08-20T00:00:00Z",
    )

    assert accepted.goal is not None
    assert required_oracle in {
        item.oracle_kind for item in accepted.goal.proposed_criteria
    }


@pytest.mark.parametrize(
    ("user_text", "model_criterion_id", "oracle_kind", "required_prefix"),
    (
        (
            "Use current release information and write report.md.",
            "criterion:model-web",
            EvidenceOracleKind.WEB_SOURCE_RECEIPT,
            "criterion:required-public-web:",
        ),
        (
            "Execute ./check-report and write report.md.",
            "criterion:model-process",
            EvidenceOracleKind.TOOL_RECEIPT,
            "criterion:required-local-process:",
        ),
    ),
)
def test_authoritative_lower_bound_cannot_be_shadowed_then_dropped_by_correction(
    user_text: str,
    model_criterion_id: str,
    oracle_kind: EvidenceOracleKind,
    required_prefix: str,
) -> None:
    user = ConversationFact(
        fact_id="fact:user:runtime-owned-lower-bound",
        kind=FactKind.USER_MESSAGE,
        content={"text": user_text},
    )
    state = ConversationState(
        conversation_id="conversation:runtime-owned-lower-bound",
        facts=(user,),
    )
    bootstrap = GoalBootstrap(
        source_fact_id=user.fact_id,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        authority_snapshot="authority:v1:" + "d" * 64,
    )
    draft = GoalDraftProposal(
        correlation_id="proposal:runtime-owned-lower-bound",
        user_outcome="Write the requested and verified report",
        beneficiary="owner",
        targets=("report.md",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                criterion_id="criterion:report",
                description="report.md exists",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path="report.md",
            ),
            ProposedCriterion(
                criterion_id=model_criterion_id,
                description="model-proposed obligation with the same oracle kind",
                oracle_kind=oracle_kind,
            ),
        ),
        requires_public_web=False,
        requires_local_process=False,
    )

    accepted = accept_goal_draft_proposal(
        state,
        draft,
        bootstrap,
        admitted_at="2026-08-20T00:00:00Z",
    )

    assert accepted.goal is not None
    runtime_owned_ids = {
        item.criterion_id
        for item in accepted.goal.proposed_criteria
        if item.criterion_id.startswith(required_prefix)
    }
    assert len(runtime_owned_ids) == 1
    assert model_criterion_id not in {
        item.criterion_id for item in accepted.goal.proposed_criteria
    }
    assert sum(
        item.oracle_kind is oracle_kind
        for item in accepted.goal.proposed_criteria
    ) == 1

    corrected = apply_goal_delta(
        accepted,
        GoalDelta(
            goal_id=accepted.goal.goal_id,
            expected_revision=accepted.goal.revision,
            reason="write corrected.md instead; keep every other requirement",
            updates={
                "targets": ["corrected.md"],
                "proposed_criteria": [
                    {
                        "criterion_id": "criterion:corrected-report",
                        "description": "corrected.md exists",
                        "oracle_kind": EvidenceOracleKind.FILESYSTEM_DIGEST.value,
                        "artifact_path": "corrected.md",
                    }
                ],
            },
        ),
    )

    assert corrected.goal is not None
    assert runtime_owned_ids <= {
        item.criterion_id for item in corrected.goal.proposed_criteria
    }


def test_goal_draft_cannot_mint_runtime_owned_obligation_identifier() -> None:
    user = ConversationFact(
        fact_id="fact:user:reserved-obligation-id",
        kind=FactKind.USER_MESSAGE,
        content={"text": "write report.md"},
    )
    state = ConversationState(
        conversation_id="conversation:reserved-obligation-id",
        facts=(user,),
    )
    bootstrap = GoalBootstrap(
        source_fact_id=user.fact_id,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        authority_snapshot="authority:v1:" + "d" * 64,
    )
    draft = GoalDraftProposal(
        correlation_id="proposal:reserved-obligation-id",
        user_outcome="Write report.md",
        beneficiary="owner",
        targets=("report.md",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                criterion_id="criterion:required-public-web:model-minted",
                description="model cannot mint Runtime authority",
                oracle_kind=EvidenceOracleKind.WEB_SOURCE_RECEIPT,
            ),
        ),
    )

    with pytest.raises(ValueError, match="reserved for Runtime-owned obligations"):
        accept_goal_draft_proposal(
            state,
            draft,
            bootstrap,
            admitted_at="2026-08-20T00:00:00Z",
        )


def test_goal_draft_rejects_model_invented_process_output_as_a_target() -> None:
    user = ConversationFact(
        fact_id="fact:user:invented-process-output",
        kind=FactKind.USER_MESSAGE,
        content={"text": "把 greet 的标点修好，然后运行现有测试确认。"},
    )
    state = ConversationState(
        conversation_id="conversation:invented-process-output",
        facts=(user,),
    )
    bootstrap = GoalBootstrap(
        source_fact_id=user.fact_id,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        authority_snapshot="authority:v1:" + "d" * 64,
    )
    draft = GoalDraftProposal(
        correlation_id="proposal:invented-process-output",
        user_outcome="修复 greet 并运行测试",
        beneficiary="owner",
        targets=("greet.py", "test-results.txt"),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                criterion_id="criterion:greet",
                description="greet.py 已修复",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path="greet.py",
            ),
            ProposedCriterion(
                criterion_id="criterion:invented-test-output",
                description="测试输出文件存在",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path="test-results.txt",
            ),
        ),
        requires_local_process=False,
    )

    with pytest.raises(ValueError, match="invented process output"):
        accept_goal_draft_proposal(
            state,
            draft,
            bootstrap,
            admitted_at="2026-08-20T00:00:00Z",
        )


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


@pytest.mark.parametrize(
    ("criterion_id", "oracle_kind"),
    (
        (
            "criterion:required-public-web:runtime-owned",
            EvidenceOracleKind.WEB_SOURCE_RECEIPT,
        ),
        (
            "criterion:required-local-process:runtime-owned",
            EvidenceOracleKind.TOOL_RECEIPT,
        ),
    ),
)
def test_goal_delta_cannot_drop_pending_runtime_owned_obligation(
    criterion_id: str,
    oracle_kind: EvidenceOracleKind,
) -> None:
    old_file = ProposedCriterion(
        criterion_id="criterion:old-file",
        description="old report exists",
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        artifact_path="reports/final.md",
    )
    obligation = ProposedCriterion(
        criterion_id=criterion_id,
        description="Runtime-owned mandatory obligation",
        oracle_kind=oracle_kind,
    )
    state = ConversationState(
        conversation_id="conversation:runtime-obligation-correction",
        goal=_goal(
            proposed_criteria=(old_file, obligation),
            admitted_criteria=(),
        ),
    )
    replacement = ProposedCriterion(
        criterion_id="criterion:new-file",
        description="new report exists",
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        artifact_path="reports/new.md",
    )

    updated = apply_goal_delta(
        state,
        GoalDelta(
            goal_id="goal:1",
            expected_revision=1,
            reason="write reports/new.md instead; keep every other requirement",
            updates={
                "targets": ["reports/new.md"],
                "proposed_criteria": [
                    {
                        "criterion_id": replacement.criterion_id,
                        "description": replacement.description,
                        "oracle_kind": replacement.oracle_kind.value,
                        "artifact_path": replacement.artifact_path,
                    }
                ],
            },
        ),
    )

    assert updated.goal is not None
    assert criterion_id in {
        item.criterion_id for item in updated.goal.proposed_criteria
    }


@pytest.mark.parametrize(
    "criterion_id",
    (
        "criterion:required-public-web:runtime-owned",
        "criterion:required-local-process:runtime-owned",
    ),
)
def test_goal_delta_cannot_shadow_runtime_obligation_id_with_another_oracle(
    criterion_id: str,
) -> None:
    obligation = ProposedCriterion(
        criterion_id=criterion_id,
        description="Runtime-owned mandatory obligation",
        oracle_kind=(
            EvidenceOracleKind.WEB_SOURCE_RECEIPT
            if "public-web" in criterion_id
            else EvidenceOracleKind.TOOL_RECEIPT
        ),
    )
    state = ConversationState(
        conversation_id="conversation:runtime-obligation-shadow",
        goal=_goal(proposed_criteria=(obligation,), admitted_criteria=()),
    )

    with pytest.raises(ValueError, match="reserved for Runtime-owned obligations"):
        apply_goal_delta(
            state,
            GoalDelta(
                goal_id="goal:1",
                expected_revision=1,
                reason="replace the target but keep every other requirement",
                updates={
                    "targets": ["reports/new.md"],
                    "proposed_criteria": [
                        {
                            "criterion_id": criterion_id,
                            "description": "shadow Runtime authority as a file",
                            "oracle_kind": EvidenceOracleKind.FILESYSTEM_DIGEST.value,
                            "artifact_path": "reports/new.md",
                        }
                    ],
                },
            ),
        )


@pytest.mark.parametrize(
    ("correction_text", "oracle_kind", "criterion_prefix"),
    (
        (
            "另外运行 ./check-report。",
            EvidenceOracleKind.TOOL_RECEIPT,
            "criterion:required-local-process:",
        ),
        (
            "另外结合当前公开 Web 资料核对结果。",
            EvidenceOracleKind.WEB_SOURCE_RECEIPT,
            "criterion:required-public-web:",
        ),
    ),
)
def test_user_correction_adds_runtime_obligation_when_model_omits_it(
    correction_text: str,
    oracle_kind: EvidenceOracleKind,
    criterion_prefix: str,
) -> None:
    correction = ConversationFact(
        fact_id="fact:user:2",
        kind=FactKind.USER_MESSAGE,
        content={"text": correction_text, "control": "goal_correction"},
    )
    goal = _goal(
        proposed_criteria=(
            ProposedCriterion(
                "criterion:file",
                "reports/final.md contains the requested result",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path="reports/final.md",
            ),
        ),
    )
    state = ConversationState(
        conversation_id="conversation:correction-lower-bound",
        facts=(
            ConversationFact(
                fact_id="fact:user:1",
                kind=FactKind.USER_MESSAGE,
                content={"text": "write reports/final.md"},
            ),
            correction,
        ),
        goal=goal,
    )
    updated = accept_goal_delta_proposal(
        state,
        GoalDeltaProposal(
            correlation_id=f"delta-{oracle_kind.value}",
            delta=GoalDelta(
                goal_id=state.goal.goal_id,
                expected_revision=state.goal.revision,
                reason="apply the user's additional requirement",
                updates={"targets": list(state.goal.targets)},
            ),
        ),
    )

    assert updated.goal is not None
    obligations = tuple(
        item
        for item in updated.goal.proposed_criteria
        if item.oracle_kind is oracle_kind
    )
    assert len(obligations) == 1
    assert obligations[0].criterion_id.startswith(criterion_prefix)
    assert correction.fact_id in updated.goal.created_from_fact_ids


@pytest.mark.parametrize(
    "invented_oracle",
    (
        EvidenceOracleKind.WEB_SOURCE_RECEIPT,
        EvidenceOracleKind.TOOL_RECEIPT,
    ),
)
def test_goal_delta_cannot_invent_effect_obligation_absent_from_correction(
    invented_oracle: EvidenceOracleKind,
) -> None:
    correction = ConversationFact(
        fact_id="fact:user:correction-without-effect",
        kind=FactKind.USER_MESSAGE,
        content={
            "text": "把标题改成新版，其他要求不变。",
            "control": "goal_correction",
        },
    )
    state = ConversationState(
        conversation_id="conversation:correction-without-effect",
        facts=(correction,),
        goal=_goal(
            proposed_criteria=(
                ProposedCriterion(
                    "criterion:file",
                    "reports/final.md contains the requested result",
                    oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                    artifact_path="reports/final.md",
                ),
            ),
            admitted_criteria=(),
        ),
    )
    updated = accept_goal_delta_proposal(
        state,
        GoalDeltaProposal(
            correlation_id=f"delta-invented-{invented_oracle.value}",
            delta=GoalDelta(
                goal_id=state.goal.goal_id,
                expected_revision=state.goal.revision,
                reason="apply the requested title correction",
                updates={
                    "assumptions": ["use the revised title"],
                    "proposed_criteria": [
                        {
                            "criterion_id": "criterion:file",
                            "description": "reports/final.md contains the requested result",
                            "oracle_kind": EvidenceOracleKind.FILESYSTEM_DIGEST.value,
                            "artifact_path": "reports/final.md",
                        },
                        {
                            "criterion_id": "criterion:model-invented-effect",
                            "description": "an effect the user did not request",
                            "oracle_kind": invented_oracle.value,
                            "artifact_path": "",
                        },
                    ],
                },
            ),
        ),
    )

    assert updated.goal is not None
    assert invented_oracle not in {
        item.oracle_kind for item in updated.goal.proposed_criteria
    }


@pytest.mark.parametrize(
    "correction_text",
    (
        "How do I run the project tests?",
        "What command runs the tests?",
        "如何运行项目测试？",
        "怎么执行这个校验器？",
    ),
)
def test_explanatory_process_question_does_not_expand_goal_authority(
    correction_text: str,
) -> None:
    correction = ConversationFact(
        fact_id="fact:user:process-question",
        kind=FactKind.USER_MESSAGE,
        content={"text": correction_text, "control": "goal_correction"},
    )
    state = ConversationState(
        conversation_id="conversation:process-question",
        facts=(correction,),
        goal=_goal(
            proposed_criteria=(
                ProposedCriterion(
                    "criterion:file",
                    "reports/final.md contains the requested result",
                    oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                    artifact_path="reports/final.md",
                ),
            ),
            admitted_criteria=(),
        ),
    )
    updated = accept_goal_delta_proposal(
        state,
        GoalDeltaProposal(
            correlation_id="delta-process-question",
            delta=GoalDelta(
                goal_id=state.goal.goal_id,
                expected_revision=state.goal.revision,
                reason="answer the user's explanatory question",
                updates={"assumptions": ["the user asked for an explanation"]},
            ),
        ),
    )

    assert updated.goal is not None
    assert EvidenceOracleKind.TOOL_RECEIPT not in {
        item.oracle_kind for item in updated.goal.proposed_criteria
    }


@pytest.mark.parametrize(
    "correction_text",
    (
        "不要运行测试，其他要求不变。",
        "不要联网搜索公开资料，其他要求不变。",
        "Do not use latest version information; use bundled docs.",
        "Never run ./check-report; keep the existing file requirement.",
    ),
)
def test_negative_correction_does_not_add_runtime_obligation(
    correction_text: str,
) -> None:
    correction = ConversationFact(
        fact_id="fact:user:negative-correction",
        kind=FactKind.USER_MESSAGE,
        content={"text": correction_text, "control": "goal_correction"},
    )
    state = ConversationState(
        conversation_id="conversation:negative-correction",
        facts=(correction,),
        goal=_goal(
            proposed_criteria=(
                ProposedCriterion(
                    "criterion:file",
                    "reports/final.md contains the requested result",
                    oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                    artifact_path="reports/final.md",
                ),
            ),
        ),
    )
    proposal = GoalDeltaProposal(
        correlation_id="delta-negative-correction",
        delta=GoalDelta(
            goal_id=state.goal.goal_id,
            expected_revision=state.goal.revision,
            reason="the user's prohibition does not change the existing Goal",
            updates={"targets": list(state.goal.targets)},
        ),
    )

    assert AgentRuntime._goal_delta_is_noop(state, proposal)


@pytest.mark.parametrize(
    "correction_text",
    (
        "另外运行 ./check-report。",
        "另外结合当前公开 Web 资料核对结果。",
    ),
)
def test_runtime_obligation_makes_empty_goal_delta_non_noop(
    correction_text: str,
) -> None:
    correction = ConversationFact(
        fact_id="fact:user:positive-correction",
        kind=FactKind.USER_MESSAGE,
        content={"text": correction_text, "control": "goal_correction"},
    )
    state = ConversationState(
        conversation_id="conversation:positive-correction",
        facts=(correction,),
        goal=_goal(
            proposed_criteria=(
                ProposedCriterion(
                    "criterion:file",
                    "reports/final.md contains the requested result",
                    oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                    artifact_path="reports/final.md",
                ),
            ),
        ),
    )
    proposal = GoalDeltaProposal(
        correlation_id="delta-positive-correction",
        delta=GoalDelta(
            goal_id=state.goal.goal_id,
            expected_revision=state.goal.revision,
            reason="apply the user's additional requirement",
            updates={"targets": list(state.goal.targets)},
        ),
    )

    assert not AgentRuntime._goal_delta_is_noop(state, proposal)


def test_process_admission_never_survives_a_goal_correction() -> None:
    process_proposal = ProposedCriterion(
        criterion_id="criterion:required-local-process:old",
        description="the requested local validator exits successfully",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
    )
    process_admission = AdmittedCriterion(
        criterion_id=process_proposal.criterion_id,
        description=process_proposal.description,
        source_fact_id="fact:user:1",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate={"receipt_digest": "a" * 64},
        required_evidence_class="process_receipt",
        admission_digest="b" * 64,
    )
    state = ConversationState(
        conversation_id="conversation:process-admission-correction",
        goal=_goal(
            proposed_criteria=(process_proposal,),
            admitted_criteria=(process_admission,),
        ),
    )

    corrected = apply_goal_delta(
        state,
        GoalDelta(
            goal_id=state.goal.goal_id,
            expected_revision=state.goal.revision,
            reason="user added one assumption",
            updates={"assumptions": ["keep the workspace local"]},
        ),
    )

    assert corrected.goal is not None
    assert process_proposal in corrected.goal.proposed_criteria
    assert corrected.goal.admitted_criteria == ()


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
        DirectResponse(
            correlation_id="control:answer:1",
            text="这是一个直接回答。",
        ),
        ClarificationRequest(
            correlation_id="control:clarify:1",
            question="报告交付给谁？",
            boundary_code="beneficiary_missing",
            missing_fields=("beneficiary",),
            safe_assumptions=(),
        ),
        GoalDraftProposal(
            correlation_id="control:goal:1",
            user_outcome="生成一份可验证报告",
            beneficiary="用户",
            targets=("deliverables/report.md",),
            scope=("deliverables",),
            non_goals=(),
            assumptions=(),
            proposed_criteria=(ProposedCriterion("criterion:1", "报告存在"),),
            next_step="读取工作区资料",
        ),
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
    intent = ExecutingIntentRecord(
        "call:1",
        "intent:1",
        "idempotency:1",
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
    )
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
                "call:1",
                "intent:1",
                "idempotency:1",
                execution_authority=ExecutionAuthorityClass.IN_PROCESS,
            ),
            tool_calls=(call,),
        ),
    )
    with pytest.raises(ValueError, match="unknown effect"):
        verify_goal_completion(unsafe)


def test_014_contract_extensions_preserve_preexisting_positional_prefixes() -> None:
    state = ConversationState("conversation:legacy", 5)
    assert state.revision == 5
    assert state.workspace_binding is None

    request = ApprovalRequest(
        "request:legacy",
        "run:legacy",
        "call:legacy",
        "binding:legacy",
        "preview",
        "write_file",
        7,
        "arguments:digest",
        "policy:v1",
        "high",
        "write",
        "target:digest",
        "precondition:digest",
        "new-content:digest",
    )
    assert request.arguments_digest == "arguments:digest"
    assert request.approval_basis_revision is None

    context = ToolPrepareContext(
        "conversation:legacy",
        "run:legacy",
        3,
        "goal:legacy",
        1,
        "workspace:legacy",
    )
    assert context.goal_id == "goal:legacy"
    assert context.approval_basis_revision == 3

    intent = ExecutionIntent(
        "call:legacy",
        "read_file",
        "read-file-v1",
        {"path": "notes.md"},
        "a" * 64,
        "b" * 64,
        "conversation:legacy:run:legacy:call:legacy",
        "policy:v1",
        "conversation:legacy",
        "run:legacy",
        SideEffectClass.READ_ONLY,
        {"stable": True},
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
    )
    assert intent.safety_binding == {"stable": True}
    assert intent.egress is EgressClass.NONE
