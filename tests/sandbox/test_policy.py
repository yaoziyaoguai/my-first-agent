"""017 native sandbox policy builder 与 Seatbelt profile compiler。

carveout 语义（git metadata 可读禁写、credential unreadable、敏感文件名
模式）、路径转义拒绝、read-only/workspace-write 可写集、network 独立子句。
"""

from __future__ import annotations

import pytest

from agent.sandbox.contracts import SandboxMode, SandboxNetworkMode
from agent.sandbox.policy import (
    SENSITIVE_FILENAME_PATTERNS,
    allow_write_subpath,
    build_sandbox_policy,
    compile_seatbelt_profile,
    deny_read_subpath,
    deny_write_subpath,
    escape_seatbelt_path,
)


def _roots(tmp_path, *, with_git: bool = True):
    workspace = tmp_path / "work"
    temp_root = tmp_path / "tmp"
    state_root = tmp_path / "state"
    home = tmp_path / "home"
    for path in (workspace, temp_root, state_root, home):
        path.mkdir(parents=True, exist_ok=True)
    if with_git:
        (workspace / ".git").mkdir(parents=True, exist_ok=True)
        (workspace / ".codex").mkdir(parents=True, exist_ok=True)
    return workspace, temp_root, state_root, home


def _policy(tmp_path, mode=SandboxMode.WORKSPACE_WRITE, **overrides):
    workspace, temp_root, state_root, home = _roots(tmp_path)
    values = {
        "mode": mode,
        "network": SandboxNetworkMode.OFF,
        "workspace": workspace,
        "temp_root": temp_root,
        "state_root": state_root,
        "home": home,
        "private_roots": (),
    }
    values.update(overrides)
    return build_sandbox_policy(**values)


def test_git_dir_is_readable_but_not_writable(tmp_path):
    policy = _policy(tmp_path)
    git_root = policy.git_metadata_roots[0]
    profile = compile_seatbelt_profile(policy)
    assert deny_write_subpath(git_root) in profile
    assert deny_read_subpath(git_root) not in profile


def test_codex_dir_is_metadata_too(tmp_path):
    policy = _policy(tmp_path)
    assert any(root.endswith("/.codex") for root in policy.git_metadata_roots)
    profile = compile_seatbelt_profile(policy)
    for root in policy.git_metadata_roots:
        assert deny_write_subpath(root) in profile


def test_git_file_gitdir_pointer_is_resolved_bounded(tmp_path):
    workspace, temp_root, state_root, home = _roots(tmp_path, with_git=False)
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    (workspace / ".git").write_text(f"gitdir: {metadata}\n", encoding="utf-8")
    (workspace / ".codex").mkdir()
    policy = build_sandbox_policy(
        mode=SandboxMode.WORKSPACE_WRITE,
        network=SandboxNetworkMode.OFF,
        workspace=workspace,
        temp_root=temp_root,
        state_root=state_root,
        home=home,
        private_roots=(),
    )
    assert str(metadata) in policy.git_metadata_roots
    # malformed / escaping 指针 fail closed
    (workspace / ".git").write_text("garbage\n", encoding="utf-8")
    with pytest.raises(ValueError, match="gitdir"):
        build_sandbox_policy(
            mode=SandboxMode.WORKSPACE_WRITE,
            network=SandboxNetworkMode.OFF,
            workspace=workspace,
            temp_root=temp_root,
            state_root=state_root,
            home=home,
            private_roots=(),
        )
    (workspace / ".git").write_text("gitdir: ../escape/../../etc\n", encoding="utf-8")
    with pytest.raises(ValueError, match="gitdir"):
        build_sandbox_policy(
            mode=SandboxMode.WORKSPACE_WRITE,
            network=SandboxNetworkMode.OFF,
            workspace=workspace,
            temp_root=temp_root,
            state_root=state_root,
            home=home,
            private_roots=(),
        )


def test_unreadable_roots_deny_read_and_write(tmp_path):
    sentinel = tmp_path / "sentinel"
    sentinel.mkdir()
    policy = _policy(tmp_path, private_roots=(str(sentinel),))
    profile = compile_seatbelt_profile(policy)
    for path in policy.unreadable_roots:
        assert deny_read_subpath(path) in profile
        assert deny_write_subpath(path) in profile
    assert str(sentinel) in policy.unreadable_roots


def test_sensitive_filename_patterns_are_denied(tmp_path):
    from agent.sandbox.policy import _fnmatch_to_regex

    policy = _policy(tmp_path)
    profile = compile_seatbelt_profile(policy)
    assert set(SENSITIVE_FILENAME_PATTERNS) == {
        ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx",
    }
    for pattern in SENSITIVE_FILENAME_PATTERNS:
        regex = _fnmatch_to_regex(pattern)
        assert f'(deny file-read* (regex #"{regex}"))' in profile, pattern
        assert f'(deny file-write* (regex #"{regex}"))' in profile, pattern


def test_escape_rejects_hostile_paths():
    for hostile in ('a"b', "a\\b", "a\nb", "a\x00b", "a\rb"):
        with pytest.raises(ValueError, match="path"):
            escape_seatbelt_path(hostile)
    assert escape_seatbelt_path("/plain/path") == "/plain/path"


def test_workspace_write_allows_exactly_workspace_and_temp(tmp_path):
    policy = _policy(tmp_path)
    profile = compile_seatbelt_profile(policy)
    assert allow_write_subpath(policy.workspace_root) in profile
    assert allow_write_subpath(policy.temp_root) in profile
    allow_subpaths = [
        line for line in profile.splitlines() if line.startswith("(allow file-write*")
    ]
    assert len(allow_subpaths) == 3  # workspace + temp + /dev/null literal


def test_read_only_compiles_no_workspace_write_allow(tmp_path):
    policy = _policy(tmp_path, mode=SandboxMode.READ_ONLY)
    profile = compile_seatbelt_profile(policy)
    assert allow_write_subpath(policy.workspace_root) not in profile
    allow_subpaths = [
        line for line in profile.splitlines() if line.startswith("(allow file-write*")
    ]
    assert allow_subpaths == ['(allow file-write* (literal "/dev/null"))']


def test_network_off_denies_and_full_does_not(tmp_path):
    off = compile_seatbelt_profile(_policy(tmp_path))
    assert "(deny network*)" in off
    full = compile_seatbelt_profile(_policy(tmp_path, network=SandboxNetworkMode.FULL))
    assert "(deny network*)" not in full


def test_danger_mode_has_no_profile(tmp_path):
    policy = _policy(tmp_path, mode=SandboxMode.DANGER_FULL_ACCESS)
    with pytest.raises(ValueError, match="unconfined"):
        compile_seatbelt_profile(policy)


def test_profile_shape_is_fixed_clause_prefix(tmp_path):
    profile = compile_seatbelt_profile(_policy(tmp_path))
    lines = profile.splitlines()
    assert lines[0] == "(version 1)"
    assert lines[1] == "(allow default)"
    assert lines[2] == "(deny file-write*)"
    assert profile.endswith("\n")
