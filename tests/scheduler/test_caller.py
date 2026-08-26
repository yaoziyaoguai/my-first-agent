from __future__ import annotations

from pathlib import Path

import pytest

from agent.composition import build_composition
from agent.runtime.context import ContextLimits
from agent.runtime.contracts import (
    ApprovalPolicy,
    BeginAnswer,
    ExecutionAuthorityClass,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    OutputPolicy,
    RunStatus,
    SideEffectClass,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.loop import InvocationLimits
from agent.runtime.tools import RegisteredTool
from agent.scheduler.caller import (
    ScheduledOccurrenceCaller,
    create_or_load_occurrence_store,
)
from agent.scheduler.contracts import ScheduledOccurrence, SchedulerError
from tests.kernel.fakes import CollectingSink, ScriptedProvider

SCOPE = "workspace-scope-digest"


def _occurrence(message: str = "what is the benign nightly status") -> ScheduledOccurrence:
    return ScheduledOccurrence(
        schedule_id="nightly-build",
        occurrence_id="2026-07-19T00:00:00Z",
        scheduled_for_utc="2026-07-19T00:00:00Z",
        message=message,
        workspace_scope_digest=SCOPE,
    )


def _gated_read_registration() -> RegisteredTool:
    # Scheduler 不是 Goal auto-driver：occurrence 首回合没有 durable Goal，effectful
    # 工具会在 prepare 前 fail closed。本测试只关心 approval pause/duplicate 语义，
    # 所以用诚实的 READ_ONLY + ALWAYS 审批工具触发同样的 pause 路径。
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="read_gated_fixture",
        version="1",
        description="read-only fixture tool that always requires approval",
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={},
        output_limit_chars=100,
    )
    return RegisteredTool(spec, lambda intent: "fixture read")


def _build_for(occurrence, state_root, provider):
    store, snapshot = create_or_load_occurrence_store(occurrence, state_root=state_root)
    composition = build_composition(
        provider=provider,
        checkpoint_store=store,
        tool_registrations=(_gated_read_registration(),),
        event_sink=CollectingSink(),
        system_policy="policy",
        context_limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        invocation_limits=InvocationLimits(),
    )
    return composition, store, snapshot


def test_first_fire_completes_and_duplicate_replays(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    occurrence = _occurrence()
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("nightly ok"),)))
    composition, store, snapshot = _build_for(occurrence, state_root, provider)

    report = ScheduledOccurrenceCaller(composition.runtime, store, snapshot, occurrence).run_once()
    assert report.run_status is RunStatus.COMPLETED
    assert report.occurrence_status == "completed"
    assert len(provider.calls) == 1

    # exact duplicate fire：reload 现有 store，replay seq 1，provider/effect 不重复。
    store2, snapshot2 = create_or_load_occurrence_store(occurrence, state_root=state_root)
    caller2 = ScheduledOccurrenceCaller(composition.runtime, store2, snapshot2, occurrence)
    report2 = caller2.run_once()
    assert report2.replayed is True
    assert len(provider.calls) == 1


def test_same_ids_different_message_conflicts_without_overwrite(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    first = _occurrence(message="original")
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("ok"),)))
    composition, _store, _snapshot = _build_for(first, state_root, provider)
    # 先真正跑一次 first，确保 occurrence checkpoint 存在。
    s_first, snap_first = create_or_load_occurrence_store(first, state_root=state_root)
    ScheduledOccurrenceCaller(composition.runtime, s_first, snap_first, first).run_once()

    drifted = _occurrence(message="tampered")
    with pytest.raises(SchedulerError):
        create_or_load_occurrence_store(drifted, state_root=state_root)


def test_paused_status_is_needs_human(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    occurrence = _occurrence()
    provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer("begin-scheduled-read")),
        ModelResponse((ModelToolCall("c1", "read_gated_fixture", {}),)),
    )
    composition, store, snapshot = _build_for(occurrence, state_root, provider)

    report = ScheduledOccurrenceCaller(composition.runtime, store, snapshot, occurrence).run_once()
    assert report.run_status is RunStatus.AWAITING_APPROVAL
    assert report.occurrence_status == "needs_human"
    assert report.pending_kind == "ApprovalRequest"


def test_conversation_busy_reconciles_with_one_shot_reload(tmp_path: Path) -> None:
    """G5 closure gate：conversation_busy 与 checkpoint_conflict 使用同一 one-shot
    reconciliation——reload authoritative snapshot，重交完全相同的 seq-1 action；不 loop，
    第二次仍冲突则原样返回。"""
    from agent.runtime.contracts import RunResult

    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    occurrence = _occurrence()
    store, snapshot = create_or_load_occurrence_store(occurrence, state_root=state_root)

    class _BusyThenComplete:
        def __init__(self) -> None:
            self.calls = 0

        def run_turn(self, action, snap):  # noqa: ANN001
            self.calls += 1
            if self.calls == 1:
                # 并发 winner 仍持 lease：loser 的 try_acquire 失败。
                return RunResult(
                    status=RunStatus.CONFLICT, state=snap.state, error_code="conversation_busy"
                )
            return RunResult(status=RunStatus.COMPLETED, state=snap.state, message="replayed")

    runtime = _BusyThenComplete()
    report = ScheduledOccurrenceCaller(runtime, store, snapshot, occurrence).run_once()
    assert runtime.calls == 2, "must reload once and re-submit the same seq-1 action"
    assert report.run_status is RunStatus.COMPLETED


def test_human_resolution_duplicate_reports_authoritative_terminal_state(tmp_path: Path) -> None:
    """A10: after human resolves approval with seq 2, duplicate fire must report
    the authoritative terminal state (COMPLETED), not the stale AWAITING_APPROVAL."""
    from agent.runtime.contracts import ResolveApproval
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    occurrence = _occurrence()
    provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer("begin-scheduled-resolution")),
        ModelResponse((ModelToolCall("c1", "read_gated_fixture", {}),)),
        ModelResponse((ModelTextBlock("resolved ok"),)),
    )
    composition, store, snapshot = _build_for(occurrence, state_root, provider)

    # first fire → approval pause
    first = ScheduledOccurrenceCaller(composition.runtime, store, snapshot, occurrence).run_once()
    assert first.run_status is RunStatus.AWAITING_APPROVAL

    # human resolves with seq 2
    auth_state = store.load().state
    pending = auth_state.active_run.pending_request
    resolve = ResolveApproval(
        conversation_id=occurrence.conversation_id,
        action_seq=auth_state.next_action_seq,
        expected_revision=auth_state.revision,
        request_id=pending.request_id,
        binding_digest=pending.binding_digest,
        approved=True,
    )
    runtime_result = composition.runtime.run_turn(resolve, store.load())
    assert runtime_result.status is RunStatus.COMPLETED

    # duplicate fire → report authoritative COMPLETED, not stale AWAITING_APPROVAL
    store2, snap2 = create_or_load_occurrence_store(occurrence, state_root=state_root)
    dup = ScheduledOccurrenceCaller(composition.runtime, store2, snap2, occurrence).run_once()
    assert dup.run_status is RunStatus.COMPLETED
    assert dup.occurrence_status == "completed"
