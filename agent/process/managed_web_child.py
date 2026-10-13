"""受管开发服务的最小 POSIX 生命周期监督器。

父进程持有 control pipe 的唯一写端。正常关闭、异常退出或被 SIGKILL 时，
读端都会得到 EOF；本监督器随后终止与自己同组的已批准开发进程。它不含
模型、工具、权限或重试逻辑，只负责一个已冻结 argv 的进程生命周期。
"""

from __future__ import annotations

import argparse
import os
import select
import signal
import subprocess
import time
from contextlib import suppress


def _stop_owned_group(*, grace_seconds: float = 1.0) -> None:
    """TERM 整组后以 KILL 收口；KILL 也会终止本监督器，因此本函数不返回。"""

    signal.signal(signal.SIGTERM, lambda _signum, _frame: None)
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgrp(), signal.SIGTERM)
    time.sleep(grace_seconds)
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgrp(), signal.SIGKILL)
    raise SystemExit(125)


def supervise(control_fd: int, lifetime_seconds: float, command: tuple[str, ...]) -> int:
    """运行一个同 process-group child，直到 child/父进程/期限任一结束。"""

    if control_fd < 0 or lifetime_seconds <= 0 or not command:
        raise ValueError("managed web supervisor arguments are invalid")
    child = subprocess.Popen(  # noqa: S603 - argv 由父侧批准并以 frozen tuple 传入
        command,
        stdin=subprocess.DEVNULL,
        stdout=None,
        stderr=None,
        shell=False,
        close_fds=True,
    )
    deadline = time.monotonic() + lifetime_seconds
    try:
        while True:
            return_code = child.poll()
            if return_code is not None:
                # 启动器可能把真正的 dev server 留在同一 process group 后自己
                # 退出。这里不能把 direct child 终态当成整个受管资源终态；
                # 按既有 ownership 回收整组，避免后代越过 lifetime。
                _stop_owned_group()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _stop_owned_group()
            readable, _, _ = select.select([control_fd], [], [], min(0.1, remaining))
            if readable and not os.read(control_fd, 1):
                _stop_owned_group()
    finally:
        with suppress(OSError):
            os.close(control_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--control-fd", type=int, required=True)
    parser.add_argument("--lifetime-seconds", type=float, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args(argv)
    command = tuple(arguments.command)
    if command and command[0] == "--":
        command = command[1:]
    return supervise(arguments.control_fd, arguments.lifetime_seconds, command)


if __name__ == "__main__":
    raise SystemExit(main())
