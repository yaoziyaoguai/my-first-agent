"""017 native composition：自动 qualification 三态 + 唯一 sandbox_exec。

qualified → 恰一个 ``sandbox_exec`` registration（ISOLATED_SANDBOX）；
backend missing/refused/unsupported → readiness/reason 如实，但 registration
仍然注册（danger-full-access 是不依赖 backend 的显式 bypass，confined
命令在 confine 处 fail closed）。注入 fake confiner 是唯一测试替身；没有
local_process fallback、没有 Docker vocabulary。
"""

from __future__ import annotations

from pathlib import Path

from agent.composition import SandboxReadiness, build_sandbox_resources
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
    return build_sandbox_resources(
        workspace=tmp_path / "work",
        state_root=tmp_path / "state",
        captured_path="/usr/bin:/bin",
        confiner=confiner,
    )


def _workspace(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    return work


def test_qualified_registers_exactly_one_sandbox_exec(tmp_path):
    _workspace(tmp_path)
    confiner = FakeConfiner(_qualified())
    resources = _build(tmp_path, confiner)
    assert resources.readiness is SandboxReadiness.READY
    assert resources.reason_code is None
    assert [r.spec.name for r in resources.registrations] == ["sandbox_exec"]
    spec = resources.registrations[0].spec
    assert spec.execution_authority is ExecutionAuthorityClass.ISOLATED_SANDBOX
    # 自动 qualification 恰一次（启动只读探测）
    assert confiner.qualify_calls == 1
    # 唯一替身是注入的 fake confiner；无 local_process fallback
    assert "local_process" not in [r.spec.name for r in resources.registrations]


def test_missing_backend_still_registers_danger_capable_tool(tmp_path):
    _workspace(tmp_path)
    confiner = FakeConfiner(_unavailable("sandbox_exec_missing"))
    resources = _build(tmp_path, confiner)
    assert resources.readiness is SandboxReadiness.TEMPORARILY_UNAVAILABLE
    assert resources.reason_code == "sandbox_exec_missing"
    # danger-full-access 不依赖 backend：registration 仍存在
    assert [r.spec.name for r in resources.registrations] == ["sandbox_exec"]


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
    assert [r.spec.name for r in resources.registrations] == ["sandbox_exec"]


def test_per_invocation_roots_live_outside_state_carveout(tmp_path):
    # policy 冻结四 root 两两不交：temp/home 基座在系统 temp 下的 session
    # 专属目录，不得落入 state_root 的 unreadable carveout。
    import tempfile as _tempfile

    _workspace(tmp_path)
    confiner = FakeConfiner(_qualified())
    build_sandbox_resources(
        workspace=tmp_path / "work",
        state_root=tmp_path / "state",
        captured_path="/usr/bin:/bin",
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
        "workspace", "state_root", "captured_path", "confiner",
    }
    assert signature.parameters["confiner"].default is None
    del SeatbeltConfiner
