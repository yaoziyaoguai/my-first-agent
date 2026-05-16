"""Phase 3: Progressive Disclosure 测试。

测试范围（来自 docs/testing/SKILL_SYSTEM_TDD.md Phase 3）：
- Level 1 prompt 仅含 metadata
- Level 2 body 仅在选中后加载
- Level 3 references/scripts/templates 仅在显式请求时加载
- 审计记录可观测 loaded levels
- prompt section 绝不包含所有 Skill body

禁止行为：
- selector/registry 预加载所有 body
- prompt section 注入全部 Skill 内容
- 加载器执行代码 / 访问网络 / pip install / 读取 .env
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from textwrap import dedent

import pytest

from agent.skill_system.errors import SkillLoadError
from agent.skill_system.loader import SkillLoader
from agent.skill_system.prompt_section import (
    build_skills_prompt_section,
    build_skill_body_section,
)
from agent.skill_system.registry import SkillRegistry
from agent.skill_system.schema import SKILL_MD_FILENAME


# ---- helpers ----

def _write_skill_md(
    dir_path: Path,
    name: str = "test-skill",
    description: str = "A test skill",
    version: str = "0.1.0",
    status: str = "active",
    body: str = "# Skill Body\n\nDefault body content.",
    extra_frontmatter: str = "",
) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    content = f"""---
name: {name}
description: {description}
version: {version}
status: {status}
risk_level: low
{extra_frontmatter}
---
{body}
"""
    path = dir_path / SKILL_MD_FILENAME
    path.write_text(dedent(content).strip(), encoding="utf-8")
    return path


def _write_resource(skill_dir: Path, subdir: str, filename: str, content: str = "resource content") -> Path:
    p = skill_dir / subdir / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ==================================================================
# Level 1: metadata only
# ==================================================================

def test_prompt_section_contains_only_metadata():
    """Level 1 prompt section 只应包含 metadata，不能包含 body。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill_md(root / "skill-a", name="skill-a", description="Skill A desc",
                        body="# Big Body\n\n" + "x" * 500)
        _write_skill_md(root / "skill-b", name="skill-b", description="Skill B desc")

        registry = SkillRegistry(roots=[root])
        section = build_skills_prompt_section(registry)

        # 必须包含 name 和 description
        assert "skill-a" in section
        assert "Skill A desc" in section
        assert "skill-b" in section

        # 绝不能包含 body
        assert "Big Body" not in section
        assert "x" * 500 not in section


def test_prompt_section_empty_when_no_skills():
    """没有可见 Skill 时 prompt section 应为空。"""
    registry = SkillRegistry(roots=[])
    assert build_skills_prompt_section(registry) == ""


def test_prompt_section_marks_status():
    """prompt section 应包含 Skill 的状态信息。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill_md(root / "active-skill", name="active-skill", status="active",
                        description="Active skill")
        _write_skill_md(root / "draft-skill", name="draft-skill", status="draft",
                        description="Draft skill")

        registry = SkillRegistry(roots=[root])
        section = build_skills_prompt_section(registry)

        assert "active" in section
        assert "draft" in section


def test_prompt_section_excludes_hidden_skills():
    """prompt section 不应包含 disabled/legacy Skill。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill_md(root / "visible", name="visible", status="active")
        _write_skill_md(root / "gone", name="gone", status="disabled")

        registry = SkillRegistry(roots=[root])
        section = build_skills_prompt_section(registry)

        assert "visible" in section
        assert "gone" not in section


# ==================================================================
# Level 2: body loading only after selection
# ==================================================================

def test_loader_loads_body_after_selection():
    """SkillLoader.load_body() 应在 Skill 被选中后才加载 SKILL.md body。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill_md(root / "target", name="target",
                        body="# Custom Body\n\nTarget-specific instructions.")

        registry = SkillRegistry(roots=[root])
        desc = registry.get_descriptor("target")
        assert desc is not None

        loader = SkillLoader(registry)
        body = loader.load_body("target")
        assert "# Custom Body" in body
        assert "Target-specific instructions" in body


def test_loader_refuses_body_for_hidden_skill():
    """disabled Skill 的 body 不应被加载（默认行为 fail closed）。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill_md(root / "hidden", name="hidden", status="disabled",
                        body="# Secret Stuff")

        registry = SkillRegistry(roots=[root])
        loader = SkillLoader(registry)

        with pytest.raises(SkillLoadError):
            loader.load_body("hidden")


def test_loader_body_for_nonexistent_skill_fails():
    """加载不存在 Skill 的 body 应 fail closed。"""
    registry = SkillRegistry(roots=[])
    loader = SkillLoader(registry)

    with pytest.raises(SkillLoadError):
        loader.load_body("nonexistent")


# ==================================================================
# Level 3: on-demand resource loading
# ==================================================================

def test_loader_loads_reference_on_demand():
    """references 只应在显式请求时加载。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        skill_dir = root / "ref-skill"
        _write_skill_md(skill_dir, name="ref-skill",
                        extra_frontmatter="""resources:
  references:
    - guide.md
  scripts: []
  templates: []
  tests: []
  dogfood: []""")
        _write_resource(skill_dir, "references", "guide.md", "# Reference Guide\n\nDetails here.")

        registry = SkillRegistry(roots=[root])
        loader = SkillLoader(registry)

        # 只有显式请求时才加载
        content = loader.load_resource("ref-skill", "references", "guide.md")
        assert "# Reference Guide" in content
        assert "Details here" in content


def test_loader_resource_path_traversal_blocked():
    """资源路径逃逸（.. / 绝对路径）必须被阻止。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        skill_dir = root / "escape-skill"
        _write_skill_md(skill_dir, name="escape-skill",
                        extra_frontmatter="""resources:
  references:
    - guide.md
  scripts: []
  templates: []
  tests: []
  dogfood: []""")

        registry = SkillRegistry(roots=[root])
        loader = SkillLoader(registry)

        # 路径逃逸尝试
        for bad_path in ["../secret.txt", "/etc/passwd", "../../.env"]:
            with pytest.raises(SkillLoadError):
                loader.load_resource("escape-skill", "references", bad_path)


def test_loader_resource_outside_allowed_subdir_blocked():
    """请求不属于 references/scripts/templates/tests/dogfood 的资源应被阻止。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill_md(root / "res-skill", name="res-skill")

        registry = SkillRegistry(roots=[root])
        loader = SkillLoader(registry)

        for bad_subdir in ["secrets", "config", "cache"]:
            with pytest.raises(SkillLoadError):
                loader.load_resource("res-skill", bad_subdir, "file.txt")  # type: ignore[arg-type]


# ==================================================================
# 审计：loaded levels 可观测
# ==================================================================

def test_loader_tracks_loaded_levels():
    """SkillLoader 应可追踪加载了哪些 level 的资源。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        skill_dir = root / "track-skill"
        _write_skill_md(skill_dir, name="track-skill",
                        extra_frontmatter="""resources:
  references:
    - ref.md
  scripts: []
  templates: []
  tests: []
  dogfood: []""")
        _write_resource(skill_dir, "references", "ref.md", "ref content")

        registry = SkillRegistry(roots=[root])
        loader = SkillLoader(registry)

        # 初始状态：无加载记录
        assert "track-skill" not in loader.loaded_levels

        # 加载 body（Level 2）
        loader.load_body("track-skill")
        assert loader.loaded_levels["track-skill"] == 2

        # 加载 resource（Level 3）
        loader.load_resource("track-skill", "references", "ref.md")
        assert loader.loaded_levels["track-skill"] == 3


def test_loader_audit_record_includes_loaded_resources():
    """审计信息应包含已加载的资源列表。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        skill_dir = root / "audit-skill"
        _write_skill_md(skill_dir, name="audit-skill",
                        extra_frontmatter="""resources:
  references:
    - audit-ref.md
  scripts: []
  templates: []
  tests: []
  dogfood: []""")
        _write_resource(skill_dir, "references", "audit-ref.md", "audit content")

        registry = SkillRegistry(roots=[root])
        loader = SkillLoader(registry)

        loader.load_body("audit-skill")
        loader.load_resource("audit-skill", "references", "audit-ref.md")

        audit = loader.get_audit_record("audit-skill")
        assert audit["loaded_level"] == 3
        assert "references/audit-ref.md" in audit["loaded_resources"]


# ==================================================================
# 大文件不默认加载
# ==================================================================

def test_loader_large_resource_policy():
    """大文件（超过阈值）的资源加载行为应可被策略控制。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        skill_dir = root / "big-skill"
        _write_skill_md(skill_dir, name="big-skill",
                        extra_frontmatter="""resources:
  references:
    - large.md
  scripts: []
  templates: []
  tests: []
  dogfood: []""")
        # 创建一个较大的文件
        large_content = "# Large File\n\n" + "data " * 2000
        _write_resource(skill_dir, "references", "large.md", large_content)

        registry = SkillRegistry(roots=[root])
        # 使用较小的 max_resource_bytes
        loader = SkillLoader(registry, max_resource_bytes=1000)

        with pytest.raises(SkillLoadError) as exc_info:
            loader.load_resource("big-skill", "references", "large.md")
        assert "过大" in exc_info.value.message or "size" in exc_info.value.message.lower() or "exceed" in exc_info.value.message.lower()


# ==================================================================
# 不执行代码、不访问网络、不读 .env
# ==================================================================

def test_loader_never_executes_code():
    """SkillLoader 不能执行任何代码（scripts 目录的内容只是文本）。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        skill_dir = root / "code-skill"
        _write_skill_md(skill_dir, name="code-skill",
                        extra_frontmatter="""resources:
  references: []
  scripts:
    - helper.py
  templates: []
  tests: []
  dogfood: []""")
        _write_resource(skill_dir, "scripts", "helper.py", "print('should not run')")

        registry = SkillRegistry(roots=[root])
        loader = SkillLoader(registry)

        # 加载应返回文件内容（文本），不应执行
        content = loader.load_resource("code-skill", "scripts", "helper.py")
        assert "print('should not run')" in content
        # 验证没有被执行（如果执行了，进程状态会变化，但我们只验证返回值是 str）


def test_loader_never_reads_env():
    """SkillLoader 不能读取 .env 文件。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill_md(root / "env-skill", name="env-skill",
                        extra_frontmatter="""resources:
  references:
    - readme.md
  scripts: []
  templates: []
  tests: []
  dogfood: []""")
        _write_resource(root / "env-skill", "references", "readme.md", "safe content")
        # 在 skill dir 中创建 .env
        (root / "env-skill" / ".env").write_text("SECRET=value")

        registry = SkillRegistry(roots=[root])
        loader = SkillLoader(registry)

        # .env 文件不应该被加载
        with pytest.raises(SkillLoadError):
            loader.load_resource("env-skill", "references", ".env")


# ==================================================================
# prompt_section 中 body 注入防护
# ==================================================================

def test_build_skill_body_section_is_per_skill():
    """单 Skill body section 只包含该 Skill 的内容。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _write_skill_md(root / "picker", name="picker", body="Picker specific body")

        registry = SkillRegistry(roots=[root])
        loader = SkillLoader(registry)
        body = loader.load_body("picker")

        section = build_skill_body_section("picker", body)
        assert "Picker specific body" in section
        assert "picker" in section


# ==================================================================
# 确认不 import legacy
# ==================================================================

def test_loader_module_does_not_import_legacy():
    """loader.py 和 prompt_section.py 不能 import agent.skills / agent.legacy_skills。"""
    import ast
    from pathlib import Path as P

    for module_path in ["agent/skill_system/loader.py", "agent/skill_system/prompt_section.py"]:
        p = P(__file__).resolve().parents[1] / module_path
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("agent.skills"), f"{module_path} imports {alias.name}"
                    assert not alias.name.startswith("agent.legacy_skills"), f"{module_path} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("agent.skills"), f"{module_path} imports {node.module}"
                assert not node.module.startswith("agent.legacy_skills"), f"{module_path} imports {node.module}"
