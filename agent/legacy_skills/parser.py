# agent/skills/parser.py

import re
from pathlib import Path
import yaml


class SkillParseError(Exception):
    """Skill 解析错误"""
    pass


KEBAB_CASE_PATTERN = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')


def parse_skill_file(skill_dir: Path) -> dict:
    """解析一个 skill 目录，返回结构化 dict。"""
    skill_dir = Path(skill_dir)
    
    if not skill_dir.is_dir():
        raise SkillParseError(f"skill 目录不存在：{skill_dir}")
    
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise SkillParseError(f"SKILL.md 不存在：{skill_md}")
    
    content = skill_md.read_text(encoding="utf-8")
    frontmatter_text, body = _split_frontmatter(content)
    
    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as e:
        raise SkillParseError(f"YAML 解析失败：{e}")
    
    if not isinstance(frontmatter, dict):
        raise SkillParseError("frontmatter 必须是 YAML 对象（键值对）")
    
    _validate_frontmatter(frontmatter, skill_dir.name)
    
    return {
        "name": frontmatter["name"],
        "description": frontmatter["description"],
        "license": frontmatter.get("license"),
        "metadata": frontmatter.get("metadata", {}),
        "allowed_tools": frontmatter.get("allowed-tools", ""),
        "body": body,
        "path": str(skill_dir),
    }


def _split_frontmatter(content: str) -> tuple[str, str]:
    lines = content.split("\n")
    
    if not lines or lines[0].strip() != "---":
        raise SkillParseError("SKILL.md 必须以 '---' 开头")
    
    end_index = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_index = i
            break
    
    if end_index is None:
        raise SkillParseError("SKILL.md 的 frontmatter 未闭合（缺少结束的 '---'）")
    
    frontmatter_text = "\n".join(lines[1:end_index])
    body = "\n".join(lines[end_index + 1:]).strip()
    
    return frontmatter_text, body


def _validate_frontmatter(frontmatter: dict, dir_name: str) -> None:
    name = frontmatter.get("name")
    if not name:
        raise SkillParseError("frontmatter 缺少必需字段 'name'")
    if not isinstance(name, str):
        raise SkillParseError("'name' 必须是字符串")
    if len(name) > 64:
        raise SkillParseError("'name' 长度不能超过 64 字符")
    if not KEBAB_CASE_PATTERN.match(name):
        raise SkillParseError(f"'name' 必须是 kebab-case：'{name}'")
    if name != dir_name:
        raise SkillParseError(
            f"'name' 必须和目录名一致：name='{name}', dir='{dir_name}'"
        )
    
    description = frontmatter.get("description")
    if not description:
        raise SkillParseError("frontmatter 缺少必需字段 'description'")
    if not isinstance(description, str):
        raise SkillParseError("'description' 必须是字符串")
    if len(description) > 1024:
        raise SkillParseError("'description' 长度不能超过 1024 字符")
