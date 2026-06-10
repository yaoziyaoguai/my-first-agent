"""Legacy Skill cleanup contract tests.

本轮不实现正式 Skill System，也不继续鼓励旧 `agent.skills.local` MVP 作为
实现目标。测试只保护隔离结果：
- 正式命名空间仍是 `agent/skill_system/`；
- 旧 `agent/legacy_skills/` 已删除（quarantine 由目录不存在强制执行）；
- `agent.skills` 主路径是 tombstone；
- 默认工具和 prompt 构造不能导入旧实现。
"""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = PROJECT_ROOT / "agent"
TOMBSTONE_SKILLS_DIR = AGENT_DIR / "skills"
LEGACY_SKILLS_DIR = AGENT_DIR / "legacy_skills"
FORMAL_SKILL_SYSTEM_DIR = AGENT_DIR / "skill_system"


def _module_imports(path: Path) -> set[str]:
    """用 AST 检查 import 边界，避免 import 旧 wrapper 时触发装饰器副作用。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_agent_skills_is_tombstone_not_legacy_implementation() -> None:
    """`agent.skills` 只保留空壳，不能继续暴露 registry/loader/installer。"""

    assert sorted(path.name for path in TOMBSTONE_SKILLS_DIR.glob("*.py")) == [
        "__init__.py"
    ]

    import agent.skills as skills_tombstone

    assert skills_tombstone.__all__ == []
    doc = skills_tombstone.__doc__ or ""
    assert "tombstone" in doc
    assert "agent/skill_system/" in doc
    # agent/legacy_skills/ 已删除；tombstone 不需要引用旧隔离路径


def test_legacy_skill_package_is_deleted() -> None:
    """旧 `agent/legacy_skills` 包已删除；quarantine 由目录不存在强制执行。"""

    assert not LEGACY_SKILLS_DIR.exists(), (
        "agent/legacy_skills/ 应已删除——quarantine 由目录不存在强制执行，"
        "而非依赖 README 中的\"不要用\"说明"
    )


def test_formal_skill_namespace_is_empty_or_independent() -> None:
    """正式命名空间不得从 quarantined legacy implementation 反向导入。"""

    if not FORMAL_SKILL_SYSTEM_DIR.exists():
        assert not FORMAL_SKILL_SYSTEM_DIR.exists()
        return

    leaked: dict[str, list[str]] = {}
    for path in FORMAL_SKILL_SYSTEM_DIR.rglob("*.py"):
        imports = sorted(
            name
            for name in _module_imports(path)
            if name == "agent.legacy_skills" or name.startswith("agent.legacy_skills.")
        )
        if imports:
            leaked[str(path.relative_to(PROJECT_ROOT))] = imports

    assert leaked == {}


def test_prompt_builder_no_longer_imports_legacy_skill_registry() -> None:
    """prompt_builder 使用 agent.skill_system.prompt_section（新路径），不导入旧 legacy。"""

    prompt_builder = AGENT_DIR / "prompt_builder.py"
    imports = _module_imports(prompt_builder)
    source = prompt_builder.read_text(encoding="utf-8")

    assert "agent.skills.registry" not in imports
    assert "agent.legacy_skills.registry" not in imports
    # Loop 2.2: prompt_builder 从 agent.skill_system.prompt_section 导入
    # build_skills_prompt_section / build_skill_body_section（新路径）
    assert "agent.skill_system.prompt_section" in imports, (
        "prompt_builder 应从 agent.skill_system.prompt_section 导入 skill section builder"
    )
    assert "build_skills_prompt_section" in source or "build_skill_body_section" in source


def test_disabled_skill_lifecycle_wrappers_do_not_import_legacy_code() -> None:
    """显式 wrapper 仍可被 import，但不能触达旧网络安装/loader 路径。"""

    wrapper_paths = (
        AGENT_DIR / "tools" / "install_skill.py",
        AGENT_DIR / "tools" / "update_skill.py",
        AGENT_DIR / "tools" / "skill.py",
    )

    for path in wrapper_paths:
        imports = _module_imports(path)
        assert "agent.skills" not in imports
        assert "agent.legacy_skills" not in imports
        assert all(not name.startswith("agent.legacy_skills.") for name in imports)

        source = path.read_text(encoding="utf-8")
        assert "已禁用" in source
        assert "agent/skill_system/" in source


def test_skill_py_load_skill_fail_closed_no_legacy_import() -> None:
    """`agent/tools/skill.py` 的 `load_skill` 仍 fail-closed 但不依赖旧包。

    legacy_skills 已删除；wrapper 不 import 任何旧实现路径，
    skill.py 也不能触达真实的 skill body 加载。
    """

    skill_py = AGENT_DIR / "tools" / "skill.py"
    source = skill_py.read_text(encoding="utf-8")
    assert "Disabled legacy load_skill wrapper" in source or "已禁用" in source, (
        "skill.py 必须声明为 disabled wrapper"
    )
    imports = _module_imports(skill_py)
    assert "agent.legacy_skills" not in imports
    assert "agent.skills" not in imports

    install_skill_py = AGENT_DIR / "tools" / "install_skill.py"
    if install_skill_py.exists():
        install_source = install_skill_py.read_text(encoding="utf-8")
        assert "from agent.legacy_skills" not in install_source
