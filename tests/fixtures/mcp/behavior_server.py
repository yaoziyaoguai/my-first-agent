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

不访问网络。
"""

from __future__ import annotations

import json
import os
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


def main() -> None:
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
            if mode == "big_result":
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
