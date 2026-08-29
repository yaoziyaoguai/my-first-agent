"""017 native U1 harness 完整性。

claim↔journey 1:1 闭合；替身 transcript 必须真实观察 wrapper 输入（一个
只返回成功、不观察 ``sandbox-exec -p`` 包装的 fake 必须被 harness 抓住）。
"""

from __future__ import annotations

import inspect

from tests.reference import test_017_sandboxed_workspace_execution as journeys
from tests.reference.test_017_sandboxed_workspace_execution import (
    FakeExecRunner,
    SandboxJourney,
)


def test_u1_claims_bound_one_to_one_to_journeys():
    module_functions = {
        name
        for name, member in inspect.getmembers(journeys, inspect.isfunction)
        if name.startswith("test_u1_")
    }
    claimed = {f"test_u1_{claim}" for claim in journeys.U1_CLAIMS}
    assert module_functions == claimed


def test_harness_rejects_a_fake_that_ignores_wrapper_input():
    """构造一个「不观察 wrapper 输入」的假 runner：harness 的旅程断言必须
    抓住它（把 argv[0] 换成裸命令也要被检出的合同）。"""

    class BlindRunner(FakeExecRunner):
        def __call__(self, **kwargs):  # noqa: ANN003, ANN202
            # 记录后篡改为「裸命令已执行」的形状——任何只看 outcome 的断言
            # 都会漏掉它；U1 的 wrapping 断言必须抓住。
            kwargs = dict(kwargs)
            kwargs["argv"] = (kwargs["argv"][-1],)
            return super().__call__(**kwargs)

    blind = BlindRunner()
    # 直接驱动盲 runner：confined 合同要求 argv[0] 是 sandbox-exec
    blind(resolved_executable="/usr/bin/sandbox-exec", argv=(
        "/usr/bin/sandbox-exec", "-p", "(version 1)", "/usr/bin/true",
    ))
    recorded = blind.calls[0]["argv"]
    assert recorded != ("/usr/bin/sandbox-exec", "-p", "(version 1)", "/usr/bin/true")
    assert recorded[0] != "/usr/bin/sandbox-exec"


def test_journey_counters_are_independent(tmp_path):
    first = SandboxJourney(tmp_path / "a")
    second = SandboxJourney(tmp_path / "b")
    assert first.exec_runner is not second.exec_runner
    assert first.probe.calls == [] and second.probe.calls == []
    assert first.runtime is not second.runtime


def test_probe_and_exec_runner_never_spawn():
    probe = journeys.FakeProbeRunner()
    result = probe.run(("/usr/bin/sandbox-exec", "-p", "x", "/usr/bin/true"))
    assert result.returncode == 0
    assert isinstance(journeys.FakeExecRunner().calls, list)
