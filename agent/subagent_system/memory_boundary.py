"""SubAgent Memory boundary.

SubAgent 可以读取 parent 提供的只读上下文，或提出 MemoryProposal；持久化、
审批和写入仍属于 Memory governance。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryProposal:
    content: str
    category: str
    confidence: float = 0.5


@dataclass(frozen=True)
class RoutedMemoryProposal:
    content: str
    category: str
    confidence: float
    source: str
    subagent_name: str
    auto_approved: bool = False


class SubAgentMemoryBoundary:
    """No MemoryStore reference; only read snapshot and route proposals."""

    def __init__(self, approved_context: str | None = None) -> None:
        self._approved_context = approved_context

    def read_context(self, scope: str) -> str | None:
        if scope in {"read_context", "propose"}:
            return self._approved_context
        return None

    def check_proposal(self, proposal: MemoryProposal, scope: str) -> bool:
        return bool(proposal.content and proposal.category and scope == "propose")

    def route_proposal(
        self, proposal: MemoryProposal, *, subagent_name: str
    ) -> RoutedMemoryProposal:
        return RoutedMemoryProposal(
            content=proposal.content,
            category=proposal.category,
            confidence=proposal.confidence,
            source="subagent",
            subagent_name=subagent_name,
            auto_approved=False,
        )

