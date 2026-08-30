from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent.automation_hosts.macos_profile import (
    BackgroundSeatbeltPolicyV1,
    compile_background_seatbelt_profile,
)
from agent.sandbox.seatbelt import SeatbeltConfiner
from agent.sandbox.tools import build_sandbox_exec_registration
from tests.sandbox.test_backend_qualification import FakeRunner
from tests.sandbox.test_seatbelt import CLOSED_ENV, _command


def _policy(tmp_path: Path) -> BackgroundSeatbeltPolicyV1:
    workspace = tmp_path / "occurrence"
    temp_root = tmp_path / "job-temp"
    home_root = tmp_path / "job-home"
    for path in (workspace, temp_root, home_root):
        path.mkdir(parents=True, mode=0o700)
    return BackgroundSeatbeltPolicyV1.create(
        workspace_root=workspace,
        temp_root=temp_root,
        home_root=home_root,
        runtime_read_roots=(
            Path("/System/Library"),
            Path("/usr/lib"),
        ),
        executable_literals=(Path("/bin/cat"),),
    )


def _sandbox(profile: str, *argv: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - exact test-owned argv under Seatbelt
        ("/usr/bin/sandbox-exec", "-p", profile, *argv),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=5,
        check=False,
    )


def _require_nested_seatbelt() -> None:
    probe = _sandbox("(version 1)\n(allow default)\n(deny network*)\n", "/usr/bin/true")
    if probe.returncode == 71 and b"sandbox_apply: Operation not permitted" in probe.stderr:
        pytest.skip("current managed Coding sandbox forbids nested macOS Seatbelt")


def test_background_profile_reads_owned_workspace_and_denies_other_owner_file(
    tmp_path,
) -> None:
    _require_nested_seatbelt()
    policy = _policy(tmp_path)
    allowed = Path(policy.workspace_root) / "allowed.txt"
    blocked_root = tmp_path / "owner-source"
    blocked_root.mkdir(mode=0o700)
    blocked = blocked_root / "blocked.txt"
    allowed.write_text("ALLOWED_SENTINEL", encoding="utf-8")
    blocked.write_text("BLOCKED_SENTINEL", encoding="utf-8")
    profile = compile_background_seatbelt_profile(policy)

    allowed_result = _sandbox(profile, "/bin/cat", str(allowed))
    blocked_result = _sandbox(profile, "/bin/cat", str(blocked))

    assert allowed_result.returncode == 0
    assert allowed_result.stdout == b"ALLOWED_SENTINEL"
    assert blocked_result.returncode != 0
    assert b"BLOCKED_SENTINEL" not in blocked_result.stdout
    assert b"BLOCKED_SENTINEL" not in blocked_result.stderr


def test_background_profile_allows_job_temp_and_home_but_denies_state(tmp_path) -> None:
    _require_nested_seatbelt()
    policy = _policy(tmp_path)
    state_root = tmp_path / "automation-state"
    state_root.mkdir(mode=0o700)
    paths = {
        "temp": Path(policy.temp_root) / "temp.txt",
        "home": Path(policy.home_root) / "home.txt",
        "state": state_root / "state.txt",
    }
    for name, path in paths.items():
        path.write_text(name, encoding="utf-8")
    profile = compile_background_seatbelt_profile(policy)

    assert _sandbox(profile, "/bin/cat", str(paths["temp"])).stdout == b"temp"
    assert _sandbox(profile, "/bin/cat", str(paths["home"])).stdout == b"home"
    denied = _sandbox(profile, "/bin/cat", str(paths["state"]))
    assert denied.returncode != 0
    assert b"state" not in denied.stdout


def test_background_profile_is_network_off_and_has_no_broad_read_allow() -> None:
    profile = compile_background_seatbelt_profile(
        BackgroundSeatbeltPolicyV1(
            workspace_root="/owned/workspace",
            temp_root="/owned/temp",
            home_root="/owned/home",
            runtime_read_roots=("/System/Library", "/usr/lib"),
            executable_literals=("/bin/cat",),
        )
    )

    assert "(deny default)" in profile
    assert "(deny network*)" in profile
    assert '(allow file-read* (subpath "/owned/workspace"))' in profile
    assert '(allow file-read* (literal "/"))' in profile
    assert '(allow file-read* (subpath "/"))' not in profile
    assert "(allow network*)" not in profile


def test_existing_sandbox_registration_and_confiner_accept_exact_background_policy(
    tmp_path,
) -> None:
    policy = _policy(tmp_path)
    confiner = SeatbeltConfiner(
        runner=FakeRunner(),
        platform_system="Darwin",
        profile_compiler=compile_background_seatbelt_profile,
        legacy_policy_type=BackgroundSeatbeltPolicyV1,
    )
    registration = build_sandbox_exec_registration(
        workspace=Path(policy.workspace_root),
        temp_root=Path(policy.temp_root),
        state_root=tmp_path / "state",
        home=Path(policy.home_root),
        captured_path="/usr/bin:/bin",
        confiner=confiner,
        policy_builder=lambda _arguments, _roots, _private: policy,
        authority_policy_digest=policy.template_digest,
    )
    (tmp_path / "state").mkdir(mode=0o700)

    binding = registration.prepare_binding({"executable": "/bin/cat"})
    invocation = confiner.confine(_command(resolved="/bin/cat"), policy, CLOSED_ENV)

    assert binding["policy_digest"] == policy.template_digest
    assert binding["policy_instance_digest"] == policy.policy_digest
    assert binding["sandbox_mode"] == "workspace-write"
    assert binding["sandbox_network"] == "off"
    assert invocation.profile == compile_background_seatbelt_profile(policy)


def test_background_policy_template_is_stable_across_fresh_occurrence_roots(
    tmp_path,
) -> None:
    first = _policy(tmp_path / "first")
    second = _policy(tmp_path / "second")

    assert first.template_digest == second.template_digest
    assert first.policy_digest != second.policy_digest
    assert first.workspace_root != second.workspace_root
    assert first.workspace_root in compile_background_seatbelt_profile(first)
    assert second.workspace_root in compile_background_seatbelt_profile(second)


def test_background_policy_template_binds_the_qualified_read_allowlist(
    tmp_path,
) -> None:
    first = _policy(tmp_path / "first")
    root = tmp_path / "second"
    workspace = root / "occurrence"
    temp_root = root / "job-temp"
    home_root = root / "job-home"
    extra_runtime = root / "runtime"
    for path in (workspace, temp_root, home_root, extra_runtime):
        path.mkdir(parents=True, mode=0o700)
    second = BackgroundSeatbeltPolicyV1.create(
        workspace_root=workspace,
        temp_root=temp_root,
        home_root=home_root,
        runtime_read_roots=(Path("/System/Library"), extra_runtime),
        executable_literals=(Path("/bin/cat"),),
    )

    assert first.template_digest != second.template_digest


def test_background_registration_rejects_instance_root_drift_with_same_template(
    tmp_path,
) -> None:
    first = _policy(tmp_path / "first")
    second = _policy(tmp_path / "second")
    selected = iter((first, second))
    confiner = SeatbeltConfiner(
        runner=FakeRunner(),
        platform_system="Darwin",
        profile_compiler=compile_background_seatbelt_profile,
        legacy_policy_type=BackgroundSeatbeltPolicyV1,
    )
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    registration = build_sandbox_exec_registration(
        workspace=Path(first.workspace_root),
        temp_root=Path(first.temp_root),
        state_root=state_root,
        home=Path(first.home_root),
        captured_path="/usr/bin:/bin",
        confiner=confiner,
        policy_builder=lambda _arguments, _roots, _private: next(selected),
        authority_policy_digest=first.template_digest,
    )

    binding = registration.prepare_binding({"executable": "/bin/cat"})
    result = registration.func(
        type(
            "Intent",
            (),
            {
                "arguments": {"executable": "/bin/cat"},
                "safety_binding": binding,
            },
        )()
    )

    assert result.code == "sandbox_policy_or_command_changed"
