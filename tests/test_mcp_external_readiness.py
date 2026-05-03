"""MCP external integration dry-run readiness contracts.

这些测试是 Remaining Roadmap 的 fake-first skeleton：它只读取 safe fixture/tmp
config，生成“如果未来授权真实集成，需要哪些步骤”的报告。它不连接真实 MCP
endpoint、不执行 server command、不联网、不读取 secret，也不把 MCP client 倒灌
runtime。
"""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "agent" / "mcp_external_readiness.py"


def _agent_imports(path: Path) -> set[str]:
    """用 AST 固定 dry-run skeleton 的依赖方向。"""

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
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_mcp_external_readiness_report_is_dry_run_only(tmp_path, monkeypatch) -> None:
    """dry-run report 只描述 readiness，不执行配置里的 command。"""

    from agent.mcp_external_readiness import build_mcp_external_readiness_report

    monkeypatch.setenv("REAL_TOKEN", "must-not-appear")
    marker = tmp_path / "server-ran"
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        f"""
        {{
          "mcpServers": {{
            "alpha": {{
              "transport": "stdio",
              "command": "python",
              "args": ["-c", "open({str(marker)!r}, 'w').write('x')"],
              "env": {{"API_KEY": "$REAL_TOKEN"}},
              "enabled": true
            }},
            "beta": {{
              "transport": "stdio",
              "command": "beta-server",
              "enabled": false
            }}
          }}
        }}
        """,
        encoding="utf-8",
    )

    report = build_mcp_external_readiness_report(config_path)

    assert report.ok is True
    assert report.no_network is True
    assert report.no_command_execution is True
    assert report.no_secret_read is True
    assert marker.exists() is False
    servers = {server.name: server for server in report.servers}
    assert servers["alpha"].enabled is True
    assert servers["alpha"].dry_run_status == "would_require_tool_discovery_authorization"
    assert servers["beta"].dry_run_status == "disabled_not_registered"
    combined = repr(report)
    assert "must-not-appear" not in combined
    assert "$REAL_TOKEN" not in combined
    assert "<redacted>" in combined


def test_mcp_external_readiness_reuses_safe_path_policy() -> None:
    """dry-run skeleton 不能绕过 MCP config parser 的敏感路径策略。"""

    from agent.mcp_external_readiness import build_mcp_external_readiness_report

    report = build_mcp_external_readiness_report(Path.home() / ".config" / "mcp.json")

    assert report.ok is False
    assert report.validation.errors[0].code == "unsafe_path"
    assert report.servers == ()


def test_mcp_external_readiness_has_no_transport_runtime_or_network_imports() -> None:
    """readiness report 是 config workflow，不是 MCP transport/client/runtime。"""

    agent_imports = _agent_imports(MODULE_PATH)
    module_imports = _module_imports(MODULE_PATH)

    assert agent_imports == {"agent.mcp_config"}
    assert {
        "subprocess",
        "socket",
        "http.client",
        "urllib",
        "requests",
        "agent.core",
        "agent.checkpoint",
        "agent.tool_executor",
        "agent.mcp_stdio",
    }.isdisjoint(agent_imports | module_imports)
