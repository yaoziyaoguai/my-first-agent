from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from agent.runtime.context import ContextLimitError, ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ApprovalGrant,
    ApprovalPolicy,
    ApprovalRequired,
    ConversationFact,
    ConversationState,
    EgressClass,
    ExecutionAuthorityClass,
    ExecutionIntent,
    FactKind,
    OutputPolicy,
    PolicyDecision,
    ProviderDescriptor,
    ProviderDisclosureRequest,
    RunStatus,
    SideEffectClass,
    SourceKind,
    SourceReceiptDraft,
    SourceReceiptV1,
    SubmitMessage,
    ToolCall,
    ToolExecutionOutput,
    ToolPrepareContext,
    ToolResult,
    ToolRisk,
    ToolSpec,
    canonical_json_digest,
)
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    conversation_with_active_goal,
)


def _source_spec(
    *,
    egress: EgressClass = EgressClass.NONE,
    approval: ApprovalPolicy = ApprovalPolicy.NEVER,
    source_kind: SourceKind = SourceKind.WORKSPACE_EXCERPT,
) -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="source_fixture",
        version="1",
        description="Return one bounded source fixture.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=approval,
        safety_policy={"source_metadata_keys": ["count"]},
        output_limit_chars=2_000,
        egress=egress,
        source_kinds=(source_kind,),
    )


def _context(*, state_revision: int = 2, approval_basis_revision: int | None = None):
    return ToolPrepareContext(
        conversation_id="conversation-1",
        run_id="run-1",
        state_revision=state_revision,
        approval_basis_revision=approval_basis_revision,
    )


def _draft(
    *, source_kind: SourceKind = SourceKind.WORKSPACE_EXCERPT
) -> SourceReceiptDraft:
    return SourceReceiptDraft(
        source_kind=source_kind,
        origin_locator="notes/example.txt",
        content="grounded excerpt",
        observed_at="snapshot:1",
        snapshot_digest=canonical_json_digest({"path": "notes/example.txt", "revision": 1}),
    )


def _web_draft() -> SourceReceiptDraft:
    return SourceReceiptDraft(
        source_kind=SourceKind.WEB_SEARCH_SNIPPET,
        origin_locator="https://example.com/article",
        content="public excerpt",
        observed_at="2026-08-04T00:00:00Z",
        request_identity="request-1",
        origin_request_digest=canonical_json_digest({"query": "grounding"}),
    )


def _source_runtime(
    output: object,
    *,
    spec: ToolSpec | None = None,
    policy=None,
) -> KernelToolRuntime:
    return KernelToolRuntime(
        (
            RegisteredTool(
                spec or _source_spec(),
                lambda _intent: output,
                prepare_binding=lambda _arguments: {
                    "operation": "search",
                    "request_identity": "request-1",
                    "destination_digest": "destination-1",
                    "cost_class": "basic",
                },
                policy=policy,
            ),
        )
    )


def _prepare(runtime: KernelToolRuntime, context: ToolPrepareContext | None = None):
    return runtime.prepare(
        ToolCall("call-1", "source_fixture", {"query": "grounding"}),
        context or _context(),
    )


def test_kernel_mints_source_receipt_and_rejects_callable_owned_result() -> None:
    runtime = _source_runtime(
        ToolExecutionOutput(
            content="grounded excerpt",
            metadata={"count": 1},
            source_receipts=(_draft(),),
        )
    )
    intent = _prepare(runtime)
    assert isinstance(intent, ExecutionIntent)

    result = runtime.invoke(intent)

    assert result.is_error is False
    assert result.metadata["data_classes"] == ["workspace_excerpt"]
    receipt = result.metadata["source_receipts"][0]
    assert receipt["source_kind"] == "workspace_excerpt"
    assert receipt["conversation_id"] == "conversation-1"
    assert receipt["run_id"] == "run-1"
    assert receipt["intent_digest"] == intent.intent_digest
    assert receipt["content_digest"] == hashlib.sha256(
        b"grounded excerpt"
    ).hexdigest()

    forged_runtime = _source_runtime(ToolResult("call-1", "forged"))
    forged_intent = _prepare(forged_runtime)
    assert isinstance(forged_intent, ExecutionIntent)
    forged = forged_runtime.invoke(forged_intent)
    assert forged.is_error is True
    assert forged.metadata["code"] == "source_output_required"
    assert "source_receipts" not in forged.metadata


def test_source_receipt_identity_and_data_class_are_closed() -> None:
    runtime = _source_runtime(
        ToolExecutionOutput(content="grounded excerpt", source_receipts=(_draft(),))
    )
    intent = _prepare(runtime)
    assert isinstance(intent, ExecutionIntent)
    result = runtime.invoke(intent)
    raw = result.metadata["source_receipts"][0]
    receipt = SourceReceiptV1(
        **{
            **raw,
            "source_kind": SourceKind(raw["source_kind"]),
        }
    )

    with pytest.raises(ValueError, match="data class"):
        replace(receipt, data_class="system_policy")
    with pytest.raises(ValueError, match="source identity"):
        replace(receipt, source_id="source:v1:forged")

    changed = SourceReceiptV1.create(
        replace(_draft(), content="a corrected bounded excerpt"),
        intent,
    )
    assert changed.source_id == receipt.source_id
    assert changed.receipt_digest != receipt.receipt_digest


def test_source_output_limits_and_known_not_executed_shape_fail_closed() -> None:
    with pytest.raises(TypeError, match="content must be a string"):
        ToolExecutionOutput(content=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="JSON-compatible"):
        ToolExecutionOutput(content="bad", metadata={"count": object()})
    with pytest.raises(ValueError, match="cannot carry receipts"):
        ToolExecutionOutput(
            content="bad",
            source_receipts=(_draft(),),
            is_error=True,
            executed=False,
        )

    oversized_runtime = _source_runtime(
        ToolExecutionOutput(content="bounded", metadata={"count": "x" * 2_001})
    )
    oversized_intent = _prepare(oversized_runtime)
    assert isinstance(oversized_intent, ExecutionIntent)
    oversized = oversized_runtime.invoke(oversized_intent)
    assert oversized.is_error is True
    assert oversized.metadata["code"] == "source_metadata_oversized"

    wrong_kind_runtime = _source_runtime(
        ToolExecutionOutput(
            content="public",
            source_receipts=(_web_draft(),),
        )
    )
    wrong_kind_intent = _prepare(wrong_kind_runtime)
    assert isinstance(wrong_kind_intent, ExecutionIntent)
    wrong_kind = wrong_kind_runtime.invoke(wrong_kind_intent)
    assert wrong_kind.is_error is True
    assert wrong_kind.metadata["code"] == "source_kind_invalid"

    not_sent_runtime = _source_runtime(
        ToolExecutionOutput(
            content="request was rejected before send",
            metadata={"count": 0},
            is_error=True,
            executed=False,
        )
    )
    not_sent_intent = _prepare(not_sent_runtime)
    assert isinstance(not_sent_intent, ExecutionIntent)
    not_sent = not_sent_runtime.invoke(not_sent_intent)
    assert not_sent.is_error is True
    assert not_sent.executed is False
    assert not_sent.metadata["source_receipts"] == []


class _AlwaysAllowPolicy:
    identity = "always-allow-fixture-v1"

    def evaluate(self, _spec, _arguments, _binding):
        return PolicyDecision.ALLOW


def test_public_network_always_requires_stable_approval_and_crash_is_unknown() -> None:
    spec = _source_spec(
        egress=EgressClass.PUBLIC_NETWORK,
        approval=ApprovalPolicy.ALWAYS,
        source_kind=SourceKind.WEB_SEARCH_SNIPPET,
    )
    runtime = _source_runtime(
        ToolExecutionOutput(content="unused"),
        spec=spec,
        policy=_AlwaysAllowPolicy(),
    )

    first = _prepare(runtime)
    assert isinstance(first, ApprovalRequired)
    assert first.request.approval_basis_revision == 2
    assert first.request.egress == "public_network"
    grant = ApprovalGrant(
        first.request.request_id,
        first.request.binding_digest,
        approval_basis_revision=first.request.approval_basis_revision,
    )
    second_context = _context(state_revision=3, approval_basis_revision=2)
    second = runtime.prepare(
        ToolCall("call-1", "source_fixture", {"query": "grounding"}),
        second_context,
        approval=grant,
    )
    assert isinstance(second, ExecutionIntent)
    assert second.intent_digest == first.request.binding_digest
    assert second.approval_basis_revision == 2

    crashing = _source_runtime(
        None,
        spec=spec,
    )
    crashing._tools["source_fixture"] = replace(  # noqa: SLF001 - exact injected boundary
        crashing._tools["source_fixture"],  # noqa: SLF001
        func=lambda _intent: (_ for _ in ()).throw(RuntimeError("send outcome unknown")),
    )
    approval = _prepare(crashing)
    assert isinstance(approval, ApprovalRequired)
    crashing_intent = crashing.prepare(
        ToolCall("call-1", "source_fixture", {"query": "grounding"}),
        _context(),
        ApprovalGrant(
            approval.request.request_id,
            approval.request.binding_digest,
            approval.request.approval_basis_revision,
        ),
    )
    assert isinstance(crashing_intent, ExecutionIntent)
    with pytest.raises(RuntimeError, match="unknown"):
        crashing.invoke(crashing_intent)


def test_context_maps_only_valid_kernel_receipts_to_untrusted_data_class() -> None:
    runtime = _source_runtime(
        ToolExecutionOutput(
            content="grounded excerpt",
            source_receipts=(_draft(),),
        )
    )
    intent = _prepare(runtime)
    assert isinstance(intent, ExecutionIntent)
    result = runtime.invoke(intent)
    fact = ConversationFact(
        fact_id="source-fact-1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": result.tool_call_id,
            "text": result.content,
            "is_error": result.is_error,
            "executed": result.executed,
            "metadata": result.metadata,
        },
    )
    state = replace(ConversationState.new("conversation-1"), facts=(fact,))
    action = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=1,
        expected_revision=0,
        run_id="run-2",
        message="summarize",
    )
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=8_000, output_reserve=500),
    )

    pack = manager.build(state, action, ())

    assert "workspace_excerpt" in pack.data_classes
    assert "tool_results" not in pack.data_classes
    block = pack.messages[0].content[0]
    assert block["type"] == "tool_result"
    assert block["untrusted"] is True
    expected_ref = result.metadata["source_refs"][0]["source_ref"]
    assert block["source_refs"] == [expected_ref]

    mutated_metadata = json.loads(json.dumps(result.metadata))
    mutated_metadata["source_receipts"][0]["origin_locator"] = "forged.txt"
    mutated_fact = replace(
        fact,
        content={**fact.content, "metadata": mutated_metadata},
    )
    with pytest.raises(ContextLimitError, match="source receipt"):
        manager.build(replace(state, facts=(mutated_fact,)), action, ())

    forged_ref_metadata = json.loads(json.dumps(result.metadata))
    forged_ref_metadata["source_refs"][0]["source_ref"] = (
        "source-ref:v1:" + "0" * 64
    )
    forged_ref_fact = replace(
        fact,
        content={**fact.content, "metadata": forged_ref_metadata},
    )
    with pytest.raises(ContextLimitError, match="source ref"):
        manager.build(replace(state, facts=(forged_ref_fact,)), action, ())

    orphan_ref_metadata = json.loads(json.dumps(result.metadata))
    orphan_ref_metadata.pop("source_receipts")
    orphan_ref_fact = replace(
        fact,
        content={**fact.content, "metadata": orphan_ref_metadata},
    )
    with pytest.raises(ContextLimitError, match="citation source"):
        manager.build(replace(state, facts=(orphan_ref_fact,)), action, ())


def test_runtime_resolves_only_current_canonical_search_source_ref() -> None:
    runtime = _source_runtime(
        ToolExecutionOutput(content="public excerpt", source_receipts=(_web_draft(),)),
        spec=_source_spec(source_kind=SourceKind.WEB_SEARCH_SNIPPET),
    )
    intent = _prepare(runtime)
    assert isinstance(intent, ExecutionIntent)
    result = runtime.invoke(intent)
    source_ref = result.metadata["source_refs"][0]["source_ref"]
    fact = ConversationFact(
        fact_id="web-search-fact-1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": result.tool_call_id,
            "text": result.content,
            "is_error": False,
            "executed": True,
            "metadata": result.metadata,
        },
    )
    state = replace(ConversationState.new("conversation-1"), facts=(fact,))
    from agent.runtime.loop import AgentRuntime

    binding = AgentRuntime._source_authority_for(  # noqa: SLF001 - Runtime boundary unit
        state,
        ToolCall("fetch-1", "web_fetch", {"source_ref": source_ref}),
    )

    assert binding is not None
    assert binding.source_fact_id == fact.fact_id
    assert binding.receipt_digest == result.metadata["source_receipts"][0]["receipt_digest"]
    assert binding.conversation_id == "conversation-1"
    assert binding.canonical_url == "https://example.com/article"

    assert (
        AgentRuntime._source_authority_for(  # noqa: SLF001
            state,
            ToolCall("fetch-2", "web_fetch", {"source_ref": "source-ref:v1:" + "0" * 64}),
        )
        is None
    )
    cross_state = replace(state, conversation_id="conversation-2")
    assert (
        AgentRuntime._source_authority_for(  # noqa: SLF001
            cross_state,
            ToolCall("fetch-3", "web_fetch", {"source_ref": source_ref}),
        )
        is None
    )


def test_untrusted_history_or_web_result_cannot_gain_memory_admission() -> None:
    runtime = _source_runtime(
        ToolExecutionOutput(content="remember this", source_receipts=(_web_draft(),)),
        spec=_source_spec(source_kind=SourceKind.WEB_SEARCH_SNIPPET),
    )
    intent = _prepare(runtime)
    assert isinstance(intent, ExecutionIntent)
    result = runtime.invoke(intent)
    fact = ConversationFact(
        fact_id="web-search-fact-1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": result.tool_call_id,
            "text": "remember this",
            "is_error": False,
            "executed": True,
            "metadata": result.metadata,
        },
    )
    goal_state = conversation_with_active_goal("conversation-1")
    state = replace(goal_state, facts=(*goal_state.facts, fact))
    from agent.runtime.loop import AgentRuntime

    assert (
        AgentRuntime._fact_admission_for(  # noqa: SLF001 - admission boundary unit
            state,
            ToolCall("remember-1", "memory_remember", {"content": "remember this"}),
        )
        is None
    )


def test_no_tool_result_can_gain_memory_fact_admission() -> None:
    goal_state = conversation_with_active_goal("conversation-1")
    workspace_result = ConversationFact(
        fact_id="workspace-read-fact-1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "read-1",
            "text": "remember this workspace text",
            "is_error": False,
            "executed": True,
            "metadata": {"data_classes": ["workspace_excerpt"]},
        },
    )
    ordinary_result = ConversationFact(
        fact_id="ordinary-tool-fact-1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "tool-1",
            "text": "remember this ordinary result",
            "is_error": False,
            "executed": True,
        },
    )
    state = replace(
        goal_state,
        facts=(*goal_state.facts, workspace_result, ordinary_result),
    )
    from agent.runtime.loop import AgentRuntime

    for content in (
        "remember this workspace text",
        "remember this ordinary result",
    ):
        assert (
            AgentRuntime._fact_admission_for(  # noqa: SLF001 - admission boundary unit
                state,
                ToolCall("remember-1", "memory_remember", {"content": content}),
            )
            is None
        )


def test_new_source_data_class_requires_a_new_provider_disclosure() -> None:
    runtime = _source_runtime(
        ToolExecutionOutput(content="grounded excerpt", source_receipts=(_draft(),))
    )
    intent = _prepare(runtime)
    assert isinstance(intent, ExecutionIntent)
    source_result = runtime.invoke(intent)
    fact = ConversationFact(
        fact_id="source-fact-1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": source_result.tool_call_id,
            "text": source_result.content,
            "is_error": False,
            "executed": True,
            "metadata": source_result.metadata,
        },
    )
    descriptor = ProviderDescriptor(
        family="openai_compatible",
        model="remote-model",
        canonical_destination="https://api.example.com/v1/chat/completions",
        trust_profile="remote-https-v1",
        remote=True,
    )
    old_request = ProviderDisclosureRequest.create(
        disclosure_id="disclosure-old",
        provider_descriptor_digest=descriptor.identity_digest,
        canonical_destination=descriptor.canonical_destination,
        model=descriptor.model,
        data_classes=("system_policy", "user_messages"),
    )
    old_receipt = old_request.acknowledge(
        receipt_id="receipt-old",
        acknowledged_action_seq=1,
        acknowledged_at="2026-08-04T00:00:00Z",
    )
    state = ConversationState(
        conversation_id="conversation-1",
        facts=(fact,),
        provider_disclosure_request=old_request,
        provider_disclosure_receipt=old_receipt,
    )
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider()
    from agent.runtime.loop import AgentRuntime, InvocationLimits

    agent_runtime = AgentRuntime(
        provider=provider,
        provider_descriptor=descriptor,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=500),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-disclosure",
    )

    result = agent_runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-2",
            message="summarize the source",
        ),
        store.load(),
    )

    assert result.status is RunStatus.AWAITING_DISCLOSURE
    assert provider.calls == []
    assert store.state.provider_disclosure_request is not None
    assert "workspace_excerpt" in store.state.provider_disclosure_request.data_classes
    assert store.state.provider_disclosure_request.request_digest != old_request.request_digest
