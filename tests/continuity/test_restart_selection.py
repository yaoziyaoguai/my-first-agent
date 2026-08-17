from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from agent.composition import build_composition
from agent.continuity.restart import project_restart
from agent.continuity.sessions import StartupDisposition, open_workspace_session
from agent.provider.fake_provider import FakeProvider
from agent.runtime.context import ContextLimits
from agent.runtime.contracts import (
    ActiveRun,
    ContinuationPhase,
    ConversationFact,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    FactKind,
    Resume,
    RunStatus,
    ToolCall,
)
from agent.runtime.loop import InvocationLimits
from agent.runtime.state import create_goal
from agent.runtime.tools import KernelToolRuntime
from tests.continuity.test_contracts import _goal
from tests.kernel.fakes import CollectingSink


def _persist_goal(opened, *, active_run: ActiveRun | None = None) -> None:  # noqa: ANN001
    assert opened.store is not None and opened.snapshot is not None
    source = ConversationFact(
        fact_id="fact:user:1",
        kind=FactKind.USER_MESSAGE,
        content={"text": "生成一份可验收的报告"},
    )
    with_goal = create_goal(
        replace(opened.snapshot.state, facts=(source,)),
        _goal(workspace_identity_digest=opened.workspace_identity.identity_digest),
    )
    if active_run is not None:
        with_goal = replace(with_goal, active_run=active_run)
    lease = opened.store.try_acquire(opened.snapshot.state.conversation_id)
    assert lease is not None
    try:
        opened.store.compare_and_swap(opened.snapshot, with_goal)
    finally:
        lease.release()


def test_reopen_projects_goal_summary_without_provider_or_tool_call(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000017",
    )
    _persist_goal(opened)

    def _unexpected(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("startup projection must not call Provider or Tool")

    monkeypatch.setattr(FakeProvider, "generate", _unexpected)
    monkeypatch.setattr(KernelToolRuntime, "invoke", _unexpected)

    reopened = open_workspace_session(workspace, state_root=state_root)
    projection = project_restart(reopened)

    assert reopened.disposition is StartupDisposition.RESUMED
    assert projection.goal_id == "goal:1"
    assert projection.goal_revision == 1
    assert projection.user_outcome == "生成一份可验收的报告"
    assert projection.required_action is None


def test_executing_checkpoint_enters_existing_unknown_effect_recovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000018",
    )
    call = ToolCall("call:1", "write_file", {"path": "reports/final.md"})
    active_run = ActiveRun(
        run_id="run:1",
        phase=ContinuationPhase.EXECUTING,
        executing_intent=ExecutingIntentRecord(
            "call:1",
            "intent:write:1",
            "idempotency:write:1",
            execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        ),
        tool_calls=(call,),
    )
    _persist_goal(opened, active_run=active_run)

    reopened = open_workspace_session(workspace, state_root=state_root)
    projection = project_restart(reopened)
    assert reopened.disposition is StartupDisposition.RECOVERY_REQUIRED
    assert projection.required_action == "resolve_unknown_tool_outcome"
    assert reopened.store is not None and reopened.snapshot is not None

    def _unexpected(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("unknown-effect restart must not call Provider or Tool")

    monkeypatch.setattr(FakeProvider, "generate", _unexpected)
    monkeypatch.setattr(KernelToolRuntime, "invoke", _unexpected)
    provider = FakeProvider()
    composition = build_composition(
        provider=provider,
        checkpoint_store=reopened.store,
        tool_registrations=(),
        event_sink=CollectingSink(),
        system_policy="policy",
        context_limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        invocation_limits=InvocationLimits(),
    )
    result = composition.runtime.run_turn(
        Resume(
            conversation_id=reopened.snapshot.state.conversation_id,
            action_seq=reopened.snapshot.state.next_action_seq,
            expected_revision=reopened.snapshot.state.revision,
        ),
        reopened.snapshot,
    )

    assert result.status is RunStatus.AWAITING_RECOVERY
