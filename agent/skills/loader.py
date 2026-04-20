"""Skill 加载器：根据名字返回 skill 的完整内容。

当模型调用 load_skill 工具时，这个模块负责从 Registry 拿到
对应 skill 的 body，返回给模型。
"""

from typing import Optional

from agent.skills.registry import get_registry


def load_skill_body(skill_name: str) -> Optional[str]:
    """按名字加载 skill 的完整 body。
    
    Args:
        skill_name: skill 名字（YAML frontmatter 里的 name 字段）
    
    Returns:
        skill 的 body 文本。找不到返回 None。
    """
    registry = get_registry()
    skill = registry.get_skill(skill_name)
    
    if skill is None:
        return None
    
    return skill["body"]


def format_skill_for_model(skill_name: str) -> str:
    """把 skill body 格式化成返回给模型的字符串。
    
    包装成有明确开头结尾的段落，让模型知道这是加载的 skill 内容。
    """
    body = load_skill_body(skill_name)
    
    if body is None:
        return f"[错误] 找不到名为 '{skill_name}' 的 skill"
    
    # 让模型明确知道这是 skill 内容，以及范围
    return (
        f"[已加载 skill: {skill_name}]\n"
        "---\n"
        f"{body}\n"
        "---\n"
        "请根据以上指令完成任务。"
    )
