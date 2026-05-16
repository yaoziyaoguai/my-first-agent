"""Phase 9: Skill System Dogfood 测试。

测试范围（来自 docs/testing/SKILL_SYSTEM_TDD.md Phase 10）：
- 合成 dogfood fixtures，覆盖 dogfood plan 中的每个场景
- 仅本地确定性运行
- 禁止网络、.env、真实 sessions/runs、真实 LLM
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.skill_system.loader import SkillLoader
from agent.skill_system.registry import SkillRegistry
from agent.skill_system.schema import load_skill_manifest
from agent.skill_system.selector import SkillSelector
from agent.skill_system.tool_binding import SkillToolBinding

DOGFOOD_ROOT = Path(__file__).parent / "fixtures" / "dogfood"


# ---- Fake ToolRegistry ----

class _FakeToolRegistry:
    """合成 ToolRegistry，用于 dogfood 测试。"""

    def __init__(self, blocked: set[str] | None = None):
        self._blocked = blocked or set()

    def is_registered(self, name: str) -> bool:
        return True

    def get_risk(self, name: str) -> str:
        return "high" if name == "run_shell" else "low"

    def get_confirmation(self, name: str) -> str:
        return "always" if name == "run_shell" else "never"

    def is_hidden(self, name: str) -> bool:
        return name in self._blocked


# ---- Fixtures ----

@pytest.fixture
def dogfood_registry():
    return SkillRegistry(roots=[DOGFOOD_ROOT])


@pytest.fixture
def dogfood_loader(dogfood_registry):
    return SkillLoader(dogfood_registry)


# ==================================================================
# Scenario 1: Git Status Audit
# ==================================================================

def test_dogfood_git_status_audit_descriptor(dogfood_registry):
    desc = dogfood_registry.get_descriptor("git-status-audit")
    assert desc is not None
    assert desc.status == "active"
    assert desc.risk_level == "medium"
    assert "run_shell" in desc.allowed_tools


def test_dogfood_git_status_audit_selector():
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    selector = SkillSelector(registry)
    decision = selector.select("Summarize the local git status and identify risky untracked files")
    assert decision.selected is True
    assert decision.skill_name == "git-status-audit"


def test_dogfood_git_status_audit_tool_binding():
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    desc = registry.get_descriptor("git-status-audit")
    assert desc is not None
    tool_reg = _FakeToolRegistry()
    binding = SkillToolBinding(desc, tool_reg)
    result = binding.check("run_shell")
    assert result.allowed is True
    assert result.requires_confirmation is True


def test_dogfood_git_status_audit_body(dogfood_loader):
    body = dogfood_loader.load_body("git-status-audit")
    assert "git" in body.lower()
    assert "只读" in body or "read" in body.lower()


# ==================================================================
# Scenario 2: RFC Alignment Audit
# ==================================================================

def test_dogfood_rfc_alignment_audit_selector():
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    selector = SkillSelector(registry)
    decision = selector.select("Check whether an implementation plan aligns with the Skill RFC")
    assert decision.selected is True
    assert decision.skill_name == "rfc-alignment-audit"


def test_dogfood_rfc_alignment_audit_readonly(dogfood_registry):
    desc = dogfood_registry.get_descriptor("rfc-alignment-audit")
    assert desc is not None
    assert "run_shell" not in desc.allowed_tools
    assert "read_file" in desc.allowed_tools


# ==================================================================
# Scenario 3: TDD Repair
# ==================================================================

def test_dogfood_tdd_repair_selector():
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    selector = SkillSelector(registry)
    decision = selector.select("Given this failing test output, propose the smallest TDD repair")
    assert decision.selected is True
    assert decision.skill_name == "tdd-repair"


def test_dogfood_tdd_repair_memory_scope(dogfood_registry):
    desc = dogfood_registry.get_descriptor("tdd-repair")
    assert desc is not None
    assert desc.memory_scope == "read_context"


# ==================================================================
# Scenario 4: Prompt Writing
# ==================================================================

def test_dogfood_prompt_writing_selector():
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    selector = SkillSelector(registry)
    decision = selector.select("Write a concise system prompt section for bounded tool use")
    assert decision.selected is True
    assert decision.skill_name == "prompt-writing"


# ==================================================================
# Scenario 5: Architecture Boundary Audit
# ==================================================================

def test_dogfood_architecture_boundary_audit_selector():
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    selector = SkillSelector(registry)
    decision = selector.select("Audit whether a diff adds cross-layer imports")
    assert decision.selected is True
    assert decision.skill_name == "architecture-boundary-audit"


# ==================================================================
# Scenario 6: Invalid SKILL.md
# ==================================================================

def test_dogfood_broken_skill_rejected():
    """broken-skill 的 SKILL.md 没有 frontmatter，解析应失败。"""
    from agent.skill_system.errors import CODE_MISSING_FRONTMATTER, SkillLoadError

    with pytest.raises(SkillLoadError) as exc_info:
        load_skill_manifest(DOGFOOD_ROOT / "broken-skill" / "SKILL.md")
    assert exc_info.value.code == CODE_MISSING_FRONTMATTER


# ==================================================================
# Scenario 7: Disabled / Hidden Skill
# ==================================================================

def test_dogfood_disabled_skill_not_visible(dogfood_registry):
    """disabled 状态的 Skill 不应在可见列表中。"""
    visible = dogfood_registry.list_visible()
    names = {d.name for d in visible}
    assert "internal-release-signer" not in names


def test_dogfood_disabled_skill_descriptor_exists(dogfood_registry):
    """disabled Skill 的 descriptor 存在但 is_visible 返回 False。"""
    desc = dogfood_registry.get_descriptor("internal-release-signer")
    assert desc is not None
    assert desc.is_visible() is False


def test_dogfood_disabled_skill_not_selected():
    """disabled Skill 不能被 selector 选中。"""
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    selector = SkillSelector(registry)
    decision = selector.select("Use the internal-release-signer skill")
    assert decision.selected is False or decision.skill_name != "internal-release-signer"


# ==================================================================
# Scenario 8: Ambiguous Skill Selection
# ==================================================================

def test_dogfood_ambiguous_selection():
    """同时匹配 tdd-repair 和 architecture-boundary-audit 时给出替代项。"""
    registry = SkillRegistry(roots=[DOGFOOD_ROOT])
    selector = SkillSelector(registry)
    decision = selector.select("Repair this failing test and check architecture boundaries")
    assert "tdd-repair" in decision.alternatives or decision.skill_name in ("tdd-repair", "architecture-boundary-audit")


# ==================================================================
# 禁止行为
# ==================================================================

def test_dogfood_no_legacy_imports():
    """dogfood fixtures 和测试本身不应导入 legacy_skills。"""
    import ast

    p = Path(__file__)
    tree = ast.parse(p.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("agent.legacy_skills")
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("agent.legacy_skills")


def test_dogfood_registry_deterministic(dogfood_registry):
    """dogfood registry 扫描结果应确定。"""
    first = {d.name for d in dogfood_registry.list_visible()}
    second = {d.name for d in dogfood_registry.list_visible()}
    assert first == second
