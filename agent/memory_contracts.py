"""Stage 3 Memory 的无副作用契约层。

本模块只定义 MemoryCandidate / MemoryDecision 这组语言边界，故意不实现
MemoryRecord、MemoryStore、retrieval、prompt 注入或 provider adapter。

架构边界：
- Candidate 只是“可能值得记住”的候选，不代表已经保存。
- Decision 只是“应该如何处理候选”的决策结果，不执行 IO、不写 storage。
- 敏感候选的 retain/update/recall 必须显式要求用户确认；这是 contract-level
  safety invariant，不是完整 MemoryPolicy。

为什么单独成模块：
`agent.memory` 目前承担 context compression 和静态 memory section，占位语义
已经较重；Slice 1 把纯 contract 放在独立文件，避免把 compression、policy、
storage、prompt 注入继续堆进同一个模块形成新的巨石。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MemoryDecisionType(StrEnum):
    """Memory 治理动作词表。

    词表只描述 decision，不描述执行。比如 RETAIN 不是“已经写入”，FORGET 也
    不是“已经删除”；执行必须留给后续 store/provider/audit slice。
    """

    RETAIN = "retain"
    RECALL = "recall"
    UPDATE = "update"
    FORGET = "forget"
    REJECT = "reject"
    NO_OP = "no-op"
    CLARIFY = "clarify"


class MemoryScope(StrEnum):
    """候选记忆适用范围。

    scope 是后续 namespace / provider 的输入信号，但当前不创建 namespace、
    不写 store，也不读取任何真实 memory artifact。
    """

    SESSION = "session"
    USER = "user"
    PROJECT = "project"
    REPO = "repo"


class MemorySensitivity(StrEnum):
    """候选记忆的敏感度标记。

    Slice 1 不做自动分类；调用方必须显式传入敏感度。后续 MemoryPolicy 可以
    负责分类，本 contract 只保证高敏 decision 不能声明“无需用户确认”。
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    SECRET = "secret"


class MemorySource(StrEnum):
    """候选来源类型。

    来源用于 provenance 和审计解释，不代表信任等级。tool_result / external
    provider 的内容尤其不能因为“有来源”就自动进入长期记忆。
    """

    USER_INPUT = "user_input"
    TOOL_RESULT = "tool_result"
    RUNTIME_EVENT = "runtime_event"
    PROJECT_CONTEXT = "project_context"
    EXTERNAL_PROVIDER = "external_provider"


SENSITIVE_MEMORY_LEVELS = frozenset({
    MemorySensitivity.HIGH,
    MemorySensitivity.SECRET,
})

CONFIRMATION_REQUIRED_DECISIONS = frozenset({
    MemoryDecisionType.RETAIN,
    MemoryDecisionType.RECALL,
    MemoryDecisionType.UPDATE,
})


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """一条“可能值得记住”的候选事实。

    Candidate 不包含 status/version/namespace/updated_at 等持久化字段，避免
    在 Slice 1 把候选误当成已保存的 MemoryRecord。它可以来自用户输入、
    tool_result、runtime event、项目上下文或未来 external provider，但来源本身
    不授予 retain 权限。
    """

    id: str
    content: str
    source: MemorySource
    source_event: str | None
    proposed_type: str
    scope: MemoryScope
    sensitivity: MemorySensitivity
    stability: str
    confidence: float
    reason: str
    created_at: str | None = None

    def __post_init__(self) -> None:
        """固定最小字段不变量，避免 contract 承载空候选。"""

        if not self.id.strip():
            raise ValueError("MemoryCandidate.id 不能为空")
        if not self.content.strip():
            raise ValueError("MemoryCandidate.content 不能为空")
        if not self.proposed_type.strip():
            raise ValueError("MemoryCandidate.proposed_type 不能为空")
        if not self.stability.strip():
            raise ValueError("MemoryCandidate.stability 不能为空")
        if not self.reason.strip():
            raise ValueError("MemoryCandidate.reason 不能为空")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("MemoryCandidate.confidence 必须在 0.0 到 1.0 之间")


@dataclass(frozen=True, slots=True)
class MemoryDecision:
    """对候选或已知目标的治理决策。

    Decision 是 immutable result，不执行写入、不调用 provider、不修改 runtime。
    后续 MemoryPolicy 可以产生它，MemoryApproval 可以确认它，MemoryStore 可以在
    更晚的 slice 消费它；本模块不承担这些执行职责。
    """

    decision_type: MemoryDecisionType
    target_candidate: MemoryCandidate | None
    action: str
    requires_user_confirmation: bool
    reason: str
    safety_flags: tuple[str, ...] = field(default_factory=tuple)
    provenance: str | None = None

    def __post_init__(self) -> None:
        """执行 contract-level 安全校验，但不做完整 policy。

        如果候选已经被上游标记为 HIGH/SECRET，那么 retain/update/recall
        不能宣称无需用户确认。这里不判断文本是否敏感，也不决定是否应该 retain；
        只是防止危险 decision 以“不需确认”的形态流入后续 slice。
        """

        if not self.action.strip():
            raise ValueError("MemoryDecision.action 不能为空")
        if not self.reason.strip():
            raise ValueError("MemoryDecision.reason 不能为空")
        if not isinstance(self.safety_flags, tuple):
            object.__setattr__(self, "safety_flags", tuple(self.safety_flags))

        candidate = self.target_candidate
        if (
            candidate is not None
            and candidate.sensitivity in SENSITIVE_MEMORY_LEVELS
            and self.decision_type in CONFIRMATION_REQUIRED_DECISIONS
            and not self.requires_user_confirmation
        ):
            raise ValueError(
                "Sensitive memory decision requires user confirmation"
            )


@dataclass(frozen=True, slots=True)
class MemorySnapshotItem:
    """一条已批准进入 prompt 视图的 memory item。

    SnapshotItem 不是 MemoryRecord：它没有 write/update/delete/status/version，
    只表示“当前这次 prompt 可以看到的、已被上游批准和过滤后的视图项”。
    """

    content: str
    scope: MemoryScope
    provenance: str
    selection_reason: str
    sensitivity: MemorySensitivity = MemorySensitivity.LOW

    def __post_init__(self) -> None:
        """保证 prompt 视图项至少可解释来源和选择原因。"""

        if not self.content.strip():
            raise ValueError("MemorySnapshotItem.content 不能为空")
        if not self.provenance.strip():
            raise ValueError("MemorySnapshotItem.provenance 不能为空")
        if not self.selection_reason.strip():
            raise ValueError("MemorySnapshotItem.selection_reason 不能为空")


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    """prompt_builder 唯一允许消费的 memory 输入视图。

    Snapshot 是已批准、已过滤、有预算的 prompt view，不是 store，也不是所有
    memory 的 dump。它不负责 retrieval，不包含 provider handle，也不执行 IO。
    """

    items: tuple[MemorySnapshotItem, ...] = field(default_factory=tuple)
    selection_reason: str = ""
    omitted_count: int = 0
    safety_filter_summary: str = ""
    token_budget: int | None = None
    rendered_char_budget: int | None = None
    query_context: str | None = None

    @classmethod
    def empty(cls) -> "MemorySnapshot":
        """返回空 snapshot；用于保持现有 prompt 行为。"""

        return cls()

    def __post_init__(self) -> None:
        """固定 snapshot 的最小结构边界。"""

        if not isinstance(self.items, tuple):
            object.__setattr__(self, "items", tuple(self.items))
        if self.omitted_count < 0:
            raise ValueError("MemorySnapshot.omitted_count 不能为负数")
        if self.items and not self.selection_reason.strip():
            raise ValueError("MemorySnapshot.selection_reason 不能为空")
        if self.token_budget is not None and self.token_budget <= 0:
            raise ValueError("MemorySnapshot.token_budget 必须为正数")
        if self.rendered_char_budget is not None and self.rendered_char_budget <= 0:
            raise ValueError("MemorySnapshot.rendered_char_budget 必须为正数")
