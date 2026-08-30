"""017 SeatbeltConfiner.confine 合同：pure wrapping，绝不 spawn。

confined modes 包装为 ``sandbox-exec -p <profile> <exact command>`` 并携带
seatbelt/confined facts；danger-full-access 是 unconfined bypass（不探测
backend）；backend unavailable ⇒ KnownNotExecuted（fail closed）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from agent.process.contracts import ExecutableIdentityV1
from agent.runtime.contracts import KnownNotExecuted
from agent.sandbox import seatbelt as seatbelt_module
from agent.sandbox.contracts import (
    ConfinedInvocationV1,
    PackagedSkillResourceLimitsV1,
    PackagedSkillSandboxPolicyV1,
    SandboxMode,
    SandboxNetworkMode,
)
from agent.sandbox.packaged_policy import build_packaged_skill_policy
from agent.sandbox.policy import build_sandbox_policy, compile_seatbelt_profile
from agent.sandbox.qualification import ProbeResult
from agent.sandbox.seatbelt import SeatbeltConfiner
from tests.sandbox.test_backend_qualification import FakeRunner

CLOSED_ENV = {"HOME": "/tmp/sbx-home", "PATH": "/usr/bin:/bin", "TMPDIR": "/tmp/sbx-tmp"}


@dataclass(frozen=True)
class RegisteredLegacyPolicy:
    mode: SandboxMode = SandboxMode.READ_ONLY
    network: SandboxNetworkMode = SandboxNetworkMode.OFF
    policy_digest: str = "c" * 64


def _identity(resolved: str = "/bin/true") -> ExecutableIdentityV1:
    return ExecutableIdentityV1(
        token=resolved,
        resolved_path=resolved,
        symlink_chain=(),
        st_dev=1,
        st_ino=2,
        file_type="regular",
        mode=0o755,
        size=1000,
        mtime_ns=1,
        content_digest="a" * 64,
        is_regular_executable=True,
        identity_digest="b" * 64,
    )


def _command(argv=("-lc", "true"), resolved: str = "/bin/sh"):
    from agent.process.contracts import ProcessCommandV1, ResourceProfile

    return ProcessCommandV1(
        executable_token=resolved,
        argv=argv,
        cwd="/tmp",
        profile=ResourceProfile.SHORT,
        executable_identity=_identity(resolved),
    )


def _policy(tmp_path, mode=SandboxMode.WORKSPACE_WRITE):
    for name in ("work", "tmp", "state", "home"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    return build_sandbox_policy(
        mode=mode,
        network=SandboxNetworkMode.OFF,
        workspace=tmp_path / "work",
        temp_root=tmp_path / "tmp",
        state_root=tmp_path / "state",
        home=tmp_path / "home",
        private_roots=(),
    )


def _qualified_confiner() -> tuple[SeatbeltConfiner, FakeRunner]:
    fake = FakeRunner()
    confiner = SeatbeltConfiner(runner=fake, platform_system="Darwin")
    return confiner, fake


def test_workspace_write_wraps_exact_command_and_records_facts(tmp_path):
    confiner, _fake = _qualified_confiner()
    command = _command()
    policy = _policy(tmp_path)
    invocation = confiner.confine(command, policy, CLOSED_ENV)
    assert isinstance(invocation, ConfinedInvocationV1)
    assert invocation.wrapped_executable == "/usr/bin/sandbox-exec"
    tail = (command.executable_identity.resolved_path, *command.argv)
    assert invocation.wrapped_argv[-len(tail):] == tail
    assert invocation.wrapped_argv[:3] == ("/usr/bin/sandbox-exec", "-p", invocation.profile)
    assert invocation.enforcement.backend == "seatbelt"
    assert invocation.enforcement.enforcement == "confined"
    assert invocation.enforcement.policy_digest == policy.policy_digest
    expected_profile = compile_seatbelt_profile(policy)
    assert invocation.profile == expected_profile
    assert invocation.enforcement.profile_digest == hashlib.sha256(
        expected_profile.encode(),
    ).hexdigest()


def test_read_only_confine_compiles_read_only_profile(tmp_path):
    confiner, _fake = _qualified_confiner()
    policy = _policy(tmp_path, mode=SandboxMode.READ_ONLY)
    invocation = confiner.confine(_command(), policy, CLOSED_ENV)
    assert "(deny network*)" in invocation.profile


def test_danger_bypass_does_not_probe_backend_and_records_unconfined(tmp_path):
    fake = FakeRunner(
        result=ProbeResult(1, b"", b"would fail", False),
    )
    confiner = SeatbeltConfiner(runner=fake, platform_system="Linux")
    policy = _policy(tmp_path, mode=SandboxMode.DANGER_FULL_ACCESS)
    invocation = confiner.confine(_command(), policy, CLOSED_ENV)
    assert invocation.wrapped_executable == "/bin/sh"
    assert invocation.wrapped_argv == ("/bin/sh", "-lc", "true")
    assert invocation.profile is None
    assert invocation.enforcement.backend == "none"
    assert invocation.enforcement.enforcement == "unconfined"
    assert invocation.enforcement.policy_digest == policy.policy_digest
    # bypass 不探测 backend：fake 零调用（即便 platform 不支持）
    assert fake.calls == []


def test_confined_backend_unavailable_fails_closed_without_spawn(tmp_path):
    fake = FakeRunner()
    confiner = SeatbeltConfiner(runner=fake, platform_system="Linux")
    policy = _policy(tmp_path)
    outcome = confiner.confine(_command(), policy, CLOSED_ENV)
    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "unsupported_platform"
    assert fake.calls == []


def test_confined_missing_binary_fails_closed(tmp_path):
    confiner = SeatbeltConfiner(
        binary="/definitely/not/sandbox-exec",
        runner=FakeRunner(),
        platform_system="Darwin",
    )
    outcome = confiner.confine(_command(), _policy(tmp_path), CLOSED_ENV)
    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "sandbox_exec_missing"


def test_environment_is_copied_not_aliased(tmp_path):
    confiner, _fake = _qualified_confiner()
    env = dict(CLOSED_ENV)
    invocation = confiner.confine(_command(), _policy(tmp_path), env)
    env["HOME"] = "/mutated"
    assert invocation.environment["HOME"] == "/tmp/sbx-home"


def test_wrapped_argv_is_argument_vector_only(tmp_path):
    confiner, _fake = _qualified_confiner()
    command = _command(argv=("-c", "echo 'quoted; string'"))
    invocation = confiner.confine(command, _policy(tmp_path), CLOSED_ENV)
    assert isinstance(invocation, ConfinedInvocationV1)
    # profile 内联经 -p 传递（不落盘、不进 shell）；命令以独立 argv 元素出现
    assert invocation.wrapped_argv[2] == invocation.profile
    assert invocation.wrapped_argv[-3:] == (
        "/bin/sh", "-c", "echo 'quoted; string'",
    )


def test_packaged_policy_uses_closed_compiler_not_legacy_injected_compiler(tmp_path):
    roots = {
        name: tmp_path / name
        for name in ("runtime", "package", "temp", "system", "work", "state", "home")
    }
    for path in roots.values():
        path.mkdir()
    for name in ("runtime", "package"):
        roots[name].chmod(0o555)
    interpreter = roots["system"] / "python"
    interpreter.write_text("fixture", encoding="utf-8")
    interpreter.chmod(0o555)
    policy = build_packaged_skill_policy(
        interpreter_path=interpreter,
        runtime_roots=(roots["runtime"],),
        package_root=roots["package"],
        temp_root=roots["temp"],
        system_runtime_roots=(roots["system"],),
        workspace_root=roots["work"],
        home_root=roots["home"],
        state_root=roots["state"],
        private_roots=(),
        runtime_closure_digest="a" * 64,
        system_runtime_digest="b" * 64,
        resource_limits=PackagedSkillResourceLimitsV1.for_profile("skill-standard-v1"),
    )
    session = roots["temp"] / "session"
    session.mkdir()
    calls = 0

    def legacy_compiler(active_policy):
        nonlocal calls
        calls += 1
        return "(version 1)\n(allow default)\n"

    confiner = SeatbeltConfiner(
        runner=FakeRunner(),
        platform_system="Darwin",
        profile_compiler=legacy_compiler,
    )
    invocation = confiner.confine(
        _command(argv=(), resolved=str(interpreter)),
        policy,
        {"TMPDIR": str(session)},
    )

    assert isinstance(invocation, ConfinedInvocationV1)
    assert calls == 0
    assert invocation.profile.startswith("(version 1)\n(deny default)\n")


def test_unknown_policy_type_is_rejected_closed_before_profile_compilation():
    calls = 0

    def legacy_compiler(active_policy):
        nonlocal calls
        calls += 1
        return "(version 1)\n(allow default)\n"

    confiner = SeatbeltConfiner(
        runner=FakeRunner(),
        platform_system="Darwin",
        profile_compiler=legacy_compiler,
    )
    outcome = confiner.confine(_command(), object(), CLOSED_ENV)

    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "sandbox_policy_type_unknown"
    assert calls == 0


def test_registered_legacy_policy_type_uses_injected_compiler():
    policy = RegisteredLegacyPolicy()
    calls = []

    def legacy_compiler(active_policy):
        calls.append(active_policy)
        return "(version 1)\n(allow default)\n"

    confiner = SeatbeltConfiner(
        runner=FakeRunner(),
        platform_system="Darwin",
        profile_compiler=legacy_compiler,
        legacy_policy_type=RegisteredLegacyPolicy,
    )
    invocation = confiner.confine(_command(), policy, CLOSED_ENV)

    assert isinstance(invocation, ConfinedInvocationV1)
    assert calls == [policy]


def test_mismatched_registered_policy_type_fails_closed_without_compiler(tmp_path):
    calls = 0

    def legacy_compiler(active_policy):
        nonlocal calls
        calls += 1
        return "(version 1)\n(allow default)\n"

    confiner = SeatbeltConfiner(
        runner=FakeRunner(),
        platform_system="Darwin",
        profile_compiler=legacy_compiler,
        legacy_policy_type=RegisteredLegacyPolicy,
    )
    outcome = confiner.confine(_command(), _policy(tmp_path), CLOSED_ENV)

    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "sandbox_policy_type_unknown"
    assert calls == 0


def test_forged_direct_packaged_policy_is_rejected_before_compiler_or_qualification(
    tmp_path, monkeypatch
):
    roots = {
        name: tmp_path / name
        for name in ("runtime", "package", "temp", "system", "work", "state", "home")
    }
    for path in roots.values():
        path.mkdir()
    for name in ("runtime", "package"):
        roots[name].chmod(0o555)
    interpreter = roots["system"] / "python"
    interpreter.write_text("fixture", encoding="utf-8")
    interpreter.chmod(0o555)
    session = roots["temp"] / "session"
    session.mkdir()
    policy = PackagedSkillSandboxPolicyV1(
        interpreter_path=str(interpreter),
        runtime_roots=("/",),
        package_root=str(roots["package"]),
        temp_root=str(roots["temp"]),
        system_runtime_roots=(str(roots["system"]),),
        workspace_root=str(roots["work"]),
        home_root=str(roots["home"]),
        state_root=str(roots["state"]),
        private_roots=(),
        runtime_closure_digest="a" * 64,
        system_runtime_digest="b" * 64,
        resource_limits=PackagedSkillResourceLimitsV1.for_profile("skill-standard-v1"),
    )
    compiler_calls = 0

    def packaged_compiler(active_policy, environment):
        nonlocal compiler_calls
        compiler_calls += 1
        return "(version 1)\n(deny default)\n"

    monkeypatch.setattr(
        seatbelt_module, "compile_packaged_skill_profile", packaged_compiler
    )
    fake = FakeRunner()
    confiner = SeatbeltConfiner(
        runner=fake,
        platform_system="Darwin",
        profile_compiler=lambda active_policy: "(version 1)\n(allow default)\n",
    )

    outcome = confiner.confine(
        _command(argv=(), resolved=str(interpreter)),
        policy,
        {"TMPDIR": str(session)},
    )

    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "sandbox_policy_type_unknown"
    assert compiler_calls == 0
    assert fake.calls == []
