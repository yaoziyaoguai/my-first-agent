"""S3 EV-01/02/03 回归（2026-10-11 审计缺陷）。

三条缺陷共享 `scripts/f2_f3_local_browser_journeys.py` 的验收驱动，因此同文件
覆盖；每条测试都驱动真实生产函数与真实子进程，不用私有状态断言替代。

- EV-01：工作 deadline 独立 latch（量级超时不因 child 刚退出而变成功）；真实
  字节保留上限（不因 UTF-8 分片解码少计）；排空/清理各有期限，不等待无限 EOF。
- EV-02：F2 每代真实路径都有 finally，资源取得即登记；逐点注入异常仍确认清理。
- EV-03：外部参数名与规范 journey 名显式映射；非零退出、错误 journey、布尔
  伪装、缺字段、重复记录、非 JSON 都不能 PASS；target/cleanup 失败可区分。
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]

# 测试替身会 monkeypatch ``f2f3.subprocess.Popen``——那是同一个全局 subprocess
# 模块对象，因此测试自己必须持有未打补丁的引用。
_REAL_POPEN = subprocess.Popen


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "f2_f3_local_browser_journeys_ev_under_test",
        ROOT / "scripts/f2_f3_local_browser_journeys.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def f2f3():
    return _load_module()


def _spawn(code: str):
    return _REAL_POPEN(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def _stub_popen(monkeypatch, module, child):
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
        module.subprocess, "Popen", lambda *a, **k: _StubProc(child)
    )


def _cleanup_child(child) -> None:
    if child.poll() is None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(child.pid), signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        child.wait(timeout=5)
    for stream in (child.stdin, child.stdout, child.stderr):
        if stream is not None and not stream.closed:
            stream.close()


# ---------------------------------------------------------------- EV-01

REPORT = json.dumps(
    {
        "journey": "f2",
        "target_checks_passed": True,
        "resource_cleanup_confirmed": True,
        "failure_codes": [],
        "details": {},
    }
)


def test_small_flush_with_delayed_eof_is_a_timeout_not_a_pass(
    f2f3, tmp_path, monkeypatch
) -> None:
    """EV-01：小片段输出后延迟 EOF，0.15s 预算必须判 timeout（量级超时）。

    Red：HEAD 在 1.27s 后仍返回 ``timeout=false``/``passed=true``——工作
    deadline 只在 select 就绪时检查，child 睡眠期间循环卡在阻塞读取。
    """

    monkeypatch.setattr(f2f3, "_COOPERATIVE_CLEANUP_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_TERM_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_KILL_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_POST_KILL_VERIFY_SECONDS", 0.5)

    child = _spawn(
        f"import time; print({REPORT!r}, flush=True); time.sleep(1.2)"
    )
    _stub_popen(monkeypatch, f2f3, child)
    started = time.monotonic()
    try:
        result = f2f3._run_bounded("f2", tmp_path, budget_seconds=0.15)
        elapsed = time.monotonic() - started
    finally:
        _cleanup_child(child)

    assert result["timeout"] is True
    assert result["passed"] is False
    assert "work_budget_timeout" in result["failure_codes"]
    # 控制等待有界：budget + coop + term/kill/verify + drain（注入后 < 5s）。
    assert elapsed < 5, f"control wait exceeded bound: {elapsed:.2f}s"
    assert elapsed > 0.15, "must not report before the deadline elapses"


def test_just_past_deadline_natural_exit_is_not_a_pass(
    f2f3, tmp_path, monkeypatch
) -> None:
    """EV-01 负例：刚好越过 deadline 的自然退出也不变成功（latch 独立于 child）。"""

    monkeypatch.setattr(f2f3, "_COOPERATIVE_CLEANUP_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_TERM_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_KILL_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_POST_KILL_VERIFY_SECONDS", 0.5)

    child = _spawn(
        f"import time; print({REPORT!r}, flush=True); time.sleep(0.6)"
    )
    _stub_popen(monkeypatch, f2f3, child)
    try:
        result = f2f3._run_bounded("f2", tmp_path, budget_seconds=0.3)
    finally:
        _cleanup_child(child)

    assert result["timeout"] is True
    assert result["passed"] is False


def test_byte_limit_counts_bytes_not_decoded_characters(
    f2f3, tmp_path, monkeypatch
) -> None:
    """EV-01：UTF-8 多字节分片按真实字节计数，不因解码换成字符计数而少计。

    产出 1.5 MiB 的中文（每字符 3 字节）→ 字节数必超 1 MiB 上限，字符数不会。
    Red：HEAD 用字符计数（`len(line)` 于 text 模式）→ 不触发 output_limit。
    """

    monkeypatch.setattr(f2f3, "_COOPERATIVE_CLEANUP_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_TERM_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_KILL_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_POST_KILL_VERIFY_SECONDS", 0.5)

    code = (
        "import sys\n"
        "payload = ('\\u4e2d' * 20000).encode('utf-8') * 25\n"  # ~1.5 MiB
        "sys.stdout.buffer.write(payload)\n"
        "sys.stdout.buffer.flush()\n"
        "import time; time.sleep(30)\n"
    )
    child = _spawn(code)
    _stub_popen(monkeypatch, f2f3, child)
    try:
        result = f2f3._run_bounded("f2", tmp_path, budget_seconds=10.0)
    finally:
        _cleanup_child(child)

    assert "output_limit" in result["failure_codes"], result["failure_codes"]
    assert result["passed"] is False
    details = result["details"]
    assert details["stdout_bytes"] > f2f3._CHILD_STDOUT_LIMIT
    # 保留上限本身成立（不继续无限追加）。
    assert details["stdout_retained"] <= f2f3._CHILD_STDOUT_LIMIT


def test_descendant_holding_pipe_does_not_block_drain(
    f2f3, tmp_path, monkeypatch
) -> None:
    """EV-01：后代继承写端时不等待无限 EOF；排空有独立期限。"""

    monkeypatch.setattr(f2f3, "_COOPERATIVE_CLEANUP_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_TERM_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_KILL_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_POST_KILL_VERIFY_SECONDS", 0.5)

    code = (
        "import subprocess, sys, time\n"
        "print(" + repr(REPORT) + ", flush=True)\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],"
        " start_new_session=True)\n"
        "time.sleep(60)\n"
    )
    child = _spawn(code)
    descendant_pid = None
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and descendant_pid is None:
            probe = subprocess.run(
                ["pgrep", "-P", str(child.pid)], capture_output=True, text=True
            )
            if probe.stdout.strip():
                descendant_pid = int(probe.stdout.strip().split()[0])
            time.sleep(0.05)
        assert descendant_pid is not None, "test descendant must exist"
        _stub_popen(monkeypatch, f2f3, child)
        started = time.monotonic()
        result = f2f3._run_bounded("f2", tmp_path, budget_seconds=0.4)
        elapsed = time.monotonic() - started
    finally:
        for pid in (descendant_pid, child.pid):
            if pid is None:
                continue
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)
        _cleanup_child(child)

    # 后代仍持有写端 → 不得等到它自然退出（30s）；排空期限封顶。
    assert elapsed < 10, f"drain waited for descendant EOF: {elapsed:.2f}s"
    assert result["timeout"] is True


# ---------------------------------------------------------------- EV-03


def test_nonzero_exit_with_success_record_cannot_pass(
    f2f3, tmp_path, monkeypatch
) -> None:
    """EV-03：成功 JSON 后 exit 7 必须失败。

    Red：HEAD 只看记录内容，``child_exit_nonzero`` 不存在 → passed=true。
    """

    monkeypatch.setattr(f2f3, "_COOPERATIVE_CLEANUP_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_TERM_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_KILL_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_POST_KILL_VERIFY_SECONDS", 0.5)

    child = _spawn(f"import sys; print({REPORT!r}, flush=True); sys.exit(7)")
    _stub_popen(monkeypatch, f2f3, child)
    try:
        result = f2f3._run_bounded("f2", tmp_path, budget_seconds=5.0)
    finally:
        _cleanup_child(child)

    assert result["passed"] is False
    assert "child_exit_nonzero" in result["failure_codes"], result["failure_codes"]
    assert result["details"]["child_exit_status"] == 7


def test_wrong_journey_record_cannot_pass(f2f3, tmp_path, monkeypatch) -> None:
    """EV-03：记录里的 journey 不是本次请求的规范名 → 失败。

    Red：HEAD 从不比对 journey → 别的旅程的记录也算 PASS。
    """

    monkeypatch.setattr(f2f3, "_COOPERATIVE_CLEANUP_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_TERM_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_KILL_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_POST_KILL_VERIFY_SECONDS", 0.5)

    wrong = json.loads(REPORT)
    wrong["journey"] = "d06_submit_readback_cleanup"
    child = _spawn(f"print({json.dumps(wrong)!r}, flush=True)")
    _stub_popen(monkeypatch, f2f3, child)
    try:
        result = f2f3._run_bounded("f2", tmp_path, budget_seconds=5.0)
    finally:
        _cleanup_child(child)

    assert result["passed"] is False
    assert "child_journey_mismatch" in result["failure_codes"]


def test_canonical_mapping_accepts_the_real_child_record(
    f2f3, tmp_path, monkeypatch
) -> None:
    """EV-03：外部参数 ``f2`` 与规范名 ``f2_restart_outclosing`` 显式映射。

    正例必须通过——否则映射写错会让真实旅程全失败。
    """

    monkeypatch.setattr(f2f3, "_COOPERATIVE_CLEANUP_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_TERM_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_KILL_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_POST_KILL_VERIFY_SECONDS", 0.5)

    assert f2f3._JOURNEY_CANONICAL["f2"] == "f2_restart_outclosing"
    assert f2f3._JOURNEY_CANONICAL["d06"] == "d06_submit_readback_cleanup"
    good = json.loads(REPORT)
    good["journey"] = "f2_restart_outclosing"
    child = _spawn(f"print({json.dumps(good)!r}, flush=True)")
    _stub_popen(monkeypatch, f2f3, child)
    try:
        result = f2f3._run_bounded("f2", tmp_path, budget_seconds=5.0)
    finally:
        _cleanup_child(child)

    assert result["passed"] is True, result["failure_codes"]
    assert result["target_checks_passed"] is True
    assert result["resource_cleanup_confirmed"] is True


def test_target_failed_but_cleanup_confirmed_is_distinguishable(
    f2f3, tmp_path, monkeypatch
) -> None:
    """EV-03：target 失败 + 清理确认 → 可区分，但都不能总体 PASS。"""

    monkeypatch.setattr(f2f3, "_COOPERATIVE_CLEANUP_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_TERM_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_KILL_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_POST_KILL_VERIFY_SECONDS", 0.5)

    report = json.loads(REPORT)
    report["journey"] = "f2_restart_outclosing"
    report["target_checks_passed"] = False
    child = _spawn(f"print({json.dumps(report)!r}, flush=True)")
    _stub_popen(monkeypatch, f2f3, child)
    try:
        result = f2f3._run_bounded("f2", tmp_path, budget_seconds=5.0)
    finally:
        _cleanup_child(child)

    assert result["passed"] is False
    assert result["target_checks_passed"] is False
    assert result["resource_cleanup_confirmed"] is True


def test_bool_disguised_as_int_and_bad_failure_codes_fail(
    f2f3, tmp_path, monkeypatch
) -> None:
    """EV-03：布尔伪装成 0/1、failure_codes 类型错误都必须失败。"""

    monkeypatch.setattr(f2f3, "_COOPERATIVE_CLEANUP_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_TERM_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_KILL_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_POST_KILL_VERIFY_SECONDS", 0.5)

    cases = {
        "int_disguised_bool": {
            "journey": "f2_restart_outclosing",
            "target_checks_passed": 1,
            "resource_cleanup_confirmed": 1,
            "failure_codes": [],
            "details": {},
        },
        "bad_failure_codes_type": {
            "journey": "f2_restart_outclosing",
            "target_checks_passed": True,
            "resource_cleanup_confirmed": True,
            "failure_codes": "none",
            "details": {},
        },
    }
    for name, payload in cases.items():
        child = _spawn(f"print({json.dumps(payload)!r}, flush=True)")
        _stub_popen(monkeypatch, f2f3, child)
        try:
            result = f2f3._run_bounded("f2", tmp_path, budget_seconds=5.0)
        finally:
            _cleanup_child(child)
        assert result["passed"] is False, name
        assert "child_protocol_bad_types" in result["failure_codes"], (
            name,
            result["failure_codes"],
        )


def test_signal_exit_cannot_pass(f2f3, tmp_path, monkeypatch) -> None:
    """EV-03：signal exit 必须失败（与正常退出区分）。"""

    monkeypatch.setattr(f2f3, "_COOPERATIVE_CLEANUP_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_TERM_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_KILL_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(f2f3, "_POST_KILL_VERIFY_SECONDS", 0.5)

    child = _spawn(
        f"import os, signal, sys; print({REPORT!r}, flush=True);"
        " os.kill(os.getpid(), signal.SIGTERM)"
    )
    _stub_popen(monkeypatch, f2f3, child)
    try:
        result = f2f3._run_bounded("f2", tmp_path, budget_seconds=5.0)
    finally:
        _cleanup_child(child)

    assert result["passed"] is False
    assert "child_exit_signal" in result["failure_codes"], result["failure_codes"]


# ---------------------------------------------------------------- EV-02


def _stub_browser_resources(monkeypatch, module, calls: list[str]):
    """替换 browser 资源构造：返回一个可登记 closeable 的 owner，不启动浏览器。"""

    def _build(*_args, **_kwargs):
        return types.SimpleNamespace(
            readiness=types.SimpleNamespace(value="ready"),
            reason_code="",
            closeables=(lambda: calls.append("closed"),),
            registrations=(),
        )

    monkeypatch.setattr(module, "build_browser_resources", _build)
    monkeypatch.setattr(module, "KernelToolRuntime", lambda *a, **k: object())


def test_f2_cleans_up_when_open_fails(f2f3, tmp_path, monkeypatch) -> None:
    """EV-02：F2 第一代 open 注入异常 → 资源仍被清理，且有界错误码上报。

    Red：HEAD 的 F2 只在正常控制流显式 close；open 抛异常时 cleanup_calls=0。
    """

    calls: list[str] = []
    _stub_browser_resources(monkeypatch, f2f3, calls)

    def _fail_open(*_args, **_kwargs):
        raise RuntimeError("synthetic first open failure")

    monkeypatch.setattr(f2f3, "_invoke_governed", _fail_open)

    result = f2f3.journey_f2_restart_outclosing(tmp_path)

    assert calls == ["closed"], "generation1 must clean up after open failure"
    assert result["passed"] is False
    assert result["cleanup_confirmed"] is True
    assert result["failure_codes"] == ["generation1_RuntimeError"]
    assert "synthetic first open failure" not in json.dumps(result)


def test_f2_cleans_up_when_readiness_check_fails(f2f3, tmp_path, monkeypatch) -> None:
    """EV-02：资源取得即登记——readiness 检查失败也由本代 finally 收口。"""

    calls: list[str] = []

    def _build(*_args, **_kwargs):
        return types.SimpleNamespace(
            readiness=types.SimpleNamespace(value="unavailable"),
            reason_code="synthetic_not_ready",
            closeables=(lambda: calls.append("closed"),),
            registrations=(),
        )

    monkeypatch.setattr(f2f3, "build_browser_resources", _build)
    monkeypatch.setattr(f2f3, "KernelToolRuntime", lambda *a, **k: object())

    result = f2f3.journey_f2_restart_outclosing(tmp_path)

    assert calls == ["closed"]
    assert result["cleanup_confirmed"] is True
    assert result["failure_codes"] == ["generation1_not_ready"]


def test_f2_cleanup_failure_keeps_task_and_cleanup_failures_separate(
    f2f3, tmp_path, monkeypatch
) -> None:
    """EV-02：一个清理回调抛错仍尝试剩余；任务/清理失败分别保留为有界码。"""

    calls: list[str] = []

    def _boom():
        calls.append("boom")
        raise RuntimeError("cleanup exploded")

    def _build(*_args, **_kwargs):
        return types.SimpleNamespace(
            readiness=types.SimpleNamespace(value="ready"),
            reason_code="",
            closeables=(_boom, lambda: calls.append("closed")),
            registrations=(),
        )

    monkeypatch.setattr(f2f3, "build_browser_resources", _build)
    monkeypatch.setattr(f2f3, "KernelToolRuntime", lambda *a, **k: object())
    monkeypatch.setattr(
        f2f3,
        "_invoke_governed",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("open failed")),
    )

    result = f2f3.journey_f2_restart_outclosing(tmp_path)

    assert calls == ["closed", "boom"], "remaining cleanup must still run"
    assert result["cleanup_confirmed"] is False
    assert result["failure_codes"] == ["generation1_cleanup_failed"]
    assert result["cleanup_failures"] == [
        {"generation": "gen1", "index": 0, "error_type": "RuntimeError"}
    ]
    assert "cleanup exploded" not in json.dumps(result)


def test_f2_second_generation_is_not_created_when_first_ledger_unclosed(
    f2f3, tmp_path, monkeypatch
) -> None:
    """EV-02：第一代 ledger 未闭合 → 不创建第二代（不掩盖清理缺口）。"""

    from agent.runtime.contracts import ToolResult

    calls: list[str] = []
    _stub_browser_resources(monkeypatch, f2f3, calls)
    monkeypatch.setattr(
        f2f3,
        "_invoke_governed",
        lambda *a, **k: ToolResult(
            tool_call_id="open-1",
            content="opened",
            metadata={"session_ref": "session-unclosed"},
        ),
    )

    class _OpenRecord:
        phase = f2f3.SessionPhase.ACTIVE

    monkeypatch.setattr(
        f2f3.BrowserSessionStore,
        "load",
        lambda self, ref: _OpenRecord(),
    )

    result = f2f3.journey_f2_restart_outclosing(tmp_path)

    assert calls == ["closed"], "only generation1 resources were created"
    assert result["passed"] is False
    assert result["cleanup_confirmed"] is True
    assert result["failure_codes"] == ["generation1_ledger_not_closed"]


def test_journey_disposition_never_infers_cleanup_from_passed() -> None:
    """EV-02/03：没有清理证据时保守判定，不把 passed 当成清理确认。"""

    module = _load_module()

    assert module._journey_disposition(
        {"passed": True, "cleanup_confirmed": True}
    ) == (True, True)
    assert module._journey_disposition(
        {"passed": False, "cleanup_confirmed": True}
    ) == (False, True)
    assert module._journey_disposition(
        {"passed": True, "cleanup_confirmed": False}
    ) == (True, False)
    # 显式字段缺失 → 回落到 cleanup_failures；再缺失则 False（保守）。
    assert module._journey_disposition(
        {"passed": True, "cleanup_failures": []}
    ) == (True, True)
    assert module._journey_disposition(
        {"passed": True, "cleanup_failures": [{"x": 1}]}
    ) == (True, False)
    assert module._journey_disposition({"passed": True}) == (True, False)
