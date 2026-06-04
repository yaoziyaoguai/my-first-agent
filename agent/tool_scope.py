"""工具作用域模型：基础工具层 + 技能工具层的合成规则。

学习型说明：
本模块定义了 Agent 工具可见性的两层模型：
1. BASE_TOOLS：Agent 始终保留的基础能力（只读工具 + 控制工具）
2. Skill tools：活跃 skill 追加的专用能力

当 skill 激活时，visible_tools = BASE_TOOLS + skill_allowed_tools，
而不是 visible_tools = skill_allowed_tools（替换模式）。

BASE_TOOLS 中的工具仍需通过 TOOL_GATE 安全策略检查（如 sensitive path policy）。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 基础只读工具 — 始终可用，不写文件、不执行命令、不访问网络
# ---------------------------------------------------------------------------
BASE_READ_TOOLS: frozenset[str] = frozenset({
    "read_file",
    "read_file_lines",
})

# ---------------------------------------------------------------------------
# 基础控制工具 — 元工具（meta tools），runtime 控制流必需
# ---------------------------------------------------------------------------
BASE_CONTROL_TOOLS: frozenset[str] = frozenset({
    "mark_step_complete",
    "request_user_input",
})

# ---------------------------------------------------------------------------
# 基础工具全集 = 只读 + 控制
# 注意：不包含 write/edit/run_shell/fetch_url 等副作用工具
# ---------------------------------------------------------------------------
BASE_TOOLS: frozenset[str] = BASE_READ_TOOLS | BASE_CONTROL_TOOLS


def resolve_skill_scoped_allowlist(
    skill_allowed_tools: frozenset[str] | set[str],
    *,
    include_base_tools: bool = True,
) -> frozenset[str]:
    """将 skill 的 allowed_tools 与基础工具层合并为最终 allowlist。

    参数：
        skill_allowed_tools: 活跃 skill 允许的工具名集合
        include_base_tools: 是否合并 BASE_TOOLS（默认 True）

    返回：
        合并后的工具名集合（frozenset）
    """
    if include_base_tools:
        return frozenset(skill_allowed_tools) | BASE_TOOLS
    return frozenset(skill_allowed_tools)


def is_base_tool(tool_name: str) -> bool:
    """判断工具名是否为 BASE_TOOLS 成员。"""
    return tool_name in BASE_TOOLS
