from __future__ import annotations

from dataclasses import replace

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    AdmittedCriterion,
    ApprovalPolicy,
    BlockedClaim,
    CompletionClaim,
    ControlReceipt,
    ConversationState,
    EvidenceOracleKind,
    ExecutionAuthorityClass,
    FactKind,
    GoalProgress,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    OutputPolicy,
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
)


def _run(provider, *, repairs=1, state: ConversationState | None = None, tools=()):
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
        limits=InvocationLimits(max_invalid_repairs=repairs),
        invocation_id_factory=lambda: "invocation-1",
    )
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

    assert result.status is RunStatus.FAILED_FATAL
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
        ScriptedProvider(*(ModelResponse((), control=claim) for claim in claims)),
        repairs=1,
        state=seed,
    )

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "no_progress"
    assert sum(
        fact.content.get("code") == "completion_not_verified"
        for fact in store.state.facts
    ) == 1


def test_research_readback_failure_has_executable_repair_instruction() -> None:
    message = AgentRuntime._evidence_repair_instruction(
        "no exact read-back fact proves the research artifact"
    )

    assert "read_file" in message
    assert "build_citation_manifest" in message
    assert "rewrite the citation sidecar" in message


def test_invented_url_failure_has_executable_repair_instruction() -> None:
    message = AgentRuntime._evidence_repair_instruction(
        "artifact contains an invented URL"
    )

    assert "web_extracted_content origin_locator" in message
    assert "edit_file" in message
    assert "rebuild" in message


def test_pregoal_source_receipt_failure_requires_current_goal_retrieval() -> None:
    message = AgentRuntime._evidence_repair_instruction(
        "source receipt is not bound to the current Goal"
    )

    assert "before this Goal" in message
    assert "materially different" in message
    assert "current-Goal source refs" in message


def test_missing_source_class_repair_requires_new_grounded_source() -> None:
    message = AgentRuntime._evidence_repair_instruction(
        "required source class is not cited"
    )

    assert "history or workspace source" in message
    assert "new source ref" in message
    assert "rewrite both targets" in message


def test_existing_source_classes_are_remapped_without_retrieval() -> None:
    for reason in (
        "required source class is not cited",
        "required source kind is not cited",
    ):
        message = AgentRuntime._evidence_repair_instruction(reason)

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

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "no_progress"
    assert sum(
        fact.content.get("code") == "no_progress_replan_required"
        for fact in store.state.facts
    ) == 1


def test_materially_different_nonexecuted_tool_attempts_can_replan_to_completion() -> None:
    result, store = _run(
        ScriptedProvider(
            ModelResponse((ModelToolCall("unknown-1", "unknown_tool_a", {}),)),
            ModelResponse((ModelToolCall("unknown-2", "unknown_tool_b", {}),)),
            ModelResponse((ModelToolCall("unknown-3", "unknown_tool_c", {}),)),
            ModelResponse((ModelTextBlock("replanned final"),)),
        ),
        repairs=1,
    )

    assert result.status is RunStatus.COMPLETED
    assert result.message == "replanned final"
    assert store.state.active_run is None


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
    assert sum(fact.kind is FactKind.TOOL_RESULT for fact in store.state.facts) == 6


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
        ScriptedProvider(*repeated, ModelResponse((ModelTextBlock("late final"),))),
        repairs=1,
        tools=(RegisteredTool(spec, lambda intent: "unchanged"),),
    )

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "no_progress"
    assert sum(
        fact.content.get("code") == "no_progress_replan_required"
        for fact in store.state.facts
    ) == 1


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
        ScriptedProvider(*responses),
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

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "no_progress"
    assert calls == 0
    assert any(
        fact.content.get("code") == "no_progress_replan_required"
        and "not currently available" in fact.content.get("text", "")
        for fact in store.state.facts
    )
