from __future__ import annotations

import pytest

from agent.runtime.contracts import (
    ActionDisposition,
    ActiveRunStatus,
    ContinuationPhase,
    ConversationFact,
    FactKind,
    RecoveryRequest,
    RecoveryResolution,
    ResolveUnknownToolOutcome,
    SubmitMessage,
    ToolCall,
)
from agent.runtime.state import (
    accept_action,
    mark_executing,
    pause_for_recovery,
    record_tool_result,
    start_tool_batch,
)


def _started_state():
    started = accept_action(
        None,
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="hello",
        ),
    ).state
    return start_tool_batch(
        started,
        (ToolCall("tool-call-1", "write_fixture", {}),),
    )


def test_executing_continuation_has_only_bound_result_or_recovery_paths() -> None:
    state = mark_executing(
        _started_state(),
        tool_call_id="tool-call-1",
        intent_digest="intent-1",
        idempotency_key="conversation-1:run-1:tool-call-1",
    )

    assert state.active_run is not None
    assert state.active_run.phase is ContinuationPhase.EXECUTING

    result = ConversationFact(
        fact_id="tool-result-1",
        kind=FactKind.TOOL_RESULT,
        content={"tool_call_id": "tool-call-1", "text": "ok", "is_error": False},
    )
    continued = record_tool_result(state, result, intent_digest="intent-1")
    assert continued.active_run is not None
    assert continued.active_run.phase is ContinuationPhase.MODEL
    assert continued.active_run.executing_intent is None

    with pytest.raises(ValueError, match="matching EXECUTING"):
        record_tool_result(continued, result, intent_digest="intent-1")


def test_unknown_outcome_requires_exact_human_classification() -> None:
    executing = mark_executing(
        _started_state(),
        tool_call_id="tool-call-1",
        intent_digest="intent-1",
        idempotency_key="key-1",
    )
    recovering = pause_for_recovery(
        executing,
        RecoveryRequest(
            request_id="recovery-1",
            run_id="run-1",
            tool_call_id="tool-call-1",
            binding_digest="intent-1",
            summary="tool outcome is unknown",
        ),
    )

    assert recovering.active_run is not None
    assert recovering.active_run.status is ActiveRunStatus.AWAITING_RECOVERY

    action = ResolveUnknownToolOutcome(
        conversation_id="conversation-1",
        action_seq=2,
        expected_revision=recovering.revision,
        request_id="recovery-1",
        binding_digest="intent-1",
        resolution=RecoveryResolution.MARK_SUCCEEDED,
    )
    resolved = accept_action(recovering, action)

    assert resolved.disposition is ActionDisposition.ACCEPTED
    assert resolved.state.active_run is not None
    assert resolved.state.active_run.status is ActiveRunStatus.RUNNABLE
    assert resolved.state.active_run.executing_intent is None
    assert resolved.state.facts[-1].kind is FactKind.TOOL_RESULT
    assert resolved.state.facts[-1].content["synthetic"] is True


def test_tool_batch_rejects_duplicate_call_ids_before_any_effect() -> None:
    started = accept_action(
        None,
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="hello",
        ),
    ).state

    with pytest.raises(ValueError, match="unique within a batch"):
        start_tool_batch(
            started,
            (
                ToolCall("duplicate", "first_tool", {}),
                ToolCall("duplicate", "second_tool", {}),
            ),
        )
