# agent/tools/update_skill.py
"""update_skill 工具：重新下载并覆盖已安装的 skill。"""
from agent.tool_registry import register_tool
from agent.skills.installer import update_skill as _update_skill
from agent.skills.registry import reload_registry


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
)
def update_skill(name: str) -> str:
    """更新 skill 并 reload registry。"""
    result = _update_skill(name)
    
    if not result["success"]:
        return f"[更新失败] {result.get('error', '未知错误')}"
    
    reload_registry()
    
    lines = [f"[更新成功] {result['message']}"]
    if result.get("safety_warnings"):
        lines.append("")
        lines.append("[安全警告]")
        for w in result["safety_warnings"]:
            lines.append(f"  - {w}")
    
    return "\n".join(lines)
