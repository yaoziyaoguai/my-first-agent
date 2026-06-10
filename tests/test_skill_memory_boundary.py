"""Phase 7: Skill Memory Context Boundary 测试。

测试范围（Skill Memory Context Boundary）：
- memory_scope=none / read_context / propose_memory
- Skill 通过 adapter 获取只读 context
- Skill 不直接写 MemoryStore
- Memory proposal 需经 governance
- 无 silent procedural retain
- 无 auto approve
"""
from __future__ import annotations

from agent.skill_system.descriptor import SkillDescriptor
from agent.skill_system.memory_boundary import (
    MemoryContextPolicy,
    MemoryProposal,
    SkillMemoryBoundary,
    check_memory_proposal,
)

# ---- helpers ----

def _desc(memory_scope: str = "none") -> SkillDescriptor:
    return SkillDescriptor(
        name="test-skill",
        description="desc",
        version="0.1.0",
        status="active",
        risk_level="low",
        memory_scope=memory_scope,  # type: ignore[arg-type]
    )


# ==================================================================
# memory_scope=none
# ==================================================================

def test_memory_scope_none_blocks_all():
    """memory_scope=none 时，不应提供 context 也不接受 proposal。"""
    boundary = SkillMemoryBoundary(_desc("none"))
    assert boundary.can_read_context() is False
    assert boundary.can_propose_memory() is False


# ==================================================================
# memory_scope=read_context
# ==================================================================

def test_memory_scope_read_context_allows_read():
    """memory_scope=read_context 允许读取已批准的 context。"""
    boundary = SkillMemoryBoundary(_desc("read_context"))
    assert boundary.can_read_context() is True
    assert boundary.can_propose_memory() is False


# ==================================================================
# memory_scope=propose_memory
# ==================================================================

def test_memory_scope_propose_memory_allows_both():
    """memory_scope=propose_memory 允许读取和提议。"""
    boundary = SkillMemoryBoundary(_desc("propose_memory"))
    assert boundary.can_read_context() is True
    assert boundary.can_propose_memory() is True


# ==================================================================
# Memory proposal 不直接写 Memory
# ==================================================================

def test_memory_proposal_is_not_direct_write():
    """MemoryProposal 只是一个候选项，不执行写入。"""
    proposal = MemoryProposal(
        content="user prefers concise responses",
        category="user_preference",
        confidence=0.8,
    )
    assert proposal.content == "user prefers concise responses"
    # MemoryProposal 没有 write/persist 方法
    assert not hasattr(proposal, "write")
    assert not hasattr(proposal, "persist")
    assert not hasattr(proposal, "save")


# ==================================================================
# check_memory_proposal 便捷函数
# ==================================================================

def test_check_memory_proposal_returns_approved_policy():
    """check_memory_proposal 返回 MemoryContextPolicy 结果。"""
    policy = MemoryContextPolicy(
        can_read=True,
        can_propose=True,
        approved_categories=frozenset({"user_preference", "fact"}),
    )
    desc = _desc("propose_memory")
    result = check_memory_proposal(desc, policy, "user_preference")
    assert result is True


def test_check_memory_proposal_rejected_for_wrong_scope():
    """memory_scope=none 时 proposal 被拒。"""
    policy = MemoryContextPolicy(
        can_read=False,
        can_propose=False,
        approved_categories=frozenset(),
    )
    desc = _desc("none")
    result = check_memory_proposal(desc, policy, "user_preference")
    assert result is False


def test_check_memory_proposal_rejected_for_wrong_category():
    """不在 approved_categories 中的 proposal 被拒。"""
    policy = MemoryContextPolicy(
        can_read=True,
        can_propose=True,
        approved_categories=frozenset({"fact"}),
    )
    desc = _desc("propose_memory")
    result = check_memory_proposal(desc, policy, "preference")
    assert result is False


# ==================================================================
# no legacy import
# ==================================================================

def test_memory_boundary_module_does_not_import_legacy():
    """memory_boundary.py 不能 import agent.skills / agent.legacy_skills。"""
    import ast
    from pathlib import Path

    p = Path(__file__).resolve().parents[1] / "agent" / "skill_system" / "memory_boundary.py"
    tree = ast.parse(p.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("agent.skills")
                assert not alias.name.startswith("agent.legacy_skills")
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("agent.skills")
            assert not node.module.startswith("agent.legacy_skills")
