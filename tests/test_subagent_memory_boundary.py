"""SubAgent Phase 8: Memory Boundary tests."""

from __future__ import annotations

from agent.subagent_system.memory_boundary import MemoryProposal, SubAgentMemoryBoundary


def test_memory_scope_none_blocks_read_and_proposal() -> None:
    """默认 none 不读取 Memory，也不允许 proposal 进入 governance 队列。"""

    boundary = SubAgentMemoryBoundary(approved_context="private context")

    assert boundary.read_context("none") is None
    assert (
        boundary.check_proposal(
            MemoryProposal(content="remember me", category="fact"), "none"
        )
        is False
    )


def test_read_context_returns_read_only_snapshot_but_blocks_write() -> None:
    """read_context 只读，不提供任何 MemoryStore 写入口。"""

    boundary = SubAgentMemoryBoundary(approved_context="approved summary")

    assert boundary.read_context("read_context") == "approved summary"
    assert (
        boundary.check_proposal(
            MemoryProposal(content="remember me", category="fact"), "read_context"
        )
        is False
    )
    assert not hasattr(boundary, "memory_store")


def test_propose_scope_routes_sanitized_proposal_to_governance() -> None:
    """propose 只表示可进入 governance，不代表 auto approve 或直接持久化。"""

    boundary = SubAgentMemoryBoundary(approved_context="approved summary")
    proposal = MemoryProposal(content="Prefer concise reports", category="user_preference")

    assert boundary.read_context("propose") == "approved summary"
    assert boundary.check_proposal(proposal, "propose") is True
    routed = boundary.route_proposal(proposal, subagent_name="reviewer")
    assert routed.source == "subagent"
    assert routed.subagent_name == "reviewer"
    assert routed.auto_approved is False

