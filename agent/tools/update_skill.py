# agent/tools/update_skill.py
"""Disabled legacy update_skill wrapper.

旧 Skill updater 的历史 installer 隔离目标 `agent.legacy_skills` **当前不存在**；
wrapper 保留显式 `update_skill` tool name 但 fail closed，避免旧网络 /
文件写入路径继续作为默认链路。`import agent.legacy_skills` 会 ImportError，
quarantine 由目录不存在强制执行。
"""

from agent.tool_registry import register_tool


@register_tool(
    name="update_skill",
    description=(
        "更新已安装的 skill（重新下载最新版本覆盖本地）。"
        "只能更新通过 install_skill 工具安装的 skill。"
        "手动放进 skills/ 目录的 skill 无法自动更新。"
    ),
    parameters={
        "name": {
            "type": "string",
            "description": "要更新的 skill 名字",
        },
    },
    confirmation="always",
    capability="skill_lifecycle",
    risk_level="high",
    output_policy="bounded_text",
)
def update_skill(name: str) -> str:
    """Fail closed: legacy 更新路径已禁用，不执行任何下载或覆盖。"""

    return (
        "update_skill 已禁用：旧 Skill updater 已隔离，正式 Skill lifecycle "
        "工具将在 agent/skill_system/ 后续阶段重新实现。本次调用未执行网络、"
        "git clone、pip install 或文件写入。"
    )
