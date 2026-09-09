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
    resolve_private_roots,
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


@pytest.mark.parametrize(
    "mode",
    (SandboxMode.READ_ONLY, SandboxMode.WORKSPACE_WRITE),
)
def test_git_file_gitdir_pointer_is_resolved_bounded(tmp_path, mode):
    workspace, temp_root, state_root, home = _roots(tmp_path, with_git=False)
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    pointer = workspace / ".git"
    codex = workspace / ".codex"
    codex.mkdir()
    policy_digests: set[str] = set()
    for target_spelling in (str(metadata), "../metadata"):
        pointer.write_text(f"gitdir: {target_spelling}\n", encoding="utf-8")
        policy = build_sandbox_policy(
            mode=mode,
            network=SandboxNetworkMode.OFF,
            workspace=workspace,
            temp_root=temp_root,
            state_root=state_root,
            home=home,
            private_roots=(),
        )
        assert policy.git_metadata_roots == (
            str(pointer),
            str(metadata),
            str(codex),
        )
        profile = compile_seatbelt_profile(policy)
        for protected in (str(pointer), str(metadata), str(codex)):
            assert deny_write_subpath(protected) in profile
            assert deny_read_subpath(protected) not in profile
        expected_writable = (
            (str(workspace), str(temp_root))
            if mode is SandboxMode.WORKSPACE_WRITE
            else ()
        )
        assert policy.writable_roots == expected_writable
        policy_digests.add(policy.policy_digest)
    assert len(policy_digests) == 1

    # malformed / escaping 指针 fail closed
    pointer.write_text("garbage\n", encoding="utf-8")
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
    pointer.write_bytes(b"x" * 257)
    with pytest.raises(ValueError, match="exceeds bounded size"):
        build_sandbox_policy(
            mode=mode,
            network=SandboxNetworkMode.OFF,
            workspace=workspace,
            temp_root=temp_root,
            state_root=state_root,
            home=home,
            private_roots=(),
        )
    pointer.write_text("gitdir: ../missing-metadata\n", encoding="utf-8")
    with pytest.raises(ValueError, match="target does not resolve"):
        build_sandbox_policy(
            mode=mode,
            network=SandboxNetworkMode.OFF,
            workspace=workspace,
            temp_root=temp_root,
            state_root=state_root,
            home=home,
            private_roots=(),
        )
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    pointer.write_text(f"gitdir: {outside}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes the workspace parent"):
        build_sandbox_policy(
            mode=mode,
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


def test_nonexistent_private_root_is_preserved_without_creating_it(tmp_path):
    missing = tmp_path / "host-home" / ".ssh"
    missing.parent.mkdir()
    policy = _policy(tmp_path, private_roots=(str(missing),))
    profile = compile_seatbelt_profile(policy)
    assert str(missing) in policy.unreadable_roots
    assert deny_read_subpath(str(missing)) in profile
    assert deny_write_subpath(str(missing)) in profile
    assert not missing.exists()

    before_digest = policy.policy_digest
    missing.mkdir()
    after = _policy(tmp_path, private_roots=(str(missing),))
    assert after.policy_digest == before_digest


def test_existing_or_broken_private_root_symlink_is_rejected(tmp_path):
    target = tmp_path / "private-target"
    target.mkdir()
    existing_link = tmp_path / "private-link"
    existing_link.symlink_to(target, target_is_directory=True)
    broken_link = tmp_path / "broken-private-link"
    broken_link.symlink_to(tmp_path / "missing-target", target_is_directory=True)

    for link in (existing_link, broken_link):
        with pytest.raises(ValueError, match="private_roots"):
            _policy(tmp_path, private_roots=(str(link),))


@pytest.mark.parametrize(
    "entry",
    ("../escape", "/absolute-replacement", "nested/../../escape", "bad\npath"),
)
def test_closed_private_roots_reject_non_relative_or_escaping_entries(
    tmp_path,
    entry,
):
    home = tmp_path / "host-home"
    home.mkdir()
    with pytest.raises(ValueError, match="private_roots"):
        resolve_private_roots(home, (entry,))


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


def test_danger_full_network_bypass_has_no_profile(tmp_path):
    # 保留行为：danger+full 是 exact-command unconfined bypass，没有 profile。
    policy = _policy(
        tmp_path, mode=SandboxMode.DANGER_FULL_ACCESS,
        network=SandboxNetworkMode.FULL,
    )
    with pytest.raises(ValueError, match="unconfined"):
        compile_seatbelt_profile(policy)


def test_danger_network_off_compiles_exact_network_only_profile(tmp_path):
    # Oracle 审计方案 1：danger+off 只叠网络限制，绝不落入 filesystem 模板。
    policy = _policy(tmp_path, mode=SandboxMode.DANGER_FULL_ACCESS)
    profile = compile_seatbelt_profile(policy)
    assert profile == "(version 1)\n(allow default)\n(deny network*)\n"
    assert "file-write" not in profile
    assert "subpath" not in profile
    assert "regex" not in profile


def test_profile_shape_is_fixed_clause_prefix(tmp_path):
    profile = compile_seatbelt_profile(_policy(tmp_path))
    lines = profile.splitlines()
    assert lines[0] == "(version 1)"
    assert lines[1] == "(allow default)"
    assert lines[2] == "(deny file-write*)"
    assert profile.endswith("\n")


@pytest.mark.parametrize(
    "mode",
    (SandboxMode.READ_ONLY, SandboxMode.WORKSPACE_WRITE),
)
def test_gitdir_pointer_through_symlink_chain_binds_final_target_only(tmp_path, mode):
    """r18 分级观察：gitfile 经多跳 symlink 解析，policy 只保护最终 resolved 路径。

    依据 CURRENT_CAPABILITY_STATUS 声明的未支持边界（gitfile symlink/TOCTOU）：
    pointer 与最终真实 target 可读禁写；中间跳 symlink 不入保护集，可被
    workspace 内已批准写入替换属于已声明 limitation，不是本轮修复对象。
    本测试固定当前行为，防止该边界被静默改变。
    """
    workspace, temp_root, state_root, home = _roots(tmp_path, with_git=False)
    real_git = tmp_path / "linked-metadata"
    real_git.mkdir()
    hop_b = tmp_path / "hop-b"
    hop_b.symlink_to(real_git, target_is_directory=True)
    hop_a = tmp_path / "hop-a"
    hop_a.symlink_to(hop_b, target_is_directory=True)
    pointer = workspace / ".git"
    pointer.write_text(f"gitdir: {hop_a}\n", encoding="utf-8")
    policy = build_sandbox_policy(
        mode=mode,
        network=SandboxNetworkMode.OFF,
        workspace=workspace,
        temp_root=temp_root,
        state_root=state_root,
        home=home,
        private_roots=(),
    )
    resolved = str(real_git.resolve())
    assert resolved in policy.git_metadata_roots
    assert str(pointer) in policy.git_metadata_roots
    profile = compile_seatbelt_profile(policy)
    for protected in (str(pointer), resolved):
        assert deny_write_subpath(protected) in profile
        assert deny_read_subpath(protected) not in profile
    # 声明 limitation 的固定：中间跳不进 git metadata 保护集。
    assert str(hop_a) not in policy.git_metadata_roots
    assert str(hop_b) not in policy.git_metadata_roots


def test_gitdir_pointer_symlink_chain_escaping_parent_fails_closed(tmp_path):
    """r18 分级观察：多跳链最终解析到 workspace parent 之外时拒绝构建 policy。"""
    workspace, temp_root, state_root, home = _roots(tmp_path, with_git=False)
    escaped = tmp_path.parent / "escaped-metadata"
    escaped.mkdir()
    try:
        hop = tmp_path / "escape-hop"
        hop.symlink_to(escaped, target_is_directory=True)
        pointer = workspace / ".git"
        pointer.write_text(f"gitdir: {hop}\n", encoding="utf-8")
        with pytest.raises(ValueError, match="escapes the workspace parent"):
            build_sandbox_policy(
                mode=SandboxMode.WORKSPACE_WRITE,
                network=SandboxNetworkMode.OFF,
                workspace=workspace,
                temp_root=temp_root,
                state_root=state_root,
                home=home,
                private_roots=(),
            )
    finally:
        escaped.rmdir()
