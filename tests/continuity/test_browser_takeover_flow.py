"""018 Task 5 P0：真实 run_turn 的 browser takeover 流（先 Red）。

provider 首次返回 browser tool call；governed callable 返回 typed
BrowserTakeoverRequestV1，ToolRuntime 归一化为 ToolResult；唯一 AgentRuntime 必须持久化
pending 后立即返回等待，不再进入 model/tool——sentinel 第二响应不得被
消费，provider/tool 各恰一次，checkpoint 已持久化 pending。
"""

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ApprovalPolicy,
    BrowserTakeoverRequestV1,
    CompleteBrowserTakeover,
    ExecutionAuthorityClass,
    ModelResponse,
    ModelToolCall,
    OutputPolicy,
    RunStatus,
    SideEffectClass,
    SubmitMessage,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.ports import RetryableProviderError
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    conversation_with_active_goal,
    goal_noop_response,
)

REQUEST = BrowserTakeoverRequestV1(
    request_id="browser-takeover:session-0123456789abcdef",
    session_ref="session-0123456789abcdef",
    profile_ref="profile-0123456789abcdef",
    profile_revision=3,
    browser_identity_digest="a" * 64,
    goal_id="goal-1",
    goal_revision=1,
    requested_at="2026-08-28T10:00:00+00:00",
)


def _browser_tool_spec() -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.BROWSER_SESSION,
        name="browser_begin_takeover",
        version="1",
        description="Request user browser takeover",
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        risk=ToolRisk.MEDIUM,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={"kind": "browser_takeover", "browser": True},
        output_limit_chars=200,
    )


def test_takeover_tool_result_returns_waiting_without_second_model_call():
    invocations: list[str] = []

    store = InMemoryCheckpointStore(conversation_with_active_goal())

    def begin_takeover(intent) -> BrowserTakeoverRequestV1:
        # headed activation/callable invocation 只能发生在 durable pending 之后。
        assert store.state.browser_takeover_pending == REQUEST
        assert intent.browser_takeover_request == REQUEST
        invocations.append(intent.tool_call_id)
        return REQUEST

    provider = ScriptedProvider(
        goal_noop_response("delta-takeover"),
        ModelResponse(
            (ModelToolCall("call-1", "browser_begin_takeover", {}),)
        ),
        # sentinel：pending 时不得消费；typed complete 后才恢复原 run。
        RetryableProviderError("resume-after-takeover"),
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="Be concise.",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(
            (
                RegisteredTool(
                    _browser_tool_spec(),
                    begin_takeover,
                    prepare_binding=lambda _arguments: {
                        "session_ref": REQUEST.session_ref,
                        "profile_ref": REQUEST.profile_ref,
                        "profile_revision": REQUEST.profile_revision,
                        "browser_identity_digest": REQUEST.browser_identity_digest,
                    },
                ),
            ),
            clock=lambda: REQUEST.requested_at,
        ),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        browser_takeover_complete=lambda request: request.profile_revision + 1,
        invocation_id_factory=lambda: "invocation-1",
    )
    submit = SubmitMessage(
        conversation_id=store.state.conversation_id,
        action_seq=store.state.next_action_seq,
        expected_revision=store.state.revision,
        run_id="run-1",
        message="sign in please",
    )
    result = runtime.run_turn(submit, store.load())
    # pending 已持久化进 checkpoint。
    assert store.state.browser_takeover_pending == REQUEST
    # 立即返回等待；不进入第二次 model 调用，不消费 sentinel。
    assert result.state.browser_takeover_pending == REQUEST
    assert len(provider.calls) == 2  # GoalDelta + tool-call 轮，无第三轮
    assert invocations == ["call-1"]
    assert result.status is RunStatus.COMPLETED
    assert "takeover" in (result.message or "").lower()
    assert result.state.active_run is not None
    assert result.state.active_run.owner_invocation_id is None
    # sentinel 未被消费（ScriptedProvider 的剩余脚本非空）。
    assert provider._responses, "sentinel response must remain unconsumed"
    # 再提交任何 message 仍零 provider 调用（pending gate）。
    followup = SubmitMessage(
        conversation_id=result.state.conversation_id,
        action_seq=result.state.next_action_seq,
        expected_revision=result.state.revision,
        run_id="run-2",
        message="keep going",
    )
    store.state = result.state
    gated = runtime.run_turn(followup, store.load())
    assert gated.state.browser_takeover_pending == REQUEST
    assert len(provider.calls) == 2
    assert provider._responses

    # 用户交还后恢复同一 Runtime/run；第三个 provider sentinel 此时才消费。
    complete = CompleteBrowserTakeover(
        conversation_id=result.state.conversation_id,
        action_seq=result.state.next_action_seq,
        expected_revision=result.state.revision,
        request_id=REQUEST.request_id,
        session_ref=REQUEST.session_ref,
        expected_profile_revision=REQUEST.profile_revision,
    )
    resumed = runtime.run_turn(complete, store.load())
    assert resumed.status is RunStatus.FAILED_RETRYABLE
    assert resumed.state.browser_takeover_pending is None
    assert len(provider.calls) == 3
    assert not provider._responses
