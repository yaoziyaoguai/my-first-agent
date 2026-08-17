from __future__ import annotations

import pytest

from agent.cli.actions import (
    build_cancel,
    build_recover_unknown_observation,
    build_resolve_approval,
    build_resolve_recovery,
    build_resume,
    build_submit,
)
from agent.runtime.contracts import (
    ActionDisposition,
    ApprovalRequest,
    ConversationState,
    EgressClass,
    RecoverUnknownObservation,
    RecoveryRequest,
    RecoveryResolution,
    SideEffectClass,
    ToolCall,
)
from agent.runtime.state import (
    accept_action,
    mark_executing,
    pause_for_approval,
    pause_for_recovery,
    start_tool_batch,
)


def _ready() -> ConversationState:
    return ConversationState.new("conversation-1")


def test_build_submit_binds_authoritative_state() -> None:
    state = _ready()
    action = build_submit(state, message="hello", run_id="run-1")
    assert action.conversation_id == "conversation-1"
    assert action.action_seq == 1
    assert action.expected_revision == 0
    assert action.run_id == "run-1"
    assert action.message == "hello"


def test_build_submit_rejects_empty_message() -> None:
    with pytest.raises(ValueError):
        build_submit(_ready(), message="   ", run_id="run-1")


def test_pending_resolution_carries_exact_identity() -> None:
    started = accept_action(None, build_submit(_ready(), message="hi", run_id="run-1")).state
    started = start_tool_batch(started, (ToolCall("call-1", "write_file", {}),))
    paused = pause_for_approval(
        started,
        ApprovalRequest(
            request_id="approval-1",
            run_id="run-1",
            tool_call_id="call-1",
            binding_digest="binding-1",
            preview="write",
        ),
    )
    resolve = build_resolve_approval(
        paused, request_id="approval-1", binding_digest="binding-1", approved=True
    )
    assert resolve.request_id == "approval-1"
    assert resolve.binding_digest == "binding-1"
    assert resolve.approved is True
    assert resolve.action_seq == paused.next_action_seq


def test_cancel_on_executing_is_unchanged_conflict_via_shared_reducer() -> None:
    started = accept_action(None, build_submit(_ready(), message="hi", run_id="run-1")).state
    batched = start_tool_batch(started, (ToolCall("call-1", "write_file", {}),))
    executing = mark_executing(
        batched, tool_call_id="call-1", intent_digest="d", idempotency_key="k"
    )
    cancel = build_cancel(executing)
    transition = accept_action(executing, cancel)
    assert transition.disposition is ActionDisposition.CONFLICT
    assert transition.state == executing


def test_resume_into_recovery_then_only_exact_resolution_progresses() -> None:
    started = accept_action(None, build_submit(_ready(), message="hi", run_id="run-1")).state
    batched = start_tool_batch(started, (ToolCall("call-1", "write_file", {}),))
    executing = mark_executing(
        batched, tool_call_id="call-1", intent_digest="d", idempotency_key="k"
    )
    recovering = pause_for_recovery(
        executing,
        RecoveryRequest(
            request_id="recovery-1",
            run_id="run-1",
            tool_call_id="call-1",
            binding_digest="d",
            summary="unknown",
        ),
    )
    # AWAITING_RECOVERY 上 Resume/Cancel 都 unchanged，只有 exact resolution 推进。
    resume_disposition = accept_action(recovering, build_resume(recovering)).disposition
    assert resume_disposition is ActionDisposition.CONFLICT
    cancel_disposition = accept_action(recovering, build_cancel(recovering)).disposition
    assert cancel_disposition is ActionDisposition.CONFLICT
    resolve = build_resolve_recovery(
        recovering,
        request_id="recovery-1",
        binding_digest="d",
        resolution=RecoveryResolution.MARK_FAILED,
    )
    assert accept_action(recovering, resolve).disposition is ActionDisposition.ACCEPTED


def test_public_observation_recovery_builder_binds_persisted_executing_intent() -> None:
    started = accept_action(None, build_submit(_ready(), message="hi", run_id="run-1")).state
    batched = start_tool_batch(started, (ToolCall("call-1", "web_search", {}),))
    executing = mark_executing(
        batched,
        tool_call_id="call-1",
        intent_digest="public-intent",
        idempotency_key="request-1",
        side_effect=SideEffectClass.READ_ONLY,
        egress=EgressClass.PUBLIC_NETWORK,
        operation="search",
        request_identity="request-1",
    )
    recovering = pause_for_recovery(
        executing,
        RecoveryRequest(
            request_id="recovery-1",
            run_id="run-1",
            tool_call_id="call-1",
            binding_digest="public-intent",
            summary="public observation outcome unknown",
        ),
    )

    action = build_recover_unknown_observation(recovering)

    assert isinstance(action, RecoverUnknownObservation)
    assert action.tool_call_id == "call-1"
    assert action.intent_digest == "public-intent"
    assert accept_action(recovering, action).disposition is ActionDisposition.ACCEPTED
