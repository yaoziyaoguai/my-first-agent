# agent/tools/skill.py
"""load_skill 工具：让模型能加载 skill。"""

from agent.tool_registry import register_tool
from agent.skills.loader import format_skill_for_model
from agent.skills.registry import get_registry


def _check_skill_exists(tool_name, tool_input, context):
    """pre_execute 钩子：确认 skill 存在。"""
    skill_name = tool_input.get("name", "")
    registry = get_registry()
    if registry.get_skill(skill_name) is None:
        available = [s["name"] for s in registry.list_skills()]
        return (
            f"拒绝执行：找不到 skill '{skill_name}'。"
            f"可用的 skill: {', '.join(available) if available else '（无）'}"
        )
    return None


@register_tool(
    name="load_skill",
    description=(
        "加载一个专业能力包（skill）的完整指令。"
        "当用户的任务匹配 system prompt 里列出的某个 skill 时，"
        "调用此工具获取完整指令后再执行任务。"
        "每个任务只需加载一次对应的 skill。"
    ),
    parameters={
        "name": {
            "type": "string",
            "description": "要加载的 skill 名字，必须是 system prompt 里列出的 name 字段",
        },
    },
    confirmation="never",  # 加载 skill 是安全的读取操作，不需要用户确认
    pre_execute=_check_skill_exists,
)
def load_skill(name: str) -> str:
    """加载指定名字的 skill，返回完整指令内容。"""
    return format_skill_for_model(name)
