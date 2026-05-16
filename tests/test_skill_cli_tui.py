"""Phase 8: CLI/TUI Skill Presentation 测试。

测试范围（来自 docs/testing/SKILL_SYSTEM_TDD.md Phase 9）：
- 列出可用 Skill 列表
- 显示选中 Skill 信息
- 显示被阻止的动作
- 显示 audit ID
- CLI/TUI 只呈现状态，不导入 loader/runtime 逻辑
"""
from __future__ import annotations

import ast
from pathlib import Path as P

from agent.skill_system.descriptor import SkillDescriptor
from agent.skill_system.presentation import (
    format_available_skills,
    format_blocked_action,
    format_selected_skill,
    format_selected_skill_for_display,
)


def _desc(name: str = "test-skill") -> SkillDescriptor:
    return SkillDescriptor(
        name=name,
        description="测试用 Skill",
        version="0.1.0",
        status="active",
        risk_level="low",
        tags=("test",),
        allowed_tools=("read_file",),
        memory_scope="none",
    )


# ==================================================================
# format_available_skills
# ==================================================================

def test_format_available_skills_empty():
    """无 Skill 时返回空列表提示。"""
    result = format_available_skills([])
    assert result
    assert "没有" in result or "no" in result.lower() or "无" in result


def test_format_available_skills_lists_names():
    """多个 Skill 时每个名称都出现。"""
    skills = [
        _desc("skill-a"),
        _desc("skill-b"),
        _desc("skill-c"),
    ]
    result = format_available_skills(skills)
    for name in ("skill-a", "skill-b", "skill-c"):
        assert name in result


def test_format_available_skills_shows_risk_and_status():
    """显示 risk_level 和 status。"""
    skills = [_desc("high-risk-skill")]
    skills[0] = SkillDescriptor(
        name="high-risk-skill",
        description="危险",
        version="0.1.0",
        status="active",
        risk_level="high",
    )
    result = format_available_skills(skills)
    assert "high" in result.lower()
    assert "active" in result.lower()


# ==================================================================
# format_selected_skill
# ==================================================================

def test_format_selected_skill_shows_basic_info():
    """选中 Skill 后展示名称、描述、版本。"""
    desc = _desc("my-skill")
    result = format_selected_skill(desc)
    assert "my-skill" in result
    assert "测试用 Skill" in result
    assert "0.1.0" in result


def test_format_selected_skill_shows_tools():
    """展示 allowed_tools。"""
    desc = _desc("my-skill")
    result = format_selected_skill(desc)
    assert "read_file" in result


def test_format_selected_skill_shows_tags():
    """展示 tags。"""
    desc = _desc("my-skill")
    result = format_selected_skill(desc)
    assert "test" in result


# ==================================================================
# format_selected_skill_for_display
# ==================================================================

def test_format_selected_skill_for_display_compact():
    """format_selected_skill_for_display 提供紧凑的单行展示。"""
    desc = _desc("compact-skill")
    result = format_selected_skill_for_display(desc)
    assert "compact-skill" in result
    assert "0.1.0" in result


# ==================================================================
# format_blocked_action
# ==================================================================

def test_format_blocked_action():
    """被阻止的动作展示原因和 Skill 名。"""
    result = format_blocked_action("my-skill", "run_shell", "风险等级过高")
    assert "my-skill" in result
    assert "run_shell" in result
    assert "风险等级过高" in result


# ==================================================================
# presentation 不导入 heavyweight 模块
# ==================================================================

def test_presentation_module_does_not_import_heavyweight():
    """presentation.py 不能导入 loader / runtime / checkpoint / handler。"""
    import agent.skill_system.presentation as pres_mod

    p = P(pres_mod.__file__).resolve()
    tree = ast.parse(p.read_text(encoding="utf-8"))
    forbidden = {
        "agent.skill_system.loader",
        "agent.skill_system.checkpoint",
        "agent.skill_system.invocation",
        "agent.skill_system.selector",
        "agent.skill_system.memory_boundary",
        "agent.core",
        "agent.tool_executor",
        "agent.checkpoint",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden, (
                    f"presentation.py 不应导入 {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in forbidden, (
                f"presentation.py 不应导入 {node.module}"
            )


# ==================================================================
# no legacy import
# ==================================================================

def test_presentation_module_does_not_import_legacy():
    """presentation.py 不能 import agent.skills / agent.legacy_skills。"""
    import agent.skill_system.presentation as pres_mod

    p = P(pres_mod.__file__).resolve()
    tree = ast.parse(p.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("agent.skills")
                assert not alias.name.startswith("agent.legacy_skills")
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("agent.skills")
            assert not node.module.startswith("agent.legacy_skills")
