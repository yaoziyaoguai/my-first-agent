"""v0.5 Phase 1 第三小步 · 本地 runtime artifact 只读 inventory（DRY RUN）。

定位（架构边界）：
    本模块覆盖 v0.5 第三小步的"看一眼本地产物长什么样"——sessions/ 与
    runs/ 目录的**结构化 metadata-only** 盘点。与 v0.4 ``agent/log_cleanup``
    形成两层分工：
      - ``log_cleanup``：拥有 agent_log.jsonl archive --apply 的有副作用
        路径，以及"3 个候选位置"的粗粒度 dry-run；
      - ``local_artifacts``（本模块）：拥有**零副作用**的细粒度 inventory
        ——按文件聚合 count / total_bytes / oldest_mtime / newest_mtime /
        per-extension 分组 / per-prefix 分组（例如 ``session_`` / 16-hex-id
        前缀的 run jsonl）。

    模块**不**做：
      - 不读取任何文件**内容**（仅 Path.stat() + Path.iterdir() / os.scandir
        遍历 metadata）；
      - 不删除、不移动、不压缩、不写文件、不打开文件做 read/write；
      - 不区分"该清理还是该保留"，**不**调用 archive，**不**承担 cleanup
        语义；
      - 不递归进 sessions/<id>/ 子目录读 checkpoint JSON 字段（仅在顶层
        `iterdir()` 看条目元信息）；
      - 不接 --apply（任何 cleanup/rotation 都属于未来 milestone）。

为什么 v0.5 第三小步选这个：
    1) 与 v0.4 ``log_cleanup`` dry-run 同模式（已验证安全路径），扩展
       治理面到 sessions/runs；
    2) **零运行时副作用**（不动 chat/loop/handler/runtime），不影响
       v0.5 前两小步的 LoopContext/ConfirmationContext helper 边界；
    3) 比 ``_dispatch_pending_confirmation`` helper 风险低得多——后者
       要碰 5 条 confirmation dispatch 分支语义，需要先写 characterization
       tests 才能安全推进。

为什么本轮**只**读 metadata，不读内容：
    - sessions/<id>.json 是 checkpoint 快照，可能包含历史 user_goal /
      tool_traces / messages 中未脱敏的对话片段；inventory 的目的是回答
      "有多少 / 多大 / 多旧"，不是"里面是什么"；
    - runs/*.jsonl 是 agent-tool-harness 等外部工具的产物，治理责任在
      外部工具，本模块不应该窥探正文；
    - 由 AST 守卫测试钉死：模块源码不得包含 ``open(``、``os.unlink``、
      ``os.remove``、``os.rename``、``os.replace``、``shutil.rmtree``、
      ``shutil.move``、``Path.unlink``、``Path.rename``、``Path.replace``、
      ``Path.write_text``、``Path.write_bytes`` 等任何"可能读内容/可能
      mutate fs"的调用。

为什么 inventory 与 cleanup/apply/rotation 是不同阶段：
    - inventory：纯观察，零副作用，用户可天天跑；
    - cleanup --apply：删除/移动，不可逆或半可逆，必须显式 confirm；
    - rotation：改 runtime 写入语义（轮转活动文件），需要 fd 重开 / file
      lock，超出"治理工具"边界，需要单独 milestone。
    把 inventory 单独做完，未来要加 --apply 时调用方已经熟悉数据结构。

为什么不做 ``_dispatch_pending_confirmation``：
    那个 helper 要碰 chat() 内 5 条 if/return 链（plan / step /
    user_input / feedback_intent / tool_confirmation），dispatch 顺序
    与 status 互斥性是当前设计契约；任何"看似等价的合并"都可能在某些
    边缘 status 组合下行为不同。需要先写 characterization tests 钉死
    5 种 status 各自命中哪个 handler，再抽 helper。本轮先做更安全的
    inventory，把 confirmation dispatch helper 放到 v0.5 第四/第五
    小步评估。

用户项目自定义入口（未来扩展点）：
    本模块当前对 v0.5 标准目录布局做硬编码（项目根 + sessions/ + runs/）。
    若用户项目结构不同，可通过 ``inventory_artifact_directory(path, kind)``
    显式传入任意目录复用，无需改 helper 签名。

如何通过 artifacts 查问题：
    CLI ``python main.py sessions inventory`` / ``python main.py runs
    inventory`` 始终打印 ``DRY RUN``  banner + 结构化报告。报告字段：
    kind / path / exists / file_count / total_bytes / oldest_mtime /
    newest_mtime / by_extension / by_prefix / sample_paths。任何字段
    缺失或异常时，CLI 会显示 ``no entries`` 或 ``directory missing``，
    永不假装成功。

注意（窗口/pane 上下文混乱时）：
    本模块属 my-first-agent 项目；当前 iTerm 标题或 shell prompt 可能
    显示 agent-tool-harness / mindforge 等其他项目，但本模块的归属应
    永远以 ``pwd`` 为准。模块本身与其他项目零耦合。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ============================================================================
# DRY RUN banner：所有 CLI 输出统一带这个前缀，让用户**不可能**误以为
# 本工具做了任何修改。即使后续未来加了 --apply，这个 banner 也只在
# read-only 路径打印，由 CLI 严格控制。
# ============================================================================
_DRY_RUN_BANNER = "DRY RUN · 本工具仅读取 metadata，**不**修改/删除/移动任何文件。"


@dataclass(frozen=True, slots=True)
class ArtifactInventory:
    """一次目录 inventory 的不可变结果。

    字段说明（全部为 read-only metadata）：
      - ``kind``：artifact 类型标签，目前是 "sessions" / "runs"，
        未来可扩展（"workspace" / "memory" 等同样需要观察的本地产物）；
      - ``path``：被 inventory 的目录路径（Path 对象）；
      - ``exists``：目录是否存在；不存在时其余统计字段为 0/空，CLI
        会输出 ``directory missing``；
      - ``file_count`` / ``total_bytes``：顶层条目（不含子目录递归内
        的内容）的文件数 / 字节总和；
      - ``oldest_mtime`` / ``newest_mtime``：顶层文件 mtime 极值
        （ISO-8601 UTC 字符串），无文件时为 None；
      - ``by_extension``：``{".jsonl": 12, ".json": 3}`` 这样的 ext
        -> count 映射，方便看清产物类型分布；
      - ``by_prefix``：按文件名前缀的粗粒度分组（默认按下划线/连字符
        前的第一段聚合，比如 ``session_xxx.json`` 全归 ``session``）；
      - ``sample_paths``：取最多 5 个样本路径让用户能直接 ``ls -la``
        看真实位置，不参与统计。

    本类**不**包含任何文件正文字段，并且 ``frozen=True`` 防止 caller
    在传递过程中改写——保持"inventory 是只读快照"的语义。
    """

    kind: str
    path: Path
    exists: bool
    file_count: int = 0
    total_bytes: int = 0
    oldest_mtime: str | None = None
    newest_mtime: str | None = None
    by_extension: dict[str, int] = field(default_factory=dict)
    by_prefix: dict[str, int] = field(default_factory=dict)
    sample_paths: list[str] = field(default_factory=list)


def _format_mtime(epoch: float) -> str:
    """把 epoch 秒转成 UTC ISO-8601。

    用 UTC + 'Z' 后缀避免本地时区差异导致测试 / 报告在不同机器上不
    可比；inventory 结果是给人和工具看的，不需要本地时区显示。
    """
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _name_prefix(name: str) -> str:
    """提取文件名前缀作为 by_prefix 分组键。

    规则（保持简单 + 可解释）：
      - ``session_xxx.json`` -> ``session``（按第一个 ``_`` 切）；
      - ``abc-def.jsonl``    -> ``abc``（按第一个 ``-`` 切）；
      - ``log123.txt``       -> 取去掉扩展名后的 stem 再做切分；
      - 16 进制 hash 文件名（``[0-9a-f]{8,}``）归到 ``hash`` 桶，
        避免每个 hash 一个桶导致前缀分布无意义。
    本函数**不**调用任何 fs 接口，纯字符串处理。
    """
    stem = name.rsplit(".", 1)[0] if "." in name else name
    head = stem
    for sep in ("_", "-"):
        if sep in head:
            head = head.split(sep, 1)[0]
            break
    if head and len(head) >= 8 and all(c in "0123456789abcdefABCDEF" for c in head):
        return "hash"
    return head or "(noname)"


def inventory_artifact_directory(
    path: Path, kind: str, *, sample_limit: int = 5
) -> ArtifactInventory:
    """对单个 artifact 目录做只读 inventory，返回不可变 ArtifactInventory。

    实现严格只用 ``Path.exists / Path.is_file / Path.iterdir / Path.stat``——
    禁止任何写/删/打开操作（由 ``test_local_artifacts_inventory`` 模块的
    AST 守卫钉死）。

    边界：
      - ``path`` 不存在 -> 返回 ``exists=False`` 且其余统计为 0/空
        （**不**报错，方便 CLI 在新装项目里也能跑）；
      - 仅遍历**顶层**条目（``iterdir`` 一层）；不递归进子目录读取
        子文件 metadata，避免误把 sessions 中的子目录当作文件统计；
        若顶层条目本身是子目录（罕见），仅计入 by_prefix=``(dir)`` 分组，
        不计入 file_count / total_bytes；
      - ``sample_limit`` 控制采样路径数量上限，默认 5；样本只用绝对路径
        字符串，不读取文件内容。
    """
    if not path.exists():
        return ArtifactInventory(kind=kind, path=path, exists=False)

    file_count = 0
    total_bytes = 0
    oldest: float | None = None
    newest: float | None = None
    by_ext: dict[str, int] = {}
    by_prefix: dict[str, int] = {}
    samples: list[str] = []

    # 仅顶层 iterdir，**不**递归。这是有意为之的边界：sessions/<id> 也许
    # 是单文件（session_xxx.json），也许是子目录（含多文件 checkpoint）；
    # 本模块只回答"顶层有多少条目"，避免无意中读到子目录里被外部工具
    # 写入的中间产物。
    for entry in path.iterdir():
        if entry.is_dir():
            by_prefix["(dir)"] = by_prefix.get("(dir)", 0) + 1
            continue
        if not entry.is_file():
            continue

        st = entry.stat()
        file_count += 1
        total_bytes += st.st_size
        if oldest is None or st.st_mtime < oldest:
            oldest = st.st_mtime
        if newest is None or st.st_mtime > newest:
            newest = st.st_mtime

        ext = entry.suffix.lower() or "(noext)"
        by_ext[ext] = by_ext.get(ext, 0) + 1

        prefix = _name_prefix(entry.name)
        by_prefix[prefix] = by_prefix.get(prefix, 0) + 1

        if len(samples) < sample_limit:
            samples.append(str(entry))

    return ArtifactInventory(
        kind=kind,
        path=path,
        exists=True,
        file_count=file_count,
        total_bytes=total_bytes,
        oldest_mtime=_format_mtime(oldest) if oldest is not None else None,
        newest_mtime=_format_mtime(newest) if newest is not None else None,
        by_extension=dict(sorted(by_ext.items())),
        by_prefix=dict(sorted(by_prefix.items())),
        sample_paths=samples,
    )


def format_artifact_inventory_report(inv: ArtifactInventory) -> str:
    """把 ArtifactInventory 渲染成给人看的 DRY RUN 报告字符串。

    设计原则：
      - 第一行永远是 ``_DRY_RUN_BANNER``，让用户**不可能**误以为做了
        修改；
      - 字段顺序固定：kind -> path -> exists -> file_count ->
        total_bytes -> mtime range -> by_ext -> by_prefix -> samples ->
        ``no changes made.`` 收尾横幅；
      - 不读取/不打印任何文件正文；
      - 不输出 ANSI 颜色（保持 CI/grep 友好）。

    本函数**不**调用任何 fs 接口（单纯渲染传入的 dataclass），与
    ``inventory_artifact_directory`` 严格分层。
    """
    lines = [_DRY_RUN_BANNER, ""]
    lines.append(f"kind         : {inv.kind}")
    lines.append(f"path         : {inv.path}")
    lines.append(f"exists       : {inv.exists}")

    if not inv.exists:
        lines.append("note         : directory missing — nothing to inventory.")
        lines.append("")
        lines.append("DRY RUN · no changes made.")
        return "\n".join(lines) + "\n"

    lines.append(f"file_count   : {inv.file_count}")
    lines.append(f"total_bytes  : {inv.total_bytes}")
    lines.append(f"oldest_mtime : {inv.oldest_mtime or '(no files)'}")
    lines.append(f"newest_mtime : {inv.newest_mtime or '(no files)'}")

    if inv.by_extension:
        ext_str = ", ".join(f"{k}={v}" for k, v in inv.by_extension.items())
        lines.append(f"by_extension : {ext_str}")
    else:
        lines.append("by_extension : (none)")

    if inv.by_prefix:
        pre_str = ", ".join(f"{k}={v}" for k, v in inv.by_prefix.items())
        lines.append(f"by_prefix    : {pre_str}")
    else:
        lines.append("by_prefix    : (none)")

    if inv.sample_paths:
        lines.append("sample_paths :")
        for s in inv.sample_paths:
            lines.append(f"  - {s}")
    else:
        lines.append("sample_paths : (none)")

    lines.append("")
    lines.append("DRY RUN · no changes made.")
    return "\n".join(lines) + "\n"


# ============================================================================
# CLI 入口辅助：让 main.py 不需要重复 import 路径常量
# ----------------------------------------------------------------------------
# v0.5 标准布局：项目根 / sessions/、项目根 / runs/。若用户项目结构不
# 同，可绕过本 helper 直接调用 ``inventory_artifact_directory(path, kind)``。
# ============================================================================
_KNOWN_KINDS: dict[str, str] = {
    "sessions": "sessions",
    "runs": "runs",
}


def inventory_known_artifact(project_root: Path, kind: str) -> ArtifactInventory:
    """按 kind 查询 v0.5 标准目录布局下的某个 artifact。

    kind 必须是 ``sessions`` 或 ``runs``——本函数**不**接受任意路径，
    防止用户误传 ``.env`` / ``agent_log.jsonl`` 这类敏感文件触发不必要
    的 stat（虽然只读 metadata 本身无害，但语义上 inventory 是给"目录
    型 artifact"用的）。
    """
    if kind not in _KNOWN_KINDS:
        raise ValueError(
            f"unknown artifact kind: {kind!r}; supported: {sorted(_KNOWN_KINDS)}"
        )
    target = project_root / _KNOWN_KINDS[kind]
    return inventory_artifact_directory(target, kind=kind)


__all__ = [
    "ArtifactInventory",
    "format_artifact_inventory_report",
    "inventory_artifact_directory",
    "inventory_known_artifact",
]
