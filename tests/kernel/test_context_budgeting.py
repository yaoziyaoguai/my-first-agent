from __future__ import annotations

from dataclasses import replace

import pytest

from agent.runtime.context import ContextLimitError, ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    ContinuationPhase,
    ControlReceipt,
    ConversationFact,
    ConversationState,
    ExecutingIntentRecord,
    FactKind,
    RecoveryRequest,
    Resume,
    SubmitMessage,
    ToolCall,
    canonical_json_digest,
)

# 012 的 reserved control schema 是 mandatory pinned context。这里的测试仍然只测
# history/group 淘汰边界，因此在旧的相对预算上显式加回这项固定成本。
CONTROL_SCHEMA_BUDGET = 970


def _fact(fact_id: str, kind: FactKind, **content):
    return ConversationFact(fact_id=fact_id, kind=kind, content=content)


def _submit() -> SubmitMessage:
    return SubmitMessage(
        conversation_id="conversation-1",
        action_seq=1,
        expected_revision=0,
        run_id="run-1",
        message="current",
    )


def test_oldest_non_pinned_groups_are_evicted_deterministically() -> None:
    state = replace(
        ConversationState.new("conversation-1"),
        facts=(
            _fact("old-user", FactKind.USER_MESSAGE, text="old " * 80),
            _fact("old-assistant", FactKind.ASSISTANT_MESSAGE, text="reply " * 80),
            _fact("recent-user", FactKind.USER_MESSAGE, text="current"),
        ),
    )
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(
            max_input_tokens=CONTROL_SCHEMA_BUDGET + 164,
            output_reserve=20,
        ),
    )

    first = manager.build(state, _submit(), ())
    second = manager.build(state, _submit(), ())

    assert first == second
    assert "recent-user" in first.budget.included_ids
    assert first.budget.excluded_ids == ("old-user", "old-assistant")


def test_pending_recovery_tool_group_is_pinned_under_pressure() -> None:
    state = replace(
        ConversationState.new("conversation-1"),
        active_run=ActiveRun(
            run_id="run-1",
            status=ActiveRunStatus.AWAITING_RECOVERY,
            phase=ContinuationPhase.EXECUTING,
            pending_request=RecoveryRequest(
                request_id="recovery-1",
                run_id="run-1",
                tool_call_id="call-1",
                binding_digest="intent-1",
                summary="unknown outcome",
            ),
            executing_intent=ExecutingIntentRecord(
                tool_call_id="call-1",
                intent_digest="intent-1",
                idempotency_key="key-1",
            ),
            tool_calls=(ToolCall("call-1", "write_file", {}),),
        ),
        facts=(
            _fact(
                "calls-1",
                FactKind.TOOL_CALLS,
                calls=[{"tool_call_id": "call-1", "name": "write_file", "arguments": {}}],
            ),
            _fact("old-user", FactKind.USER_MESSAGE, text="old " * 80),
            _fact("recent-user", FactKind.USER_MESSAGE, text="current"),
        ),
    )
    action = Resume(
        conversation_id="conversation-1",
        action_seq=2,
        expected_revision=1,
    )
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(
            max_input_tokens=CONTROL_SCHEMA_BUDGET + 194,
            output_reserve=20,
        ),
    )

    pack = manager.build(state, action, ())

    assert "calls-1" in pack.budget.included_ids
    assert "recent-user" in pack.budget.included_ids
    assert "old-user" in pack.budget.excluded_ids


def test_pinned_core_too_large_fails_before_any_provider_boundary() -> None:
    state = replace(
        ConversationState.new("conversation-1"),
        facts=(_fact("recent-user", FactKind.USER_MESSAGE, text="x" * 400),),
    )
    manager = KernelContextManager(
        system_policy="policy" * 20,
        limits=ContextLimits(max_input_tokens=30, output_reserve=10),
    )

    with pytest.raises(ContextLimitError) as exc:
        manager.build(state, _submit(), ())

    assert exc.value.code == "context_core_too_large"


def test_context_module_has_no_semantic_compaction_or_provider_call(monkeypatch) -> None:
    state = replace(
        ConversationState.new("conversation-1"),
        facts=(_fact("recent-user", FactKind.USER_MESSAGE, text="current"),),
    )
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(
            max_input_tokens=CONTROL_SCHEMA_BUDGET + 144,
            output_reserve=10,
        ),
    )
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("unexpected input"))

    pack = manager.build(state, _submit(), ())

    assert (
        pack.budget.estimated_input_tokens + pack.budget.output_reserve
        <= CONTROL_SCHEMA_BUDGET + 144
    )


def test_output_reserve_reduces_the_available_input_budget() -> None:
    state = replace(
        ConversationState.new("conversation-1"),
        facts=(
            _fact("old-user", FactKind.USER_MESSAGE, text="old " * 40),
            _fact("recent-user", FactKind.USER_MESSAGE, text="current"),
        ),
    )
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(
            max_input_tokens=CONTROL_SCHEMA_BUDGET + 154,
            output_reserve=30,
        ),
    )

    pack = manager.build(state, _submit(), ())

    assert (
        pack.budget.estimated_input_tokens + pack.budget.output_reserve
        <= CONTROL_SCHEMA_BUDGET + 154
    )
    assert "old-user" in pack.budget.excluded_ids


def test_control_receipt_continuity_is_pinned_and_budgeted() -> None:
    receipts = tuple(
        ControlReceipt.create(
            correlation_id=f"control-{index}",
            control_kind="goal_progress",
            goal_id="goal-1",
            goal_revision=1,
            accepted_state_revision=7,
            payload_digest=canonical_json_digest({"note": "progress", "index": index}),
        )
        for index in range(12)
    )
    state = replace(
        ConversationState.new("conversation-1"),
        control_receipts=receipts,
    )
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=100, output_reserve=20),
    )

    with pytest.raises(ContextLimitError) as exc:
        manager.build(state, _submit(), ())

    assert exc.value.code == "context_core_too_large"
