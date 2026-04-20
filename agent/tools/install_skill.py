# agent/tools/install_skill.py
"""install_skill 工具：让模型/用户能触发 skill 安装。"""

from agent.tool_registry import register_tool
from agent.skills.installer import install_from_github
from agent.skills.registry import reload_registry


@register_tool(
    name="install_skill",
    description=(
        "从 GitHub 下载并安装一个 skill。"
        "URL 格式：https://github.com/<owner>/<repo>/tree/<branch>/<skill-name>。"
        "安装后会自动做安全检查，通过才会保留。"
        "只在用户明确要求安装 skill 时使用此工具。"
    ),
    parameters={
        "url": {
            "type": "string",
            "description": "GitHub skill 目录的 URL",
        },
    },
    confirmation="always",  # 下载网络内容，必须用户确认
)
def install_skill(url: str) -> str:
    """安装 skill 并自动 reload registry。"""
    result = install_from_github(url)
    
    if not result["success"]:
        return f"[安装失败] {result.get('error', '未知错误')}"
    
    # 安装成功，reload registry 让新 skill 立即可用
    reload_registry()
    
    lines = [
        f"[安装成功] skill '{result['skill_name']}' 已安装到 {result['skill_path']}",
        "",
        "skill 已加载到 registry，可以直接使用 load_skill 调用。",
    ]
    
    if result.get("safety_warnings"):
        lines.append("")
        lines.append("[安全警告]")
        for w in result["safety_warnings"]:
            lines.append(f"  - {w}")
    
    return "\n".join(lines)
