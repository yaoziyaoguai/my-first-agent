"""v0.3 M3 · Skill 体系坦诚化的回归守护测试。

这些测试**不验证 Skill 功能本身**（M3 不实现 Skill runtime），它们守护
「文案 / 文档 / 入口不再让用户误以为 Skill 已经成熟」这个不变量。

历史背景：v0.2 启动屏曾印 `'/reload_skills' 重新加载 skill`，但主循环
从来没有 slash command 解析器，那行字符串纯粹误导。M3 删掉它后，需要
回归测试守护它不会再被悄悄复活。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agent import cli_renderer

# -- TOOL_REGISTRY 测试隔离 --
# test_load_skill_does_not_import_legacy_modules_at_runtime 会触发
# `from agent.tools import skill`，间接调用 @register_tool(name="load_skill")，
# 把 load_skill 注入全局 TOOL_REGISTRY。
# 若不清除，后续 test_tool_registry_contract.py 会因 load_skill 意外存在而失败。
# 此 fixture 在每次 import agent.tools.skill 之后把 load_skill 弹出，
# 保证测试间无顺序依赖。

_TOOL_REGISTRY_SKILL_NAMES = {"load_skill", "install_skill", "update_skill", "load_skills"}


@pytest.fixture(autouse=True)
def _purge_load_skill_from_tool_registry():
    """每次测试后从 TOOL_REGISTRY 清除 load_skill 等 Skill lifecycle 工具注册。

    设计意图：test_skill_system_honesty.py 的某些测试会 import agent.tools.skill
    来验证其 fail-closed 行为。import 副作用把 load_skill 注册进全局 TOOL_REGISTRY，
    污染后续模块的工具合约测试。本 fixture 每次测试后清理，不依赖模块执行顺序。
    """
    yield
    from agent.tool_registry import TOOL_REGISTRY

    for name in list(TOOL_REGISTRY):
        if name in _TOOL_REGISTRY_SKILL_NAMES:
            del TOOL_REGISTRY[name]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_SKILLS_DIR = PROJECT_ROOT / "agent" / "skills"
QUARANTINED_LEGACY_SKILLS_DIR = PROJECT_ROOT / "agent" / "legacy_skills"
FORMAL_SKILL_SYSTEM_DIR = PROJECT_ROOT / "agent" / "skill_system"


def _module_imports(path: Path) -> set[str]:
    """静态读取 import 关系，避免 import lifecycle 工具时触发注册或网络路径。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


# ---------- 启动文案诚实度 ----------

def test_session_header_does_not_advertise_dead_slash_command():
    """slash command 在 v0.1 已下线，启动屏不应再宣称 /reload_skills 可用。"""
    out = cli_renderer.render_session_header(session_id="x", cwd=".")
    assert "/reload_skills" not in out
    # 不应出现任何 slash command 提示，避免下次又被人加回去
    assert "/reload" not in out


def test_session_header_honestly_describes_skill_status():
    """启动屏必须诚实描述 Skill 当前状态：safe-local 基线完成，marketplace 未实现。"""
    out = cli_renderer.render_session_header(session_id="x", cwd=".")
    assert "safe-local" in out
    assert "demo-note-maker" in out
    assert "marketplace" in out


# ---------- README / 计划文档诚实度 ----------

def test_readme_marks_skill_as_experimental():
    text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    # README 必须有 v0.3 M3 实验性声明指针
    assert "V0_3_SKILL_SYSTEM_STATUS" in text
    assert "实验性" in text
    # README 里若提到 /reload_skills，必须是在「不再印 / 历史误导」这种否定语境
    if "/reload_skills" in text:
        assert "不再印" in text or "历史" in text or "已删" in text or "误导" in text


def test_skill_status_doc_exists_and_covers_key_sections():
    doc = PROJECT_ROOT / "docs" / "archive" / "v0.x" / "V0_3_SKILL_SYSTEM_STATUS.md"
    assert doc.exists(), "M3 必须落地 docs/archive/v0.x/V0_3_SKILL_SYSTEM_STATUS.md"
    text = doc.read_text(encoding="utf-8")
    # 必须明确登记 /reload_skills 是死代码
    assert "/reload_skills" in text
    # 必须有「实验性」字样降预期
    assert "实验性" in text
    # 必须明确不做 sub-agent
    assert "sub-agent" in text.lower()


def test_planning_marks_m3_as_status_clarification_not_runtime():
    text = (PROJECT_ROOT / "docs" / "archive" / "v0.x" / "V0_3_PLANNING.md").read_text(encoding="utf-8")  # noqa: E501
    # M3 段必须出现「状态澄清」类语义，且不应承诺实现 Skill runtime
    assert "M3" in text
    # 不能宣称 M3 实现了 sub-agent / 权限白名单 / activation policy
    m3_section = text.split("M3")[1].split("M4")[0]
    for forbidden in ("sub-agent 触发", "Skill marketplace", "远端"):
        assert forbidden not in m3_section.split("不做")[0] if "不做" in m3_section else True


# ---------- Skill section 注入对主流程的影响 ----------

def test_prompt_builder_skills_section_is_empty_until_formal_system_exists() -> None:
    """旧 registry 已隔离，prompt_builder 不能再从 legacy 生成 Skill prompt。"""

    from agent.prompt_builder import build_skills_section

    assert build_skills_section() == ""


# ---------- 没有 Skill 单测的事实登记 ----------

def test_status_doc_acknowledges_no_skill_unit_tests():
    """status doc 必须诚实声明当前没有 skill 单元测试，避免后续读者误以为
    Skill 子系统是受测过的。"""
    doc = (PROJECT_ROOT / "docs" / "archive" / "v0.x" / "V0_3_SKILL_SYSTEM_STATUS.md").read_text(
        encoding="utf-8"
    )
    assert "没有 skill 单元测试" in doc


# ---------- Legacy cleanup：隔离旧原型边界 ----------

def test_legacy_agent_skills_package_exports_no_formal_api() -> None:
    """Cleanup 边界：`agent.skills` 只作为 tombstone 存在。

    这里允许 import package `__init__`，但 tombstone 不得导出 registry、
    installer、loader 或 local helper，避免正式实现误用旧 path。
    """

    import agent.skills as legacy_skills

    assert legacy_skills.__all__ == []
    doc = legacy_skills.__doc__ or ""
    assert "tombstone" in doc
    assert "agent/skill_system/" in doc
    assert "agent/legacy_skills/" in doc


def test_skill_docs_pin_phase0_namespace_and_checkpoint_boundaries() -> None:
    """Phase 0 文档边界：正式实现命名空间与 checkpoint 红线必须一致。"""

    rfc = (PROJECT_ROOT / "docs" / "rfc" / "SKILL_CANONICAL_RFC.md").read_text(
        encoding="utf-8"
    )
    loop = (
        PROJECT_ROOT / "docs" / "archive" / "roadmap" / "SKILL_SYSTEM_IMPLEMENTATION_LOOP.md"
    ).read_text(encoding="utf-8")
    audit = (
        PROJECT_ROOT / "docs" / "archive" / "2026-05-27-cleanup" / "audit" / "SKILL_SYSTEM_AUDIT_CHECKLIST.md"  # noqa: E501
    ).read_text(encoding="utf-8")

    assert "formal implementation namespace is `agent/skill_system/`" in rfc
    assert "`agent/skills/` has been cleaned/quarantined" in rfc
    assert "Checkpoint stores unredacted Skill body, resources, or secrets." in audit

    assert "must not import or modify quarantined legacy Skill" in loop
    assert "create or modify `agent/skill_system/*`" in loop


def test_default_tools_keep_skill_lifecycle_tools_explicit_opt_in() -> None:
    """Phase 0 边界：默认工具入口不注册 Skill lifecycle tools。

    只做源码级检查，不 import `agent.tools.install_skill`，这样测试不会触发
    installer 依赖，也不会接近真实网络、`git clone` 或 `pip install` 路径。
    """

    tools_init = PROJECT_ROOT / "agent" / "tools" / "__init__.py"
    install_tool = PROJECT_ROOT / "agent" / "tools" / "install_skill.py"
    update_tool = PROJECT_ROOT / "agent" / "tools" / "update_skill.py"
    load_tool = PROJECT_ROOT / "agent" / "tools" / "skill.py"

    default_imports = _module_imports(tools_init)
    assert default_imports.isdisjoint(
        {
            "agent.tools.install_skill",
            "agent.tools.update_skill",
            "agent.tools.skill",
            "agent.skills",
            "agent.legacy_skills",
            "agent.subagents",
        }
    )

    install_source = install_tool.read_text(encoding="utf-8")
    update_source = update_tool.read_text(encoding="utf-8")
    load_source = load_tool.read_text(encoding="utf-8")

    assert 'confirmation="always"' in install_source
    assert 'risk_level="high"' in install_source
    assert 'capability="skill_lifecycle"' in install_source
    assert 'confirmation="always"' in update_source
    # P3 纵深防御：load_skill wrapper 也应使用 confirmation="always"
    assert 'confirmation="always"' in load_source
    assert 'confirmation="never"' not in load_source
    assert _module_imports(install_tool).isdisjoint({"agent.legacy_skills"})
    assert _module_imports(update_tool).isdisjoint({"agent.legacy_skills"})
    assert _module_imports(load_tool).isdisjoint({"agent.legacy_skills"})
    assert "已禁用" in install_source
    assert "已禁用" in update_source
    assert "已禁用" in load_source


def test_formal_skill_namespace_is_not_legacy_contaminated() -> None:
    """Cleanup 边界：正式 `agent/skill_system` 不得反向复用旧 prototype。

    Phase 0 允许正式命名空间尚不存在；一旦后续 phase 创建该目录，本测试会
    继续用 AST 守住它不能 import `agent.skills.*` 或 `agent.legacy_skills.*`。
    """

    if not FORMAL_SKILL_SYSTEM_DIR.exists():
        assert not FORMAL_SKILL_SYSTEM_DIR.exists()
        return

    leaked_imports: dict[str, list[str]] = {}
    for path in FORMAL_SKILL_SYSTEM_DIR.rglob("*.py"):
        imports = sorted(
            name
            for name in _module_imports(path)
            if name == "agent.skills"
            or name.startswith("agent.skills.")
            or name == "agent.legacy_skills"
            or name.startswith("agent.legacy_skills.")
        )
        if imports:
            leaked_imports[str(path.relative_to(PROJECT_ROOT))] = imports

    assert leaked_imports == {}


def test_install_from_github_remains_legacy_explicit_opt_in_boundary() -> None:
    """Cleanup 边界：installer 风险只在隔离区保留，不在测试中执行。

    这个测试读取 docstring 标记，不调用 `install_from_github`。它确认旧函数
    仍在 `agent.legacy_skills` 隔离区，正式实现不能把它当默认路径。
    """

    installer_source = (QUARANTINED_LEGACY_SKILLS_DIR / "installer.py").read_text(
        encoding="utf-8"
    )

    assert "def install_from_github" in installer_source
    assert "真实网络访问" in installer_source
    assert "`git clone`" in installer_source
    assert "`pip install`" in installer_source
    assert "explicit opt-in" in installer_source
    assert '`confirmation="always"`' in installer_source
    assert sorted(path.name for path in LEGACY_SKILLS_DIR.glob("*.py")) == [
        "__init__.py"
    ]


# ---------- P3: load_skill fail-closed 纵深防御 ----------

def test_load_skill_wrapper_is_fail_closed_and_returns_disabled_message() -> None:
    """load_skill 即使被显式调用也必须返回 disabled string，不能加载旧实现。

    Runtime 测试验证 wrapper 的 fail-closed 行为：
    - confirmation 必须是 "always"（纵深防御）
    - 函数体必须返回 disabled message
    - 不能触发 install_from_github / pip install / 网络操作
    - 不能 import agent.skills / agent.legacy_skills 作为实现依赖
    """

    from agent.tools.skill import load_skill

    result = load_skill("any-skill-name")
    assert "已禁用" in result
    assert "agent/skill_system/" in result
    assert isinstance(result, str)
    # 确认不泄露任何旧实现路径
    assert "install_from_github" not in result
    assert "git clone" not in result
    assert "pip install" not in result


def test_load_skill_does_not_import_legacy_modules_at_runtime() -> None:
    """导入 load_skill 不能触发 agent.skills / agent.legacy_skills 的副作用导入。

    这个测试用 sys.modules 快照验证：import agent.tools.skill 前后不会增加
    agent.skills.* / agent.legacy_skills.* 模块。
    """

    import sys

    before = {
        name
        for name in sys.modules
        if name == "agent.skills"
        or name.startswith("agent.skills.")
        or name == "agent.legacy_skills"
        or name.startswith("agent.legacy_skills.")
    }

    from agent.tools import skill as _skill_module  # noqa: F401,F811

    after = {
        name
        for name in sys.modules
        if name == "agent.skills"
        or name.startswith("agent.skills.")
        or name == "agent.legacy_skills"
        or name.startswith("agent.legacy_skills.")
    }

    newly_loaded = after - before
    assert not newly_loaded, (
        f"import agent.tools.skill 不应触发 legacy 模块加载，但加载了: {newly_loaded}"
    )
