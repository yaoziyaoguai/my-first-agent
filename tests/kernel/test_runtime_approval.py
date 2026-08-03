from __future__ import annotations

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ApprovalPolicy,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    OutputPolicy,
    ResolveApproval,
    Resume,
    RunStatus,
    SideEffectClass,
    SubmitMessage,
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
)


def test_approval_pause_is_durable_and_exact_resume_executes_once() -> None:
    calls: list[str] = []
    spec = ToolSpec(
        name="write_fixture",
        version="1",
        description="Write a fixture",
        input_schema={
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={},
        output_limit_chars=50,
    )
    provider = ScriptedProvider(
        ModelResponse((ModelToolCall("call-1", "write_fixture", {"content": "hello"}),)),
        ModelResponse((ModelTextBlock("done"),)),
    )
    store = InMemoryCheckpointStore(conversation_with_active_goal())
    sink = CollectingSink()
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(
            (
                RegisteredTool(
                    spec,
                    lambda intent: calls.append(intent.arguments["content"]) or "written",
                ),
            )
        ),
        checkpoint_store=store,
        event_sink=sink,
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    submit = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=store.state.next_action_seq,
        expected_revision=store.state.revision,
        run_id=f"run-{store.state.next_action_seq}",
        message="write it",
    )

    paused = runtime.run_turn(submit, store.load())

    assert paused.status is RunStatus.AWAITING_APPROVAL
    assert paused.request is not None
    assert calls == []
    assert store.state.active_run is not None

    approval = ResolveApproval(
        conversation_id="conversation-1",
        action_seq=store.state.next_action_seq,
        expected_revision=store.state.revision,
        request_id=paused.request.request_id,
        binding_digest=paused.request.binding_digest,
        approved=True,
    )
    completed = runtime.run_turn(approval, store.load())

    assert completed.status is RunStatus.COMPLETED
    assert calls == ["hello"]
    assert len(provider.calls) == 2


def test_resume_reemits_same_approval_without_provider_or_tool_call() -> None:
    spec = ToolSpec(
        name="write_fixture",
        version="1",
        description="Write a fixture",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={},
        output_limit_chars=20,
    )
    provider = ScriptedProvider(
        ModelResponse((ModelToolCall("call-1", "write_fixture", {}),)),
    )
    store = InMemoryCheckpointStore(conversation_with_active_goal())
    sink = CollectingSink()
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
        ),
        tool_runtime=KernelToolRuntime((RegisteredTool(spec, lambda intent: "written"),)),
        checkpoint_store=store,
        event_sink=sink,
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    submit = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=store.state.next_action_seq,
        expected_revision=store.state.revision,
        run_id=f"run-{store.state.next_action_seq}",
        message="write",
    )
    first = runtime.run_turn(submit, store.load())
    first_event_id = sink.events[-1].event_id
    resume = Resume(
        conversation_id="conversation-1",
        action_seq=store.state.next_action_seq,
        expected_revision=store.state.revision,
    )

    second = runtime.run_turn(resume, store.load())

    assert first.status is second.status is RunStatus.AWAITING_APPROVAL
    assert len(provider.calls) == 1
    assert sink.events[-1].event_id == first_event_id
