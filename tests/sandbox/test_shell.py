"""governed ``shell_exec`` Slice 1：registration 合同与转译/防漂移单元测试。

全部使用 fake confiner/runner——不跑真实外网，不做 composition 接线。
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from agent.process.contracts import ProcessDraftOutcome
from agent.process.preparation import prepare_process
from agent.runtime.contracts import (
    ApprovalPolicy,
    EgressClass,
    ExecutionAuthorityClass,
    KnownNotExecuted,
    OutputPolicy,
    SideEffectClass,
    ToolRisk,
)
from agent.sandbox.contracts import SandboxExecutionDraftV1
from agent.sandbox.shell import (
    SHELL_PATH,
    SHELL_TRUST_NOTICE,
    SHELL_TRUST_NOTICE_ID,
    build_shell_exec_registration,
    shell_exec_tool_spec,
)

CAPTURED_PATH = "/usr/bin:/bin"
EXACT_COMMAND = "echo start && cat notes.txt | grep ok > out.txt $(pwd); rm -rf x || true"


class FakeConfiner:
    """正常 shell fake：所有 mode 都返回 seatbelt/confined + 真实 profile 字节。"""

    def __init__(self) -> None:
        self.commands: list = []
        self.policies: list = []

    def confine(self, command, policy, environment):  # noqa: ANN001
        from agent.sandbox.contracts import (
            ConfinedInvocationV1,
            SandboxEnforcementFactsV1,
        )
        from agent.sandbox.policy import compile_seatbelt_profile

        self.commands.append(command)
        self.policies.append(policy)
        profile = compile_seatbelt_profile(policy)
        resolved = command.executable_identity.resolved_path
        return ConfinedInvocationV1(
            wrapped_executable="/usr/bin/sandbox-exec",
            wrapped_argv=(
                "/usr/bin/sandbox-exec", "-p", profile, resolved, *command.argv,
            ),
            profile=profile,
            environment=dict(environment),
            enforcement=SandboxEnforcementFactsV1(
                backend="seatbelt",
                enforcement="confined",
                mode=policy.mode,
                network=policy.network,
                policy_digest=policy.policy_digest,
                profile_digest=hashlib.sha256(profile.encode()).hexdigest(),
            ),
        )


class FakeRunner:
    def __init__(self, draft=None) -> None:
        self.draft = draft or SimpleNamespace(
            outcome=ProcessDraftOutcome.EXITED,
            pid=1,
            process_group_id=1,
            exit_code=0,
            signal=None,
            started_at_monotonic=0.0,
            ended_at_monotonic=0.1,
            duration_seconds=0.1,
            stdout_bytes=0,
            stderr_bytes=0,
            stdout_digest="a" * 64,
            stderr_digest="b" * 64,
            stdout_projection="",
            stderr_projection="",
            stdout_truncated=False,
            stderr_truncated=False,
            group_reaped=True,
            term_sent=False,
            kill_sent=False,
            error_code=None,
        )
        self.calls: list[dict] = []

    def __call__(self, **kwargs):  # noqa: ANN003
        self.calls.append(kwargs)
        return self.draft


def _unconfined_facts(policy):  # noqa: ANN001
    from agent.sandbox.contracts import SandboxEnforcementFactsV1

    return SandboxEnforcementFactsV1(
        backend="none",
        enforcement="unconfined",
        mode=policy.mode,
        network=policy.network,
        policy_digest=policy.policy_digest,
    )


def _roots(tmp_path):  # noqa: ANN001
    roots = {}
    for name in ("workspace", "temp", "state", "home"):
        roots[name] = tmp_path / name
        roots[name].mkdir()
    return roots


def _registration(tmp_path, **overrides):  # noqa: ANN001
    roots = _roots(tmp_path)
    confiner = overrides.pop("confiner", FakeConfiner())
    runner = overrides.pop("runner", FakeRunner())
    registration = build_shell_exec_registration(
        workspace=roots["workspace"],
        temp_root=roots["temp"],
        state_root=roots["state"],
        home=roots["home"],
        captured_path=CAPTURED_PATH,
        confiner=confiner,
        runner=runner,
        **overrides,
    )
    return registration, confiner, runner, roots


def _intent(arguments: dict, binding: dict) -> SimpleNamespace:
    return SimpleNamespace(arguments=dict(arguments), safety_binding=dict(binding))


# --------------------------------------------------------------------------- #
# 1. spec/schema/default 合同
# --------------------------------------------------------------------------- #


def test_shell_exec_spec_is_closed_and_governed() -> None:
    spec = shell_exec_tool_spec()
    assert spec.name == "shell_exec"
    assert spec.version == "governed-shell-v1"
    assert spec.input_schema == {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "mode": {
                "type": "string",
                "enum": ["read-only", "workspace-write", "danger-full-access"],
            },
            "timeout_seconds": {
                "type": "integer",
                "minimum": 10,
                "maximum": 900,
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }
    assert spec.risk is ToolRisk.HIGH
    assert spec.side_effect is SideEffectClass.EXTERNAL
    assert spec.output_policy is OutputPolicy.BOUNDED_TEXT
    assert spec.output_limit_chars == 64_000
    assert spec.approval_policy is ApprovalPolicy.ALWAYS
    assert spec.egress is EgressClass.GOVERNED_NETWORK
    assert spec.execution_authority is ExecutionAuthorityClass.ISOLATED_SANDBOX
    # 最小公开合同：不暴露 cwd/profile/network/env/stdin/tty。
    for forbidden in ("cwd", "profile", "network", "env", "stdin", "tty"):
        assert forbidden not in spec.input_schema["properties"]
    # 网络语义固定：所有 mode（含 danger）都 network off。
    assert spec.safety_policy["network"] == "off"
    assert spec.safety_policy["shell_path"] == "/bin/sh"
    assert spec.safety_policy["timeout_bounds"] == [10, 900]


# --------------------------------------------------------------------------- #
# 2. translate/prepare binding：/bin/sh identity、exact digest、默认 network
#    off、danger 强警告、独立 trust notice
# --------------------------------------------------------------------------- #


def test_binding_binds_shell_identity_exact_digest_and_network_off(tmp_path) -> None:
    registration, _, _, roots = _registration(tmp_path)
    binding = registration.prepare_binding({"command": EXACT_COMMAND})
    # /bin/sh identity + exact command 由转译后的 process command fingerprint 绑定。
    translated = prepare_process(
        {"executable": SHELL_PATH, "argv": ["-c", EXACT_COMMAND],
         "cwd": ".", "profile": "standard"},
        workspace=roots["workspace"],
        captured_path=CAPTURED_PATH,
    )
    assert binding["command_fingerprint"] == translated.command.command_fingerprint
    assert binding["command_sha256"] == hashlib.sha256(
        EXACT_COMMAND.encode("utf-8")
    ).hexdigest()
    assert binding["sandbox_mode"] == "workspace-write"
    assert binding["sandbox_network"] == "off"
    preview = binding["effect_preview"]
    # preview 用 JSON quoting 展示 exact command。
    import json

    assert f"/bin/sh -c {json.dumps(EXACT_COMMAND, ensure_ascii=False)}" in preview
    assert "network=off" in preview
    # confined preview 不携带 danger 语义（trust notice 本身含 danger 警告，
    # 故按 mode/network 字段断言）。
    assert "mode=workspace-write" in preview
    assert "network=full" not in preview
    # trust notice 独立于 native sandbox_exec。
    assert binding["trust_notice_id"] == SHELL_TRUST_NOTICE_ID
    assert binding["trust_notice_id"] != "native_sandbox_v1"
    assert binding["trust_notice_digest"] == hashlib.sha256(
        SHELL_TRUST_NOTICE.encode()
    ).hexdigest()


def test_all_modes_bind_network_off_and_danger_warns_no_fs_isolation(tmp_path) -> None:
    registration, confiner, _, _ = _registration(tmp_path)
    for mode in ("read-only", "workspace-write", "danger-full-access"):
        binding = registration.prepare_binding({"command": "true", "mode": mode})
        assert binding["sandbox_mode"] == mode
        # 网络语义固定：所有 mode（含 danger）都 network off。
        assert binding["sandbox_network"] == "off"
    danger_preview = registration.prepare_binding(
        {"command": "true", "mode": "danger-full-access"},
    )["effect_preview"]
    assert "network=off" in danger_preview
    assert "network=full" not in danger_preview
    assert "NO filesystem isolation" in danger_preview
    # confiner 收到的 policy 同样固定 network off。
    assert all(policy.network.value == "off" for policy in confiner.policies)


@pytest.mark.parametrize(
    ("timeout", "tier"),
    [
        (10, "short"),
        (11, "standard"),
        (120, "standard"),
        (121, "long"),
        (900, "long"),
    ],
)
def test_timeout_selects_minimal_tier_with_exact_wall_deadline(
    tmp_path, timeout, tier,
) -> None:
    from agent.process.contracts import ResourceProfile, ResourceProfileV1

    registration, _, runner, _ = _registration(tmp_path)
    arguments = {"command": "true", "timeout_seconds": timeout}
    binding = registration.prepare_binding(arguments)
    assert binding["timeout_seconds"] == timeout
    preview = binding["effect_preview"]
    assert f"timeout={timeout}s" in preview
    assert f"profile={tier}" in preview
    draft = registration.func(_intent(arguments, binding))
    assert isinstance(draft, SandboxExecutionDraftV1)
    assert len(runner.calls) == 1
    call = runner.calls[0]
    # wall deadline 精确等于批准值，绝不向上取整到档位上限。
    assert call["profile"].wall_deadline_seconds == timeout
    assert call["profile"].profile.value == tier
    # 其余 caps/grace 来自该最小足够档位。
    tier_limits = ResourceProfileV1.for_profile(ResourceProfile(tier))
    assert call["profile"].term_grace_seconds == tier_limits.term_grace_seconds
    assert call["profile"].kill_grace_seconds == tier_limits.kill_grace_seconds
    assert call["profile"].stdout_cap_bytes == tier_limits.stdout_cap_bytes
    assert call["profile"].combined_cap_bytes == tier_limits.combined_cap_bytes


def test_same_tier_timeouts_never_reuse_one_binding(tmp_path) -> None:
    registration, _, runner, _ = _registration(tmp_path)
    first = registration.prepare_binding(
        {"command": "true", "timeout_seconds": 60},
    )
    second = registration.prepare_binding(
        {"command": "true", "timeout_seconds": 90},
    )
    assert first["timeout_seconds"] == 60
    assert second["timeout_seconds"] == 90
    assert first != second
    assert first["effect_preview"] != second["effect_preview"]
    # 旧 binding 执行新 timeout 的 intent：runner 前 KnownNotExecuted。
    outcome = registration.func(
        _intent({"command": "true", "timeout_seconds": 90}, first),
    )
    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "shell_command_or_policy_changed"
    assert runner.calls == []


# --------------------------------------------------------------------------- #
# 3. pipeline/&&/重定向/expansion 原样成为单一 -c argv，不被解析
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "command",
    [
        "echo start && cat notes.txt | grep ok > out.txt $(pwd); rm -rf x || true",
        "for i in 1 2 3; do echo $i; done | tee log; unset i",
        "a=b C=d env sh -c 'echo $a $C' > /dev/null 2>&1 < /dev/null",
    ],
)
def test_shell_syntax_survives_as_single_dash_c_argv(tmp_path, command) -> None:
    registration, confiner, _, _ = _registration(tmp_path)
    intent = _intent(
        {"command": command}, registration.prepare_binding({"command": command}),
    )
    draft = registration.func(intent)
    assert isinstance(draft, SandboxExecutionDraftV1)
    assert draft.outcome.value == "exited"
    # confiner 收到的是唯一转译：/bin/sh + ["-c", exact command]。
    assert len(confiner.commands) == 1
    translated = confiner.commands[0]
    assert translated.executable_token == SHELL_PATH
    assert translated.executable_identity.resolved_path == SHELL_PATH
    assert translated.argv == ("-c", command)


# --------------------------------------------------------------------------- #
# 4. binding drift 在 executor 前 KnownNotExecuted
# --------------------------------------------------------------------------- #


def test_binding_drift_is_rejected_before_executor(tmp_path) -> None:
    registration, confiner, runner, _ = _registration(tmp_path)
    arguments = {"command": EXACT_COMMAND, "timeout_seconds": 90}
    binding = registration.prepare_binding(arguments)
    hex_a, hex_b = "a" * 64, "b" * 64
    for mutated in (
        {**binding, "command_fingerprint": hex_a},
        {**binding, "command_sha256": hex_b},
        {**binding, "policy_digest": hex_a},
        {**binding, "timeout_seconds": 60},
    ):
        outcome = registration.func(_intent(arguments, mutated))
        assert isinstance(outcome, KnownNotExecuted)
        assert outcome.code == "shell_command_or_policy_changed"
    assert confiner.commands == [] and runner.calls == []


# --------------------------------------------------------------------------- #
# 5. invoke 交给 NativeSandboxExecutor：closed env、no shell=True
# --------------------------------------------------------------------------- #


def test_invoke_reaches_executor_with_closed_environment(tmp_path) -> None:
    registration, _, runner, roots = _registration(tmp_path)
    arguments = {"command": EXACT_COMMAND}
    intent = _intent(arguments, registration.prepare_binding(arguments))
    draft = registration.func(intent)
    assert isinstance(draft, SandboxExecutionDraftV1)
    assert draft.original_command_fingerprint == intent.safety_binding[
        "command_fingerprint"
    ]
    assert len(runner.calls) == 1
    call = runner.calls[0]
    # confined 路径：runner 收到 sandbox-exec 包装的 argv（-p profile
    # /bin/sh -c exact command），不存在 shell=True 通道。
    assert call["resolved_executable"] == "/usr/bin/sandbox-exec"
    assert call["argv"][0] == "-p"
    assert call["argv"][2:] == (SHELL_PATH, "-c", EXACT_COMMAND)
    assert set(call) == {"resolved_executable", "argv", "cwd", "profile", "environment"}
    # cwd 固定 workspace root，不再由参数提供。
    assert call["cwd"] == str(roots["workspace"])
    assert call["profile"].profile.value == "standard"
    assert set(call["environment"]) == {
        "HOME", "TMPDIR", "PATH", "LANG", "LC_CTYPE", "TZ",
    }
    assert call["environment"]["PATH"] == CAPTURED_PATH


# --------------------------------------------------------------------------- #
# 6. invalid command/cwd/mode fail closed
# --------------------------------------------------------------------------- #


# 注：未知参数（cwd/profile/network/env/stdin/tty 等）在 runtime 层由 closed
# schema 的 additionalProperties=False 拒绝，在 binding 层由 closed 参数集拒绝。
@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"command": None},
        {"command": 123},
        {"command": ""},
        {"command": "   \t \n"},
        {"command": "true\x00false"},
        {"command": "x" * (16 * 1024 + 1)},
        {"command": "true", "mode": "full"},
        {"command": "true", "mode": None},
        # 最小公开合同：这些参数不再存在于 shell_exec。
        {"command": "true", "cwd": "."},
        {"command": "true", "profile": "short"},
        {"command": "true", "network": "off"},
        {"command": "true", "env": {"X": "1"}},
        {"command": "true", "stdin": "data"},
        {"command": "true", "tty": True},
        # timeout_seconds：int（拒绝 bool）、闭区间 10..900。
        {"command": "true", "timeout_seconds": True},
        {"command": "true", "timeout_seconds": False},
        {"command": "true", "timeout_seconds": 9},
        {"command": "true", "timeout_seconds": 901},
        {"command": "true", "timeout_seconds": 11.0},
        {"command": "true", "timeout_seconds": "120"},
    ],
)
def test_invalid_arguments_fail_closed_at_binding(tmp_path, arguments) -> None:
    registration, confiner, runner, _ = _registration(tmp_path)
    with pytest.raises(ValueError):
        registration.prepare_binding(arguments)
    assert confiner.commands == [] and runner.calls == []


def test_shell_trust_notice_states_network_scope_honestly(tmp_path) -> None:
    registration, _, _, _ = _registration(tmp_path)
    notice = SHELL_TRUST_NOTICE
    # danger 不增加 filesystem 隔离，但网络仍固定 off。
    assert "danger-full-access" in notice
    assert "no filesystem isolation" in notice
    assert "network" in notice and "every mode" in notice
    # network=off 的边界必须准确：只约束本命令与受 Seatbelt 管辖的普通子进程。
    assert "Seatbelt-governed subprocesses" in notice
    assert "does not disconnect" in notice
    assert "already-open file descriptors" in notice
    assert "system services" in notice
    assert "writable files" in notice
    # binding 的 trust digest 从当前文本派生：文本变更触发新 digest。
    binding = registration.prepare_binding({"command": "true"})
    assert binding["trust_notice_digest"] == hashlib.sha256(
        notice.encode("utf-8"),
    ).hexdigest()


def test_timeout_defaults_to_120_and_accepts_closed_range(tmp_path) -> None:
    registration, _, _, _ = _registration(tmp_path)
    default_binding = registration.prepare_binding({"command": "true"})
    assert default_binding["timeout_seconds"] == 120
    for accepted in (10, 11, 120, 121, 900):
        binding = registration.prepare_binding(
            {"command": "true", "timeout_seconds": accepted},
        )
        assert binding["timeout_seconds"] == accepted


def test_backend_unavailable_means_zero_runner_calls_in_every_mode(tmp_path) -> None:
    from agent.runtime.contracts import KnownNotExecuted as _Kne

    class UnavailableConfiner:
        def confine(self, command, policy, environment):  # noqa: ANN001
            return _Kne(
                code="sandbox_exec_missing",
                message="sandbox backend unavailable; shell not executed",
            )

    registration, _, runner, _ = _registration(
        tmp_path, confiner=UnavailableConfiner(),
    )
    # 三个 shell mode 都依赖 Seatbelt backend：缺 backend ⇒ 零目标 runner。
    for mode in ("read-only", "workspace-write", "danger-full-access"):
        arguments = {"command": "true", "mode": mode}
        binding = registration.prepare_binding(arguments)
        outcome = registration.func(_intent(arguments, binding))
        assert isinstance(outcome, KnownNotExecuted)
        assert outcome.code == "sandbox_exec_missing"
    assert runner.calls == []


def test_malicious_unconfined_fake_reaches_no_runner_in_any_mode(tmp_path) -> None:
    # 专门恶意 fake：在 network-off policy 下伪报 none/off facts——所有 mode
    # 都必须在 runner 前被 enforcement 校验拒绝（正常 fake 见 FakeConfiner）。
    class MaliciousConfiner:
        def confine(self, command, policy, environment):  # noqa: ANN001
            from agent.sandbox.contracts import ConfinedInvocationV1

            resolved = command.executable_identity.resolved_path
            return ConfinedInvocationV1(
                wrapped_executable=resolved,
                wrapped_argv=(resolved, *command.argv),
                profile=None,
                environment=dict(environment),
                enforcement=_unconfined_facts(policy),
            )

    registration, _, runner, _ = _registration(
        tmp_path, confiner=MaliciousConfiner(),
    )
    for mode in ("read-only", "workspace-write", "danger-full-access"):
        arguments = {"command": "true", "mode": mode}
        binding = registration.prepare_binding(arguments)
        outcome = registration.func(_intent(arguments, binding))
        assert isinstance(outcome, KnownNotExecuted)
        assert outcome.code == "enforcement_facts_mismatch"
    assert runner.calls == []


def test_public_runtime_reasks_when_timeout_changes_within_same_tier(tmp_path) -> None:
    from agent.runtime.contracts import (
        SandboxAuthorityLeaseV1,
        ToolCall,
        ToolPrepareContext,
    )
    from agent.runtime.tools import ApprovalRequired, KernelToolRuntime

    registration, _, _, _ = _registration(tmp_path)
    runtime = KernelToolRuntime(
        (registration,), clock=lambda: "2026-09-05T08:00:00+00:00",
    )

    def context(leases=()):  # noqa: ANN202
        return ToolPrepareContext(
            conversation_id="conversation-1",
            run_id="run-1",
            state_revision=1,
            goal_id="goal-1",
            goal_revision=1,
            workspace_identity_digest="workspace-digest-1",
            sandbox_leases=leases,
        )

    def call(arguments):  # noqa: ANN202
        return ToolCall("call-1", "shell_exec", arguments)

    pending = runtime.prepare(
        call({"command": "true", "timeout_seconds": 60}), context(),
    )
    assert isinstance(pending, ApprovalRequired)
    candidate = pending.request.sandbox_authority_candidate
    lease = SandboxAuthorityLeaseV1.create(
        lease_id="sandbox-lease:t60",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        workspace_identity_digest=candidate.workspace_identity_digest,
        original_command_fingerprint=candidate.original_command_fingerprint,
        policy_digest=candidate.policy_digest,
        mode=candidate.mode,
        network=candidate.network,
        readable_command=candidate.readable_command,
        trust_notice_id=candidate.trust_notice_id,
        trust_notice_digest=candidate.trust_notice_digest,
        approved_request_identity="approval-60",
        issued_at="2026-09-05T07:59:00+00:00",
        expires_at="2026-09-05T10:00:00+00:00",
    )
    same_timeout = runtime.prepare(
        call({"command": "true", "timeout_seconds": 60}), context((lease,)),
    )
    assert not isinstance(same_timeout, ApprovalRequired)
    # 同档位不同 timeout：candidate（含带 timeout 的 preview）不再匹配旧
    # lease，必须重新 approval，不得跨 timeout 复用 approval lease。
    changed = runtime.prepare(
        call({"command": "true", "timeout_seconds": 90}), context((lease,)),
    )
    assert isinstance(changed, ApprovalRequired)


def test_shell_workspace_root_replacement_is_known_not_executed(tmp_path) -> None:
    registration, _, runner, roots = _registration(tmp_path)
    arguments = {"command": EXACT_COMMAND}
    binding = registration.prepare_binding(arguments)
    # cwd 固定 workspace root：prepare 后同路径 rm+mkdir（新 inode）→
    # descriptor 漂移在 spawn 前被拒绝，零 runner 调用。
    import shutil

    shutil.rmtree(roots["workspace"])
    roots["workspace"].mkdir()
    outcome = registration.func(_intent(arguments, binding))
    assert isinstance(outcome, KnownNotExecuted)
    # boundary 持有旧 root identity：同路径新目录在 admission 即被拒绝。
    assert outcome.code == "cwd_boundary_denied"
    assert runner.calls == []
