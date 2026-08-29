"""共享 POSIX process-group 所有权 primitive。

两个真实消费者：``agent/process/runner.py``（governed local_process 的
``group_reaped`` draft 合同）与 ``agent/subagent/process_runner.py``
（hard-deadline kill 的 ``process_terminated`` receipt 合同）。本模块只拥有
OS 层 group 事实——verified identity、TERM→KILL、bounded liveness 确认——
不定义任何结果/receipt taxonomy；无法确认消失时 raise ``ProcessCleanupError``，
调用方必须 fail closed，不得把 unknown 当 terminated。
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from contextlib import suppress

# Post-KILL 验证预算（秒）：默认给足慢机器上的 zombie/orphan 收敛；总清理
# 时间仍保持有界（TERM grace + KILL grace + 该预算）。
POST_KILL_VERIFY_BUDGET_SECONDS = 6.0


class ProcessCleanupError(RuntimeError):
    """process group 在 TERM+KILL 后仍无法确认消失 → 调用方必须 fail closed。"""


def verified_group_identity(pid: int) -> int:
    """``start_new_session=True`` 后 PGID 必须等于 pid。mismatch → fail-closed。

    ESRCH → 返回 pid：leader 已退出且消失（超快进程在 Popen 与本 probe 之间
    退出的实测 race）。这只表示「无法观察」，不表示「group 不存在」——调用方
    保留 expected identity（pid）继续治理/确认；其余 OSError（EPERM 等）与
    identity mismatch 仍 fail-closed。
    """

    try:
        observed = os.getpgid(pid)
    except ProcessLookupError:
        return pid
    except OSError as exc:
        raise ProcessCleanupError(
            f"cannot verify process group identity for pid {pid}: {exc}"
        ) from exc
    if observed != pid:
        raise ProcessCleanupError(
            f"observed PGID {observed} != expected {pid}; session identity mismatch"
        )
    return observed


def group_alive(pgid: int) -> bool:
    """signal 0 probe。只有 ESRCH 表示 gone；其他 OSError → fail-closed。

    pgid 缺失不是「group 已消失」的证据——无可治理 identity 就无法确认
    清理，必须 fail closed，不得据此报告 reaped。
    """

    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError as exc:
        raise ProcessCleanupError(
            f"cannot determine process group liveness: {exc}"
        ) from exc


def terminate_group(
    proc: subprocess.Popen,
    pgid: int,
    *,
    term_grace_seconds: float,
    kill_grace_seconds: float,
    verify_budget_seconds: float = POST_KILL_VERIFY_BUDGET_SECONDS,
) -> tuple[bool, bool]:
    """TERM→KILL→bounded verify on observed process group。

    返回 ``(term_sent, kill_sent)``，仅在 group 消失被 liveness probe 确认后
    返回；无法确认 → raise ``ProcessCleanupError``。signal 送达失败不构成
    清理证明——``group_alive`` 是唯一确认 oracle。grace/预算秒数由调用方的
    产品合同决定（process profile 或 subagent 常量），总时长保持有界。

    Pre-KILL probe EPERM → conservative：proceed to KILL（cannot confirm gone,
    but TERM may not have been enough）。Post-KILL verification unknown → raise。
    循环内机会性收尸 leader：SIGKILL 后 leader 僵尸未 reap 时 killpg 会持续
    报告存活（慢/负载机器上 proc.wait(kill_grace) 可能超时错过退出窗口）→
    纯探测循环偶发耗尽 → 诚实 ProcessCleanupError（E3 content 门 j3 flake
    实测）。按 monotonic 给予完整预算，而不是固定次数。
    """

    term_sent = _signal_group(pgid, signal.SIGTERM)
    with suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=term_grace_seconds)
    try:
        group_gone = not group_alive(pgid)
    except ProcessCleanupError:
        group_gone = False
    if group_gone:
        return term_sent, False
    kill_sent = _signal_group(pgid, signal.SIGKILL)
    with suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=kill_grace_seconds)
    verification_deadline = time.monotonic() + verify_budget_seconds
    while time.monotonic() < verification_deadline:
        remaining = verification_deadline - time.monotonic()
        with suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=min(0.1, max(0.0, remaining)))
        if not group_alive(pgid):
            return term_sent, kill_sent
        remaining = verification_deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.1, remaining))
    raise ProcessCleanupError(
        "process group survived TERM+KILL; cannot confirm cleanup"
    )


def _signal_group(pgid: int, sig: int) -> bool:
    """Send signal to observed group. Returns True if delivered, False if not.

    Signal delivery failure does not prove cleanup. ``group_alive`` remains the
    only confirmation oracle and fails closed on every result other than ESRCH.
    """

    try:
        os.killpg(pgid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False
