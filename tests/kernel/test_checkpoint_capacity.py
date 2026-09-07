"""015 U2：ConversationState 对 process authority lease 的有界容量与失效不变量。

lease 由 conversation state 拥有（KTD2/KTD12），容量有界；Goal revision 变更或进入
terminal 状态必须清空 lease。下列测试在 U2 product code 落地后验证这些不变量。

后半部分是 checkpoint usage/capacity 合同：CheckpointUsage 只读度量、
CheckpointStore.usage 的 default/custom/stale/determinism 语义。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path

import pytest

import agent.runtime.contracts as contracts
from agent.runtime.checkpoint import (
    DEFAULT_MAX_STATE_BYTES,
    CheckpointConflictError,
    InMemoryCheckpointStore,
    LocalCheckpointStore,
    encode_conversation_state,
)
from agent.runtime.contracts import (
    ConversationState,
    GoalFrame,
    GoalStatus,
    ProposedCriterion,
    SubmitMessage,
)
from agent.runtime.ports import CheckpointStore, CheckpointUsage
from agent.runtime.state import accept_action


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


# --- checkpoint usage/capacity 合同 -----------------------------------------


def _usage_fixture_state(conversation_id: str = "conversation-usage") -> ConversationState:
    return ConversationState.new(conversation_id)


def _accepted_state(state: ConversationState) -> ConversationState:
    return accept_action(
        state,
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-usage",
            message="advance revision for usage contract",
        ),
    ).state


def test_checkpoint_usage_type_enforces_strict_positive_invariants() -> None:
    usage = CheckpointUsage(active_bytes=10, soft_threshold_bytes=8, hard_cap_bytes=10)
    assert (usage.active_bytes, usage.soft_threshold_bytes, usage.hard_cap_bytes) == (
        10,
        8,
        10,
    )
    # frozen：不可变。
    with pytest.raises(FrozenInstanceError):
        usage.active_bytes = 11
    # slots：无实例 dict。
    assert not hasattr(usage, "__dict__")
    # 严格正整数。
    for kwargs in (
        {"active_bytes": 0, "soft_threshold_bytes": 8, "hard_cap_bytes": 10},
        {"active_bytes": 10, "soft_threshold_bytes": 0, "hard_cap_bytes": 10},
        {"active_bytes": 10, "soft_threshold_bytes": 8, "hard_cap_bytes": 0},
        {"active_bytes": -1, "soft_threshold_bytes": 8, "hard_cap_bytes": 10},
    ):
        with pytest.raises(ValueError):
            CheckpointUsage(**kwargs)
    # active <= hard 且 soft <= hard。
    with pytest.raises(ValueError):
        CheckpointUsage(active_bytes=11, soft_threshold_bytes=8, hard_cap_bytes=10)
    with pytest.raises(ValueError):
        CheckpointUsage(active_bytes=10, soft_threshold_bytes=11, hard_cap_bytes=10)
    # soft 下限 1 在极小 cap 下仍然合法。
    assert CheckpointUsage(active_bytes=1, soft_threshold_bytes=1, hard_cap_bytes=1)


def test_checkpoint_usage_exposed_by_protocol_and_both_stores(tmp_path: Path) -> None:
    state = _usage_fixture_state()
    stores = (
        InMemoryCheckpointStore(state),
        LocalCheckpointStore.initialize(tmp_path / "state" / "conversation.json", state),
    )
    for store in stores:
        assert isinstance(store, CheckpointStore), type(store).__name__
        snapshot = store.load()
        usage = store.usage(snapshot)
        assert isinstance(usage, CheckpointUsage)


def test_checkpoint_usage_default_capacity_is_eight_mib(tmp_path: Path) -> None:
    assert DEFAULT_MAX_STATE_BYTES == 8 * 1024 * 1024
    state = _usage_fixture_state()
    stores = (
        InMemoryCheckpointStore(state),
        LocalCheckpointStore.initialize(tmp_path / "state" / "conversation.json", state),
    )
    for store in stores:
        usage = store.usage(store.load())
        assert usage.hard_cap_bytes == DEFAULT_MAX_STATE_BYTES
        # 默认 soft 恰为 6 MiB（hard 的 3/4）。
        assert usage.soft_threshold_bytes == 6 * 1024 * 1024
        assert usage.active_bytes == len(encode_conversation_state(state))
        assert 0 < usage.active_bytes <= usage.hard_cap_bytes
        assert usage.soft_threshold_bytes <= usage.hard_cap_bytes


def test_checkpoint_usage_custom_cap_scales_soft_threshold(tmp_path: Path) -> None:
    state = _usage_fixture_state()
    path = tmp_path / "state" / "conversation.json"
    LocalCheckpointStore.initialize(path, state)
    for max_state_bytes, expected_soft in ((1_000, 750), (800, 600)):
        memory_store = InMemoryCheckpointStore(state, max_state_bytes=max_state_bytes)
        local_store = LocalCheckpointStore(path, max_state_bytes=max_state_bytes)
        for store in (memory_store, local_store):
            usage = store.usage(store.load())
            assert usage.hard_cap_bytes == max_state_bytes
            assert usage.soft_threshold_bytes == expected_soft
            assert usage.active_bytes == len(encode_conversation_state(state))


def test_checkpoint_usage_fails_closed_on_stale_snapshot_local(tmp_path: Path) -> None:
    state = _usage_fixture_state()
    store = LocalCheckpointStore.initialize(tmp_path / "state" / "conversation.json", state)
    snapshot = store.load()
    lease = store.try_acquire(state.conversation_id)
    assert lease is not None
    saved = store.compare_and_swap(snapshot, _accepted_state(snapshot.state))

    with pytest.raises(CheckpointConflictError) as excinfo:
        store.usage(snapshot)
    assert excinfo.value.current is not None
    assert excinfo.value.current.state.revision == saved.state.revision
    lease.release()


def test_checkpoint_usage_fails_closed_on_stale_snapshot_memory() -> None:
    state = _usage_fixture_state()
    store = InMemoryCheckpointStore(state)
    snapshot = store.load()
    lease = store.try_acquire(state.conversation_id)
    assert lease is not None
    saved = store.compare_and_swap(snapshot, _accepted_state(snapshot.state))

    with pytest.raises(CheckpointConflictError):
        store.usage(snapshot)
    assert saved.state.revision > snapshot.state.revision
    lease.release()


def test_checkpoint_usage_is_deterministic_and_mutation_free(tmp_path: Path) -> None:
    state = _usage_fixture_state()
    memory_store = InMemoryCheckpointStore(state)
    path = tmp_path / "state" / "conversation.json"
    local_store = LocalCheckpointStore.initialize(path, state)
    for store in (memory_store, local_store):
        snapshot = store.load()
        assert store.usage(snapshot) == store.usage(snapshot)
        # 只读零 mutation：token/revision 不因 usage 改变。
        assert store.load() == snapshot

    # local 铁证：usage 未触碰 checkpoint 字节，旧 snapshot 仍可 CAS。
    snapshot = local_store.load()
    assert memory_store.usage(memory_store.load()).active_bytes == len(
        encode_conversation_state(state)
    )
    lease = local_store.try_acquire(state.conversation_id)
    assert lease is not None
    saved = local_store.compare_and_swap(snapshot, _accepted_state(snapshot.state))
    assert saved.state.revision == snapshot.state.revision + 1
    lease.release()
