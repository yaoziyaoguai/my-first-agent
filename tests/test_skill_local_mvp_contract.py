"""Legacy Skill cleanup contract tests.

本轮不实现正式 Skill System，也不继续鼓励旧 `agent.skills.local` MVP 作为
实现目标。测试只保护隔离结果：
- 正式命名空间仍是 `agent/skill_system/`；
- 旧实现只在 `agent/legacy_skills/` 作为历史材料；
- `agent.skills` 主路径是 tombstone；
- 默认工具和 prompt 构造不能再导入旧实现。
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
    assert "agent/legacy_skills/" in doc


def test_legacy_skill_implementation_is_quarantined() -> None:
    """旧实现移动到 `agent/legacy_skills`，仅作显式迁移材料。"""

    expected_files = {
        "__init__.py",
        "installer.py",
        "loader.py",
        "local.py",
        "parser.py",
        "registry.py",
        "safety.py",
    }
    assert expected_files.issubset(
        {path.name for path in LEGACY_SKILLS_DIR.glob("*.py")}
    )
    assert (LEGACY_SKILLS_DIR / "README.md").is_file()

    readme = (LEGACY_SKILLS_DIR / "README.md").read_text(encoding="utf-8")
    assert "not the formal Skill System" in readme
    assert "agent/skill_system/" in readme
    assert "install_from_github" in readme


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


def test_legacy_installer_network_path_is_not_formal_tool_path() -> None:
    """旧 installer 仍在隔离区，但正式/默认路径不能 import 或调用它。"""

    installer_source = (LEGACY_SKILLS_DIR / "installer.py").read_text(
        encoding="utf-8"
    )
    assert "def install_from_github" in installer_source
    assert "git clone" in installer_source

    install_wrapper = (AGENT_DIR / "tools" / "install_skill.py").read_text(
        encoding="utf-8"
    )
    assert "from agent.legacy_skills" not in install_wrapper
    assert "install_from_github(" not in install_wrapper
    assert "git clone、pip install" in install_wrapper
