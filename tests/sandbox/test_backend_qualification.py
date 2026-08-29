"""017 native backend qualification（macOS Seatbelt，只读 fail closed）。

qualification 只做一次 bounded functional probe（minimal profile +
``/usr/bin/true``），绝不执行用户命令、不安装/启动/登录任何服务、不降级。
closed reasons：qualified / unsupported_platform / sandbox_exec_missing /
seatbelt_profile_refused / functional_probe_failed。
"""

from __future__ import annotations

import pytest

from agent.sandbox.qualification import (
    MINIMAL_PROBE_PROFILE,
    PROBE_OUTPUT_CAP_BYTES,
    ProbeResult,
    SeatbeltCommandRunner,
)
from agent.sandbox.seatbelt import SeatbeltConfiner


class FakeRunner:
    def __init__(self, *, result: ProbeResult | None = None, error=None) -> None:
        self.default = result or ProbeResult(
            returncode=0, stdout=b"", stderr=b"", timed_out=False,
        )
        self.error = error
        self.calls: list[tuple] = []

    def run(self, argv, *, cwd, env, timeout):  # noqa: ANN001, ANN202
        self.calls.append((tuple(argv), cwd, dict(env), timeout))
        if self.error is not None:
            raise self.error
        return self.default


def test_qualified_identity_binds_canonical_binary_platform_and_probe():
    fake = FakeRunner()
    confiner = SeatbeltConfiner(
        runner=fake,
        platform_system="Darwin",
        platform_release="24.5.0",
    )
    report = confiner.qualify()
    assert report.available is True
    assert report.reason_code == "qualified"
    assert report.backend_identity is not None
    assert report.backend_identity.executable_path == "/usr/bin/sandbox-exec"
    assert report.backend_identity.platform_system == "Darwin"
    assert report.backend_identity.platform_release == "24.5.0"
    assert report.backend_identity.functional_probe_digest
    assert report.backend_identity.probe_profile_digest


def test_qualification_probe_is_bounded_and_never_a_user_command():
    fake = FakeRunner()
    confiner = SeatbeltConfiner(runner=fake, platform_system="Darwin")
    confiner.qualify()
    assert fake.calls == [
        (
            ("/usr/bin/sandbox-exec", "-p", MINIMAL_PROBE_PROFILE, "/usr/bin/true"),
            None,
            {},
            pytest.approx(5.0),
        ),
    ]


def test_qualification_is_cached_per_confiner_instance():
    fake = FakeRunner()
    confiner = SeatbeltConfiner(runner=fake, platform_system="Darwin")
    first = confiner.qualify()
    second = confiner.qualify()
    assert first is second
    assert len(fake.calls) == 1


def test_unsupported_platform_is_closed_and_spawns_nothing():
    fake = FakeRunner()
    confiner = SeatbeltConfiner(runner=fake, platform_system="Linux")
    report = confiner.qualify()
    assert report.available is False
    assert report.reason_code == "unsupported_platform"
    assert report.backend_identity is None
    assert fake.calls == []


def test_missing_binary_fails_closed_without_spawn():
    fake = FakeRunner()
    confiner = SeatbeltConfiner(
        binary="/definitely/not/sandbox-exec",
        runner=fake,
        platform_system="Darwin",
    )
    report = confiner.qualify()
    assert report.available is False
    assert report.reason_code == "sandbox_exec_missing"
    assert fake.calls == []


def test_profile_refusal_is_distinguished_from_probe_failure():
    refused = SeatbeltConfiner(
        runner=FakeRunner(
            result=ProbeResult(1, b"", b"profile syntax error", False),
        ),
        platform_system="Darwin",
    )
    assert refused.qualify().reason_code == "seatbelt_profile_refused"

    timed_out = SeatbeltConfiner(
        runner=FakeRunner(
            result=ProbeResult(None, b"", b"", timed_out=True),
        ),
        platform_system="Darwin",
    )
    assert timed_out.qualify().reason_code == "functional_probe_failed"

    signaled = SeatbeltConfiner(
        runner=FakeRunner(
            result=ProbeResult(-9, b"", b"killed", False),
        ),
        platform_system="Darwin",
    )
    assert signaled.qualify().reason_code == "functional_probe_failed"

    oversize = SeatbeltConfiner(
        runner=FakeRunner(
            result=ProbeResult(0, b"x" * (PROBE_OUTPUT_CAP_BYTES + 1), b"", False),
        ),
        platform_system="Darwin",
    )
    assert oversize.qualify().reason_code == "functional_probe_failed"


def test_production_runner_is_bounded_and_argument_vector_only():
    runner = SeatbeltCommandRunner()
    assert hasattr(runner, "run")
    # 真实探测在 Task 9 E3 才执行；这里只锁接口形状（argv/cwd/env/timeout 关键字）
    import inspect

    signature = inspect.signature(runner.run)
    assert set(signature.parameters) - {"self"} == {"argv", "cwd", "env", "timeout"}
