"""Memory T1 confirmation form 的集中语义。

本模块只保存 procedural memory 确认形式的词表和校验，不写 store、不调 runtime、
不接 provider，也不决定 candidate 是否可被记住。把它从 emergence 模块抽出，
是为了让 M2/M3 的治理边界更清楚：form 语义集中，执行路径仍留在原有模块。
"""

from __future__ import annotations

from typing import Literal


MemoryConfirmationForm = Literal["pending_review", "inline_confirmation"]

ALLOWED_MEMORY_CONFIRMATION_FORMS: frozenset[str] = frozenset({
    "pending_review",
    "inline_confirmation",
})
"""当前 procedural T1 允许的确认形式。"""

DISALLOWED_MEMORY_CONFIRMATION_FORMS: frozenset[str] = frozenset({
    "silent",
    "auto_retained",
    "none",
})
"""明确禁止的确认形式；它们会绕过或混淆 human confirmation。"""


def validate_memory_confirmation_form(form: str) -> None:
    """校验 confirmation form 不得绕过 procedural human confirmation。

    这是 fail-closed 的边界函数：禁止值直接报错；未知值也报错，避免后续
    refactor 中把未审查的新 form 当作默认安全路径。
    """

    if form in DISALLOWED_MEMORY_CONFIRMATION_FORMS:
        raise ValueError(
            f"confirmation_form='{form}' 不被允许。"
            f"Procedural memory 永不可 silent retain / auto retain。"
            f"允许的 form: pending_review, inline_confirmation"
        )
    if form not in ALLOWED_MEMORY_CONFIRMATION_FORMS:
        raise ValueError(
            f"confirmation_form='{form}' 未经审查。"
            f"允许的 form: pending_review, inline_confirmation"
        )
