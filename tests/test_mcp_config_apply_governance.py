"""MCP Safe Apply + Governance contract tests.

这些测试把 Pack 1 的 plan preview 推进到“安全 apply”之前先钉住边界：
- apply 必须 plan-first，并且显式 `--yes`；
- 只允许 tmp_path / fixture 这类安全路径，不写真实 home config；
- backup、diff、safety manifest 都是 evidence，不是 runtime brain；
- 不执行 MCP server command、不联网、不展开 env secret；
- CLI 仍然只是薄 adapter，业务语义留在 service/use-case。
"""

from __future__ import annotations

import ast
import io
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVICE_MODULE = PROJECT_ROOT / "agent" / "mcp_config_service.py"
CLI_MODULE = PROJECT_ROOT / "agent" / "mcp_config_cli.py"


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        """
        {
          "metadata": {"owner": "fixture"},
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


def _module_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_apply_requires_plan_and_explicit_yes_without_writing(tmp_path) -> None:
    """apply 不是另一个 plan-preview：没有 plan 或没有 --yes 都必须拒绝写入。"""

    from agent.mcp_config_service import apply_mcp_config_plan, plan_add_mcp_server

    config_path = _write_config(tmp_path)
    before = config_path.read_text(encoding="utf-8")
    plan_result = plan_add_mcp_server(
        config_path,
        name="gamma",
        command="gamma-server",
    )

    missing_plan = apply_mcp_config_plan(config_path, plan=None, yes=True)
    missing_yes = apply_mcp_config_plan(config_path, plan=plan_result.plan, yes=False)

    assert missing_plan.ok is False
    assert missing_plan.errors[0].code == "missing_plan"
    assert missing_yes.ok is False
    assert missing_yes.errors[0].code == "confirmation_required"
    assert config_path.read_text(encoding="utf-8") == before


def test_apply_adds_server_deterministically_with_backup_and_manifest(
    tmp_path,
    monkeypatch,
) -> None:
    """安全 apply 只写 safe path，并输出 redacted diff / manifest 作为审计证据。"""

    from agent.mcp_config_service import apply_mcp_config_plan, plan_add_mcp_server

    monkeypatch.setenv("FAKE_TOKEN", "real-env-value-must-not-appear")
    config_path = _write_config(tmp_path)
    before = config_path.read_text(encoding="utf-8")
    plan_result = plan_add_mcp_server(
        config_path,
        name="gamma",
        command="gamma-server",
        args=("--safe",),
        env_specs=("TOKEN=$FAKE_TOKEN", "LOG_LEVEL=info"),
    )

    result = apply_mcp_config_plan(config_path, plan=plan_result.plan, yes=True)

    assert result.ok is True
    assert result.backup_path is not None
    assert result.backup_path.parent == tmp_path
    assert result.backup_path.read_text(encoding="utf-8") == before
    written = json.loads(config_path.read_text(encoding="utf-8"))
    assert written["mcpServers"]["gamma"] == {
        "args": ["--safe"],
        "command": "gamma-server",
        "env": {"LOG_LEVEL": "info", "TOKEN": "$FAKE_TOKEN"},
        "transport": "stdio",
    }
    assert config_path.read_text(encoding="utf-8") == json.dumps(
        written,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"

    evidence = "\n".join(result.diff.lines)
    assert "real-env-value-must-not-appear" not in evidence
    assert "$FAKE_TOKEN" not in evidence
    assert "alpha-secret-value" not in evidence
    assert "TOKEN" in evidence
    assert "<redacted>" in evidence
    assert result.manifest.path_allowed is True
    assert result.manifest.explicit_yes is True
    assert result.manifest.no_network is True
    assert result.manifest.no_command_execution is True
    assert result.manifest.no_env_expansion is True
    assert result.manifest.no_real_home_write is True


def test_apply_blocks_home_sensitive_and_secret_like_paths_without_writing(tmp_path) -> None:
    """path policy 必须挡在写入前，尤其不能碰 home、运行产物或 secret-like 文件名。"""

    from agent.mcp_config_service import apply_mcp_config_plan, plan_add_mcp_server

    safe_path = _write_config(tmp_path)
    plan_result = plan_add_mcp_server(safe_path, name="gamma", command="gamma-server")
    blocked_paths = (
        Path.home() / ".config" / "mcp" / "config.json",
        tmp_path / ".env",
        tmp_path / "agent_log.jsonl",
        tmp_path / "sessions" / "mcp.json",
        tmp_path / "runs" / "mcp.json",
        tmp_path / "secret-config.json",
    )

    for blocked_path in blocked_paths:
        result = apply_mcp_config_plan(blocked_path, plan=plan_result.plan, yes=True)

        assert result.ok is False
        assert result.errors[0].code == "unsafe_path"
        assert not blocked_path.exists()


def test_apply_remove_does_not_execute_configured_server_command(tmp_path) -> None:
    """配置里的 command 只是文本；apply remove 不能启动 server 或 shell command。"""

    from agent.mcp_config_service import apply_mcp_config_plan, plan_remove_mcp_server

    marker = tmp_path / "server-command-ran"
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps({
            "mcpServers": {
                "danger": {
                    "command": f"python -c 'open({str(marker)!r}, \"w\").write(\"x\")'",
                }
            }
        }),
        encoding="utf-8",
    )
    plan_result = plan_remove_mcp_server(config_path, name="danger")

    result = apply_mcp_config_plan(config_path, plan=plan_result.plan, yes=True)

    assert result.ok is True
    assert not marker.exists()
    assert "danger" not in json.loads(config_path.read_text(encoding="utf-8"))["mcpServers"]


def test_cli_apply_uses_plan_packet_yes_and_redacted_presenter(tmp_path) -> None:
    """CLI apply 仍是薄 adapter：读 plan packet 后交给 service/presenter。"""

    from agent.mcp_config_service import plan_add_mcp_server, serialize_mcp_config_plan

    config_path = _write_config(tmp_path)
    before = config_path.read_text(encoding="utf-8")

    exit_code, output = _run_cli(["config", "apply", "--path", str(config_path)])
    assert exit_code == 2
    assert "plan" in output.lower()
    assert config_path.read_text(encoding="utf-8") == before

    plan_result = plan_add_mcp_server(
        config_path,
        name="gamma",
        command="gamma-server",
        env_specs=("API_KEY=literal-secret-value",),
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(serialize_mcp_config_plan(plan_result.plan), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    exit_code, output = _run_cli([
        "config",
        "apply",
        "--path",
        str(config_path),
        "--plan",
        str(plan_path),
    ])
    assert exit_code == 1
    assert "confirmation_required" in output
    assert config_path.read_text(encoding="utf-8") == before

    exit_code, output = _run_cli([
        "config",
        "apply",
        "--path",
        str(config_path),
        "--plan",
        str(plan_path),
        "--yes",
    ])
    assert exit_code == 0
    assert "Safety manifest" in output
    assert "literal-secret-value" not in output
    assert "<redacted>" in output


def test_plan_packet_and_apply_result_repr_do_not_leak_secret_values(tmp_path) -> None:
    """plan/apply 结果可以被 evidence packet 引用，但 repr 不能夹带 secret。"""

    from agent.mcp_config_service import (
        apply_mcp_config_plan,
        parse_mcp_config_plan_mapping,
        plan_add_mcp_server,
        serialize_mcp_config_plan,
    )

    config_path = _write_config(tmp_path)
    plan_result = plan_add_mcp_server(
        config_path,
        name="gamma",
        command="gamma-server",
        env_specs=("PASSWORD=super-secret-password",),
    )
    packet = serialize_mcp_config_plan(plan_result.plan)
    parsed_plan, errors = parse_mcp_config_plan_mapping(packet)
    result = apply_mcp_config_plan(config_path, plan=parsed_plan, yes=True)

    combined = f"{plan_result!r}\n{parsed_plan!r}\n{result!r}\n{result.diff.lines}"
    assert errors == ()
    assert result.ok is True
    assert "super-secret-password" not in combined
    assert "<redacted>" in combined


def test_apply_governance_layers_do_not_import_transport_runtime_or_network() -> None:
    """safe apply 属于 config workflow，不允许倒灌 runtime/transport/network。"""

    forbidden_modules = {"subprocess", "socket", "http.client", "urllib", "requests"}

    assert _module_imports(SERVICE_MODULE).isdisjoint(forbidden_modules)
    assert _module_imports(CLI_MODULE).isdisjoint(forbidden_modules)
