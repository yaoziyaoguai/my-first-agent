"""Skill Memory Boundary —— Skill 与 Memory 之间的安全适配器。

设计原则（来自 RFC Sec 3 / SDD Sec 7）：
- Skill 可以声明 memory_scope
- Runtime / adapter 可提供只读 context
- Skill 不直接写 MemoryStore
- Skill output 如需记忆，作为 proposal 回到 Memory governance
- 无 silent procedural retain
- 无 auto approve
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.skill_system.descriptor import MemoryScope, SkillDescriptor


@dataclass(frozen=True)
class MemoryContextPolicy:
    """Runtime 为一次 Skill 调用批准的 Memory 上下文策略。"""

    can_read: bool
    """是否允许 Skill 读取已批准的 Memory 上下文。"""

    can_propose: bool
    """是否允许 Skill 提议新的 Memory 条目。"""

    approved_categories: frozenset[str] = frozenset()
    """已批准的 Memory 类别集合。"""


@dataclass(frozen=True)
class MemoryProposal:
    """Skill 提议的 Memory 候选项——不直接写入，需经 governance。"""

    content: str
    """提议的 Memory 内容。"""

    category: str
    """Memory 类别（如 'user_preference', 'fact'）。"""

    confidence: float = 0.5
    """置信度 (0.0 - 1.0)。"""

    source_skill: str = ""


class SkillMemoryBoundary:
    """Skill 与 Memory 的边界适配器。

    不直接持有 MemoryStore 引用——通过 policy 控制。
    """

    def __init__(self, descriptor: SkillDescriptor):
        self._descriptor = descriptor
        self._scope: MemoryScope = descriptor.memory_scope

    def can_read_context(self) -> bool:
        """Skill 是否可以请求只读 Memory 上下文。"""
        return self._scope in ("read_context", "propose_memory")

    def can_propose_memory(self) -> bool:
        """Skill 是否可以提议 Memory 写入。"""
        return self._scope == "propose_memory"


def check_memory_proposal(
    descriptor: SkillDescriptor,
    policy: MemoryContextPolicy,
    category: str,
) -> bool:
    """安全网关：检查 Memory proposal 是否应被接受。

    返回 True 表示 proposal 可以进入 governance 审批流程，
    不表示直接写入。
    """
    if descriptor.memory_scope == "none":
        return False
    if not policy.can_propose:
        return False
    return category in policy.approved_categories
