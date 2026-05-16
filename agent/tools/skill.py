# agent/tools/skill.py
"""Disabled legacy load_skill wrapper.

旧 `agent.skills` loader/registry 不再作为模型可用能力包路径。wrapper 保留
显式 import path 但不加载 body、不读旧 registry、不注入 prompt；正式加载逻辑
必须由 `agent/skill_system/` progressive disclosure 实现。
"""

from agent.tool_registry import register_tool


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
    confirmation="never",
    capability="skill_lifecycle",
    risk_level="medium",
    output_policy="bounded_text",
)
def load_skill(name: str) -> str:
    """Fail closed: legacy loader 已禁用，不读取或返回旧 Skill body。"""

    return (
        "load_skill 已禁用：旧 Skill loader 已隔离，正式 Skill body loading 将由 "
        "agent/skill_system/ 后续阶段按 progressive disclosure 重新实现。"
    )
