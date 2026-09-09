from __future__ import annotations

from dataclasses import replace

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ApprovalPolicy,
    BeginAnswer,
    ConversationFact,
    ConversationState,
    ExecutionAuthorityClass,
    FactKind,
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
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.state import accept_action
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider


def _runtime(provider, store, tools=(), *, limits=None, sink=None):
    return AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="Be concise.",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(tools),
        checkpoint_store=store,
        event_sink=sink or CollectingSink(),
        limits=limits or InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )


def _submit(state: ConversationState, message: str = "hello") -> SubmitMessage:
    return SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-1",
        message=message,
    )


def test_text_only_turn_completes_through_one_provider_owner() -> None:
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("hello back"),)))
    runtime = _runtime(provider, store)

    result = runtime.run_turn(_submit(store.state), store.load())

    assert result.status is RunStatus.COMPLETED
    assert result.message == "hello back"
    assert len(provider.calls) == 1
    assert store.state.active_run is None
    assert store.state.facts[-1].content["text"] == "hello back"


def test_provider_receives_recent_history_when_budget_evicts_one_group() -> None:
    initial = replace(
        ConversationState.new("conversation-1"),
        facts=(
            ConversationFact(
                fact_id="user-old",
                kind=FactKind.USER_MESSAGE,
                content={"text": "OLD_FIELD=" + "a" * 240},
            ),
            ConversationFact(
                fact_id="user-recent",
                kind=FactKind.USER_MESSAGE,
                content={"text": "RECENT_CONFIRMED=keep-me" + "b" * 240},
            ),
        ),
    )
    action = _submit(initial, "answer using the latest confirmed field")
    accepted = accept_action(initial, action).state
    roomy = KernelContextManager(
        system_policy="Be concise.",
        limits=ContextLimits(max_input_tokens=100_000, output_reserve=1),
    )
    retained = replace(
        accepted,
        facts=tuple(fact for fact in accepted.facts if fact.fact_id != "user-old"),
    )
    retained_cost = roomy.build(retained, action, ()).budget.estimated_input_tokens
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("done"),)))
    store = InMemoryCheckpointStore(initial)
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="Be concise.",
            limits=ContextLimits(
                max_input_tokens=retained_cost + 20,
                output_reserve=20,
            ),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    delivered = repr(provider.calls[0].messages)
    assert "RECENT_CONFIRMED=keep-me" in delivered
    assert "OLD_FIELD=" not in delivered


def test_tool_result_rebuilds_context_before_final_response() -> None:
    calls: list[str] = []

    def read_fixture(intent) -> str:
        path = intent.arguments["path"]
        calls.append(path)
        return "content:" + path

    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="read_fixture",
        version="1",
        description="Read a fixture",
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
        safety_policy={"fixture": True},
        output_limit_chars=100,
    )
    provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer("begin-read-result")),
        ModelResponse((ModelToolCall("call-1", "read_fixture", {"path": "a.txt"}),)),
        ModelResponse((ModelTextBlock("used the file"),)),
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = _runtime(provider, store, (RegisteredTool(spec, read_fixture),))

    result = runtime.run_turn(_submit(store.state), store.load())

    assert result.status is RunStatus.COMPLETED
    assert calls == ["a.txt"]
    assert len(provider.calls) == 3
    assert any(
        block.get("type") == "tool_result"
        for message in provider.calls[2].messages
        for block in message.content
    )


def test_text_with_tool_call_is_preamble_not_completion() -> None:
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="read_fixture",
        version="1",
        description="Read a fixture",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={},
        output_limit_chars=20,
    )
    provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer("begin-preamble-read")),
        ModelResponse(
            (
                ModelTextBlock("I will inspect it."),
                ModelToolCall("call-1", "read_fixture", {}),
            )
        ),
        ModelResponse((ModelTextBlock("final"),)),
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = _runtime(provider, store, (RegisteredTool(spec, lambda intent: "ok"),))

    result = runtime.run_turn(_submit(store.state), store.load())

    assert result.message == "final"
    assert len(provider.calls) == 3
