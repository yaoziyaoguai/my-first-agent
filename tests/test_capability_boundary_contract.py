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
SKILL_MODULE = PROJECT_ROOT / "agent" / "skills" / "local.py"
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


def test_skill_and_subagent_local_modules_do_not_import_runtime_or_tools() -> None:
    """local MVP 模块只能声明边界，不能直接接入 runtime/tool executor。"""

    forbidden = {
        "agent.core",
        "agent.tool_executor",
        "agent.tool_registry",
        "agent.tools",
        "agent.skills.installer",
    }

    assert _agent_imports(SKILL_MODULE).isdisjoint(forbidden)
    assert _agent_imports(SUBAGENT_MODULE).isdisjoint(forbidden)


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
    """二者可共享 parent policy 数据，但不会自动执行或调用工具。"""

    from agent.skills.local import load_local_skill_descriptor
    from agent.subagents.local import build_delegation_request
    from agent.subagents.local import load_local_subagent_profile

    skill = load_local_skill_descriptor(
        PROJECT_ROOT / "tests" / "fixtures" / "skills" / "safe-writer"
    ).descriptor
    subagent = load_local_subagent_profile(
        PROJECT_ROOT / "tests" / "fixtures" / "subagents" / "code-reviewer"
    ).profile

    request = build_delegation_request(
        subagent,
        task="review skill usage",
        parent_allowed_tools=skill.allowed_tools,
    )

    assert request.ok is True
    assert request.request is not None
    assert request.request.parent_controlled is True
    assert request.request.allowed_tools == ("read_file",)
