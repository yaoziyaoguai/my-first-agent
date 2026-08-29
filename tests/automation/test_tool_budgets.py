from __future__ import annotations

from dataclasses import replace

import pytest

from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.contracts import (
    ActiveRun,
    BackgroundActionAuthorityV1,
    ContinuationPhase,
    ConversationState,
    EgressClass,
    ExecutionAuthorityClass,
    SideEffectClass,
    ToolCall,
)
from agent.runtime.state import mark_executing

from .test_runtime_binding import _binding


def _state(
    *,
    tool_calls_used: int = 0,
    sandbox_commands_used: int = 0,
) -> ConversationState:
    state = ConversationState.new(
        "conversation:background-budget",
        background_occurrence_binding=_binding(),
    )
    return replace(
        state,
        active_run=ActiveRun(
            run_id="run:background-budget",
            phase=ContinuationPhase.TOOL,
            owner_invocation_id="invocation:background-budget",
            tool_calls=(ToolCall("call:budget", "sandbox_exec", {}),),
            tool_calls_used=tool_calls_used,
            sandbox_commands_used=sandbox_commands_used,
        ),
    )


def _action(*, ordinal: int) -> BackgroundActionAuthorityV1:
    return BackgroundActionAuthorityV1(
        action_class="sandbox_confined",
        action_fingerprint="1" * 64,
        occurrence_binding_digest=_binding().binding_digest,
        claim_verdict_digest="2" * 64,
        budget_ordinal=ordinal,
        policy_digest="3" * 64,
    )


def _mark(state: ConversationState, *, ordinal: int) -> ConversationState:
    return mark_executing(
        state,
        tool_call_id="call:budget",
        intent_digest="4" * 64,
        idempotency_key="background-budget:call",
        side_effect=SideEffectClass.EXTERNAL,
        egress=EgressClass.NONE,
        operation="sandbox_exec",
        execution_authority=ExecutionAuthorityClass.ISOLATED_SANDBOX,
        background_action_authority=_action(ordinal=ordinal),
    )


def test_background_tool_and_class_budgets_increment_in_executing_checkpoint(
    tmp_path,
) -> None:
    executing = _mark(_state(tool_calls_used=3, sandbox_commands_used=1), ordinal=2)

    assert executing.active_run is not None
    assert executing.active_run.tool_calls_used == 4
    assert executing.active_run.sandbox_commands_used == 2
    restored = LocalCheckpointStore.initialize(
        tmp_path / "checkpoint.json",
        executing,
    ).load().state
    assert restored.active_run == executing.active_run


@pytest.mark.parametrize(
    ("state", "ordinal", "message"),
    [
        (_state(tool_calls_used=8), 1, "tool-call budget"),
        (_state(sandbox_commands_used=2), 3, "sandbox_confined budget"),
        (_state(sandbox_commands_used=1), 1, "does not bind"),
    ],
)
def test_background_budget_reuse_and_wrong_ordinal_fail_closed(
    state: ConversationState,
    ordinal: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _mark(state, ordinal=ordinal)
