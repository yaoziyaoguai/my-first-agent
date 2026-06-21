"""G-025 (Phase 4): real local MCP connect/list/call/result flight.

Resolves the prior G-025 blocker ("no authorized MCP endpoint"). The user
authorized building/finding a safe MCP service, so this drives the REAL stdio
MCP transport (StdioMCPClient) against a safe LOCAL fixture MCP server
(`tests/fixtures/minimal_mcp_stdio_server.py`) — a real subprocess speaking
JSON-RPC over stdio (not FakeMCPClient, no network, no npx).

Flow:
    MCPServerConfig(transport=stdio, command=python, args=(fixture,))
    StdioMCPClient.initialize -> server handshake (connect)
    StdioMCPClient.list_tools -> [echo] (list)
    StdioMCPClient.call_tool("echo", {message}) -> MCPCallResult (call + result)

Runs by default (local, deterministic, no external dependency). The governed
audit recording for MCP is covered by `tests/runtime_integration/test_mcp_audit_evidence.py`;
this test proves real endpoint reachability (connect/list/call/result). No secret
(the fixture is local; MCP transport does not touch provider credentials).
"""

from __future__ import annotations

import pathlib
import sys

from agent.mcp_models import MCPServerConfig
from agent.mcp_stdio import StdioMCPClient

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
_FIXTURE_SERVER = PROJECT_ROOT / "tests" / "fixtures" / "minimal_mcp_stdio_server.py"


def _local_echo_server() -> MCPServerConfig:
    return MCPServerConfig(
        name="g025-local-echo",
        transport="stdio",
        command=sys.executable,
        args=(str(_FIXTURE_SERVER),),
        enabled=True,
    )


def test_real_local_mcp_connect_list_call_result() -> None:
    """Real stdio MCP flight: connect (initialize) -> list -> call -> result."""
    assert _FIXTURE_SERVER.is_file(), f"fixture MCP server missing: {_FIXTURE_SERVER}"
    server = _local_echo_server()
    client = StdioMCPClient(timeout_seconds=10.0)

    # connect (initialize handshake)
    init = client.initialize(server)
    assert init.get("protocolVersion") == "2024-11-05"
    server_info = init.get("serverInfo", {})
    assert server_info.get("name") == "minimal-local-mcp"

    # list
    tools = client.list_tools(server)
    names = [t.name for t in tools]
    assert "echo" in names, f"echo tool not listed; got {names}"

    # call + result
    result = client.call_tool(server, "echo", {"message": "g025-local-ok"})
    assert result.is_error is False, f"echo call returned error: {result.content!r}"
    content_text = ""
    content = result.content
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict):
            content_text = str(first.get("text", ""))
    assert "g025-local-ok" in content_text, (
        f"echo result did not carry the message; got {content_text!r}"
    )


def test_real_local_mcp_resources_list_and_read() -> None:
    """G-042a: MCP resources primitive — resources/list + resources/read (local)."""
    assert _FIXTURE_SERVER.is_file()
    server = _local_echo_server()
    client = StdioMCPClient(timeout_seconds=10.0)

    resources = client.list_resources(server)
    uris = [r.get("uri") for r in resources if isinstance(r, dict)]
    assert "greeting://hello" in uris, f"greeting resource not listed; got {uris}"

    contents = client.read_resource(server, "greeting://hello")
    texts = [
        c.get("text", "")
        for c in contents
        if isinstance(c, dict)
    ]
    assert any("hello from local MCP resource" in t for t in texts), (
        f"resource read did not return the greeting; got {texts!r}"
    )
