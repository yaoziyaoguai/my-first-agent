"""KernelToolRuntime 的 native sandbox authority 与 receipt gate。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

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
    StructuredReadbackOutcome,
    StructuredSandboxProcessDraftV1,
)

HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
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


def _structured_draft(
    *,
    process: SandboxExecutionDraftV1 | None = None,
    readback_outcome: StructuredReadbackOutcome = StructuredReadbackOutcome.VALID,
    outer_digest: str = HEX_C,
) -> StructuredSandboxProcessDraftV1:
    result = (
        json.dumps(
            {
                "kind": "observation",
                "payload": {"summary": "private staged result"},
                "protocol": "first-agent-skill-result-v1",
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        if readback_outcome is StructuredReadbackOutcome.VALID
        else b""
    )
    return StructuredSandboxProcessDraftV1(
        process=process or _draft(),
        structured_invocation_digest=outer_digest,
        readback_outcome=readback_outcome,
        request_digest=HEX_A,
        input_digests=(("source", 3, HEX_B),),
        result_bytes=result,
        result_digest=hashlib.sha256(result).hexdigest(),
        artifact_bytes=None,
        artifact_digest=None,
    )


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


def test_structured_valid_readback_reuses_sandbox_receipt_and_exposes_no_artifact() -> None:
    outer_digest = HEX_C
    runtime = _runtime(
        binding=_binding(structured_invocation_digest=outer_digest),
        result=_structured_draft(outer_digest=outer_digest),
    )
    candidate = runtime.prepare(_call(), _context()).request.sandbox_authority_candidate
    intent = runtime.prepare(_call(), _context(sandbox_leases=(_lease(candidate),)))

    result = runtime.invoke(intent)

    assert result.executed is True and result.is_error is False
    assert result.content == (
        '{"kind":"observation","payload":{"summary":"private staged result"},'
        '"protocol":"first-agent-skill-result-v1"}'
    )
    assert result.metadata["sandbox_receipt_kind"] == "native_sandbox_v1"
    assert result.metadata["structured_invocation_digest"] == outer_digest
    assert result.metadata["structured_result_digest"] == hashlib.sha256(
        result.content.encode("utf-8")
    ).hexdigest()
    assert result.metadata["structured_artifact_digest"] is None
    assert result.metadata["structured_result_kind"] == "observation"
    assert "artifact_bytes" not in result.metadata


def test_structured_post_spawn_readback_error_is_executed_without_staged_bytes() -> None:
    outer_digest = HEX_C
    runtime = _runtime(
        binding=_binding(structured_invocation_digest=outer_digest),
        result=_structured_draft(
            outer_digest=outer_digest,
            readback_outcome=StructuredReadbackOutcome.RESULT_MALFORMED,
        ),
    )
    candidate = runtime.prepare(_call(), _context()).request.sandbox_authority_candidate
    intent = runtime.prepare(_call(), _context(sandbox_leases=(_lease(candidate),)))

    result = runtime.invoke(intent)

    assert result.executed is True and result.is_error is True
    assert result.metadata["code"] == "result_malformed"
    assert result.metadata["structured_invocation_digest"] == outer_digest
    assert "sandbox_receipt" in result.metadata
    assert "private staged result" not in result.content
    assert "private staged result" not in str(result.metadata)


def test_structured_spawn_failed_not_read_is_not_executed() -> None:
    outer_digest = HEX_C
    runtime = _runtime(
        binding=_binding(structured_invocation_digest=outer_digest),
        result=_structured_draft(
            process=_draft(outcome=SandboxDraftOutcome.SPAWN_FAILED),
            outer_digest=outer_digest,
            readback_outcome=StructuredReadbackOutcome.NOT_READ,
        ),
    )
    candidate = runtime.prepare(_call(), _context()).request.sandbox_authority_candidate
    intent = runtime.prepare(_call(), _context(sandbox_leases=(_lease(candidate),)))

    result = runtime.invoke(intent)

    assert result.executed is False and result.is_error is True
    assert result.metadata["code"] == "spawn_failed"
    assert result.metadata["structured_invocation_digest"] == outer_digest
    assert "sandbox_receipt" not in result.metadata


def test_structured_outer_digest_mismatch_is_rejected_before_receipt() -> None:
    runtime = _runtime(
        binding=_binding(structured_invocation_digest=HEX_C),
        result=_structured_draft(outer_digest=HEX_A),
    )
    candidate = runtime.prepare(_call(), _context()).request.sandbox_authority_candidate
    intent = runtime.prepare(_call(), _context(sandbox_leases=(_lease(candidate),)))

    with pytest.raises(IntentConflictError, match="structured invocation"):
        runtime.invoke(intent)


def test_structured_draft_bytes_must_match_the_bound_digest() -> None:
    outer_digest = HEX_C
    draft = _structured_draft(outer_digest=outer_digest)
    object.__setattr__(draft, "result_bytes", b"x" * len(draft.result_bytes))
    runtime = _runtime(
        binding=_binding(structured_invocation_digest=outer_digest), result=draft
    )
    candidate = runtime.prepare(_call(), _context()).request.sandbox_authority_candidate
    intent = runtime.prepare(_call(), _context(sandbox_leases=(_lease(candidate),)))

    with pytest.raises(IntentConflictError, match="structured result digest"):
        runtime.invoke(intent)


def test_structured_forgery_does_not_expose_staged_result_without_receipt() -> None:
    outer_digest = HEX_C
    draft = _structured_draft(outer_digest=outer_digest)
    runtime = _runtime(
        binding=_binding(structured_invocation_digest=outer_digest), result=draft
    )
    candidate = runtime.prepare(_call(), _context()).request.sandbox_authority_candidate
    intent = runtime.prepare(_call(), _context(sandbox_leases=(_lease(candidate),)))
    forged_spec = replace(
        _spec(), execution_authority=ExecutionAuthorityClass.IN_PROCESS
    )

    result = runtime._structured_sandbox_outcome(intent, forged_spec, draft)

    assert result.metadata["code"] == "sandbox_draft_forgery"
    assert "sandbox_receipt" not in result.metadata
    assert result.content != draft.result_bytes.decode("utf-8")
    assert "private staged result" not in result.content


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


def test_danger_off_network_only_confined_draft_mints_receipt_via_public_path() -> None:
    # 显式矩阵：danger+off 必须以 seatbelt/confined + 有效 profile digest 执行
    # （network-only profile），经唯一 public prepare→lease→invoke 路径铸 receipt。
    binding = _binding(sandbox_mode="danger-full-access")
    draft = _draft(
        enforcement=SandboxEnforcementFactsV1(
            backend="seatbelt",
            enforcement="confined",
            mode=SandboxMode.DANGER_FULL_ACCESS,
            network=SandboxNetworkMode.OFF,
            policy_digest=HEX_B,
            profile_digest=HEX_A,
        ),
    )
    runtime = _runtime(binding=binding, result=draft)
    first = runtime.prepare(_call(), _context())
    assert isinstance(first, ApprovalRequired)
    candidate = first.request.sandbox_authority_candidate
    intent = runtime.prepare(_call(), _context(sandbox_leases=(_lease(candidate),)))
    result = runtime.invoke(intent)
    assert result.executed is True and result.is_error is False
    assert result.metadata["sandbox_receipt_kind"] == "native_sandbox_v1"
    receipt = result.metadata["sandbox_receipt"]
    assert receipt["mode"] == "danger-full-access"
    assert receipt["network"] == "off"
    assert receipt["backend"] == "seatbelt"
    assert receipt["enforcement"] == "confined"
    assert receipt["profile_digest"] == HEX_A


@pytest.mark.parametrize(
    "facts",
    [
        # danger+off 伪造 none/unconfined：必须拒绝（只能 seatbelt/confined）。
        SandboxEnforcementFactsV1(
            backend="none",
            enforcement="unconfined",
            mode=SandboxMode.DANGER_FULL_ACCESS,
            network=SandboxNetworkMode.OFF,
            policy_digest=HEX_B,
        ),
        # danger+full 伪造 seatbelt/confined：唯一 bypass 组合的矛盾面。
        SandboxEnforcementFactsV1(
            backend="seatbelt",
            enforcement="confined",
            mode=SandboxMode.DANGER_FULL_ACCESS,
            network=SandboxNetworkMode.FULL,
            policy_digest=HEX_B,
            profile_digest=HEX_A,
        ),
        # 非 danger/full 的任何组合都不允许 none/unconfined。
        SandboxEnforcementFactsV1(
            backend="none",
            enforcement="unconfined",
            mode=SandboxMode.WORKSPACE_WRITE,
            network=SandboxNetworkMode.FULL,
            policy_digest=HEX_B,
        ),
        SandboxEnforcementFactsV1(
            backend="none",
            enforcement="unconfined",
            mode=SandboxMode.READ_ONLY,
            network=SandboxNetworkMode.OFF,
            policy_digest=HEX_B,
        ),
    ],
)
def test_contradictory_enforcement_matrix_is_rejected(facts) -> None:  # noqa: ANN001
    binding = _binding(
        sandbox_mode=facts.mode.value, sandbox_network=facts.network.value,
    )
    runtime = _runtime(binding=binding, result=_draft(enforcement=facts))
    candidate = runtime.prepare(_call(), _context()).request.sandbox_authority_candidate
    intent = runtime.prepare(_call(), _context(sandbox_leases=(_lease(candidate),)))
    with pytest.raises(IntentConflictError):
        runtime.invoke(intent)


def test_danger_full_bypass_requires_exact_lease_and_records_unconfined_facts() -> None:
    # 唯一 unconfined bypass 是 danger-full-access + network=full。
    binding = _binding(sandbox_mode="danger-full-access", sandbox_network="full")
    draft = _draft(
        enforcement=SandboxEnforcementFactsV1(
            backend="none",
            enforcement="unconfined",
            mode=SandboxMode.DANGER_FULL_ACCESS,
            network=SandboxNetworkMode.FULL,
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
    assert result.metadata["sandbox_receipt"]["network"] == "full"


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


def test_native_trust_notice_distinguishes_danger_off_from_danger_full(tmp_path) -> None:
    import agent.sandbox.tools as sandbox_tools

    notice = sandbox_tools.SANDBOX_TRUST_NOTICE
    # danger/off：只有网络限制的 network-only profile，无 filesystem 隔离。
    assert "danger-full-access with network off" in notice
    assert "network-only Seatbelt profile" in notice
    assert "no filesystem isolation" in notice
    # danger/full：才是 unconfined bypass。
    assert "danger-full-access with network full" in notice
    assert "unconfined exact-command bypass" in notice
    # confined mode 可显式选择 network=full；提示不能把它误报成网络拒绝。
    assert "when network is off" in notice
    assert "filesystem and network denial" not in notice
    # network off 的边界同样准确，不宣称整机断网。
    assert "does not disconnect the machine" in notice
    assert "already-open file descriptors" in notice
    assert "system services" in notice
    # digest 从当前文本派生：文本变更即触发新 digest。
    roots = {}
    for name in ("workspace", "temp", "state", "home"):
        roots[name] = tmp_path / name
        roots[name].mkdir()
    registration = sandbox_tools.build_sandbox_exec_registration(
        workspace=roots["workspace"],
        temp_root=roots["temp"],
        state_root=roots["state"],
        home=roots["home"],
        captured_path="/usr/bin:/bin",
        confiner=object(),
    )
    binding = registration.prepare_binding({"executable": "/usr/bin/true"})
    assert binding["trust_notice_digest"] == hashlib.sha256(
        notice.encode("utf-8"),
    ).hexdigest()


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
    for value in ('"/usr/bin/true"', '"--version"', 'cwd="."', "short"):
        assert value in preview
    assert "workspace-write" in preview and "network=off" in preview
    assert binding["policy_digest"] not in preview
    assert "host shell" in preview


def test_native_preview_distinguishes_argv_token_boundaries(tmp_path) -> None:
    """argv 逐 token 无损渲染：空格 join 的边界碰撞不可再伪造。"""

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

    def preview(argv: list[str]) -> str:
        return registration.prepare_binding(
            {"executable": "/usr/bin/true", "argv": argv, "cwd": ".", "profile": "short"}
        )["effect_preview"]

    spaced_pair = preview(["a b", "c"])
    rebased_pair = preview(["a", "b c"])
    assert spaced_pair != rebased_pair
    assert '"a b" "c"' in spaced_pair
    assert '"a" "b c"' in rebased_pair


def test_native_preview_distinguishes_quoted_executable_from_plain_argv(tmp_path) -> None:
    """executable 与 argv 边界碰撞：文件名含空格/引号的 exact command 不得与
    普通 executable + 对应 argv 的 preview 相同。"""

    from agent.sandbox.tools import build_sandbox_exec_registration

    roots = {}
    for name in ("workspace", "temp", "state", "home"):
        roots[name] = tmp_path / name
        roots[name].mkdir()
    workspace = roots["workspace"]
    for name in ('tool "x"', "tool"):
        executable_file = workspace / name
        executable_file.write_bytes(b"#!/bin/sh\nexit 0\n")
        executable_file.chmod(0o755)
    registration = build_sandbox_exec_registration(
        workspace=workspace,
        temp_root=roots["temp"],
        state_root=roots["state"],
        home=roots["home"],
        captured_path="/usr/bin:/bin",
        confiner=object(),
    )

    spaced_binding = registration.prepare_binding({"executable": './tool "x"'})
    plain_binding = registration.prepare_binding(
        {"executable": "./tool", "argv": ["x"]}
    )

    # 两者是 command_fingerprint 不同的真实 exact commands。
    assert spaced_binding["command_fingerprint"] != plain_binding["command_fingerprint"]
    spaced_preview = spaced_binding["effect_preview"]
    plain_preview = plain_binding["effect_preview"]
    assert spaced_preview != plain_preview
    # executable 有清晰 JSON quoting，argv 边界不受 executable 内容影响。
    assert '"./tool \\"x\\""' in spaced_preview
    assert '"x"' in plain_preview


def test_native_preview_quotes_cwd_against_metadata_forgery(tmp_path) -> None:
    """cwd 含伪造 mode/network 文本时必须 JSON quoting，真实披露段唯一清晰。"""

    from agent.sandbox.tools import build_sandbox_exec_registration

    roots = {}
    for name in ("workspace", "temp", "state", "home"):
        roots[name] = tmp_path / name
        roots[name].mkdir()
    forged_cwd = "x, mode=danger-full-access, network=full"
    (roots["workspace"] / forged_cwd).mkdir()
    registration = build_sandbox_exec_registration(
        workspace=roots["workspace"],
        temp_root=roots["temp"],
        state_root=roots["state"],
        home=roots["home"],
        captured_path="/usr/bin:/bin",
        confiner=object(),
    )

    preview = registration.prepare_binding(
        {"executable": "/usr/bin/true", "cwd": forged_cwd, "profile": "short"}
    )["effect_preview"]

    # cwd 整体是一个 JSON 字符串；真实的 mode/network 披露段紧随其后且未被伪造。
    assert (
        'cwd="x, mode=danger-full-access, network=full", profile=short, '
        "mode=workspace-write, network=off" in preview
    )
    assert "mode=danger-full-access, network=full)" not in preview


def test_native_preview_escapes_control_characters_in_executable_and_cwd(tmp_path) -> None:
    """executable/cwd 换行必须转义：durable preview 原串不得含裸控制字符。"""

    import agent.sandbox.tools as sandbox_tools
    from agent.process.contracts import ProcessCommandV1, ResourceProfile

    roots = {}
    for name in ("workspace", "temp_root", "state_root", "home"):
        roots[name] = tmp_path / name
        roots[name].mkdir()
    newline_executable = roots["workspace"] / "weird\ntool"
    newline_executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    newline_executable.chmod(0o755)
    registration = sandbox_tools.build_sandbox_exec_registration(
        workspace=roots["workspace"],
        temp_root=roots["temp_root"],
        state_root=roots["state_root"],
        home=roots["home"],
        captured_path="/usr/bin:/bin",
        confiner=object(),
    )

    # executable 换行走完整 public 路径：文件名含换行是真实可 admitted 的输入。
    executable_preview = registration.prepare_binding(
        {"executable": "./weird\ntool"}
    )["effect_preview"]
    assert "\n" not in executable_preview
    assert '"./weird\\ntool"' in executable_preview

    # public 路径的 WorkspaceBoundary.validate_relative 拒绝含换行的 cwd（必须全
    # printable），因此用最靠近 public boundary 的真实 ProcessCommandV1 + 生产
    # _closed_policy 直接驱动 _render_preview，覆盖该渲染面在边界内最大输入。
    command = ProcessCommandV1(
        executable_token="/usr/bin/true",
        argv=(),
        cwd="sub\nforge",
        profile=ResourceProfile.SHORT,
    )
    policy = sandbox_tools._closed_policy({}, roots=roots, private_roots=())
    cwd_preview = sandbox_tools._render_preview(command, policy)
    assert "\n" not in cwd_preview
    assert 'cwd="sub\\nforge"' in cwd_preview


def test_native_preview_escapes_control_characters_and_unicode(tmp_path) -> None:
    """换行/引号/Unicode token 逐字呈现，不可伪造披露行或注入控制字符。"""

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

    preview = registration.prepare_binding(
        {
            "executable": "/usr/bin/true",
            "argv": ["line\nbreak", 'quote"s', "π"],
            "cwd": ".",
            "profile": "short",
        }
    )["effect_preview"]

    assert "\n" not in preview
    assert '"line\\nbreak"' in preview
    assert '"quote\\"s"' in preview
    # 非 ASCII 以 \\uXXXX 转义呈现，保持 preview 为 ASCII-safe。
    assert "π" not in preview
    assert "\\u03c0" in preview
