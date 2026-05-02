"""Thin CLI adapter for MCP config management.

本层只解析 `mcp config ...` 参数、调用 service/use-case、交给 presenter 输出。
它不读取默认 home config、不写文件、不执行 MCP server、不连接网络；这些边界由
Slice 1 parser/policy 和 Pack 1 service tests 一起固定。
"""

from __future__ import annotations

import sys
from typing import TextIO

from agent.mcp_config_presenter import (
    render_apply_deferred,
    render_cli_error,
    render_config_list,
    render_plan_result,
    render_server_inspection,
    render_validation_result,
)
from agent.mcp_config_service import (
    inspect_mcp_server,
    list_mcp_config,
    plan_add_mcp_server,
    plan_remove_mcp_server,
    validate_mcp_config,
)


def run_mcp_config_cli(args: list[str], *, stdout: TextIO | None = None) -> int:
    """Run the MCP config subcommand and return a process-style exit code."""

    output = stdout or sys.stdout
    rest = list(args)
    if rest and rest[0] == "config":
        rest = rest[1:]
    if not rest:
        output.write(render_cli_error("missing subcommand"))
        return 2

    command = rest[0]
    command_args = rest[1:]

    if command == "apply":
        output.write(render_apply_deferred())
        return 2

    parsed, error = _parse_options(command_args)
    if error is not None:
        output.write(render_cli_error(error))
        return 2

    path = _single_value(parsed, "--path")
    if path is None:
        output.write(render_cli_error("missing --path"))
        return 2

    if command == "list":
        result = list_mcp_config(path)
        output.write(render_config_list(result))
        return 0 if result.ok else 1

    if command == "inspect":
        name = _single_value(parsed, "--name")
        if name is None:
            output.write(render_cli_error("missing --name"))
            return 2
        result = inspect_mcp_server(path, name)
        output.write(render_server_inspection(result))
        return 0 if result.ok else 1

    if command == "validate":
        result = validate_mcp_config(path)
        output.write(render_validation_result(result))
        return 0 if result.ok else 1

    if command == "plan-add":
        name = _single_value(parsed, "--name")
        server_command = _single_value(parsed, "--command")
        if name is None:
            output.write(render_cli_error("missing --name"))
            return 2
        if server_command is None:
            output.write(render_cli_error("missing --command"))
            return 2
        result = plan_add_mcp_server(
            path,
            name=name,
            command=server_command,
            args=tuple(parsed.get("--arg", ())),
            env_specs=tuple(parsed.get("--env", ())),
        )
        output.write(render_plan_result(result))
        return 0 if result.ok else 1

    if command == "plan-remove":
        name = _single_value(parsed, "--name")
        if name is None:
            output.write(render_cli_error("missing --name"))
            return 2
        result = plan_remove_mcp_server(path, name=name)
        output.write(render_plan_result(result))
        return 0 if result.ok else 1

    output.write(render_cli_error(f"unknown subcommand {command!r}"))
    return 2


def _parse_options(tokens: list[str]) -> tuple[dict[str, list[str]], str | None]:
    """解析简单 flag/value；允许 `--arg --safe` 这类以短横线开头的参数值。

    使用这个小 parser 是为了保持 CLI adapter 可控，同时避免 argparse 把 server
    arg 误判成 CLI option。业务含义仍由 service/use-case 决定。
    """

    values: dict[str, list[str]] = {}
    index = 0
    while index < len(tokens):
        option = tokens[index]
        if not option.startswith("--"):
            return {}, f"unexpected argument {option!r}"
        if index + 1 >= len(tokens):
            return {}, f"missing value for {option}"
        values.setdefault(option, []).append(tokens[index + 1])
        index += 2
    return values, None


def _single_value(options: dict[str, list[str]], name: str) -> str | None:
    values = options.get(name)
    if not values:
        return None
    return values[-1]
