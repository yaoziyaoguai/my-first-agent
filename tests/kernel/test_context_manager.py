from __future__ import annotations

from dataclasses import replace

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ControlReceipt,
    ConversationFact,
    ConversationState,
    FactKind,
    GoalFrame,
    GoalStatus,
    ProposedCriterion,
    SideEffectClass,
    SubmitMessage,
    ToolDefinition,
    canonical_json_digest,
)

CONTROL_SCHEMA_BUDGET = 970


def _fact(fact_id: str, kind: FactKind, **content):
    return ConversationFact(fact_id=fact_id, kind=kind, content=content)


def _action(message: str = "current question") -> SubmitMessage:
    return SubmitMessage(
        conversation_id="conversation-1",
        action_seq=3,
        expected_revision=2,
        run_id="run-1",
        message=message,
    )


def test_context_pack_is_provider_neutral_and_explainable() -> None:
    state = replace(
        ConversationState.new("conversation-1"),
        facts=(
            _fact("user-1", FactKind.USER_MESSAGE, text="first"),
            _fact("assistant-1", FactKind.ASSISTANT_MESSAGE, text="answer"),
            _fact("user-2", FactKind.USER_MESSAGE, text="current question"),
        ),
    )
    tools = (
        ToolDefinition(
            name="read_file",
            description="Read one bounded file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        ),
    )
    manager = KernelContextManager(
        system_policy="Follow the tool policy.",
        limits=ContextLimits(
            max_input_tokens=CONTROL_SCHEMA_BUDGET + 300,
            output_reserve=60,
        ),
    )

    pack = manager.build(state, _action(), tools)

    assert pack.system == "Follow the tool policy."
    assert pack.tools == tools
    assert pack.budget.output_reserve == 60
    assert pack.budget.estimated_input_tokens <= pack.budget.input_limit
    assert "user-2" in pack.budget.included_ids
    assert any(
        block.get("text") == "current question"
        for message in pack.messages
        for block in message.content
    )


def test_effectful_tool_definitions_are_hidden_until_goal_is_durable() -> None:
    state = replace(
        ConversationState.new("conversation-1"),
        facts=(_fact("user-2", FactKind.USER_MESSAGE, text="create report.md"),),
    )
    tools = (
        ToolDefinition(
            name="read_file",
            description="Read one file",
            input_schema={"type": "object", "properties": {}},
        ),
        ToolDefinition(
            name="write_file",
            description="Write one file",
            input_schema={"type": "object", "properties": {}},
            side_effect=SideEffectClass.WRITE,
        ),
    )
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=8_000, output_reserve=500),
        workspace_scope_digest="workspace-1",
    )

    before = manager.build(state, _action("create report.md"), tools)
    goal = GoalFrame(
        goal_id="goal-1",
        revision=1,
        created_from_fact_ids=("user-2",),
        workspace_identity_digest="workspace-1",
        user_outcome="create report.md",
        beneficiary="user",
        targets=("report.md",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(ProposedCriterion("criterion-1", "report.md exists"),),
        admitted_criteria=(),
        authority_snapshot="fixed-composition",
        status=GoalStatus.GOAL_READY,
        created_at="2026-08-02T00:00:00Z",
        updated_at="2026-08-02T00:00:00Z",
    )
    after = manager.build(replace(state, goal=goal), _action("continue"), tools)

    assert tuple(tool.name for tool in before.tools) == ("read_file",)
    assert tuple(tool.name for tool in after.tools) == ("read_file", "write_file")


def test_tool_calls_and_results_are_one_atomic_group() -> None:
    state = replace(
        ConversationState.new("conversation-1"),
        facts=(
            _fact(
                "calls-1",
                FactKind.TOOL_CALLS,
                calls=[
                    {"tool_call_id": "call-1", "name": "read_file", "arguments": {"path": "a"}},
                    {"tool_call_id": "call-2", "name": "read_file", "arguments": {"path": "b"}},
                ],
            ),
            _fact(
                "result-1",
                FactKind.TOOL_RESULT,
                tool_call_id="call-1",
                text="A" * 120,
                is_error=False,
            ),
            _fact(
                "result-2",
                FactKind.TOOL_RESULT,
                tool_call_id="call-2",
                text="B" * 120,
                is_error=False,
            ),
            _fact(
                "calls-2",
                FactKind.TOOL_CALLS,
                calls=[{"tool_call_id": "call-3", "name": "read_file", "arguments": {"path": "c"}}],
            ),
            _fact(
                "result-3",
                FactKind.TOOL_RESULT,
                tool_call_id="call-3",
                text="recent",
                is_error=False,
            ),
            _fact("user-current", FactKind.USER_MESSAGE, text="current question"),
        ),
    )
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(
            max_input_tokens=CONTROL_SCHEMA_BUDGET + 204,
            output_reserve=20,
            max_tool_result_chars=200,
        ),
    )

    pack = manager.build(state, _action(), ())

    group_ids = {"calls-1", "result-1", "result-2"}
    included = group_ids.intersection(pack.budget.included_ids)
    excluded = group_ids.intersection(pack.budget.excluded_ids)
    assert included in (set(), group_ids)
    assert excluded in (set(), group_ids)
    assert included != excluded


def test_large_tool_result_is_clipped_before_budgeting() -> None:
    state = replace(
        ConversationState.new("conversation-1"),
        facts=(
            _fact(
                "calls-1",
                FactKind.TOOL_CALLS,
                calls=[{"tool_call_id": "call-1", "name": "read_file", "arguments": {"path": "a"}}],
            ),
            _fact(
                "result-1",
                FactKind.TOOL_RESULT,
                tool_call_id="call-1",
                text="sensitive-looking-but-fixture-only:" + "x" * 200,
                is_error=False,
            ),
            _fact("user-current", FactKind.USER_MESSAGE, text="current question"),
        ),
    )
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(
            max_input_tokens=CONTROL_SCHEMA_BUDGET + 300,
            output_reserve=30,
            max_tool_result_chars=24,
        ),
    )

    pack = manager.build(state, _action(), ())

    assert pack.budget.clipped_ids == ("result-1",)
    result_block = next(
        block
        for message in pack.messages
        for block in message.content
        if block.get("type") == "tool_result"
    )
    assert result_block["original_chars"] > 24
    assert result_block["reason"] == "tool_result_char_limit"
    assert len(result_block["sha256"]) == 64


def test_context_manager_projects_reserved_control_separately_from_product_tools() -> None:
    receipt = ControlReceipt.create(
        correlation_id="control-1",
        control_kind="goal_progress",
        goal_id="goal-1",
        goal_revision=1,
        accepted_state_revision=7,
        payload_digest=canonical_json_digest({"note": "progress"}),
    )
    state = replace(
        ConversationState.new("conversation-1"),
        facts=(_fact("user-1", FactKind.USER_MESSAGE, text="current question"),),
        control_receipts=(receipt,),
    )
    tools = (
        ToolDefinition(
            name="read_file",
            description="Read one bounded file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        ),
    )
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=2000, output_reserve=100),
    )

    pack = manager.build(state, _action(), tools)

    assert pack.control_receipts == (receipt,)
    assert pack.control_schema["name"] == "first_agent_control_v1"
    schema = pack.control_schema["input_schema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["kind"]["enum"] == [
        "clarification_request",
        "goal_proposal",
        "goal_progress",
        "goal_delta_proposal",
        "completion_claim",
        "blocked_claim",
    ]
    assert pack.tools == tools
    assert all(tool.name != "first_agent_control_v1" for tool in pack.tools)
