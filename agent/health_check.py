"""项目健康检查（v0.3 M2 升级版）。

每个 check_* 函数返回一个**字段稳定**的结构化 dict：

{
    "status": "pass" | "warn" | "error" | "skip",
    "current_value": <可读字符串或数值>,   # 当前观察值，例如 "93.23 MB" / 128 / 4
    "path": <相关文件或目录的相对路径>,     # 用户可以直接 cd / ls 的路径
    "risk": <一句话解释风险>,              # 中文，避免英文 jargon
    "action": <推荐手动命令，单行>,        # 用户可复制粘贴，但不会自动执行
    "message": <短总结>,                  # 兼容 v0.2 / cli_renderer.summarize_health
    # 可选：详情字段（issues / files 列表等）
}

设计目标：
- 让 health 报告从「⚠️ workspace_lint: warn / 有告警」升级为
  「workspace_lint: 7 文件，4 处 lint 错误（含 unused import: os）；
   建议：python -m ruff check workspace/」
- 不自动删除任何用户日志/session/checkpoint：所有 action 都是字符串建议，
  执行权交回用户。
"""
import subprocess
from pathlib import Path

# 中文学习边界：health check 需要检查工具注册表的完整性（tool_registry_integrity /
# tool_risk_distribution），必须在模块加载时显式触发 agent.tools 的导入以完成
# @register_tool 装饰器注册。不把这个 import 藏在 check 函数内部，是为了让副作用
# （工具注册）在 health check 入口处显式可见，而不是隐藏在个别函数的执行路径中。
# 这不会改变 tool_registry 的注册机制，也不修改任何 agent/tools/*.py。
import agent.tools  # noqa: F401  触发所有 @register_tool 装饰器
from agent.logger import log_event
from config import PROJECT_DIR


def _relative_path(p: Path) -> str:
    """把绝对路径转成相对 PROJECT_DIR 的可读形式，避免泄漏家目录路径。"""
    try:
        return str(p.relative_to(PROJECT_DIR))
    except ValueError:
        return str(p)


def check_workspace_lint():
    """检查 workspace 下所有 Python 文件的 lint 状态。"""
    workspace = PROJECT_DIR / "workspace"
    rel_path = _relative_path(workspace)
    if not workspace.exists():
        return {
            "status": "skip",
            "current_value": "目录不存在",
            "path": rel_path,
            "risk": "无",
            "action": "无需操作",
            "message": "workspace 目录不存在",
        }

    py_files = list(workspace.glob("**/*.py"))
    if not py_files:
        return {
            "status": "skip",
            "current_value": "0 .py 文件",
            "path": rel_path,
            "risk": "无",
            "action": "无需操作",
            "message": "workspace 内无 Python 文件",
        }

    try:
        result = subprocess.run(
            ["ruff", "check"] + [str(f) for f in py_files],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return {
                "status": "pass",
                "current_value": f"{len(py_files)} 文件，0 lint 错误",
                "path": rel_path,
                "risk": "无",
                "action": "无需操作",
                "message": "workspace lint 通过",
                "file_count": len(py_files),
            }

        # 解析 ruff 输出，截前 3 行作为人类可读的具体来源
        issue_lines = [
            line for line in result.stdout.splitlines() if line.strip()
        ]
        sample = "; ".join(issue_lines[:3])
        return {
            "status": "warn",
            "current_value": f"{len(py_files)} 文件，有 lint 错误",
            "path": rel_path,
            "risk": (
                "workspace 是 Agent 自身写出的 scratch 目录，"
                "lint 错误本身不影响 Runtime；但里面可能混了过期样本，"
                "需要人工 review 后再决定是 fix 还是删除。"
            ),
            "action": (
                f"python -m ruff check {rel_path}"
                "（先看具体来源；不要直接 --fix，可能含有意保留的反例）"
            ),
            "message": f"workspace lint 发现问题：{sample[:200]}"
            if sample
            else "workspace lint 有告警",
            "file_count": len(py_files),
            "issues": result.stdout.strip(),
        }
    except Exception as e:
        return {
            "status": "error",
            "current_value": "执行失败",
            "path": rel_path,
            "risk": "ruff 不可用或 workspace 文件异常",
            "action": "检查 ruff 是否安装：.venv/bin/python -m ruff --version",
            "message": f"workspace lint 检查异常：{e}",
        }


def check_backup_accumulation():
    """检查 .bak 备份文件是否堆积过多。"""
    bak_files = list(PROJECT_DIR.rglob("*.bak"))
    count = len(bak_files)
    if count > 10:
        sample = ", ".join(_relative_path(f) for f in bak_files[:5])
        return {
            "status": "warn",
            "current_value": f"{count} 个 .bak 文件",
            "path": ".",
            "risk": "备份文件长期累积会让仓库扫描变慢，且容易混淆当前版本。",
            "action": (
                "人工 review 后归档或删除（举例）：\n"
                "  ls -t **/*.bak | head\n"
                "  mkdir -p ~/Documents/my-first-agent-archives/backups\n"
                "  mv path/to/some.bak ~/Documents/my-first-agent-archives/backups/"
            ),
            "message": f"发现 {count} 个备份文件，建议清理（前 5 个：{sample}）",
            "count": count,
            "files": [_relative_path(f) for f in bak_files[:20]],
        }
    return {
        "status": "pass",
        "current_value": f"{count} 个 .bak 文件",
        "path": ".",
        "risk": "无",
        "action": "无需操作",
        "message": "备份文件数量正常",
        "count": count,
    }


def check_log_size():
    """检查 agent_log.jsonl 大小。"""
    log_file = PROJECT_DIR / "agent_log.jsonl"
    rel_path = _relative_path(log_file)
    if not log_file.exists():
        return {
            "status": "pass",
            "current_value": "0 MB（不存在）",
            "path": rel_path,
            "risk": "无",
            "action": "无需操作",
            "message": "日志文件不存在",
        }

    size_mb = round(log_file.stat().st_size / (1024 * 1024), 2)
    if size_mb > 10:
        return {
            "status": "warn",
            "current_value": f"{size_mb} MB",
            "path": rel_path,
            "risk": (
                "日志文件持续增长会拖慢启动 grep / observer 检索，"
                "并占用磁盘空间。不影响 Runtime 正确性，但长期不归档会让"
                "诊断越来越慢。"
            ),
            "action": (
                "先看摘要再决定归档（不会自动执行，复制粘贴）：\n"
                "  python main.py logs --tail 100        # v0.3 M4 摘要查看\n"
                f"  mv {rel_path} {rel_path}.bak.$(date +%Y%m%d-%H%M%S)\n"
                "  mkdir -p ~/Documents/my-first-agent-archives/\n"
                f"  mv {rel_path}.bak.* ~/Documents/my-first-agent-archives/"
            ),
            "message": f"日志文件已达 {size_mb} MB，建议归档或清理",
            "size_mb": size_mb,
        }
    return {
        "status": "pass",
        "current_value": f"{size_mb} MB",
        "path": rel_path,
        "risk": "无",
        "action": "无需操作",
        "message": "日志文件大小正常",
        "size_mb": size_mb,
    }


def check_session_accumulation():
    """检查 session 快照是否堆积。"""
    session_dir = PROJECT_DIR / "sessions"
    rel_path = _relative_path(session_dir)
    if not session_dir.exists():
        return {
            "status": "pass",
            "current_value": "0 个快照（目录不存在）",
            "path": rel_path,
            "risk": "无",
            "action": "无需操作",
            "message": "sessions 目录不存在",
        }

    sessions = list(session_dir.glob("*.json"))
    count = len(sessions)
    if count > 50:
        return {
            "status": "warn",
            "current_value": f"{count} 个快照",
            "path": rel_path,
            "risk": (
                "session 快照长期累积会占磁盘空间，且 grep 历史 session 时"
                "扫描成本高。不影响 Runtime 正确性。"
            ),
            "action": (
                "人工归档（不会自动执行，复制粘贴）：\n"
                "  mkdir -p ~/Documents/my-first-agent-archives/sessions/\n"
                f"  mv {rel_path}/*.json ~/Documents/my-first-agent-archives/sessions/"
            ),
            "message": f"发现 {count} 个 session 快照，建议归档",
            "count": count,
        }
    return {
        "status": "pass",
        "current_value": f"{count} 个快照",
        "path": rel_path,
        "risk": "无",
        "action": "无需操作",
        "message": "session 数量正常",
        "count": count,
    }


def check_tool_registry_integrity():
    """检查所有注册工具是否具有完整的治理 metadata。

    每个工具应包含 name / description / capability / risk_level / output_policy /
    input_schema。缺失项可能导致工具无法被正确审计或确认策略不完整。
    元工具（meta_tool=True）豁免 output_policy 检查。
    """
    from agent.tool_registry import TOOL_REGISTRY

    if not TOOL_REGISTRY:
        return {
            "status": "error",
            "current_value": "0 个已注册工具",
            "path": "agent/tools/ + agent/tool_registry.py",
            "risk": "工具注册表为空——Agent 没有任何可执行能力。",
            "action": "检查 agent/tools/__init__.py 是否正确导入所有工具模块",
            "message": "工具注册表为空",
        }

    required_fields = (
        "name", "description", "parameters", "capability", "risk_level", "output_policy"
    )
    issues: list[str] = []
    meta_tool_count = 0
    for name, info in TOOL_REGISTRY.items():
        if info.get("meta_tool"):
            meta_tool_count += 1
        # 使用 is None 而非 not info.get(f)，因为 parameters={}（零参数工具）
        # 是合法的 falsy 值，不应被误判为缺失字段。
        missing = [f for f in required_fields if info.get(f) is None]
        if missing:
            issues.append(f"工具 '{name}' 缺少字段: {missing}")

    total = len(TOOL_REGISTRY)
    business_tools = total - meta_tool_count

    if issues:
        return {
            "status": "error",
            "current_value": f"{total} 工具（{meta_tool_count} 元工具），{len(issues)} 个有缺失",
            "path": "agent/tool_registry.py",
            "risk": "工具 metadata 缺失会导致审计不完整、策略评估失效。",
            "action": f"检查以下工具: {', '.join(issues[:3])}",
            "message": f"工具 registry 有 {len(issues)} 处 metadata 缺失",
            "issues": issues,
        }
    return {
        "status": "pass",
        "current_value": (
            f"{total} 工具（{business_tools} 业务 + {meta_tool_count} 元工具），metadata 完整"
        ),
        "path": "agent/tool_registry.py",
        "risk": "无",
        "action": "无需操作",
        "message": f"工具 registry 正常：{total} 工具",
        "tool_count": total,
        "business_tools": business_tools,
        "meta_tools": meta_tool_count,
    }


def check_tool_risk_distribution():
    """检查工具风险等级分布，标记异常集中。

    如果所有工具都是 high risk，说明 risk 赋值过于保守或缺失细粒度分类。
    如果所有工具都是 low risk，说明可能存在风险低估。
    """
    from agent.tool_registry import get_tool_specs

    specs = get_tool_specs()
    if not specs:
        return {
            "status": "skip",
            "current_value": "无工具",
            "path": "agent/tool_registry.py",
            "risk": "无",
            "action": "无需操作",
            "message": "无工具，跳过风险分布检查",
        }

    risk_counts: dict[str, int] = {}
    capability_counts: dict[str, int] = {}
    for spec in specs:
        risk = spec.get("risk_level", "unknown")
        risk_counts[risk] = risk_counts.get(risk, 0) + 1
        cap = spec.get("capability", "unknown")
        capability_counts[cap] = capability_counts.get(cap, 0) + 1

    high_count = risk_counts.get("high", 0)
    total = len(specs)
    high_ratio = high_count / total if total > 0 else 0

    warnings: list[str] = []
    if high_ratio > 0.8 and total > 2:
        warnings.append(
            f"{high_count}/{total} 工具标记为 high risk（{high_ratio:.0%}），"
            "如果大部分是只读或低风险操作，建议细化 risk 赋值。"
        )
    if "unknown" in risk_counts:
        warnings.append(
            f"{risk_counts['unknown']} 个工具的 risk_level 未知，应补齐。"
        )

    status = "warn" if warnings else "pass"
    return {
        "status": status,
        "current_value": (
            f"risk 分布: {', '.join(f'{k}:{v}' for k, v in sorted(risk_counts.items()))}; "
            f"capability: {', '.join(f'{k}:{v}' for k, v in sorted(capability_counts.items()))}"
        ),
        "path": "agent/tool_registry.py",
        "risk": "; ".join(warnings) if warnings else "无",
        "action": (
            "检查高 risk 工具是否确实需要高 risk；细化工具 capability 分类"
            if warnings else "无需操作"
        ),
        "message": (
            "工具风险分布正常"
            if status == "pass"
            else f"工具风险分布需关注: {'; '.join(warnings)}"
        ),
        "risk_counts": risk_counts,
        "capability_counts": capability_counts,
        "total_tools": total,
    }


def check_mcp_config_readiness():
    """检查 MCP 体系的安全接入选型状态。

    当前阶段默认不启用 MCP。本检查验证 MCP 模块可用性、policy/sanitizer/audit
    核心函数可调用性、bridge 状态和 registry 中 MCP tools 的 metadata。
    不启动 MCP server，不执行 tools/call。
    """
    findings: list[str] = []
    smoke_results: dict[str, str] = {}

    # 检查核心 MCP 模块是否存在
    for mod_name in ("agent.mcp", "agent.mcp_policy", "agent.mcp_audit",
                     "agent.mcp_sanitizer", "agent.mcp_models"):
        try:
            __import__(mod_name)
            smoke_results[mod_name] = "ok"
        except ImportError:
            findings.append(f"{mod_name} 不可用")
            smoke_results[mod_name] = "missing"

    if findings:
        return {
            "status": "error",
            "current_value": f"{len(findings)} 个 MCP 模块不可用",
            "path": "agent/mcp*.py",
            "risk": "MCP 安全体系不完整，无法安全接入外部工具。",
            "action": f"修复缺失模块: {', '.join(findings)}",
            "message": f"MCP 模块缺失: {', '.join(findings)}",
            "missing_modules": findings,
            "smoke_results": smoke_results,
        }

    # policy gate smoke: 用 fake config 验证 evaluate_server_policy 可调用
    try:
        from agent.mcp_models import MCPServerConfig
        from agent.mcp_policy import evaluate_server_policy

        fake_server = MCPServerConfig(name="smoke_test", command="echo", enabled=True)
        result = evaluate_server_policy(
            fake_server,
            server_allowlist=frozenset(),
        )
        if result.decision == "blocked":
            smoke_results["policy_gate"] = "ok"
        else:
            findings.append("policy gate smoke: 空 allowlist 未返回 blocked")
            smoke_results["policy_gate"] = "unexpected"
    except Exception as e:
        findings.append(f"policy gate smoke 异常: {e}")
        smoke_results["policy_gate"] = "error"

    # sanitizer smoke: 验证 sanitize_description 可调用且返回带前缀的结果
    try:
        from agent.mcp_sanitizer import sanitize_description

        sanitized = sanitize_description("test tool", server_name="smoke")
        if "[MCP:smoke]" in sanitized:
            smoke_results["sanitizer"] = "ok"
        else:
            findings.append("sanitizer smoke: 描述缺少来源标记")
            smoke_results["sanitizer"] = "missing_prefix"
    except Exception as e:
        findings.append(f"sanitizer smoke 异常: {e}")
        smoke_results["sanitizer"] = "error"

    # audit emitter smoke: 验证 MCP audit 函数存在且可调用
    try:
        from agent.mcp_audit import emit_mcp_server_discovered

        event = emit_mcp_server_discovered("smoke_srv")
        if event.server_name == "smoke_srv":
            smoke_results["audit_emitter"] = "ok"
        else:
            smoke_results["audit_emitter"] = "unexpected"
    except Exception as e:
        findings.append(f"audit emitter smoke 异常: {e}")
        smoke_results["audit_emitter"] = "error"

    # registry audit: 检查 TOOL_REGISTRY 中 MCP tools 的 metadata 完整性
    try:
        from agent.tool_registry import TOOL_REGISTRY

        mcp_tools = {
            name: info
            for name, info in TOOL_REGISTRY.items()
            if info.get("capability") == "mcp_tool"
        }
        mcp_missing_prefix = [
            name
            for name, info in mcp_tools.items()
            if "[MCP:" not in info.get("description", "")
        ]
        if mcp_missing_prefix:
            findings.append(
                f"{len(mcp_missing_prefix)} 个 MCP tools 缺少来源标记"
            )
        smoke_results["registry_mcp_tools"] = str(len(mcp_tools))
    except Exception:
        smoke_results["registry_mcp_tools"] = "error"

    # bridge mode detection
    try:
        import os
        bridge_enabled = os.getenv("MY_FIRST_AGENT_MCP_ENABLE", "")
        smoke_results["bridge_enabled"] = (
            "yes" if bridge_enabled.strip() in ("1", "true", "yes")
            else "no"
        )
    except Exception:
        smoke_results["bridge_enabled"] = "unknown"

    status = "warn" if findings else "pass"
    return {
        "status": status,
        "current_value": (
            "MCP 安全体系就绪（policy gate + audit + sanitizer + bridge readiness）。"
            "真实 MCP server 接入默认禁用，需显式 allowlist。"
        ),
        "path": "agent/mcp*.py + agent/mcp_bridge.py",
        "risk": "; ".join(findings) if findings else "无",
        "action": (
            "如需启用 MCP: 设置 MY_FIRST_AGENT_MCP_ENABLE=1 并提供 allowlist。"
            "当前只支持 stdio + dry-run 模式。"
        ),
        "message": "MCP 安全体系就绪" if status == "pass" else f"MCP 有 {len(findings)} 个关注项",
        "smoke_results": smoke_results,
        "findings": findings,
    }


def check_runs_accumulation():
    """检查 runs/ 目录下的 trace 文件是否堆积过多。"""
    runs_dir = PROJECT_DIR / "runs"
    rel_path = _relative_path(runs_dir)
    if not runs_dir.exists():
        return {
            "status": "pass",
            "current_value": "0 个文件（目录不存在）",
            "path": rel_path,
            "risk": "无",
            "action": "无需操作",
            "message": "runs 目录不存在",
        }

    run_files = list(runs_dir.glob("*.jsonl"))
    count = len(run_files)
    if count > 20:
        return {
            "status": "warn",
            "current_value": f"{count} 个 trace 文件",
            "path": rel_path,
            "risk": "trace 文件长期累积占用磁盘空间，且不影响 Runtime 正确性。",
            "action": (
                "人工清理旧 trace 文件（不会自动执行，复制粘贴）：\n"
                f"  ls -t {rel_path}/*.jsonl | tail -n +21 | xargs rm"
            ),
            "message": f"runs/ 下发现 {count} 个 trace 文件，建议清理旧文件",
            "count": count,
        }
    return {
        "status": "pass",
        "current_value": f"{count} 个 trace 文件",
        "path": rel_path,
        "risk": "无",
        "action": "无需操作",
        "message": "runs 文件数量正常",
        "count": count,
    }


def collect_health_results():
    """运行所有健康检查并写入 log_event，但**不打印**任何东西。

    所有渲染交给 agent/health_report.py 完成。这样：
    - cli_renderer.summarize_health 可以直接用结果做单行摘要
    - format_health_report 做完整结构化报告
    - format_health_report_json 做 --json 输出
    - 测试可以直接断言结构，不用 capture stdout
    """
    checks = {
        "workspace_lint": check_workspace_lint,
        "backup_accumulation": check_backup_accumulation,
        "log_size": check_log_size,
        "session_accumulation": check_session_accumulation,
        "runs_accumulation": check_runs_accumulation,
        "tool_registry_integrity": check_tool_registry_integrity,
        "tool_risk_distribution": check_tool_risk_distribution,
        "mcp_config_readiness": check_mcp_config_readiness,
    }
    results = {name: fn() for name, fn in checks.items()}
    log_event("health_check", results)
    return results


def run_health_check(verbose: bool = True):
    """v0.2 兼容入口：默认 verbose=True 时打印 v0.3 M2 结构化报告。

    背后只是 collect_health_results + format_health_report 的组合。
    把入口保留是为了不破坏 init_session / 测试中既有的调用方。
    """
    results = collect_health_results()
    if verbose:
        # 延迟 import 避免循环依赖（health_report 用 cli_renderer 的纯函数风格）。
        from agent.health_report import format_health_report

        print(format_health_report(results))
    return results
