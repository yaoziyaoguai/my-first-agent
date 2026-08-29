"""015 U3：approval reducer 铸造 process authority lease、typed revoke 与失效不变量。

在 reducer 层直接测试（构造带 ``process_authority_candidate`` 的 pending ApprovalRequest
+ Goal + ActiveRun，调用 ``_apply_action`` 或公开 transition），不依赖 local_process
tool（U6）。每条 Red 映射 R7-R11 / R22 / KTD3-KTD4；RevokeProcessAuthority 缺失时用
``pytest.fail`` 守卫。
"""

from __future__ import annotations

from typing import get_args

import pytest

import agent.runtime.contracts as contracts
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    ApprovalRequest,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    ExecutionAuthorityClass,
    FactKind,
    GoalFrame,
    GoalStatus,
    ProposedCriterion,
    ResolveApproval,
    ToolCall,
)
from agent.runtime.state import (
    _apply_action,
    apply_goal_delta,
    cancel_goal,
    mark_executing,
    pause_goal,
)

CONVERSATION = "conversation-u3"
GOAL_ID = "goal-u3"
WORKSPACE = "workspace-u3"


def _goal(*, revision: int = 1, status: GoalStatus = GoalStatus.GOAL_READY) -> GoalFrame:
    return GoalFrame(
        goal_id=GOAL_ID,
        revision=revision,
        created_from_fact_ids=("fact-user",),
        workspace_identity_digest=WORKSPACE,
        user_outcome="governed local action",
        beneficiary="user",
        targets=("artifact.txt",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion("criterion-u3", "command contract satisfied"),
        ),
        admitted_criteria=(),
        authority_snapshot="fixed-composition",
        status=status,
        created_at="2026-08-09T00:00:00Z",
        updated_at="2026-08-09T00:00:00Z",
    )


def _candidate():
    return contracts.ProcessAuthorityCandidateV1.create(
        candidate_id="candidate-u3",
        goal_id=GOAL_ID,
        goal_revision=1,
        workspace_identity_digest=WORKSPACE,
        command_fingerprint="f" * 64,
        readable_command="/usr/bin/true --flag",
        executable_digest="e" * 64,
        argv_digest="a" * 64,
        cwd_digest="w" * 64,
        resource_profile="standard",
        environment_policy_digest="p" * 64,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        trust_notice_digest="t" * 64,
        issued_at="2026-08-09T00:00:00Z",
        max_uses=8,
        expiry_minutes=60,
    )


def _lease(lease_type, *, ordinal: int, goal_revision: int = 1):
    return lease_type.create(
        lease_id=f"lease-u3-{ordinal}",
        candidate_digest=_candidate().candidate_digest,
        goal_id=GOAL_ID,
        goal_revision=goal_revision,
        workspace_identity_digest=WORKSPACE,
        command_fingerprint="f" * 64,
        readable_command="/usr/bin/true --flag",
        executable_digest="e" * 64,
        argv_digest="a" * 64,
        cwd_digest="w" * 64,
        resource_profile="standard",
        environment_policy_digest="p" * 64,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        approved_request_identity="req-u3",
        issued_at="2026-08-09T00:00:00Z",
        expires_at="2026-08-09T01:00:00Z",
        max_uses=8,
        uses_consumed=0,
    )


def _awaiting_approval(*, with_candidate: bool = True) -> ConversationState:
    candidate = _candidate() if with_candidate else None
    pending = ApprovalRequest(
        request_id="req-u3",
        run_id="run-u3",
        tool_call_id="call-u3",
        binding_digest="b" * 64,
        preview="exact command + same-UID notice",
        tool_name="local_process",
        process_authority_candidate=candidate,
    )
    active = ActiveRun(
        run_id="run-u3",
        status=ActiveRunStatus.AWAITING_APPROVAL,
        phase=ContinuationPhase.TOOL,
        batch_cursor=0,
        tool_calls=(ToolCall("call-u3", "local_process", {}),),
        pending_request=pending,
    )
    base = ConversationState.new(CONVERSATION)
    from dataclasses import replace

    return replace(
        base,
        goal=_goal(),
        facts=(
            ConversationFact(
                fact_id="fact-user",
                kind=FactKind.USER_MESSAGE,
                content={"text": "governed local action"},
            ),
        ),
        active_run=active,
    )


def _resolve(*, approved: bool) -> ResolveApproval:
    return ResolveApproval(
        conversation_id=CONVERSATION,
        action_seq=1,
        expected_revision=0,
        request_id="req-u3",
        binding_digest="b" * 64,
        approved=approved,
        approved_at="2026-08-09T00:30:00Z",
    )


def test_015_approve_mints_process_authority_lease_bound_to_candidate() -> None:
    """R8 / KTD3 / KTD4：ResolveApproval(approved=True) 对 process candidate 铸造
    绑定 candidate identity 与 approved request 的 durable lease。"""

    state = _awaiting_approval(with_candidate=True)
    result = _apply_action(state, _resolve(approved=True))
    leases = result.process_leases
    assert len(leases) == 1
    lease = leases[0]
    candidate = state.active_run.pending_request.process_authority_candidate
    assert lease.goal_id == candidate.goal_id
    assert lease.goal_revision == candidate.goal_revision
    assert lease.workspace_identity_digest == candidate.workspace_identity_digest
    assert lease.command_fingerprint == candidate.command_fingerprint
    assert lease.candidate_digest == candidate.candidate_digest
    assert lease.approved_request_identity == "req-u3"
    assert lease.max_uses == 8
    assert lease.uses_consumed == 0
    assert lease.expires_at  # 60-minute expiry derived from candidate


def test_015_process_approval_without_approval_time_fails_closed() -> None:
    """真实 adapter 不得漏掉批准时刻后静默退回 candidate/request 时刻。"""

    from dataclasses import replace as _replace

    state = _awaiting_approval(with_candidate=True)
    action = _replace(_resolve(approved=True), approved_at=None)
    with pytest.raises(ValueError, match="approved_at"):
        _apply_action(state, action)


def test_015_revoke_process_authority_is_part_of_public_action_union() -> None:
    """所有 adapter 产生的 typed action 都必须属于公共 ``Action`` 合同。"""

    assert contracts.RevokeProcessAuthority in get_args(contracts.Action)


def test_015_reject_does_not_mint_process_authority_lease() -> None:
    """R8 / F4：拒绝不铸造 lease；后续 exact command 需重新请求批准。"""

    state = _awaiting_approval(with_candidate=True)
    result = _apply_action(state, _resolve(approved=False))
    assert result.process_leases == ()


def test_015_non_process_approval_does_not_mint_lease() -> None:
    """R2 / KTD1：普通工具 approval（无 process candidate）不铸造 process lease。"""

    state = _awaiting_approval(with_candidate=False)
    result = _apply_action(state, _resolve(approved=True))
    assert result.process_leases == ()


def test_015_revoke_process_authority_removes_single_and_all_leases() -> None:
    """R11 / KTD4：typed RevokeProcessAuthority 移除指定 lease 或全部 lease。"""

    revoke_type = getattr(contracts, "RevokeProcessAuthority", None)
    if revoke_type is None:
        pytest.fail("015 requires RevokeProcessAuthority typed action")
    lease_type = contracts.ProcessAuthorityLeaseV1
    from dataclasses import replace

    lease_a = _lease(lease_type, ordinal=1)
    lease_b = _lease(lease_type, ordinal=2)
    base = replace(
        ConversationState.new(CONVERSATION),
        goal=_goal(),
        process_leases=(lease_a, lease_b),
        revision=2,
    )
    # 撤销单条：按 lease_id 选择。
    revoke_one = revoke_type(
        conversation_id=CONVERSATION,
        action_seq=3,
        expected_revision=2,
        lease_id=lease_a.lease_id,
    )
    after_one = _apply_action(base, revoke_one)
    assert [lease.lease_id for lease in after_one.process_leases] == [lease_b.lease_id]
    # 撤销全部。
    revoke_all = revoke_type(
        conversation_id=CONVERSATION,
        action_seq=4,
        expected_revision=3,
        lease_id=None,
    )
    base_with_revision = replace(after_one, revision=3)
    after_all = _apply_action(base_with_revision, revoke_all)
    assert after_all.process_leases == ()


def test_015_goal_delta_clears_process_leases() -> None:
    """R9 / KTD12：Goal revision 变更（correction/delta）必须清空 process lease。"""

    lease_type = contracts.ProcessAuthorityLeaseV1
    from dataclasses import replace

    state = replace(
        ConversationState.new(CONVERSATION),
        goal=_goal(revision=1),
        process_leases=(_lease(lease_type, ordinal=1),),
    )
    delta = contracts.GoalDelta(
        goal_id=GOAL_ID,
        expected_revision=1,
        reason="natural-language correction",
        updates={"user_outcome": "revised outcome"},
        updated_at="2026-08-09T00:00:00Z",
    )
    result = apply_goal_delta(state, delta)
    assert result.process_leases == ()
    assert result.goal.revision == 2


def test_015_pause_and_cancel_clear_process_leases() -> None:
    """R9 / KTD12：pause 与 cancel 都使 process lease 失效（R9 明列）。"""

    lease_type = contracts.ProcessAuthorityLeaseV1
    from dataclasses import replace

    paused = replace(
        ConversationState.new(CONVERSATION),
        goal=_goal(revision=1, status=GoalStatus.GOAL_READY),
        process_leases=(_lease(lease_type, ordinal=1),),
    )
    after_pause = pause_goal(paused, goal_id=GOAL_ID, expected_revision=1)
    assert after_pause.process_leases == ()

    cancelled = replace(
        ConversationState.new(CONVERSATION),
        goal=_goal(revision=1, status=GoalStatus.GOAL_READY),
        process_leases=(_lease(lease_type, ordinal=2),),
    )
    after_cancel = cancel_goal(cancelled, goal_id=GOAL_ID, expected_revision=1)
    assert after_cancel.process_leases == ()


def test_015_mark_executing_consumes_process_lease_use_once() -> None:
    """R9 / KTD12：EXECUTING checkpoint 单调消费 lease use；unknown lease fail closed。"""

    lease_type = getattr(contracts, "ProcessAuthorityLeaseV1", None)
    if lease_type is None:
        pytest.fail("015 requires ProcessAuthorityLeaseV1")
    from dataclasses import replace

    lease = _lease(lease_type, ordinal=1)
    active = ActiveRun(
        run_id="run-u7",
        status=ActiveRunStatus.RUNNABLE,
        phase=ContinuationPhase.TOOL,
        batch_cursor=0,
        tool_calls=(ToolCall("call-u7", "local_process", {}),),
    )
    base = replace(
        ConversationState.new("conversation-u7"),
        goal=_goal(),
        process_leases=(lease,),
        active_run=active,
    )
    executing = mark_executing(
        base,
        tool_call_id="call-u7",
        intent_digest="i" * 64,
        idempotency_key="conversation-u7:run-u7:call-u7",
        side_effect=contracts.SideEffectClass.EXTERNAL,
        egress=contracts.EgressClass.NONE,
        operation="local_process",
        request_identity="conversation-u7:run-u7:call-u7",
        execution_authority=contracts.ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        process_lease_id=lease.lease_id,
    )
    assert executing.process_leases[0].uses_consumed == 1
    assert executing.active_run.executing_intent.execution_authority is (
        contracts.ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS
    )
    # unknown lease id → fail closed（不得 silently 消费不存在的 authority）。
    with pytest.raises(ValueError):
        mark_executing(
            base,
            tool_call_id="call-u7",
            intent_digest="i" * 64,
            idempotency_key="conversation-u7:run-u7:call-u7",
            side_effect=contracts.SideEffectClass.EXTERNAL,
            egress=contracts.EgressClass.NONE,
            operation="local_process",
            request_identity="conversation-u7:run-u7:call-u7",
            execution_authority=contracts.ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
            process_lease_id="process-lease:nonexistent",
        )


def test_015_user_confirmed_artifact_admits_filesystem_criterion() -> None:
    """F4（P2 review finding）：artifact digest 的 authority 是**用户**，非模型。

    ResolveApproval 可携带 confirmed_artifact（path + 64-hex sha256）——批准 process
    command 的同一 typed action 同时确认 artifact 期望，Runtime 铸 FILESYSTEM_DIGEST
    criterion（012-014 criterion admission 语义）。malformed（空 path / 非 hex sha /
    naive？无时间）必须 fail closed，不铸 criterion。
    """

    from dataclasses import replace as _replace

    from agent.runtime.contracts import ConversationFact, EvidenceOracleKind, FactKind

    base = _awaiting_approval(with_candidate=True)
    # criterion admission 需要 goal 的 authoritative user fact 存在于 durable facts。
    user_fact = ConversationFact(
        fact_id="fact-user",
        kind=FactKind.USER_MESSAGE,
        content={"text": "produce the artifact"},
    )
    base = _replace(base, facts=(user_fact,))
    digest = "d" * 64
    action = _replace(
        _resolve(approved=True),
        confirmed_artifact_path="artifact.out",
        confirmed_artifact_sha256=digest,
    )
    result = _apply_action(base, action)
    kinds = [
        (c.oracle_kind, c.predicate)
        for c in result.goal.admitted_criteria
        if c.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
    ]
    assert kinds == [
        (EvidenceOracleKind.FILESYSTEM_DIGEST, {"path": "artifact.out", "sha256": digest})
    ], "user-confirmed artifact must mint exactly one FILESYSTEM_DIGEST criterion"

    # mutation：malformed sha（非 64-hex）必须 fail closed。
    bad = _replace(
        _resolve(approved=True),
        confirmed_artifact_path="artifact.out",
        confirmed_artifact_sha256="not-hex",
    )
    import pytest as _pytest

    with _pytest.raises(ValueError):
        _apply_action(base, bad)


def test_015_lease_expiry_anchored_at_approval_time() -> None:
    """F6（P2 review finding / R9）：lease 在**批准后** 60 分钟过期。

    审批等待不得缩短租约：candidate issued_at=T0，用户 T0+30min 才批准 →
    lease.issued_at/expires_at 锚定批准时刻（T0+30 → T0+90），而非 candidate 的
    T0+60。approved_at naive（无时区）必须 fail closed。
    """

    from dataclasses import asdict
    from dataclasses import replace as _replace

    base = _awaiting_approval(with_candidate=True)
    candidate_values = asdict(
        base.active_run.pending_request.process_authority_candidate
    )
    candidate_values.pop("candidate_digest")
    candidate_values["issued_at"] = "2026-08-15T00:00:00Z"
    candidate_values["expiry_minutes"] = 60
    candidate = contracts.ProcessAuthorityCandidateV1.create(**candidate_values)
    state = _replace(
        base,
        active_run=_replace(
            base.active_run,
            pending_request=_replace(
                base.active_run.pending_request,
                process_authority_candidate=candidate,
            ),
        ),
    )
    approved_late = "2026-08-15T00:30:00Z"
    action = _replace(_resolve(approved=True), approved_at=approved_late)
    result = _apply_action(state, action)
    leases = result.process_leases
    assert leases, "process approval must mint a lease"
    assert leases[0].issued_at == approved_late
    assert leases[0].expires_at == "2026-08-15T01:30:00Z", (
        "expiry must be approval + 60min, not candidate + 60min"
    )

    # mutation：naive approved_at（无时区）必须 fail closed。
    naive = _replace(_resolve(approved=True), approved_at="2026-08-15T00:30:00")
    import pytest as _pytest

    with _pytest.raises(ValueError):
        _apply_action(state, naive)


def test_015_crash_after_executing_does_not_duplicate_spawn_or_lease_use() -> None:
    """R16/R19/AE9：EXECUTING checkpoint 后 crash → restart 不重放 spawn、lease use 单调。

    一旦 active_run 进入 EXECUTING，mark_executing 拒绝再次进入（clean RUNNABLE 要求），
    故 restart 无法 re-spawn；lease use 已在第一次 EXECUTING 单调消费，不会重复计费。
    """

    lease_type = contracts.ProcessAuthorityLeaseV1
    from dataclasses import replace

    lease = _lease(lease_type, ordinal=1)
    active = ActiveRun(
        run_id="run-crash",
        status=ActiveRunStatus.RUNNABLE,
        phase=ContinuationPhase.TOOL,
        batch_cursor=0,
        tool_calls=(ToolCall("call-crash", "local_process", {}),),
    )
    base = replace(
        ConversationState.new("conversation-crash"),
        goal=_goal(),
        process_leases=(lease,),
        active_run=active,
    )
    executing = mark_executing(
        base,
        tool_call_id="call-crash",
        intent_digest="i" * 64,
        idempotency_key="conversation-crash:run-crash:call-crash",
        side_effect=contracts.SideEffectClass.EXTERNAL,
        egress=contracts.EgressClass.NONE,
        operation="local_process",
        request_identity="conversation-crash:run-crash:call-crash",
        execution_authority=contracts.ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        process_lease_id=lease.lease_id,
    )
    assert executing.process_leases[0].uses_consumed == 1
    assert executing.active_run.phase is ContinuationPhase.EXECUTING
    # crash 后 restart 观察到 EXECUTING：再次 mark_executing 被拒（不重放 spawn）。
    with pytest.raises(ValueError):
        mark_executing(
            executing,
            tool_call_id="call-crash",
            intent_digest="i" * 64,
            idempotency_key="conversation-crash:run-crash:call-crash",
            side_effect=contracts.SideEffectClass.EXTERNAL,
            egress=contracts.EgressClass.NONE,
            operation="local_process",
            request_identity="conversation-crash:run-crash:call-crash",
            execution_authority=contracts.ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
            process_lease_id=lease.lease_id,
        )
    # lease use 单调：crash 不恢复 use，仍是 1（不重复计费）。
    assert executing.process_leases[0].uses_consumed == 1
