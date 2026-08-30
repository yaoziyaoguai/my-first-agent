"""F1（P1 review finding 2026-08-16）：stale ApprovalGrant 不得绕过 durable lease。

production 路径实测（Codex 2026-08-16）：approve → revoke/expiry/clock rollback 后，
matching grant 仍把 prepare 变成 ``ExecutionIntent``（process_lease=None）→ invoke
真实 spawn → receipt 落 fallback pseudo lease（use_ordinal=0）。LOCAL_SAME_UID_PROCESS
的 authority 只能来自 exact active durable lease：prepare / invoke / mark_executing /
mint receipt 四层都必须无 exact active lease 即 fail closed（零 spawn、重新 approval）。
"""

from __future__ import annotations

import os
import stat
from dataclasses import replace

import pytest

from agent.process.contracts import ProcessDraftOutcome, ProcessExecutionDraftV1
from agent.process.tools import build_local_process_registration, local_process_tool_spec
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    ApprovalRequired,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    ExecutionAuthorityClass,
    ExecutionIntent,
    FactKind,
    GoalFrame,
    GoalStatus,
    InvocationOrigin,
    ProposedCriterion,
    ResolveApproval,
    RevokeProcessAuthority,
    ToolCall,
    ToolPrepareContext,
    ToolResult,
)
from agent.runtime.state import _apply_action, mark_executing, pause_for_approval
from agent.runtime.tools import IntentConflictError, KernelToolRuntime, RegisteredTool

CONVERSATION = "conversation-f1"
GOAL_ID = "goal-f1"
WORKSPACE_DIGEST = "workspace-f1"
T0 = "2026-08-16T00:00:00Z"


def _goal() -> GoalFrame:
    return GoalFrame(
        goal_id=GOAL_ID,
        revision=1,
        created_from_fact_ids=("fact-user",),
        workspace_identity_digest=WORKSPACE_DIGEST,
        user_outcome="governed local action",
        beneficiary="user",
        targets=("artifact.txt",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(ProposedCriterion("criterion-f1", "command contract"),),
        admitted_criteria=(),
        authority_snapshot="fixed-composition",
        status=GoalStatus.GOAL_READY,
        created_at=T0,
        updated_at=T0,
    )


def _make_marker_executable(workspace, marker) -> str:
    """真实 fixture：spawn 可观察（写入 marker 文件）——零 spawn 断言的证据。"""

    path = workspace / "marker-exe"
    path.write_bytes(
        f"#!/bin/sh\nprintf x >> {marker}\nprintf done\n".encode()
    )
    os.chmod(path, stat.S_IRWXU)
    return str(path.relative_to(workspace))


def _runtime(workspace, clock, marker) -> KernelToolRuntime:
    return KernelToolRuntime(
        (
            build_local_process_registration(
                workspace=workspace, captured_path="/usr/bin:/bin", clock=clock
            ),
        ),
        clock=clock,
    )


def _context(runtime, *, process_leases=()) -> ToolPrepareContext:
    return ToolPrepareContext(
        conversation_id=CONVERSATION,
        run_id="run-f1",
        state_revision=1,
        goal_id=GOAL_ID,
        goal_revision=1,
        workspace_identity_digest=WORKSPACE_DIGEST,
        process_leases=process_leases,
    )


def _runnable_state(call: ToolCall) -> ConversationState:
    return replace(
        ConversationState.new(CONVERSATION),
        goal=_goal(),
        facts=(
            ConversationFact(
                fact_id="fact-user",
                kind=FactKind.USER_MESSAGE,
                content={"text": "governed local action"},
            ),
        ),
        active_run=ActiveRun(
            run_id="run-f1",
            status=ActiveRunStatus.RUNNABLE,
            phase=ContinuationPhase.TOOL,
            batch_cursor=0,
            tool_calls=(call,),
        ),
    )


def _approve(state, request) -> ConversationState:
    paused = pause_for_approval(state, request)
    return _apply_action(
        paused,
        ResolveApproval(
            conversation_id=CONVERSATION,
            action_seq=1,
            expected_revision=paused.revision,
            request_id=request.request_id,
            binding_digest=request.binding_digest,
            approved=True,
            approved_at=T0,
        ),
    )


@pytest.fixture()
def journey(tmp_path):
    """approve 一个真实 process command，返回 (runtime, call, approved_state, marker, clock)。"""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    marker = str(tmp_path / "spawn-marker")
    clock = {"now": T0}
    runtime = _runtime(workspace, lambda: clock["now"], marker)
    rel = _make_marker_executable(workspace, marker)
    call = ToolCall(
        "call-f1", "local_process",
        {"executable": rel, "argv": [], "cwd": ".", "profile": "standard"},
    )
    state = _runnable_state(call)
    first = runtime.prepare(call, _context(runtime))
    assert isinstance(first, ApprovalRequired)
    approved = _approve(state, first.request)
    # 前提：批准铸出 exact durable lease + durable grant（production resume 携带物）。
    assert len(approved.process_leases) == 1
    assert approved.active_run.approval_grant is not None
    return runtime, call, approved, marker, clock


def test_015_revoked_lease_stale_grant_fails_closed_zero_spawn(journey, tmp_path) -> None:
    """revoke 后同一 call-id + matching grant：不得 ExecutionIntent、不得 spawn、重新 approval。"""

    runtime, call, approved, marker, _clock = journey
    revoked = _apply_action(
        approved,
        RevokeProcessAuthority(
            conversation_id=CONVERSATION,
            action_seq=2,
            expected_revision=approved.revision,
            lease_id=None,
        ),
    )
    # bypass 表面（Red 前提）：lease 已清空，但 durable grant 仍随 resume 携带。
    assert revoked.process_leases == ()
    assert revoked.active_run.approval_grant is not None

    prepared = runtime.prepare(
        call,
        _context(runtime, process_leases=revoked.process_leases),
        approval=revoked.active_run.approval_grant,
    )
    assert isinstance(prepared, ApprovalRequired), (
        "stale grant must not mint an executable process intent after revoke"
    )
    assert prepared.request.process_authority_candidate is not None, (
        "re-approval must present a fresh candidate"
    )
    assert not os.path.exists(marker), "no spawn may happen without an active lease"


def test_015_expired_lease_stale_grant_fails_closed_zero_spawn(journey) -> None:
    """lease 到期后（leases 仍在 state）matching grant 同样不得执行。"""

    runtime, call, approved, marker, clock = journey
    clock["now"] = "2026-08-16T01:00:01Z"  # approved_at + 60min + 1s
    prepared = runtime.prepare(
        call,
        _context(runtime, process_leases=approved.process_leases),
        approval=approved.active_run.approval_grant,
    )
    assert isinstance(prepared, ApprovalRequired)
    assert not os.path.exists(marker)


def test_015_clock_rollback_stale_grant_fails_closed_zero_spawn(journey) -> None:
    """clock rollback（now < issued_at）后 matching grant 同样不得执行。"""

    runtime, call, approved, marker, clock = journey
    clock["now"] = "2026-08-15T23:00:00Z"  # 早于 approved_at/issued_at
    prepared = runtime.prepare(
        call,
        _context(runtime, process_leases=approved.process_leases),
        approval=approved.active_run.approval_grant,
    )
    assert isinstance(prepared, ApprovalRequired)
    assert not os.path.exists(marker)


def test_015_invoke_rejects_process_intent_without_exact_lease(tmp_path) -> None:
    """invoke 层（defense in depth）：authority=LOCAL_SAME_UID_PROCESS 且无 lease 的
    self-consistent intent 必须在 callable 执行前 fail closed（零 spawn）。"""

    spawned: list[object] = []

    def spy_executor(intent):  # noqa: ANN001
        spawned.append(intent)
        return ProcessExecutionDraftV1(
            outcome=ProcessDraftOutcome.EXITED,
            pid=1,
            process_group_id=1,
            exit_code=0,
            signal=None,
            started_at_monotonic=0.0,
            ended_at_monotonic=0.0,
            duration_seconds=0.0,
            stdout_bytes=0,
            stderr_bytes=0,
            stdout_digest="d" * 64,
            stderr_digest="d" * 64,
            stdout_projection="",
            stderr_projection="",
            stdout_truncated=False,
            stderr_truncated=False,
            group_reaped=True,
            term_sent=False,
            kill_sent=False,
        )

    from agent.runtime.tools import _digest_json

    runtime = KernelToolRuntime(
        (RegisteredTool(spec=local_process_tool_spec(), func=spy_executor),)
    )
    arguments = {"executable": "fixture-exe", "argv": [], "cwd": "."}
    base = ExecutionIntent(
        tool_call_id="call-f1",
        tool_name="local_process",
        tool_identity=local_process_tool_spec().identity_digest,
        arguments=arguments,
        arguments_digest=_digest_json(arguments),
        intent_digest="",
        idempotency_key=f"{CONVERSATION}:run-f1:call-f1",
        policy_identity="kernel-default-tool-policy-v1",
        conversation_id=CONVERSATION,
        run_id="run-f1",
        side_effect=local_process_tool_spec().side_effect,
        invocation_origin=InvocationOrigin.MODEL,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        process_lease=None,
    )
    # 模拟旧 buggy prepare 铸出的形状：digest 与「无 lease」自洽（process_lease_digest=None）。
    intent = replace(base, intent_digest=runtime._intent_digest(base))
    with pytest.raises(IntentConflictError):
        runtime.invoke(intent)
    assert spawned == [], "executor must not run for a lease-less process intent"


def test_015_mint_receipt_rejects_lease_less_process_intent(tmp_path) -> None:
    """mint-receipt 层：pseudo lease receipt（fallback lease_id/use_ordinal=0）必须删除。"""

    runtime = KernelToolRuntime(
        (RegisteredTool(spec=local_process_tool_spec(), func=lambda _i: None),)
    )
    spec = local_process_tool_spec()
    base = ExecutionIntent(
        tool_call_id="call-f1",
        tool_name="local_process",
        tool_identity=spec.identity_digest,
        arguments={"executable": "fixture-exe", "argv": [], "cwd": "."},
        arguments_digest="a" * 64,
        intent_digest="i" * 64,
        idempotency_key=f"{CONVERSATION}:run-f1:call-f1",
        policy_identity="kernel-default-tool-policy-v1",
        conversation_id=CONVERSATION,
        run_id="run-f1",
        side_effect=spec.side_effect,
        invocation_origin=InvocationOrigin.MODEL,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        goal_id=GOAL_ID,
        goal_revision=1,
        workspace_identity_digest=WORKSPACE_DIGEST,
        safety_binding={
            "command_fingerprint": "f" * 64,
            "executable_digest": "e" * 64,
            "argv_digest": "a" * 64,
            "cwd_digest": "w" * 64,
            "resource_profile": "standard",
            "environment_policy_digest": "p" * 64,
        },
        process_lease=None,
    )
    draft = ProcessExecutionDraftV1(
        outcome=ProcessDraftOutcome.EXITED,
        pid=1,
        process_group_id=1,
        exit_code=0,
        signal=None,
        started_at_monotonic=0.0,
        ended_at_monotonic=0.0,
        duration_seconds=0.0,
        stdout_bytes=0,
        stderr_bytes=0,
        stdout_digest="d" * 64,
        stderr_digest="d" * 64,
        stdout_projection="",
        stderr_projection="",
        stdout_truncated=False,
        stderr_truncated=False,
        group_reaped=True,
        term_sent=False,
        kill_sent=False,
    )
    with pytest.raises(IntentConflictError):
        runtime._mint_process_receipt(base, spec, draft)


def test_015_mark_executing_requires_lease_for_process_authority(journey) -> None:
    """mark_executing 层：LOCAL_SAME_UID_PROCESS 的 EXECUTING checkpoint 必须消费
    exact durable lease（process_lease_id 缺失即 fail closed），不得静默通过。"""

    runtime, call, _approved, _marker, _clock = journey
    state = _runnable_state(call)
    with pytest.raises(ValueError):
        mark_executing(
            state,
            tool_call_id=call.tool_call_id,
            intent_digest="i" * 64,
            idempotency_key=f"{CONVERSATION}:run-f1:{call.tool_call_id}",
            side_effect=runtime._tools["local_process"].spec.side_effect,
            egress=runtime._tools["local_process"].spec.egress,
            operation="local_process",
            request_identity=f"{CONVERSATION}:run-f1:{call.tool_call_id}",
            execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
            process_lease_id=None,
        )


def test_015_live_lease_resume_still_executes_and_spawns_once(journey) -> None:
    """fail-closed 收紧不得破坏合法路径：active lease + grant → 执行一次、marker 恰好一次。"""

    runtime, call, approved, marker, _clock = journey
    intent = runtime.prepare(
        call,
        _context(runtime, process_leases=approved.process_leases),
        approval=approved.active_run.approval_grant,
    )
    assert isinstance(intent, ExecutionIntent)
    assert intent.process_lease is not None
    result = runtime.invoke(intent)
    assert isinstance(result, ToolResult)
    assert result.is_error is False
    assert result.metadata.get("lease_id") == approved.process_leases[0].lease_id
    assert result.metadata.get("use_ordinal") == 1
    assert os.path.exists(marker)
    with open(marker, encoding="utf-8") as handle:
        assert handle.read() == "x"
