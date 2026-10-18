from dataclasses import FrozenInstanceError, asdict, replace

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
    InvocationOrigin,
    ModelResponse,
    ModelToolCall,
    PauseGoal,
    ProposedCriterion,
    ProviderContinuationV1,
    ProviderDescriptor,
    RecoveryRequest,
    RequirementCoverage,
    ResumeGoal,
    SelectGoal,
    SideEffectClass,
    ToolCall,
    ToolPrepareContext,
    canonical_action_digest,
    canonical_json_digest,
    model_response_from_payload,
    model_response_payload,
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


def test_goal_draft_model_response_round_trips_typed_evidence_oracles() -> None:
    response = ModelResponse(
        (),
        control=GoalDraftProposal(
            correlation_id="draft:round-trip",
            user_outcome="Run the bounded command.",
            beneficiary="owner",
            targets=("workspace",),
            scope=("one occurrence",),
            non_goals=(),
            assumptions=(),
            proposed_criteria=(
                ProposedCriterion(
                    criterion_id="criterion:receipt",
                    description="receipt exists",
                    oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
                ),
            ),
            next_step="run the command",
            requires_local_process=True,
        ),
    )

    restored = model_response_from_payload(model_response_payload(response))

    assert restored == response


def test_completion_claim_coverage_round_trips_and_rejects_non_string_ids() -> None:
    """R2-A：持久化 ModelResponse 的 coverage 逐元素校验。

    合法 coverage roundtrip 保真；``source_fact_ids``/``criterion_ids`` 混入
    非字符串元素时必须拒绝，不能构造出携带畸形 ID 的 claim。
    """
    import copy

    claim = CompletionClaim(
        correlation_id="claim:rt",
        goal_id="goal:1",
        goal_revision=1,
        criterion_evidence_refs=("evid-1",),
        requirement_coverage=(
            RequirementCoverage(
                requirement_id="requirement:report",
                requirement="the exact report is written",
                source_fact_ids=("fact:user:1",),
                status="satisfied",
                criterion_ids=("criterion:report-exists",),
            ),
        ),
    )
    payload = model_response_payload(ModelResponse((), control=claim))
    restored = model_response_from_payload(payload)
    assert isinstance(restored.control, CompletionClaim)
    assert restored.control == claim

    for key in ("source_fact_ids", "criterion_ids"):
        bad = copy.deepcopy(payload)
        bad["control"]["payload"]["requirement_coverage"][0][key] = [123]
        with pytest.raises(ValueError):
            model_response_from_payload(bad)


def test_provider_continuation_round_trips_without_entering_visible_blocks() -> None:
    continuation = ProviderContinuationV1.create(
        provider_identity_digest="a" * 64,
        opaque_payload="private reasoning",
    )
    response = ModelResponse(
        (ModelToolCall("call-1", "read_file", {"path": "README.md"}),),
        provider_continuation=continuation,
    )

    restored = model_response_from_payload(model_response_payload(response))

    assert restored == response
    assert restored.blocks == response.blocks
    assert "private reasoning" not in repr(restored)


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


def test_goal_draft_derives_semantic_validation_obligation_from_authoritative_user_fact() -> None:
    user = ConversationFact(
        fact_id="fact:user:semantic-validation",
        kind=FactKind.USER_MESSAGE,
        content={"text": "Fix the bug and make all tests pass."},
    )
    state = ConversationState(
        conversation_id="conversation:semantic-validation",
        facts=(user,),
    )
    bootstrap = GoalBootstrap(
        source_fact_id=user.fact_id,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        authority_snapshot="authority:v1:" + "d" * 64,
    )
    draft = GoalDraftProposal(
        correlation_id="proposal:semantic-validation",
        user_outcome="Fix the bug with passing tests",
        beneficiary="owner",
        targets=("src/bug.py",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                criterion_id="criterion:fixed-source",
                description="the corrected source is present",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path="src/bug.py",
            ),
        ),
        requires_local_process=True,
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
    assert accepted.goal.authority_snapshot == bootstrap.authority_snapshot


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


# R3 冻结输入表：直接发给产品的完整 user text（WORK-PACKAGES R3 节逐字）。
# 期望三态：True=必须建立 process 义务；False=禁止（不得建立义务）；
# None=未表态（模型 flag 也不能单独制造义务）。
_R3_FROZEN_INPUTS = (
    ("明确执行", "运行 pytest -q", True),
    ("等义连接", "修复功能，运行 pytest -q", True),
    ("等义连接", "修复功能并运行 pytest -q", True),
    ("等义连接", "修好后运行 pytest -q", True),
    ("分步", "先修复功能，然后执行 pytest -q", True),
    ("英文对照", "Fix the bug and run pytest -q", True),
    ("显式脚本", "运行 ./check-result", True),
    ("禁止", "不要运行测试，只修改 app.py", False),
    ("后续禁止", "运行测试。不要运行任何程序，只修改 app.py。", False),
    ("只求解释", "如何运行 pytest -q？", None),
    (
        "要求写例句",
        "只写 README，内容包含这句话：运行 pytest -q。不要执行它。",
        False,
    ),
    ("无运行要求", "只修改 app.py 中的拼写错误", None),
)


@pytest.mark.parametrize(
    ("label", "user_text", "expected"),
    _R3_FROZEN_INPUTS,
    ids=[item[0] + ":" + item[1][:18] for item in _R3_FROZEN_INPUTS],
)
@pytest.mark.parametrize("model_flag", (True, False))
def test_r3_explicit_requirement_survives_connective_variants(
    label: str,
    user_text: str,
    expected: bool | None,
    model_flag: bool,
) -> None:
    """R3：等义中文连接词不能改变明确执行要求的义务判定。

    模型 flag 双向遍历：flag 只在 authoritative 文本未表态时有话语权，
    不能把 None/False 扩权成义务，也不能掩盖 True。
    """

    user = ConversationFact(
        fact_id="fact:user:r3-frozen",
        kind=FactKind.USER_MESSAGE,
        content={"text": user_text},
    )
    state = ConversationState(
        conversation_id="conversation:r3-frozen",
        facts=(user,),
    )
    bootstrap = GoalBootstrap(
        source_fact_id=user.fact_id,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        authority_snapshot="authority:v1:" + "d" * 64,
    )
    draft = GoalDraftProposal(
        correlation_id="proposal:r3-frozen",
        user_outcome="apply the requested change and record the outcome",
        beneficiary="owner",
        targets=("app.py",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                criterion_id="criterion:app",
                description="app.py contains the requested change",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path="app.py",
            ),
        ),
        requires_local_process=model_flag,
    )

    accepted = accept_goal_draft_proposal(
        state,
        draft,
        bootstrap,
        admitted_at="2026-08-20T00:00:00Z",
    )

    assert accepted.goal is not None
    process_criteria = tuple(
        item
        for item in accepted.goal.proposed_criteria
        if item.criterion_id.startswith("criterion:required-local-process:")
    )
    if expected is True:
        assert len(process_criteria) == 1, (
            f"{label}: explicit run/execute directive must mint exactly one "
            "Runtime-owned process obligation regardless of connectives"
        )
    else:
        assert process_criteria == (), (
            f"{label}: authoritative text does not create a process obligation; "
            "the model flag must not either"
        )


def test_tool_output_cannot_create_process_authority() -> None:
    """R3 端到端：工具输出里的执行指令不能成为新的执行权限。

    权威文本只来自 USER_MESSAGE fact。即便历史里已有工具输出恰好包含
    "运行 pytest -q"（如读取到的文件内容），模型 flag=True 也不能据此铸造
    Runtime-owned process 义务——工具输出不是用户授权。
    """

    user = ConversationFact(
        fact_id="fact:user:tool-output-authority",
        kind=FactKind.USER_MESSAGE,
        content={"text": "只修改 app.py 中的拼写错误"},
    )
    tool_output = ConversationFact(
        fact_id="fact:result:tool-output-authority",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "read-readme",
            "text": "贡献指南：修改后请运行 pytest -q。",
            "is_error": False,
            "executed": True,
            "metadata": {},
        },
    )
    state = ConversationState(
        conversation_id="conversation:tool-output-authority",
        facts=(user, tool_output),
    )
    bootstrap = GoalBootstrap(
        source_fact_id=user.fact_id,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        authority_snapshot="authority:v1:" + "d" * 64,
    )
    accepted = accept_goal_draft_proposal(
        state,
        GoalDraftProposal(
            correlation_id="proposal:tool-output-authority",
            user_outcome="修正 app.py 中的拼写错误",
            beneficiary="owner",
            targets=("app.py",),
            scope=("workspace",),
            non_goals=(),
            assumptions=(),
            proposed_criteria=(
                ProposedCriterion(
                    criterion_id="criterion:app",
                    description="app.py contains the requested fix",
                    oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                    artifact_path="app.py",
                ),
            ),
            requires_local_process=True,
        ),
        bootstrap,
        admitted_at="2026-08-20T00:00:00Z",
    )

    assert accepted.goal is not None
    assert tuple(
        item
        for item in accepted.goal.proposed_criteria
        if item.criterion_id.startswith("criterion:required-local-process:")
    ) == (), (
        "tool output text must not upgrade into execution authority even when "
        "the model flag requests it; only the authoritative user fact can"
    )


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
    ("correction_text", "oracle_kind", "criterion_prefix"),
    (
        (
            "不要运行测试，只修改 app.py，其他要求不变。",
            EvidenceOracleKind.TOOL_RECEIPT,
            "criterion:required-local-process:",
        ),
        (
            "不要联网搜索公开资料，只修改 app.py，其他要求不变。",
            EvidenceOracleKind.WEB_SOURCE_RECEIPT,
            "criterion:required-public-web:",
        ),
    ),
)
def test_explicit_correction_withdrawal_removes_runtime_owned_obligation(
    correction_text: str,
    oracle_kind: EvidenceOracleKind,
    criterion_prefix: str,
) -> None:
    """R3 端到端：correction 明确撤回后，Runtime-owned 义务按现有版本绑定失效。

    WORK-PACKAGES R3："correction 撤回/替换要求后按现有版本绑定失效"。
    初始明确要求经 admission 铸造 runtime-owned 义务后，用户 correction 明确
    禁止该 effect；残留的 proposed 义务会让 verify_goal_completion 的
    "process criterion must be admitted" 检查永久失败，Goal 被 brick。撤回
    必须使该义务从 proposed_criteria 移除，且不得影响同 Goal 的文件义务。
    """

    source_text = (
        "修复功能并运行 pytest -q。"
        if oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
        else "修复功能并结合当前公开 Web 资料核对结果。"
    )
    user = ConversationFact(
        fact_id="fact:user:1",
        kind=FactKind.USER_MESSAGE,
        content={"text": source_text},
    )
    state = ConversationState(
        conversation_id="conversation:withdrawal",
        facts=(user,),
    )
    bootstrap = GoalBootstrap(
        source_fact_id=user.fact_id,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        authority_snapshot="authority:v1:" + "d" * 64,
    )
    draft = GoalDraftProposal(
        correlation_id="proposal:withdrawal",
        user_outcome="修复功能并验证结果",
        beneficiary="owner",
        targets=("app.py",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                criterion_id="criterion:app",
                description="app.py contains the requested fix",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path="app.py",
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
    minted = tuple(
        item
        for item in accepted.goal.proposed_criteria
        if item.criterion_id.startswith(criterion_prefix)
    )
    assert len(minted) == 1, "admission must mint the runtime-owned obligation"

    correction = ConversationFact(
        fact_id="fact:user:2",
        kind=FactKind.USER_MESSAGE,
        content={"text": correction_text, "control": "goal_correction"},
    )
    corrected_state = replace(accepted, facts=(*accepted.facts, correction))
    updated = accept_goal_delta_proposal(
        corrected_state,
        GoalDeltaProposal(
            correlation_id="delta:withdrawal",
            delta=GoalDelta(
                goal_id=accepted.goal.goal_id,
                expected_revision=accepted.goal.revision,
                reason="apply the user's explicit withdrawal",
                updates={"assumptions": ["user withdrew the effect requirement"]},
            ),
        ),
    )

    assert updated.goal is not None
    remaining = tuple(
        item
        for item in updated.goal.proposed_criteria
        if item.criterion_id.startswith(criterion_prefix)
    )
    assert remaining == (), (
        "an explicit correction that prohibits the effect must retire the "
        "runtime-owned obligation; otherwise verify_goal_completion's "
        "'must be admitted' check bricks the Goal forever"
    )
    assert any(
        item.criterion_id == "criterion:app"
        for item in updated.goal.proposed_criteria
    ), "withdrawal must not touch unrelated artifact criteria"
    assert correction.fact_id in updated.goal.created_from_fact_ids


@pytest.mark.parametrize(
    ("correction_text", "oracle_kind", "criterion_prefix"),
    (
        (
            "把标题改成新版，其他要求不变。",
            EvidenceOracleKind.TOOL_RECEIPT,
            "criterion:required-local-process:",
        ),
        (
            "把标题改成新版，其他要求不变。",
            EvidenceOracleKind.WEB_SOURCE_RECEIPT,
            "criterion:required-public-web:",
        ),
    ),
)
def test_silent_correction_keeps_runtime_owned_obligation(
    correction_text: str,
    oracle_kind: EvidenceOracleKind,
    criterion_prefix: str,
) -> None:
    """对照：correction 未表态（None）时不得撤回既有 Runtime 义务。"""

    source_text = (
        "修复功能并运行 pytest -q。"
        if oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
        else "修复功能并结合当前公开 Web 资料核对结果。"
    )
    user = ConversationFact(
        fact_id="fact:user:1",
        kind=FactKind.USER_MESSAGE,
        content={"text": source_text},
    )
    state = ConversationState(
        conversation_id="conversation:silent-correction",
        facts=(user,),
    )
    bootstrap = GoalBootstrap(
        source_fact_id=user.fact_id,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        authority_snapshot="authority:v1:" + "d" * 64,
    )
    draft = GoalDraftProposal(
        correlation_id="proposal:silent-correction",
        user_outcome="修复功能并验证结果",
        beneficiary="owner",
        targets=("app.py",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion(
                criterion_id="criterion:app",
                description="app.py contains the requested fix",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path="app.py",
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
    correction = ConversationFact(
        fact_id="fact:user:2",
        kind=FactKind.USER_MESSAGE,
        content={"text": correction_text, "control": "goal_correction"},
    )
    corrected_state = replace(accepted, facts=(*accepted.facts, correction))
    updated = accept_goal_delta_proposal(
        corrected_state,
        GoalDeltaProposal(
            correlation_id="delta:silent-correction",
            delta=GoalDelta(
                goal_id=accepted.goal.goal_id,
                expected_revision=accepted.goal.revision,
                reason="apply the artifact-only correction",
                updates={"assumptions": ["title revised"]},
            ),
        ),
    )

    assert updated.goal is not None
    remaining = tuple(
        item
        for item in updated.goal.proposed_criteria
        if item.criterion_id.startswith(criterion_prefix)
    )
    assert len(remaining) == 1, (
        "a correction that does not mention the effect must not silently drop "
        "the authoritative runtime-owned obligation"
    )


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
        issued_at="2026-09-04T00:00:00Z",
        expires_at="2026-09-04T01:00:00Z",
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
            issued_at="2026-09-04T00:00:00Z",
            expires_at="2026-09-04T01:00:00Z",
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
            issued_at=binding.issued_at,
            expires_at=binding.expires_at,
            max_uses=binding.max_uses,
            uses_consumed=binding.uses_consumed,
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
        requirement_coverage=(
            RequirementCoverage(
                requirement_id="requirement:report",
                requirement="报告文件存在且内容匹配",
                source_fact_ids=("fact:user:1",),
                status="satisfied",
                criterion_ids=("criterion:report-exists",),
            ),
        ),
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


def test_goal_completion_requires_browser_and_managed_server_cleanup() -> None:
    evidence = _evidence()
    claim = CompletionClaim(
        correlation_id="control:claim:resources",
        goal_id="goal:1",
        goal_revision=1,
        criterion_evidence_refs=(evidence.evidence_id,),
        requirement_coverage=(
            RequirementCoverage(
                requirement_id="requirement:report",
                requirement="报告文件存在且内容匹配",
                source_fact_ids=("fact:user:1",),
                status="satisfied",
                criterion_ids=("criterion:report-exists",),
            ),
        ),
    )

    def result(fact_id: str, text: str, metadata: dict) -> ConversationFact:
        return ConversationFact(
            fact_id=fact_id,
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": fact_id,
                "text": text,
                "is_error": False,
                "executed": True,
                "metadata": metadata,
            },
        )

    opened = ConversationState(
        conversation_id="conversation:1",
        goal=_goal(status=GoalStatus.EXECUTING),
        evidence_records=(evidence,),
        completion_claim=claim,
        facts=(
            result(
                "open",
                '{"session_ref":"session-1"}',
                {"browser_result_kind": "browser_open", "session_ref": "session-1"},
            ),
            result(
                "start",
                '{"resource_ref":"managed-web-1","status":"ready"}',
                {"tool_name": "managed_web_start"},
            ),
        ),
    )
    with pytest.raises(ValueError, match="browser_close, managed_web_stop"):
        verify_goal_completion(opened)

    closed = replace(
        opened,
        facts=(
            *opened.facts,
            result(
                "close",
                '{"session_ref":"session-1","outcome":"cleaned"}',
                {
                    "browser_result_kind": "browser_close",
                    "session_ref": "session-1",
                    "cleanup_outcome": "cleaned",
                },
            ),
            result(
                "stop",
                '{"resource_ref":"managed-web-1","cleanup":"confirmed"}',
                {"tool_name": "managed_web_stop"},
            ),
        ),
    )
    assert verify_goal_completion(closed).goal.status is GoalStatus.VERIFIED_DONE


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
        InvocationOrigin.MODEL,
        {"stable": True},
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
    )
    assert intent.safety_binding == {"stable": True}
    assert intent.egress is EgressClass.NONE


# ---------------------------------------------------------------------------
# W1：authoritative_deliverable_file_paths 冻结判别表（2026-10-17 日用收口包）。
# 期望集 = 当前权威 USER_MESSAGE 原文里"直接正向要求的 workspace 相对文件
# 交付对象"下界。阅读输入、参照/禁止对象、疑问句、非路径关键词、危险路径、
# 非权威来源（TOOL_RESULT）一律不得进入交付约束。与显式 process 要求同型：
# 纯派生、逐 clause、按 fact 顺序做正/负更新。
# ---------------------------------------------------------------------------

W1_D04_TASK = (
    "完成 retry_app 的 bounded retry 行为：瞬态 RuntimeError 失败需要重试，新的"
    "公开参数名是 max_retries，命令行适配器 retry_app/cli.py 必须使用同一个值；"
    "负数限制无效，一次操作的执行次数上限是 1 + max_retries。同时保留旧的"
    " retry_count 关键字与 CLI 选项作为别名；旧名与新名同时提供时必须拒绝这个"
    "有歧义的请求。"
)
W1_RENAMED_TASK = (
    "为 metrics_app 新增阈值处理：在 metrics_app/threshold.py 实现 "
    "clamp(value, *, span)，把 value 限制在 [0, span] 区间内，越界时取最近的"
    "边界；span 必须是正数，非正数直接报错。metrics_app/report.py 的 "
    "format_row 也要改为对每个数值调用 clamp，输出 row=<序号>:<限幅值> 并用"
    "空格连接。"
)
W1_CONFIRM_TASK = (
    "在 retry_app/service.py 实现有界重试：瞬态 RuntimeError 失败需要重试，"
    "公开参数名是 max_retries，负数限制无效，一次操作的执行次数上限是 "
    "1 + max_retries；同时保留旧的 retry_count 关键字作为别名，旧名与新名"
    "同时提供时必须拒绝这个有歧义的请求。"
)

_W1_FROZEN_INPUTS = (
    (
        "D04 原文只点名 CLI",
        W1_D04_TASK,
        frozenset({"retry_app/cli.py"}),
    ),
    (
        "改名同构双交付",
        W1_RENAMED_TASK,
        frozenset({"metrics_app/threshold.py", "metrics_app/report.py"}),
    ),
    (
        "双交付中文",
        "更新 app/worker.py；app/command.py 必须使用相同配置",
        frozenset({"app/worker.py", "app/command.py"}),
    ),
    (
        "双交付英文",
        "Update app/worker.py; app/command.py must use the same configuration.",
        frozenset({"app/worker.py", "app/command.py"}),
    ),
    (
        "阅读输入不算交付",
        "阅读 SPEC.md，修改 app/worker.py",
        frozenset({"app/worker.py"}),
    ),
    (
        "参照与禁止对象不强制修改",
        "参考 docs/example.py，不要修改它；更新 app/worker.py",
        frozenset({"app/worker.py"}),
    ),
    (
        "R3 原文 process 路径不算文件交付",
        "创建 notes.txt 并 运行 ./check.sh",
        frozenset({"notes.txt"}),
    ),
    (
        "疑问句不产生交付要求",
        "如何修改 app/config.py？",
        frozenset(),
    ),
    (
        "非路径关键词不算交付对象",
        "把 max_retries 的默认值改为 3",
        frozenset(),
    ),
    (
        "纯散文无显式交付对象",
        "把重试逻辑改成有界的",
        frozenset(),
    ),
    (
        "句内明确禁止对象",
        "更新 app/worker.py，不要改动 app/legacy.py",
        frozenset({"app/worker.py"}),
    ),
    (
        "已正确目标的单文件任务",
        W1_CONFIRM_TASK,
        frozenset({"retry_app/service.py"}),
    ),
    (
        "参照规格实现不把规格当交付对象",
        "实现 SPEC.md 中要求的笔记功能",
        frozenset(),
    ),
    (
        "按说明实现不把规格当交付对象",
        "按 SPEC.md 的说明实现笔记功能：创建 notes/idea.md，记录当天想法。",
        frozenset({"notes/idea.md"}),
    ),
    (
        "绝对路径与父目录逃逸拒绝",
        "更新 /etc/hosts 和 ../outside.py",
        frozenset(),
    ),
)


def _deliverable_extractor():
    # 局部导入：Red 阶段只让新测试失败，不让整个模块 collection 报错。
    from agent.runtime.state import authoritative_deliverable_file_paths

    return authoritative_deliverable_file_paths


def _w1_state(
    fact_texts: tuple[tuple[str, str, dict], ...],
    source_ids: tuple[str, ...],
) -> ConversationState:
    """按 (fact_id, text, extra_content) 构造权威来源绑定的 W1 状态。"""

    facts = tuple(
        ConversationFact(
            fact_id=fact_id,
            kind=FactKind.USER_MESSAGE,
            content={"text": text, **extra},
        )
        for fact_id, text, extra in fact_texts
    )
    return replace(
        ConversationState.new("conversation:w1-deliverable"),
        goal=replace(
            _goal(),
            created_from_fact_ids=source_ids,
        ),
        facts=facts,
    )


@pytest.mark.parametrize(
    ("label", "user_text", "expected"),
    _W1_FROZEN_INPUTS,
    ids=[item[0] for item in _W1_FROZEN_INPUTS],
)
def test_w1_deliverable_lower_bound_recognizes_direct_file_requirements(
    label: str,
    user_text: str,
    expected: frozenset[str],
) -> None:
    """W1.4 矩阵：明确文件交付下界只认直接正向要求，拒绝扩大解释。"""

    state = _w1_state(
        (("fact:user:w1", user_text, {}),),
        ("fact:user:w1",),
    )

    assert _deliverable_extractor()(state) == expected, label


# ---------------------------------------------------------------------------
# 2026-10-18 CLI 首发阻断包 A（审计 F1/F2）：交付对象来源分类的冻结矩阵。
# 既有 _W1_FROZEN_INPUTS 全部继续生效；本表只补发布包新增的有限语法行。
# ---------------------------------------------------------------------------

_RELEASE_A_FROZEN_INPUTS = (
    (
        "中文紧邻路径仍是交付对象",
        "修改app/config.py",
        frozenset({"app/config.py"}),
    ),
    (
        "行内反引号路径仍是交付对象",
        "修改 `app/config.py`",
        frozenset({"app/config.py"}),
    ),
    (
        "中文紧邻双交付下界",
        "命令行适配器retry_app/cli.py 必须使用同一个值",
        frozenset({"retry_app/cli.py"}),
    ),
    (
        "礼貌请求是交付要求",
        "Could you update app/config.py?",
        frozenset({"app/config.py"}),
    ),
    (
        "please 礼貌请求是交付要求",
        "Could you please update app/config.py?",
        frozenset({"app/config.py"}),
    ),
    (
        "would 礼貌请求是交付要求",
        "Would you update app/config.py?",
        frozenset({"app/config.py"}),
    ),
    (
        "would please 礼貌请求是交付要求",
        "Would you please update app/config.py?",
        frozenset({"app/config.py"}),
    ),
    (
        "解释型请求不产生义务",
        "Could you explain how to update app/config.py?",
        frozenset(),
    ),
    (
        "英文说明型疑问不产生义务",
        "How do I update app/config.py?",
        frozenset(),
    ),
    (
        "版本号不是交付文件",
        "Update Python to 3.12",
        frozenset(),
    ),
    (
        "数字版本目录不排除路径",
        "修改 app/v3.12/config.py",
        frozenset({"app/v3.12/config.py"}),
    ),
    (
        "requirements 规格指称不是交付对象",
        "Implement SPEC.md requirements",
        frozenset(),
    ),
    (
        "根据规格实现需求不是交付对象",
        "根据 SPEC.md 实现需求",
        frozenset(),
    ),
    (
        "直接修改优先于说明后缀",
        "修改 SPEC.md 的说明",
        frozenset({"SPEC.md"}),
    ),
    (
        "跨分句引文不产生义务",
        "解释“创建 app/example.py；修改 app/other.py”的含义，不要修改任何文件。",
        frozenset(),
    ),
    (
        "日志报告不产生义务",
        "日志显示：创建 app/old.py；请说明原因，不要修改文件。",
        frozenset(),
    ),
    (
        "日志范围跨分号继承",
        "日志显示：创建 app/old.py；修改 app/other.py；请说明原因",
        frozenset(),
    ),
    (
        "明确新请求终止日志范围",
        "日志显示：创建 app/old.py；请修改 app/live.py",
        frozenset({"app/live.py"}),
    ),
    (
        "阅读加修改只计修改对象",
        "阅读 SPEC.md，然后修改 app/config.py",
        frozenset({"app/config.py"}),
    ),
    (
        "根据说明修改只计修改对象",
        "根据 SPEC.md 的说明修改 app/config.py",
        frozenset({"app/config.py"}),
    ),
    (
        "围栏代码块示例不产生义务",
        "修改 app/live.py；下面代码块只是示例，勿执行：\n"
        "```text\n创建 app/demo.py\n修改 app/example.py\n```",
        frozenset({"app/live.py"}),
    ),
    (
        "绝对与逃逸路径不是交付对象",
        "修改 /tmp/out.py、../out.py 和 dir/../out.py",
        frozenset(),
    ),
    (
        "遍历续接不截取前缀",
        "修改 dir/out.py/../other.py",
        frozenset(),
    ),
    (
        "反斜线附尾不截取",
        "修改 dir/out.py\\x",
        frozenset(),
    ),
    (
        "Windows 盘符不截取",
        "修改 C:\\tmp\\out.py",
        frozenset(),
    ),
    (
        "URL 不截取",
        "修改 https://host/out.py",
        frozenset(),
    ),
    (
        "CJK 段内不截取后缀",
        "修改 /tmp/中文out.py",
        frozenset(),
    ),
    (
        "查询串不截取",
        "修改 app/config.py?x=1",
        frozenset(),
    ),
)


@pytest.mark.parametrize(
    ("label", "user_text", "expected"),
    _RELEASE_A_FROZEN_INPUTS,
    ids=[item[0] for item in _RELEASE_A_FROZEN_INPUTS],
)
def test_release_a_deliverable_source_classification(
    label: str,
    user_text: str,
    expected: frozenset[str],
) -> None:
    """发布包 A 矩阵：中文紧邻/礼貌请求计入下界；输入指称、引文、
    围栏示例、日志报告、版本号与非法 token 形状不产生或截取交付义务。"""

    state = _w1_state(
        (("fact:user:release-a", user_text, {}),),
        ("fact:user:release-a",),
    )

    assert _deliverable_extractor()(state) == expected, label


def test_w1_correction_adds_deliverable_without_clearing_others() -> None:
    """correction 新增对象则约束生效，且不清空其它既有交付对象。"""

    state = _w1_state(
        (
            ("fact:user:w1", "更新 app/worker.py", {}),
            (
                "fact:user:w1-fix",
                "另外还要创建 app/flags.py",
                {"control": "goal_correction"},
            ),
        ),
        ("fact:user:w1", "fact:user:w1-fix"),
    )

    assert _deliverable_extractor()(state) == frozenset(
        {"app/worker.py", "app/flags.py"}
    )


def test_w1_correction_withdrawal_updates_only_named_target() -> None:
    """明确撤回只移除被点名对象，其余交付对象保留。"""

    state = _w1_state(
        (
            (
                "fact:user:w1",
                "更新 app/worker.py；app/command.py 必须使用相同配置",
                {},
            ),
            (
                "fact:user:w1-fix",
                "不要修改 app/command.py，只修改 app/worker.py",
                {"control": "goal_correction"},
            ),
        ),
        ("fact:user:w1", "fact:user:w1-fix"),
    )

    assert _deliverable_extractor()(state) == frozenset({"app/worker.py"})


def test_w1_silent_correction_keeps_existing_deliverables() -> None:
    """沉默或仅改无关要求的 correction 不能清空既有交付对象。"""

    state = _w1_state(
        (
            (
                "fact:user:w1",
                "更新 app/worker.py；app/command.py 必须使用相同配置",
                {},
            ),
            (
                "fact:user:w1-fix",
                "界面文案换成中文",
                {"control": "goal_correction"},
            ),
        ),
        ("fact:user:w1", "fact:user:w1-fix"),
    )

    assert _deliverable_extractor()(state) == frozenset(
        {"app/worker.py", "app/command.py"}
    )


def test_w1_unconsumed_correction_does_not_apply_early() -> None:
    """未消费 correction（未进 created_from_fact_ids）不提前生效。"""

    state = _w1_state(
        (
            ("fact:user:w1", "更新 app/worker.py", {}),
            (
                "fact:user:w1-fix",
                "另外还要创建 app/flags.py",
                {"control": "goal_correction"},
            ),
        ),
        ("fact:user:w1",),
    )

    assert _deliverable_extractor()(state) == frozenset({"app/worker.py"})


def test_w1_withdraw_then_readd_restores_deliverable() -> None:
    """按 fact 顺序做正/负更新：撤回后再要求恢复交付对象。"""

    state = _w1_state(
        (
            ("fact:user:w1", "更新 app/worker.py", {}),
            (
                "fact:user:w1-fix-1",
                "不要更新 app/worker.py",
                {"control": "goal_correction"},
            ),
            (
                "fact:user:w1-fix-2",
                "还是要更新 app/worker.py",
                {"control": "goal_correction"},
            ),
        ),
        ("fact:user:w1", "fact:user:w1-fix-1", "fact:user:w1-fix-2"),
    )

    assert _deliverable_extractor()(state) == frozenset({"app/worker.py"})


def test_w1_tool_output_text_cannot_create_deliverable_requirement() -> None:
    """W1.4：TOOL_RESULT 里的“修改 app/other.py”不是用户交付要求。

    与 R3 的工具输出非权威边界同型：交付下界只从 created_from_fact_ids
    绑定的 USER_MESSAGE 原文派生，工具输出/日志引文不铸造义务。
    """

    user = ConversationFact(
        fact_id="fact:user:w1-tool-output",
        kind=FactKind.USER_MESSAGE,
        content={"text": "修复启动失败的问题"},
    )
    tool_output = ConversationFact(
        fact_id="fact:result:w1-tool-output",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "read-log",
            "text": "日志显示：修改 app/other.py 后即可恢复。",
            "is_error": False,
            "executed": True,
            "metadata": {},
        },
    )
    state = replace(
        ConversationState.new("conversation:w1-tool-output"),
        goal=replace(
            _goal(),
            created_from_fact_ids=("fact:user:w1-tool-output",),
        ),
        facts=(user, tool_output),
    )

    assert _deliverable_extractor()(state) == frozenset()
