"""Runtime pending request 的窄类型契约。

这些 TypedDict 只描述现有 JSON-safe dict 结构，不改变 checkpoint schema，
也不引入新的状态机字段。它们存在的边界价值是：core / confirmation /
memory / tool executor 仍可传递普通 dict，但 public/cross-module API 不再
退化成无语义的 ``dict[str, Any]``。
"""

from __future__ import annotations

from typing import Any, TypedDict


class MemoryInlineConfirmationPayload(TypedDict, total=False):
    """inline procedural confirmation 在 pending dict 内携带的最小 payload。

    该 payload 仍由 memory_interaction 负责构造和解析；confirmation handler
    只能按 awaiting_kind 分流，不能理解 memory store 或 governance 内部。
    """

    candidate_content: str
    candidate_kind: str
    source_evidence: list[str]
    allowed_actions: list[str]
    metadata: dict[str, Any]


class ConfirmationActionSpec(TypedDict, total=False):
    """未来结构化 option/action 的轻量契约。

    当前运行时仍使用 ``options: list[str]`` 保持兼容；这个类型先给新边界留
    下明确名字，避免继续把 action 语义散落为匿名 dict。
    """

    label: str
    value: str
    description: str
    requires_free_text: bool


class PendingUserInputRequest(TypedDict, total=False):
    """TaskState.pending_user_input_request 的现有 dict 结构。

    字段按既有来源合并：
    - request_user_input / fallback / no_progress：question、why_needed、
      options、context、tool_use_id、step_index
    - feedback_intent：pending_feedback_text、origin_status
    - memory confirmation：_candidate_id、_choice_map、_origin_status
    - memory inline confirmation：actions、_inline_confirmation_request

    这是类型收敛，不是 schema migration；未知旧字段仍由 total=False 兼容。
    """

    awaiting_kind: str
    question: str
    why_needed: str
    options: list[str]
    actions: list[str]
    context: str
    tool_use_id: str
    step_index: int | None
    pending_feedback_text: str
    origin_status: str
    _candidate_id: str | None
    _choice_map: dict[str, str]
    _origin_status: str
    _inline_confirmation_request: MemoryInlineConfirmationPayload


__all__ = [
    "ConfirmationActionSpec",
    "MemoryInlineConfirmationPayload",
    "PendingUserInputRequest",
]
