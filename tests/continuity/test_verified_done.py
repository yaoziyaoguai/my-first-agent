from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRun,
    AdmittedCriterion,
    BlockedClaim,
    CompletionClaim,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    EvidenceOracleKind,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    FactKind,
    GoalBootstrap,
    GoalDelta,
    GoalDeltaProposal,
    GoalDraftProposal,
    GoalStatus,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    ProposedCriterion,
    RequirementCoverage,
    Resume,
    RunStatus,
    SubmitMessage,
    ToolCall,
    ToolPrepareContext,
    closed_evidence_id,
)
from agent.runtime.evidence import ClosedEvidenceRegistry, EvidenceVerificationError
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.state import (
    accept_goal_delta_proposal,
    accept_goal_draft_proposal,
    record_completion_claim,
    record_evidence,
    verify_goal_completion,
)
from agent.runtime.tools import KernelToolRuntime
from agent.tools.file_ops import build_file_tool_runtime
from tests.continuity.test_contracts import _goal
from tests.kernel.fakes import (
    RUNTIME_GOAL_ID,
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    goal_noop_response,
)

CONTENT = "verified report\n"
CONTENT_DIGEST = hashlib.sha256(CONTENT.encode()).hexdigest()
EVIDENCE_ID = "evidence:goal:1:1:criterion:report-exists"
# _runtime 的 SubmitMessage 被消费为 goal_correction，落为 action:1:user 权威
# fact；覆盖率门要求 claim 引用每条权威用户输入，因此两者都必须被覆盖。
RUNTIME_SOURCE_FACT_IDS = ("fact:user:1", "action:1:user")


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


def _claim(
    *,
    correlation_id: str = "claim-1",
    source_fact_ids: tuple[str, ...] = ("fact:user:1",),
) -> CompletionClaim:
    return CompletionClaim(
        correlation_id=correlation_id,
        goal_id="goal:1",
        goal_revision=1,
        criterion_evidence_refs=(EVIDENCE_ID,),
        requirement_coverage=(
            RequirementCoverage(
                requirement_id="requirement:report",
                requirement="the exact verified report is written",
                source_fact_ids=source_fact_ids,
                status="satisfied",
                criterion_ids=("criterion:report-exists",),
            ),
        ),
    )


def _runtime(state: ConversationState, *responses: ModelResponse):
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(
        goal_noop_response("verification-user-supplement"),
        *responses,
    )
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
        ModelResponse((ModelTextBlock("done"),)),
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "invalid_model_control"
    assert store.state.goal.status is GoalStatus.GOAL_READY
    assert store.state.evidence_records == ()


def test_deterministic_receipts_bound_to_all_mandatory_criteria_verify_goal() -> None:
    from tests.continuity.test_browser_authority import make_lease

    runtime, store, action = _runtime(
        replace(_state(), browser_leases=(make_lease(),)),
        ModelResponse((), control=_claim(source_fact_ids=RUNTIME_SOURCE_FACT_IDS)),
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    assert store.state.goal.status is GoalStatus.VERIFIED_DONE
    assert store.state.evidence_records[0].evidence_id == EVIDENCE_ID
    assert store.state.evidence_records[0].source_fact_ids == (
        "fact:calls:1",
        "fact:read-result:1",
    )
    assert store.state.browser_leases == ()


def test_completion_claim_receipt_digest_binds_requirement_coverage() -> None:
    """R2-A：claim receipt 的 payload_digest 必须绑定全部语义相关 coverage 字段。

    相同其他字段、不同 coverage 的两个 claim 不得共享同一 digest；coverage
    完全相同时 digest 与 correlation_id 无关（response 自身身份与 receipt
    payload 身份分别验证）。
    """

    base = _state()
    records = ClosedEvidenceRegistry().derive(
        base, _claim(), observed_at="2026-10-14T00:00:00Z"
    )
    with_evidence = record_evidence(base, records)

    first = record_completion_claim(with_evidence, _claim(correlation_id="claim-a"))
    control = record_completion_claim(with_evidence, _claim(correlation_id="claim-c"))
    rewritten = replace(
        _claim(correlation_id="claim-b"),
        requirement_coverage=(
            replace(
                _claim().requirement_coverage[0],
                requirement="every user requirement is satisfied",
            ),
        ),
    )
    second = record_completion_claim(with_evidence, rewritten)

    assert (
        first.control_receipts[-1].payload_digest
        == control.control_receipts[-1].payload_digest
    )
    assert (
        first.control_receipts[-1].payload_digest
        != second.control_receipts[-1].payload_digest
    )


def test_sentinel_claim_without_coverage_stays_empty_and_gate_rejects() -> None:
    """R2-B：bind_runtime_goal 不为缺失 coverage 代填"已满足"语义。

    RUNTIME_GOAL_ID 占位但 requirement_coverage 为空时，经 helper 后仍为空
    （只绑定动态身份/引用）；真实完成门必须拒绝，Goal 不得进入
    VERIFIED_DONE。
    """
    runtime, store, action = _runtime(
        _state(),
        ModelResponse(
            (),
            control=CompletionClaim(
                correlation_id="claim-empty-coverage",
                goal_id=RUNTIME_GOAL_ID,
                goal_revision=1,
                criterion_evidence_refs=(),
            ),
        ),
        ModelResponse((ModelTextBlock("cannot verify yet"),)),
    )

    runtime.run_turn(action, store.load())

    goal = store.state.goal
    assert goal is not None
    assert goal.status is not GoalStatus.VERIFIED_DONE
    claim = store.state.completion_claim
    assert claim is not None
    assert claim.goal_id == goal.goal_id, "identity binding still applies"
    assert claim.requirement_coverage == (), "helper must not fabricate coverage"


def test_read_back_alone_does_not_auto_complete_goal(tmp_path) -> None:
    """R2：read-back 产生闭合证据后，Runtime 不再自行合成复核，回到 model loop。

    修复前：最终 read-back 后 Runtime 自动合成 `runtime-completion:` claim 并
    直接 VERIFIED_DONE，模型无需逐项复核权威要求。R2 合同要求自动路径不得
    自行合成"已复核所有业务要求"——证据齐全后仍需模型显式提交带
    requirement_coverage 的 completion_claim。
    """

    workspace = tmp_path / "workspace"
    (workspace / "reports").mkdir(parents=True)
    (workspace / "reports" / "final.md").write_text(CONTENT, encoding="utf-8")
    seed = _state()
    state = replace(
        seed,
        facts=(seed.facts[0],),
        active_run=ActiveRun("run-auto-complete"),
    )
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(
        ModelResponse(
            (
                ModelToolCall(
                    "read-final",
                    "read_file",
                    {"path": "reports/final.md"},
                ),
            )
        )
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=10_000, output_reserve=200),
        ),
        tool_runtime=build_file_tool_runtime(workspace),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-auto-complete",
    )
    action = Resume(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is not RunStatus.COMPLETED
    assert store.state.goal is not None
    assert store.state.goal.status is not GoalStatus.VERIFIED_DONE
    assert store.state.completion_claim is None
    # 批次结束后确实回到了 model loop（而不是在批次边界自行收尾）。
    assert len(provider.calls) == 2


def test_read_back_then_explicit_coverage_claim_verifies_goal(tmp_path) -> None:
    """R2：证据齐全后，模型显式提交带 coverage 的 claim 仍能在有限步内完成。"""

    workspace = tmp_path / "workspace"
    (workspace / "reports").mkdir(parents=True)
    (workspace / "reports" / "final.md").write_text(CONTENT, encoding="utf-8")
    seed = _state()
    state = replace(
        seed,
        facts=(seed.facts[0],),
        active_run=ActiveRun("run-auto-complete"),
    )
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(
        ModelResponse(
            (
                ModelToolCall(
                    "read-final",
                    "read_file",
                    {"path": "reports/final.md"},
                ),
            )
        ),
        ModelResponse((), control=_claim()),
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=10_000, output_reserve=200),
        ),
        tool_runtime=build_file_tool_runtime(workspace),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-auto-complete",
    )
    action = Resume(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    assert store.state.goal is not None
    assert store.state.goal.status is GoalStatus.VERIFIED_DONE
    assert store.state.completion_claim is not None
    assert store.state.completion_claim.correlation_id == "claim-1"
    assert len(provider.calls) == 2


def test_readback_completion_waits_for_remaining_read(tmp_path) -> None:
    """R2：闭合证据来自批次中第一个 read 时，整批仍需完整落盘后再显式收尾。

    旧自动收尾的触发条件本就要求 MODEL 阶段且无剩余 tool_calls，不会因批次
    第一项是 read 就跳过第二项；它截断的是**整批结束之后**的主模型业务工作
    ——read 证据一闭合就直接 VERIFIED_DONE，模型不再有机会继续。R2 删除自动
    收尾后，批内每个调用都先有 durable 结果，模型的显式 claim（带逐项
    coverage）才是唯一收尾路径。
    """

    workspace = tmp_path / "workspace"
    (workspace / "reports").mkdir(parents=True)
    (workspace / "reports" / "final.md").write_text(CONTENT, encoding="utf-8")
    (workspace / "notes.md").write_text("supporting notes\n", encoding="utf-8")
    seed = _state()
    state = replace(
        seed,
        facts=(seed.facts[0],),
        active_run=ActiveRun("run-batched-readback"),
    )
    store = InMemoryCheckpointStore(state)
    sink = CollectingSink()
    provider = ScriptedProvider(
        ModelResponse(
            (
                ModelToolCall(
                    "read-final",
                    "read_file",
                    {"path": "reports/final.md"},
                ),
                ModelToolCall(
                    "read-notes",
                    "read_file",
                    {"path": "notes.md"},
                ),
            )
        ),
        ModelResponse((), control=_claim()),
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=10_000, output_reserve=200),
        ),
        tool_runtime=build_file_tool_runtime(workspace),
        checkpoint_store=store,
        event_sink=sink,
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-batched-readback",
    )
    action = Resume(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    result_ids = tuple(
        fact.content.get("tool_call_id")
        for fact in store.state.facts
        if fact.kind is FactKind.TOOL_RESULT
    )
    assert result_ids == ("read-final", "read-notes")
    assert len(provider.calls) == 2
    assert store.state.goal is not None
    assert store.state.goal.status is GoalStatus.VERIFIED_DONE
    assert tuple(event.kind.value for event in sink.events)[-3:] == (
        "tool_result",
        "tool_result",
        "completed",
    )


def test_unadmitted_explicit_process_requirement_cannot_verify_done() -> None:
    """用户要求 run/validate 时，文件 read-back 不能代替 process receipt。"""

    state = _state()
    assert state.goal is not None
    process_requirement = ProposedCriterion(
        criterion_id="criterion:required-process",
        description="the requested validator exits successfully",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
    )
    state = replace(
        state,
        goal=replace(
            state.goal,
            proposed_criteria=(*state.goal.proposed_criteria, process_requirement),
        ),
    )
    claim = _claim()
    records = ClosedEvidenceRegistry().derive(
        state, claim, observed_at="2026-08-24T00:00:00Z"
    )
    state = record_evidence(state, records)
    state = record_completion_claim(state, claim)

    with pytest.raises(ValueError, match="process criterion must be admitted"):
        verify_goal_completion(state)


def test_withdrawn_process_obligation_cannot_brick_completion_gate() -> None:
    """R3 端到端：correction 明确禁止后，撤回的义务不得阻塞 completion gate。

    修复前：admission 铸造的 runtime-owned process 义务在 correction 撤回后
    仍残留在 proposed_criteria，verify_goal_completion 的 "process criterion
    must be admitted" 检查永久失败 → Goal 无法完成。修复后：义务随现行版本
    失效，文件证据齐全时正常到 VERIFIED_DONE。
    """

    content = "fixed app\n"
    digest = hashlib.sha256(content.encode()).hexdigest()
    source = ConversationFact(
        fact_id="fact:user:1",
        kind=FactKind.USER_MESSAGE,
        content={"text": "运行 pytest -q，并修复 app.py 的功能。"},
    )
    state = ConversationState(
        conversation_id="conversation:withdrawal-e2e",
        facts=(source,),
    )
    bootstrap = GoalBootstrap(
        source_fact_id=source.fact_id,
        workspace_identity_digest="workspace:v1:" + "c" * 64,
        authority_snapshot="authority:v1:" + "d" * 64,
    )
    accepted = accept_goal_draft_proposal(
        state,
        GoalDraftProposal(
            correlation_id="proposal:withdrawal-e2e",
            user_outcome="修复 app.py 并验证结果",
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
            requires_local_process=False,
        ),
        bootstrap,
        admitted_at="2026-08-20T00:00:00Z",
    )
    assert accepted.goal is not None
    assert any(
        item.criterion_id.startswith("criterion:required-local-process:")
        for item in accepted.goal.proposed_criteria
    ), "admission must mint the runtime-owned process obligation"

    correction = ConversationFact(
        fact_id="fact:user:2",
        kind=FactKind.USER_MESSAGE,
        content={
            "text": "不要运行测试，只修改 app.py，其他要求不变。",
            "control": "goal_correction",
        },
    )
    corrected = accept_goal_delta_proposal(
        replace(accepted, facts=(*accepted.facts, correction)),
        GoalDeltaProposal(
            correlation_id="delta:withdrawal-e2e",
            delta=GoalDelta(
                goal_id=accepted.goal.goal_id,
                expected_revision=accepted.goal.revision,
                reason="apply the user's explicit prohibition",
                updates={"assumptions": ["tests must not run"]},
            ),
        ),
    )
    assert corrected.goal is not None
    goal = replace(
        corrected.goal,
        admitted_criteria=(
            AdmittedCriterion(
                criterion_id="criterion:app",
                description="app.py contains the requested fix",
                source_fact_id=source.fact_id,
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                predicate={"path": "app.py", "sha256": digest},
                required_evidence_class="workspace_file",
                admission_digest="b" * 64,
            ),
        ),
    )
    evidence_id = closed_evidence_id(goal.goal_id, goal.revision, "criterion:app")
    state = replace(
        corrected,
        goal=goal,
        facts=(
            *corrected.facts,
            ConversationFact(
                fact_id="fact:calls:1",
                kind=FactKind.TOOL_CALLS,
                content={
                    "calls": [
                        {
                            "tool_call_id": "read-app",
                            "name": "read_file",
                            "arguments": {"path": "app.py"},
                        }
                    ]
                },
            ),
            ConversationFact(
                fact_id="fact:read-result:1",
                kind=FactKind.TOOL_RESULT,
                content={
                    "tool_call_id": "read-app",
                    "text": content,
                    "is_error": False,
                    "executed": True,
                    "metadata": {},
                },
            ),
        ),
    )
    claim = CompletionClaim(
        correlation_id="claim:withdrawal-e2e",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        criterion_evidence_refs=(evidence_id,),
        requirement_coverage=(
            RequirementCoverage(
                requirement_id="requirement:fix-app-without-tests",
                requirement="修复 app.py，且不运行测试",
                source_fact_ids=(source.fact_id, correction.fact_id),
                status="satisfied",
                criterion_ids=("criterion:app",),
            ),
        ),
    )
    records = ClosedEvidenceRegistry().derive(
        state, claim, observed_at="2026-08-24T00:00:00Z"
    )
    state = record_evidence(state, records)
    state = record_completion_claim(state, claim)

    verified = verify_goal_completion(state)

    assert verified.goal is not None
    assert verified.goal.status is GoalStatus.VERIFIED_DONE


def test_blocked_claim_rejected_when_completion_evidence_is_derivable() -> None:
    """016 真实 E3 第 96 轮 a2 J7 观测的 false-blocked 形状。

    edit 与 local_process 均成功（durable receipts、exit 0）后模型以 BlockedClaim
    收尾，goal 被终化为 blocked。blocked-claim 守卫的合同文本要求"concrete
    safe attempt **produces a durable blocker**"（design §5.2/§9：blocked 表示
    无安全动作可推进），而实现只检查 attempt-made。当全部 mandatory criteria
    的完成证据已可从 durable facts 推导时，"无法推进"不成立——completion_claim
    本身即可推进。受理该 claim 会把可完成的 Goal 错误终化为 blocked
    （false-completion 的对偶）。产品必须拒绝并给出 budget 内的 completion
    修复指引；模型随后提交正确 claim 时 Goal 必须能到 VERIFIED_DONE。
    """
    blocked = BlockedClaim(
        correlation_id="blocked-1",
        goal_id="goal:1",
        goal_revision=1,
        blocker="cannot verify the edit",
        safe_attempts=(),
        resume_condition="manual verification",
    )
    runtime, store, action = _runtime(
        _state(),
        ModelResponse((), control=blocked),
        ModelResponse((), control=_claim(source_fact_ids=RUNTIME_SOURCE_FACT_IDS)),
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    assert store.state.goal.status is GoalStatus.VERIFIED_DONE
    guidance = next(
        str(fact.content.get("text", ""))
        for fact in store.state.facts
        if fact.kind is FactKind.POLICY_RESULT
        and fact.content.get("code") == "completion_evidence_available"
    )
    # R2-C：blocked 修复指引与当前完成门共享——物理证据可推导不等于业务复核
    # 完成，指引必须同时要求逐项 requirement_coverage 复核，而不是只教模型抄
    # evidence refs。
    assert "requirement_coverage" in guidance
    assert "blocked" in guidance


def test_blocked_claim_cannot_replace_available_final_read_back(tmp_path) -> None:
    """产物已写且 read_file 可用时，缺 read-back 不是 durable blocker。"""

    workspace = tmp_path / "workspace"
    (workspace / "reports").mkdir(parents=True)
    (workspace / "reports" / "final.md").write_text(CONTENT, encoding="utf-8")
    seed = _state()
    write_call = ConversationFact(
        fact_id="run:run-readback-blocked:tool-batch:1",
        kind=FactKind.TOOL_CALLS,
        content={
            "calls": [
                {
                    "tool_call_id": "write-final",
                    "name": "write_file",
                    "arguments": {"path": "reports/final.md", "content": CONTENT},
                }
            ]
        },
    )
    write_result = ConversationFact(
        fact_id="run:run-readback-blocked:tool-result:1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "write-final",
            "text": "written",
            "is_error": False,
            "executed": True,
        },
    )
    state = replace(
        seed,
        facts=(seed.facts[0], write_call, write_result),
        active_run=ActiveRun("run-readback-blocked"),
    )
    blocked = BlockedClaim(
        correlation_id="blocked-before-readback",
        goal_id="goal:1",
        goal_revision=1,
        blocker="the final artifact cannot be verified",
        safe_attempts=("wrote the artifact",),
        resume_condition="verify it manually",
    )
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(
        ModelResponse((), control=blocked),
        ModelResponse(
            (ModelToolCall("read-final", "read_file", {"path": "reports/final.md"}),)
        ),
        ModelResponse((), control=_claim()),
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=10_000, output_reserve=200),
        ),
        tool_runtime=build_file_tool_runtime(workspace),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-readback-blocked",
    )
    action = Resume(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    assert store.state.goal is not None
    assert store.state.goal.status is GoalStatus.VERIFIED_DONE
    assert any(
        fact.kind is FactKind.POLICY_RESULT
        and fact.content.get("code") == "blocked_claim_not_verified"
        and "read_file" in fact.content.get("text", "")
        for fact in store.state.facts
    )


def test_unadmitted_filesystem_goal_keeps_write_tool_as_pending_obligation() -> None:
    """correction 令旧 file binding 失效后，失败的预读不能授权 blocked。"""

    state = _state()
    assert state.goal is not None
    state = replace(
        state,
        goal=replace(state.goal, admitted_criteria=()),
        active_run=ActiveRun("run-corrected-file"),
    )

    assert ClosedEvidenceRegistry().pending_obligation_tools(
        state,
        available_tools=("read_file", "write_file", "edit_file"),
    ) == ("write_file",)


@pytest.mark.parametrize(
    ("process_failed", "expected_tool"),
    ((False, "confirm_file"), (True, "write_file")),
)
def test_process_generated_artifact_requires_confirmation_only_after_success(
    process_failed: bool,
    expected_tool: str,
) -> None:
    state = _state()
    assert state.goal is not None
    run_id = "run-generated-artifact"
    process_call = ConversationFact(
        fact_id=f"run:{run_id}:tool-batch:1",
        kind=FactKind.TOOL_CALLS,
        content={
            "calls": [
                {
                    "tool_call_id": "generate-artifact",
                    "name": "local_process",
                    "arguments": {
                        "executable": "./generate-report",
                        "argv": [],
                        "cwd": ".",
                        "profile": "short",
                    },
                }
            ]
        },
    )
    process_result = ConversationFact(
        fact_id=f"run:{run_id}:tool-result:1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "generate-artifact",
            "text": "generation result",
            "is_error": process_failed,
            "executed": True,
        },
    )
    state = replace(
        state,
        goal=replace(state.goal, admitted_criteria=()),
        active_run=ActiveRun(run_id),
        facts=(*state.facts, process_call, process_result),
    )

    assert ClosedEvidenceRegistry().pending_obligation_tools(
        state,
        available_tools=("read_file", "confirm_file", "write_file", "edit_file"),
    ) == (expected_tool,)


def test_admitted_filesystem_goal_with_only_failed_read_still_requires_write() -> None:
    """纠正后的 criterion 已准入，也不能让失败预读冒充写入 attempt。"""

    seed = _state()
    failed_call = ConversationFact(
        fact_id="run:run-corrected-file:tool-batch:1",
        kind=FactKind.TOOL_CALLS,
        content={
            "calls": [
                {
                    "tool_call_id": "read-missing-final",
                    "name": "read_file",
                    "arguments": {"path": "reports/final.md"},
                }
            ]
        },
    )
    failed_result = ConversationFact(
        fact_id="run:run-corrected-file:tool-result:1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "read-missing-final",
            "text": "workspace file denied",
            "is_error": True,
            "executed": False,
            "failure_code": "workspace_file_denied",
        },
    )
    state = replace(
        seed,
        facts=(seed.facts[0], failed_call, failed_result),
        active_run=ActiveRun("run-corrected-file"),
    )

    assert ClosedEvidenceRegistry().pending_obligation_tools(
        state,
        available_tools=("read_file", "write_file", "edit_file"),
    ) == ("write_file",)
    assert ClosedEvidenceRegistry().pending_obligation_tools(
        _state(),
        available_tools=("read_file", "write_file", "edit_file"),
    ) == ()


def test_obsolete_rejection_does_not_authorize_false_blocked_claim() -> None:
    """Goal correction 后旧 target 的拒绝不能阻断已可证明的新 Goal。

    真实 016 J11 会在 ``draft.md`` approval 边界收到自然语言 correction；若模型
    随后又请求旧 target，用户拒绝只是维护修正后的 authority，不是当前 Goal 的
    blocker。完成证据已可推导时，Runtime 仍须拒绝 blocked_claim。
    """

    state = _state()
    obsolete_call = ConversationFact(
        fact_id="run:run-verify:tool-batch:4",
        kind=FactKind.TOOL_CALLS,
        content={
            "calls": [
                {
                    "tool_call_id": "write-obsolete-draft",
                    "name": "write_file",
                    "arguments": {"path": "draft.md", "content": "obsolete"},
                }
            ]
        },
    )
    rejection = ConversationFact(
        fact_id="action:4:rejection",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "write-obsolete-draft",
            "text": "User rejected the requested tool action.",
            "is_error": True,
            "rejected": True,
        },
    )
    state = replace(
        state,
        facts=(*state.facts, obsolete_call, rejection),
        active_run=ActiveRun(
            run_id="run-verify",
            rejected_request_ids=("approval-obsolete-draft",),
        ),
    )
    blocked = BlockedClaim(
        correlation_id="blocked-obsolete-rejection",
        goal_id="goal:1",
        goal_revision=1,
        blocker="the obsolete draft write was rejected",
        safe_attempts=("requested draft.md",),
        resume_condition="allow the obsolete draft write",
    )
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(
        ModelResponse((), control=blocked),
        ModelResponse((), control=_claim()),
    )
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
        invocation_id_factory=lambda: "invocation-obsolete-rejection",
    )
    action = Resume(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    assert store.state.goal is not None
    assert store.state.goal.status is GoalStatus.VERIFIED_DONE
    assert any(
        fact.kind is FactKind.POLICY_RESULT
        and fact.content.get("code") == "completion_evidence_available"
        for fact in store.state.facts
    )


def test_redundant_web_rejection_is_not_a_current_goal_blocker() -> None:
    """已有 mandatory Web receipt 时，拒绝重复检索不能伪造 blocker。"""

    state = _state()
    assert state.goal is not None
    file_criterion = state.goal.admitted_criteria[0]
    web_proposal = ProposedCriterion(
        criterion_id="criterion:web",
        description="public source retrieved",
        oracle_kind=EvidenceOracleKind.WEB_SOURCE_RECEIPT,
    )
    web_criterion = replace(
        file_criterion,
        criterion_id="criterion:web",
        oracle_kind=EvidenceOracleKind.WEB_SOURCE_RECEIPT,
        predicate={"receipt_digest": "a" * 64, "source_kind": "web_extracted_content"},
        required_evidence_class="public_web_source",
    )
    call = ConversationFact(
        fact_id="run:run-web-reject:tool-batch:4",
        kind=FactKind.TOOL_CALLS,
        content={
            "calls": [
                {
                    "tool_call_id": "repeat-web",
                    "name": "web_fetch",
                    "arguments": {"source_ref": "source-ref:v1:repeat"},
                }
            ]
        },
    )
    rejection = ConversationFact(
        fact_id="action:4:rejection",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "repeat-web",
            "text": "User rejected the requested tool action.",
            "is_error": True,
            "rejected": True,
        },
    )
    state = replace(
        state,
        facts=(*state.facts, call, rejection),
        goal=replace(
            state.goal,
            proposed_criteria=(*state.goal.proposed_criteria, web_proposal),
            admitted_criteria=(*state.goal.admitted_criteria, web_criterion),
        ),
        active_run=ActiveRun(
            run_id="run-web-reject",
            rejected_request_ids=("approval-repeat-web",),
        ),
    )

    assert AgentRuntime._rejection_still_blocks_current_goal(state) is False


def test_filesystem_oracle_rederives_exact_path_and_content_digest_from_raw_facts() -> None:
    records = ClosedEvidenceRegistry().derive(
        _state(),
        _claim(),
        observed_at="2026-08-02T02:00:00Z",
    )
    assert records[0].passed is True
    assert records[0].oracle_identity == "filesystem-digest:v1"


def test_filesystem_oracle_uses_original_bytes_digest_for_binary_artifact(tmp_path) -> None:
    payload = b"%PDF-1.7\x00\xff\xfe\n"
    (tmp_path / "artifact.pdf").write_bytes(payload)
    runtime = build_file_tool_runtime(tmp_path)
    intent = runtime.prepare(
        ToolCall("read-binary", "read_file", {"path": "artifact.pdf"}),
        ToolPrepareContext(
            conversation_id="conversation-1",
            run_id="run-binary",
            state_revision=0,
            goal_id="goal:1",
            goal_revision=1,
            workspace_identity_digest="workspace-digest-1",
        ),
    )
    result = runtime.invoke(intent)
    facts = (
        ConversationFact(
            fact_id="fact:calls:binary",
            kind=FactKind.TOOL_CALLS,
            content={
                "calls": [
                    {
                        "tool_call_id": "read-binary",
                        "name": "read_file",
                        "arguments": {"path": "artifact.pdf"},
                    }
                ]
            },
        ),
        ConversationFact(
            fact_id="fact:result:binary",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": result.tool_call_id,
                "text": result.content,
                "is_error": result.is_error,
                "executed": result.executed,
                "metadata": result.metadata,
            },
        ),
    )
    goal = _goal()
    criterion = replace(
        goal.admitted_criteria[0],
        predicate={
            "path": "artifact.pdf",
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
    )
    state = ConversationState(
        conversation_id="conversation-1",
        facts=facts,
        goal=replace(goal, admitted_criteria=(criterion,)),
    )

    records = ClosedEvidenceRegistry().derive(
        state,
        _claim(),
        observed_at="2026-08-02T02:00:00Z",
    )
    assert records[0].passed is True


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
                execution_authority=ExecutionAuthorityClass.IN_PROCESS,
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
