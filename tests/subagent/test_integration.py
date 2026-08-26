"""SubAgent Product gate：parent → approval → child → parent completion。

候选 reference task（见 roadmap）：让 isolated child 独立审查一段 bounded 设计提案，
并与 parent 直接回答对照。证据：child handoff/成本/时长、可核对的增量观点。
"""

from __future__ import annotations

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    BlockedClaim,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    ResolveApproval,
    RunStatus,
    SubmitMessage,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from agent.subagent.contracts import ChildProfile
from agent.subagent.runner import ChildAgentRunner
from agent.subagent.tools import build_subagent_tool_registrations
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    conversation_with_active_goal,
    goal_noop_response,
)


def _profile() -> ChildProfile:
    return ChildProfile(
        runner_version="subagent-v1",
        provider_profile_id="default",
        provider_destination="local",
        workspace_scope_digest="scope-1",
        max_input_tokens=4_000,
        max_output_tokens=1_000,
        limits_digest="limits-1",
        hard_deadline_seconds=30.0,
    )


def test_parent_delegates_and_uses_child_finding() -> None:
    child_provider = ScriptedProvider(
        ModelResponse((ModelTextBlock("the hidden risk is SECRET-OMEGA"),))
    )
    runner = ChildAgentRunner(provider=child_provider, profile=_profile())
    parent_provider = ScriptedProvider(
        goal_noop_response("delegation-user-supplement"),
        ModelResponse(
            (
                ModelToolCall(
                    "delegate-1",
                    "subagent__delegate",
                    {"objective": "find the hidden risk", "handoff": "design: X"},
                ),
            )
        ),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="subagent-finding-blocked",
                goal_id="goal-1",
                goal_revision=1,
                blocker="Risk: SECRET-OMEGA confirmed",
                safe_attempts=("delegated the bounded review",),
                resume_condition="provide a closed completion oracle",
            ),
        ),
    )
    # subagent__delegate 是 EXTERNAL effectful 工具：合法路径是 Goal 准入之后执行，
    # 所以 parent checkpoint 从已有 durable Goal 的状态起步。
    store = InMemoryCheckpointStore(conversation_with_active_goal("parent-1"))
    runtime = AgentRuntime(
        provider=parent_provider,
        context_manager=KernelContextManager(
            system_policy="policy", limits=ContextLimits(max_input_tokens=8_000, output_reserve=200)
        ),
        tool_runtime=KernelToolRuntime(build_subagent_tool_registrations(runner)),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "parent-invocation",
    )

    first = runtime.run_turn(
        SubmitMessage(
            conversation_id="parent-1",
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            run_id="run-1",
            message="delegate the review",
        ),
        store.load(),
    )
    assert first.status is RunStatus.AWAITING_APPROVAL
    assert first.request is not None

    approved = runtime.run_turn(
        ResolveApproval(
            conversation_id="parent-1",
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            request_id=first.request.request_id,
            binding_digest=first.request.binding_digest,
            approved=True,
        ),
        store.load(),
    )

    assert approved.status is RunStatus.COMPLETED
    # 可核对增量：parent 最终回答包含仅能从 child 获得的 SECRET-OMEGA。
    assert "SECRET-OMEGA" in approved.message
    assert len(parent_provider.calls) == 3
    assert len(child_provider.calls) == 1
