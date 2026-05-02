"""Pre-Skill/Subagent Pack 1：MCP config CLI/service/presenter contract tests.

这些测试把 Slice 2+3 合并成一个较大的执行包：
- CLI 只能做 list / inspect / validate / plan-add / plan-remove；
- plan 只产出 diff preview，不写 config；
- apply 仍然拒绝；
- CLI adapter 必须很薄，业务语义在 service，展示在 presenter；
- 不读取真实 home config，不执行 server command，不联网，不泄漏 secret。
"""

from __future__ import annotations

import ast
import io
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI_MODULE = PROJECT_ROOT / "agent" / "mcp_config_cli.py"
SERVICE_MODULE = PROJECT_ROOT / "agent" / "mcp_config_service.py"
PRESENTER_MODULE = PROJECT_ROOT / "agent" / "mcp_config_presenter.py"


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        """
        {
          "mcpServers": {
            "alpha": {
              "transport": "stdio",
              "command": "alpha-server",
              "args": ["--mode", "test"],
              "env": {
                "API_KEY": "alpha-secret-value",
                "LOG_LEVEL": "debug"
              },
              "enabled": true
            },
            "beta": {
              "transport": "stdio",
              "command": "beta-server",
              "enabled": false
            }
          }
        }
        """,
        encoding="utf-8",
    )
    return config_path


def _run_cli(args: list[str]) -> tuple[int, str]:
    from agent.mcp_config_cli import run_mcp_config_cli

    stdout = io.StringIO()
    exit_code = run_mcp_config_cli(args, stdout=stdout)
    return exit_code, stdout.getvalue()


def _agent_imports(path: Path) -> set[str]:
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


def test_cli_list_safe_fixture_configs(tmp_path) -> None:
    """list 只展示 safe fixture server 摘要，不读取默认 home config。"""

    config_path = _write_config(tmp_path)

    exit_code, output = _run_cli(["config", "list", "--path", str(config_path)])

    assert exit_code == 0
    assert "alpha" in output
    assert "beta" in output
    assert "enabled" in output
    assert "alpha-secret-value" not in output


def test_cli_inspect_one_server_with_secret_redaction(tmp_path) -> None:
    """inspect 展示单个 server 明细，但 secret-like env value 必须 redacted。"""

    config_path = _write_config(tmp_path)

    exit_code, output = _run_cli([
        "config",
        "inspect",
        "--path",
        str(config_path),
        "--name",
        "alpha",
    ])

    assert exit_code == 0
    assert "alpha-server" in output
    assert "API_KEY=<redacted>" in output
    assert "LOG_LEVEL=debug" in output
    assert "alpha-secret-value" not in output


def test_cli_validate_returns_structured_validation_result(tmp_path) -> None:
    """validate 复用 Slice 1 validation result，不把业务策略写进 CLI。"""

    config_path = tmp_path / "invalid.json"
    config_path.write_text(
        '{"mcpServers": {"broken": {"args": "--not-list"}}}',
        encoding="utf-8",
    )

    exit_code, output = _run_cli(["config", "validate", "--path", str(config_path)])

    assert exit_code == 1
    assert "invalid" in output.lower()
    assert "broken" in output
    assert "command" in output
    assert "args" in output


def test_plan_add_produces_diff_preview_without_writing_config(tmp_path) -> None:
    """plan-add 只生成计划和 diff preview，不能修改 config 文件。"""

    config_path = _write_config(tmp_path)
    before = config_path.read_text(encoding="utf-8")

    exit_code, output = _run_cli([
        "config",
        "plan-add",
        "--path",
        str(config_path),
        "--name",
        "gamma",
        "--command",
        "gamma-server",
        "--arg",
        "--safe",
        "--env",
        "TOKEN=gamma-secret-value",
    ])

    assert exit_code == 0
    assert config_path.read_text(encoding="utf-8") == before
    assert "Plan: add gamma" in output
    assert "+ gamma" in output
    assert "TOKEN=<redacted>" in output
    assert "gamma-secret-value" not in output


def test_plan_remove_produces_diff_preview_without_writing_config(tmp_path) -> None:
    """plan-remove 只表达删除意图和 diff，不做 destructive change。"""

    config_path = _write_config(tmp_path)
    before = config_path.read_text(encoding="utf-8")

    exit_code, output = _run_cli([
        "config",
        "plan-remove",
        "--path",
        str(config_path),
        "--name",
        "beta",
    ])

    assert exit_code == 0
    assert config_path.read_text(encoding="utf-8") == before
    assert "Plan: remove beta" in output
    assert "- beta" in output


def test_apply_command_requires_plan() -> None:
    """Safe Apply pack 后 apply 不再全量 deferred，但仍必须先有 plan packet。"""

    exit_code, output = _run_cli(["config", "apply", "--path", "unused", "--yes"])

    assert exit_code == 2
    assert "plan" in output.lower()


def test_cli_rejects_unsafe_home_config_path() -> None:
    """CLI 不允许默认/真实 home config，必须显式 safe fixture/tmp path。"""

    home_config = Path.home() / ".config" / "mcp" / "config.json"

    exit_code, output = _run_cli(["config", "list", "--path", str(home_config)])

    assert exit_code == 1
    assert "unsafe_path" in output


def test_main_routes_mcp_config_validate_without_starting_runtime(tmp_path) -> None:
    """main.py 只把 mcp config 子命令转发给 CLI adapter，不进入 agent loop。"""

    from main import main

    config_path = _write_config(tmp_path)

    assert main(["mcp", "config", "validate", "--path", str(config_path)]) == 0


def test_mcp_config_cli_layers_do_not_import_transport_runtime_or_network() -> None:
    """CLI/service/presenter 边界不能倒灌 runtime，也不能连接 MCP transport。"""

    assert _agent_imports(CLI_MODULE) <= {
        "agent.mcp_config_cli",
        "agent.mcp_config_presenter",
        "agent.mcp_config_service",
    }
    assert _agent_imports(SERVICE_MODULE) == {"agent.mcp_config"}
    assert _agent_imports(PRESENTER_MODULE) <= {
        "agent.mcp_config",
        "agent.mcp_config_service",
    }
    forbidden_modules = {"subprocess", "socket", "http.client", "urllib", "requests"}
    assert _module_imports(CLI_MODULE).isdisjoint(forbidden_modules)
    assert _module_imports(SERVICE_MODULE).isdisjoint(forbidden_modules)
    assert _module_imports(PRESENTER_MODULE).isdisjoint(forbidden_modules)
