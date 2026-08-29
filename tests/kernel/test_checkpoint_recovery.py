from __future__ import annotations

from pathlib import Path

from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.contracts import (
    ActiveRunStatus,
    ConversationState,
    EgressClass,
    ExecutionAuthorityClass,
    RecoveryRequest,
    SideEffectClass,
    SubmitMessage,
    ToolCall,
)
from agent.runtime.state import (
    accept_action,
    mark_executing,
    pause_for_recovery,
    start_tool_batch,
)


def test_executing_recovery_round_trips_without_live_dependencies(tmp_path: Path) -> None:
    action = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=1,
        expected_revision=0,
        run_id="run-1",
        message="do it",
    )
    state = accept_action(ConversationState.new("conversation-1"), action).state
    state = start_tool_batch(state, (ToolCall("call-1", "write_fixture", {}),))
    state = mark_executing(
        state,
        tool_call_id="call-1",
        intent_digest="intent-1",
        idempotency_key="key-1",
        side_effect=SideEffectClass.WRITE,
        egress=EgressClass.NONE,
        operation="write_file",
        request_identity="key-1",
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
    )
    state = pause_for_recovery(
        state,
        RecoveryRequest(
            request_id="recovery-1",
            run_id="run-1",
            tool_call_id="call-1",
            binding_digest="intent-1",
            summary="unknown",
        ),
    )
    path = tmp_path / "state" / "conversation.json"
    store = LocalCheckpointStore.initialize(path, state)

    restored = store.load().state

    assert restored == state
    assert restored.active_run is not None
    assert restored.active_run.status is ActiveRunStatus.AWAITING_RECOVERY
