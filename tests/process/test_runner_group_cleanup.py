"""015 runner group-cleanup Reds (R16/AE8 stop-ship).

Test 1: leader exits 0, descendant (same PGID) ignores TERM + holds pipe.
  Old: proc.poll() returns 0 -> never cleanup -> drain hangs.
  Fix: timeout fires at wall deadline regardless of leader status.

Test 2: monkeypatch _group_alive to True -> ProcessCleanupError.

Test 3: normal KILL path -> TIMED_OUT_REAPED + no orphan.

All tests: finally killpg cleanup for exact recorded PGID only.
"""

from __future__ import annotations

import errno
import os
import signal
import stat
import subprocess
import time
from contextlib import suppress
from pathlib import Path

import pytest

from agent.process.contracts import ProcessDraftOutcome, ResourceProfile, ResourceProfileV1
from agent.process.group import ProcessCleanupError
from agent.process.runner import run_local_process


def _fast_profile(*, deadline=2, cap=4096):
    return ResourceProfileV1(
        profile=ResourceProfile.SHORT,
        wall_deadline_seconds=deadline,
        term_grace_seconds=1,
        kill_grace_seconds=1,
        stdout_cap_bytes=cap,
        stderr_cap_bytes=cap,
        combined_cap_bytes=cap * 2,
        rendered_chars=cap,
        argv_max_items=128,
        argv_item_max_bytes=16 * 1024,
        argv_total_max_bytes=64 * 1024,
        executable_hash_max_bytes=256 * 1024 * 1024,
    )


def _make_executable(dir_path: Path, name: str, content: bytes) -> str:
    path = dir_path / name
    path.write_bytes(content)
    os.chmod(path, stat.S_IRWXU)
    return str(path)


def _cleanup_exact_pgid(pgid: int | None) -> None:
    """Only kill the exact PGID this test created. Never pkill/pgrep/os.system."""
    if pgid is None:
        return
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGKILL)


def test_015_leader_exit_descendant_holds_pipe_bounded_cleanup(
    tmp_path: Path, monkeypatch
) -> None:
    """R16/AE8: leader exits 0 immediately; descendant (same PGID) ignores TERM, holds pipe.

    Root cause: old runner used `proc.poll() is None` as timeout gate -> when leader exits,
    gate is False -> drain hangs forever on descendant's pipe.
    Fix: timeout fires at wall deadline regardless of leader status.
    """

    import agent.process.runner as runner_module

    fixture = b"""#!/bin/sh
# Fork descendant ignoring TERM+HUP, holding stdout pipe
( trap '' TERM HUP; sleep 30 ) &
# Leader exits immediately; session SIGHUP must not pre-kill the descendant
exit 0
"""
    exe = _make_executable(tmp_path, "pipe-holder", fixture)
    recorded_proc: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    class _RecordingPopen(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            super().__init__(*args, **kwargs)
            recorded_proc.append(self)

    monkeypatch.setattr(runner_module.subprocess, "Popen", _RecordingPopen)
    start = time.monotonic()
    draft = None
    try:
        with suppress(ProcessCleanupError):
            draft = run_local_process(
                resolved_executable=exe,
                argv=[],
                cwd=str(tmp_path),
                profile=_fast_profile(deadline=2),
                environment={},
            )
        # macOS 上原 PGID 数字可能在 leader 先退出后被 foreign group 复用，
        # liveness probe 返回 EPERM。此时 fail closed 是正确且有界的结果。
        elapsed = time.monotonic() - start
        assert elapsed < 10, f"runner hung for {elapsed:.1f}s"
        if draft is not None:
            assert draft.outcome is ProcessDraftOutcome.TIMED_OUT_REAPED
            assert draft.group_reaped is True
    finally:
        if recorded_proc:
            _cleanup_exact_pgid(recorded_proc[0].pid)


def test_015_esrch_pgid_probe_keeps_expected_identity_no_false_reaped(
    tmp_path: Path, monkeypatch
) -> None:
    """Codex 终审 P1：_verified_pgid ESRCH→None 不得把 group 当已确认清理。

    start_new_session=True 保证 group identity == child pid。leader 在 probe 前退出
    （ESRCH race）时，同 group descendant 仍存活且必须可治理。旧实现把 pgid 置
    None：_group_alive(None)=False 被当成「group gone」→ draft 谎报
    group_reaped=True / process_group_id=None，而 descendant 存活。
    Green：保留 expected PGID identity；只有 ESRCH 能证明 group 消失。数字 PGID 被
    系统复用后若 probe 返回 EPERM，必须进入 unknown，不能用 pipe EOF 伪造 reaped。
    """

    import agent.process.runner as runner_module

    fixture = b"""#!/bin/sh
# Descendant (same PGID) survives leader and holds the stdout pipe.
/bin/sleep 30 &
exec /bin/echo leader-done
"""
    exe = _make_executable(tmp_path, "esrch-descendant", fixture)
    # 精确模拟 Popen 后 getpgid 命中 ESRCH race（leader 已退出）：共享 seam 的
    # verified_group_identity 在 ESRCH 时返回 pid（保留 expected identity）。
    import agent.process.group as group_module

    monkeypatch.setattr(group_module, "verified_group_identity", lambda pid: pid)
    recorded_proc: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    class _RecordingPopen(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            super().__init__(*args, **kwargs)
            recorded_proc.append(self)

    monkeypatch.setattr(runner_module.subprocess, "Popen", _RecordingPopen)
    probed_pgids: list[int] = []

    def _unconfirmable_group(pgid: int) -> bool:
        probed_pgids.append(pgid)
        raise ProcessCleanupError("synthetic unconfirmable group")

    monkeypatch.setattr(group_module, "group_alive", _unconfirmable_group)
    try:
        with pytest.raises(ProcessCleanupError):
            run_local_process(
                resolved_executable=exe,
                argv=[],
                cwd=str(tmp_path),
                profile=_fast_profile(deadline=1),
                environment={},
            )
    finally:
        if recorded_proc:
            assert probed_pgids and all(
                pgid == recorded_proc[0].pid for pgid in probed_pgids
            )
            _cleanup_exact_pgid(recorded_proc[0].pid)


def test_015_cannot_confirm_group_survival_raises_and_cleans_up(
    tmp_path: Path, monkeypatch
) -> None:
    """ProcessCleanupError when final group verification cannot confirm -> unknown outcome.

    Monkeypatch _group_alive to always True -> _terminate_group raises after KILL retry.
    Uses recording wrapper on subprocess.Popen to capture exact PID for cleanup.
    Assert: ProcessCleanupError raised.
    """

    fixture = b"""#!/bin/sh
trap '' TERM
sleep 30
"""
    exe = _make_executable(tmp_path, "unreachable-kill", fixture)
    # Monkeypatch: group always "alive" AND pipe closure always fails → cannot confirm
    monkeypatch.setattr("agent.process.group.group_alive", lambda _pgid: True)
    recorded_proc: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    class _RecordingPopen(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            super().__init__(*args, **kwargs)
            recorded_proc.append(self)

    monkeypatch.setattr("agent.process.runner.subprocess.Popen", _RecordingPopen)

    start = time.monotonic()
    try:
        with pytest.raises(ProcessCleanupError):
            run_local_process(
                resolved_executable=exe,
                argv=[],
                cwd=str(tmp_path),
                profile=_fast_profile(deadline=1),
                environment={},
            )
        elapsed = time.monotonic() - start
        assert elapsed < 10, "ProcessCleanupError path hung"
    finally:
        # Clean up exact recorded PID only (start_new_session -> PGID == PID).
        for proc in recorded_proc:
            pid = proc.pid
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(pid, signal.SIGKILL)
            with suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=2)
            with suppress(OSError):
                proc.stdout.close()
            with suppress(OSError):
                proc.stderr.close()


def test_015_post_kill_verification_uses_full_bounded_time_budget(monkeypatch) -> None:
    """负载下 orphan zombie 可晚于旧的 30 次 probe 消失，但仍在 <10s 合同内。"""

    import agent.process.group as group_module

    clock = [0.0]
    monkeypatch.setattr(group_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        group_module.time,
        "sleep",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    monkeypatch.setattr(group_module, "_signal_group", lambda _pgid, _sig: True)
    probes = [0]

    def delayed_group_reap(_pgid: int) -> bool:
        probes[0] += 1
        return probes[0] < 37

    monkeypatch.setattr(group_module, "group_alive", delayed_group_reap)

    class ReapedLeader:
        def wait(self, timeout: float) -> int:  # noqa: ARG002
            return 0

    result = group_module.terminate_group(  # noqa: SLF001
        ReapedLeader(),
        12345,
        term_grace_seconds=1,
        kill_grace_seconds=1,
    )

    assert result == (True, True)
    assert 3 < clock[0] < 6


def test_015_pipe_eof_does_not_prove_process_group_cleanup(
    tmp_path: Path, monkeypatch
) -> None:
    """R16 / design §9.3：pipe EOF 不能替代 observed group liveness 证明。

    模拟 KILL 后 direct child 与 pipes 已关闭、但 group probe 仍不可确认。旧 fallback
    会把 EOF 当 ``group_reaped=True``；正确行为是抛 ``ProcessCleanupError``，交给
    Runtime unknown-outcome recovery。
    """

    import agent.process.group as group_module

    fixture = b"#!/bin/sh\ntrap '' TERM\nsleep 30\n"
    exe = _make_executable(tmp_path, "pipe-eof-is-not-group-proof", fixture)

    def kill_then_unconfirmed(  # noqa: ANN001, ANN202
        proc,
        pgid,
        *,
        term_grace_seconds,  # noqa: ARG001
        kill_grace_seconds,
        verify_budget_seconds=6.0,  # noqa: ARG001
    ):
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGKILL)
        with suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=kill_grace_seconds)
        raise ProcessCleanupError("group liveness remains unconfirmed")

    monkeypatch.setattr(group_module, "terminate_group", kill_then_unconfirmed)
    with pytest.raises(ProcessCleanupError):
        run_local_process(
            resolved_executable=exe,
            argv=[],
            cwd=str(tmp_path),
            profile=_fast_profile(deadline=1),
            environment={},
        )


def test_015_trap_term_descendant_killed_and_no_orphan(tmp_path: Path) -> None:
    """KILL 后能确认 group 消失则 REAPED；PGID 复用导致 EPERM 时诚实 unknown。"""

    fixture = b"""#!/bin/sh
trap '' TERM
( trap '' TERM; sleep 30 ) &
wait
"""
    exe = _make_executable(tmp_path, "trap-term", fixture)
    start = time.monotonic()
    draft = None
    try:
        try:
            draft = run_local_process(
                resolved_executable=exe,
                argv=[],
                cwd=str(tmp_path),
                profile=_fast_profile(deadline=2),
                environment={},
            )
        except ProcessCleanupError as error:
            # macOS 可能在原 group 被 KILL 后立即复用 PGID；signal-0 对 foreign
            # group 返回 EPERM。Runtime 的正确合同是 bounded unknown，不得把
            # 无法确认误报为 REAPED，所以真实 OS 测试必须接受这条 fail-closed 路径。
            # 其他 cleanup failure 仍是回归，绝不能被这个平台 race 掩盖。
            cause = error.__cause__
            if not (
                isinstance(cause, PermissionError)
                and cause.errno == errno.EPERM
                and str(error).startswith("cannot determine process group liveness:")
            ):
                raise
            assert time.monotonic() - start < 15
            return
        assert time.monotonic() - start < 15
        assert draft.outcome is ProcessDraftOutcome.TIMED_OUT_REAPED
        assert draft.group_reaped is True
    finally:
        if draft is not None:
            _cleanup_exact_pgid(draft.process_group_id)
