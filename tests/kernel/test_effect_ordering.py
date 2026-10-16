from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    ApprovalPolicy,
    ApprovalRequest,
    CancelRun,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    EgressClass,
    ExecuteOperatorTool,
    ExecutionAuthorityClass,
    FactKind,
    InvocationOrigin,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    OutputPolicy,
    ResolveApproval,
    Resume,
    RunStatus,
    SideEffectClass,
    SubmitMessage,
    ToolCall,
    ToolExposure,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.state import (
    complete_run,
    end_run,
    mark_executing,
    pause_for_approval,
    record_tool_result,
    start_tool_batch,
)
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
from agent.tools.file_ops import build_file_tool_runtime
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    RecordingCheckpointStore,
    ScriptedProvider,
    conversation_with_active_goal,
    goal_noop_response,
)


def _runtime(
    store,
    provider,
    callable_,
    *,
    approval: ApprovalPolicy = ApprovalPolicy.NEVER,
    exposure: ToolExposure = ToolExposure.MODEL,
    event_sink=None,
):
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="write_fixture",
        version="1",
        description="Write fixture",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=approval,
        safety_policy={},
        output_limit_chars=20,
    )
    return AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
        ),
        tool_runtime=KernelToolRuntime(
            (RegisteredTool(spec, callable_, exposure=exposure),)
        ),
        checkpoint_store=store,
        event_sink=event_sink or CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )


def _action(state: ConversationState) -> SubmitMessage:
    # 从当前状态派生序列,兼容 seeded(带 Goal)与全新会话两种起点。
    return SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id=f"run-{state.next_action_seq}",
        message="write",
    )


def test_cas_failure_before_executing_invokes_zero_callables() -> None:
    calls = 0

    def effect(intent) -> str:
        nonlocal calls
        calls += 1
        return "done"

    # 已有 Goal 的用户补充先由 no-op delta 消费并记录 replan；save#6 才是
    # EXECUTING checkpoint。注入点必须命中 mark_executing，断言才不空洞。
    store = InMemoryCheckpointStore(conversation_with_active_goal())
    store.fail_on_save = 6
    provider = ScriptedProvider(
        goal_noop_response("effect-cas-user-supplement"),
        ModelResponse((ModelToolCall("call-1", "write_fixture", {}),)),
    )

    result = _runtime(store, provider, effect).run_turn(_action(store.state), store.load())

    assert result.status is RunStatus.FAILED_FATAL
    assert calls == 0


def test_result_save_failure_enters_unknown_outcome_recovery() -> None:
    calls = 0

    def effect(intent) -> str:
        nonlocal calls
        calls += 1
        return "done"

    store = InMemoryCheckpointStore(conversation_with_active_goal())
    # 前台调用现在会先持久化 durable model-attempt 计数；目标仍是
    # effect 已执行后保存结果失败的 unknown-outcome 边界。
    store.fail_on_save = 9
    provider = ScriptedProvider(
        goal_noop_response("effect-save-user-supplement"),
        ModelResponse((ModelToolCall("call-1", "write_fixture", {}),)),
        ModelResponse((ModelTextBlock("must not auto retry"),)),
    )

    result = _runtime(store, provider, effect).run_turn(_action(store.state), store.load())

    assert result.status is RunStatus.AWAITING_RECOVERY
    assert calls == 1
    assert len(provider.calls) == 2
    assert store.state.active_run is not None
    assert store.state.active_run.status.value == "awaiting_recovery"


def test_directory_result_save_failure_requires_recovery_without_replay(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class FailDirectoryResultOnce(InMemoryCheckpointStore):
        failed = False

        def compare_and_swap(self, snapshot, new_state):
            new_facts = new_state.facts[len(self.state.facts) :]
            if (
                not self.failed
                and (workspace / "reports").is_dir()
                and any(fact.kind is FactKind.TOOL_RESULT for fact in new_facts)
            ):
                self.failed = True
                raise RuntimeError("injected directory result checkpoint failure")
            return super().compare_and_swap(snapshot, new_state)

    store = FailDirectoryResultOnce(conversation_with_active_goal())
    provider = ScriptedProvider(
        goal_noop_response("directory-result-user-supplement"),
        ModelResponse(
            (ModelToolCall("mkdir-1", "make_directory", {"path": "reports"}),)
        ),
        ModelResponse((ModelTextBlock("must not run after unknown directory result"),)),
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
        ),
        tool_runtime=build_file_tool_runtime(workspace),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-directory-result",
    )
    first = runtime.run_turn(_action(store.state), store.load())
    assert first.status is RunStatus.AWAITING_APPROVAL
    assert first.request is not None

    failed = runtime.run_turn(
        ResolveApproval(
            conversation_id=store.state.conversation_id,
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            request_id=first.request.request_id,
            binding_digest=first.request.binding_digest,
            approved=True,
        ),
        store.load(),
    )

    assert failed.status is RunStatus.AWAITING_RECOVERY
    assert (workspace / "reports").is_dir()
    assert len(provider.calls) == 2
    assert store.state.active_run is not None
    assert store.state.active_run.status.value == "awaiting_recovery"

    resumed = runtime.run_turn(
        Resume(
            conversation_id=store.state.conversation_id,
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
        ),
        store.load(),
    )

    assert resumed.status is RunStatus.CONFLICT
    assert resumed.error_code == "illegal_action_for_state"
    assert len(provider.calls) == 2
    assert (workspace / "reports").is_dir()


def test_declining_first_directory_in_batch_causes_zero_effects(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = InMemoryCheckpointStore(conversation_with_active_goal())
    provider = ScriptedProvider(
        goal_noop_response("directory-decline-user-supplement"),
        ModelResponse(
            (
                ModelToolCall("mkdir-1", "make_directory", {"path": "reports"}),
                ModelToolCall(
                    "mkdir-2",
                    "make_directory",
                    {"path": "reports/2026"},
                ),
                ModelToolCall(
                    "write-1",
                    "write_file",
                    {
                        "path": "reports/2026/daily.md",
                        "content": "must not be written",
                    },
                ),
            )
        ),
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
        ),
        tool_runtime=build_file_tool_runtime(workspace),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-directory-decline",
    )

    pending = runtime.run_turn(_action(store.state), store.load())
    assert pending.status is RunStatus.AWAITING_APPROVAL
    assert pending.request is not None

    declined = runtime.run_turn(
        ResolveApproval(
            conversation_id=store.state.conversation_id,
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            request_id=pending.request.request_id,
            binding_digest=pending.request.binding_digest,
            approved=False,
        ),
        store.load(),
    )

    assert declined.status is RunStatus.CANCELLED
    assert declined.error_code == "approval_declined"
    assert len(provider.calls) == 2
    assert not (workspace / "reports").exists()


def test_write_callable_exception_enters_unknown_outcome_recovery() -> None:
    calls = 0

    def effect_then_fail(intent) -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("failure after possible effect")

    store = InMemoryCheckpointStore(conversation_with_active_goal())
    provider = ScriptedProvider(
        goal_noop_response("effect-exception-user-supplement"),
        ModelResponse((ModelToolCall("call-1", "write_fixture", {}),)),
        ModelResponse((ModelTextBlock("must not auto retry"),)),
    )

    result = _runtime(store, provider, effect_then_fail).run_turn(
        _action(store.state),
        store.load(),
    )

    assert result.status is RunStatus.AWAITING_RECOVERY
    assert calls == 1
    assert len(provider.calls) == 2
    assert store.state.active_run is not None
    assert store.state.active_run.status.value == "awaiting_recovery"


def test_operator_tool_uses_same_approval_executing_result_order() -> None:
    calls: list[str] = []
    state = replace(
        conversation_with_active_goal(),
        active_run=ActiveRun(run_id="run-existing"),
    )
    store = RecordingCheckpointStore(state)
    provider = ScriptedProvider()
    events = CollectingSink()
    runtime = _runtime(
        store,
        provider,
        lambda intent: calls.append(intent.tool_call_id) or "private result",
        approval=ApprovalPolicy.ALWAYS,
        exposure=ToolExposure.OPERATOR,
        event_sink=events,
    )
    action = ExecuteOperatorTool(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        action_id="operator-action-1",
        tool_name="write_fixture",
        arguments={},
        submitted_at="2026-08-30T12:00:00Z",
    )

    first = runtime.run_turn(action, store.load())

    assert first.status is RunStatus.AWAITING_APPROVAL
    assert calls == []
    pending = store.load()
    assert pending.state.active_run.invocation_origin is InvocationOrigin.OPERATOR
    assert first.request is not None
    second = runtime.run_turn(
        ResolveApproval(
            conversation_id=pending.state.conversation_id,
            action_seq=pending.state.next_action_seq,
            expected_revision=pending.state.revision,
            request_id=first.request.request_id,
            binding_digest=first.request.binding_digest,
            approved=True,
        ),
        pending,
    )

    assert second.status is RunStatus.COMPLETED
    assert calls == ["operator-action-1"]
    assert store.saved_phases.index("executing") < store.saved_fact_kinds.index(
        "tool_result"
    )
    assert provider.calls == []
    assert "private result" not in repr(events.events)


class _SemanticWriteFailure(InMemoryCheckpointStore):
    """按保存状态语义注入写失败，不绑定固定调用序号。

    R1 合同：效果已执行后 result 保存失败、且随后 recovery 保存也失败时，
    不能把 run 清成"确定未执行"。注入点按 attempted state 的语义判定
    （EXECUTING 相 + 携带 tool_result fact / AWAITING_RECOVERY 相），
    与真实 LocalCheckpointStore 在 replace 前失败、旧快照仍有效的语义一致。
    ``recovery_failures`` 控制 result 保存失败后再失败几次 recovery 保存；
    ``permanent=True`` 表示之后所有保存持续失败。
    """

    def __init__(self, state, *, recovery_failures: int = 2, permanent: bool = False):
        super().__init__(state)
        self.recovery_failures = recovery_failures
        self.permanent = permanent
        self.result_save_failed = False
        self.recovery_failures_done = 0
        self.attempted_clears = 0
        self.failures: list[str] = []

    def compare_and_swap(self, snapshot, new_state):
        prior = len(self.state.facts)
        new_kinds = [fact.kind for fact in new_state.facts[prior:]]
        old_active = snapshot.state.active_run
        new_active = new_state.active_run
        if (
            old_active is not None
            and new_active is None
            and old_active.phase is ContinuationPhase.EXECUTING
        ):
            self.attempted_clears += 1
        is_result_save = (
            old_active is not None
            and old_active.phase is ContinuationPhase.EXECUTING
            and FactKind.TOOL_RESULT in new_kinds
        )
        is_recovery_save = (
            new_active is not None
            and new_active.status is ActiveRunStatus.AWAITING_RECOVERY
        )
        should_fail = False
        if is_result_save and not self.result_save_failed:
            self.result_save_failed = True
            self.failures.append("result")
            should_fail = True
        elif self.result_save_failed:
            if self.permanent:
                self.failures.append("permanent")
                should_fail = True
            elif is_recovery_save and (
                self.recovery_failures_done < self.recovery_failures
            ):
                self.recovery_failures_done += 1
                self.failures.append("recovery")
                should_fail = True
        if should_fail:
            raise RuntimeError("injected pre-commit write failure")
        return super().compare_and_swap(snapshot, new_state)


def test_unknown_effect_survives_result_and_recovery_save_failures() -> None:
    """R1-T1：效果执行后 result/recovery 连续保存失败，UNKNOWN 必须留存。

    存储恢复（后续保存重新成功）后：durable intent 仍在；Resume 进入既有
    recovery 分类流程；不生成"未执行"事实；不再调用 provider/tool。
    """

    calls: list[str] = []

    def effect(intent) -> str:
        calls.append("effect")
        return "done"

    store = _SemanticWriteFailure(
        conversation_with_active_goal(), recovery_failures=2
    )
    provider = ScriptedProvider(
        goal_noop_response("r1-t1-supplement"),
        ModelResponse((ModelToolCall("call-1", "write_fixture", {}),)),
        ModelResponse((ModelTextBlock("must not run without classification"),)),
    )
    runtime = _runtime(store, provider, effect)

    result = runtime.run_turn(_action(store.state), store.load())

    assert calls == ["effect"], "the effect must have run exactly once"
    durable = store.load().state
    active = durable.active_run
    assert active is not None, (
        "UNKNOWN must stay durable: the active run cannot be cleared after a "
        "tool effect whose result and recovery checkpoints both failed to save"
    )
    assert store.attempted_clears == 0, (
        "no CAS may even attempt to clear the EXECUTING run while the effect "
        "outcome is unclassified"
    )
    intent = active.executing_intent
    assert intent is not None
    assert intent.tool_call_id == "call-1"
    assert active.phase is ContinuationPhase.EXECUTING
    assert active.batch_cursor == 0
    assert active.tool_calls[0].tool_call_id == "call-1"
    assert result.status is not RunStatus.FAILED_FATAL or active is not None
    assert not any(
        fact.kind is FactKind.TOOL_RESULT
        and fact.content.get("tool_call_id") == "call-1"
        for fact in durable.facts
    ), "no fabricated executed/not-executed result may be recorded"

    # 存储恢复后 Resume 进入既有 recovery 分类流程，不重放效果。
    resumed = runtime.run_turn(
        Resume(
            conversation_id=durable.conversation_id,
            action_seq=durable.next_action_seq,
            expected_revision=durable.revision,
        ),
        store.load(),
    )
    assert resumed.status is RunStatus.AWAITING_RECOVERY
    assert calls == ["effect"]
    assert len(provider.calls) == 2, "no extra provider call may happen on resume"
    recovered = store.load().state
    assert recovered.active_run is not None
    assert recovered.active_run.status is ActiveRunStatus.AWAITING_RECOVERY
    assert recovered.active_run.pending_request is not None


def test_all_followup_saves_failing_reports_persistence_failure_honestly() -> None:
    """R1-T2：所有后续保存继续失败时，durable EXECUTING 保留且如实报错。"""

    calls: list[str] = []

    def effect(intent) -> str:
        calls.append("effect")
        return "done"

    store = _SemanticWriteFailure(
        conversation_with_active_goal(), permanent=True
    )
    provider = ScriptedProvider(
        goal_noop_response("r1-t2-supplement"),
        ModelResponse((ModelToolCall("call-1", "write_fixture", {}),)),
    )
    runtime = _runtime(store, provider, effect)

    result = runtime.run_turn(_action(store.state), store.load())

    assert calls == ["effect"]
    durable = store.load().state
    active = durable.active_run
    assert active is not None
    assert active.phase is ContinuationPhase.EXECUTING
    assert active.executing_intent is not None
    assert active.executing_intent.tool_call_id == "call-1"
    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "recovery_persistence_failed"
    assert store.attempted_clears == 0, (
        "no attempt to clear the EXECUTING run may happen while every "
        "follow-up save keeps failing"
    )
    assert any(
        "persistence" in warning or "failed" in warning
        for warning in result.delivery_warnings
    ), "persistence failure must be reported, not silently swallowed"
    assert not any(
        fact.kind is FactKind.TOOL_RESULT for fact in durable.facts
    )


def test_cancel_run_closes_unstarted_suffix_in_same_transition() -> None:
    """R1-T4：多调用批次第一项成功、第二项待批准时 CancelRun 分流。

    已执行 prefix 结果保持原值；cursor 之后（含待批准项）确定未开始，
    与清空 run 落在同一 CAS，不产生重复调用/结果。
    """

    seed = conversation_with_active_goal()
    state = replace(seed, active_run=ActiveRun(run_id="run-batch"))
    state = start_tool_batch(
        state,
        (
            ToolCall("call-1", "write_fixture", {}),
            ToolCall("call-2", "write_fixture", {}),
        ),
    )
    state = mark_executing(
        state,
        tool_call_id="call-1",
        intent_digest="digest-1",
        idempotency_key="key-1",
        side_effect=SideEffectClass.WRITE,
        egress=EgressClass.NONE,
        operation="write_fixture",
        request_identity="identity-1",
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
    )
    state = record_tool_result(
        state,
        ConversationFact(
            fact_id="run:run-batch:tool-result:call-1:0",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": "call-1",
                "text": "ok",
                "is_error": False,
                "executed": True,
            },
        ),
        intent_digest="digest-1",
    )
    state = pause_for_approval(
        state,
        ApprovalRequest(
            request_id="approval-2",
            run_id="run-batch",
            tool_call_id="call-2",
            binding_digest="binding-2",
            preview="write fixture",
            tool_name="write_fixture",
        ),
    )
    store = InMemoryCheckpointStore(state)
    runtime = AgentRuntime(
        provider=ScriptedProvider(),
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )

    cancelled = runtime.run_turn(
        CancelRun(
            conversation_id="conversation-1",
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
        ),
        store.load(),
    )

    assert cancelled.status is RunStatus.CANCELLED
    durable = store.load().state
    assert durable.active_run is None
    results = {
        fact.content["tool_call_id"]: fact.content
        for fact in durable.facts
        if fact.kind is FactKind.TOOL_RESULT
    }
    assert results["call-1"]["executed"] is True
    assert results["call-2"]["executed"] is False
    assert results["call-2"]["superseded"] is True


def test_capacity_end_run_closes_unstarted_tail_in_same_cas() -> None:
    """R1-T5：end_run/complete_run 在仍有未执行 tail 时结束，同一 CAS 先闭合。

    TOOL 相（含 AWAITING_APPROVAL）的 cursor 指向尚未 prepare/执行的首个
    call；终态转换必须把 calls[cursor:] 补记为确定非执行，并与清空 run 落在
    同一转换里。complete_run 追加的 assistant fact 位于闭合结果之后。
    """

    seed = conversation_with_active_goal()
    state = replace(seed, active_run=ActiveRun(run_id="run-batch"))
    state = start_tool_batch(
        state,
        (
            ToolCall("call-1", "write_fixture", {}),
            ToolCall("call-2", "write_fixture", {}),
        ),
    )
    state = mark_executing(
        state,
        tool_call_id="call-1",
        intent_digest="digest-1",
        idempotency_key="key-1",
        side_effect=SideEffectClass.WRITE,
        egress=EgressClass.NONE,
        operation="write_fixture",
        request_identity="identity-1",
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
    )
    state = record_tool_result(
        state,
        ConversationFact(
            fact_id="run:run-batch:tool-result:call-1:0",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": "call-1",
                "text": "ok",
                "is_error": False,
                "executed": True,
            },
        ),
        intent_digest="digest-1",
    )

    ended = end_run(
        state,
        status=RunStatus.CONVERSATION_LIMIT_REACHED,
        code="conversation_capacity",
        message="Conversation state has no safe capacity for another effect.",
    )

    assert ended.active_run is None
    results = {
        fact.content["tool_call_id"]: fact.content
        for fact in ended.facts
        if fact.kind is FactKind.TOOL_RESULT
    }
    assert results["call-1"]["executed"] is True
    assert results["call-2"]["executed"] is False
    assert results["call-2"]["superseded"] is True

    completed = complete_run(state, message="run completed")

    assert completed.active_run is None
    results = {
        fact.content["tool_call_id"]: fact.content
        for fact in completed.facts
        if fact.kind is FactKind.TOOL_RESULT
    }
    assert results["call-1"]["executed"] is True
    assert results["call-2"]["executed"] is False
    assert results["call-2"]["superseded"] is True
    kinds = [fact.kind for fact in completed.facts]
    assert kinds[-1] is FactKind.ASSISTANT_MESSAGE
    closed_position = next(
        index
        for index, fact in enumerate(completed.facts)
        if fact.kind is FactKind.TOOL_RESULT
        and fact.content["tool_call_id"] == "call-2"
    )
    assert closed_position == len(completed.facts) - 2


def test_terminal_and_replay_result_commit_atomically() -> None:
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    # durable model-attempt checkpoint 使 terminal commit 后移一次保存。
    store.fail_on_save = 4
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("done"),)))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    action = _action(store.state)

    failed = runtime.run_turn(action, store.load())
    replayed = runtime.run_turn(action, store.load())

    assert failed.status is RunStatus.FAILED_FATAL
    assert failed.error_code == "runtime_failure"
    assert store.state.active_run is None
    assert store.state.replay_records[-1].result is not None
    assert replayed.status is RunStatus.FAILED_FATAL
    assert replayed.replayed is True
    assert len(provider.calls) == 1
