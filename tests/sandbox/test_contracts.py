"""017 native sandbox contracts（frozen spec §3–§5）。

closed 三值 mode/network、policy identity digest 绑定、canonical 路径与
carveout 不重叠、enforcement facts 一致性（bypass=unconfined、confined=
seatbelt+hex64 profile digest）。
"""

from __future__ import annotations

import pytest

from agent.runtime.contracts import canonical_json_digest
from agent.sandbox.contracts import (
    ConfinedInvocationV1,
    SandboxBackendIdentityV1,
    SandboxEnforcementFactsV1,
    SandboxMode,
    SandboxNetworkMode,
    SandboxPolicyV1,
)


def _policy(**overrides) -> SandboxPolicyV1:
    from agent.sandbox.policy import build_sandbox_policy

    return build_sandbox_policy(**overrides)


def test_mode_and_network_are_closed_enums():
    assert SandboxMode.READ_ONLY.value == "read-only"
    assert SandboxMode.WORKSPACE_WRITE.value == "workspace-write"
    assert SandboxMode.DANGER_FULL_ACCESS.value == "danger-full-access"
    assert SandboxNetworkMode.OFF.value == "off"
    assert SandboxNetworkMode.FULL.value == "full"
    with pytest.raises(ValueError):
        SandboxMode("container")
    with pytest.raises(ValueError):
        SandboxNetworkMode("allowlist")


def test_policy_identity_digest_binds_every_member(tmp_path):
    workspace = tmp_path / "work"
    temp_root = tmp_path / "tmp"
    state_root = tmp_path / "state"
    home = tmp_path / "home"
    for path in (workspace, temp_root, state_root, home):
        path.mkdir()
    policy = _policy(
        mode=SandboxMode.WORKSPACE_WRITE,
        network=SandboxNetworkMode.OFF,
        workspace=workspace,
        temp_root=temp_root,
        state_root=state_root,
        home=home,
        private_roots=(),
    )
    assert policy.policy_digest == canonical_json_digest(policy.identity_values())
    assert policy.workspace_root != policy.temp_root
    assert policy.writable_roots == (str(workspace), str(temp_root))
    # 私有 root 注入 unreadable carveout
    private = tmp_path / "sentinel"
    private.mkdir()
    with_private = _policy(
        mode=SandboxMode.WORKSPACE_WRITE,
        network=SandboxNetworkMode.OFF,
        workspace=workspace,
        temp_root=temp_root,
        state_root=state_root,
        home=home,
        private_roots=(str(private),),
    )
    assert str(private) in with_private.unreadable_roots
    assert with_private.policy_digest != policy.policy_digest


def test_policy_rejects_noncanonical_and_overlapping_roots(tmp_path):
    workspace = tmp_path / "work"
    temp_root = tmp_path / "tmp"
    state_root = tmp_path / "state"
    home = tmp_path / "home"
    for path in (workspace, temp_root, state_root, home):
        path.mkdir()
    with pytest.raises(ValueError, match="canonical"):
        _policy(
            mode=SandboxMode.WORKSPACE_WRITE,
            network=SandboxNetworkMode.OFF,
            workspace=workspace / ".." / "work",
            temp_root=temp_root,
            state_root=state_root,
            home=home,
            private_roots=(),
        )
    (workspace / "nested-tmp").mkdir()
    with pytest.raises(ValueError, match="overlap"):
        _policy(
            mode=SandboxMode.WORKSPACE_WRITE,
            network=SandboxNetworkMode.OFF,
            workspace=workspace,
            temp_root=workspace / "nested-tmp",
            state_root=state_root,
            home=home,
            private_roots=(),
        )
    (workspace / "st").mkdir()
    with pytest.raises(ValueError, match="overlap"):
        _policy(
            mode=SandboxMode.WORKSPACE_WRITE,
            network=SandboxNetworkMode.OFF,
            workspace=workspace,
            temp_root=temp_root,
            state_root=workspace / "st",
            home=home,
            private_roots=(),
        )
    with pytest.raises(ValueError, match="canonical"):
        _policy(
            mode=SandboxMode.WORKSPACE_WRITE,
            network=SandboxNetworkMode.OFF,
            workspace=workspace,
            temp_root=temp_root,
            state_root=tmp_path / "missing-state",
            home=home,
            private_roots=(),
        )


def test_policy_rejects_symlink_workspace_drift(tmp_path):
    workspace = tmp_path / "work"
    workspace.mkdir()
    (tmp_path / "tmp").mkdir()
    (tmp_path / "state").mkdir()
    (tmp_path / "home").mkdir()
    link = tmp_path / "link-work"
    link.symlink_to(workspace)
    with pytest.raises(ValueError, match="canonical"):
        _policy(
            mode=SandboxMode.WORKSPACE_WRITE,
            network=SandboxNetworkMode.OFF,
            workspace=link,
            temp_root=tmp_path / "tmp",
            state_root=tmp_path / "state",
            home=tmp_path / "home",
            private_roots=(),
        )


def test_read_only_has_no_writable_roots_and_danger_has_no_seatables(tmp_path):
    workspace = tmp_path / "work"
    temp_root = tmp_path / "tmp"
    state_root = tmp_path / "state"
    home = tmp_path / "home"
    for path in (workspace, temp_root, state_root, home):
        path.mkdir()
    common = {
        "workspace": workspace,
        "temp_root": temp_root,
        "state_root": state_root,
        "home": home,
        "private_roots": (),
    }
    read_only = _policy(
        mode=SandboxMode.READ_ONLY, network=SandboxNetworkMode.OFF, **common,
    )
    assert read_only.writable_roots == ()
    danger = _policy(
        mode=SandboxMode.DANGER_FULL_ACCESS,
        network=SandboxNetworkMode.OFF,
        **common,
    )
    assert danger.writable_roots == ()
    assert danger.git_metadata_roots == ()
    assert danger.unreadable_roots == ()


def test_enforcement_facts_coherence():
    confined = SandboxEnforcementFactsV1(
        backend="seatbelt",
        enforcement="confined",
        mode=SandboxMode.WORKSPACE_WRITE,
        network=SandboxNetworkMode.OFF,
        policy_digest="a" * 64,
        profile_digest="b" * 64,
    )
    assert confined.policy_digest == "a" * 64
    bypass = SandboxEnforcementFactsV1(
        backend="none",
        enforcement="unconfined",
        mode=SandboxMode.DANGER_FULL_ACCESS,
        network=SandboxNetworkMode.OFF,
        policy_digest="c" * 64,
        profile_digest="",
    )
    assert bypass.enforcement == "unconfined"
    with pytest.raises(ValueError, match="closed"):
        SandboxEnforcementFactsV1(
            backend="docker",
            enforcement="confined",
            mode=SandboxMode.WORKSPACE_WRITE,
            network=SandboxNetworkMode.OFF,
            policy_digest="a" * 64,
            profile_digest="b" * 64,
        )
    with pytest.raises(ValueError):
        SandboxEnforcementFactsV1(
            backend="seatbelt",
            enforcement="unconfined",
            mode=SandboxMode.DANGER_FULL_ACCESS,
            network=SandboxNetworkMode.OFF,
            policy_digest="a" * 64,
            profile_digest="",
        )
    with pytest.raises(ValueError):
        SandboxEnforcementFactsV1(
            backend="seatbelt",
            enforcement="confined",
            mode=SandboxMode.WORKSPACE_WRITE,
            network=SandboxNetworkMode.OFF,
            policy_digest="a" * 64,
            profile_digest="not-hex",
        )


def test_confined_invocation_normalizes_argv_tuples():
    invocation = ConfinedInvocationV1(
        wrapped_executable="/usr/bin/sandbox-exec",
        wrapped_argv=["sandbox-exec", "-p", "(version 1)"],
        profile="(version 1)\n",
        environment={"HOME": "/tmp/x"},
        enforcement=SandboxEnforcementFactsV1(
            backend="seatbelt",
            enforcement="confined",
            mode=SandboxMode.WORKSPACE_WRITE,
            network=SandboxNetworkMode.OFF,
            policy_digest="a" * 64,
            profile_digest="b" * 64,
        ),
    )
    assert invocation.wrapped_argv == ("sandbox-exec", "-p", "(version 1)")
    with pytest.raises(AttributeError):
        invocation.wrapped_argv = ()  # type: ignore[misc]


def test_backend_identity_digest_binds_all_facts():
    identity = SandboxBackendIdentityV1(
        executable_path="/usr/bin/sandbox-exec",
        platform_system="Darwin",
        platform_release="24.5.0",
        functional_probe_digest="d" * 64,
        probe_profile_digest="e" * 64,
    )
    assert identity.backend_identity_digest == canonical_json_digest(
        {
            "executable_path": "/usr/bin/sandbox-exec",
            "platform_system": "Darwin",
            "platform_release": "24.5.0",
            "functional_probe_digest": "d" * 64,
            "probe_profile_digest": "e" * 64,
        },
    )
