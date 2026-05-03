"""MCP CLI Config Management Slice 1 contract tests.

这些测试先固定 parser / validator / redaction 的架构边界：
- 这里只处理 fake fixture / tmp_path / explicit safe path；
- 不读取真实 MCP config、`.env`、agent_log、sessions 或 runs；
- 不展开 env var，不执行 server command，不连接 MCP server；
- 后续 CLI adapter 只能复用这些 service/model seam，不能把策略写进 main.py。
"""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "agent" / "mcp_config.py"


def _agent_imports(path: Path) -> set[str]:
    """用 AST 固定依赖方向，避免 config parser 偷偷倒灌 runtime/tool/memory。"""

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
    """确认 Slice 1 不引入 transport / network / subprocess 依赖。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_parses_minimal_safe_config_fixture_without_executing_command(tmp_path) -> None:
    """parser 只解析 safe fixture，不执行 command，也不连接 server。"""

    from agent.mcp_config import load_mcp_config

    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        """
        {
          "mcpServers": {
            "demo": {
              "transport": "stdio",
              "command": "fake-mcp-server",
              "args": ["--mode", "test"],
              "env": {"LOG_LEVEL": "debug"},
              "enabled": true
            }
          }
        }
        """,
        encoding="utf-8",
    )

    result = load_mcp_config(config_path)

    assert result.ok is True
    assert result.errors == ()
    assert result.config is not None
    assert result.source.path == config_path
    server = result.config.servers_by_name["demo"]
    assert server.name == "demo"
    assert server.transport == "stdio"
    assert server.command == "fake-mcp-server"
    assert server.args == ("--mode", "test")
    assert server.env["LOG_LEVEL"].display_value == "debug"
    assert server.enabled is True


def test_validation_result_reports_required_and_type_errors() -> None:
    """validation result 要结构化报告错误，而不是靠异常或泄漏原始配置。"""

    from agent.mcp_config import parse_mcp_config_mapping

    result = parse_mcp_config_mapping({
        "mcpServers": {
            "missing-command": {"args": ["--ok"]},
            "bad-args": {"command": "fake", "args": "--not-a-list"},
            "bad-env": {"command": "fake", "env": ["TOKEN=secret"]},
        }
    })

    assert result.ok is False
    assert result.config is None
    assert {
        (error.server_name, error.field, error.code)
        for error in result.errors
    } == {
        ("missing-command", "command", "missing_required"),
        ("bad-args", "args", "invalid_type"),
        ("bad-env", "env", "invalid_type"),
    }
    assert "secret" not in repr(result)


def test_secret_env_values_are_redacted_without_expanding_environment(monkeypatch) -> None:
    """secret-like env key 只能被标记/隐藏，不能读取真实环境变量值。"""

    from agent.mcp_config import parse_mcp_config_mapping

    monkeypatch.setenv("FAKE_API_KEY", "real-secret-value-must-not-appear")
    result = parse_mcp_config_mapping({
        "mcpServers": {
            "demo": {
                "command": "fake",
                "env": {
                    "API_KEY": "$FAKE_API_KEY",
                    "SERVICE_TOKEN": "literal-token-value",
                    "LOG_LEVEL": "debug",
                },
            }
        }
    })

    assert result.ok is True
    assert result.config is not None
    env = result.config.servers_by_name["demo"].env
    assert env["API_KEY"].display_value == "<redacted>"
    assert env["SERVICE_TOKEN"].display_value == "<redacted>"
    assert env["LOG_LEVEL"].display_value == "debug"
    rendered = repr(result)
    assert "real-secret-value-must-not-appear" not in rendered
    assert "literal-token-value" not in rendered
    assert "$FAKE_API_KEY" not in rendered


def test_unknown_fields_are_preserved_deterministically() -> None:
    """config management 不能破坏用户未知字段；Slice 1 先保留而不解释。"""

    from agent.mcp_config import parse_mcp_config_mapping

    result = parse_mcp_config_mapping({
        "metadata": {"owner": "fake"},
        "mcpServers": {
            "demo": {
                "command": "fake",
                "custom": {"keep": True},
            }
        },
    })

    assert result.ok is True
    assert result.config is not None
    assert tuple(result.config.unknown_fields) == ("metadata",)
    server = result.config.servers_by_name["demo"]
    assert tuple(server.unknown_fields) == ("custom",)
    assert server.unknown_fields["custom"] == {"keep": True}


def test_safe_path_policy_rejects_sensitive_and_home_paths(tmp_path) -> None:
    """service 只读 explicit safe path；真实 home config / 敏感产物默认拒绝。"""

    from agent.mcp_config import MCPConfigPathPolicy, load_mcp_config

    valid_path = tmp_path / "mcp.json"
    valid_path.write_text('{"mcpServers": {"demo": {"command": "fake"}}}', encoding="utf-8")
    assert load_mcp_config(valid_path).ok is True

    policy = MCPConfigPathPolicy()
    unsafe_paths = (
        Path.home() / ".config" / "mcp" / "config.json",
        PROJECT_ROOT / ".env",
        PROJECT_ROOT / "agent_log.jsonl",
        PROJECT_ROOT / "sessions" / "real.json",
        PROJECT_ROOT / "runs" / "real.jsonl",
    )
    for path in unsafe_paths:
        result = load_mcp_config(path, path_policy=policy)
        assert result.ok is False
        assert result.config is None
        assert result.errors[0].code == "unsafe_path"


def test_safe_summary_and_model_repr_do_not_leak_secret_values() -> None:
    """Slice 2 presenter 之前，Slice 1 model/summary 已不能泄漏 secret。"""

    from agent.mcp_config import parse_mcp_config_mapping, summarize_mcp_config

    result = parse_mcp_config_mapping({
        "mcpServers": {
            "demo": {
                "command": "fake",
                "env": {"PASSWORD": "super-secret-password"},
            }
        }
    })

    assert result.ok is True
    assert result.config is not None
    summary = summarize_mcp_config(result.config)
    combined = f"{result!r}\n{summary!r}\n{summary}"
    assert "super-secret-password" not in combined
    assert "<redacted>" in combined


def test_mcp_config_foundation_has_no_transport_runtime_or_memory_dependencies() -> None:
    """config parser 是开发者工作流层，不是 runtime brain 或 MCP transport。"""

    agent_imports = _agent_imports(MODULE_PATH)
    module_imports = _module_imports(MODULE_PATH)

    forbidden_agent_imports = {
        "agent.core",
        "agent.checkpoint",
        "agent.prompt_builder",
        "agent.memory_store",
        "agent.memory_snapshot_generator",
        "agent.tool_registry",
        "agent.mcp_stdio",
    }
    forbidden_modules = {"subprocess", "socket", "http.client", "urllib", "requests"}

    assert agent_imports.isdisjoint(forbidden_agent_imports)
    assert module_imports.isdisjoint(forbidden_modules)


def test_mcp_config_sample_fixture_is_loadable_and_documented() -> None:
    """MCP config management 需要 fake fixture，而不是只靠临时 JSON。

    这个测试补齐 completion audit 暴露的 evidence gap：fixture config 只用于
    parser/CLI review，不连接真实 MCP endpoint、不执行 command、不读取 secret。
    """

    from agent.mcp_config import load_mcp_config
    from agent.mcp_config_presenter import render_server_inspection
    from agent.mcp_config_service import inspect_mcp_server

    fixture_path = PROJECT_ROOT / "tests" / "fixtures" / "mcp_config" / "safe-mcp.json"
    docs_path = PROJECT_ROOT / "docs" / "MCP_CONFIG_MANAGEMENT.md"

    validation = load_mcp_config(fixture_path)
    inspection = inspect_mcp_server(fixture_path, "fixture")
    rendered = render_server_inspection(inspection)
    docs = docs_path.read_text(encoding="utf-8")

    assert validation.ok is True
    assert validation.config is not None
    assert validation.config.servers_by_name["fixture"].command == "fake-mcp-server"
    assert "ANTHROPIC_API_KEY" not in rendered
    assert "<redacted>" in rendered
    for phrase in (
        "explicit safe fixture path",
        "no real MCP endpoint",
        "no server execution",
        "no .env",
        "plan-first",
    ):
        assert phrase in docs
