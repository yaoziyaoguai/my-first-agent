"""Phase 2: Filesystem Skill Registry 测试。

测试范围（Filesystem Skill Registry）：
- 确定性文件系统扫描
- 重复名称 fail closed
- disabled/hidden Skill 不可见
- runtime/session scoped 构造
- 仅显式传入的 root 被扫描
- 注册表只返回 descriptor，不加载 body

禁止行为（来自 RFC/SDD）：
- module-level global singleton
- 读取 .env / 网络
- import legacy agent.skills / agent.legacy_skills
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from textwrap import dedent

import pytest

from agent.skill_system.errors import SkillLoadError
from agent.skill_system.registry import SkillRegistry

# ---- helpers ----

def _write_skill_md(
    dir_path: Path,
    name: str = "test-skill",
    description: str = "A test skill",
    version: str = "0.1.0",
    status: str = "active",
    risk_level: str = "low",
    extra: str = "",
) -> Path:
    """在指定目录写入一个合法 SKILL.md。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    content = f"""---
name: {name}
description: {description}
version: {version}
status: {status}
risk_level: {risk_level}
{extra}---
# {name}

Skill body for {name}.
"""
    path = dir_path / "SKILL.md"
    path.write_text(dedent(content).strip(), encoding="utf-8")
    return path


# ==================================================================
# 基本扫描与构造
# ==================================================================

def test_registry_constructs_with_explicit_roots():
    """注册表必须接受显式 skill root 列表，不使用隐式全局路径。"""
    registry = SkillRegistry(roots=[])
    assert registry.list_visible() == []


def test_registry_discovers_skill_from_single_root():
    """注册表从传入的 root 中发现 SKILL.md 并返回 descriptor。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill_md(root / "safe-writer", name="safe-writer")

        registry = SkillRegistry(roots=[root])
        descriptors = registry.list_visible()
        assert len(descriptors) == 1
        assert descriptors[0].name == "safe-writer"
        assert descriptors[0].status == "active"


def test_registry_discovers_from_multiple_roots():
    """注册表应扫描所有传入的 root。"""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        root_a = base / "skills-a"
        root_b = base / "skills-b"
        _write_skill_md(root_a / "skill-a", name="skill-a")
        _write_skill_md(root_b / "skill-b", name="skill-b")

        registry = SkillRegistry(roots=[root_a, root_b])
        names = {d.name for d in registry.list_visible()}
        assert names == {"skill-a", "skill-b"}


def test_registry_scan_is_deterministic():
    """扫描顺序必须是确定性的（按路径排序）。"""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        root = base / "skills"
        for name in ["z-skill", "a-skill", "m-skill"]:
            _write_skill_md(root / name, name=name)

        registry = SkillRegistry(roots=[root])
        names = [d.name for d in registry.list_visible()]
        assert names == sorted(names), f"扫描顺序应确定，实际: {names}"


# ==================================================================
# 只扫描包含 SKILL.md 的目录
# ==================================================================

def test_registry_skips_folders_without_skill_md():
    """不包含 SKILL.md 的目录不应被识别为 Skill。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        (root / "not-a-skill").mkdir(parents=True)
        (root / "not-a-skill" / "README.md").write_text("hello")
        _write_skill_md(root / "real-skill", name="real-skill")

        registry = SkillRegistry(roots=[root])
        names = {d.name for d in registry.list_visible()}
        assert names == {"real-skill"}


# ==================================================================
# 重复名称 fail closed
# ==================================================================

def test_duplicate_skill_names_fail_closed():
    """两个 Skill 目录包含同名 SKILL.md 时必须 fail closed。"""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        root_a = base / "skills-a"
        root_b = base / "skills-b"
        _write_skill_md(root_a / "dup-skill", name="dup-skill")
        _write_skill_md(root_b / "another-dup", name="dup-skill")

        with pytest.raises(SkillLoadError) as exc_info:
            SkillRegistry(roots=[root_a, root_b])
        assert exc_info.value.code == "DUPLICATE_NAME"


# ==================================================================
# 无效 Skill fail closed
# ==================================================================

def test_invalid_skill_in_root_skipped():
    """无效的 SKILL.md 被跳过，不影响其他有效 Skill 的注册。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill_md(root / "valid-skill", name="valid-skill")
        # 写入一个无效的 SKILL.md（缺少 version 字段）
        bad_dir = root / "bad-skill"
        bad_dir.mkdir(parents=True)
        (bad_dir / "SKILL.md").write_text(
            "---\nname: bad-skill\ndescription: desc\nstatus: draft\n---\nbody"
        )

        registry = SkillRegistry(roots=[root])
        assert registry.get_descriptor("valid-skill") is not None
        assert registry.get_descriptor("bad-skill") is None


# ==================================================================
# 诊断：无效 Skill 不再静默跳过
# ==================================================================

def test_get_load_errors_surfaces_missing_version():
    """缺 version 时 get_load_errors() 必须包含错误信息，不再静默丢弃。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill_md(root / "valid-skill", name="valid-skill")
        bad_dir = root / "bad-skill"
        bad_dir.mkdir(parents=True)
        (bad_dir / "SKILL.md").write_text(
            "---\nname: bad-skill\ndescription: desc\nstatus: draft\n---\nbody"
        )

        registry = SkillRegistry(roots=[root])
        errors = registry.get_load_errors()
        assert len(errors) == 1, (
            f"缺 version 应产生 1 个错误，实际: {len(errors)}"
        )
        assert errors[0].code == "MISSING_VERSION"
        assert "version" in errors[0].safe_preview.lower()


def test_get_load_errors_cleared_on_reset():
    """reset() 后重新扫描，load_errors 应该反映最新状态。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        bad_dir = root / "bad-skill"
        bad_dir.mkdir(parents=True)
        (bad_dir / "SKILL.md").write_text(
            "---\nname: bad-skill\ndescription: desc\nstatus: draft\n---\nbody"
        )

        registry = SkillRegistry(roots=[root])
        assert len(registry.get_load_errors()) == 1

        # 修复 SKILL.md 后 reset——错误应清空
        (bad_dir / "SKILL.md").write_text(
            "---\nname: bad-skill\ndescription: desc\nversion: 0.1.0\nstatus: active\n---\nbody"
        )
        registry.reset()
        assert len(registry.get_load_errors()) == 0
        assert registry.get_descriptor("bad-skill") is not None


def test_get_load_errors_empty_when_all_valid():
    """所有 SKILL.md 合法时 get_load_errors() 返回空列表。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill_md(root / "skill-a", name="skill-a")
        _write_skill_md(root / "skill-b", name="skill-b")

        registry = SkillRegistry(roots=[root])
        assert registry.get_load_errors() == []
        assert len(registry.list_visible()) == 2


# ==================================================================
# disabled / hidden Skill 不可见
# ==================================================================

def test_disabled_skill_not_visible():
    """disabled 状态的 Skill 不出现在 list_visible() 中。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill_md(root / "disabled-skill", name="disabled-skill", status="disabled")
        _write_skill_md(root / "active-skill", name="active-skill", status="active")

        registry = SkillRegistry(roots=[root])
        visible_names = {d.name for d in registry.list_visible()}
        assert "disabled-skill" not in visible_names
        assert "active-skill" in visible_names


def test_legacy_skill_not_visible():
    """legacy 状态的 Skill 默认不可见。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill_md(root / "legacy-skill", name="legacy-skill", status="legacy")

        registry = SkillRegistry(roots=[root])
        assert registry.list_visible() == []


def test_hidden_skill_not_visible_but_registered():
    """disabled Skill 虽然不在 visible 列表中，但可以通过 get_descriptor 查询。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill_md(root / "hidden-skill", name="hidden-skill", status="disabled")

        registry = SkillRegistry(roots=[root])
        assert registry.list_visible() == []
        # 内部仍然可以查询
        desc = registry.get_descriptor("hidden-skill")
        assert desc is not None
        assert desc.name == "hidden-skill"
        assert desc.status == "disabled"


# ==================================================================
# get_descriptor API
# ==================================================================

def test_get_descriptor_returns_none_for_unknown():
    """查询不存在的 Skill 返回 None。"""
    registry = SkillRegistry(roots=[])
    assert registry.get_descriptor("nonexistent") is None


def test_get_descriptor_returns_correct_skill():
    """按名称查询返回正确的 SkillDescriptor。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill_md(root / "target", name="target", description="The target skill")

        registry = SkillRegistry(roots=[root])
        desc = registry.get_descriptor("target")
        assert desc is not None
        assert desc.name == "target"
        assert "target skill" in desc.description


# ==================================================================
# reset / 再加载
# ==================================================================

def test_registry_reset_reloads_from_roots():
    """reset() 后重新扫描 root，应反映文件系统变化。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill_md(root / "skill-1", name="skill-1")

        registry = SkillRegistry(roots=[root])
        assert len(registry.list_visible()) == 1

        # 新增 Skill 目录
        _write_skill_md(root / "skill-2", name="skill-2")
        registry.reset()
        assert len(registry.list_visible()) == 2


# ==================================================================
# 不加载 body（Phase 2 只返回 metadata）
# ==================================================================

def test_registry_descriptor_has_no_body():
    """注册表返回的 SkillDescriptor 不包含 SKILL.md body。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill_md(root / "body-test", name="body-test",
                        description="Test body exclusion")

        registry = SkillRegistry(roots=[root])
        desc = registry.get_descriptor("body-test")
        assert desc is not None
        # SkillDescriptor 不应有 body 字段
        assert not hasattr(desc, "body")


# ==================================================================
# 添加 root
# ==================================================================

def test_add_root_extends_registry():
    """add_root() 动态扩展注册表扫描范围。"""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        root_a = base / "skills-a"
        root_b = base / "skills-b"
        _write_skill_md(root_a / "skill-a", name="skill-a")
        _write_skill_md(root_b / "skill-b", name="skill-b")

        registry = SkillRegistry(roots=[root_a])
        assert len(registry.list_visible()) == 1

        registry.add_root(root_b)
        assert len(registry.list_visible()) == 2


# ==================================================================
# 不接受非目录 root
# ==================================================================

def test_registry_rejects_nonexistent_root():
    """传入不存在的 root 路径应 fail closed。"""
    with tempfile.TemporaryDirectory() as tmp:
        bad_root = Path(tmp) / "nonexistent"
        with pytest.raises((SkillLoadError, FileNotFoundError, ValueError)):
            SkillRegistry(roots=[bad_root])


# ==================================================================
# 空 roots 构造
# ==================================================================

def test_registry_without_roots_is_empty():
    """不传 roots 或传空列表时，注册表应为空。"""
    registry = SkillRegistry()
    assert registry.list_visible() == []
    registry2 = SkillRegistry(roots=[])
    assert registry2.list_visible() == []


# ==================================================================
# 确认不 import legacy
# ==================================================================

def test_registry_module_does_not_import_legacy():
    """registry.py 不能 import agent.skills 或 agent.legacy_skills。"""
    import ast
    from pathlib import Path as _Path

    registry_path = _Path(__file__).resolve().parents[1] / "agent" / "skill_system" / "registry.py"
    tree = ast.parse(registry_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("agent.skills")
                assert not alias.name.startswith("agent.legacy_skills")
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("agent.skills")
            assert not node.module.startswith("agent.legacy_skills")


# ==================================================================
# Phase 7 B7 Extension Points — SkillRegistry.scope
# ==================================================================


class TestSkillRegistryB7Extension:
    """Phase 7 B7 扩展点：SkillRegistry.scope 参数预留。

    scope 参数在 Phase 7 前默认为 "default"，不影响现有行为。
    B7 将使用 scope 实现 per-instance skill registry 隔离。
    """

    def test_scope_default(self):
        """默认 scope 为 "default"。"""
        registry = SkillRegistry()
        assert registry.scope == "default"

    def test_scope_custom(self):
        """自定义 scope 可通过构造参数设置。"""
        registry = SkillRegistry(roots=[], scope="instance-1")
        assert registry.scope == "instance-1"

    def test_scope_with_skills_still_works(self):
        """scope 参数不影响 Phase 4-7 的 skill 加载行为。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill_md(root / "sample-skill", name="sample-skill")
            registry = SkillRegistry(roots=[root], scope="custom-scope")
            assert registry.scope == "custom-scope"
            visible = registry.list_visible()
            assert len(visible) == 1
            assert visible[0].name == "sample-skill"

    def test_scope_different_instances_independent(self):
        """不同 scope 的 registry 在 Phase 7 前仍共享相同的文件系统视图。

        B7 实现 scope 隔离后此测试需要更新。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill_md(root / "demo", name="demo-skill")
            r1 = SkillRegistry(roots=[root], scope="scope-a")
            r2 = SkillRegistry(roots=[root], scope="scope-b")
            # Phase 4-7: 不同 scope 的 registry 扫描同一文件系统，
            # 结果相同（scope 尚未隔离）
            assert len(r1.list_visible()) == len(r2.list_visible()) == 1
            assert r1.get_descriptor("demo-skill") is not None
            assert r2.get_descriptor("demo-skill") is not None
