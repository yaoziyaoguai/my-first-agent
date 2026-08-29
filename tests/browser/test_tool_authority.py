"""018 Task 6：browser action authority 必须经唯一 ToolRuntime。"""

from dataclasses import replace

from agent.runtime.contracts import (
    ApprovalPolicy,
    ApprovalRequired,
    BrowserAuthorityLeaseV1,
    EgressClass,
    ExecutionAuthorityClass,
    ExecutionIntent,
    OutputPolicy,
    SideEffectClass,
    ToolCall,
    ToolPrepareContext,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.tools import KernelToolRuntime, RegisteredTool

NOW = "2026-08-28T10:00:00+00:00"
EXPIRES = "2026-08-28T11:00:00+00:00"
SESSION = "session-0123456789abcdef"
PROFILE = "profile-0123456789abcdef"


def _binding(*, action_digest: str = "3" * 64) -> dict:
    return {
        "session_ref": SESSION,
        "browser_identity_digest": "a" * 64,
        "profile_ref": PROFILE,
        "profile_revision": 3,
        "allowed_origins": ["https://site.example.test"],
        "mode": "site_bound_interactive",
        "page_id": SESSION,
        "frame_id": "main",
        "observation_digest": "1" * 64,
        "action_digest": action_digest,
        "consequence": "disclose",
        "effect_preview": "disclose; fill_form; https://site.example.test",
        "issued_at": NOW,
        "expires_at": EXPIRES,
    }


def _registration(binding: dict) -> RegisteredTool:
    return RegisteredTool(
        spec=ToolSpec(
            name="browser_act",
            version="1",
            description="Execute one bound browser action",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            risk=ToolRisk.HIGH,
            side_effect=SideEffectClass.EXTERNAL,
            output_policy=OutputPolicy.BOUNDED_TEXT,
            approval_policy=ApprovalPolicy.ALWAYS,
            safety_policy={"kind": "browser_action"},
            output_limit_chars=1_000,
            egress=EgressClass.GOVERNED_NETWORK,
            execution_authority=ExecutionAuthorityClass.BROWSER_SESSION,
        ),
        prepare_binding=lambda _arguments: dict(binding),
        func=lambda _intent: "ok",
    )


def _context(*, leases=()) -> ToolPrepareContext:
    return ToolPrepareContext(
        conversation_id="conversation-1",
        run_id="run-1",
        state_revision=7,
        approval_basis_revision=7,
        goal_id="goal-1",
        goal_revision=2,
        workspace_identity_digest="w" * 64,
        browser_leases=tuple(leases),
    )


def _lease(request: ApprovalRequired) -> BrowserAuthorityLeaseV1:
    candidate = request.request.browser_action_candidate
    assert candidate is not None
    return BrowserAuthorityLeaseV1.create(
        lease_id="browser-lease-1",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        session_ref=candidate.session_ref,
        browser_identity_digest=candidate.browser_identity_digest,
        profile_ref=candidate.profile_ref,
        profile_revision=candidate.profile_revision,
        allowed_origins=candidate.allowed_origins,
        mode=candidate.mode,
        page_id=candidate.page_id,
        frame_id=candidate.frame_id,
        observation_digest=candidate.observation_digest,
        action_digest=candidate.action_digest,
        consequence=candidate.consequence,
        approved_request_identity=request.request.request_id,
        issued_at=NOW,
        expires_at=candidate.expires_at,
    )


def test_non_observe_browser_action_requires_exact_candidate_then_reuses_lease():
    runtime = KernelToolRuntime((_registration(_binding()),), clock=lambda: NOW)
    call = ToolCall("call-1", "browser_act", {})

    first = runtime.prepare(call, _context())
    assert isinstance(first, ApprovalRequired)
    candidate = first.request.browser_action_candidate
    assert candidate is not None
    assert candidate.goal_id == "goal-1"
    assert candidate.goal_revision == 2
    assert candidate.session_ref == SESSION
    assert candidate.action_digest == "3" * 64
    assert candidate.consequence == "disclose"

    prepared = runtime.prepare(call, _context(leases=(_lease(first),)))
    assert isinstance(prepared, ExecutionIntent)
    assert prepared.browser_lease is not None
    assert prepared.browser_lease.candidate_digest == candidate.candidate_digest


def test_stale_or_consumed_browser_lease_cannot_authorize_changed_action():
    first_runtime = KernelToolRuntime((_registration(_binding()),), clock=lambda: NOW)
    call = ToolCall("call-1", "browser_act", {})
    first = first_runtime.prepare(call, _context())
    assert isinstance(first, ApprovalRequired)
    lease = _lease(first)

    changed = KernelToolRuntime(
        (_registration(_binding(action_digest="4" * 64)),), clock=lambda: NOW
    ).prepare(call, _context(leases=(lease,)))
    assert isinstance(changed, ApprovalRequired)
    assert changed.request.browser_action_candidate is not None
    assert changed.request.browser_action_candidate.action_digest == "4" * 64

    consumed = first_runtime.prepare(
        call, _context(leases=(replace(lease, uses_consumed=1),))
    )
    assert isinstance(consumed, ApprovalRequired)


def test_browser_lease_use_is_consumed_in_executing_checkpoint():
    from agent.runtime.contracts import ActiveRun, ContinuationPhase
    from agent.runtime.state import mark_executing
    from tests.kernel.fakes import conversation_with_active_goal

    runtime = KernelToolRuntime((_registration(_binding()),), clock=lambda: NOW)
    call = ToolCall("call-1", "browser_act", {})
    approval = runtime.prepare(call, _context())
    assert isinstance(approval, ApprovalRequired)
    lease = _lease(approval)
    state = conversation_with_active_goal()
    state = replace(
        state,
        browser_leases=(lease,),
        active_run=ActiveRun(
            run_id="run-1",
            phase=ContinuationPhase.TOOL,
            tool_calls=(call,),
        ),
    )

    executing = mark_executing(
        state,
        tool_call_id="call-1",
        intent_digest="intent-1",
        idempotency_key="key-1",
        side_effect=SideEffectClass.EXTERNAL,
        egress=EgressClass.GOVERNED_NETWORK,
        operation="browser_act",
        request_identity="key-1",
        execution_authority=ExecutionAuthorityClass.BROWSER_SESSION,
        browser_lease_id=lease.lease_id,
    )

    assert executing.browser_leases[0].uses_consumed == 1
