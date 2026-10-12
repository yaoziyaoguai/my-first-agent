from __future__ import annotations

from dataclasses import replace

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    ApprovalPolicy,
    ApprovalRequest,
    BlockedClaim,
    EgressClass,
    ExecutionAuthorityClass,
    GoalAuthorizationScope,
    GoalStatus,
    ModelResponse,
    ModelToolCall,
    OutputPolicy,
    ResolveApproval,
    Resume,
    RevokeGoalTargetAuthority,
    RunStatus,
    SideEffectClass,
    SubmitMessage,
    ToolCall,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits, RetryableProviderError
from agent.runtime.state import accept_action, pause_for_approval, start_tool_batch
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
            ),
            clock=lambda: "2026-09-04T00:30:00Z",
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


def test_opt_in_goal_target_approval_avoids_repeat_prompt_for_same_write_scope() -> None:
    calls: list[str] = []
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="write_file",
        version="1",
        description="Write an exact workspace fixture",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={"workspace_scoped": True},
        output_limit_chars=50,
    )
    provider = ScriptedProvider(
        goal_noop_response("goal-target-consent-user-supplement"),
        ModelResponse(
            (ModelToolCall("write-1", "write_file", {"path": "note.txt", "content": "one"}),)
        ),
        ModelResponse(
            (ModelToolCall("write-2", "write_file", {"path": "note.txt", "content": "two"}),)
        ),
        RetryableProviderError("stop after both writes"),
    )
    initial = conversation_with_active_goal()
    assert initial.goal is not None
    initial = replace(initial, goal=replace(initial.goal, targets=("note.txt",)))
    store = InMemoryCheckpointStore(initial)
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
                    prepare_binding=lambda arguments: {
                        "effect_preview": f"write {arguments['path']}",
                    },
                ),
            ),
            clock=lambda: "2026-09-04T00:30:00Z",
        ),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-goal-target-consent",
    )
    paused = runtime.run_turn(
        SubmitMessage(
            conversation_id=initial.conversation_id,
            action_seq=initial.next_action_seq,
            expected_revision=initial.revision,
            run_id="run-goal-target-consent",
            message="write the requested target",
        ),
        store.load(),
    )
    assert paused.status is RunStatus.AWAITING_APPROVAL
    assert paused.request is not None

    result = runtime.run_turn(
        ResolveApproval(
            conversation_id=initial.conversation_id,
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            request_id=paused.request.request_id,
            binding_digest=paused.request.binding_digest,
            approved=True,
            approved_at="2026-09-04T00:00:00Z",
            authorize_goal_target=True,
        ),
        store.load(),
    )

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert calls == ["one", "two"]
    assert len(store.state.goal_authorizations) == 1
    assert store.state.goal_authorizations[0].normalized_target == "note.txt"
    assert store.state.goal_authorizations[0].uses_consumed == 2
    assert store.state.goal_authorizations[0].remaining_uses == 14

    revoked = runtime.run_turn(
        RevokeGoalTargetAuthority(
            conversation_id=initial.conversation_id,
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
        ),
        store.load(),
    )
    assert revoked.status is RunStatus.COMPLETED
    assert store.state.goal_authorizations == ()


def test_opt_in_goal_target_approval_cannot_expand_beyond_current_goal_targets() -> None:
    calls: list[str] = []
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="write_file",
        version="1",
        description="Write an exact workspace fixture",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={"workspace_scoped": True},
        output_limit_chars=50,
    )
    provider = ScriptedProvider(
        goal_noop_response("goal-target-deny-user-supplement"),
        ModelResponse(
            (ModelToolCall("write-outside", "write_file", {"path": "other.txt", "content": "x"}),)
        ),
    )
    initial = conversation_with_active_goal()
    assert initial.goal is not None
    initial = replace(initial, goal=replace(initial.goal, targets=("note.txt",)))
    store = InMemoryCheckpointStore(initial)
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
                    lambda intent: calls.append(intent.arguments["path"]) or "written",
                    prepare_binding=lambda arguments: {
                        "effect_preview": f"write {arguments['path']}",
                    },
                ),
            )
        ),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-goal-target-deny",
    )
    paused = runtime.run_turn(
        SubmitMessage(
            conversation_id=initial.conversation_id,
            action_seq=initial.next_action_seq,
            expected_revision=initial.revision,
            run_id="run-goal-target-deny",
            message="write only the requested target",
        ),
        store.load(),
    )
    assert paused.request is not None

    denied = runtime.run_turn(
        ResolveApproval(
            conversation_id=initial.conversation_id,
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            request_id=paused.request.request_id,
            binding_digest=paused.request.binding_digest,
            approved=True,
            approved_at="2026-09-04T00:00:00Z",
            authorize_goal_target=True,
        ),
        store.load(),
    )

    assert denied.status is RunStatus.CONFLICT
    assert denied.error_code == "goal_target_authorization_mismatch"
    assert calls == []
    assert store.state.goal_authorizations == ()


def test_explicit_goal_directory_approval_mints_only_declared_directory_scope() -> None:
    initial = conversation_with_active_goal()
    assert initial.goal is not None
    state = replace(
        initial,
        goal=replace(initial.goal, targets=("reports",)),
        active_run=ActiveRun(run_id="run-directory-consent"),
    )
    state = start_tool_batch(
        state,
        (
            ToolCall(
                "write-report",
                "write_file",
                {"path": "reports/daily.md", "content": "daily"},
            ),
        ),
    )
    pending = ApprovalRequest(
        request_id="approval-directory-consent",
        run_id="run-directory-consent",
        tool_call_id="write-report",
        binding_digest="binding-directory-consent",
        preview="write reports/daily.md",
        tool_name="write_file",
        side_effect=SideEffectClass.WRITE.value,
        egress=EgressClass.NONE.value,
    )
    state = pause_for_approval(state, pending)

    transition = accept_action(
        state,
        ResolveApproval(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            request_id=pending.request_id,
            binding_digest=pending.binding_digest,
            approved=True,
            approved_at="2026-09-04T00:00:00Z",
            authorize_goal_directory=True,
        ),
    )

    assert transition.state.active_run is not None
    assert transition.state.active_run.status is ActiveRunStatus.RUNNABLE
    assert len(transition.state.goal_authorizations) == 1
    binding = transition.state.goal_authorizations[0]
    assert binding.normalized_target == "reports"
    assert binding.scope is GoalAuthorizationScope.DIRECTORY


def test_declined_approval_stops_the_current_run_without_another_model_or_effect() -> None:
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
        goal_noop_response("approval-decline-user-supplement"),
        ModelResponse((ModelToolCall("call-1", "write_fixture", {"content": "no"}),)),
        ModelResponse((ModelToolCall("call-2", "write_fixture", {"content": "retry"}),)),
    )
    store = InMemoryCheckpointStore(conversation_with_active_goal())
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
        ),
        tool_runtime=KernelToolRuntime(
            (RegisteredTool(spec, lambda intent: calls.append(intent.arguments["content"])),)
        ),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-decline",
    )
    paused = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            run_id="run-decline",
            message="write it",
        ),
        store.load(),
    )
    assert paused.status is RunStatus.AWAITING_APPROVAL
    assert paused.request is not None

    declined = runtime.run_turn(
        ResolveApproval(
            conversation_id="conversation-1",
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            request_id=paused.request.request_id,
            binding_digest=paused.request.binding_digest,
            approved=False,
        ),
        store.load(),
    )

    assert declined.status is RunStatus.CANCELLED
    assert declined.error_code == "approval_declined"
    assert declined.state.active_run is None
    assert declined.state.goal is not None
    assert declined.state.goal.status is not GoalStatus.CANCELLED
    assert calls == []
    assert len(provider.calls) == 2
    rejection = declined.state.facts[-1]
    assert rejection.content["executed"] is False
    assert rejection.content["rejected"] is True


def test_declining_one_item_stops_the_rest_of_its_batch_and_keeps_prior_results() -> None:
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
        goal_noop_response("approval-batch-user-supplement"),
        ModelResponse(
            tuple(
                ModelToolCall(f"call-{index}", "write_fixture", {"content": content})
                for index, content in enumerate(("first", "second", "third"), start=1)
            )
        ),
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
                    lambda intent: calls.append(intent.arguments["content"]) or "written",
                ),
            )
        ),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-batch-decline",
    )
    pending_first = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            run_id="run-batch-decline",
            message="write three items",
        ),
        store.load(),
    )
    assert pending_first.request is not None
    pending_second = runtime.run_turn(
        ResolveApproval(
            conversation_id="conversation-1",
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            request_id=pending_first.request.request_id,
            binding_digest=pending_first.request.binding_digest,
            approved=True,
        ),
        store.load(),
    )
    assert pending_second.status is RunStatus.AWAITING_APPROVAL
    assert pending_second.request is not None
    assert calls == ["first"]

    declined = runtime.run_turn(
        ResolveApproval(
            conversation_id="conversation-1",
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            request_id=pending_second.request.request_id,
            binding_digest=pending_second.request.binding_digest,
            approved=False,
        ),
        store.load(),
    )

    assert declined.status is RunStatus.CANCELLED
    assert calls == ["first"]
    assert len(provider.calls) == 2
    assert any(
        fact.kind.value == "tool_result"
        and fact.content.get("tool_call_id") == "call-1"
        and fact.content.get("executed") is True
        for fact in declined.state.facts
    )
    assert any(
        fact.kind.value == "tool_result"
        and fact.content.get("tool_call_id") == "call-2"
        and fact.content.get("rejected") is True
        for fact in declined.state.facts
    )
    assert not any(
        fact.kind.value == "tool_result"
        and fact.content.get("tool_call_id") == "call-3"
        for fact in declined.state.facts
    )


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
