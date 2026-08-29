"""共享 POSIX process-group 所有权 primitive 的接口测试（Red：模块尚不存在）。

agent/process/group.py 拥有 verified group identity、TERM→KILL 与 bounded
liveness 确认；两个真实消费者是 agent/process/runner.py（group_reaped draft
合同）与 agent/subagent/process_runner.py（process_terminated receipt 合同），
各自的结果/receipt taxonomy 不在本模块。
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from contextlib import suppress

import pytest

from agent.process.group import (
    ProcessCleanupError,
    group_alive,
    terminate_group,
    verified_group_identity,
)


def _spawn(code: str) -> subprocess.Popen:
    return subprocess.Popen(  # noqa: S603 - 测试自有的 bounded python 代码
        [sys.executable, "-c", code],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def test_verified_group_identity_pins_start_new_session_pgid() -> None:
    proc = _spawn("import time; time.sleep(5)")
    try:
        assert verified_group_identity(proc.pid) == proc.pid
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_verified_group_identity_esrch_keeps_governable_identity() -> None:
    """leader 先退出（ESRCH race）→ 保留 expected pid 作为可治理 identity。"""

    proc = _spawn("pass")
    proc.wait(timeout=5)
    assert verified_group_identity(proc.pid) == proc.pid


def test_verified_group_identity_mismatch_fails_closed(monkeypatch) -> None:
    proc = _spawn("import time; time.sleep(5)")
    try:
        monkeypatch.setattr(os, "getpgid", lambda pid: pid + 1000)
        with pytest.raises(ProcessCleanupError):
            verified_group_identity(proc.pid)
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_group_alive_true_for_live_group_and_false_after_exit() -> None:
    live = _spawn("import time; time.sleep(5)")
    try:
        assert group_alive(live.pid) is True
    finally:
        live.kill()
        live.wait(timeout=5)
    deadline = time.monotonic() + 5
    while group_alive(live.pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert group_alive(live.pid) is False


def test_terminate_group_kills_same_group_descendant_and_confirms(tmp_path) -> None:
    """descendant 与 leader 同 group 时必须整组终结并确认消失。

    descendant PID 由 child 写入 pid 文件传回 parent：测试先证明 descendant
    确实存在且共享预期 PGID（否则不构成 group-kill 证明），terminate_group
    后再证明该 PID 本身消失——仅杀 leader 的实现无法通过（防 vacuous）。
    """

    pid_file = tmp_path / "descendant.pid"
    sleeper = "import time; time.sleep(30)"
    leader = _spawn(
        "import subprocess, sys, time\n"
        "descendant = subprocess.Popen(\n"
        f"    [sys.executable, '-c', {sleeper!r}],\n"
        ")\n"
        f"with open({str(pid_file)!r}, 'w') as handle:\n"
        "    handle.write(str(descendant.pid))\n"
        "time.sleep(30)"
    )
    pgid = verified_group_identity(leader.pid)
    try:
        # 有界等待 child 写回 descendant PID；派生未发生 → 测试失败而非 vacuous 通过。
        report_deadline = time.monotonic() + 5
        while time.monotonic() < report_deadline and not pid_file.exists():
            time.sleep(0.05)
        assert pid_file.exists(), "fixture never reported a descendant pid"
        descendant_pid = int(pid_file.read_text().strip())
        assert os.getpgid(descendant_pid) == pgid, (
            "descendant must share the expected process group before termination"
        )
        assert group_alive(pgid) is True
        term_sent, kill_sent = terminate_group(
            leader,
            pgid,
            term_grace_seconds=0.5,
            kill_grace_seconds=0.5,
            verify_budget_seconds=2.0,
        )
        assert (term_sent or kill_sent) is True
        # 证明 descendant 本身消失（孤儿由 init 收殓，有界轮询到 ESRCH）。
        gone_deadline = time.monotonic() + 5
        while time.monotonic() < gone_deadline:
            try:
                os.kill(descendant_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            pytest.fail("descendant still probes alive after terminate_group")
        assert group_alive(pgid) is False, "descendant must not survive the group kill"
    finally:
        # 有界、精确 PGID 清理；不 broad kill。
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGKILL)
        leader.wait(timeout=5)


def test_terminate_group_unconfirmable_raises_within_budget(monkeypatch) -> None:
    """信号无法送达（killpg 全部失败）时必须在有界预算内 fail closed。"""

    survivor = _spawn("import time; time.sleep(30)")
    pgid = verified_group_identity(survivor.pid)
    try:
        monkeypatch.setattr(os, "killpg", lambda pgid, sig: None)
        with pytest.raises(ProcessCleanupError):
            terminate_group(
                survivor,
                pgid,
                term_grace_seconds=0.1,
                kill_grace_seconds=0.1,
                verify_budget_seconds=0.4,
            )
    finally:
        monkeypatch.undo()
        os.killpg(pgid, signal.SIGKILL)
        survivor.wait(timeout=5)
