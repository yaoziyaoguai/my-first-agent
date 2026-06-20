"""Memory confirmation form 语义的集中化边界测试。

v0.9.x Stabilization M2-M3 只允许把既有语义从 emergence 模块中抽出，
不能改变 Memory governance：procedural 仍必须 T1 human confirmation，
silent / auto_retained / none 仍然禁止。
"""

from __future__ import annotations

import pytest

from agent.memory_confirmation_forms import (
    ALLOWED_MEMORY_CONFIRMATION_FORMS,
    DISALLOWED_MEMORY_CONFIRMATION_FORMS,
    validate_memory_confirmation_form,
)


def test_confirmation_forms_keep_existing_t1_semantics() -> None:
    """pending_review 与 inline_confirmation 是当前唯一允许的 T1 form。"""

    assert frozenset({
        "pending_review",
        "inline_confirmation",
    }) == ALLOWED_MEMORY_CONFIRMATION_FORMS
    validate_memory_confirmation_form("pending_review")
    validate_memory_confirmation_form("inline_confirmation")


@pytest.mark.parametrize("form", ["silent", "auto_retained", "none"])
def test_confirmation_forms_reject_silent_or_auto_paths(form: str) -> None:
    """禁止值必须 fail-closed，避免 procedural memory 绕过人类确认。"""

    assert form in DISALLOWED_MEMORY_CONFIRMATION_FORMS
    with pytest.raises(ValueError, match="Procedural memory 永不可"):
        validate_memory_confirmation_form(form)
