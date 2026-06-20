"""Minimal MCP fixture server with safe URL fetch capability.

中文学习边界：
- 本地 stdio fixture，只支持 allowlisted URL 的 HTTP GET。
- 不访问任意 URL、不发送 headers、不记录完整响应正文。
- 用于验证 MCP bridge 对跨 server / 跨 tool category 的 policy gate 一致性。
- 不是生产 server，不替代真实 fetch MCP server。
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

# 只允许这些 URL（read-only, safe）
_ALLOWED_URLS = frozenset({
    "https://httpbin.org/get",
    "https://httpbin.org/ip",
    "https://httpbin.org/user-agent",
})


def _response(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _safe_fetch(url: str) -> str:
    """只对 allowlisted URL 做 HTTP GET，返回摘要。"""
    if url not in _ALLOWED_URLS:
        return f"拒绝访问：URL '{url}' 不在 allowlist 中。当前允许: {sorted(_ALLOWED_URLS)}"

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            # 只返回短摘要，不返回完整响应正文
            return f"[HTTP {resp.status}] {body[:300]}"
    except urllib.error.URLError as e:
        return f"fetch 失败: {e}"
    except Exception as e:
        return f"fetch 异常: {e}"


def main() -> int:
    request = json.loads(sys.stdin.readline())
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "minimal-fetch-mcp", "version": "test"},
        }
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "safe_fetch",
                    "description": (
                        "Fetch a URL with allowlist restriction. "
                        "Only HTTP GET on pre-approved URLs."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "URL to fetch"}
                        },
                        "required": ["url"],
                    },
                }
            ]
        }
    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if tool_name == "safe_fetch":
            url = arguments.get("url", "")
            text = _safe_fetch(url)
            result = {
                "content": [{"type": "text", "text": text}],
                "isError": "失败" in text or "异常" in text or "拒绝" in text,
            }
        else:
            result = {
                "content": [{"type": "text", "text": f"unknown tool: {tool_name}"}],
                "isError": True,
            }
    else:
        print(json.dumps({
            "jsonrpc": "2.0", "id": request_id,
            "error": {"code": -32601, "message": f"unknown method: {method}"},
        }), flush=True)
        return 0

    print(json.dumps(_response(request_id, result)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
