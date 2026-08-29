"""KernelToolRuntime 的 native sandbox authority 与 receipt gate。"""

from __future__ import annotations

import pytest

from agent.runtime.contracts import (
    ApprovalPolicy,
    EgressClass,
    ExecutionAuthorityClass,
    OutputPolicy,
    SandboxAuthorityLeaseV1,
    SideEffectClass,
    ToolCall,
    ToolPrepareContext,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.tools import (
    ApprovalRequired,
    IntentConflictError,
    KernelToolRuntime,
    RegisteredTool,
)
from agent.sandbox.contracts import (
    SandboxDraftOutcome,
    SandboxEnforcementFactsV1,
    SandboxExecutionDraftV1,
    SandboxMode,
    SandboxNetworkMode,
)

HEX_A = "a" * 64
HEX_B = "b" * 64
NOW = "2026-08-27T08:00:00+00:00"


def _spec() -> ToolSpec:
    return ToolSpec(
        name="sandbox_exec",
        version="native-sandbox-v1",
        description="run one exact native sandbox command",
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
        safety_policy={"kind": "sandbox_exec"},
        output_limit_chars=4096,
        egress=EgressClass.NONE,
        execution_authority=ExecutionAuthorityClass.ISOLATED_SANDBOX,
    )


def _binding(**overrides) -> dict:
    values = {
        "command_fingerprint": HEX_A,
        "policy_digest": HEX_B,
        "sandbox_mode": "workspace-write",
        "sandbox_network": "off",
        "effect_preview": "/usr/bin/true (cwd=., workspace-write, network=off)",
        "trust_notice_id": "native_sandbox_v1",
        "trust_notice_digest": HEX_A,
    }
    values.update(overrides)
    return values


def _draft(**overrides) -> SandboxExecutionDraftV1:
    values = {
        "outcome": SandboxDraftOutcome.EXITED,
        "exit_code": 0,
        "signal": None,
        "duration_seconds": 0.1,
        "stdout_bytes": 2,
        "stderr_bytes": 0,
        "stdout_digest": HEX_A,
        "stderr_digest": HEX_B,
        "stdout_projection": "ok",
        "stderr_projection": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "original_command_fingerprint": HEX_A,
        "enforcement": SandboxEnforcementFactsV1(
            backend="seatbelt",
            enforcement="confined",
            mode=SandboxMode.WORKSPACE_WRITE,
            network=SandboxNetworkMode.OFF,
            policy_digest=HEX_B,
            profile_digest=HEX_A,
        ),
    }
    values.update(overrides)
    return SandboxExecutionDraftV1(**values)


def _runtime(*, binding=None, result=None, clock=NOW) -> KernelToolRuntime:
    prepared_binding = _binding() if binding is None else binding
    draft = _draft() if result is None else result
    return KernelToolRuntime(
        (
            RegisteredTool(
                spec=_spec(),
                func=lambda _intent: draft,
                prepare_binding=lambda _arguments: dict(prepared_binding),
            ),
        ),
        clock=lambda: clock,
    )


def _context(**overrides) -> ToolPrepareContext:
    values = {
        "conversation_id": "conversation-1",
        "run_id": "run-1",
        "state_revision": 7,
        "goal_id": "goal-1",
        "goal_revision": 1,
        "workspace_identity_digest": "workspace-digest-1",
    }
    values.update(overrides)
    return ToolPrepareContext(**values)


def _call() -> ToolCall:
    return ToolCall("call-1", "sandbox_exec", {"executable": "/usr/bin/true"})


def _lease(candidate, **overrides) -> SandboxAuthorityLeaseV1:  # noqa: ANN001
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
        "issued_at": "2026-08-27T07:59:00+00:00",
        "expires_at": "2026-08-27T10:00:00+00:00",
    }
    values.update(overrides)
    return SandboxAuthorityLeaseV1.create(**values)


def test_prepare_builds_candidate_only_from_trusted_binding() -> None:
    runtime = _runtime()
    outcome = runtime.prepare(_call(), _context())
    assert isinstance(outcome, ApprovalRequired)
    candidate = outcome.request.sandbox_authority_candidate
    assert candidate.original_command_fingerprint == HEX_A
    assert candidate.policy_digest == HEX_B
    assert candidate.mode == "workspace-write"
    assert candidate.network == "off"
    assert not hasattr(candidate, "image_digest")


def test_exact_active_lease_allows_once_and_every_binding_drift_reasks() -> None:
    runtime = _runtime()
    candidate = runtime.prepare(_call(), _context()).request.sandbox_authority_candidate
    exact = _lease(candidate)
    prepared = runtime.prepare(_call(), _context(sandbox_leases=(exact,)))
    assert not isinstance(prepared, ApprovalRequired)
    assert prepared.sandbox_lease == exact
    for change in (
        {"original_command_fingerprint": HEX_B},
        {"policy_digest": HEX_A},
        {"mode": "read-only"},
        {"network": "full"},
        {"uses_consumed": 1},
    ):
        lease = (
            exact.with_use_consumed(1)
            if change == {"uses_consumed": 1}
            else _lease(candidate, **change)
        )
        outcome = runtime.prepare(_call(), _context(sandbox_leases=(lease,)))
        assert isinstance(outcome, ApprovalRequired)


def test_stale_revision_expired_and_malformed_clock_fail_closed_to_approval() -> None:
    runtime = _runtime()
    candidate = runtime.prepare(_call(), _context()).request.sandbox_authority_candidate
    for lease in (
        _lease(candidate, goal_revision=2),
        _lease(candidate, expires_at=NOW),
    ):
        assert isinstance(
            runtime.prepare(_call(), _context(sandbox_leases=(lease,))),
            ApprovalRequired,
        )
    malformed_clock = _runtime(clock="not-a-time")
    assert isinstance(
        malformed_clock.prepare(
            _call(), _context(sandbox_leases=(_lease(candidate),)),
        ),
        ApprovalRequired,
    )


def test_invoke_accepts_only_matching_sandbox_draft_and_mints_closed_receipt() -> None:
    runtime = _runtime()
    candidate = runtime.prepare(_call(), _context()).request.sandbox_authority_candidate
    intent = runtime.prepare(_call(), _context(sandbox_leases=(_lease(candidate),)))
    result = runtime.invoke(intent)
    assert result.is_error is False and result.executed is True
    assert result.metadata["sandbox_receipt_kind"] == "native_sandbox_v1"
    receipt = result.metadata["sandbox_receipt"]
    assert receipt["original_command_fingerprint"] == HEX_A
    assert receipt["policy_digest"] == HEX_B
    assert receipt["backend"] == "seatbelt"
    assert "image_digest" not in receipt


def test_spawn_failed_mints_no_receipt() -> None:
    runtime = _runtime(result=_draft(outcome=SandboxDraftOutcome.SPAWN_FAILED))
    candidate = runtime.prepare(_call(), _context()).request.sandbox_authority_candidate
    intent = runtime.prepare(_call(), _context(sandbox_leases=(_lease(candidate),)))
    result = runtime.invoke(intent)
    assert result.is_error is True and result.executed is False
    assert "sandbox_receipt" not in result.metadata


def test_sandbox_callable_cannot_return_plain_success_without_a_draft() -> None:
    runtime = _runtime(result="looks successful")
    candidate = runtime.prepare(_call(), _context()).request.sandbox_authority_candidate
    intent = runtime.prepare(_call(), _context(sandbox_leases=(_lease(candidate),)))
    with pytest.raises(
        IntentConflictError,
        match="verifiable execution draft",
    ):
        runtime.invoke(intent)


@pytest.mark.parametrize(
    "draft",
    [
        _draft(original_command_fingerprint=HEX_B),
        _draft(
            enforcement=SandboxEnforcementFactsV1(
                backend="seatbelt",
                enforcement="confined",
                mode=SandboxMode.READ_ONLY,
                network=SandboxNetworkMode.OFF,
                policy_digest=HEX_B,
                profile_digest=HEX_A,
            ),
        ),
        _draft(
            enforcement=SandboxEnforcementFactsV1(
                backend="none",
                enforcement="unconfined",
                mode=SandboxMode.DANGER_FULL_ACCESS,
                network=SandboxNetworkMode.OFF,
                policy_digest=HEX_B,
            ),
        ),
    ],
)
def test_forged_command_policy_or_enforcement_facts_are_rejected(draft) -> None:  # noqa: ANN001
    runtime = _runtime(result=draft)
    candidate = runtime.prepare(_call(), _context()).request.sandbox_authority_candidate
    intent = runtime.prepare(_call(), _context(sandbox_leases=(_lease(candidate),)))
    with pytest.raises(IntentConflictError):
        runtime.invoke(intent)


def test_danger_bypass_requires_exact_lease_and_records_unconfined_facts() -> None:
    binding = _binding(sandbox_mode="danger-full-access")
    draft = _draft(
        enforcement=SandboxEnforcementFactsV1(
            backend="none",
            enforcement="unconfined",
            mode=SandboxMode.DANGER_FULL_ACCESS,
            network=SandboxNetworkMode.OFF,
            policy_digest=HEX_B,
        ),
    )
    runtime = _runtime(binding=binding, result=draft)
    first = runtime.prepare(_call(), _context())
    assert isinstance(first, ApprovalRequired)
    candidate = first.request.sandbox_authority_candidate
    intent = runtime.prepare(_call(), _context(sandbox_leases=(_lease(candidate),)))
    result = runtime.invoke(intent)
    assert result.metadata["sandbox_receipt"]["backend"] == "none"
    assert result.metadata["sandbox_receipt"]["enforcement"] == "unconfined"


def test_native_registration_has_one_exact_closed_tool_schema() -> None:
    import agent.sandbox.tools as sandbox_tools

    spec = sandbox_tools.sandbox_exec_tool_spec()
    assert spec.name == "sandbox_exec"
    assert spec.input_schema == {
        "type": "object",
        "properties": {
            "executable": {"type": "string"},
            "argv": {"type": "array", "items": {"type": "string"}},
            "cwd": {"type": "string"},
            "profile": {
                "type": "string",
                "enum": ["short", "standard", "long"],
            },
            "mode": {
                "type": "string",
                "enum": ["read-only", "workspace-write", "danger-full-access"],
            },
            "network": {"type": "string", "enum": ["off", "full"]},
        },
        "required": ["executable"],
        "additionalProperties": False,
    }
    assert not hasattr(sandbox_tools, "build_sandbox_capture_registration")
    assert not hasattr(sandbox_tools, "build_sandbox_apply_registration")


def test_native_registration_binding_defaults_and_preview_are_exact(tmp_path) -> None:
    from agent.sandbox.tools import build_sandbox_exec_registration

    roots = {}
    for name in ("workspace", "temp", "state", "home"):
        roots[name] = tmp_path / name
        roots[name].mkdir()
    registration = build_sandbox_exec_registration(
        workspace=roots["workspace"],
        temp_root=roots["temp"],
        state_root=roots["state"],
        home=roots["home"],
        captured_path="/usr/bin:/bin",
        confiner=object(),
    )
    binding = registration.prepare_binding(
        {
            "executable": "/usr/bin/true",
            "argv": ["--version"],
            "cwd": ".",
            "profile": "short",
        }
    )
    assert binding["sandbox_mode"] == "workspace-write"
    assert binding["sandbox_network"] == "off"
    preview = binding["effect_preview"]
    for value in ("/usr/bin/true", "--version", "cwd=.", "short"):
        assert value in preview
    assert "workspace-write" in preview and "network=off" in preview
    assert binding["policy_digest"] not in preview
    assert "host shell" in preview
