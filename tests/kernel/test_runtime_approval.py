from __future__ import annotations

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ApprovalPolicy,
    BlockedClaim,
    ExecutionAuthorityClass,
    ModelResponse,
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
    goal_noop_response,
)


def test_approval_pause_is_durable_and_exact_resume_executes_once() -> None:
    calls: list[str] = []
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
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
        goal_noop_response("approval-user-supplement"),
        ModelResponse((ModelToolCall("call-1", "write_fixture", {"content": "hello"}),)),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="approval-fixture-blocked",
                goal_id="goal-1",
                goal_revision=1,
                blocker="done",
                safe_attempts=("executed the approved fixture write",),
                resume_condition="provide a closed completion oracle",
            ),
        ),
    )
    store = InMemoryCheckpointStore(conversation_with_active_goal())
    sink = CollectingSink()
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
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
    assert len(provider.calls) == 3


def test_resume_reemits_same_approval_without_provider_or_tool_call() -> None:
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
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
        goal_noop_response("approval-resume-user-supplement"),
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
    assert len(provider.calls) == 2
    assert sink.events[-1].event_id == first_event_id


def test_successful_approved_request_is_not_repeated_after_resume() -> None:
    calls: list[str] = []
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="fetch_fixture",
        version="1",
        description="Fetch one immutable fixture",
        input_schema={
            "type": "object",
            "properties": {"ref": {"type": "string"}},
            "required": ["ref"],
            "additionalProperties": False,
        },
        risk=ToolRisk.MEDIUM,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={},
        output_limit_chars=50,
    )
    provider = ScriptedProvider(
        goal_noop_response("approval-repeat-user-supplement"),
        *(
            ModelResponse(
                (ModelToolCall(f"fetch-{index}", "fetch_fixture", {"ref": "same"}),)
            )
            for index in range(3)
        )
    )
    store = InMemoryCheckpointStore(conversation_with_active_goal())
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
        ),
        tool_runtime=KernelToolRuntime(
            (
                RegisteredTool(
                    spec,
                    lambda intent: calls.append(intent.arguments["ref"]) or "fetched",
                ),
            )
        ),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_invalid_repairs=1),
        invocation_id_factory=lambda: "invocation-1",
    )
    submit = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=store.state.next_action_seq,
        expected_revision=store.state.revision,
        run_id=f"run-{store.state.next_action_seq}",
        message="fetch it",
    )
    paused = runtime.run_turn(submit, store.load())
    assert paused.status is RunStatus.AWAITING_APPROVAL
    assert paused.request is not None

    result = runtime.run_turn(
        ResolveApproval(
            conversation_id="conversation-1",
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            request_id=paused.request.request_id,
            binding_digest=paused.request.binding_digest,
            approved=True,
        ),
        store.load(),
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "no_progress"
    assert calls == ["same"]
