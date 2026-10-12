from __future__ import annotations

import pytest

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ApprovalPolicy,
    BeginAnswer,
    ConversationState,
    ExecutionAuthorityClass,
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
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.ports import ModelAttemptBudgetExhaustedError
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider


class _BudgetExhaustedProvider:
    def generate(self, _context, *, delta_observer=None):  # noqa: ANN001, ARG002
        raise ModelAttemptBudgetExhaustedError(
            "model attempt budget exhausted before dispatch"
        )


def test_transport_budget_exhaustion_pauses_as_a_limit() -> None:
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=_BudgetExhaustedProvider(),
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="hello",
        ),
        store.load(),
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "model_attempt_budget_exhausted"


def test_invocation_limit_pauses_and_resume_gets_fresh_budget() -> None:
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="read_fixture",
        version="1",
        description="Read fixture",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={},
        output_limit_chars=10,
    )
    provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer("begin-limited-read")),
        ModelResponse((ModelToolCall("call-1", "read_fixture", {}),)),
        ModelResponse((ModelTextBlock("final"),)),
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime((RegisteredTool(spec, lambda intent: "ok"),)),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_model_calls=2),
        invocation_id_factory=lambda: "invocation-1",
    )
    submit = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=1,
        expected_revision=0,
        run_id="run-1",
        message="read",
    )

    paused = runtime.run_turn(submit, store.load())
    assert paused.status is RunStatus.LIMIT_REACHED

    resume = Resume(
        conversation_id="conversation-1",
        action_seq=store.state.next_action_seq,
        expected_revision=store.state.revision,
    )
    completed = runtime.run_turn(resume, store.load())

    assert completed.status is RunStatus.COMPLETED
    assert completed.message == "final"


def test_unbounded_cumulative_limits_allow_a_progressing_model_tool_loop() -> None:
    calls: list[str] = []
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="read_fixture",
        version="1",
        description="Read fixture",
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
        output_limit_chars=10,
    )
    provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer("begin-two-reads")),
        ModelResponse((ModelToolCall("call-1", "read_fixture", {"path": "one"}),)),
        ModelResponse((ModelToolCall("call-2", "read_fixture", {"path": "two"}),)),
        ModelResponse((ModelTextBlock("final"),), output_tokens=100),
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(
            (RegisteredTool(spec, lambda intent: calls.append(intent.arguments["path"]) or "ok"),)
        ),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(
            max_model_calls=None,
            max_tool_calls=None,
            max_input_tokens=None,
            max_output_tokens=None,
        ),
        invocation_id_factory=lambda: "invocation-1",
    )

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="read twice",
        ),
        store.load(),
    )

    assert result.status is RunStatus.COMPLETED
    assert result.message == "final"
    assert result.model_calls_used == 4
    assert calls == ["one", "two"]


def test_run_model_budget_persists_across_resume_until_caller_explicitly_extends_it() -> None:
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="read_fixture",
        version="1",
        description="Read fixture",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={},
        output_limit_chars=10,
    )
    provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer("begin-bounded-run")),
        ModelResponse((ModelToolCall("call-bounded-run", "read_fixture", {}),)),
        ModelResponse((ModelTextBlock("final"),)),
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-run-budget"))

    def runtime(limit: int) -> AgentRuntime:
        return AgentRuntime(
            provider=provider,
            context_manager=KernelContextManager(
                system_policy="policy",
                limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
            ),
            tool_runtime=KernelToolRuntime((RegisteredTool(spec, lambda _intent: "ok"),)),
            checkpoint_store=store,
            event_sink=CollectingSink(),
            limits=InvocationLimits(
                max_model_calls=None,
                max_run_model_calls=limit,
            ),
            invocation_id_factory=lambda: "invocation-run-budget",
        )

    paused = runtime(2).run_turn(
        SubmitMessage(
            conversation_id="conversation-run-budget",
            action_seq=1,
            expected_revision=0,
            run_id="run-budget",
            message="continue until complete",
        ),
        store.load(),
    )

    assert paused.status is RunStatus.LIMIT_REACHED
    assert paused.error_code == "run_model_call_limit"
    assert len(provider.calls) == 2
    assert store.state.active_run is not None
    assert store.state.active_run.model_calls_used == 2

    still_paused = runtime(2).run_turn(
        Resume(
            conversation_id="conversation-run-budget",
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
        ),
        store.load(),
    )
    assert still_paused.status is RunStatus.LIMIT_REACHED
    assert len(provider.calls) == 2

    completed = runtime(3).run_turn(
        Resume(
            conversation_id="conversation-run-budget",
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
        ),
        store.load(),
    )
    assert completed.status is RunStatus.COMPLETED
    assert completed.message == "final"
    assert len(provider.calls) == 3


@pytest.mark.parametrize(
    "resume_time",
    ["2026-09-13T00:01:01Z", "2026-09-12T23:59:59Z"],
)
def test_run_wall_budget_persists_across_resume_and_stops_before_provider(
    resume_time: str,
) -> None:
    provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer("started")),
        ModelResponse((ModelTextBlock("must not be requested"),)),
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-wall-budget"))

    def runtime(*, now: str) -> AgentRuntime:
        return AgentRuntime(
            provider=provider,
            context_manager=KernelContextManager(
                system_policy="policy",
                limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
            ),
            tool_runtime=KernelToolRuntime(()),
            checkpoint_store=store,
            event_sink=CollectingSink(),
            limits=InvocationLimits(
                max_model_calls=1,
                max_run_wall_seconds=60,
            ),
            invocation_id_factory=lambda: "invocation-wall-budget",
            run_time_factory=lambda: now,
        )

    paused = runtime(now="2026-09-13T00:00:00Z").run_turn(
        SubmitMessage(
            conversation_id="conversation-wall-budget",
            action_seq=1,
            expected_revision=0,
            run_id="run-wall-budget",
            message="continue until complete",
        ),
        store.load(),
    )

    assert paused.status is RunStatus.LIMIT_REACHED
    assert paused.error_code == "model_call_limit"
    assert len(provider.calls) == 1
    assert store.state.active_run is not None
    assert store.state.active_run.run_started_at == "2026-09-13T00:00:00Z"

    expired = runtime(now=resume_time).run_turn(
        Resume(
            conversation_id="conversation-wall-budget",
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
        ),
        store.load(),
    )

    assert expired.status is RunStatus.LIMIT_REACHED
    assert expired.error_code == "run_wall_time_limit"
    assert len(provider.calls) == 1


def test_conversation_capacity_stops_before_provider_effect() -> None:
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("must not run"),)))
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    store.capacity_available = False
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    submit = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=1,
        expected_revision=0,
        run_id="run-1",
        message="hello",
    )

    result = runtime.run_turn(submit, store.load())

    assert result.status is RunStatus.CONVERSATION_LIMIT_REACHED
    assert provider.calls == []
    assert store.state.active_run is None


def test_tool_call_limit_pauses_before_the_next_callable() -> None:
    calls = 0

    def read_fixture(intent) -> str:
        nonlocal calls
        calls += 1
        return "ok"

    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="read_fixture",
        version="1",
        description="Read fixture",
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
        output_limit_chars=10,
    )
    provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer("begin-batched-read")),
        ModelResponse(
            (
                ModelToolCall("call-1", "read_fixture", {"path": "one"}),
                ModelToolCall("call-2", "read_fixture", {"path": "two"}),
            )
        )
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime((RegisteredTool(spec, read_fixture),)),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_tool_calls=1),
        invocation_id_factory=lambda: "invocation-1",
    )

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="read twice",
        ),
        store.load(),
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "tool_call_limit"
    assert calls == 1
    assert store.state.active_run is not None
    assert store.state.active_run.status.value == "paused_limit"


def test_input_token_limit_pauses_before_provider_call() -> None:
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("must not run"),)))
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_input_tokens=1),
        invocation_id_factory=lambda: "invocation-1",
    )

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="hello",
        ),
        store.load(),
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "input_token_limit"
    assert provider.calls == []
    assert store.state.active_run is not None
    assert store.state.active_run.status.value == "paused_limit"


def test_output_token_limit_pauses_after_one_provider_call() -> None:
    provider = ScriptedProvider(
        ModelResponse((ModelTextBlock("too much"),), output_tokens=2)
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_output_tokens=1),
        invocation_id_factory=lambda: "invocation-1",
    )

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="hello",
        ),
        store.load(),
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "output_token_limit"
    assert len(provider.calls) == 1
    assert store.state.active_run is not None
    assert store.state.active_run.status.value == "paused_limit"


def test_missing_usage_uses_conservative_output_bound() -> None:
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("x" * 100),)))
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_output_tokens=50),
        invocation_id_factory=lambda: "invocation-1",
    )

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="hello",
        ),
        store.load(),
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "output_token_limit"


def test_underreported_usage_cannot_bypass_conservative_output_bound() -> None:
    provider = ScriptedProvider(
        ModelResponse((ModelTextBlock("x" * 100),), output_tokens=0)
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_output_tokens=50),
        invocation_id_factory=lambda: "invocation-1",
    )

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="hello",
        ),
        store.load(),
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "output_token_limit"
    assert len(provider.calls) == 1


def test_provider_max_tokens_stop_is_not_reported_completed() -> None:
    provider = ScriptedProvider(
        ModelResponse(
            (ModelTextBlock("truncated answer"),),
            stop_reason="max_tokens",
            output_tokens=5,
        )
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="hello",
        ),
        store.load(),
    )

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "provider_output_truncated"
    assert result.message is None
    assert store.state.active_run is None
