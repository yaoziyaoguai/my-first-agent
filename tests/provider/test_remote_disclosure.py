from __future__ import annotations

from dataclasses import replace

from agent.memory.preferences import (
    OwnerPreferenceSource,
    OwnerPreferenceStore,
    PreferenceAdmission,
)
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    AcknowledgeProviderDisclosure,
    ActiveRunStatus,
    BeginAnswer,
    ConversationFact,
    ConversationState,
    FactKind,
    GoalStatus,
    ModelResponse,
    ModelTextBlock,
    PauseGoal,
    ProviderDescriptor,
    Resume,
    ResumeGoal,
    RunStatus,
    SubmitMessage,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    ScriptedResponse,
    conversation_with_active_goal,
    goal_noop_response,
)


def _descriptor(*, model: str = "remote-model") -> ProviderDescriptor:
    return ProviderDescriptor(
        family="openai_compatible",
        model=model,
        canonical_destination="https://api.example.com/v1/chat/completions",
        trust_profile="remote-https-v1",
        remote=True,
    )


def _runtime(
    state: ConversationState,
    descriptor: ProviderDescriptor | None,
    responses: tuple[ScriptedResponse, ...] | None = None,
):
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(
        *(responses if responses is not None else (ModelResponse((ModelTextBlock("done"),)),))
    )
    runtime = AgentRuntime(
        provider=provider,
        provider_descriptor=descriptor,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-disclosure",
    )
    return runtime, store, provider


def _submit(state: ConversationState) -> SubmitMessage:
    return SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-1",
        message="hello",
    )


def test_first_remote_generate_requires_disclosure_and_send_count_is_zero() -> None:
    runtime, store, provider = _runtime(ConversationState.new("conversation-1"), _descriptor())

    result = runtime.run_turn(_submit(store.state), store.load())

    assert result.status is RunStatus.AWAITING_DISCLOSURE
    assert provider.calls == []
    assert store.state.provider_disclosure_request is not None
    assert store.state.provider_disclosure_receipt is None
    assert store.state.provider_disclosure_request.data_classes == (
        "system_policy",
        "user_messages",
    )


def test_exact_acknowledgement_allows_one_bound_context_pack() -> None:
    runtime, store, provider = _runtime(ConversationState.new("conversation-1"), _descriptor())
    runtime.run_turn(_submit(store.state), store.load())
    request = store.state.provider_disclosure_request
    assert request is not None
    ack = AcknowledgeProviderDisclosure(
        conversation_id=store.state.conversation_id,
        action_seq=store.state.next_action_seq,
        expected_revision=store.state.revision,
        request_digest=request.request_digest,
        acknowledged_at="2026-08-02T01:00:00Z",
    )

    result = runtime.run_turn(ack, store.load())

    assert result.status is RunStatus.COMPLETED
    assert result.message == "done"
    assert len(provider.calls) == 1
    assert provider.calls[0].data_classes == request.data_classes
    assert store.state.provider_disclosure_receipt is not None
    assert store.state.provider_disclosure_receipt.request_digest == request.request_digest


def test_pending_disclosure_survives_goal_pause_and_ack_continues_after_resume() -> None:
    """E1-B 真实缺口（2026-10-17）：/pause 恰落在 pending provider disclosure 上时，
    active run 被停掉但挂起披露仍 durable。新进程 /resume 后，精确 ack 必须可应答
    并点燃继续回合（与 SubmitMessage 同型点火），而不是静默 idle 丢掉挂起回合。"""

    runtime, store, provider = _runtime(
        conversation_with_active_goal(),
        _descriptor(),
        responses=(
            ModelResponse((ModelTextBlock("sent"),)),
            goal_noop_response("correlation-resume-2"),
        ),
    )
    runtime.run_turn(_submit(store.state), store.load())
    request = store.state.provider_disclosure_request
    assert request is not None

    def _control(action_cls, **kwargs):
        state = store.state
        goal = state.goal
        assert goal is not None
        return action_cls(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            goal_id=goal.goal_id,
            goal_revision=goal.revision,
            **kwargs,
        )

    paused = runtime.run_turn(_control(PauseGoal), store.load())
    assert paused.message == "goal paused at a safe boundary"
    assert store.state.active_run is None
    assert store.state.goal.status is GoalStatus.PAUSED
    assert store.state.provider_disclosure_request is not None

    resumed = runtime.run_turn(_control(ResumeGoal), store.load())
    assert resumed.message == "goal resumed"
    assert store.state.goal.status is GoalStatus.GOAL_READY
    assert store.state.active_run is None
    assert store.state.provider_disclosure_request is not None
    assert store.state.provider_disclosure_receipt is None

    state = store.state
    ack = AcknowledgeProviderDisclosure(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_digest=request.request_digest,
        acknowledged_at="2026-10-17T00:00:00Z",
    )
    ignited = runtime.run_turn(ack, store.load())

    # 恢复后的上下文多了 pause/resume 控制回执：数据类集合变化按既有合同要求
    # 新披露。第一步 ack 的职责是点燃继续回合（active run 回来），而不是免检。
    assert ignited.status is RunStatus.AWAITING_DISCLOSURE
    assert store.state.active_run is not None
    assert store.state.active_run.status is ActiveRunStatus.AWAITING_DISCLOSURE
    renewed = store.state.provider_disclosure_request
    assert renewed is not None and renewed.request_digest != request.request_digest
    assert renewed.data_classes != request.data_classes
    assert store.state.provider_disclosure_receipt is None

    state = store.state
    final_ack = AcknowledgeProviderDisclosure(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_digest=renewed.request_digest,
        acknowledged_at="2026-10-17T00:01:00Z",
    )
    result = runtime.run_turn(final_ack, store.load())

    # 恢复的回合真实发出（修复前此处 0 发送、静默 idle）；有限脚本下 run 停在
    # 下一次数据类增长的新披露上——与既有「数据类变更需重新披露」合同一致，
    # 不是免检直通。
    assert result.status is RunStatus.AWAITING_DISCLOSURE
    assert len(provider.calls) == 2
    assert store.state.provider_disclosure_receipt is None
    third = store.state.provider_disclosure_request
    assert third is not None and third.request_digest != renewed.request_digest


def test_release_b_orphan_refusal_via_repl_keeps_zero_egress_delta() -> None:
    """B（2026-10-18）：生产 Runtime 走 Submit→Pause→Resume 到达恢复形状后，
    REPL 输入 n 必须安全退出——零 provider 请求、零业务消息、零 receipt、
    零状态演进，任务与 pending 决策原样保留。"""

    runtime, store, provider = _runtime(
        conversation_with_active_goal(),
        _descriptor(),
        responses=(ModelResponse((ModelTextBlock("sent"),)),),
    )
    runtime.run_turn(_submit(store.state), store.load())
    assert provider.calls == []

    def _control(action_cls):  # noqa: ANN001
        state = store.state
        goal = state.goal
        assert goal is not None
        return action_cls(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            goal_id=goal.goal_id,
            goal_revision=goal.revision,
        )

    runtime.run_turn(_control(PauseGoal), store.load())
    resumed = runtime.run_turn(_control(ResumeGoal), store.load())
    assert resumed.message == "goal resumed"
    assert store.state.active_run is None
    assert store.state.goal is not None
    assert store.state.goal.status is GoalStatus.GOAL_READY
    before = store.state
    output: list[str] = []

    from agent.cli.app import run_repl

    exit_code = run_repl(
        runtime,
        store,
        input_fn=lambda _prompt: "n",
        write_fn=output.append,
        run_id_factory=lambda: "run-refuse",
    )

    assert exit_code == 0
    assert provider.calls == []
    assert output[-1] == (
        "The pending disclosure was not sent. The task is preserved; leaving this session."
    )
    assert store.state == before
    assert store.state.provider_disclosure_request is not None
    assert store.state.provider_disclosure_receipt is None
    runtime, store, provider = _runtime(ConversationState.new("conversation-1"), _descriptor())
    runtime.run_turn(_submit(store.state), store.load())
    request = store.state.provider_disclosure_request
    assert request is not None
    stale = request.acknowledge(
        receipt_id="receipt-stale",
        acknowledged_action_seq=2,
        acknowledged_at="2026-08-02T01:00:00Z",
    )
    # 模拟已确认旧模型后继续同一个 paused run；新 descriptor 必须先生成新 disclosure。
    store.state = replace(
        store.state,
        provider_disclosure_receipt=stale,
        active_run=replace(
            store.state.active_run,
            status=ActiveRunStatus.RUNNABLE,
        ),
    )
    changed = AgentRuntime(
        provider=provider,
        provider_descriptor=_descriptor(model="changed-model"),
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-changed",
    )
    resume = Resume(
        conversation_id=store.state.conversation_id,
        action_seq=store.state.next_action_seq,
        expected_revision=store.state.revision,
    )

    result = changed.run_turn(resume, store.load())

    assert result.status is RunStatus.AWAITING_DISCLOSURE
    assert provider.calls == []
    assert store.state.provider_disclosure_receipt is None
    assert store.state.provider_disclosure_request.model == "changed-model"


def test_fake_local_provider_does_not_request_remote_disclosure() -> None:
    local = ProviderDescriptor(
        family="fake",
        model="fake",
        canonical_destination="http://127.0.0.1/fake",
        trust_profile="local-no-network-v1",
        remote=False,
    )
    runtime, store, provider = _runtime(ConversationState.new("conversation-1"), local)

    result = runtime.run_turn(_submit(store.state), store.load())

    assert result.status is RunStatus.COMPLETED
    assert len(provider.calls) == 1
    assert store.state.provider_disclosure_request is None


def test_context_pack_closed_data_classes_bind_exact_receipt() -> None:
    runtime, store, _provider = _runtime(ConversationState.new("conversation-1"), _descriptor())
    runtime.run_turn(_submit(store.state), store.load())
    request = store.state.provider_disclosure_request
    assert request is not None
    assert tuple(sorted(set(request.data_classes))) == request.data_classes
    assert request.request_digest == request._expected_digest()


def test_owner_preference_category_requires_new_acknowledgement(tmp_path) -> None:
    runtime, store, _provider = _runtime(
        ConversationState.new("conversation-1"),
        _descriptor(),
    )
    runtime.run_turn(_submit(store.state), store.load())
    first_request = store.state.provider_disclosure_request
    assert first_request is not None
    runtime.run_turn(
        AcknowledgeProviderDisclosure(
            conversation_id=store.state.conversation_id,
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            request_digest=first_request.request_digest,
            acknowledged_at="2026-08-02T01:00:00Z",
        ),
        store.load(),
    )
    preference_store = OwnerPreferenceStore.create(
        tmp_path / "preferences.json",
        provider_trust_digest="trust-1",
    )
    preference_store.confirm(
        PreferenceAdmission.from_user_fact(
            ConversationFact(
                "user-preference-1",
                FactKind.USER_MESSAGE,
                {"text": "Prefer concise answers"},
            ),
            content="Prefer concise answers",
            confirmed=True,
        )
    )
    provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer("begin-owner-preferences"))
    )
    changed = AgentRuntime(
        provider=provider,
        provider_descriptor=_descriptor(),
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
            sources=(OwnerPreferenceSource(preference_store),),
            workspace_identity_digest="workspace-1",
            context_scope_digest="workspace-1",
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
    )

    result = changed.run_turn(_submit(store.state), store.load())

    assert result.status is RunStatus.AWAITING_DISCLOSURE
    assert provider.calls == []
    intent_request = store.state.provider_disclosure_request
    assert intent_request is not None
    assert "owner_preferences" not in intent_request.data_classes

    result = changed.run_turn(
        AcknowledgeProviderDisclosure(
            conversation_id=store.state.conversation_id,
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            request_digest=intent_request.request_digest,
            acknowledged_at="2026-08-02T01:01:00Z",
        ),
        store.load(),
    )

    assert result.status is RunStatus.AWAITING_DISCLOSURE
    assert len(provider.calls) == 1, "intent must be chosen before preferences are loaded"
    request = store.state.provider_disclosure_request
    assert request is not None
    assert "owner_preferences" in request.data_classes
    assert request.request_digest != intent_request.request_digest


def test_event_loss_cannot_bypass_durable_disclosure() -> None:
    state = ConversationState.new("conversation-1")
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("must not send"),)))
    runtime = AgentRuntime(
        provider=provider,
        provider_descriptor=_descriptor(),
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(fail=True),
        limits=InvocationLimits(),
    )

    result = runtime.run_turn(_submit(state), store.load())

    assert result.status is RunStatus.AWAITING_DISCLOSURE
    assert result.delivery_warnings
    assert store.load().state.provider_disclosure_request is not None
    assert provider.calls == []
