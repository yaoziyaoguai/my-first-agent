"""017 native sandbox authority：exact command/policy + one-shot lease。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    ApprovalRequest,
    ContinuationPhase,
    ConversationState,
    EgressClass,
    ExecutionAuthorityClass,
    GoalStatus,
    ResolveApproval,
    SandboxAuthorityCandidateV1,
    SandboxAuthorityLeaseV1,
    SandboxReceiptV1,
    SideEffectClass,
    ToolCall,
)
from agent.runtime.state import _apply_action, cancel_goal, mark_executing, pause_goal
from tests.kernel.fakes import conversation_with_active_goal

HEX_A = "a" * 64
HEX_B = "b" * 64
NOW = "2026-08-27T08:00:00+00:00"


def _candidate(**overrides) -> SandboxAuthorityCandidateV1:
    values = {
        "candidate_id": "sandbox-candidate:one",
        "goal_id": "goal-1",
        "goal_revision": 1,
        "workspace_identity_digest": "workspace-digest-1",
        "original_command_fingerprint": HEX_A,
        "policy_digest": HEX_B,
        "mode": "workspace-write",
        "network": "off",
        "readable_command": "/usr/bin/true (cwd=., workspace-write, network=off)",
        "trust_notice_id": "native_sandbox_v1",
        "trust_notice_digest": HEX_A,
        "issued_at": NOW,
    }
    values.update(overrides)
    return SandboxAuthorityCandidateV1.create(**values)


def _lease(**overrides) -> SandboxAuthorityLeaseV1:
    candidate = _candidate()
    values = {
        "lease_id": "sandbox-lease:one",
        "candidate_digest": candidate.candidate_digest,
        "goal_id": candidate.goal_id,
        "goal_revision": candidate.goal_revision,
        "workspace_identity_digest": candidate.workspace_identity_digest,
        "original_command_fingerprint": candidate.original_command_fingerprint,
        "policy_digest": candidate.policy_digest,
        "mode": candidate.mode,
        "network": candidate.network,
        "readable_command": candidate.readable_command,
        "trust_notice_id": candidate.trust_notice_id,
        "trust_notice_digest": candidate.trust_notice_digest,
        "approved_request_identity": "approval-one",
        "issued_at": NOW,
        "expires_at": "2026-08-27T10:00:00+00:00",
    }
    values.update(overrides)
    return SandboxAuthorityLeaseV1.create(**values)


def test_candidate_digest_binds_exact_command_policy_and_trust_notice() -> None:
    candidate = _candidate()
    for change in (
        {"original_command_fingerprint": HEX_B},
        {"policy_digest": HEX_A},
        {"mode": "read-only"},
        {"network": "full"},
        {"trust_notice_id": "different"},
    ):
        assert _candidate(**change).candidate_digest != candidate.candidate_digest
    assert not hasattr(candidate, "image_digest")
    assert not hasattr(candidate, "workspace_snapshot_digest")
    assert candidate.execution_authority is ExecutionAuthorityClass.ISOLATED_SANDBOX


def test_candidate_rejects_open_policy_values_and_forged_digest() -> None:
    with pytest.raises(ValueError, match="mode"):
        _candidate(mode="custom")
    with pytest.raises(ValueError, match="network"):
        _candidate(network="allowlist")
    candidate = _candidate()
    with pytest.raises(ValueError, match="digest mismatch"):
        replace(candidate, policy_digest=HEX_A)


def test_lease_is_exact_one_shot_and_all_mutations_miss() -> None:
    lease = _lease()
    assert lease.max_uses == 1
    exact = {
        "goal_id": "goal-1",
        "goal_revision": 1,
        "workspace_identity_digest": "workspace-digest-1",
        "original_command_fingerprint": HEX_A,
        "policy_digest": HEX_B,
        "mode": "workspace-write",
        "network": "off",
    }
    assert lease.matches(**exact)
    for field, value in (
        ("goal_revision", 2),
        ("workspace_identity_digest", "workspace-other"),
        ("original_command_fingerprint", HEX_B),
        ("policy_digest", HEX_A),
        ("mode", "read-only"),
        ("network", "full"),
    ):
        changed = {**exact, field: value}
        assert not lease.matches(**changed)
    assert lease.with_use_consumed(1).uses_consumed == 1
    with pytest.raises(ValueError, match="budget exhausted"):
        lease.with_use_consumed(2)


def _awaiting_approval() -> ConversationState:
    state = conversation_with_active_goal()
    candidate = _candidate()
    request = ApprovalRequest(
        request_id="approval-one",
        run_id="run-one",
        tool_call_id="call-one",
        binding_digest=HEX_A,
        preview=candidate.readable_command,
        tool_name="sandbox_exec",
        sandbox_authority_candidate=candidate,
    )
    return replace(
        state,
        active_run=ActiveRun(
            run_id="run-one",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            tool_calls=(ToolCall("call-one", "sandbox_exec", {}),),
            pending_request=request,
        ),
    )


def _approval(state: ConversationState, *, approved: bool) -> ResolveApproval:
    return ResolveApproval(
        conversation_id=state.conversation_id,
        action_seq=1,
        expected_revision=state.revision,
        request_id="approval-one",
        binding_digest=HEX_A,
        approved=approved,
        approved_at="2026-08-27T08:01:00+00:00",
    )


def test_approval_mints_exact_one_shot_lease_and_rejection_mints_none() -> None:
    state = _awaiting_approval()
    approved = _apply_action(state, _approval(state, approved=True))
    lease = approved.sandbox_leases[0]
    candidate = state.active_run.pending_request.sandbox_authority_candidate
    assert lease.candidate_digest == candidate.candidate_digest
    assert lease.original_command_fingerprint == candidate.original_command_fingerprint
    assert lease.policy_digest == candidate.policy_digest
    assert lease.max_uses == 1 and lease.uses_consumed == 0
    rejected = _apply_action(state, _approval(state, approved=False))
    assert rejected.sandbox_leases == ()


def test_mark_executing_consumes_sandbox_lease_once() -> None:
    state = _awaiting_approval()
    approved = _apply_action(state, _approval(state, approved=True))
    executing = mark_executing(
        approved,
        tool_call_id="call-one",
        intent_digest=HEX_B,
        idempotency_key="conversation-1:run-one:call-one",
        side_effect=SideEffectClass.EXTERNAL,
        egress=EgressClass.NONE,
        operation="sandbox_exec",
        request_identity="conversation-1:run-one:call-one",
        execution_authority=ExecutionAuthorityClass.ISOLATED_SANDBOX,
        sandbox_lease_id=approved.sandbox_leases[0].lease_id,
    )
    assert executing.sandbox_leases[0].uses_consumed == 1
    with pytest.raises(ValueError, match="sandbox lease"):
        mark_executing(
            approved,
            tool_call_id="call-one",
            intent_digest=HEX_B,
            idempotency_key="conversation-1:run-one:call-one",
            side_effect=SideEffectClass.EXTERNAL,
            egress=EgressClass.NONE,
            operation="sandbox_exec",
            request_identity="conversation-1:run-one:call-one",
            execution_authority=ExecutionAuthorityClass.ISOLATED_SANDBOX,
            sandbox_lease_id="missing",
        )


def test_goal_pause_cancel_and_terminal_state_revoke_sandbox_authority() -> None:
    state = replace(conversation_with_active_goal(), sandbox_leases=(_lease(),))
    assert pause_goal(state, goal_id="goal-1", expected_revision=1).sandbox_leases == ()
    assert cancel_goal(state, goal_id="goal-1", expected_revision=1).sandbox_leases == ()
    with pytest.raises(ValueError, match="terminal goal"):
        replace(state, goal=replace(state.goal, status=GoalStatus.CANCELLED))


def test_receipt_strictly_binds_authority_enforcement_and_draft() -> None:
    lease = _lease()
    receipt = SandboxReceiptV1.create(
        receipt_id="sandbox-receipt:one",
        lease_id=lease.lease_id,
        lease_digest=lease.lease_digest,
        candidate_digest=lease.candidate_digest,
        goal_id=lease.goal_id,
        goal_revision=lease.goal_revision,
        workspace_identity_digest=lease.workspace_identity_digest,
        original_command_fingerprint=lease.original_command_fingerprint,
        policy_digest=lease.policy_digest,
        mode=lease.mode,
        network=lease.network,
        backend="seatbelt",
        enforcement="confined",
        profile_digest=HEX_A,
        outcome="exited",
        draft_digest=HEX_B,
        issued_at=NOW,
    )
    assert SandboxReceiptV1.from_json(receipt.to_json()) == receipt
    with pytest.raises(ValueError):
        SandboxReceiptV1.from_json({**receipt.to_json(), "image_digest": HEX_A})
    values = receipt._digest_values()
    values.update(receipt_id="sandbox-receipt:danger", mode="danger-full-access")
    with pytest.raises(ValueError, match="danger-full-access"):
        SandboxReceiptV1.create(**values)
