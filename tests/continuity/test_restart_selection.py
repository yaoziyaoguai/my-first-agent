from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from agent.composition import build_composition, build_tool_registrations
from agent.continuity.restart import project_restart
from agent.continuity.sessions import StartupDisposition, open_workspace_session
from agent.provider.fake_provider import FakeProvider
from agent.runtime.context import ContextLimits
from agent.runtime.contracts import (
    ActiveRun,
    BeginAnswer,
    ContinuationPhase,
    ConversationFact,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    FactKind,
    GoalProgress,
    GoalStatus,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    Resume,
    RunStatus,
    SubmitMessage,
    ToolCall,
    source_result_since_latest_user,
)
from agent.runtime.loop import InvocationLimits
from agent.runtime.state import create_goal, record_goal_progress
from agent.runtime.tools import KernelToolRuntime
from tests.continuity.test_contracts import _goal
from tests.kernel.fakes import (
    CollectingSink,
    ScriptedProvider,
    goal_draft_from_frame,
)


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


def test_reopen_projects_restart_ready_work_record_without_repeating_effects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000020",
    )
    assert opened.store is not None and opened.snapshot is not None
    source = ConversationFact(
        fact_id="fact:user:work-record",
        kind=FactKind.USER_MESSAGE,
        content={"text": "修复导出并验证"},
    )
    state = create_goal(
        replace(opened.snapshot.state, facts=(source,)),
        _goal(
            workspace_identity_digest=opened.workspace_identity.identity_digest,
            created_from_fact_ids=(source.fact_id,),
        ),
    )
    state = record_goal_progress(
        state,
        GoalProgress(
            correlation_id="work-record-v1",
            goal_id=state.goal.goal_id,
            goal_revision=state.goal.revision,
            summary=(
                "已修改 exporter.py 和 tests/test_exporter.py；最近有效检查为 "
                "pytest tests/test_exporter.py（12 passed）；失败路线：不要再用 split(',')"
            ),
            next_step="检查整体 diff，再运行最终相关回归并收尾",
        ),
    )
    lease = opened.store.try_acquire(state.conversation_id)
    assert lease is not None
    try:
        opened.store.compare_and_swap(opened.snapshot, state)
    finally:
        lease.release()

    def _unexpected(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("restart projection must not call Provider or Tool")

    monkeypatch.setattr(FakeProvider, "generate", _unexpected)
    monkeypatch.setattr(KernelToolRuntime, "invoke", _unexpected)
    reopened = open_workspace_session(workspace, state_root=state_root)
    projection = project_restart(reopened)

    assert projection.progress_summary == state.goal.progress_summary
    assert projection.next_step == state.goal.next_step
    assert projection.goal_revision == state.goal.revision
    assert reopened.snapshot is not None
    assert reopened.snapshot.state.facts == (source,)


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


def test_restart_after_answer_grounding_keeps_goal_window_closed_without_user_action(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """已接受的问答检索可恢复，但外部内容不能在重启后升级成 Goal。"""
    workspace = tmp_path / "restart-workspace"
    workspace.mkdir()
    (workspace / "data.csv").write_text("name,value\na,1\n", encoding="utf-8")
    state_root = tmp_path / "state-root"
    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000019",
    )
    assert opened.store is not None and opened.snapshot is not None
    goal_frame = _goal(workspace_identity_digest=opened.workspace_identity.identity_digest)
    provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer(correlation_id="ctl-answer-1")),
        ModelResponse((ModelToolCall("call:1", "read_file", {"path": "data.csv"}),)),
        ModelResponse((), control=goal_draft_from_frame("ctl-goal-1", goal_frame)),
        ModelResponse((ModelTextBlock("我已读取本地数据。"),)),
    )
    composition = build_composition(
        provider=provider,
        checkpoint_store=opened.store,
        tool_registrations=build_tool_registrations(
            workspace=workspace,
            max_tool_result_chars=20_000,
        ),
        event_sink=CollectingSink(),
        system_policy="policy",
        context_limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        invocation_limits=InvocationLimits(),
        workspace_identity_digest=opened.workspace_identity.identity_digest,
        context_scope_digest=opened.workspace_identity.scope_digest,
    )
    first_state = opened.snapshot.state
    result = composition.runtime.run_turn(
        SubmitMessage(
            conversation_id=first_state.conversation_id,
            action_seq=first_state.next_action_seq,
            expected_revision=first_state.revision,
            run_id="run-j12-first",
            message="读取 data.csv 并告诉我其中第一条记录是什么？",
        ),
        opened.snapshot,
    )

    # 第一进程结束：begin_answer 已先落盘，read 才成功；随后从 source 内容
    # 推导的 Goal 被拒绝，问答文本可以安全收尾。
    assert result.status is RunStatus.COMPLETED
    state = opened.store.load().state
    assert state.goal is None
    assert source_result_since_latest_user(state) is True
    assert any(
        fact.kind is FactKind.TOOL_RESULT
        and isinstance(fact.content.get("metadata"), dict)
        and fact.content["metadata"].get("source_receipts")
        for fact in state.facts
    ), "pre-Goal read must leave durable workspace source receipts"

    # 重启：恢复同一 conversation，零 provider/tool 调用，投影准确。
    def _unexpected(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("restart projection must not call Provider or Tool")

    monkeypatch.setattr(FakeProvider, "generate", _unexpected)
    monkeypatch.setattr(KernelToolRuntime, "invoke", _unexpected)
    reopened = open_workspace_session(workspace, state_root=state_root)
    projection = project_restart(reopened)

    assert reopened.disposition is StartupDisposition.RESUMED
    assert reopened.snapshot is not None and reopened.store is not None
    assert reopened.snapshot.state.conversation_id == state.conversation_id
    assert projection.goal_id is None
    assert projection.required_action is None
    assert source_result_since_latest_user(reopened.snapshot.state) is True, (
        "restart is not a user action; the Goal minting window stays closed"
    )

    # 恢复路径正控：真实用户补充后同一 Goal 草案可被铸造（013 的
    # before_user_interrupt 语义）；E3 harness 依 §7 不提供该补充。
    provider_after = ScriptedProvider(
        ModelResponse((), control=goal_draft_from_frame("ctl-goal-2", goal_frame)),
        ModelResponse((ModelTextBlock("已重新建立任务。"),)),
    )
    composition_after = build_composition(
        provider=provider_after,
        checkpoint_store=reopened.store,
        tool_registrations=(),
        event_sink=CollectingSink(),
        system_policy="policy",
        context_limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        invocation_limits=InvocationLimits(),
        workspace_identity_digest=opened.workspace_identity.identity_digest,
        context_scope_digest=opened.workspace_identity.scope_digest,
    )
    second_state = reopened.snapshot.state
    composition_after.runtime.run_turn(
        SubmitMessage(
            conversation_id=second_state.conversation_id,
            action_seq=second_state.next_action_seq,
            expected_revision=second_state.revision,
            run_id="run-j12-second",
            message="请按原要求继续完成这个任务。",
        ),
        reopened.snapshot,
    )

    final_state = reopened.store.load().state
    assert final_state.goal is not None
    assert final_state.goal.goal_id.startswith("goal-v1-"), (
        "the Goal must be Runtime-minted, not model self-reported"
    )


def test_force_new_creates_fresh_conversation_keeping_prior_history(
    tmp_path: Path,
) -> None:
    """/new(r19 小步 2):显式新任务必须得到新的 conversation identity,
    即便旧会话尚无 Goal(无 Goal 会话在 resume 语义下视为 active,普通
    open 会被 RESUMED 而不是新建)。旧 checkpoint 原样保留在历史中。"""
    workspace = tmp_path / "w"
    workspace.mkdir()
    state_root = tmp_path / "state"

    first = open_workspace_session(workspace, state_root=state_root)
    assert first.disposition is StartupDisposition.CREATED
    assert first.snapshot is not None and first.checkpoint_path is not None

    # 无 Goal 的闲聊会话:普通 open 会 RESUMED 同一会话。
    resumed = open_workspace_session(workspace, state_root=state_root)
    assert resumed.disposition is StartupDisposition.RESUMED
    assert resumed.snapshot is not None
    assert (
        resumed.snapshot.state.conversation_id
        == first.snapshot.state.conversation_id
    )

    # force_new(/new 语义):新 conversation identity,旧 checkpoint 保留。
    second = open_workspace_session(
        workspace, state_root=state_root, force_new=True
    )
    assert second.disposition is StartupDisposition.CREATED
    assert second.snapshot is not None
    assert (
        second.snapshot.state.conversation_id
        != first.snapshot.state.conversation_id
    )
    assert first.checkpoint_path.exists()


def test_select_required_forces_selector_over_single_active_candidate(
    tmp_path: Path,
) -> None:
    """/switch(Oracle gap2 #1):select_required 投影下,单个 active 候选也不
    自动 RESUMED——切换的语义就是让用户显式选择(候选含当前 conversation)。"""
    workspace = tmp_path / "w"
    workspace.mkdir()
    state_root = tmp_path / "state"

    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000051",
    )
    assert opened.disposition is StartupDisposition.CREATED
    _persist_goal(opened)

    # 默认投影:单候选自动 RESUMED(既有语义保持)。
    resumed = open_workspace_session(workspace, state_root=state_root)
    assert resumed.disposition is StartupDisposition.RESUMED

    # /switch 语义:同一状态强制 SELECT_REQUIRED。
    selection = open_workspace_session(
        workspace, state_root=state_root, select_required=True
    )
    assert selection.disposition is StartupDisposition.SELECT_REQUIRED
    assert selection.candidate_inventory is not None
    assert len(selection.candidate_inventory) == 1


def test_select_required_without_active_candidates_creates_new_conversation(
    tmp_path: Path,
) -> None:
    """/switch 没有任何非终态候选时落到新建 conversation(与 startup 行为一致);
    调用方(main)对该投影显式告知,不静默换挡。"""
    workspace = tmp_path / "w"
    workspace.mkdir()
    state_root = tmp_path / "state"

    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000061",
    )
    assert opened.store is not None and opened.snapshot is not None
    _persist_goal(opened)
    snapshot = opened.store.load()
    # 终态 Goal 的 conversation 不是 active 候选（CANCELLED 终态，无 completion
    # claim 语义纠缠，fixture 最小）。
    terminal = replace(
        snapshot.state,
        goal=replace(snapshot.state.goal, status=GoalStatus.CANCELLED),
    )
    lease = opened.store.try_acquire(snapshot.state.conversation_id)
    assert lease is not None
    try:
        opened.store.compare_and_swap(snapshot, terminal)
    finally:
        lease.release()

    fallback = open_workspace_session(
        workspace, state_root=state_root, select_required=True
    )
    assert fallback.disposition is StartupDisposition.CREATED
    assert fallback.snapshot is not None
    assert (
        fallback.snapshot.state.conversation_id
        != snapshot.state.conversation_id
    )


def test_force_new_and_select_required_are_mutually_exclusive(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "w"
    workspace.mkdir()
    try:
        open_workspace_session(
            workspace,
            state_root=tmp_path / "state",
            force_new=True,
            select_required=True,
        )
    except ValueError as error:
        assert "mutually exclusive" in str(error)
    else:
        raise AssertionError("force_new + select_required must be rejected")
