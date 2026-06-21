"""Minimal local stdio MCP-like test server.

测试 fixture 只处理单条 JSON-RPC line，不读取文件、不联网、不访问 secret。它用于
验证 First Agent 的 stdio transport / list_tools / call_tool seam，不代表完整 MCP
server 实现。
"""

from __future__ import annotations

import json
import sys


def _response(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> int:
    request = json.loads(sys.stdin.readline())
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "minimal-local-mcp", "version": "test"},
        }
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "echo",
                    "description": "Echo a message from a local MCP fixture",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                    },
                }
            ]
        }
    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if tool_name == "echo":
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": f"echo: {arguments.get('message', '')}",
                    }
                ],
                "isError": False,
            }
        else:
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": f"unknown tool: {tool_name}",
                    }
                ],
                "isError": True,
            }
    elif method == "resources/list":
        # G-042a: MCP resources primitive (local, no file/network).
        result = {
            "resources": [
                {
                    "uri": "greeting://hello",
                    "name": "hello",
                    "description": "A static local greeting resource",
                    "mimeType": "text/plain",
                }
            ]
        }
    elif method == "resources/read":
        uri = params.get("uri", "")
        if uri == "greeting://hello":
            result = {
                "contents": [
                    {
                        "uri": "greeting://hello",
                        "mimeType": "text/plain",
                        "text": "hello from local MCP resource",
                    }
                ]
            }
        else:
            result = {"contents": []}
    else:
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"unknown method: {method}"},
        }), flush=True)
        return 0

    print(json.dumps(_response(request_id, result)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
