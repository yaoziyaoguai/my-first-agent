"""Maintenance command routing for `main.py`.

学习型说明：
维护命令可以输出报告或转发到已有 CLI，但不能拥有 Runtime TaskState
状态迁移、不能写 checkpoint、不能进入交互式 agent loop。这里集中路由，
让 `main.py` 保持 thin process entrypoint。
"""

from __future__ import annotations

from pathlib import Path

from agent.runtime_events import RuntimeEventKind, command_event_transition


def _maintenance_command_transition(kind: RuntimeEventKind):
    """声明 health/logs 子命令是 no-op Runtime transition。"""

    outcome = command_event_transition(kind)
    if outcome.next_status is not None or outcome.should_checkpoint:
        raise RuntimeError(f"maintenance command must be no-op: {kind.value}")
    if (
        outcome.clear_pending_tool
        or outcome.clear_pending_user_input
        or outcome.advance_step
    ):
        raise RuntimeError(f"maintenance command cannot mutate task state: {kind.value}")
    return outcome


def dispatch_maintenance_command(
    argv: list[str],
    *,
    project_root: Path,
) -> int | None:
    """处理非交互维护命令；未命中时返回 None 让 main 进入 agent loop。"""

    # status 命令：provider 配置静态诊断（v0.12+ 使用统一 config.yaml 入口）
    if argv and argv[0] == "status":
        from agent.provider.diagnostics import (
            diagnose_provider_config_from_unified,
            render_diagnostic_report,
        )

        _maintenance_command_transition(RuntimeEventKind.HEALTH_COMMAND)
        diagnostic = diagnose_provider_config_from_unified(
            dotenv_path=project_root / ".env",
        )
        print(render_diagnostic_report(diagnostic))

        # R-G05: provider-visible tool-name diagnostic (surfaces dotted names to operator)
        try:
            import agent.tools  # noqa: F401  ensure tools registered
            from agent.provider.anthropic_http import validate_provider_tool_names
            from agent.tool_registry import get_model_visible_tools
            _invalid_names = validate_provider_tool_names(
                get_model_visible_tools(max_mcp_tools=5)
            )
            if _invalid_names:
                print()
                print("⚠️ Provider tool-name diagnostic:")
                for _n in _invalid_names:
                    print(f"   {_n}: chars invalid for ^[a-zA-Z0-9_-]+$")
                print("   (adapter auto-sanitizes at the seam; informational)")
        except Exception:
            pass

        if diagnostic.status == "error":
            return 2
        if diagnostic.status == "warn":
            return 1
        return 0

    # provider-diagnostics 命令：增强的 provider 配置诊断（支持 isolated dotenv）
    if argv and argv[0] == "provider-diagnostics":
        from agent.provider.diagnostics import (
            diagnose_provider_config_from_unified,
            diagnose_provider_config_isolated,
            render_diagnostic_report,
        )

        _maintenance_command_transition(RuntimeEventKind.HEALTH_COMMAND)

        isolated = "--isolated-dotenv" in argv[1:]
        if isolated:
            dotenv_path = project_root / ".env"
            if not dotenv_path.is_file():
                print(f"错误：项目 .env 文件不存在: {dotenv_path}")
                return 2
            print("=== Isolated Project .env Diagnostic ===\n")
            print("说明：此诊断清除了所有外层环境变量中的 provider 配置，")
            print(f"只从 {dotenv_path} 加载配置。\n")
            diagnostic = diagnose_provider_config_isolated(dotenv_path)
        else:
            diagnostic = diagnose_provider_config_from_unified(
                dotenv_path=project_root / ".env",
            )

        print(render_diagnostic_report(diagnostic))
        if diagnostic.status == "error":
            return 2
        if diagnostic.status == "warn":
            return 1
        return 0

    if len(argv) >= 2 and argv[0] == "mcp" and argv[1] == "config":
        from agent.mcp_config_cli import run_mcp_config_cli

        return run_mcp_config_cli(argv[1:])

    if argv and argv[0] == "demo":
        from agent.local_demo import run_demo_cli

        return run_demo_cli(argv[1:])

    if argv and argv[0] == "health":
        from agent.health_check import collect_health_results
        from agent.health_report import format_health_report, format_health_report_json

        _maintenance_command_transition(RuntimeEventKind.HEALTH_COMMAND)
        results = collect_health_results()
        if "--json" in argv[1:]:
            print(format_health_report_json(results))
        else:
            print(format_health_report(results))
        return 0

    if argv and argv[0] == "logs":
        return _dispatch_logs_command(argv[1:], project_root=project_root)

    if argv and argv[0] in {"sessions", "runs"}:
        return _dispatch_artifact_inventory_command(argv, project_root=project_root)

    if argv and argv[0] == "memory" and len(argv) >= 2 and argv[1] == "extract":
        from agent.memory_extraction_review import run_extraction_review_cli

        return run_extraction_review_cli()

    if argv and argv[0] == "memory" and len(argv) >= 2 and argv[1] in {
        "index",
        "archive",
    }:
        from agent.memory_maintenance_cli import run_memory_maintenance_cli

        return run_memory_maintenance_cli(argv[1:])

    return None


def _dispatch_logs_command(rest: list[str], *, project_root: Path) -> int:
    """处理 logs / logs cleanup；不读取 agent_log.jsonl 正文。"""

    from agent.log_viewer import render_logs

    _maintenance_command_transition(RuntimeEventKind.LOGS_COMMAND)

    if rest and rest[0] == "cleanup":
        from agent.log_cleanup import (
            archive_agent_log,
            collect_cleanup_candidates,
            format_cleanup_dry_run_report,
        )

        cleanup_args = rest[1:]
        apply_flag = "--apply" in cleanup_args
        candidates = collect_cleanup_candidates(project_root)
        print(format_cleanup_dry_run_report(candidates), end="")
        print()
        result = archive_agent_log(project_root, apply=apply_flag)
        print(result.message)
        return 0

    def _opt(name: str) -> str | None:
        if name in rest:
            idx = rest.index(name)
            if idx + 1 < len(rest):
                return rest[idx + 1]
        return None

    try:
        tail_str = _opt("--tail")
        tail = int(tail_str) if tail_str is not None else 50
    except ValueError:
        print(f"--tail 需要整数，得到：{tail_str!r}")
        return 2

    summary_mode = "--summary" in rest

    print(
        render_logs(
            tail=tail,
            session_id=_opt("--session"),
            event=_opt("--event"),
            tool=_opt("--tool"),
            include_observer="--include-observer" in rest,
            summary=summary_mode,
        )
    )
    return 0


def _dispatch_artifact_inventory_command(
    argv: list[str],
    *,
    project_root: Path,
) -> int:
    """处理 sessions/runs inventory，只读 metadata，不读取真实内容。"""

    from agent.local_artifacts import (
        format_artifact_inventory_report,
        inventory_known_artifact,
    )

    kind = argv[0]
    sub = argv[1] if len(argv) > 1 else None
    if sub != "inventory":
        print(
            f"用法：python main.py {kind} inventory\n"
            f"当前 v0.5 第三小步**只**支持只读 inventory；不支持 cleanup/apply/rotation。"
        )
        return 2

    inv = inventory_known_artifact(project_root, kind)
    print(format_artifact_inventory_report(inv), end="")
    return 0
