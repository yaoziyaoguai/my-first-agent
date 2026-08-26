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
    ModelResponse,
    ModelTextBlock,
    ProviderDescriptor,
    Resume,
    RunStatus,
    SubmitMessage,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider


def _descriptor(*, model: str = "remote-model") -> ProviderDescriptor:
    return ProviderDescriptor(
        family="openai_compatible",
        model=model,
        canonical_destination="https://api.example.com/v1/chat/completions",
        trust_profile="remote-https-v1",
        remote=True,
    )


def _runtime(state: ConversationState, descriptor: ProviderDescriptor | None):
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("done"),)))
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


def test_model_destination_or_data_class_change_invalidates_receipt() -> None:
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
