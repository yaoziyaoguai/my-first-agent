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
                "人工归档（不会自动执行，复制粘贴）：\n"
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
