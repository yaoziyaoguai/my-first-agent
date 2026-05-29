"""MCP JSON-RPC stdio fixture server for real evidence validation.

这是一个安全的本地 fixture server，仅用于验证 MCP bridge 真实连接路径。
不联网、不读文件、不执行 shell——只提供 echo 和 demo 两个只读工具。

用法:
    python3 scripts/fixtures/mcp_echo_server.py
"""

from __future__ import annotations

import json
import sys
from typing import Any

TOOLS = [
    {
        "name": "mcp_echo",
        "description": "Echo the input message back. Safe read-only MCP bridge validation tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message to echo back.",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "mcp_demo_status",
        "description": "Return a static status object. Safe read-only MCP bridge validation tool.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]

SERVER_INFO = {
    "name": "mcp-echo-fixture",
    "version": "0.1.0",
}


def _send_response(response_id: int, result: dict[str, Any]) -> None:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": response_id, "result": result},
        ensure_ascii=False,
    )
    sys.stdout.write(payload + "\n")
    sys.stdout.flush()


def _send_error(response_id: int, code: int, message: str) -> None:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": response_id, "error": {"code": code, "message": message}},
        ensure_ascii=False,
    )
    sys.stdout.write(payload + "\n")
    sys.stdout.flush()


def handle_request(request: dict[str, Any]) -> None:
    req_id = request.get("id", 0)
    method = request.get("method", "")
    params = request.get("params", {})

    if method == "initialize":
        _send_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    elif method == "notifications/initialized":
        # MCP spec: server 不需要对此响应
        pass
    elif method == "tools/list":
        _send_response(req_id, {"tools": TOOLS})
    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        if tool_name == "mcp_echo":
            msg = arguments.get("message", "")
            _send_response(req_id, {
                "content": [{"type": "text", "text": f"[mcp_echo] {msg}"}],
                "isError": False,
            })
        elif tool_name == "mcp_demo_status":
            _send_response(req_id, {
                "content": [{"type": "text", "text": json.dumps({
                    "status": "ok",
                    "server": "mcp-echo-fixture",
                    "uptime": "fixture",
                })}],
                "isError": False,
            })
        else:
            _send_response(req_id, {
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                "isError": True,
            })
    else:
        _send_error(req_id, -32601, f"Method not found: {method}")


def main() -> None:
    # 将 stderr 用于日志，避免污染 stdout JSON-RPC 通道
    print("[mcp_echo_server] fixture started, waiting for requests...", file=sys.stderr)
    for line in sys.stdin:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            request = json.loads(stripped)
        except json.JSONDecodeError:
            print(f"[mcp_echo_server] invalid JSON: {stripped[:80]}", file=sys.stderr)
            continue
        handle_request(request)


if __name__ == "__main__":
    main()
