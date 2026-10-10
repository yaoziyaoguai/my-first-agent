"""017 native composition：自动 qualification 三态 + sandbox_exec 与 shell_exec。

qualified → 静态注册恰 ``sandbox_exec`` 与 ``shell_exec``（稳定顺序，均
ISOLATED_SANDBOX）；backend missing/refused/unsupported → readiness/reason
如实，但两个 registration 仍然注册（danger-full-access 是不依赖 backend 的
显式 bypass，confined 命令在 confine 处 fail closed）。注入 fake confiner
是唯一测试替身；qualification 恰一次、没有 local_process fallback、
没有 Docker vocabulary。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.composition import (
    HOST_HOME_PRIVATE_ROOTS,
    SandboxReadiness,
    build_sandbox_resources,
)
from agent.runtime.contracts import ExecutionAuthorityClass
from agent.sandbox.contracts import SandboxQualificationV1


class FakeConfiner:
    """protocol 形状的注入替身：只记录调用，永不 spawn。"""

    def __init__(self, report: SandboxQualificationV1) -> None:
        self.report = report
        self.qualify_calls = 0
        self.confine_calls: list[tuple] = []

    def qualify(self) -> SandboxQualificationV1:
        self.qualify_calls += 1
        return self.report

    def confine(self, command, policy, environment):  # noqa: ANN001, ANN202
        self.confine_calls.append((command, policy, dict(environment)))
        raise AssertionError("composition tests never execute commands")


def _qualified() -> SandboxQualificationV1:
    from agent.sandbox.contracts import SandboxBackendIdentityV1

    return SandboxQualificationV1(
        True,
        "qualified",
        backend_identity=SandboxBackendIdentityV1(
            executable_path="/usr/bin/sandbox-exec",
            platform_system="Darwin",
            platform_release="24.5.0",
            functional_probe_digest="a" * 64,
            probe_profile_digest="b" * 64,
        ),
    )


def _unavailable(reason: str) -> SandboxQualificationV1:
    return SandboxQualificationV1(False, reason)


def _build(tmp_path: Path, confiner) -> object:
    host_home = tmp_path / "host-home"
    host_home.mkdir(exist_ok=True)
    return build_sandbox_resources(
        workspace=tmp_path / "work",
        state_root=tmp_path / "state",
        captured_path="/usr/bin:/bin",
        host_home=host_home,
        confiner=confiner,
    )


def _workspace(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    return work


def test_qualified_registers_sandbox_and_shell_exec(tmp_path):
    _workspace(tmp_path)
    confiner = FakeConfiner(_qualified())
    resources = _build(tmp_path, confiner)
    assert resources.readiness is SandboxReadiness.READY
    assert resources.reason_code is None
    assert [r.spec.name for r in resources.registrations] == [
        "sandbox_exec",
        "shell_exec",
    ]
    for registration in resources.registrations:
        spec = registration.spec
        assert spec.execution_authority is ExecutionAuthorityClass.ISOLATED_SANDBOX
    # 自动 qualification 恰一次（启动只读探测，两工具共享同一探测）
    assert confiner.qualify_calls == 1
    # 唯一替身是注入的 fake confiner；无 local_process fallback
    assert "local_process" not in [r.spec.name for r in resources.registrations]


def test_missing_backend_still_registers_danger_capable_tools(tmp_path):
    _workspace(tmp_path)
    confiner = FakeConfiner(_unavailable("sandbox_exec_missing"))
    resources = _build(tmp_path, confiner)
    assert resources.readiness is SandboxReadiness.TEMPORARILY_UNAVAILABLE
    assert resources.reason_code == "sandbox_exec_missing"
    # danger-full-access 不依赖 backend：两个 registration 仍存在
    assert [r.spec.name for r in resources.registrations] == [
        "sandbox_exec",
        "shell_exec",
    ]


def test_refused_backend_maps_to_temporarily_unavailable(tmp_path):
    _workspace(tmp_path)
    confiner = FakeConfiner(_unavailable("seatbelt_profile_refused"))
    resources = _build(tmp_path, confiner)
    assert resources.readiness is SandboxReadiness.TEMPORARILY_UNAVAILABLE
    assert resources.reason_code == "seatbelt_profile_refused"
    confiner_probe = FakeConfiner(_unavailable("functional_probe_failed"))
    assert _build(tmp_path, confiner_probe).reason_code == "functional_probe_failed"


def test_unsupported_platform_is_distinct_state(tmp_path):
    _workspace(tmp_path)
    confiner = FakeConfiner(_unavailable("unsupported_platform"))
    resources = _build(tmp_path, confiner)
    assert resources.readiness is SandboxReadiness.UNSUPPORTED
    assert resources.reason_code == "unsupported_platform"
    # backend unsupported 也不在 composition 裁剪工具：confined modes
    # 执行时 fail closed，danger-full-access 仍有明确既有语义。
    assert [r.spec.name for r in resources.registrations] == [
        "sandbox_exec",
        "shell_exec",
    ]


def test_per_invocation_roots_live_outside_state_carveout(tmp_path):
    # policy 冻结四 root 两两不交：temp/home 基座在系统 temp 下的 session
    # 专属目录，不得落入 state_root 的 unreadable carveout。
    import tempfile as _tempfile

    _workspace(tmp_path)
    host_home = tmp_path / "host-home"
    host_home.mkdir()
    confiner = FakeConfiner(_qualified())
    build_sandbox_resources(
        workspace=tmp_path / "work",
        state_root=tmp_path / "state",
        captured_path="/usr/bin:/bin",
        host_home=host_home,
        confiner=confiner,
    )
    base_name = (
        "first-agent-sbx-"
        + __import__("hashlib").sha256(
            str(tmp_path / "state").encode(),
        ).hexdigest()[:12]
    )
    base = __import__("pathlib").Path(_tempfile.gettempdir()) / base_name
    assert (base / "temp").is_dir()
    assert (base / "home").is_dir()
    assert not (base / "temp").is_relative_to(tmp_path / "state")


def test_default_confiner_construction_is_lazy_and_backend_safe():
    # 默认路径构造 SeatbeltConfiner（探测延迟到 build 内一次只读 probe）；
    # 本测试不触发真实探测——仅验证符号存在与签名形状。
    import inspect

    from agent.composition import build_sandbox_resources as build
    from agent.sandbox.seatbelt import SeatbeltConfiner

    signature = inspect.signature(build)
    assert set(signature.parameters) - {"self"} == {
        "workspace", "state_root", "captured_path", "host_home", "confiner",
    }
    assert signature.parameters["host_home"].default is inspect.Parameter.empty
    assert signature.parameters["confiner"].default is None
    del SeatbeltConfiner


def test_default_composition_passes_one_closed_private_root_tuple_to_both_tools(
    tmp_path,
    monkeypatch,
):
    assert HOST_HOME_PRIVATE_ROOTS == (
        ".aws",
        ".claude",
        ".codex",
        ".config",
        ".docker",
        ".gnupg",
        ".kube",
        ".opencode",
        ".ssh",
        ".ua",
        ".git-credentials",
        ".netrc",
        ".npmrc",
        ".pypirc",
    )
    workspace = _workspace(tmp_path)
    state_root = tmp_path / "state"
    host_home = tmp_path / "host-home"
    state_root.mkdir()
    host_home.mkdir()
    captured: dict[str, tuple] = {}

    from agent.sandbox import shell as sandbox_shell
    from agent.sandbox import tools as sandbox_tools

    original_sandbox = sandbox_tools.build_sandbox_exec_registration
    original_shell = sandbox_shell.build_shell_exec_registration

    def capture_sandbox(**kwargs):  # noqa: ANN003, ANN202
        captured["sandbox_exec"] = kwargs["private_roots"]
        return original_sandbox(**kwargs)

    def capture_shell(**kwargs):  # noqa: ANN003, ANN202
        captured["shell_exec"] = kwargs["private_roots"]
        return original_shell(**kwargs)

    monkeypatch.setattr(sandbox_tools, "build_sandbox_exec_registration", capture_sandbox)
    monkeypatch.setattr(sandbox_shell, "build_shell_exec_registration", capture_shell)

    build_sandbox_resources(
        workspace=workspace,
        state_root=state_root,
        captured_path="/usr/bin:/bin",
        host_home=host_home,
        confiner=FakeConfiner(_qualified()),
    )

    expected = tuple(str(host_home / entry) for entry in HOST_HOME_PRIVATE_ROOTS)
    assert captured == {"sandbox_exec": expected, "shell_exec": expected}
    assert not (host_home / ".ssh").exists()
    assert not (host_home / ".aws").exists()


def test_invalid_or_overlapping_host_home_fails_composition_closed(tmp_path):
    workspace = _workspace(tmp_path)
    state_root = tmp_path / "state"
    state_root.mkdir()
    regular_file = tmp_path / "not-a-home"
    regular_file.write_text("fixture", encoding="utf-8")
    real_home = tmp_path / "real-home"
    real_home.mkdir()
    symlink_home = tmp_path / "symlink-home"
    symlink_home.symlink_to(real_home, target_is_directory=True)

    for invalid in (tmp_path / "missing-home", regular_file, symlink_home):
        with pytest.raises(ValueError, match="host_home"):
            build_sandbox_resources(
                workspace=workspace,
                state_root=state_root,
                captured_path="/usr/bin:/bin",
                host_home=invalid,
                confiner=FakeConfiner(_qualified()),
            )

    protected_workspace = real_home / ".ssh" / "project"
    protected_workspace.mkdir(parents=True)
    with pytest.raises(ValueError, match="overlap"):
        build_sandbox_resources(
            workspace=protected_workspace,
            state_root=state_root,
            captured_path="/usr/bin:/bin",
            host_home=real_home,
            confiner=FakeConfiner(_qualified()),
        )

    enclosing_workspace = tmp_path / "enclosing-workspace"
    nested_home = enclosing_workspace / "host-home"
    nested_home.mkdir(parents=True)
    with pytest.raises(ValueError, match="overlap"):
        build_sandbox_resources(
            workspace=enclosing_workspace,
            state_root=state_root,
            captured_path="/usr/bin:/bin",
            host_home=nested_home,
            confiner=FakeConfiner(_qualified()),
        )
