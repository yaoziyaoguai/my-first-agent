"""v0.4 主线 A 第一切片 · 本地 runtime artifact 清理 dry-run（只列出，不动文件）。

定位（架构边界）：
    本模块**只做** "如果你要清理本地 runtime 产物，候选清单长什么样" 的报告
    输出，**不**真正删除/归档/压缩任何文件，**不**读取这些文件的内容。
    它是 v0.4 主线 A（agent_log.jsonl 日志治理）的最小入口，与 v0.2
    `python main.py health` 的 log_size warning 形成互补：

      - `python main.py health`   → 给出 risk 等级 + 建议命令（人类可读警告）
      - `python main.py logs cleanup` → 给出可操作清单（DRY RUN inventory）

负责什么 / 不负责什么：
    负责：用 stat 收集 agent_log.jsonl / sessions/ / runs/ 的 路径、大小、
        是否存在、是否被 git tracked，渲染成 DRY RUN 报告字符串。
    不负责：真实删除、移动、压缩、归档、按时间筛选、按大小自动 rotate、
        读取或解析任一文件内容、修改 .gitignore、上报 telemetry、删除
        .env（.env 永远不进入候选清单，连 stat 都不做）。

为什么本切片不做真删除：
    1) 本地 runtime 产物（sessions / runs / 日志）可能正被另一个长跑进程
       使用，盲删可能导致正在写入的进程崩溃；
    2) 用户可能正在做诊断分析，需要保留完整证据链；
    3) 本切片先给出 inventory + 安全提示（git tracked? 已被 ignore?），让
       用户用 shell 命令自行决定如何处理；
    4) `--apply` 真删需要更严格的并发安全 / 备份 / 回滚机制，属下一切片。

用户项目自定义入口：
    本模块当前对 v0.4 标准目录布局（项目根 + sessions/ + runs/）做硬编码；
    若用户项目结构不同，应通过 `paths_to_inspect` 参数显式覆盖（保留为
    后续扩展点，本 MVP 默认值即可覆盖 my-first-agent 自身布局）。

如何通过 artifacts 查问题：
    DRY RUN 报告 stdout 自带 "DRY RUN" banner + 每条候选的 (path, size,
    exists, gitignored, git_tracked) 元信息；不打印任何文件正文。若用户
    报告 "为什么我的 sessions 目录没列出"，请检查 PROJECT_DIR 是否被
    config.PROJECT_DIR 正确识别。

未来扩展点（非本切片范围）：
    - `--apply` 真删（需要并发锁 + 备份目录 + 回滚）
    - size-based / age-based 自动 rotation
    - per-session log 按 SESSION_ID 分文件
    - gzip 归档自动压缩
    - cleanup 后自动 vacuum（释放磁盘）

什么是 mock / demo（无）：
    本模块所有逻辑都是真实 stat + 真实 git 检查；不存在 mock。但其默认
    阈值（如 dry-run 中"大文件" 提示标记 >10MB）参考 v0.2 health 的
    阈值，未来若调整需统一两处。
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

# 阈值与 v0.2 health/check_log_size 对齐：超过 10MB 标记为"建议关注"，
# 但本模块**不**因此触发任何动作，只是在报告里加视觉提示。
_LARGE_SIZE_MB_THRESHOLD = 10.0


@dataclass
class CleanupCandidate:
    """单个候选清理目标的元信息（不含文件内容）。

    本 dataclass 只保存 stat 级元数据：路径、大小、存在性、git 状态。
    这些字段都不需要读文件内容，能保证 dry-run 零副作用、零信息泄漏。
    """

    label: str
    path: Path
    exists: bool
    size_bytes: int
    gitignored: bool
    git_tracked: bool


def _compute_size_bytes(path: Path) -> int:
    """计算路径的总字节数（不读取内容，仅 stat）。

    单文件：直接 stat；目录：递归累加所有文件 stat（也仅 stat，不 open）。
    异常吞掉返回 0，符合"observability 不能改变 runtime 行为"的边界。
    """
    if not path.exists():
        return 0
    try:
        if path.is_file():
            return path.stat().st_size
        total = 0
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += child.stat().st_size
            except OSError:
                # 单个 child stat 失败不影响整体报告，跳过即可。
                continue
        return total
    except OSError:
        return 0


def _is_gitignored(path: Path, project_root: Path) -> bool:
    """通过 `git check-ignore` 判断路径是否被 .gitignore 忽略。

    用 subprocess 调 git，不引入新依赖。git 命令失败（不在 git 仓库 / 路径
    不存在）一律返回 False（保守不报"已 ignore"，避免误导用户认为安全）。
    """
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=str(project_root),
            capture_output=True,
            timeout=5,
        )
        # check-ignore 返回 0 = ignored，返回 1 = not ignored，其他 = 异常
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _is_git_tracked(path: Path, project_root: Path) -> bool:
    """通过 `git ls-files --error-unmatch` 判断路径是否被 git track。

    track 状态比 ignore 更危险——若候选清理目标已被 track，意味着用户可能
    误把日志/sessions 加入了 git，dry-run 报告必须显眼提示这点。
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path)],
            cwd=str(project_root),
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def collect_cleanup_candidates(project_root: Path) -> list[CleanupCandidate]:
    """收集 my-first-agent 标准布局下的清理候选元信息。

    硬编码扫描 3 个候选位置（agent_log.jsonl / sessions/ / runs/），与
    .gitignore 中的条目一致。**不**扫描 .env / config.py / agent/ 等源码
    目录——本切片只关心运行时产生的本地大文件。
    """
    targets = [
        ("agent_log.jsonl", project_root / "agent_log.jsonl"),
        ("sessions/", project_root / "sessions"),
        ("runs/", project_root / "runs"),
    ]
    candidates: list[CleanupCandidate] = []
    for label, path in targets:
        exists = path.exists()
        candidates.append(
            CleanupCandidate(
                label=label,
                path=path,
                exists=exists,
                size_bytes=_compute_size_bytes(path) if exists else 0,
                gitignored=_is_gitignored(path, project_root) if exists else False,
                git_tracked=_is_git_tracked(path, project_root) if exists else False,
            )
        )
    return candidates


def format_cleanup_dry_run_report(candidates: list[CleanupCandidate]) -> str:
    """把候选清单渲染成人类可读的 DRY RUN 报告字符串。

    报告每行包含：label / 路径 / 大小（MB）/ 存在 / gitignored / git_tracked。
    末尾给出明确的 "DRY RUN: no files modified" 注脚 + 建议下一步命令。
    格式刻意简单，方便 grep / pipe；不用任何颜色 ANSI 码，避免重定向时
    污染输出。
    """
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("DRY RUN: agent log / runtime artifacts cleanup inventory")
    lines.append("=" * 60)
    lines.append("（本命令只列出候选，绝不删除/移动/压缩任何文件）")
    lines.append("")

    for c in candidates:
        size_mb = round(c.size_bytes / (1024 * 1024), 2)
        large_marker = " [LARGE]" if size_mb > _LARGE_SIZE_MB_THRESHOLD else ""
        if not c.exists:
            lines.append(f"- {c.label}: 不存在 (skip)")
            continue
        warn_tracked = " [WARN: 已被 git track！]" if c.git_tracked else ""
        ignored_tag = " (gitignored)" if c.gitignored else ""
        lines.append(
            f"- {c.label}: {size_mb} MB{large_marker}{ignored_tag}{warn_tracked}"
        )
        lines.append(f"    path: {c.path}")

    lines.append("")
    lines.append("DRY RUN: no files were modified.")
    lines.append(
        "如需手动归档，可参考 python main.py health 中 log_size 检查的建议命令；"
        "本切片不提供 --apply 真删（需要并发锁 / 备份 / 回滚，属下一切片范围）。"
    )
    return "\n".join(lines) + "\n"
