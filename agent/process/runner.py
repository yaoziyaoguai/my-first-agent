"""015 bounded POSIX process lifecycle（KTD6 / KTD9）。

只消费已准备好的 immutable spawn inputs（resolved executable + argv + cwd + profile +
closed environment），运行一次 foreground process：``shell=False``、stdin DEVNULL、no
TTY、``start_new_session=True``（独立 process group）、增量有界排空 stdout/stderr、
monotonic deadline、bounded TERM→KILL→reap。返回 closed ``ProcessExecutionDraftV1``。

runner 不读取 checkpoint、不认识 Goal/approval/model，也不自报 receipt。spawn 后无法
确认的失败抛给调用方（Runtime）进入既有 unknown-outcome recovery，绝不在这里伪造。
"""

from __future__ import annotations

import hashlib
import os
import select
import signal
import subprocess
import time
from contextlib import suppress

from agent.process.contracts import (
    ProcessDraftOutcome,
    ProcessExecutionDraftV1,
    ResourceProfileV1,
)

_CHUNK = 65_536
_SELECT_SLICE = 0.2
_HARD_DRAIN_MARGIN = 2.0  # pipe drain 宽限（秒），在 deadline+grace 之外


class ProcessCleanupError(RuntimeError):
    """process group 在 TERM+KILL 后仍无法确认消失 → unknown outcome（不伪造 receipt）。"""


def run_local_process(
    *,
    resolved_executable: str,
    argv,
    cwd: str,
    profile: ResourceProfileV1,
    environment: dict[str, str],
) -> ProcessExecutionDraftV1:
    """运行一次 bounded foreground process，返回 closed draft。"""

    argv_list = [str(resolved_executable), *[str(item) for item in argv]]
    started = time.monotonic()
    deadline = started + profile.wall_deadline_seconds
    try:
        proc = subprocess.Popen(  # noqa: S603 - argv 受 admission 校验，shell=False
            argv_list,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=environment,
            shell=False,
            start_new_session=True,
            close_fds=True,
        )
    except (OSError, ValueError) as exc:
        return _draft_failed(started, "spawn_failed", str(exc))

    # start_new_session=True → group identity == proc.pid（内核保证，与 leader 是否
    # 存活无关）。probe 仅验证 observed PGID == pid；mismatch/EPERM → fail-closed。
    # probe 在 try/finally 内执行（Codex 预审 §11.4：probe 失败不得遗留已启动
    # child/pipe）。ESRCH（leader 在 Popen 与 probe 之间退出的实测 race）→ 保留
    # expected PGID identity：同 group descendant 仍存活时必须可治理——绝不能把
    # 「无 observed pgid」当「group 已消失」（Codex 终审 P1 false group-reaped）。
    pgid: int
    stdout: bytearray = bytearray()
    stderr: bytearray = bytearray()
    out_done = err_done = False
    out_trunc = err_trunc = False
    term_sent = kill_sent = False
    timed_out = False
    out_fd = proc.stdout.fileno()
    err_fd = proc.stderr.fileno()
    hard_drain_deadline = (
        deadline
        + profile.term_grace_seconds
        + profile.kill_grace_seconds
        + _HARD_DRAIN_MARGIN
    )
    # group_confirmed_gone 初始 False：只有 process-group liveness probe 能确认。
    group_confirmed_gone = False

    try:
        observed_pgid = _verified_pgid(proc.pid)
        # ESRCH：leader 已退出，但 group identity 仍由 start_new_session 钉死为
        # proc.pid；killpg(pgid) 可达存活 descendant，清理与确认都按真实 group 进行。
        pgid = proc.pid if observed_pgid is None else observed_pgid
        while not (out_done and err_done):
            now = time.monotonic()
            if not timed_out and now >= deadline:
                timed_out = True
                term_sent, kill_sent, group_confirmed_gone = _terminate_group(
                    proc, pgid, profile
                )
            if now > hard_drain_deadline:
                break
            watch = []
            if not out_done:
                watch.append(out_fd)
            if not err_done:
                watch.append(err_fd)
            if not watch:
                break
            if timed_out or proc.poll() is not None:
                timeout = _SELECT_SLICE
            else:
                timeout = max(0.0, min(_SELECT_SLICE, deadline - time.monotonic()))
            try:
                readable, _, _ = select.select(watch, [], [], timeout)
            except (OSError, ValueError):
                break
            for fd in readable:
                try:
                    chunk = os.read(fd, _CHUNK)
                except OSError:
                    chunk = b""
                if not chunk:
                    if fd == out_fd:
                        out_done = True
                    else:
                        err_done = True
                    continue
                if fd == out_fd:
                    if _append_capped(
                        stdout, chunk, profile.stdout_cap_bytes,
                        len(stdout) + len(stderr), profile.combined_cap_bytes,
                    ):
                        out_trunc = True
                else:
                    if _append_capped(
                        stderr, chunk, profile.stderr_cap_bytes,
                        len(stdout) + len(stderr), profile.combined_cap_bytes,
                    ):
                        err_trunc = True

        # Reap direct child FIRST（remove zombie from group before probing）。
        _reap(proc, profile)

        # Post-drain orphan cleanup：leader 正常退出但 descendant 持 pipe 时 group 仍活。
        needs_cleanup = False
        if not timed_out:
            try:
                needs_cleanup = _group_alive(pgid)
            except ProcessCleanupError:
                needs_cleanup = True
        if needs_cleanup:
            timed_out = True
            term_sent, kill_sent, group_confirmed_gone = _terminate_group(
                proc, pgid, profile
            )
        # 正常退出：确认 observed group 已消失。
        if not timed_out:
            try:
                group_confirmed_gone = not _group_alive(pgid)
            except ProcessCleanupError:
                group_confirmed_gone = False
    finally:
        # 任何 path（包括 ProcessCleanupError）都显式 reap + 关闭 streams。
        _reap(proc, profile)
        for stream in (proc.stdout, proc.stderr):
            with suppress(OSError):
                stream.close()

    ended = time.monotonic()
    outcome, signal_name = _classify(timed_out, proc.returncode)
    return ProcessExecutionDraftV1(
        outcome=outcome,
        pid=proc.pid,
        process_group_id=pgid,
        exit_code=proc.returncode if outcome is ProcessDraftOutcome.EXITED else None,
        signal=signal_name,
        started_at_monotonic=started,
        ended_at_monotonic=ended,
        duration_seconds=ended - started,
        stdout_bytes=len(stdout),
        stderr_bytes=len(stderr),
        stdout_digest=_sha256(stdout),
        stderr_digest=_sha256(stderr),
        stdout_projection=_project(stdout, profile.rendered_chars),
        stderr_projection=_project(stderr, profile.rendered_chars),
        stdout_truncated=out_trunc,
        stderr_truncated=err_trunc,
        group_reaped=group_confirmed_gone,
        term_sent=term_sent,
        kill_sent=kill_sent,
        error_code=None,
    )


def _append_capped(
    buf: bytearray, chunk: bytes, stream_cap: int, combined_used: int, combined_cap: int,
) -> bool:
    room = max(0, min(stream_cap - len(buf), combined_cap - combined_used))
    if room <= 0:
        return True
    if len(chunk) > room:
        buf.extend(chunk[:room])
        return True
    buf.extend(chunk)
    return len(buf) >= stream_cap or (combined_used + len(buf)) >= combined_cap


def _terminate_group(proc: subprocess.Popen, pgid: int, profile: ResourceProfileV1):
    """TERM→KILL→verify on observed process group。

    Pre-KILL probe EPERM → conservative：proceed to KILL（cannot confirm gone, but
    TERM may not have been enough）。Post-KILL verification EPERCH/unknown → fail-closed。
    """

    term_sent = _signal_group(pgid, signal.SIGTERM)
    with suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=profile.term_grace_seconds)
    # Pre-KILL probe：if group gone → done。EPERM → cannot confirm → proceed to KILL。
    try:
        group_gone = not _group_alive(pgid)
    except ProcessCleanupError:
        group_gone = False
    if group_gone:
        return term_sent, False, True
    kill_sent = _signal_group(pgid, signal.SIGKILL)
    with suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=profile.kill_grace_seconds)
    # Post-KILL verification：must confirm group gone。Any failure → ProcessCleanupError。
    # 循环内机会性收尸 leader：SIGKILL 后 leader 僵尸未 reap 时 killpg(0) 会持续报告
    # 存活（慢/负载机器上 proc.wait(kill_grace) 可能超时错过退出窗口）→ 纯探测循环
    # 偶发耗尽 → 诚实 ProcessCleanupError（E3 content 门 j3 flake 实测）。预算保持
    # 30 次（≈6s，bounded-cleanup 合同 <10s 不变）；KILL 未送达（EPERM）时每次
    # wait(0.1) 有界，不会无限阻塞。
    for _ in range(30):
        with suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=0.1)
        if not _group_alive(pgid):
            return term_sent, kill_sent, True
        time.sleep(0.1)
    raise ProcessCleanupError(
        "process group survived TERM+KILL; cannot confirm cleanup"
    )


def _group_alive(pgid: int) -> bool:
    """signal 0 probe。只有 ProcessLookupError/ESRCH 表示 gone；其他 OSError → fail-closed。

    pgid 缺失（None）不是「group 已消失」的证据——无可治理 identity 就无法确认
    清理，必须 fail closed 进 unknown，不得据此报告 reaped。
    """

    if pgid is None:
        raise ProcessCleanupError(
            "no verified process group identity; cannot confirm cleanup"
        )
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError as exc:
        raise ProcessCleanupError(
            f"cannot determine process group liveness: {exc}"
        ) from exc


def _reap(proc: subprocess.Popen, profile: ResourceProfileV1) -> None:
    if proc.poll() is None:
        with suppress(OSError):
            proc.kill()
        with suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=profile.kill_grace_seconds)


def _signal_group(pgid: int, sig: int) -> bool:
    """Send signal to observed group. Returns True if delivered, False if not.

    Signal delivery failure does not prove cleanup. ``_group_alive`` remains the
    only confirmation oracle and fails closed on every result other than ESRCH.
    """

    try:
        os.killpg(pgid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False


def _verified_pgid(pid: int) -> int | None:
    """start_new_session=True 后 PGID 必须等于 pid。mismatch → fail-closed。

    ESRCH → None：leader 已退出且消失（超快进程在 Popen 与本 probe 之间退出的
    实测负载 race）。这只表示「无法观察」，不表示「group 不存在」——调用方保留
    expected identity（pid）继续治理/确认；其余 OSError（EPERM 等）与 identity
    mismatch 仍 fail-closed。
    """

    try:
        observed = os.getpgid(pid)
    except ProcessLookupError:
        return None
    except OSError as exc:
        raise ProcessCleanupError(
            f"cannot verify process group identity for pid {pid}: {exc}"
        ) from exc
    if observed != pid:
        raise ProcessCleanupError(
            f"observed PGID {observed} != expected {pid}; session identity mismatch"
        )
    return observed


def _classify(
    timed_out: bool, returncode: int | None,
) -> tuple[ProcessDraftOutcome, str | None]:
    if timed_out:
        return ProcessDraftOutcome.TIMED_OUT_REAPED, None
    if returncode is None:
        # P3（冻结合同 taxonomy）：spawn 后无法确认退出不是「未执行」——
        # SPAWN_FAILED 断言 pre-spawn 证明。post-spawn unconfirmed 必须 unknown
        # （ProcessCleanupError → Runtime recovery），不得铸 draft。
        raise ProcessCleanupError(
            "process exited unobservably; outcome cannot be confirmed after spawn"
        )
    if returncode >= 0:
        return ProcessDraftOutcome.EXITED, None
    sig = -returncode
    try:
        return ProcessDraftOutcome.SIGNALED, signal.Signals(sig).name
    except ValueError:
        return ProcessDraftOutcome.SIGNALED, str(sig)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _project(buf: bytes, rendered_chars: int) -> str:
    return buf.decode("utf-8", errors="replace")[:rendered_chars]


def _draft_failed(started: float, code: str, message: str) -> ProcessExecutionDraftV1:
    ended = time.monotonic()
    return ProcessExecutionDraftV1(
        outcome=ProcessDraftOutcome.SPAWN_FAILED,
        pid=None,
        process_group_id=None,
        exit_code=None,
        signal=None,
        started_at_monotonic=started,
        ended_at_monotonic=ended,
        duration_seconds=ended - started,
        stdout_bytes=0,
        stderr_bytes=0,
        stdout_digest=_sha256(b""),
        stderr_digest=_sha256(b""),
        stdout_projection="",
        stderr_projection="",
        stdout_truncated=False,
        stderr_truncated=False,
        group_reaped=True,
        term_sent=False,
        kill_sent=False,
        error_code=code,
    )
