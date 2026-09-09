"""Raw JSON-RPC stdio server for bridge behavior tests（仅测试用）。

FastMCP fixture 无法表达「call 已执行后断连 / 挂起 / 返回超大结果」这些 transport
边界场景，故用裸 JSON-RPC 2.0（newline-delimited）server 精确控制。读 stdin 一行一条，
按 mode 决定 tools/call 后的行为：

- ``disconnect_after_call``：收到 tools/call 先写 marker（证明 bytes/args 已到达、
  副作用已发生），再直接退出、不回 response——模拟 call 写出后断连。
- ``hang_after_call``：写 marker 后永久挂起、保持 stdout 打开、永不回 response——
  模拟 hanging server，用于验证有界 cleanup。
- ``big_result``：回一个 ``BEHAVIOR_SIZE_MB``（默认 5）MB 的 text content——用于验证
  transport-owned result cap。
- ``spawn_child_leader_exit``：收到 tools/call 后 spawn 一个留在同组（不开新 session）的
  benign child，写 ``BEHAVIOR_CHILD_FACTS``（leader/child/PGID），等 ``BEHAVIOR_CHILD_RELEASE``
  握手放行，再回已知成功并自行退出——模拟「leader 单独退出、同组 child 存活」，用于验证
  owned process group cleanup proof（006）。

不访问网络。
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time


def _write(obj: dict) -> None:
    data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _probe_tool() -> dict:
    return {
        "name": "probe",
        "description": "behavior probe",
        "inputSchema": {"type": "object", "properties": {}},
    }


def _wait_for_release(path: str, *, timeout: float = 15.0) -> None:
    """有界握手：等测试确认 group membership（touch release 文件）后再继续。

    测试异常未放行时也不永久挂起：超时后按原计划继续，最终 leader 退出、child 由自身
    watchdog 收口，绝不残留进程。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(path):
            return
        time.sleep(0.01)


def _child_sleeper(seconds: float) -> None:
    """benign 同组 child：不开新 session，留在 server 的 owned group（PGID==server PID）。

    默认关闭继承的 stdio——server 退出后 bridge 的 readers 才能收到 EOF；仅当
    ``BEHAVIOR_CHILD_INHERIT_STDIO=1`` 时保留（覆盖 inherit stdout/stderr 的真实路径）。
    child 在有界 watchdog 下存活，任何测试失败都不会留下无限期进程。
    """
    if os.environ.get("BEHAVIOR_CHILD_INHERIT_STDIO") != "1":
        for fd in (0, 1, 2):
            with contextlib.suppress(OSError):
                os.close(fd)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(0.1)


def _spawn_group_child_and_record_facts() -> None:
    """spawn 同组 benign child 并把 leader/child/PGID 写入 ``BEHAVIOR_CHILD_FACTS``。

    facts 是测试「亲自确认 child 确属本次 owned group」的依据（真实 syscall 复核），
    不是注入的布尔值。child 不经 setsid/setpgid，天然继承 server 的 process group。
    """
    child = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "_child_sleeper", "30"],
    )
    facts_path = os.environ.get("BEHAVIOR_CHILD_FACTS")
    if facts_path:
        with open(facts_path, "w", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "leader_pid": os.getpid(),
                        "child_pid": child.pid,
                        "pgid": os.getpgrp(),
                    }
                )
            )
    release = os.environ.get("BEHAVIOR_CHILD_RELEASE")
    if release:
        _wait_for_release(release)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "_child_sleeper":
        _child_sleeper(float(sys.argv[2]) if len(sys.argv) > 2 else 30.0)
        return
    mode = sys.argv[1] if len(sys.argv) > 1 else "disconnect_after_call"
    proposed = "2025-11-25"
    # 启动握手：写自身 PID，供 cleanup 测试在不依赖脆弱 sleep 的前提下确定性地
    # 复验「process group 是否被 kill/reap、是否残留 orphan」。start_new_session=True
    # 下 server 自身即 process-group leader，PID == PGID。
    pidfile = os.environ.get("BEHAVIOR_PIDFILE")
    if pidfile:
        with open(pidfile, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
    for raw in iter(sys.stdin.buffer.readline, b""):
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        method = msg.get("method")
        msg_id = msg.get("id")
        if method == "initialize":
            proposed = msg.get("params", {}).get("protocolVersion", proposed)
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": proposed,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "behavior", "version": "0"},
                    },
                }
            )
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            _write({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": [_probe_tool()]}})
        elif method == "tools/call":
            # commit-point 铁证：server 已收到并处理 call。marker 记录到达的 arguments。
            marker = os.environ.get("BEHAVIOR_MARKER")
            if marker:
                arguments = msg.get("params", {}).get("arguments", {})
                with open(marker, "w", encoding="utf-8") as fh:
                    fh.write(json.dumps(arguments, ensure_ascii=False))
            if mode == "spawn_child_leader_exit":
                # 006 U1 反例主体：同组 benign child + leader 已知成功退出。
                _spawn_group_child_and_record_facts()
                _write(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [{"type": "text", "text": "ok"}],
                            "isError": False,
                        },
                    }
                )
                # leader 已知成功退出；同组 child 继续存活，模拟「leader 终态被误当作
                # group cleanup proof」的真实形态。
                sys.exit(0)
            elif mode == "big_result":
                size_mb = int(os.environ.get("BEHAVIOR_SIZE_MB", "5"))
                _write(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [{"type": "text", "text": "X" * (size_mb * 1024 * 1024)}],
                            "isError": False,
                        },
                    }
                )
            elif mode == "hang_after_call":
                while True:
                    time.sleep(1)
            else:  # disconnect_after_call：call 已执行，故意不回 response 直接断连。
                sys.stdout.buffer.flush()
                sys.exit(0)


if __name__ == "__main__":
    main()
