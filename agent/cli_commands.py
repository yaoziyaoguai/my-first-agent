"""CLI meta-command 检测与渲染模块。

中文学习边界：
- 本模块只负责 CLI meta-command 的**检测**（deterministic string matching）和
  **渲染**（纯文本格式化），不执行任何核心副作用。
- 核心副作用（Memory retain/write、Tool Pipeline、SubAgent runtime）仍由
  core.chat() 内的服务调用执行。
- 这不是第二条 runtime——所有命令仍必须通过 core.chat() 统一入口进入。
- 后续新增 CLI 命令只需在本模块新增 detect/render 函数，不污染 core.py。

为什么从 core.py 提取：
- core.py 的 chat() 是 runtime orchestrator，不应堆砌命令解析和文本渲染逻辑
- 提取后 chat() 仍然是唯一用户入口，但命令解析职责分离到独立模块
- 避免 core.py 持续膨胀，也为后续 manual dogfood 提供清晰的扩展点

架构约束：
- detect 函数：纯字符串匹配，无 IO、无副作用
- render 函数：纯格式化，输入数据 → 输出文本
- 不得调用 ToolRegistry、Memory store write、SubAgent delegation、LLM
- 不得导入 core.py（避免循环依赖）
"""

from __future__ import annotations

from dataclasses import dataclass


# ═══════════════════════════════════════════════════════════════════════════
# CommandIntent: typed command classification（RT-02 remediation）
# ═══════════════════════════════════════════════════════════════════════════
# 中文学习边界：CommandIntent 是纯数据结构——它只描述命令的**意图**，不执行任何
# 副作用。core.chat() 读取 intent 后决定如何分派，但分派逻辑仍然在 core.chat()
# 内通过现有服务调用完成。这不是新 runtime，只是让原本散落的 if/return 块有
# 了可测试、可审计的类型标签。
#
# architecture boundary:
# - READ_ONLY: 只读命令，不产生 IO 副作用（show memories/list/help）
# - MUTATING: 有副作用但仅限 memory store（forget memory）
# - DELEGATING: 委托子代理执行（可能产生 filesystem/IO 副作用）


class CommandCategory:
    """CLI 命令分类——描述副作用级别，不描述实现。"""
    READ_ONLY = "read_only"
    MUTATING = "mutating"
    DELEGATING = "delegating"


@dataclass(frozen=True)
class CommandIntent:
    """typed command intent——core.chat() 消费此结构决定分派路径。

    这不是 runtime action，不经过 dispatcher。它是 CLI meta-command 层的
    分类标签，帮助 core.chat() 在统一入口处明确每个快捷命令的副作用级别。
    """
    category: str
    label: str  # 人类可读的命令名，用于 logging/debug


# ═══════════════════════════════════════════════════════════════════════════
# Known Command Shortcuts Allowlist（PF-02 freeze boundary）
# ═══════════════════════════════════════════════════════════════════════════
# 中文学习边界：这是 CLI meta-command 的 freeze/allowlist。
# 当前所有 CLI 快捷命令都必须在此注册。新增 command shortcut 必须先走
# Architecture Decision——这不是 runtime enforcement，而是工程纪律约束。
# 新增 detect 函数但不更新此 allowlist 会导致 focused test 失败，
# 从而在 code review 阶段拦截。
#
# architecture boundary:
# - 这些是 CLI-only / DEMO-ONLY transitional affordances
# - 不经过 dispatcher / evidence path / Tool Pipeline
# - future: 迁入 typed command/use-case layer → dispatcher → runtime flow
# - removal criteria: 当对应的 unified runtime path 完全替代此 shortcut 后移除
# - sunset: v0.4+ 开始逐步将 MUTATING/DELEGATING shortcuts 迁入 dispatcher

KNOWN_COMMAND_SHORTCUTS: frozenset[str] = frozenset({
    "detect_show_memories",
    "detect_forget_memory",
    "detect_show_subagents",
    "detect_delegate_to_subagent",
    "detect_nl_delegation",
})


def get_known_command_shortcuts() -> frozenset[str]:
    """返回当前已注册的 CLI command shortcut 名称集合。

    供 characterization tests 验证 allowlist 完整性。
    新增 shortcut 必须先更新 KNOWN_COMMAND_SHORTCUTS，否则测试失败。
    """
    return KNOWN_COMMAND_SHORTCUTS


# ========== Detection functions（纯字符串匹配，无副作用） ==========

def detect_show_memories(text: str) -> bool:
    """检测用户输入是否为"查看记忆"CLI 命令。

    支持的触发词（中英文）：
    - show memories / list memories / show my memories
    - 显示记忆 / 列出记忆 / 查看记忆 / 我的记忆 / 已保存的记忆
    - 记忆列表 / 查看已保存
    """
    text_lower = text.strip().lower()
    triggers = (
        "show memories", "list memories", "show my memories",
        "显示记忆", "列出记忆", "查看记忆", "我的记忆", "已保存的记忆",
        "记忆列表", "查看已保存",
    )
    return any(trigger in text_lower for trigger in triggers)


def detect_forget_memory(text: str) -> str | None:
    """检测用户输入是否为"忘记记忆"CLI 命令，返回待匹配的关键词或 ID。

    支持的触发模式（中英文）：
    - forget <keyword> / forget id:<id>
    - 忘记 <keyword> / 忘记 id:<id>
    - remove memory <keyword>
    - 删除记忆 <keyword> / 删掉记忆 <keyword> / 清除记忆 <keyword>

    返回 None 表示不是 forget 命令。
    """
    import re

    text_stripped = text.strip()
    text_lower = text_stripped.lower()
    prefixes = (
        "forget ", "忘记", "remove memory ", "remove memories ",
        "删除记忆", "删掉记忆", "清除记忆",
    )
    for prefix in prefixes:
        if text_lower.startswith(prefix):
            remainder = text_stripped[len(prefix):].strip()
            if remainder:
                return remainder
            return None
    m = re.match(r".*?(?:forget|忘记|删除记忆|删掉记忆)\s+(.+)", text_lower)
    if m:
        return text_stripped[m.start(1):].strip() or None
    return None


def detect_show_subagents(text: str) -> bool:
    """检测用户输入是否为"查看子代理"CLI 命令。

    支持的触发词（中英文）：
    - show subagents / list subagents / show agents
    - 显示子代理 / 列出子代理 / 查看子代理 / 子代理列表
    """
    text_lower = text.strip().lower()
    triggers = (
        "show subagents", "list subagents", "show agents",
        "显示子代理", "列出子代理", "查看子代理", "子代理列表",
    )
    return any(trigger in text_lower for trigger in triggers)


def detect_delegate_to_subagent(text: str) -> tuple[str, str] | None:
    """检测用户输入是否为"委托子代理"CLI 命令，返回 (subagent_name, task)。

    支持的触发模式：
    - delegate to <name>: <task>
    - 委托 <name>: <task> / 委托 <name>：<task>
    - delegate <task> to <name>
    """
    import re

    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    # Pattern 1: "delegate to <name>: <task>"
    m = re.match(r"delegate\s+to\s+(\S+)\s*:\s*(.+)", text_lower)
    if m:
        return (m.group(1), text_stripped[m.start(2):].strip())

    # Pattern 2: "委托 <name>: <task>" (支持中英文冒号)
    m = re.match(r"委托\s+(\S+)\s*[:：]\s*(.+)", text_stripped)
    if m:
        return (m.group(1), m.group(2).strip())

    # Pattern 3: "delegate <task> to <name>"
    m = re.match(r"delegate\s+(.+)\s+to\s+(\S+)", text_lower)
    if m:
        return (m.group(2), text_stripped[m.start(1):m.end(1)].strip())

    return None


def detect_nl_delegation(text: str) -> tuple[str, str] | None:
    """检测用户输入是否为自然语言子代理委托，返回 (subagent_name, task)。

    Issue 2: safe deterministic NL delegation fixtures。
    用户无需记忆 CLI 语法即可委托子代理——说"帮我统计 demo workspace"
    就能触发 demo-stat。这是 deterministic 关键词匹配，不调用 LLM、
    不经过 tool pipeline、不成为第二条 runtime。

    支持的 NL 触发模式（确定性匹配，默认委托给 demo-stat）：
    - 帮我统计/分析 <task>
    - 统计一下/分析一下 <task>
    - 帮我看看/查看 <task>
    - summarize/analyze demo workspace files
    - count files in project
    - 文件统计/项目统计

    返回 (subagent_name, task) 或 None。
    """
    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    # 中文 NL 触发词 → demo-stat
    cn_patterns: list[tuple[str, str | None]] = [
        ("帮我统计", None),   # → task = remainder
        ("帮我分析", None),
        ("统计一下", None),
        ("分析一下", None),
        ("帮我看看", None),
        ("帮我查看", None),
        ("文件统计", "统计项目文件"),
        ("项目统计", "统计项目文件"),
    ]
    for prefix, fixed_task in cn_patterns:
        if text_stripped.startswith(prefix):
            task = fixed_task if fixed_task else text_stripped[len(prefix):].strip()
            if task:
                return ("demo-stat", task)

    # 英文 NL 触发词 → demo-stat
    en_patterns: list[tuple[str, str | None]] = [
        ("summarize", None),
        ("analyze demo", None),
        ("count files", None),
    ]
    for prefix, fixed_task in en_patterns:
        if text_lower.startswith(prefix):
            remaining = text_stripped[len(prefix):].strip()
            task = fixed_task if fixed_task else (remaining or text_stripped)
            if task:
                return ("demo-stat", task)

    return None


# ========== Rendering functions（纯格式化，无副作用） ==========

def render_memory_list(records) -> str:
    """格式化记忆列表为 CLI 可读文本。

    每条记忆显示短 ID（前8位，供 forget 命令复制使用）、来源类型、
    时间和内容摘要。

    字段映射基于 MemoryRecord 真实字段：
    - id → 显示前8位短 ID（用户可复制用于 forget id:<short_id>）
    - source_type → 记忆来源类型（explicit_user_request / agent_suggested 等）
    - metadata.created_at → 创建时间（如存在）；不存在时诚实显示 unavailable
    - content → 记忆内容（截断到120字符）

    为什么显示短 ID 就必须支持短 ID 删除：
    - 用户看到短 ID 会自然复制使用；如果不支持短 ID 前缀匹配，
      forget id:<displayed_id> 永远失败，dogfood checklist step 8 阻塞。
    - 因此 forget 逻辑必须支持前缀匹配。

    为什么 created_at 缺失时诚实显示 unavailable：
    - MemoryRecord 没有顶层 created_at 字段，时间信息在 metadata dict 中
    - metadata 可能为空或没有 created_at（取决于 memory source）
    - 伪造时间会误导用户以为系统记录了精确时间戳
    - 诚实标注 unavailable 是 fake/local-safe memory 的透明性要求
    """
    if not records:
        return "暂无已保存的记忆。"

    lines = [f"已保存的记忆（共 {len(records)} 条）："]
    for i, r in enumerate(records, 1):
        rid = getattr(r, "id", "?")
        content = getattr(r, "content", str(r))[:120]
        source_type = getattr(r, "source_type", "")
        # created_at 在 metadata dict 中，不在 MemoryRecord 顶层字段
        metadata = getattr(r, "metadata", None)
        created = ""
        if isinstance(metadata, dict):
            created = str(metadata.get("created_at", ""))
        if not created:
            created = "unavailable"

        meta_str = f"来源:{source_type}" if source_type else "来源:unknown"
        meta_str += f", 时间:{created}"
        short_id = str(rid)[:8] if rid else "?"
        lines.append(f"  {i}. [{short_id}] [{meta_str}] {content}")
    return "\n".join(lines)


def render_memory_forget_result(keyword: str, removed_count: int) -> str:
    """格式化 forget memory 成功结果。"""
    return f"已移除 {removed_count} 条记忆（匹配「{keyword}」）。"


def render_memory_forget_not_found(keyword: str) -> str:
    """格式化 forget memory 未找到结果。"""
    return f"未找到匹配「{keyword}」的记忆。"


def render_subagent_list(descriptors) -> str:
    """格式化子代理列表为 CLI 可读文本。"""
    if not descriptors:
        return "暂无已注册的子代理。"

    lines = [f"已注册的子代理（共 {len(descriptors)} 个）："]
    for i, d in enumerate(descriptors, 1):
        name = getattr(d, "name", str(d))
        role = getattr(d, "role", "")
        desc = getattr(d, "description", "")[:80]
        lines.append(f"  {i}. {name} [{role}] — {desc}")
    return "\n".join(lines)


def render_delegate_result(
    subagent_name: str,
    status: str,
    summary: str = "",
    stop_reason: str = "",
    confidence: float = 0.0,
) -> str:
    """格式化子代理委托结果为 CLI 可读文本。"""
    parts = [
        f"[SubAgent: {subagent_name}]",
        f"状态: {status}",
    ]
    if stop_reason:
        parts.append(f"停止原因: {stop_reason}")
    if summary:
        parts.append(f"摘要: {summary}")
    if confidence > 0:
        parts.append(f"置信度: {confidence:.0%}")
    return "\n".join(parts)


def render_delegate_not_found(subagent_name: str, visible_names: list[str]) -> str:
    """格式化子代理未找到的结果。"""
    hint = f"可用子代理：{', '.join(visible_names)}" if visible_names else "暂无已注册的子代理"
    return f"未找到子代理「{subagent_name}」。{hint}。"


def render_delegate_error(subagent_name: str, error: str) -> str:
    """格式化子代理执行错误。"""
    return f"子代理执行失败「{subagent_name}」：{error}"
