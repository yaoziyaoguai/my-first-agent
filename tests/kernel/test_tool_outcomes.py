from __future__ import annotations

import pytest

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRunStatus,
    ApprovalPolicy,
    BlockedClaim,
    ConversationState,
    EvidenceOracleKind,
    ExecutionAuthorityClass,
    FactKind,
    KnownExecutedError,
    KnownNotExecuted,
    ModelResponse,
    ModelToolCall,
    OutputPolicy,
    ProposedCriterion,
    ResolveApproval,
    RunStatus,
    SideEffectClass,
    SubmitMessage,
    ToolPrepareContext,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    conversation_with_active_goal,
    goal_noop_response,
)


def _write_spec(name: str) -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name=name,
        version="1",
        description="fixture write tool",
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={},
        output_limit_chars=64,
    )


def _build(registrations, provider_responses):
    provider = ScriptedProvider(
        goal_noop_response("tool-outcome-user-supplement"),
        *provider_responses,
    )
    # 本文件全部场景都要执行 effectful 工具,统一从已建立 Goal 的 seed 起步。
    store = InMemoryCheckpointStore(conversation_with_active_goal())
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(registrations),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    return runtime, store, provider


def _submit(state: ConversationState) -> SubmitMessage:
    return SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id=f"run-{state.next_action_seq}",
        message="do it",
    )


def _blocked_response(correlation_id: str, message: str) -> ModelResponse:
    return ModelResponse(
        (),
        control=BlockedClaim(
            correlation_id=correlation_id,
            goal_id="goal-1",
            goal_revision=1,
            blocker=message,
            safe_attempts=("classified the tool outcome",),
            resume_condition="provide a closed completion oracle",
        ),
    )


def test_known_not_executed_advances_cursor_without_recovery() -> None:
    def maybe_write(intent) -> KnownNotExecuted:
        # effect 之前证明 precondition 漂移，副作用没有发生。
        return KnownNotExecuted(
            code="precondition_drift",
            message="target changed before the effect",
        )

    runtime, store, provider = _build(
        (RegisteredTool(_write_spec("guarded_write"), maybe_write),),
        (
            ModelResponse((ModelToolCall("call-1", "guarded_write", {}),)),
            _blocked_response("known-not-executed-blocked", "done"),
        ),
    )

    result = runtime.run_turn(_submit(store.state), store.load())

    assert result.status is RunStatus.COMPLETED
    assert len(provider.calls) == 3
    tool_result_facts = [
        fact
        for fact in store.state.facts
        if fact.kind is FactKind.TOOL_RESULT and fact.content.get("tool_call_id") == "call-1"
    ]
    assert len(tool_result_facts) == 1
    assert tool_result_facts[0].content["executed"] is False
    # 没有 synthetic recovery fact：known-not-executed 不进入 unknown-outcome recovery。
    assert not any(fact.content.get("synthetic") for fact in store.state.facts)
    assert store.state.active_run is None


def test_unknown_write_exception_enters_recovery() -> None:
    def boom(intent) -> str:
        raise RuntimeError("effect may already have happened")

    runtime, store, provider = _build(
        (RegisteredTool(_write_spec("unsafe_write"), boom),),
        (ModelResponse((ModelToolCall("call-1", "unsafe_write", {}),)),),
    )

    result = runtime.run_turn(_submit(store.state), store.load())

    assert result.status is RunStatus.AWAITING_RECOVERY
    assert result.request is not None
    assert len(provider.calls) == 2
    assert store.state.active_run is not None
    assert store.state.active_run.status is ActiveRunStatus.AWAITING_RECOVERY


def test_stale_approval_is_nonfatal_nonexecution() -> None:
    """A16: when an approved grant's precondition drifts before invocation, the run must
    record a known-not-executed approval_mismatch result with zero effects and continue,
    NOT become FAILED_FATAL from a retained grant violating the MODEL-phase invariant.
    """
    effect_calls = []
    precondition_box = {"digest": "original"}

    def prepare_binding(arguments):
        return {
            "effect_preview": "write fixture",
            "target_digest": "target",
            "precondition_digest": precondition_box["digest"],
        }

    def write_func(intent) -> str:
        effect_calls.append(intent.tool_call_id)
        return "written"

    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="write_fixture",
        version="1",
        description="fixture write",
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={},
        output_limit_chars=64,
    )
    registration = RegisteredTool(spec, write_func, prepare_binding=prepare_binding)
    runtime, store, provider = _build(
        (registration,),
        (
            ModelResponse((ModelToolCall("call-1", "write_fixture", {}),)),
            _blocked_response("stale-approval-blocked", "done after mismatch"),
        ),
    )

    first = runtime.run_turn(_submit(store.state), store.load())
    assert first.status is RunStatus.AWAITING_APPROVAL
    assert first.request is not None

    # approval pause 后漂移 precondition；旧 grant 的 binding 不再匹配。
    precondition_box["digest"] = "tampered"
    resolve = ResolveApproval(
        conversation_id="conversation-1",
        action_seq=store.state.next_action_seq,
        expected_revision=store.state.revision,
        request_id=first.request.request_id,
        binding_digest=first.request.binding_digest,
        approved=True,
    )
    result = runtime.run_turn(resolve, store.load())

    assert result.status is not RunStatus.FAILED_FATAL
    assert effect_calls == []  # callable 从未执行
    tool_results = [
        fact
        for fact in store.state.facts
        if fact.kind is FactKind.TOOL_RESULT and fact.content.get("tool_call_id") == "call-1"
    ]
    assert tool_results
    assert tool_results[0].content["executed"] is False
    assert result.status is RunStatus.COMPLETED


def test_known_executed_errors_are_not_success() -> None:
    """A18: a known-executed failure (remote isError / unsupported content / child nonterminal)
    must surface as executed=True, is_error=True with a code, never flattened into a success
    string. Unclassified external failure stays unknown (recovery), not downgraded here.
    """

    def remote_failure(intent) -> KnownExecutedError:
        return KnownExecutedError(code="remote_error", message="remote tool reported isError")

    runtime, store, provider = _build(
        (RegisteredTool(_write_spec("remote_tool"), remote_failure),),
        (
            ModelResponse((ModelToolCall("call-1", "remote_tool", {}),)),
            _blocked_response("known-executed-error-blocked", "done"),
        ),
    )
    result = runtime.run_turn(_submit(store.state), store.load())

    assert result.status is RunStatus.COMPLETED
    tool_results = [
        fact
        for fact in store.state.facts
        if fact.kind is FactKind.TOOL_RESULT and fact.content.get("tool_call_id") == "call-1"
    ]
    assert tool_results
    assert tool_results[0].content["executed"] is True
    assert tool_results[0].content["is_error"] is True
    assert tool_results[0].content["metadata"]["code"] == "remote_error"


def test_artifact_confirmation_ambiguity_message_names_criteria_and_remedy() -> None:
    # 真实 E3（016 第 23 轮 J12）证明:process approval 撞上多个 filesystem
    # criterion 时,旧消息只陈述规则,模型无法自纠而被困到 blocked。消息必须点名
    # 冲突 criteria(id + path/deferred)并给出明确恢复动作。
    context = ToolPrepareContext(
        conversation_id="conv",
        run_id="run",
        state_revision=1,
        proposed_criteria=(
            ProposedCriterion(
                criterion_id="crit-report",
                description="report written",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path="report.md",
            ),
            ProposedCriterion(
                criterion_id="crit-check",
                description="validator ledger",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path=None,
            ),
        ),
    )
    with pytest.raises(ValueError) as excinfo:
        KernelToolRuntime._artifact_confirmation_requirement(context)
    message = str(excinfo.value)
    assert "crit-report" in message
    assert "report.md" in message
    assert "crit-check" in message
    assert "deferred" in message
    assert "goal_delta_proposal" in message


def test_artifact_confirmation_ignores_already_admitted_criteria() -> None:
    # 016 真实 E3 第 23/27/34 轮:写批准后 criterion 同时保留在 proposed 与
    # admitted;不过滤已确认项时,[已确认 report.md + validator criterion] 会被
    # 误判为"多个 pending artifact 义务"而 fail-closed 死锁。已 admitted 的
    # criterion 不再计入 process 绑定;剩余唯一 bound criterion 正常出 requirement。
    admitted_report = ProposedCriterion(
        criterion_id="crit-report",
        description="report written",
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        artifact_path="report.md",
    )
    validator = ProposedCriterion(
        criterion_id="crit-validator",
        description="validator ledger",
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        artifact_path=".process-invocations",
    )
    context = ToolPrepareContext(
        conversation_id="conv",
        run_id="run",
        state_revision=1,
        proposed_criteria=(admitted_report, validator),
        admitted_criterion_ids=frozenset({"crit-report"}),
    )
    requirement = KernelToolRuntime._artifact_confirmation_requirement(context)
    assert requirement is not None
    assert requirement.criterion_id == "crit-validator"
    assert requirement.artifact_path == ".process-invocations"


def test_artifact_confirmation_deferred_only_criterion_needs_no_requirement() -> None:
    # 唯一 pending filesystem criterion 仍是 deferred 时,process 批准没有可确认
    # 的 artifact(绑定只发生在具体文件写入批准,validator 产物不经 write_file)。
    # 返回 None 走普通批准,而不是 hard error 死锁(016 真实 E3 第 23/27/34 轮)。
    context = ToolPrepareContext(
        conversation_id="conv",
        run_id="run",
        state_revision=1,
        proposed_criteria=(
            ProposedCriterion(
                criterion_id="crit-check",
                description="validator ledger",
                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                artifact_path=None,
            ),
        ),
    )
    assert KernelToolRuntime._artifact_confirmation_requirement(context) is None
