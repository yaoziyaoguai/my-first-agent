"""015 U2：ConversationState 对 process authority lease 的有界容量与失效不变量。

lease 由 conversation state 拥有（KTD2/KTD12），容量有界；Goal revision 变更或进入
terminal 状态必须清空 lease。下列测试在 U2 product code 落地后验证这些不变量。
"""

from __future__ import annotations

from dataclasses import fields, replace

import pytest

import agent.runtime.contracts as contracts
from agent.runtime.contracts import (
    ConversationState,
    GoalFrame,
    GoalStatus,
    ProposedCriterion,
)


def test_015_conversation_state_owns_process_leases_with_bounded_capacity() -> None:
    """R8 / KTD2 / KTD12：ConversationState 持有有界 process_leases，默认空。"""

    state_fields = {field.name for field in fields(ConversationState)}
    assert "process_leases" in state_fields, (
        "ConversationState must own process authority leases"
    )
    default_leases = next(
        field.default
        for field in fields(ConversationState)
        if field.name == "process_leases"
    )
    assert default_leases == (), "process_leases must default to empty"
    capacity = getattr(contracts, "MAX_PROCESS_LEASES", None)
    assert isinstance(capacity, int) and capacity > 0, (
        "015 must declare a bounded MAX_PROCESS_LEASES capacity"
    )


def test_015_process_lease_capacity_rejects_overflow_and_duplicate_id() -> None:
    """R9 / KTD4 / KTD12：lease 数量不得超过容量；duplicate lease_id 被拒绝。"""

    lease_type = getattr(contracts, "ProcessAuthorityLeaseV1", None)
    if lease_type is None:
        pytest.fail("015 requires ProcessAuthorityLeaseV1 to test capacity")
    goal = _fixture_goal(revision=1, status=GoalStatus.GOAL_READY)
    base = ConversationState.new("conversation-capacity")
    capacity = contracts.MAX_PROCESS_LEASES
    # 超容量：用 distinct lease_id 构造 capacity+1 条 lease。
    overflow = tuple(
        _fixture_lease(lease_type, ordinal=index) for index in range(capacity + 1)
    )
    with pytest.raises(ValueError):
        replace(base, goal=goal, process_leases=overflow)
    # duplicate lease_id：两条相同 ID 的 lease。
    duplicate = (
        _fixture_lease(lease_type, ordinal=1),
        _fixture_lease(lease_type, ordinal=1),
    )
    with pytest.raises(ValueError):
        replace(base, goal=goal, process_leases=duplicate)


def test_015_process_leases_invalidate_on_goal_revision_or_terminal() -> None:
    """R9 / KTD12：Goal revision 变更或 terminal 状态必须清空 process lease。

    state 不变量：每条 lease 必须绑定当前 goal_id/goal_revision/workspace；goal 进入
    VERIFIED_DONE / CANCELLED 时不得残留 lease。这让 correction / 完成自然失效旧权限。
    """

    lease_type = getattr(contracts, "ProcessAuthorityLeaseV1", None)
    if lease_type is None:
        pytest.fail("015 requires ProcessAuthorityLeaseV1 to test invalidation")
    base = ConversationState.new("conversation-invalidation")
    lease = _fixture_lease(lease_type, ordinal=1, goal_revision=1)
    # lease 绑定当前 revision：合法。
    ready = _fixture_goal(revision=1, status=GoalStatus.GOAL_READY)
    replace(base, goal=ready, process_leases=(lease,))
    # lease 绑定 stale revision：state 不允许。
    revised = _fixture_goal(revision=2, status=GoalStatus.GOAL_READY)
    with pytest.raises(ValueError):
        replace(base, goal=revised, process_leases=(lease,))
    # goal terminal 却残留 lease：state 不允许。
    terminal = _fixture_goal(revision=1, status=GoalStatus.VERIFIED_DONE)
    with pytest.raises(ValueError):
        replace(base, goal=terminal, process_leases=(lease,))


def _fixture_goal(*, revision: int, status: GoalStatus) -> GoalFrame:
    return GoalFrame(
        goal_id="goal-capacity",
        revision=revision,
        created_from_fact_ids=("fact-user",),
        workspace_identity_digest="workspace-capacity",
        user_outcome="bounded process authority",
        beneficiary="user",
        targets=("artifact.txt",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion("criterion-capacity", "command contract satisfied"),
        ),
        admitted_criteria=(),
        authority_snapshot="fixed-composition",
        status=status,
        created_at="2026-08-09T00:00:00Z",
        updated_at="2026-08-09T00:00:00Z",
    )


def _fixture_lease(lease_type, *, ordinal: int, goal_revision: int = 1):
    return lease_type.create(
        lease_id=f"lease-{ordinal}",
        candidate_digest="c" * 64,
        goal_id="goal-capacity",
        goal_revision=goal_revision,
        workspace_identity_digest="workspace-capacity",
        command_fingerprint="f" * 64,
        readable_command="/usr/bin/true --capacity-check",
        executable_digest="e" * 64,
        argv_digest="a" * 64,
        cwd_digest="w" * 64,
        resource_profile="standard",
        environment_policy_digest="p" * 64,
        execution_authority=contracts.ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        approved_request_identity="request-1",
        issued_at="2026-08-09T00:00:00Z",
        expires_at="2026-08-09T01:00:00Z",
        max_uses=8,
        uses_consumed=0,
    )
