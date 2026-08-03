"""本地 fixture MCP stdio server。

仅用于测试：用 SDK server 侧 FastMCP 暴露确定性工具，供 project-owned transport 驱动。
不访问网络。启动方式：``python stdio_server.py``（FastMCP.run 默认 stdio transport）。
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("fixture")


@mcp.tool()
def echo(text: str) -> str:
    """Return the same text that was sent."""
    return text


@mcp.tool()
def broken() -> str:
    """Always raises, exercising the error-result path."""
    raise RuntimeError("fixture tool failed on purpose")


@mcp.tool()
def environment() -> str:
    """Return sorted environment variable names of this server process (test-only)."""
    import os

    return "\n".join(sorted(os.environ))


@mcp.tool()
def chatty(marker: str, kbytes: int) -> str:
    """Write a large, identifiable burst to stderr, then return a distinct marker.

    Exercises continuous stderr draining: without draining the stderr pipe fills and the
    server blocks before it can return. The stderr content must never reach the model.
    """
    import sys

    sys.stderr.write("SECRET-STDERR-MARKER\n")
    sys.stderr.flush()
    sys.stderr.write("S" * (int(kbytes) * 1024))
    sys.stderr.flush()
    return f"done-{marker}"


if __name__ == "__main__":
    mcp.run()
