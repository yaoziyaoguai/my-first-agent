"""MCP client architecture seam characterization tests.

本文件不实现真实 MCP transport，也不连接真实 MCP server。它只锁住 First Agent
接入 MCP 前必须具备的本地边界：配置是 source of truth、MCP tools 必须显式
opt-in、调用结果仍映射到现有 legacy ToolResult contract，且 MCP client seam
不能倒灌 runtime/checkpoint/TUI。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _agent_imports(path: Path) -> set[str]:
    """用 AST 收集 agent.* imports，避免 grep 注释造成误判。"""

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


def _module_imports(path: Path) -> set[str]:
    """收集普通 imports，确认 MCP seam 没有偷偷接真实 transport。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_mcp_config_loader_uses_explicit_config_without_secret_reads(tmp_path) -> None:
    """MCP server config 必须来自显式配置，不扫描 home 或读取 `.env`。

    这是 Host 配置边界：配置文件是 source of truth，CLI 未来只能管理配置。
    本测试使用 tmp fixture，不接真实 secret；env var 只作为占位字符串保存，
    不能在 loader 中解析或读取。
    """

    from agent.mcp import load_mcp_server_configs, load_mcp_server_configs_from_mapping

    config = {
        "mcpServers": {
            "demo": {
                "transport": "stdio",
                "command": "demo-mcp-server",
                "args": ["--token", "${MCP_DEMO_TOKEN}"],
                "env": {"MCP_DEMO_TOKEN": "${MCP_DEMO_TOKEN}"},
                "enabled": True,
            }
        }
    }
    configs = load_mcp_server_configs_from_mapping(config)

    assert len(configs) == 1
    assert configs[0].name == "demo"
    assert configs[0].transport == "stdio"
    assert configs[0].args == ("--token", "${MCP_DEMO_TOKEN}")
    assert configs[0].env == {"MCP_DEMO_TOKEN": "${MCP_DEMO_TOKEN}"}
    assert configs[0].enabled is True

    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        '{"mcpServers": {"demo": {"command": "demo-mcp-server", "enabled": true}}}',
        encoding="utf-8",
    )
    assert load_mcp_server_configs(config_path)[0].command == "demo-mcp-server"

    with pytest.raises(ValueError, match="敏感"):
        load_mcp_server_configs(".env")


def test_mcp_tools_do_not_enter_base_registry_until_explicitly_registered() -> None:
    """MCP tools 不能因为 import base tools 自动进入默认 registry。

    MCP server 是外部能力源，默认暴露会绕过当前 Tooling Foundation 的人工审计。
    因此 `agent.tools` 只能加载本地 base tools；MCP tools 必须由专门 opt-in seam
    显式注册。
    """

    import agent.tools  # noqa: F401
    from agent.tool_registry import (
        TOOL_CAPABILITIES,
        TOOL_REGISTRY,
        get_allowed_tools,
        get_tool_definitions,
    )

    assert "mcp_tool" in TOOL_CAPABILITIES
    assert all(not name.startswith("mcp__") for name in TOOL_REGISTRY)
    assert all(not name.startswith("mcp__") for name in get_allowed_tools())
    assert all(
        not definition["name"].startswith("mcp__")
        for definition in get_tool_definitions()
    )


def test_explicit_mcp_tool_registration_uses_confirmation_and_legacy_result_contract() -> None:
    """显式注册的 MCP tool 复用本地 registry、confirmation 和 legacy result seam。

    FakeMCPClient 是 architecture seam 测试替身：它不启动 server、不联网，只证明
    list_tools / call_tool 可以映射成本地 optional tool。MCP client 不参与 runtime
    transition；tool_executor 未来仍只看到普通 registry tool。
    """

    from agent.mcp import (
        FakeMCPClient,
        MCPCallResult,
        MCPServerConfig,
        MCPToolDescriptor,
        register_mcp_tools,
    )
    from agent.tool_registry import (
        TOOL_REGISTRY,
        execute_tool,
        get_tool_specs,
        needs_tool_confirmation,
    )

    server = MCPServerConfig(name="demo", command="demo-server", enabled=True)
    descriptor = MCPToolDescriptor(
        server_name="demo",
        name="echo",
        description="echo via fake MCP",
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
        },
    )
    client = FakeMCPClient(
        tools_by_server={"demo": [descriptor]},
        results_by_call={("demo", "echo"): MCPCallResult(content={"ok": True})},
    )

    registered = register_mcp_tools([server], client)

    try:
        assert registered == ("mcp__demo__echo",)
        assert "mcp__demo__echo" in TOOL_REGISTRY
        assert needs_tool_confirmation("mcp__demo__echo", {"message": "hi"}) is True
        spec = {spec["name"]: spec for spec in get_tool_specs()}["mcp__demo__echo"]
        assert spec["capability"] == "mcp_tool"
        assert spec["confirmation"] == "always"
        assert execute_tool("mcp__demo__echo", {"message": "hi"}) == "{'ok': True}"
        assert client.calls == [("demo", "echo", {"message": "hi"})]
    finally:
        TOOL_REGISTRY.pop("mcp__demo__echo", None)


def test_disabled_mcp_server_does_not_register_tools() -> None:
    """配置存在不等于 opt-in；enabled=False 的 server 不应注册任何 tool。

    这保护默认安全语义：MCP config 可以作为 source of truth 存在，但只有显式启用
    的 server 才能通过 opt-in seam 进入 registry。未来 CLI 也只能修改配置，不能
    绕过这个 enabled gate 直接把外部 tools 注入 runtime。
    """

    from agent.mcp import FakeMCPClient, MCPServerConfig, MCPToolDescriptor, register_mcp_tools

    disabled_server = MCPServerConfig(name="demo", command="demo-server", enabled=False)
    client = FakeMCPClient(
        tools_by_server={
            "demo": [
                MCPToolDescriptor(
                    server_name="demo",
                    name="echo",
                    description="disabled tool",
                )
            ]
        }
    )

    assert register_mcp_tools([disabled_server], client) == ()
    assert client.calls == []


def test_mcp_error_result_maps_to_existing_failure_prefix_contract() -> None:
    """MCP call failure 仍映射到现有 `错误：` prefix，不半路迁移 ToolResult。

    第一阶段不能把 ToolResult 改成半结构化对象；MCP seam 只能把 fake client
    返回值压回现有 legacy string contract，让 tool_executor 的分类逻辑继续复用。
    """

    from agent.mcp import MCPCallResult
    from agent.tool_result_contract import classify_tool_outcome

    result = MCPCallResult(is_error=True, error_message="server unavailable")
    legacy = result.to_legacy_tool_result(server_name="demo", tool_name="echo")

    assert legacy == "错误：MCP 工具 demo/echo 执行失败：server unavailable"
    assert classify_tool_outcome(legacy)[0] == "failed"


def test_mcp_content_blocks_map_to_legacy_string_result_contract() -> None:
    """MCP text content blocks 必须压回当前 string ToolResult contract。

    真实 MCP tool 常返回 content block list；但 First Agent 的 result classifier
    仍是 prefix-based string seam。本测试防止 MCP seam 半路把 list 传给 runtime，
    导致 tool_executor 分类和 display event 语义漂移。
    """

    from agent.mcp import MCPCallResult
    from agent.tool_result_contract import classify_tool_outcome

    result = MCPCallResult(content=[
        {"type": "text", "text": "hello"},
        {"type": "text", "text": "world"},
    ])
    legacy = result.to_legacy_tool_result(server_name="demo", tool_name="echo")

    assert legacy == "hello\nworld"
    assert classify_tool_outcome(legacy)[0] == "executed"


def test_mcp_architecture_seam_does_not_import_runtime_or_real_transport() -> None:
    """MCP seam 不能倒灌 runtime，也不能偷偷接真实 transport。

    本阶段只允许本地配置、descriptor、fake client 和 registry opt-in seam。
    真实 stdio/HTTP/SSE transport、checkpoint、TUI、confirmation handler 都必须留到
    后续明确授权的 slice。
    """

    mcp_path = PROJECT_ROOT / "agent" / "mcp.py"
    agent_imports = _agent_imports(mcp_path)
    module_imports = _module_imports(mcp_path)

    assert agent_imports == {"agent.tool_registry"}
    assert {
        "agent.core",
        "agent.tool_executor",
        "agent.checkpoint",
        "agent.confirm_handlers",
        "agent.response_handlers",
        "agent.display_events",
    }.isdisjoint(agent_imports)
    assert {"subprocess", "socket", "http.client", "urllib", "requests"}.isdisjoint(
        module_imports
    )
