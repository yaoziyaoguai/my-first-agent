"""Checkpoint v7 native sandbox authority codec and v6 invalidation。"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from agent.runtime.checkpoint import (
    CheckpointInvariantError,
    CheckpointVersionError,
    _decode_state,
    _encode_state,
)
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    ApprovalRequest,
    ContinuationPhase,
    ConversationWorkspaceBindingV1,
    SandboxAuthorityCandidateV1,
    SandboxAuthorityLeaseV1,
    ToolCall,
)
from tests.kernel.fakes import conversation_with_active_goal

HEX_A = "a" * 64
HEX_B = "b" * 64


def _candidate() -> SandboxAuthorityCandidateV1:
    return SandboxAuthorityCandidateV1.create(
        candidate_id="sandbox-candidate:one",
        goal_id="goal-1",
        goal_revision=1,
        workspace_identity_digest="workspace-digest-1",
        original_command_fingerprint=HEX_A,
        policy_digest=HEX_B,
        mode="workspace-write",
        network="off",
        readable_command="/usr/bin/true",
        trust_notice_id="native_sandbox_v1",
        trust_notice_digest=HEX_A,
        issued_at="2026-08-27T08:00:00+00:00",
    )


def _lease() -> SandboxAuthorityLeaseV1:
    return SandboxAuthorityLeaseV1.create(
        lease_id="sandbox-lease:one",
        candidate_digest=HEX_A,
        goal_id="goal-1",
        goal_revision=1,
        workspace_identity_digest="workspace-digest-1",
        original_command_fingerprint=HEX_A,
        policy_digest=HEX_B,
        mode="workspace-write",
        network="off",
        readable_command="/usr/bin/true",
        trust_notice_id="native_sandbox_v1",
        trust_notice_digest=HEX_A,
        approved_request_identity="approval-one",
        issued_at="2026-08-27T08:00:00+00:00",
        expires_at="2026-08-27T10:00:00+00:00",
    )


def _state_with_pending_candidate():  # noqa: ANN202
    state = conversation_with_active_goal()
    return replace(
        state,
        active_run=ActiveRun(
            run_id="run-one",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            tool_calls=(ToolCall("call-one", "sandbox_exec", {}),),
            pending_request=ApprovalRequest(
                request_id="approval-one",
                run_id="run-one",
                tool_call_id="call-one",
                binding_digest=HEX_A,
                preview="/usr/bin/true",
                sandbox_authority_candidate=_candidate(),
            ),
        ),
    )


def test_v8_round_trips_native_one_shot_lease_exactly() -> None:
    state = replace(conversation_with_active_goal(), sandbox_leases=(_lease(),))
    payload = json.loads(_encode_state(state))
    assert payload["schema_version"] == 8
    encoded = payload["state"]["sandbox_leases"][0]
    assert encoded["original_command_fingerprint"] == HEX_A
    assert "image_digest" not in encoded
    assert _decode_state(_encode_state(state)).sandbox_leases == (_lease(),)


def test_v7_round_trips_pending_native_candidate_exactly() -> None:
    state = _state_with_pending_candidate()
    decoded = _decode_state(_encode_state(state))
    assert decoded.active_run.pending_request.sandbox_authority_candidate == _candidate()


@pytest.mark.parametrize("mutation", ["unknown", "missing", "forged"])
def test_v7_rejects_unknown_missing_and_forged_native_candidate_fields(
    mutation: str,
) -> None:
    payload = json.loads(_encode_state(_state_with_pending_candidate()))
    candidate = payload["state"]["active_run"]["pending_request"][
        "sandbox_authority_candidate"
    ]
    if mutation == "unknown":
        candidate["extra"] = True
    elif mutation == "missing":
        del candidate["network"]
    else:
        candidate["policy_digest"] = HEX_A
    with pytest.raises((CheckpointInvariantError, CheckpointVersionError)):
        _decode_state(json.dumps(payload).encode())


def test_v7_rejects_unknown_missing_and_forged_native_lease_fields() -> None:
    state = replace(conversation_with_active_goal(), sandbox_leases=(_lease(),))
    for mutation in ("unknown", "missing", "forged"):
        payload = json.loads(_encode_state(state))
        lease = payload["state"]["sandbox_leases"][0]
        if mutation == "unknown":
            lease["extra"] = True
        elif mutation == "missing":
            del lease["network"]
        else:
            lease["policy_digest"] = HEX_A
        with pytest.raises((CheckpointInvariantError, CheckpointVersionError)):
            _decode_state(json.dumps(payload).encode())


def test_v6_docker_lease_is_invalidated_instead_of_resigned() -> None:
    state = replace(conversation_with_active_goal(), sandbox_leases=(_lease(),))
    payload = json.loads(_encode_state(state))
    payload["schema_version"] = 6
    del payload["state"]["background_occurrence_binding"]
    payload["state"]["sandbox_leases"] = [
        {
            "lease_id": "docker-lease",
            "lease_digest": HEX_A,
            "candidate_digest": HEX_A,
            "goal_id": "goal-1",
            "goal_revision": 1,
            "workspace_identity_digest": "workspace-digest-1",
            "image_digest": "sha256:" + HEX_A,
            "workspace_snapshot_digest": HEX_A,
            "spec_digest": HEX_A,
            "network_policy_digest": HEX_A,
            "resource_limits_digest": HEX_A,
            "readable_command": "docker exec",
            "approved_request_identity": "approval-old",
            "issued_at": "2026-08-27T08:00:00+00:00",
            "expires_at": "2026-08-27T10:00:00+00:00",
            "max_uses": 64,
            "uses_consumed": 0,
        }
    ]
    decoded = _decode_state(json.dumps(payload).encode())
    assert decoded.sandbox_leases == ()


def test_v6_non_sandbox_contract_still_migrates() -> None:
    state = replace(
        conversation_with_active_goal(),
        workspace_binding=ConversationWorkspaceBindingV1.create(
            workspace_scope_digest=HEX_A,
            workspace_identity_digest="workspace-digest-1",
            bound_at="2026-08-27T08:00:00+00:00",
        ),
    )
    payload = json.loads(_encode_state(state))
    payload["schema_version"] = 6
    del payload["state"]["background_occurrence_binding"]
    decoded = _decode_state(json.dumps(payload).encode())
    assert decoded.goal == state.goal
    assert decoded.sandbox_leases == ()
