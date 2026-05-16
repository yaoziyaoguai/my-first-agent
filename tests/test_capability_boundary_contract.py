"""Skill/Subagent/Tool capability boundary contract.

Pack 7 不实现真实 activation；它把三者关系钉死：
- Tool 是原子执行能力；
- Skill 是同一 parent 上下文里的 capability descriptor；
- Subagent 是 parent-controlled delegation request/result；
- Skill/Subagent 都不能直接绕过 runtime/tool policy。
"""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_TOMBSTONE = PROJECT_ROOT / "agent" / "skills" / "__init__.py"
LEGACY_SKILLS_DIR = PROJECT_ROOT / "agent" / "legacy_skills"
FORMAL_SKILL_SYSTEM_DIR = PROJECT_ROOT / "agent" / "skill_system"
SUBAGENT_MODULE = PROJECT_ROOT / "agent" / "subagents" / "local.py"
DOC_PATH = PROJECT_ROOT / "docs" / "CAPABILITY_BOUNDARIES.md"


def _agent_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name.startswith("agent"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "agent":
                imports.update(f"agent.{alias.name}" for alias in node.names)
            elif node.module.startswith("agent."):
                imports.add(node.module)
    return imports


def test_skill_tombstone_and_subagent_local_modules_do_not_import_runtime_or_tools() -> None:
    """Skill tombstone 和 subagent local 模块不能直接接入 runtime/tool executor。

    旧 Skill MVP 已隔离到 `agent.legacy_skills`，本测试不再把它当正式
    capability module；这里只保护正式入口不能继续导入旧实现。
    """

    forbidden = {
        "agent.core",
        "agent.tool_executor",
        "agent.tool_registry",
        "agent.tools",
        "agent.legacy_skills",
    }

    assert _agent_imports(SKILL_TOMBSTONE).isdisjoint(forbidden)
    assert _agent_imports(SUBAGENT_MODULE).isdisjoint(forbidden)


def test_formal_skill_namespace_does_not_import_legacy_skills() -> None:
    """正式 Skill 命名空间不得反向依赖 quarantined legacy implementation。"""

    if not FORMAL_SKILL_SYSTEM_DIR.exists():
        assert not FORMAL_SKILL_SYSTEM_DIR.exists()
        return

    leaked: dict[str, list[str]] = {}
    for path in FORMAL_SKILL_SYSTEM_DIR.rglob("*.py"):
        imports = sorted(
            name
            for name in _agent_imports(path)
            if name == "agent.legacy_skills" or name.startswith("agent.legacy_skills.")
        )
        if imports:
            leaked[str(path.relative_to(PROJECT_ROOT))] = imports

    assert leaked == {}


def test_legacy_skill_package_is_quarantined_not_formal_boundary() -> None:
    """旧 Skill 代码只作为历史参考，不能被测试继续当成正式 Skill MVP。"""

    assert (LEGACY_SKILLS_DIR / "README.md").is_file()
    assert "agent/skill_system/" in (LEGACY_SKILLS_DIR / "README.md").read_text(
        encoding="utf-8"
    )


def test_skill_subagent_tool_boundary_doc_exists() -> None:
    """docs 要明确 skill/subagent/tool 三者边界，避免 future activation 漂移。"""

    text = DOC_PATH.read_text(encoding="utf-8")

    required = (
        "Tool = atomic execution",
        "Skill = local capability descriptor",
        "Subagent = parent-controlled delegation",
        "parent runtime remains in control",
        "no direct tool execution",
        "no real LLM/provider",
        "no external process",
        "fake-first",
        "local-only",
        "not a broad refactor",
    )
    for phrase in required:
        assert phrase in text


def test_skill_and_subagent_can_share_parent_policy_without_activation() -> None:
    """共享 parent policy 的正式测试等待 `agent/skill_system` 实现。

    本轮只清理旧 prototype，不实现正式 Skill descriptor；因此这里只确认
    SubAgent local request 仍由 parent policy 裁剪，Skill 侧不再从 legacy MVP
    提供运行时对象。
    """

    from agent.subagents.local import build_delegation_request
    from agent.subagents.local import load_local_subagent_profile

    subagent = load_local_subagent_profile(
        PROJECT_ROOT / "tests" / "fixtures" / "subagents" / "code-reviewer"
    ).profile

    request = build_delegation_request(
        subagent,
        task="review skill usage",
        parent_allowed_tools=("read_file", "write_file"),
    )

    assert request.ok is True
    assert request.request is not None
    assert request.request.parent_controlled is True
    assert request.request.allowed_tools == ("read_file",)
