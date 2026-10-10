"""S3-A/B（DU-20/21/22）：本地旅程驱动器的控制与清理合同测试。

不启动真实 Chromium：journey 函数与子进程启动都被测试替身替换，只验证
_run_bounded 的控制/协议/清理判定与 _JourneyCleanup 的有界聚合语义。
"""

from __future__ import annotations

import contextlib
import importlib.util
import subprocess  # noqa: F401
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "f2_f3_local_browser_journeys_under_test",
        ROOT / "scripts/f2_f3_local_browser_journeys.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def f2f3():
    return _load_module()


def test_journey_cleanup_owner_reverse_once_and_aggregates(f2f3) -> None:
    """DU-20：逆序、每 callback 最多一次、一个抛错仍尝试剩余；
    以 (generation, index, error_type) 聚合有界失败。"""

    calls: list[str] = []
    owner = f2f3._JourneyCleanup("gen1")

    def ok_a():
        calls.append("a")

    def boom():
        calls.append("boom")
        raise RuntimeError("cleanup exploded")

    def ok_c():
        calls.append("c")

    owner.register(ok_a)
    owner.register(boom)
    owner.register(ok_c)
    failures = owner.close()
    assert calls == ["c", "boom", "a"], "reverse order, no skip on failure"
    assert owner.close() == failures, "at most once per callback"
    assert failures == [
        {"generation": "gen1", "index": 1, "error_type": "RuntimeError"}
    ]
    assert "cleanup exploded" not in str(failures), "no raw exception content"


def test_run_bounded_rejects_bad_budget_before_launch(f2f3, tmp_path, monkeypatch) -> None:
    """DU-22：NaN/Inf/非正 budget 在启动前拒绝（不发子进程）。"""

    launched = []

    class _NoLaunch:
        def __getattr__(self, name):  # noqa: ANN204
            raise AssertionError("subprocess must not launch for invalid budget")

    def _fake_popen(*args, **kwargs):  # noqa: ANN002, ANN003
        launched.append(1)
        raise AssertionError("Popen must not be called for invalid budget")

    monkeypatch.setattr(f2f3.subprocess, "Popen", _fake_popen)
    for bad in (float("nan"), float("inf"), 0, -5):
        result = f2f3._run_bounded(
            "f2", tmp_path, budget_seconds=bad
        )
        assert result["passed"] is False
        assert "budget_not_finite" in result["failure_codes"]
    assert launched == []


def test_run_bounded_timeout_latches_and_terminates_owned_group(
    f2f3, tmp_path, monkeypatch
) -> None:
    """DU-21：预算到期锁存 timeout；cooperative 宽限后仅对本次 verified
    group 有界 terminate；无 child 清理报告时保守 cleanup=False。"""

    # 注入较小常量（合同允许测试注入较小常量，不真等 143s）。
    monkeypatch.setattr(f2f3, "_COOPERATIVE_CLEANUP_SECONDS", 0.5)
    monkeypatch.setattr(f2f3, "_TERM_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_KILL_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_POST_KILL_VERIFY_SECONDS", 0.5)

    # 真子进程：忽略 stdin EOF，睡眠；被 terminate_group 杀掉即证明有界停止。
    sleeper_code = "import time; time.sleep(60)"
    child = subprocess.Popen(
        [sys.executable, "-c", sleeper_code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    class _StubProc:
        def __init__(self, real) -> None:
            self._real = real
            self.pid = real.pid
            self.stdin = real.stdin
            self.stdout = real.stdout
            self.stderr = real.stderr

        def poll(self):  # noqa: ANN201
            return self._real.poll()

        def wait(self, timeout=None):  # noqa: ANN001, ANN201
            return self._real.wait(timeout=timeout)

    shadow = types.SimpleNamespace(
        Popen=lambda *a, _child=child, **k: _StubProc(_child),
        TimeoutExpired=subprocess.TimeoutExpired,
        PIPE=subprocess.PIPE,
    )
    monkeypatch.setattr(f2f3, "subprocess", shadow)

    base = tmp_path / "journey-base"
    base.mkdir()
    started = time.monotonic()
    result = f2f3._run_bounded("f2", base, budget_seconds=0.5)
    elapsed = time.monotonic() - started

    assert result["timeout"] is True
    assert result["passed"] is False
    assert "work_budget_timeout" in result["failure_codes"]
    assert result["resource_cleanup_confirmed"] is False
    # worker_terminated：子进程已 reap 且 group 消失。
    assert result["worker_terminated"] is True
    # 控制等待有界：budget + coop + term/kill/verify（注入常量后 < 5s）。
    assert elapsed < 15, f"control wait exceeded bound: {elapsed:.1f}s"
    assert result["retained_base"] == str(base)


def test_run_bounded_protocol_failures_fail_bounded(f2f3, tmp_path, monkeypatch) -> None:
    """DU-22：child 异常/缺记录/重复记录/坏 JSON/缺字段/类型错全部有界失败。"""

    monkeypatch.setattr(f2f3, "_COOPERATIVE_CLEANUP_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_TERM_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_KILL_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_POST_KILL_VERIFY_SECONDS", 0.5)

    real_popen = subprocess.Popen
    cases = {
        "no_record": "",
        "bad_json": "definitely not json\n",
        "two_records": (
            '{"journey":"f2","target_checks_passed":true,'
            '"resource_cleanup_confirmed":true,"failure_codes":[],"details":{}}\n'
            '{"journey":"f2","target_checks_passed":true,'
            '"resource_cleanup_confirmed":true,"failure_codes":[],"details":{}}\n'
        ),
        "missing_fields": '{"journey":"f2"}\n',
        "bad_types": (
            '{"journey":"f2","target_checks_passed":"yes",'
            '"resource_cleanup_confirmed":true,"failure_codes":[],"details":{}}\n'
        ),
    }
    for name, payload in cases.items():
        child = real_popen(
            [sys.executable, "-c", f"import sys; sys.stdout.write({payload!r})"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

        class _StubProc:
            def __init__(self, real) -> None:
                self._real = real
                self.pid = real.pid
                self.stdin = real.stdin
                self.stdout = real.stdout
                self.stderr = real.stderr

            def poll(self):  # noqa: ANN201
                return self._real.poll()

            def wait(self, timeout=None):  # noqa: ANN001, ANN201
                return self._real.wait(timeout=timeout)

        current = child

        def _popen_stub(*_a, _current=current, **_k):
            return _StubProc(_current)

        shadow = types.SimpleNamespace(
            Popen=_popen_stub,
            TimeoutExpired=subprocess.TimeoutExpired,
            PIPE=subprocess.PIPE,
        )
        monkeypatch.setattr(f2f3, "subprocess", shadow)
        result = f2f3._run_bounded("f2", tmp_path, budget_seconds=5.0)
        child.wait(timeout=5)
        for stream in (child.stdout, child.stderr):
            if stream and not stream.closed:
                stream.close()
        assert result["passed"] is False, name
        assert result["resource_cleanup_confirmed"] is False, name
        assert result["worker_terminated"] is True, name
        assert any(
            code.startswith("child_protocol_") or code == "child_non_json_output"
            for code in result["failure_codes"]
        ), (name, result["failure_codes"])


def test_group_gone_does_not_prove_independent_session_descendant_cleaned(
    f2f3, tmp_path, monkeypatch
) -> None:
    """DU-21：拥有独立 session 的测试后代反例——外层 group 停止不等于它消失；
    测试用精确所有权在 finally 清掉自己的后代，不为证明泄漏留下新泄漏。"""

    monkeypatch.setattr(f2f3, "_COOPERATIVE_CLEANUP_SECONDS", 0.3)
    monkeypatch.setattr(f2f3, "_TERM_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_KILL_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_POST_KILL_VERIFY_SECONDS", 0.5)

    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess, sys, time; subprocess.Popen([sys.executable, "
            "'-c', 'import time; time.sleep(30)'], start_new_session=True); "
            "time.sleep(60)",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    from agent.process.group import verified_group_identity

    descendant_pid = None
    import contextlib
    import os
    import signal

    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and descendant_pid is None:
            probe = subprocess.run(
                ["pgrep", "-P", str(child.pid)],
                capture_output=True,
                text=True,
            )
            if probe.stdout.strip():
                descendant_pid = int(probe.stdout.strip().split()[0])
            time.sleep(0.05)
        assert descendant_pid is not None, "test descendant must exist"
        descendant_pgid = verified_group_identity(descendant_pid)

        class _StubProc:
            def __init__(self, real) -> None:
                self._real = real
                self.pid = real.pid
                self.stdin = real.stdin
                self.stdout = real.stdout
                self.stderr = real.stderr

            def poll(self):  # noqa: ANN201
                return self._real.poll()

            def wait(self, timeout=None):  # noqa: ANN001, ANN201
                return self._real.wait(timeout=timeout)

        monkeypatch.setattr(
            f2f3.subprocess, "Popen", lambda *a, **k: _StubProc(child)
        )
        result = f2f3._run_bounded("f2", tmp_path, budget_seconds=0.5)
        # 外层 group 已终止（worker_terminated），但独立 session 的后代仍在。
        assert result["worker_terminated"] is True
        assert result["passed"] is False
        os.kill(descendant_pid, 0)  # 后代仍存活 = 反例成立
        del descendant_pgid
    finally:
        # 测试自己用精确所有权清理后代与 child（保留目录中不残留活进程）。
        import os
        import signal

        for pid in (descendant_pid, child.pid):
            if pid is None:
                continue
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
        child.wait(timeout=5)
        for stream in (child.stdout, child.stderr):
            if stream and not stream.closed:
                stream.close()


def test_run_bounded_stdout_overflow_fails_bounded(f2f3, tmp_path) -> None:
    """DU-22 子条件（2026-10-10 审计补证）：子进程 stdout 超 1 MiB 上限
    → output_limit 失败码 + 有界收尾（worker 终止、目录保留、不无限读取）。"""

    real_popen = subprocess.Popen
    flood = (
        "import sys\n"
        "sys.stdout.write('x' * (1300 * 1024))\n"
        "sys.stdout.flush()\n"
        "import time\ntime.sleep(30)\n"
    )
    child = real_popen(
        [sys.executable, "-c", flood],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    class _StubProc:
        def __init__(self, real) -> None:
            self._real = real
            self.pid = real.pid
            self.stdin = real.stdin
            self.stdout = real.stdout
            self.stderr = real.stderr

        def poll(self):  # noqa: ANN201
            return self._real.poll()

        def wait(self, timeout=None):  # noqa: ANN001, ANN201
            return self._real.wait(timeout=timeout)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        f2f3.subprocess,
        "Popen",
        lambda *a, _c=child, **k: _StubProc(_c),
    )
    try:
        result = f2f3._run_bounded("f2", tmp_path, budget_seconds=10.0)
    finally:
        monkey.undo()
        with contextlib.suppress(subprocess.TimeoutExpired):
            child.wait(timeout=5)
        for stream in (child.stdout, child.stderr):
            if stream and not stream.closed:
                stream.close()
    assert result["passed"] is False
    assert "output_limit" in result["failure_codes"], result["failure_codes"]
    assert result["worker_terminated"] is True
    assert result["resource_cleanup_confirmed"] is False
    assert result["retained_base"] == str(tmp_path)


def test_run_bounded_stderr_overflow_fails_bounded(f2f3, tmp_path) -> None:
    """DU-22 子条件：子进程 stderr 超 64 KiB 上限 → 同一有界失败路径。"""

    real_popen = subprocess.Popen
    flood = (
        "import sys, time\n"
        "sys.stderr.write('e' * (70 * 1024))\n"
        "sys.stderr.flush()\n"
        "time.sleep(30)\n"
    )
    child = real_popen(
        [sys.executable, "-c", flood],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    class _StubProc:
        def __init__(self, real) -> None:
            self._real = real
            self.pid = real.pid
            self.stdin = real.stdin
            self.stdout = real.stdout
            self.stderr = real.stderr

        def poll(self):  # noqa: ANN201
            return self._real.poll()

        def wait(self, timeout=None):  # noqa: ANN001, ANN201
            return self._real.wait(timeout=timeout)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        f2f3.subprocess,
        "Popen",
        lambda *a, _c=child, **k: _StubProc(_c),
    )
    try:
        result = f2f3._run_bounded("f2", tmp_path, budget_seconds=10.0)
    finally:
        monkey.undo()
        with contextlib.suppress(subprocess.TimeoutExpired):
            child.wait(timeout=5)
        for stream in (child.stdout, child.stderr):
            if stream and not stream.closed:
                stream.close()
    assert result["passed"] is False
    assert "output_limit" in result["failure_codes"], result["failure_codes"]
    assert result["worker_terminated"] is True
    assert result["retained_base"] == str(tmp_path)
