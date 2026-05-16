# agent/tools/install_skill.py
"""Disabled legacy install_skill wrapper.

旧 Skill installer 已隔离到 `agent.legacy_skills`，这里不再 import 旧
`install_from_github`，避免显式导入 tool wrapper 时触达真实网络 / git clone /
pip install 风险路径。正式 Skill lifecycle tools 将由 `agent/skill_system/`
后续阶段重新实现。
"""

from agent.tool_registry import register_tool


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
    capability="skill_lifecycle",
    risk_level="high",
    output_policy="bounded_text",
)
def install_skill(url: str) -> str:
    """Fail closed: legacy 网络安装路径已禁用，不执行任何下载或写入。"""

    return (
        "install_skill 已禁用：旧 Skill installer 已隔离，正式 Skill lifecycle "
        "工具将在 agent/skill_system/ 后续阶段重新实现。本次调用未执行网络、"
        "git clone、pip install 或文件写入。"
    )
