"""v0.4 主线 A · 本地 runtime artifact 治理（dry-run + 受控 archive --apply）。

定位（架构边界）：
    本模块覆盖 v0.4 主线 A 的两层操作：
      1) **dry-run inventory**（第一切片）：列出本地 runtime 产物
         （agent_log.jsonl / sessions/ / runs/）的 stat 元信息，零副作用。
      2) **archive --apply**（第二切片）：仅对 agent_log.jsonl 做带二次确认
         的原子 rename，不删除、不 gzip、不读取内容。

    模块**不**真正删除/压缩/读取这些文件的内容，**不**自动 rotate，**不**
    处理 sessions/ 和 runs/（它们语义不同：sessions 是 checkpoint 数据、
    runs 是外部工具产物，需要分别治理）。

为什么 archive --apply 默认仍是 dry-run：
    archive 是首个真正有 fs 副作用的操作。即使是 rename（不丢数据），也
    可能让"正在 tail -f"或"agent 主进程内嵌的 logger"短暂感知不到旧文件。
    所以 CLI 必须显式 `--apply` 才进入真删/真改路径，否则用户复制粘贴
    历史命令时不会误触。

为什么 --apply 必须精确等于 "yes"：
    `Y / y / yes please / 中文"是" / 任意非空` 都不算确认。这条契约让用户
    必须**用键盘敲 3 个字母**而不是按 Enter 一带而过；防止"无意识确认"。
    与 `git push --force-with-lease` 的设计思路相同：让 dangerous op 多走
    一步显式动作。

为什么本切片只做 mv，不做 gzip / 删除 / 自动 rotation：
    - mv 可逆（rename 回去即可），fs 副作用最小；
    - gzip 不可逆且让 `python main.py logs --tail` / `less` 失效；
    - 删除是不可恢复的；
    - 自动 rotation 必须改 `agent/logger.py` 的写路径并加 fd 重开/file lock，
      改 runtime 写入语义，超出"治理工具"边界，需要单独 milestone。

为什么不读取真实 agent_log.jsonl 内容：
    日志可能含历史未脱敏的 raw content（早期 prompt / tool_result 正文）。
    本模块只关心"它有多大、被谁 track"，不需要也不应该 open。

为什么 sessions / runs 不在 archive --apply 范围：
    sessions 是 checkpoint snapshot（删了无法 resume），runs 是 agent-tool
    -harness 等外部工具的痕迹（治理责任在外部工具）。混在一起 archive
    会让用户误以为"清理日志会丢 checkpoint"。

用户项目自定义入口：
    本模块当前对 v0.4 标准目录布局做硬编码（项目根 + sessions/ + runs/
    + agent_log.jsonl）；若用户项目结构不同，应通过参数显式覆盖。

如何通过 artifacts 查问题：
    DRY RUN 报告 stdout 自带 "DRY RUN" banner + 每条候选元信息。--apply
    输出 ArchiveResult 中 status / source / target / message 字段，可
    grep "ARCHIVE" 定位。本模块**绝不**打印任何文件正文。

未来扩展点（非本切片范围）：
    - `--apply --gzip` 归档自动压缩
    - per-session log 按 SESSION_ID 分文件
    - size/age-based 自动 rotation（需改 logger 写路径）
    - cleanup --apply 处理 sessions/ / runs/（需 sessions 治理 milestone）

什么是 mock / demo：
    无。所有逻辑都是真实 stat / git subprocess / Path.rename。测试通过
    tmp_path 假项目验证，**不**触碰真实 agent_log.jsonl 内容。
"""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# 阈值与 v0.2 health/check_log_size 对齐：超过 10MB 标记为"建议关注"，
# 但本模块**不**因此触发任何动作，只是在报告里加视觉提示。
_LARGE_SIZE_MB_THRESHOLD = 10.0

# archive --apply 必须精确等于此字符串才执行；任何变体（Y/y/yes please）
# 都拒绝。与 `git push --force-with-lease` 同样的"显式动作"设计哲学。
_REQUIRED_CONFIRM_TOKEN = "yes"


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
        "若要执行真实 archive，请加 --apply（仅 mv，不 gzip / 不删除；"
        "会要求输入 'yes' 二次确认）。"
    )
    return "\n".join(lines) + "\n"


# ============================================================
# 第二切片 · archive --apply 受控实现
# ============================================================


@dataclass
class ArchiveResult:
    """archive 操作的结构化结果，供 CLI 渲染 + 测试断言。

    字段语义：
      status: "skipped_no_source" | "cancelled" | "target_exists" | "archived"
      source: 原 agent_log.jsonl 路径（archive 后已不存在）
      target: 归档后的新路径（archive 成功才有意义；其他状态可为 None）
      message: 给用户的可读说明，包含 ARCHIVE 关键字便于 grep
    """

    status: str
    source: Path
    target: Path | None
    message: str


def _build_archive_target(source: Path, now: datetime | None = None) -> Path:
    """生成归档目标文件名 `<stem>.archived-YYYYMMDD-HHMMSS.<suffix>`。

    保留原后缀（.jsonl）的原因：
      - 让 `python main.py logs --tail` / `less` 等现有工具不需任何改造就
        能继续读历史归档；
      - 防止用户看到 `.archived` 后缀以为内容格式变了。

    时间戳精确到秒：实践中"同一秒内连续两次 --apply"几乎不可能（必须人工
    输入 yes），若真发生就让 `_archive_apply` 的目标已存在分支拒绝覆盖。
    """
    ts = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return source.with_name(f"{source.stem}.archived-{ts}{source.suffix}")


def archive_agent_log(
    project_root: Path,
    *,
    apply: bool,
    confirm_input: Callable[[], str] | None = None,
    now: datetime | None = None,
) -> ArchiveResult:
    """执行 agent_log.jsonl 的归档（dry-run 或受确认的 --apply）。

    设计要点（中文学习型说明）：
    1. **只动 agent_log.jsonl**：不碰 sessions/runs/.env，本模块的 sessions
       与 runs 仅在 dry-run inventory 中露面，--apply 路径根本不读它们。
    2. **默认 dry-run**：apply=False 时仅返回 "would archive ..." 的
       ArchiveResult，源文件零变化。
    3. **--apply 必须二次确认**：apply=True 时调用 confirm_input()，要求
       严格等于 "yes"（小写、无空白）才执行；任何变体一律取消。
    4. **零内容读取**：源文件只 stat（exists/size），从不 open。
    5. **原子 rename**：用 Path.rename（POSIX `os.rename` 包装），同 fs
       原子；不存在中间态。失败时 OS 抛异常，不吞。
    6. **不覆盖**：若目标 archive 路径已存在（极端情况：1 秒内重复 --apply），
       拒绝覆盖并返回 status="target_exists"，让用户人工介入。
    7. **不需要 file lock**：因为 `agent/logger.py` 每次 log_event 都
       open(LOG_FILE, "a") 而**不持久 fd**，rename 后下一次 log_event 自动
       创建新文件，无 fd 错引。加 lock 反而引入死锁可能。

    confirm_input 注入：
      生产路径默认走 `input("type 'yes' to confirm: ")`；测试路径传入
      lambda 返回固定字符串，避免 mock stdin 的脆弱性。
    """
    source = project_root / "agent_log.jsonl"

    if not source.exists():
        # 源不存在是常见情况（fresh checkout / 已 archive 过），友好退出。
        return ArchiveResult(
            status="skipped_no_source",
            source=source,
            target=None,
            message=f"ARCHIVE skipped: {source.name} 不存在，无需 archive。",
        )

    target = _build_archive_target(source, now=now)

    if not apply:
        size_mb = round(source.stat().st_size / (1024 * 1024), 2)
        return ArchiveResult(
            status="dry_run",
            source=source,
            target=target,
            message=(
                f"DRY RUN: would archive {source.name} "
                f"({size_mb} MB) -> {target.name}\n"
                "（加 --apply 才真正执行 mv；执行前会要求输入 'yes'）"
            ),
        )

    # --apply 路径：必须二次确认
    confirm = confirm_input or _default_confirm_input
    answer = confirm()
    if answer != _REQUIRED_CONFIRM_TOKEN:
        return ArchiveResult(
            status="cancelled",
            source=source,
            target=target,
            message=(
                f"ARCHIVE cancelled: 输入 {answer!r} 不等于 "
                f"{_REQUIRED_CONFIRM_TOKEN!r}，未执行任何操作。"
            ),
        )

    if target.exists():
        # 极端竞态：1 秒内重复 --apply。拒绝覆盖，让用户人工决定。
        return ArchiveResult(
            status="target_exists",
            source=source,
            target=target,
            message=(
                f"ARCHIVE refused: 目标 {target.name} 已存在，拒绝覆盖。"
                "请稍后再试或手动处理。"
            ),
        )

    # 真实副作用：原子 rename。失败让 OS 异常上抛，不吞。
    source.rename(target)

    return ArchiveResult(
        status="archived",
        source=source,
        target=target,
        message=(
            f"ARCHIVE done: {source.name} -> {target.name}\n"
            "提示：下一次 log_event 会自动创建新的 agent_log.jsonl；"
            "若有 tail -f / TUI 监控正在运行，需重新 attach。"
        ),
    )


def _default_confirm_input() -> str:
    """生产环境默认确认读取：从 stdin 阻塞读一行并 strip。

    抽出独立函数便于测试时注入替身（test 不依赖 sys.stdin mock）。
    刻意不接受 EOF 默认值，让 Ctrl-D 也算"未确认"。
    """
    try:
        return input("type 'yes' to confirm archive: ").strip()
    except EOFError:
        return ""
