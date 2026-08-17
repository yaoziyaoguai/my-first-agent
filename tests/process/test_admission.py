"""015 U4：executable / cwd / environment admission 的 closed 合同与行为。

admission 在任何 effect 之前解析 command identity 并构造 secret-minimized spawn
profile（KTD5/KTD7）。下列 Red 在 ``agent.process`` 落地前因模块缺失而准确失败
（guarded import → ``pytest.fail``），落地后转为 Green。
"""

from __future__ import annotations

import os
import stat

import pytest

try:
    from agent.process.admission import (
        build_environment_plan,
        resolve_executable,
        revalidate_executable,
    )
    from agent.process.contracts import (
        SAME_UID_TRUST_NOTICE,
        EnvironmentProfileV1,
        ExecutableIdentityV1,
        KnownNotExecuted,
        ProcessCommandV1,
        ResourceProfile,
        ResourceProfileV1,
    )

    _AVAILABLE = True
except ModuleNotFoundError:
    _AVAILABLE = False


def _require_admission():
    if not _AVAILABLE:
        pytest.fail("015 requires agent.process admission contracts")


def test_015_resource_profiles_are_closed_with_fixed_limits() -> None:
    """R4 / §7.3：三个 closed profile 的 wall deadline / grace / caps 固定，模型只能选枚举。"""

    _require_admission()
    expected = {
        ResourceProfile.SHORT: dict(
            wall_deadline_seconds=10,
            term_grace_seconds=1,
            kill_grace_seconds=1,
            stdout_cap_bytes=256 * 1024,
            stderr_cap_bytes=256 * 1024,
            combined_cap_bytes=512 * 1024,
            rendered_chars=16_000,
        ),
        ResourceProfile.STANDARD: dict(
            wall_deadline_seconds=120,
            term_grace_seconds=2,
            kill_grace_seconds=2,
            stdout_cap_bytes=1024 * 1024,
            stderr_cap_bytes=1024 * 1024,
            combined_cap_bytes=2 * 1024 * 1024,
            rendered_chars=32_000,
        ),
        ResourceProfile.LONG: dict(
            wall_deadline_seconds=900,
            term_grace_seconds=5,
            kill_grace_seconds=5,
            stdout_cap_bytes=2 * 1024 * 1024,
            stderr_cap_bytes=2 * 1024 * 1024,
            combined_cap_bytes=4 * 1024 * 1024,
            rendered_chars=64_000,
        ),
    }
    assert {item.value for item in ResourceProfile} == {"short", "standard", "long"}
    for profile, limits in expected.items():
        spec = ResourceProfileV1.for_profile(profile)
        assert spec.profile is profile
        for field_name, value in limits.items():
            assert getattr(spec, field_name) == value, f"{profile.value}.{field_name}"
        # 所有 profile 共享的 argv / hash 上限。
        assert spec.argv_max_items == 128
        assert spec.argv_item_max_bytes == 16 * 1024
        assert spec.argv_total_max_bytes == 64 * 1024
        assert spec.executable_hash_max_bytes == 256 * 1024 * 1024


def test_015_same_uid_trust_notice_states_boundary_not_os_sandbox() -> None:
    """R13-R16 / §3.2：披露必须说明 same-UID，不得宣称 OS sandbox/filesystem confinement。"""

    _require_admission()
    lowered = SAME_UID_TRUST_NOTICE.casefold()
    assert "same-uid" in lowered
    # 诚实披露：明确否认 OS sandbox / filesystem confinement / network denial，而不是
    # 让这些词缺席——用户必须看到「这【不】是 sandbox」的准确措辞。
    assert "not an os sandbox" in lowered
    assert "not a filesystem confinement" in lowered
    assert "not a network denial" in lowered


def test_015_environment_profile_excludes_secret_and_proxy_keys() -> None:
    """R14 / §7.2：closed environment allowlist 不得包含 provider/proxy/ambient key。"""

    _require_admission()
    plan = build_environment_plan(captured_path="/usr/bin:/bin")
    assert isinstance(plan, EnvironmentProfileV1)
    allow = {name.casefold() for name in plan.allowlist}
    for forbidden in (
        "anthropic_api_key",
        "openai_api_key",
        "first_agent_api_key",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "ssh_auth_sock",
        "aws_secret_access_key",
    ):
        assert forbidden not in allow, f"environment allowlist must exclude {forbidden}"
    # PATH 是 composition 捕获的 bounded host PATH；locale 是 closed safe subset。
    assert "path" in allow


def _make_executable(directory, name: str, content: bytes = b"#!/bin/sh\necho hi\n") -> str:
    path = directory / name
    path.write_bytes(content)
    os.chmod(path, stat.S_IRWXU)
    return str(path)


def test_015_resolve_absolute_executable_binds_identity() -> None:
    """R12 / KTD5：absolute executable 解析为 regular-file identity（path + stat + digest）。"""

    _require_admission()
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as raw_dir:
        directory = Path(raw_dir)
        exe = _make_executable(directory, "fixture-exe")
        identity = resolve_executable(exe, search_paths=())
        assert isinstance(identity, ExecutableIdentityV1)
        assert identity.is_regular_executable is True
        assert identity.content_digest  # bounded SHA-256 of content
        assert identity.identity_digest  # canonical identity digest
        assert identity.size == len(b"#!/bin/sh\necho hi\n")


def test_015_admission_rejects_missing_non_executable_and_directory() -> None:
    """R12 / AE6：missing / non-executable / directory 在 spawn 前 fail closed。"""

    _require_admission()
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as raw_dir:
        directory = Path(raw_dir)
        # missing
        rejected = resolve_executable(str(directory / "absent"), search_paths=())
        assert isinstance(rejected, KnownNotExecuted)
        # non-executable regular file
        plain = directory / "plain"
        plain.write_bytes(b"data")
        os.chmod(plain, stat.S_IRUSR | stat.S_IWUSR)
        rejected = resolve_executable(str(plain), search_paths=())
        assert isinstance(rejected, KnownNotExecuted)
        # directory
        rejected = resolve_executable(str(directory), search_paths=())
        assert isinstance(rejected, KnownNotExecuted)


def test_015_executable_revalidation_detects_content_drift() -> None:
    """R12 / AE6 / KTD5：approval 后 content 替换，revalidation 返回 identity changed。"""

    _require_admission()
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as raw_dir:
        directory = Path(raw_dir)
        exe = _make_executable(directory, "drift-exe", b"#!/bin/sh\necho one\n")
        identity = resolve_executable(exe, search_paths=())
        assert isinstance(identity, ExecutableIdentityV1)
        # 替换内容（保持可执行位）。
        exe_path = Path(exe)
        exe_path.write_bytes(b"#!/bin/sh\necho two\n")
        os.chmod(exe_path, stat.S_IRWXU)
        revalidated = revalidate_executable(identity)
        assert isinstance(revalidated, KnownNotExecuted)
        assert revalidated.code == "executable_identity_changed"


def test_015_executable_revalidation_detects_permission_drift(tmp_path) -> None:
    """Approval 后 permission mode 漂移必须 fail closed，即使 bytes/stat 其余不变。"""

    _require_admission()
    exe = _make_executable(tmp_path, "mode-drift")
    identity = resolve_executable(exe, search_paths=())
    assert isinstance(identity, ExecutableIdentityV1)
    # 普通 group-read 位在 macOS sandbox/materialized tree 中也稳定保留；set-id 位可能
    # 被宿主文件系统静默清除，会让安全回归测试产生环境相关 false pass/fail。
    os.chmod(exe, stat.S_IRWXU | stat.S_IRGRP)

    revalidated = revalidate_executable(identity)
    assert isinstance(revalidated, KnownNotExecuted)
    assert revalidated.code == "executable_identity_changed"


def test_015_relative_path_entries_are_not_executable_authority(tmp_path) -> None:
    """相对 PATH 不能在 admission cwd 与 spawn cwd 之间重定向到另一个 binary。"""

    _require_admission()
    relative_bin = tmp_path / "relative-bin"
    relative_bin.mkdir()
    _make_executable(relative_bin, "fixture-exe")

    result = resolve_executable(
        "fixture-exe",
        search_paths=("relative-bin",),
        workspace_root=tmp_path / "workspace-without-exe",
    )
    assert isinstance(result, KnownNotExecuted)
    assert result.code == "not_found"


def test_015_argv_and_command_fingerprint_are_literal_and_bounded() -> None:
    """R4 / AE2 / §6：argv 作为 literal bytes；profile + argv/cwd 进入 command fingerprint。"""

    _require_admission()
    argv = ("--flag", ";", "|", ">", "$()", "`", "line\nwith newline")
    command = ProcessCommandV1(
        executable_token="/usr/bin/true",
        argv=argv,
        cwd=".",
        profile=ResourceProfile.STANDARD,
        executable_identity=None,
        environment_policy=None,
    )
    # argv 原样保留（含 shell metacharacter 与 newline），不做字符串拒绝。
    assert command.argv == argv
    assert command.profile is ResourceProfile.STANDARD
    assert command.command_fingerprint
    # profile 变化改变 command identity。
    different = ProcessCommandV1(
        executable_token="/usr/bin/true",
        argv=argv,
        cwd=".",
        profile=ResourceProfile.LONG,
        executable_identity=None,
        environment_policy=None,
    )
    assert different.command_fingerprint != command.command_fingerprint


def test_015_executable_over_hash_cap_rejected_not_prefix_hashed(tmp_path) -> None:
    """P3（冻结合同）：executable 超过 256 MiB 必须拒绝，不得只 hash prefix 冒充
    identity digest——否则两个共享前 256MiB 的大文件会得到同一 identity。"""

    if not _AVAILABLE:
        pytest.fail("015 requires agent.process admission contracts")

    cap = ResourceProfileV1.for_profile(ResourceProfile.STANDARD).executable_hash_max_bytes
    path = tmp_path / "huge-exe"
    with open(path, "wb") as handle:
        handle.truncate(cap + 1)
    os.chmod(path, stat.S_IRWXU)
    result = resolve_executable(str(path))
    assert isinstance(result, KnownNotExecuted)
    assert result.code == "executable_too_large"
