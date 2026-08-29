from __future__ import annotations

from dataclasses import replace

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRun,
    AdmittedCriterion,
    ApprovalPolicy,
    BeginAnswer,
    BlockedClaim,
    ClarificationRequest,
    CompletionClaim,
    ControlReceipt,
    ConversationState,
    DirectResponse,
    EvidenceOracleKind,
    ExecutionAuthorityClass,
    FactKind,
    GoalProgress,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    OutputPolicy,
    Resume,
    RunStatus,
    SideEffectClass,
    SubmitMessage,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.evidence import ClosedEvidenceRegistry
from agent.runtime.loop import AgentRuntime, InvocationLimits, RetryableProviderError
from agent.runtime.ports import InvalidProviderResponseError
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    conversation_with_active_goal,
    goal_noop_response,
)


def _resume(state: ConversationState) -> Resume:
    """在同一 run 内继续(不注入新用户文本,避免 correction-pending 掩蔽)。"""

    return Resume(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
    )


def _run(
    provider,
    *,
    repairs=1,
    no_progress_replans=2,
    max_model_calls=16,
    state: ConversationState | None = None,
    tools=(),
    action=None,
):
    initial = state or ConversationState.new("conversation-1")
    store = InMemoryCheckpointStore(initial)
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
        ),
        tool_runtime=KernelToolRuntime(tools),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(
            max_model_calls=max_model_calls,
            max_invalid_repairs=repairs,
            max_no_progress_replans=no_progress_replans,
        ),
        invocation_id_factory=lambda: "invocation-1",
    )
    if action is None:
        action = SubmitMessage(
            conversation_id=initial.conversation_id,
            action_seq=initial.next_action_seq,
            expected_revision=initial.revision,
            run_id="run-1",
            message="hello",
        )
    return runtime.run_turn(action, store.load()), store


def test_transient_provider_error_is_retryable_pause() -> None:
    result, store = _run(ScriptedProvider(RetryableProviderError("timeout")))

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert store.state.active_run is not None


def test_invalid_provider_output_has_bounded_repair_then_fails_fatal() -> None:
    result, store = _run(
        ScriptedProvider(ModelResponse(()), ModelResponse(())),
        repairs=1,
    )

    assert result.status is RunStatus.FAILED_FATAL
    assert store.state.active_run is None


def test_invalid_provider_response_can_recover_once_without_tool_effect() -> None:
    result, store = _run(
        ScriptedProvider(
            InvalidProviderResponseError("malformed_tool_call"),
            ModelResponse((ModelTextBlock("recovered"),)),
        ),
        repairs=1,
    )

    assert result.status is RunStatus.COMPLETED
    assert result.message == "recovered"
    assert [
        fact.content["code"]
        for fact in store.state.facts
        if fact.content.get("code") == "invalid_provider_response"
    ] == ["invalid_provider_response"]
    repair_fact = next(
        fact
        for fact in store.state.facts
        if fact.content.get("code") == "invalid_provider_response"
    )
    assert "malformed_tool_call" in repair_fact.content["text"]


def test_successful_tool_result_resets_invalid_response_repair_budget() -> None:
    """repair allowance 只约束连续坏响应，不能跨真实 product progress 累计。"""

    seed = replace(
        conversation_with_active_goal(),
        active_run=ActiveRun("run-1"),
    )
    assert seed.goal is not None
    spec = ToolSpec(
        name="observe",
        version="1",
        description="observe a bounded fixture",
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={},
        output_limit_chars=100,
    )
    blocked = BlockedClaim(
        correlation_id="blocked-after-fresh-repair",
        goal_id=seed.goal.goal_id,
        goal_revision=seed.goal.revision,
        blocker="the bounded fixture has no further information",
        safe_attempts=("observed the fixture",),
        resume_condition="provide a different fixture",
    )
    result, store = _run(
        ScriptedProvider(
            InvalidProviderResponseError("malformed_tool_call"),
            ModelResponse((ModelToolCall("observe-1", "observe", {}),)),
            InvalidProviderResponseError("malformed_tool_call"),
            ModelResponse((), control=blocked),
        ),
        repairs=1,
        state=seed,
        tools=(RegisteredTool(spec, lambda _intent: "observed"),),
        action=_resume(seed),
    )

    assert result.status is RunStatus.COMPLETED
    assert store.state.goal is not None
    assert store.state.goal.status.value == "blocked"


def test_repeated_invalid_provider_response_fails_closed() -> None:
    result, store = _run(
        ScriptedProvider(
            InvalidProviderResponseError("malformed_control"),
            InvalidProviderResponseError("malformed_control"),
        ),
        repairs=1,
    )

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "invalid_provider_response"
    assert store.state.active_run is None


def test_malformed_control_repair_carries_bounded_shape_detail() -> None:
    # 016 真实 E3 J11:correction 后模型反复提交形状错误的 control,修复消息
    # 只说 malformed_control 时模型无从自纠,最终耗尽额度 fatal。repair 必须
    # 携带归一化层给出的有界 shape detail(键名级,绝不含 wire 值)。
    from agent.provider.protocol import ProviderProtocolError

    result, store = _run(
        ScriptedProvider(
            ProviderProtocolError(
                "malformed_control",
                detail="expected exactly ['a', 'b']; missing ['updated_at']",
            ),
            ModelResponse((ModelTextBlock("recovered"),)),
        ),
        repairs=1,
    )

    assert result.status is RunStatus.COMPLETED
    repair_fact = next(
        fact
        for fact in store.state.facts
        if fact.content.get("code") == "invalid_provider_response"
    )
    assert "missing ['updated_at']" in repair_fact.content["text"]


def test_malformed_control_repair_reflects_installed_goal_state() -> None:
    result, store = _run(
        ScriptedProvider(
            InvalidProviderResponseError("malformed_control"),
            InvalidProviderResponseError("malformed_control"),
        ),
        repairs=1,
        state=conversation_with_active_goal(),
    )

    assert result.status is RunStatus.FAILED_FATAL
    repair = next(
        fact
        for fact in store.state.facts
        if fact.content.get("code") == "invalid_provider_response"
    )
    assert "trusted_goal already exists" in repair.content["text"]
    assert "goal_proposal is unavailable" in repair.content["text"]
    assert "goal_delta_proposal only for a real conflict" in repair.content["text"]
    assert "Allowed control kinds now" in repair.content["text"]


def test_control_hidden_by_current_schema_cannot_mutate_goal() -> None:
    seed = conversation_with_active_goal()
    assert seed.goal is not None
    controls = tuple(
        GoalProgress(
            correlation_id=f"hidden-progress-{index}",
            goal_id=seed.goal.goal_id,
            goal_revision=seed.goal.revision,
            summary="narrated without a product result",
            next_step="keep narrating",
        )
        for index in range(2)
    )

    result, store = _run(
        ScriptedProvider(*(ModelResponse((), control=control) for control in controls)),
        repairs=1,
        state=seed,
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "no_progress"
    assert store.state.goal is not None
    assert store.state.goal.progress_summary is None
    assert any(
        fact.content.get("code") == "no_progress_replan_required"
        for fact in store.state.facts
    )


def test_repeated_invalid_completion_control_exhausts_shared_repair_budget() -> None:
    seed = conversation_with_active_goal()
    assert seed.goal is not None
    criterion = AdmittedCriterion(
        criterion_id="criterion-confirmed",
        description="owner confirms the bounded result",
        source_fact_id="action:1:user",
        oracle_kind=EvidenceOracleKind.USER_CONFIRMATION,
        predicate={"confirmed": True},
        required_evidence_class="user_confirmation",
        admission_digest="runtime-admission-confirmed",
    )
    source = replace(
        seed.facts[0],
        content={
            "text": "please persist the fixture note",
            "criterion_id": criterion.criterion_id,
            "confirmed": True,
        },
    )
    correlation_id = "already-used-completion"
    seed = replace(
        seed,
        facts=(source,),
        goal=replace(seed.goal, admitted_criteria=(criterion,)),
        control_receipts=(
            ControlReceipt.create(
                correlation_id=correlation_id,
                control_kind="goal_progress",
                goal_id=seed.goal.goal_id,
                goal_revision=seed.goal.revision,
                accepted_state_revision=seed.revision,
                payload_digest="prior-control-payload",
            ),
        ),
    )
    claim = CompletionClaim(
        correlation_id=correlation_id,
        goal_id=seed.goal.goal_id,
        goal_revision=seed.goal.revision,
        criterion_evidence_refs=(
            ClosedEvidenceRegistry.evidence_id(
                seed.goal.goal_id,
                seed.goal.revision,
                criterion.criterion_id,
            ),
        ),
    )

    result, store = _run(
        ScriptedProvider(
            ModelResponse((), control=claim),
            ModelResponse((), control=claim),
        ),
        repairs=1,
        state=seed,
    )

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "invalid_model_control"
    assert store.state.active_run is None
    assert [
        fact.content.get("code")
        for fact in store.state.facts
        if fact.content.get("code") == "invalid_model_control"
    ] == ["invalid_model_control"]


def test_reused_blocked_claim_correlation_is_bounded_repair_not_crash() -> None:
    # 016 真实 E3 第 87 轮 J10:同一 run 内(无新用户补充,correction 不 pending)
    # 模型复用已受理 correlation_id 的 blocked_claim,accept_blocked_claim 的
    # ValueError 未被包裹,直接 runtime_failure fatal(§18 同类:模型可修复
    # 输入错误必须有界 repair)。GoalDraft/GoalDelta/CompletionClaim 已有同型
    # 包裹;BlockedClaim 与 ClarificationRequest 同样不得把可修复输入升级为
    # runtime crash。Resume 驱动同一 run,不走 SubmitMessage(新用户文本会使
    # correction-pending 只放行 goal_delta_proposal,掩盖本缺陷)。
    seed = conversation_with_active_goal()
    assert seed.goal is not None
    seed = replace(
        seed,
        active_run=ActiveRun(run_id="run-reuse-blocked"),
        control_receipts=(
            ControlReceipt.create(
                correlation_id="already-used-blocked",
                control_kind="goal_progress",
                goal_id=seed.goal.goal_id,
                goal_revision=seed.goal.revision,
                accepted_state_revision=seed.revision,
                payload_digest="prior-control-payload",
            ),
        ),
    )
    claims = tuple(
        BlockedClaim(
            correlation_id="already-used-blocked",
            goal_id=seed.goal.goal_id,
            goal_revision=seed.goal.revision,
            blocker="the fixture runner is not approved",
            safe_attempts=(),
            resume_condition="approve the runner",
        )
        for _ in range(2)
    )

    result, store = _run(
        ScriptedProvider(*(ModelResponse((), control=claim) for claim in claims)),
        repairs=1,
        state=seed,
        action=_resume(seed),
    )

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "invalid_model_control"
    assert [
        fact.content.get("code")
        for fact in store.state.facts
        if fact.content.get("code") == "invalid_model_control"
    ] == ["invalid_model_control"]


def test_reused_clarification_correlation_is_bounded_repair_not_crash() -> None:
    # 同一缺陷类的第二分支:accept_clarification_request 的 correlation 复用
    # ValueError 同样未被包裹(016 第 87 轮定诊时的姊妹缺口)。
    seed = conversation_with_active_goal()
    assert seed.goal is not None
    seed = replace(
        seed,
        active_run=ActiveRun(run_id="run-reuse-clarify"),
        control_receipts=(
            ControlReceipt.create(
                correlation_id="already-used-clarify",
                control_kind="goal_progress",
                goal_id=seed.goal.goal_id,
                goal_revision=seed.goal.revision,
                accepted_state_revision=seed.revision,
                payload_digest="prior-control-payload",
            ),
        ),
    )
    requests = tuple(
        ClarificationRequest(
            correlation_id="already-used-clarify",
            question="Which output format do you need?",
            boundary_code="direction_boundary",
            missing_fields=("output_format",),
            safe_assumptions=(),
        )
        for _ in range(2)
    )

    result, store = _run(
        ScriptedProvider(
            *(ModelResponse((), control=request) for request in requests)
        ),
        repairs=1,
        state=seed,
        action=_resume(seed),
    )

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "invalid_model_control"
    assert [
        fact.content.get("code")
        for fact in store.state.facts
        if fact.content.get("code") == "invalid_model_control"
    ] == ["invalid_model_control"]


def test_repeated_unverified_completion_claims_fail_as_no_progress() -> None:
    seed = conversation_with_active_goal()
    assert seed.goal is not None
    claims = tuple(
        CompletionClaim(
            correlation_id=f"unverified-completion-{index}",
            goal_id=seed.goal.goal_id,
            goal_revision=seed.goal.revision,
            criterion_evidence_refs=(),
        )
        for index in range(2)
    )

    result, store = _run(
        ScriptedProvider(
            goal_noop_response("unverified-completion-user-supplement"),
            *(ModelResponse((), control=claim) for claim in claims),
        ),
        repairs=1,
        state=seed,
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "no_progress"
    assert sum(
        fact.content.get("code") == "completion_not_verified"
        for fact in store.state.facts
    ) == 1


def test_research_readback_failure_has_executable_repair_instruction() -> None:
    message = ClosedEvidenceRegistry().assess_gap(
        "no exact read-back fact proves the research artifact"
    ).repair_instruction

    assert "read_file" in message
    assert "build_citation_manifest" in message
    assert "rewrite the citation sidecar" in message


def test_truncated_research_source_has_executable_alternate_fetch_instruction() -> None:
    message = ClosedEvidenceRegistry().assess_gap(
        "truncated source receipt cannot prove research"
    ).repair_instruction

    assert "unattempted" in message
    assert "web_fetch" in message
    assert "not truncated" in message
    assert "rewrite" in message


def test_invented_url_failure_has_executable_repair_instruction() -> None:
    message = ClosedEvidenceRegistry().assess_gap(
        "artifact contains an invented URL"
    ).repair_instruction

    assert "web_extracted_content origin_locator" in message
    assert "edit_file" in message
    assert "rebuild" in message


def test_pregoal_source_receipt_failure_requires_current_goal_retrieval() -> None:
    message = ClosedEvidenceRegistry().assess_gap(
        "source receipt is not bound to the current Goal"
    ).repair_instruction

    assert "before this Goal" in message
    assert "materially different" in message
    assert "current-Goal source refs" in message


def test_missing_source_class_repair_requires_new_grounded_source() -> None:
    message = ClosedEvidenceRegistry().assess_gap(
        "required source class is not cited"
    ).repair_instruction

    assert "history or workspace source" in message
    assert "new source ref" in message
    assert "rewrite both targets" in message


def test_unavailable_control_repairs_teach_the_closing_move() -> None:
    # 016 真实 E3 观测（第 53/93 轮 J8）：research.md 与 sidecar 均已写的
    # evidence-ready 收尾阶段，模型反复提交当前语境不可用的 control（具体
    # wire kind 未记录于 bounded FAIL_DETAIL），4 次 repair 后 fatal
    # invalid_model_control；第 72 轮 J7 的同类 fatal 仅作更宽泛旁证。既有
    # repair 消息列出 allowed kinds，但"concrete work remains"不成立的收尾
    # 语境缺收尾动作指引——repair-guidance 完整性缺口。本测试用
    # DirectResponse 构造代表性 deterministic reproducer（有活动 Goal 时不可
    # 用的 control 之一），不宣称真实 wire kind；断言 repair 教
    # completion_claim 收尾（逐字复制当前 trusted_goal refs），该指引对任何
    # 不可用 kind 都必须成立。
    seed = conversation_with_active_goal()
    unavailable = tuple(
        ModelResponse(
            (),
            control=DirectResponse(
                correlation_id=f"unavailable-direct-{index}",
                text="Here is the finished research summary.",
            ),
        )
        for index in range(5)
    )

    result, store = _run(
        ScriptedProvider(goal_noop_response("ctl-noop-supplement"), *unavailable),
        repairs=4,
        state=seed,
    )

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "invalid_model_control"
    repairs = [
        fact.content.get("text", "")
        for fact in store.state.facts
        if fact.content.get("code") == "invalid_model_control"
    ]
    assert len(repairs) == 4, "budget 4 must produce four repair messages before fatal"
    for message in repairs:
        assert "not currently available" in message
        assert "expected_completion_evidence_refs" in message, (
            "closing-phase repair must teach the completion move with the exact "
            "copy directive, not merely list the control kind name"
        )


def test_active_goal_final_prose_repair_teaches_exact_completion_move() -> None:
    # 016 真实 J8 诊断：Web、双文件与 read-back 已完成后，模型用 final prose
    # 收尾。Runtime 必须继续拒绝文字假完成，但 repair 也必须给出唯一可执行的
    # completion_claim 复制指引，不能只列 control 名称。
    seed = conversation_with_active_goal()
    prose = tuple(
        ModelResponse((ModelTextBlock("The requested research is complete."),))
        for _ in range(5)
    )

    result, store = _run(
        ScriptedProvider(goal_noop_response("final-prose-user-supplement"), *prose),
        repairs=4,
        state=seed,
    )

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "invalid_model_control"
    repairs = [
        fact.content.get("text", "")
        for fact in store.state.facts
        if fact.content.get("code") == "active_goal_requires_control"
    ]
    assert len(repairs) == 4
    for message in repairs:
        assert "completion_claim" in message
        assert "criterion_evidence_refs exactly" in message
        assert "expected_completion_evidence_refs" in message


def test_manifest_binding_failures_have_executable_rebuild_instruction() -> None:
    # 016 真实 E3 J8 最后一公里（第 74/82/88/90 轮）：research.md 与 sidecar 均
    # 已写，模型在 canonical sidecar 之后再次编辑 artifact 等，completion 以
    # manifest 绑定族原因被拒；该族拒绝落入通用兜底（"create missing evidence
    # or send blocked_claim"），既无确定性重建程序、又把 blocked_claim 作为出
    # 路，模型随即 churn（3-8 次 file effect）直至 goal_ready/blocked。绑定族
    # 必须给出可执行重建指令，且不得以 blocked_claim 为出路（来源已存在，
    # 重建即完成）。
    for reason in (
        "citation manifest is not bound to the exact artifact",
        "citation manifest is not bound to the current Goal",
        "citation manifest read-back is invalid",
        "each citation marker must occur in the artifact",
    ):
        message = ClosedEvidenceRegistry().assess_gap(reason).repair_instruction

        assert "build_citation_manifest" in message, reason
        assert "blocked_claim" not in message, reason


def test_stale_or_inexact_completion_refs_have_copy_current_refs_instruction() -> None:
    # 016 真实 E3 第 65/70 轮 J11:write 与 read-back 全部完成后,completion claim
    # 因 refs 抄错(Goal revision 变更后复制了旧投影块)被拒;通用兜底让模型
    # "创建缺失 evidence 或 send blocked_claim",而 refs 错误不存在缺失
    # evidence,模型被兜底指令引导向 blocked_claim、goal=blocked。refs/stale
    # 拒绝必须给出"逐字复制当前 trusted_goal refs"的可执行修复,且不得把
    # blocked_claim 作为该语境的出路。
    for reason in (
        "completion claim evidence refs are not exact",
        "completion claim is stale",
    ):
        message = ClosedEvidenceRegistry().assess_gap(reason).repair_instruction

        assert "expected_completion_evidence_refs" in message, reason
        assert "blocked_claim" not in message, reason


def test_existing_source_classes_are_remapped_without_retrieval() -> None:
    for reason in (
        "required source class is not cited",
        "required source kind is not cited",
    ):
        message = ClosedEvidenceRegistry().assess_gap(reason).repair_instruction

        assert "already exists" in message
        assert "valid marker" in message
        assert "source class" in message
        assert "do not retrieve it again" in message
        assert "[H1]" not in message
        assert "[W1]" not in message


def test_repeated_nonexecuted_tool_repairs_fail_as_no_progress() -> None:
    result, store = _run(
        ScriptedProvider(
            *(
                ModelResponse((ModelToolCall(f"unknown-{index}", "unknown_tool", {}),))
                for index in range(3)
            )
        ),
        repairs=1,
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "no_progress"
    assert sum(
        fact.content.get("code") == "unadvertised_tool"
        for fact in store.state.facts
    ) == 1
    assert not any(fact.kind is FactKind.TOOL_CALLS for fact in store.state.facts)
    assert not any(fact.kind is FactKind.TOOL_RESULT for fact in store.state.facts)


def test_materially_different_nonexecuted_tool_attempts_can_replan_to_completion() -> None:
    result, store = _run(
        ScriptedProvider(
            ModelResponse((ModelToolCall("unknown-1", "unknown_tool_a", {}),)),
            ModelResponse((ModelToolCall("unknown-2", "unknown_tool_b", {}),)),
            ModelResponse((ModelToolCall("unknown-3", "unknown_tool_c", {}),)),
            ModelResponse((ModelTextBlock("replanned final"),)),
        ),
        repairs=1,
        no_progress_replans=4,
    )

    assert result.status is RunStatus.COMPLETED
    assert result.message == "replanned final"
    assert store.state.active_run is None


def test_sixteenth_known_nonexecuted_tool_attempt_pauses_without_extra_send() -> None:
    calls: list[str] = []
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="read_fixture",
        version="1",
        description="Read one immutable fixture",
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
        output_limit_chars=100,
    )
    provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer("begin-known-not-executed")),
        *(
            ModelResponse((ModelToolCall(f"invalid-{index}", "read_fixture", {}),))
            for index in range(16)
        ),
        RetryableProviderError("post-threshold send must not happen"),
    )

    result, store = _run(
        provider,
        no_progress_replans=16,
        max_model_calls=None,
        tools=(RegisteredTool(spec, lambda _intent: calls.append("invoked")),),
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "no_progress"
    assert len(provider.calls) == 17
    assert calls == []
    assert store.state.active_run is not None
    assert store.state.active_run.status.value == "paused_limit"


def test_one_parallel_nonexecuted_batch_uses_one_replan_opportunity() -> None:
    result, store = _run(
        ScriptedProvider(
            ModelResponse(
                tuple(
                    ModelToolCall(f"unknown-{index}", "unknown_tool", {})
                    for index in range(6)
                )
            ),
            ModelResponse((ModelTextBlock("replanned after batch feedback"),)),
        ),
        repairs=1,
    )

    assert result.status is RunStatus.COMPLETED
    assert result.message == "replanned after batch feedback"
    assert not any(fact.kind is FactKind.TOOL_CALLS for fact in store.state.facts)
    assert not any(fact.kind is FactKind.TOOL_RESULT for fact in store.state.facts)
    assert sum(
        fact.content.get("code") == "unadvertised_tool"
        for fact in store.state.facts
    ) == 1


def test_repeated_identical_successful_tool_results_fail_as_no_progress() -> None:
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="read_fixture",
        version="1",
        description="Read one immutable fixture",
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
        output_limit_chars=100,
    )
    repeated = tuple(
        ModelResponse(
            (ModelToolCall(f"read-{index}", "read_fixture", {"path": "same.txt"}),)
        )
        for index in range(3)
    )

    result, store = _run(
        ScriptedProvider(
            ModelResponse((), control=BeginAnswer("begin-repeated-read")),
            *repeated,
            ModelResponse((ModelTextBlock("late final"),)),
        ),
        repairs=1,
        tools=(RegisteredTool(spec, lambda intent: "unchanged"),),
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "no_progress"
    assert sum(
        fact.content.get("code") == "no_progress_replan_required"
        for fact in store.state.facts
    ) == 1


def test_non_citation_goal_target_does_not_enter_citation_authority() -> None:
    calls: list[str] = []
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="read_fixture",
        version="1",
        description="Read the current workspace",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={},
        output_limit_chars=100,
    )
    state = conversation_with_active_goal()
    assert state.goal is not None
    state = replace(state, goal=replace(state.goal, targets=(".",)))
    provider = ScriptedProvider(
        goal_noop_response("read-current-user-supplement"),
        ModelResponse((ModelToolCall("read-current", "read_fixture", {}),)),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="read-current-blocked",
                goal_id="goal-1",
                goal_revision=1,
                blocker="fixture complete",
                safe_attempts=("read current workspace",),
                resume_condition="not applicable to this fixture",
            ),
        ),
    )

    result, _store = _run(
        provider,
        state=state,
        tools=(RegisteredTool(spec, lambda _intent: calls.append("read") or "content"),),
    )

    assert result.status is RunStatus.COMPLETED
    assert calls == ["read"]


def test_workspace_mutation_invalidates_prior_read_deduplication() -> None:
    calls: list[str] = []

    def spec(name: str, side_effect: SideEffectClass) -> ToolSpec:
        return ToolSpec(
            execution_authority=ExecutionAuthorityClass.IN_PROCESS,
            name=name,
            version="1",
            description=name,
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            risk=ToolRisk.LOW,
            side_effect=side_effect,
            output_policy=OutputPolicy.BOUNDED_TEXT,
            approval_policy=ApprovalPolicy.NEVER,
            safety_policy={},
            output_limit_chars=100,
        )

    responses = (
        ModelResponse(
            (ModelToolCall("read-before", "read_file", {"path": "report.md"}),)
        ),
        ModelResponse(
            (ModelToolCall("edit", "edit_file", {"path": "report.md"}),)
        ),
        ModelResponse(
            (ModelToolCall("read-after", "read_file", {"path": "report.md"}),)
        ),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="stop-after-stale-read",
                goal_id="goal-1",
                goal_revision=1,
                blocker="test finished after the fresh read",
                safe_attempts=("read after edit",),
                resume_condition="not applicable to this fixture",
            ),
        ),
    )
    result, _store = _run(
        ScriptedProvider(
            goal_noop_response("workspace-mutation-user-supplement"),
            *responses,
        ),
        repairs=1,
        state=conversation_with_active_goal(),
        tools=(
            RegisteredTool(
                spec("read_file", SideEffectClass.READ_ONLY),
                lambda _intent: calls.append("read") or "content",
            ),
            RegisteredTool(
                spec("edit_file", SideEffectClass.WRITE),
                lambda _intent: calls.append("edit") or "edited",
            ),
        ),
    )

    assert result.status is RunStatus.COMPLETED
    assert result.message == "test finished after the fresh read"
    assert calls == ["read", "edit", "read"]


def test_model_cannot_call_registered_read_only_tool_hidden_from_context() -> None:
    calls = 0

    def hidden_fetch(intent) -> str:  # noqa: ANN001
        nonlocal calls
        calls += 1
        return "must not execute"

    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="web_fetch",
        version="1",
        description="Fetch only an available searched source",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={},
        output_limit_chars=100,
    )
    result, store = _run(
        ScriptedProvider(
            ModelResponse((ModelToolCall("hidden-1", "web_fetch", {}),)),
            ModelResponse((ModelToolCall("hidden-2", "web_fetch", {}),)),
        ),
        repairs=1,
        tools=(RegisteredTool(spec, hidden_fetch),),
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "no_progress"
    assert calls == 0
    assert any(
        fact.content.get("code") == "unadvertised_tool"
        and "not currently available" in fact.content.get("text", "")
        for fact in store.state.facts
    )
