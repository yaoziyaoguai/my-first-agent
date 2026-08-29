from __future__ import annotations

from dataclasses import replace

from agent.automation.claim_verifier import AutomationClaimVerifier
from agent.browser.contracts import BrowserMode
from agent.runtime.contracts import (
    ApprovalPolicy,
    ApprovalRequired,
    BackgroundActionAuthorityV1,
    EgressClass,
    ExecutionAuthorityClass,
    ExecutionIntent,
    OutputPolicy,
    PolicyDecision,
    SideEffectClass,
    ToolCall,
    ToolPrepareContext,
    ToolResult,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
from agent.sandbox.contracts import (
    SandboxDraftOutcome,
    SandboxEnforcementFactsV1,
    SandboxExecutionDraftV1,
    SandboxMode,
    SandboxNetworkMode,
)

from .test_claim_verifier import _execution_authority, _running_claim


class _RequireApprovalPolicy:
    identity = "background-test-policy-v1"

    def evaluate(self, spec, arguments, binding):  # noqa: ANN001, ANN201
        del spec, arguments, binding
        return PolicyDecision.REQUIRE_APPROVAL


class _BrokenVerifier:
    def verify(self, check):  # noqa: ANN001, ANN201
        del check
        raise RuntimeError("store unavailable")


def _context(**overrides) -> ToolPrepareContext:  # noqa: ANN003
    values = {
        "conversation_id": "conversation:background",
        "run_id": "run:background",
        "state_revision": 7,
        "goal_id": "goal:background",
        "goal_revision": 1,
        "workspace_identity_digest": "a" * 64,
        "background_execution_authority": _execution_authority(),
        "background_tool_calls_used": 0,
        "background_sandbox_commands_used": 0,
        "background_browser_actions_used": 0,
    }
    values.update(overrides)
    return ToolPrepareContext(**values)


def _sandbox_registration(
    calls: list[str],
    *,
    outcome: SandboxDraftOutcome = SandboxDraftOutcome.SPAWN_FAILED,
) -> RegisteredTool:
    spec = ToolSpec(
        name="sandbox_exec",
        version="background-test-v1",
        description="execute exact confined command",
        input_schema={
            "type": "object",
            "properties": {"executable": {"type": "string"}},
            "required": ["executable"],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.EXTERNAL,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={"kind": "sandbox_exec", "shell": False, "background": False},
        output_limit_chars=4_096,
        egress=EgressClass.NONE,
        execution_authority=ExecutionAuthorityClass.ISOLATED_SANDBOX,
    )

    def execute(_intent):  # noqa: ANN001, ANN202
        calls.append("sandbox")
        return SandboxExecutionDraftV1(
            outcome=outcome,
            exit_code=0 if outcome is SandboxDraftOutcome.EXITED else None,
            signal=None,
            duration_seconds=0,
            stdout_bytes=0,
            stderr_bytes=0,
            stdout_digest="1" * 64,
            stderr_digest="2" * 64,
            stdout_projection="",
            stderr_projection="",
            stdout_truncated=False,
            stderr_truncated=False,
            original_command_fingerprint="3" * 64,
            enforcement=SandboxEnforcementFactsV1(
                backend="seatbelt",
                enforcement="confined",
                mode=SandboxMode.WORKSPACE_WRITE,
                network=SandboxNetworkMode.OFF,
                policy_digest="6" * 64,
                profile_digest="4" * 64,
            ),
        )

    return RegisteredTool(
        spec=spec,
        func=execute,
        policy=_RequireApprovalPolicy(),
        prepare_binding=lambda _arguments: {
            "command_fingerprint": "3" * 64,
            "policy_digest": "6" * 64,
            "sandbox_mode": "workspace-write",
            "sandbox_network": "off",
            "effect_preview": "bounded",
            "trust_notice_id": "native_sandbox_v1",
            "trust_notice_digest": "4" * 64,
        },
    )


def _browser_registration(*, consequence: str) -> RegisteredTool:
    return RegisteredTool(
        spec=ToolSpec(
            name="browser_open" if consequence == "observe" else "browser_act",
            version="background-test-v1",
            description="bounded browser action",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            risk=ToolRisk.HIGH,
            side_effect=SideEffectClass.EXTERNAL,
            output_policy=OutputPolicy.BOUNDED_TEXT,
            approval_policy=ApprovalPolicy.ALWAYS,
            safety_policy={
                "kind": "browser_open" if consequence == "observe" else "browser_action"
            },
            output_limit_chars=1_000,
            egress=EgressClass.GOVERNED_NETWORK,
            execution_authority=ExecutionAuthorityClass.BROWSER_SESSION,
        ),
        func=lambda _intent: "ok",
        policy=_RequireApprovalPolicy(),
        prepare_binding=lambda _arguments: {
            "mode": BrowserMode.PUBLIC_READ_EPHEMERAL.value,
            "profile_ref": None,
            "profile_revision": None,
            "allowed_origins": [],
            "action_budget": 3,
            "browser_identity_digest": "5" * 64,
            "session_expiry_monotonic": 1.0,
            "consequence": consequence,
            "effect_preview": "bounded",
            "session_ref": "browser-session:test",
            "page_id": "page:test",
            "frame_id": "frame:test",
            "observation_digest": "8" * 64,
            "action_digest": "9" * 64,
            "issued_at": "2026-08-28T00:00:00+00:00",
            "expires_at": "2026-08-28T01:00:00+00:00",
        },
    )


def test_exact_confined_sandbox_grant_bypasses_no_ordinary_lease() -> None:
    repository, _ = _running_claim()
    calls: list[str] = []
    runtime = KernelToolRuntime(
        (_sandbox_registration(calls),),
        background_claim_verifier=AutomationClaimVerifier(repository),
        clock=lambda: "2026-08-28T00:01:00Z",
    )

    intent = runtime.prepare(
        ToolCall("call-1", "sandbox_exec", {"executable": "/usr/bin/true"}),
        _context(),
    )

    assert isinstance(intent, ExecutionIntent)
    assert intent.sandbox_lease is None
    assert isinstance(intent.background_action_authority, BackgroundActionAuthorityV1)
    assert intent.background_action_authority.action_class == "sandbox_confined"
    result = runtime.invoke(intent)
    assert result.executed is False
    assert calls == ["sandbox"]


def test_successful_background_sandbox_uses_distinct_receipt_without_fake_lease() -> None:
    repository, _ = _running_claim()
    calls: list[str] = []
    runtime = KernelToolRuntime(
        (_sandbox_registration(calls, outcome=SandboxDraftOutcome.EXITED),),
        background_claim_verifier=AutomationClaimVerifier(repository),
        clock=lambda: "2026-08-28T00:01:00Z",
    )
    intent = runtime.prepare(
        ToolCall("call-success", "sandbox_exec", {"executable": "/usr/bin/true"}),
        _context(),
    )
    assert isinstance(intent, ExecutionIntent)

    result = runtime.invoke(intent)

    assert result.executed is True and result.is_error is False
    assert result.metadata["sandbox_receipt_kind"] == "background_sandbox_v1"
    receipt = result.metadata["sandbox_receipt"]
    assert "lease_id" not in receipt
    assert receipt["background_action_authority_digest"] == (
        intent.background_action_authority.authority_digest
    )


def test_public_browser_open_is_admitted_but_disclose_remains_approval() -> None:
    repository, _ = _running_claim()
    verifier = AutomationClaimVerifier(repository)
    open_runtime = KernelToolRuntime(
        (_browser_registration(consequence="observe"),),
        background_claim_verifier=verifier,
        clock=lambda: "2026-08-28T00:01:00Z",
    )
    disclose_runtime = KernelToolRuntime(
        (_browser_registration(consequence="disclose"),),
        background_claim_verifier=verifier,
        clock=lambda: "2026-08-28T00:01:00Z",
    )

    admitted = open_runtime.prepare(ToolCall("call-open", "browser_open", {}), _context())
    blocked = disclose_runtime.prepare(ToolCall("call-act", "browser_act", {}), _context())

    assert isinstance(admitted, ExecutionIntent)
    assert admitted.background_action_authority.action_class == "browser_public_observe"
    assert isinstance(blocked, ApprovalRequired)
    assert blocked.request.browser_action_candidate is not None


def test_policy_workspace_and_budget_drift_do_not_gain_background_authority() -> None:
    repository, _ = _running_claim()
    verifier = AutomationClaimVerifier(repository)
    call = ToolCall("call-1", "sandbox_exec", {"executable": "/usr/bin/true"})
    for binding_change, context_change in (
        ({"sandbox_network": "full"}, {}),
        ({"sandbox_mode": "danger-full-access"}, {}),
        ({"policy_digest": "f" * 64}, {}),
        ({}, {"workspace_identity_digest": "x" * 64}),
        ({}, {"background_sandbox_commands_used": 2}),
    ):
        calls: list[str] = []
        registration = _sandbox_registration(calls)
        original = registration.prepare_binding
        registration = replace(
            registration,
            prepare_binding=lambda arguments, original=original, change=binding_change: {
                **original(arguments),
                **change,
            },
        )
        runtime = KernelToolRuntime(
            (registration,),
            background_claim_verifier=verifier,
            clock=lambda: "2026-08-28T00:01:00Z",
        )
        outcome = runtime.prepare(call, _context(**context_change))
        if context_change.get("background_sandbox_commands_used") == 2:
            assert isinstance(outcome, ToolResult)
            assert outcome.metadata["code"] == (
                "background_sandbox_confined_budget_exhausted"
            )
        else:
            assert isinstance(outcome, ApprovalRequired)
        assert calls == []


def test_ephemeral_environment_and_browser_policy_drift_require_approval() -> None:
    repository, _ = _running_claim()
    verifier = AutomationClaimVerifier(repository)
    base = _execution_authority()
    sandbox_runtime = KernelToolRuntime(
        (_sandbox_registration([]),),
        background_claim_verifier=verifier,
        clock=lambda: "2026-08-28T00:01:00Z",
    )
    browser_runtime = KernelToolRuntime(
        (_browser_registration(consequence="observe"),),
        background_claim_verifier=verifier,
        clock=lambda: "2026-08-28T00:01:00Z",
    )

    sandbox = sandbox_runtime.prepare(
        ToolCall("call-sandbox", "sandbox_exec", {"executable": "/usr/bin/true"}),
        _context(
            background_execution_authority=replace(
                base,
                background_environment_policy_digest="f" * 64,
            )
        ),
    )
    browser = browser_runtime.prepare(
        ToolCall("call-browser", "browser_open", {}),
        _context(
            background_execution_authority=replace(
                base,
                browser_origin_policy_digest="e" * 64,
            )
        ),
    )

    assert isinstance(sandbox, ApprovalRequired)
    assert isinstance(browser, ApprovalRequired)


def test_missing_or_failed_claim_verifier_fails_closed_before_callable() -> None:
    call = ToolCall("call-1", "sandbox_exec", {"executable": "/usr/bin/true"})
    for verifier in (None, _BrokenVerifier()):
        calls: list[str] = []
        runtime = KernelToolRuntime(
            (_sandbox_registration(calls),),
            background_claim_verifier=verifier,
            clock=lambda: "2026-08-28T00:01:00Z",
        )

        result = runtime.prepare(call, _context())

        assert isinstance(result, ToolResult)
        assert result.metadata["code"] == "background_claim_unavailable"
        assert calls == []
