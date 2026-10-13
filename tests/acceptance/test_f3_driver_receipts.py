"""F3a/D06：操作证明只认 durable receipts（本次合成 state 内），审批≠执行。"""

from __future__ import annotations

from agent.runtime.contracts import GoalStatus
from scripts.run_real_coding_scenario import (
    product_ran_related_tests,
)
from tests.acceptance import f3_helpers as h


def test_f3_approval_only_is_not_executed_test() -> None:
    """A10-3：只有审批记录、无执行证据 → 不可能构成 typed VERIFIED_DONE state。"""

    import pytest

    with pytest.raises(ValueError, match="VERIFIED_DONE requires"):
        h.state(status=GoalStatus.VERIFIED_DONE, with_claim=False)


def test_f3_executed_success_in_current_goal_passes() -> None:
    """A14/A11-正向：当前 Goal 的成功 receipt + passed evidence → true。"""

    fact = h.process_receipt_fact("p1", exit_code=0)
    state = h.derived_state((fact,))
    ok, reason = product_ran_related_tests(state)
    assert ok is True and reason == ""


def test_f3_old_goal_receipt_is_not_reusable() -> None:
    """A11/R2c：孤立 passed 记录 + 异 Goal 失败 receipt 不构成真实执行证据。"""

    fact = h.process_receipt_fact("p-old", exit_code=1, goal_id="goal-other")
    state = h.state(
        status=GoalStatus.VERIFIED_DONE,
        facts=(fact,),
        evidence=(h.evidence_record("criterion:required-local-process:f3"),),
    )
    ok, reason = product_ran_related_tests(state)
    # B07：证据必须能由内核从 durable facts 重验；孤立 passed 记录 fail closed。
    assert ok is False
    assert "does not rederive" in reason
