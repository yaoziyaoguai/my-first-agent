from __future__ import annotations

from dataclasses import replace

from agent.runtime.contracts import (
    ActionDisposition,
    ActiveRunStatus,
    ApprovalRequest,
    CancelRun,
    ContinuationPhase,
    RecordedRunResult,
    RecoveryRequest,
    ResolveApproval,
    Resume,
    RunStatus,
    SubmitMessage,
    ToolCall,
)
from agent.runtime.state import (
    accept_action,
    complete_run,
    finalize_action,
    mark_executing,
    pause_for_approval,
    pause_for_recovery,
    start_tool_batch,
)
from tests.kernel.fakes import conversation_with_active_goal


def _submit(*, seq: int = 1, revision: int = 0, message: str = "hello") -> SubmitMessage:
    return SubmitMessage(
        conversation_id="conversation-1",
        action_seq=seq,
        expected_revision=revision,
        run_id="run-1",
        message=message,
    )


def test_ready_submit_starts_one_runnable_run() -> None:
    transition = accept_action(state=None, action=_submit())

    assert transition.disposition is ActionDisposition.ACCEPTED
    assert transition.state.revision == 1
    assert transition.state.next_action_seq == 2
    assert transition.state.active_run is not None
    assert transition.state.active_run.status is ActiveRunStatus.RUNNABLE
    assert transition.state.active_run.run_id == "run-1"


def test_illegal_action_conflicts_without_mutating_state() -> None:
    first = accept_action(state=None, action=_submit())
    illegal = accept_action(
        state=first.state,
        action=_submit(seq=2, revision=first.state.revision, message="second"),
    )

    assert illegal.disposition is ActionDisposition.CONFLICT
    assert illegal.reason == "illegal_action_for_state"
    assert illegal.state == first.state


def test_approval_must_match_exact_pending_request() -> None:
    started = accept_action(state=None, action=_submit()).state
    started = start_tool_batch(
        started,
        (ToolCall("tool-call-1", "write_file", {}),),
    )
    paused = pause_for_approval(
        started,
        ApprovalRequest(
            request_id="approval-1",
            run_id="run-1",
            tool_call_id="tool-call-1",
            binding_digest="binding-1",
            preview="write file",
        ),
    )
    wrong = ResolveApproval(
        conversation_id="conversation-1",
        action_seq=2,
        expected_revision=paused.revision,
        request_id="approval-1",
        binding_digest="wrong",
        approved=True,
    )

    rejected = accept_action(paused, wrong)

    assert rejected.disposition is ActionDisposition.CONFLICT
    assert rejected.state == paused

    exact = replace(wrong, binding_digest="binding-1")
    accepted = accept_action(paused, exact)
    assert accepted.disposition is ActionDisposition.ACCEPTED
    assert accepted.state.active_run is not None
    assert accepted.state.active_run.status is ActiveRunStatus.RUNNABLE
    assert accepted.state.active_run.pending_request is None


def test_natural_language_correction_replaces_unexecuted_pending_approval() -> None:
    seed = conversation_with_active_goal()
    started = accept_action(
        state=seed,
        action=_submit(
            seq=seed.next_action_seq,
            revision=seed.revision,
            message="write draft.md",
        ),
    ).state
    started = start_tool_batch(
        started,
        (ToolCall("tool-call-1", "write_file", {"path": "draft.md"}),),
    )
    paused = pause_for_approval(
        started,
        ApprovalRequest(
            request_id="approval-1",
            run_id="run-1",
            tool_call_id="tool-call-1",
            binding_digest="binding-1",
            preview="write draft.md",
        ),
    )
    correction = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=started.next_action_seq,
        expected_revision=paused.revision,
        run_id="run-correction",
        message="write final.md instead",
    )

    transition = accept_action(paused, correction)

    assert transition.disposition is ActionDisposition.ACCEPTED
    assert transition.state.active_run is not None
    assert transition.state.active_run.run_id == "run-correction"
    assert transition.state.active_run.pending_request is None
    assert transition.state.facts[-1].content == {
        "text": "write final.md instead",
        "control": "goal_correction",
    }


def test_replay_precedes_revision_and_evicted_sequences_expire() -> None:
    first_action = _submit()
    first = accept_action(None, first_action, max_replay_records=1)
    first_done = finalize_action(
        complete_run(first.state, message="done"),
        action_seq=1,
        result=RecordedRunResult(status=RunStatus.COMPLETED, run_id="run-1", message="done"),
    )

    replay = accept_action(first_done, first_action, max_replay_records=1)
    assert replay.disposition is ActionDisposition.REPLAYED
    assert replay.recorded_result is not None
    assert replay.recorded_result.message == "done"

    changed = accept_action(first_done, replace(first_action, message="different"))
    assert changed.disposition is ActionDisposition.CONFLICT
    assert changed.reason == "action_digest_mismatch"

    second_action = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=2,
        expected_revision=first_done.revision,
        run_id="run-2",
        message="next",
    )
    second = accept_action(first_done, second_action, max_replay_records=1)
    second_done = finalize_action(
        complete_run(second.state, message="next done"),
        action_seq=2,
        result=RecordedRunResult(status=RunStatus.COMPLETED, run_id="run-2"),
        max_replay_records=1,
    )

    expired = accept_action(second_done, first_action, max_replay_records=1)
    assert expired.disposition is ActionDisposition.CONFLICT
    assert expired.reason == "action_sequence_expired"
    assert second_done.replay_floor == 2

    gap = Resume(
        conversation_id="conversation-1",
        action_seq=4,
        expected_revision=second_done.revision,
    )
    assert accept_action(second_done, gap).reason == "action_sequence_gap"


def test_replay_capacity_never_evicts_past_an_unfinished_action() -> None:
    first = accept_action(None, _submit(), max_replay_records=2).state
    second_action = Resume(
        conversation_id="conversation-1",
        action_seq=2,
        expected_revision=first.revision,
    )
    second = accept_action(first, second_action, max_replay_records=2).state
    second = finalize_action(
        second,
        action_seq=2,
        result=RecordedRunResult(status=RunStatus.LIMIT_REACHED, run_id="run-1"),
        max_replay_records=2,
    )
    third = Resume(
        conversation_id="conversation-1",
        action_seq=3,
        expected_revision=second.revision,
    )

    blocked = accept_action(second, third, max_replay_records=2)

    assert blocked.disposition is ActionDisposition.CONFLICT
    assert blocked.reason == "replay_capacity_exhausted"
    assert blocked.state == second


def test_completion_returns_conversation_to_ready_and_cancel_is_state_scoped() -> None:
    started = accept_action(None, _submit()).state
    ready = complete_run(started, message="done")

    assert ready.active_run is None
    second = accept_action(
        ready,
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=2,
            expected_revision=ready.revision,
            run_id="run-2",
            message="again",
        ),
    )
    assert second.disposition is ActionDisposition.ACCEPTED

    cancel = CancelRun(
        conversation_id="conversation-1",
        action_seq=3,
        expected_revision=second.state.revision,
    )
    stale_owned = replace(
        second.state,
        active_run=replace(second.state.active_run, owner_invocation_id="dead-invocation"),
    )
    cancelled = accept_action(stale_owned, cancel)
    assert cancelled.disposition is ActionDisposition.ACCEPTED
    assert cancelled.state.active_run is None


# ---- 002 U1: durable EXECUTING / AWAITING_RECOVERY action legality gate ----
# 未知 effect 必须由人类分类，不能被 CancelRun/Resume 绕过。
# 见 docs/architecture/CAPABILITY_REINTRODUCTION_ROADMAP.md 与
# docs/plans/2026-07-18-002-feat-governed-skill-source-plan.md R5。


def _executing_run_state():
    started = accept_action(state=None, action=_submit()).state
    batched = start_tool_batch(
        started,
        (ToolCall("tool-call-1", "write_file", {}),),
    )
    return mark_executing(
        batched,
        tool_call_id="tool-call-1",
        intent_digest="intent-1",
        idempotency_key="conversation-1:run-1:tool-call-1",
    )


def _awaiting_recovery_state():
    return pause_for_recovery(
        _executing_run_state(),
        RecoveryRequest(
            request_id="recovery-1",
            run_id="run-1",
            tool_call_id="tool-call-1",
            binding_digest="intent-1",
            summary="tool outcome is unknown",
        ),
    )


def test_cancel_run_on_executing_continuation_is_unchanged_conflict() -> None:
    executing = _executing_run_state()
    cancel = CancelRun(
        conversation_id="conversation-1",
        action_seq=2,
        expected_revision=executing.revision,
    )

    transition = accept_action(executing, cancel)

    assert transition.disposition is ActionDisposition.CONFLICT
    assert transition.state == executing
    assert transition.state.active_run is not None
    assert transition.state.active_run.phase is ContinuationPhase.EXECUTING
    assert transition.state.active_run.executing_intent is not None


def test_cancel_run_on_awaiting_recovery_is_unchanged_conflict() -> None:
    recovering = _awaiting_recovery_state()
    cancel = CancelRun(
        conversation_id="conversation-1",
        action_seq=2,
        expected_revision=recovering.revision,
    )

    transition = accept_action(recovering, cancel)

    assert transition.disposition is ActionDisposition.CONFLICT
    assert transition.state == recovering
    assert transition.state.active_run is not None
    assert transition.state.active_run.status is ActiveRunStatus.AWAITING_RECOVERY


def test_resume_on_awaiting_recovery_is_unchanged_conflict() -> None:
    recovering = _awaiting_recovery_state()
    resume = Resume(
        conversation_id="conversation-1",
        action_seq=2,
        expected_revision=recovering.revision,
    )

    transition = accept_action(recovering, resume)

    assert transition.disposition is ActionDisposition.CONFLICT
    assert transition.state == recovering
    assert transition.state.active_run is not None
    assert transition.state.active_run.status is ActiveRunStatus.AWAITING_RECOVERY


def test_resume_on_executing_continuation_remains_legal() -> None:
    # 进入 AWAITING_RECOVERY 的唯一入口是 Resume 一个 ownerless EXECUTING 续延；
    # loop 检测到 phase==EXECUTING 后创建 recovery request。reducer 必须保持 Resume 合法。
    executing = _executing_run_state()
    resume = Resume(
        conversation_id="conversation-1",
        action_seq=2,
        expected_revision=executing.revision,
    )

    transition = accept_action(executing, resume)

    assert transition.disposition is ActionDisposition.ACCEPTED
