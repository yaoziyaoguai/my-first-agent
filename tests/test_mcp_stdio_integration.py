"""Minimal real stdio MCP integration tests.

这些测试使用本地 fixture server 做端到端验证：config -> stdio client ->
initialize/list_tools/call_tool -> registry opt-in -> legacy ToolResult。它不联网、
不安装外部 server、不读取真实文件系统或 secret，因此是 MCP real integration 的
低风险第一步。
"""

from __future__ import annotations

import ast
from pathlib import Path
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SERVER = PROJECT_ROOT / "tests" / "fixtures" / "minimal_mcp_stdio_server.py"


def _agent_imports(path: Path) -> set[str]:
    """用 AST 收集 agent.* imports，确认 transport 不倒灌 runtime。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name.startswith("agent"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "agent":
                imports.update(f"agent.{alias.name}" for alias in node.names)
            elif node.module.startswith("agent."):
                imports.add(node.module)
    return imports


def _local_stdio_server_config():
    from agent.mcp import MCPServerConfig

    return MCPServerConfig(
        name="local_fixture",
        command=sys.executable,
        args=(str(FIXTURE_SERVER),),
        enabled=True,
    )


def _temporary_stdio_server_config(tmp_path: Path, source: str):
    """创建一次性本地 stdio server fixture，不访问真实项目/用户目录。"""

    from agent.mcp import MCPServerConfig

    server_path = tmp_path / "server.py"
    server_path.write_text(source, encoding="utf-8")
    return MCPServerConfig(
        name="tmp_fixture",
        command=sys.executable,
        args=(str(server_path),),
        enabled=True,
    )


def test_stdio_mcp_client_initialize_list_and_call_tool() -> None:
    """真实 stdio transport 能完成 initialize/list_tools/call_tool 最小闭环。

    这里启动的是 tests fixture，不是外部 server；它验证 transport framing 和
    MCP-ish JSON-RPC 方法映射，同时避免任何 token、home、项目根文件访问。
    """

    from agent.mcp_stdio import StdioMCPClient

    client = StdioMCPClient(timeout_seconds=5)
    server = _local_stdio_server_config()

    initialize_result = client.initialize(server)
    tools = client.list_tools(server)
    call_result = client.call_tool(server, "echo", {"message": "hello"})

    assert initialize_result["serverInfo"]["name"] == "minimal-local-mcp"
    assert [tool.name for tool in tools] == ["echo"]
    assert tools[0].input_schema["properties"].keys() == {"message"}
    assert call_result.to_legacy_tool_result(
        server_name="local_fixture",
        tool_name="echo",
    ) == "echo: hello"


def test_stdio_mcp_tool_executes_through_registry_with_confirmation() -> None:
    """stdio MCP tool 必须显式 opt-in 后才通过 registry 执行。

    这条端到端测试覆盖：本地 config -> stdio list_tools -> registry opt-in ->
    confirmation policy -> execute_tool -> stdio call_tool -> legacy string result。
    MCP client 仍不参与 runtime transition/checkpoint，tool_executor 未来无需知道
    该 tool 来自 fake、stdio 还是其他 transport。
    """

    from agent.mcp import register_mcp_tools
    from agent.mcp_stdio import StdioMCPClient
    from agent.tool_registry import TOOL_REGISTRY, execute_tool, needs_tool_confirmation

    client = StdioMCPClient(timeout_seconds=5)
    server = _local_stdio_server_config()
    registered = register_mcp_tools([server], client)

    try:
        assert registered == ("mcp__local_fixture__echo",)
        assert needs_tool_confirmation(
            "mcp__local_fixture__echo",
            {"message": "hello"},
        ) is True
        assert execute_tool("mcp__local_fixture__echo", {"message": "hello"}) == "echo: hello"
    finally:
        for name in registered:
            TOOL_REGISTRY.pop(name, None)


def test_stdio_mcp_tool_not_found_maps_to_legacy_failure_contract() -> None:
    """server-side tool error 必须回到现有 `错误：` failure contract。

    真实 MCP server 可能对未知 tool 返回 `isError` content block；本测试证明
    transport 不把该 block 直接丢给 runtime，而是经 MCPCallResult 映射成 legacy
    string，让 tool_result classifier 可以继续稳定工作。
    """

    from agent.mcp_stdio import StdioMCPClient
    from agent.tool_result_contract import classify_tool_outcome

    client = StdioMCPClient(timeout_seconds=5)
    result = client.call_tool(_local_stdio_server_config(), "missing", {})
    legacy = result.to_legacy_tool_result(
        server_name="local_fixture",
        tool_name="missing",
    )

    assert legacy == "错误：MCP 工具 local_fixture/missing 执行失败：unknown tool: missing"
    assert classify_tool_outcome(legacy)[0] == "failed"


def test_stdio_mcp_json_rpc_error_is_transport_error(tmp_path) -> None:
    """JSON-RPC error 属于 transport/client 边界，不应伪装成成功结果。"""

    from agent.mcp_stdio import MCPTransportError, StdioMCPClient

    server = _temporary_stdio_server_config(
        tmp_path,
        "import json, sys\n"
        "request = json.loads(sys.stdin.readline())\n"
        "print(json.dumps({'jsonrpc': '2.0', 'id': request.get('id'), "
        "'error': {'code': -32601, 'message': 'nope'}}), flush=True)\n",
    )

    with pytest.raises(MCPTransportError, match="JSON-RPC error"):
        StdioMCPClient(timeout_seconds=5).initialize(server)


def test_stdio_mcp_malformed_response_is_transport_error(tmp_path) -> None:
    """malformed response 必须被 transport seam 明确报错。

    这避免后续把 JSON decode exception 泄漏到 runtime 层；tool registry 如果执行到
    该异常，会沿用 execute_tool 的 legacy failure 兜底。
    """

    from agent.mcp_stdio import MCPTransportError, StdioMCPClient

    server = _temporary_stdio_server_config(
        tmp_path,
        "print('not-json', flush=True)\n",
    )

    with pytest.raises(MCPTransportError, match="非法 JSON"):
        StdioMCPClient(timeout_seconds=5).initialize(server)


def test_stdio_mcp_timeout_is_transport_error(tmp_path) -> None:
    """stdio request timeout 必须清理进程并返回 transport error。

    测试使用 tmp fixture 和极短 timeout，不连接外部 server；它锁住最小 process
    cleanup 边界，避免真实 transport 卡住 Agent runtime。
    """

    from agent.mcp_stdio import MCPTransportError, StdioMCPClient

    server = _temporary_stdio_server_config(
        tmp_path,
        "import time\ntime.sleep(2)\n",
    )

    with pytest.raises(MCPTransportError, match="timeout"):
        StdioMCPClient(timeout_seconds=0.1).initialize(server)


def test_stdio_mcp_transport_does_not_import_runtime_checkpoint_or_tui() -> None:
    """stdio transport 只依赖 MCP model seam，不依赖 runtime hot path。

    真实 transport 是外部通信边界；如果它 import core/checkpoint/TUI/confirmation
    handlers，就会把协议层和 Agent runtime 绑成新巨石。
    """

    imports = _agent_imports(PROJECT_ROOT / "agent" / "mcp_stdio.py")

    assert imports == {"agent.mcp"}
