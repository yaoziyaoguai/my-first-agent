"""013 CLI 上下文确认：用户不复制内部 digest 或 request ID。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import main as entrypoint
from agent.cli.app import run_repl
from agent.continuity.sessions import open_workspace_session
from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.contracts import (
    AcknowledgeProviderDisclosure,
    ActiveRun,
    ActiveRunStatus,
    AdmittedCriterion,
    ApprovalRequest,
    ContinuationPhase,
    ConversationState,
    EgressClass,
    EvidenceOracleKind,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    GoalFrame,
    GoalStatus,
    LoadedSnapshot,
    ModelResponse,
    ModelTextBlock,
    ProposedCriterion,
    ProviderDisclosureReceipt,
    ProviderDisclosureRequest,
    RecoverUnknownObservation,
    RecoveryRequest,
    RecoveryResolution,
    ResolveApproval,
    ResolveUnknownToolOutcome,
    RunResult,
    RunStatus,
    SideEffectClass,
    SubmitMessage,
    ToolCall,
)


class StaticStore:
    def __init__(self, state: ConversationState) -> None:
        self.state = state

    def load(self) -> LoadedSnapshot:
        return LoadedSnapshot(self.state, "token-1")


class RecordingRuntime:
    def __init__(self) -> None:
        self.actions = []
        self.snapshots = []

    def run_turn(self, action, snapshot):  # noqa: ANN001
        self.actions.append(action)
        self.snapshots.append(snapshot)
        return RunResult(RunStatus.COMPLETED, snapshot.state)


class SequencedStore:
    """按 load 次序返回预置 snapshot，模拟 action 完成后状态的 durable 演进。"""

    def __init__(self, states: list[ConversationState]) -> None:
        self._states = list(states)
        self._loads = 0

    def load(self) -> LoadedSnapshot:
        index = min(len(self._states) - 1, self._loads)
        self._loads += 1
        return LoadedSnapshot(self._states[index], f"token-{index}")


def _run(state: ConversationState, *inputs: str):
    runtime = RecordingRuntime()
    values = iter(inputs)
    output: list[str] = []
    exit_code = run_repl(
        runtime,
        StaticStore(state),
        input_fn=lambda _: next(values),
        write_fn=output.append,
        run_id_factory=lambda: "run-new",
    )
    return runtime, output, exit_code


def test_repl_shows_working_feedback_before_running_an_action() -> None:
    """非流式路径在同步 Runtime 调用前也必须让用户知道输入已被接收。"""

    output: list[str] = []
    state = ConversationState.new("conversation-1")
    inputs = iter(("do the work", "/exit"))

    class FeedbackObservingRuntime:
        def run_turn(self, action, snapshot):  # noqa: ANN001
            assert output == ["Working..."]
            return RunResult(
                RunStatus.COMPLETED,
                snapshot.state,
                run_id=action.run_id,
                message="done",
            )

    exit_code = run_repl(
        FeedbackObservingRuntime(),
        StaticStore(state),
        input_fn=lambda _prompt: next(inputs),
        write_fn=output.append,
        run_id_factory=lambda: "run-new",
    )

    assert exit_code == 0
    assert output == ["Working...", "done"]


def _disclosure_state() -> ConversationState:
    request = ProviderDisclosureRequest.create(
        disclosure_id="disclosure-1",
        provider_descriptor_digest="descriptor-1",
        canonical_destination="https://provider.example/v1",
        model="daily-model",
        data_classes=("user_message",),
    )
    return replace(
        ConversationState.new("conversation-1"),
        active_run=ActiveRun(
            "run-1",
            status=ActiveRunStatus.AWAITING_DISCLOSURE,
        ),
        provider_disclosure_request=request,
    )


def _approval_state() -> tuple[ConversationState, ApprovalRequest]:
    request = ApprovalRequest(
        request_id="approval-internal-id",
        run_id="run-1",
        tool_call_id="call-1",
        binding_digest="approval-binding",
        preview="write notes/idea.md (12 bytes)",
        tool_name="write_file",
    )
    state = replace(
        ConversationState.new("conversation-1"),
        active_run=ActiveRun(
            "run-1",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            pending_request=request,
            tool_calls=(ToolCall("call-1", "write_file", {}),),
        ),
    )
    return state, request


def _recovery_state() -> tuple[ConversationState, RecoveryRequest]:
    request = RecoveryRequest(
        request_id="recovery-internal-id",
        run_id="run-1",
        tool_call_id="call-1",
        binding_digest="recovery-binding",
        summary="the write outcome is unknown",
    )
    state = replace(
        ConversationState.new("conversation-1"),
        active_run=ActiveRun(
            "run-1",
            status=ActiveRunStatus.AWAITING_RECOVERY,
            phase=ContinuationPhase.EXECUTING,
            pending_request=request,
            executing_intent=ExecutingIntentRecord(
                execution_authority=ExecutionAuthorityClass.IN_PROCESS,
                tool_call_id="call-1",
                intent_digest="recovery-binding",
                idempotency_key="idempotency-1",
            ),
            tool_calls=(ToolCall("call-1", "write_file", {}),),
        ),
    )
    return state, request


def _public_observation_recovery_state() -> ConversationState:
    state, request = _recovery_state()
    assert state.active_run is not None
    return replace(
        state,
        active_run=replace(
            state.active_run,
            pending_request=replace(request, summary="public observation outcome is unknown"),
            executing_intent=ExecutingIntentRecord(
                execution_authority=ExecutionAuthorityClass.IN_PROCESS,
                tool_call_id="call-1",
                intent_digest="recovery-binding",
                idempotency_key="request-1",
                side_effect=SideEffectClass.READ_ONLY,
                egress=EgressClass.PUBLIC_NETWORK,
                operation="search",
                request_identity="request-1",
            ),
            tool_calls=(ToolCall("call-1", "web_search", {}),),
        ),
    )


@pytest.mark.parametrize("answer", ["y", "YES", "是", "允许"])
def test_contextual_disclosure_yes_binds_exact_pending_digest(answer: str) -> None:
    state = _disclosure_state()
    runtime, _, exit_code = _run(state, answer, "/exit")

    assert exit_code == 0
    action = runtime.actions[0]
    assert isinstance(action, AcknowledgeProviderDisclosure)
    assert action.request_digest == state.provider_disclosure_request.request_digest


@pytest.mark.parametrize("answer", ["n", "NO", "否", "不允许"])
def test_contextual_disclosure_no_exits_without_send_action(answer: str) -> None:
    runtime, output, exit_code = _run(_disclosure_state(), answer)

    assert exit_code == 0
    assert runtime.actions == []
    # 输入前显示的是 disclosure 决策提示；退出消息只陈述本次 pending 未发送
    # （B，2026-10-18），不笼统声称历史零发送。
    assert output[0].startswith("Remote provider disclosure required")
    assert output[-1] == _RELEASE_B_REFUSAL


def _resumed_disclosure_state() -> ConversationState:
    """E1-B 缺口形态（2026-10-17）：/pause 停掉 active run、/resume 已把 Goal 翻回
    GOAL_READY，挂起披露仍 durable——y 必须仍可应答以点燃继续回合。"""
    request = ProviderDisclosureRequest.create(
        disclosure_id="disclosure-1",
        provider_descriptor_digest="descriptor-1",
        canonical_destination="https://provider.example/v1",
        model="daily-model",
        data_classes=("user_message",),
    )
    goal = GoalFrame(
        goal_id="goal-1",
        revision=1,
        created_from_fact_ids=("action:1:user",),
        workspace_identity_digest="workspace-digest-1",
        user_outcome="Persist the requested fixture note",
        beneficiary="user",
        targets=("workspace",),
        scope=("workspace/fixtures",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(
            ProposedCriterion("criterion-1", "fixture note exists"),
        ),
        admitted_criteria=(),
        authority_snapshot="authority-1",
        status=GoalStatus.GOAL_READY,
        created_at="2026-10-17T00:00:00Z",
        updated_at="2026-10-17T00:00:00Z",
    )
    return replace(
        ConversationState.new("conversation-1"),
        goal=goal,
        provider_disclosure_request=request,
    )


def test_contextual_disclosure_yes_after_goal_resume_binds_pending_digest() -> None:
    state = _resumed_disclosure_state()
    runtime, _, exit_code = _run(state, "y", "/exit")

    assert exit_code == 0
    action = runtime.actions[0]
    assert isinstance(action, AcknowledgeProviderDisclosure)
    assert action.request_digest == state.provider_disclosure_request.request_digest


def test_contextual_disclosure_yes_stays_inactive_while_goal_still_paused() -> None:
    base = _resumed_disclosure_state()
    assert base.goal is not None
    state = replace(base, goal=replace(base.goal, status=GoalStatus.PAUSED))
    runtime, _, exit_code = _run(state, "y", "/exit")

    assert exit_code == 0
    assert all(
        not isinstance(action, AcknowledgeProviderDisclosure)
        for action in runtime.actions
    )


# ---- B（2026-10-18 CLI release blockers）：pending 外发确认的 yes/no/空回车
# 在活跃 AWAITING_DISCLOSURE 与 /pause→/resume 恢复形状下是同一个决定 ----

_RELEASE_B_REFUSAL = (
    "The pending disclosure was not sent. The task is preserved; leaving this session."
)


@pytest.mark.parametrize(
    "state_factory", [_disclosure_state, _resumed_disclosure_state]
)
@pytest.mark.parametrize("answer", ["n", "no", "否", "", "   "])
def test_release_b_refusal_and_default_refusal_exit_safely(
    state_factory, answer: str
) -> None:
    """n/no/否/空回车/纯空格都等于拒绝：当前输入后立即安全退出，不提交
    业务消息、不生成 receipt、不触发任何 run_turn（含空输入——只提供一次
    输入，第二次读取即失败，证明拒绝发生在当前输入而非下一轮）。"""

    runtime, output, exit_code = _run(state_factory(), answer)

    assert exit_code == 0
    assert runtime.actions == []
    assert output[0].startswith("Remote provider disclosure required")
    assert output[-1] == _RELEASE_B_REFUSAL


@pytest.mark.parametrize("answer", ["y", "yes", "是", "n", "no", "否"])
def test_release_b_paused_guard_prompts_resume_without_business_message(
    answer: str,
) -> None:
    """窄范围 PAUSED 保护：active=None、Goal=PAUSED、request!=None、receipt=None
    时裸 yes/no（含原同义词）只提示先 /resume，不提交业务消息。"""

    base = _resumed_disclosure_state()
    assert base.goal is not None
    state = replace(base, goal=replace(base.goal, status=GoalStatus.PAUSED))
    runtime, output, exit_code = _run(state, answer, "/exit")

    assert exit_code == 0
    assert runtime.actions == []
    rendered = "\n".join(output)
    assert _RELEASE_B_REFUSAL not in rendered
    assert "/resume" in rendered


def test_release_b_paused_empty_stays_ignored() -> None:
    base = _resumed_disclosure_state()
    assert base.goal is not None
    state = replace(base, goal=replace(base.goal, status=GoalStatus.PAUSED))
    runtime, output, exit_code = _run(state, "", "/exit")

    assert exit_code == 0
    assert runtime.actions == []
    rendered = "\n".join(output)
    assert _RELEASE_B_REFUSAL not in rendered
    assert "/resume" not in rendered


def test_release_b_empty_without_pending_stays_ignored() -> None:
    runtime, output, exit_code = _run(ConversationState.new("conversation-1"), "", "/exit")

    assert exit_code == 0
    assert runtime.actions == []
    assert _RELEASE_B_REFUSAL not in "\n".join(output)


def _receipt_for(request: ProviderDisclosureRequest) -> ProviderDisclosureReceipt:
    return ProviderDisclosureReceipt(
        receipt_id="receipt-1",
        request_digest=request.request_digest,
        acknowledged_action_seq=1,
        acknowledged_at="2026-10-18T00:00:00Z",
    )


@pytest.mark.parametrize(
    "state_factory", [_disclosure_state, _resumed_disclosure_state]
)
def test_release_b_receipt_present_is_not_hijacked_by_refusal(state_factory) -> None:
    """已 receipt 的形状不是 answerable pending：n 不被拒绝分支接管为安全退出。
    活跃形状命中既有“run 等待专属命令”守卫；恢复形状走普通业务输入。"""

    state = state_factory()
    assert state.provider_disclosure_request is not None
    state = replace(
        state, provider_disclosure_receipt=_receipt_for(state.provider_disclosure_request)
    )
    runtime, output, exit_code = _run(state, "n")

    assert exit_code == 0
    rendered = "\n".join(output)
    assert _RELEASE_B_REFUSAL not in rendered
    assert all(
        not isinstance(action, AcknowledgeProviderDisclosure)
        for action in runtime.actions
    )
    if state.active_run is not None:
        assert runtime.actions == []
        assert "reserved command" in rendered
    else:
        assert runtime.actions and isinstance(runtime.actions[0], SubmitMessage)


def test_release_b_refused_pending_survives_checkpoint_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """经历 checkpoint 落盘、新进程重开：同一 pending 仍可渲染与拒绝，
    拒绝零外发、零状态演进，且 Goal 已 ready 不强迫再 /resume。"""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000042",
    )
    assert opened.store is not None and opened.snapshot is not None
    binding = opened.snapshot.state.workspace_binding
    assert binding is not None
    base = _resumed_disclosure_state()
    assert base.goal is not None
    pending = replace(
        base,
        conversation_id=opened.snapshot.state.conversation_id,
        workspace_binding=binding,
        goal=replace(base.goal, workspace_identity_digest=binding.workspace_identity_digest),
    )
    lease = opened.store.try_acquire(pending.conversation_id)
    assert lease is not None
    try:
        opened.store.compare_and_swap(opened.snapshot, pending)
    finally:
        lease.release()
    before = opened.store.load().state
    provider_calls: list[str] = []
    monkeypatch.setattr(
        entrypoint.FakeProvider,
        "generate",
        lambda *_args, **_kwargs: provider_calls.append("generate")
        or ModelResponse((ModelTextBlock("sent"),)),
    )
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--provider",
            "fake",
        ],
        input_fn=lambda _prompt: "n",
        write_fn=output.append,
    )

    assert exit_code == 0
    assert provider_calls == []
    assert LocalCheckpointStore(opened.checkpoint_path).load().state == before
    rendered = "\n".join(output)
    assert "Remote provider disclosure required" in rendered
    assert rendered.rstrip().endswith(_RELEASE_B_REFUSAL)
    # 同一落盘 pending 重开后 y 仍可应答：拒绝不清 pending、不写 DENIED。
    output_yes: list[str] = []
    reopened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000043",
    )
    assert reopened.snapshot is not None
    assert reopened.snapshot.state.goal is not None
    assert reopened.snapshot.state.goal.status is GoalStatus.GOAL_READY
    assert reopened.snapshot.state.provider_disclosure_request is not None
    runtime_reopen = RecordingRuntime()
    yes_values = iter(("y", "/exit"))
    yes_code = run_repl(
        runtime_reopen,
        opened.store,
        input_fn=lambda _prompt: next(yes_values),
        write_fn=output_yes.append,
        run_id_factory=lambda: "run-reopen",
    )

    assert yes_code == 0
    assert isinstance(runtime_reopen.actions[0], AcknowledgeProviderDisclosure)


@pytest.mark.parametrize(
    ("answer", "approved"),
    [("yes", True), ("是", True), ("no", False), ("否", False)],
)
def test_contextual_approval_binds_exact_pending_request(
    answer: str, approved: bool
) -> None:
    state, request = _approval_state()
    runtime, _, _ = _run(state, answer, "/exit")

    action = runtime.actions[0]
    assert isinstance(action, ResolveApproval)
    assert action.request_id == request.request_id
    assert action.binding_digest == request.binding_digest
    assert action.approved is approved


def test_natural_language_at_approval_is_a_goal_correction() -> None:
    state, _request = _approval_state()
    runtime, output, _ = _run(
        state,
        "请改为写入 final.md，不要创建 draft.md。",
        "/exit",
    )

    action = runtime.actions[0]
    assert isinstance(action, SubmitMessage)
    assert action.message == "请改为写入 final.md，不要创建 draft.md。"
    # 自然语言更正不产生 error 输出；Working 只确认输入已提交，仍由 pending
    # projection 提供唯一可操作的审批提示。
    assert output and all(
        message == "Working..." or "Approval required" in message for message in output
    )


@pytest.mark.parametrize(
    ("answer", "resolution"),
    [
        ("已成功", RecoveryResolution.MARK_SUCCEEDED),
        ("succeeded", RecoveryResolution.MARK_SUCCEEDED),
        ("未成功", RecoveryResolution.MARK_FAILED),
        ("failed", RecoveryResolution.MARK_FAILED),
    ],
)
def test_recovery_requires_explicit_outcome_and_binds_exact_request(
    answer: str, resolution: RecoveryResolution
) -> None:
    state, request = _recovery_state()
    runtime, _, _ = _run(state, answer, "/exit")

    action = runtime.actions[0]
    assert isinstance(action, ResolveUnknownToolOutcome)
    assert action.request_id == request.request_id
    assert action.binding_digest == request.binding_digest
    assert action.resolution is resolution


@pytest.mark.parametrize("answer", ["先停止", "stop"])
def test_recovery_stop_exits_without_classifying_or_replaying(answer: str) -> None:
    runtime, output, exit_code = _run(_recovery_state()[0], answer)

    assert exit_code == 0
    assert runtime.actions == []
    assert output[0].startswith("Unknown tool outcome")
    assert output[-1] == "Stopped without classifying or retrying the previous operation."


def test_ambiguous_yes_does_not_classify_unknown_outcome() -> None:
    runtime, output, _ = _run(_recovery_state()[0], "yes", "/exit")

    assert runtime.actions == []
    assert any("success" in message.lower() and "failed" in message.lower() for message in output)


@pytest.mark.parametrize("answer", ["continue", "继续"])
def test_public_observation_recovery_records_unknown_without_guess_or_retry(
    answer: str,
) -> None:
    state = _public_observation_recovery_state()
    runtime, _, _ = _run(state, answer, "/exit")

    action = runtime.actions[0]
    assert isinstance(action, RecoverUnknownObservation)
    assert action.tool_call_id == "call-1"
    assert action.intent_digest == "recovery-binding"


def test_public_observation_recovery_rejects_success_guess() -> None:
    runtime, output, _ = _run(
        _public_observation_recovery_state(),
        "success",
        "/exit",
    )

    assert runtime.actions == []
    assert any(
        "continue" in message.lower() and "not retry" in message.lower()
        for message in output
    )


@pytest.mark.parametrize("text", ["yes", "no", "是", "否"])
def test_same_text_without_pending_decision_is_an_ordinary_message(text: str) -> None:
    state = ConversationState.new("conversation-1")
    runtime, _, _ = _run(state, text, "/exit")

    action = runtime.actions[0]
    assert isinstance(action, SubmitMessage)
    assert action.message == text


@pytest.mark.parametrize("pending_kind", ["disclosure", "approval", "recovery"])
def test_restart_redisplays_exact_pending_decision_without_provider_or_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pending_kind: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000041",
    )
    assert opened.store is not None and opened.snapshot is not None
    if pending_kind == "disclosure":
        pending = _disclosure_state()
        expected = "destination: https://provider.example/v1"
    elif pending_kind == "approval":
        pending = _approval_state()[0]
        expected = "preview: write notes/idea.md (12 bytes)"
    else:
        pending = _recovery_state()[0]
        expected = "Unknown tool outcome: the write outcome is unknown"
    pending = replace(
        pending,
        conversation_id=opened.snapshot.state.conversation_id,
        workspace_binding=opened.snapshot.state.workspace_binding,
    )
    lease = opened.store.try_acquire(pending.conversation_id)
    assert lease is not None
    try:
        opened.store.compare_and_swap(opened.snapshot, pending)
    finally:
        lease.release()
    before = opened.store.load().state
    provider_calls: list[str] = []
    monkeypatch.setattr(
        entrypoint.FakeProvider,
        "generate",
        lambda *_args, **_kwargs: provider_calls.append("generate") or None,
    )
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--provider",
            "fake",
        ],
        input_fn=lambda _prompt: "/exit",
        write_fn=output.append,
    )

    assert exit_code == 0
    assert provider_calls == []
    assert LocalCheckpointStore(opened.checkpoint_path).load().state == before
    rendered = "\n".join(output)
    assert expected in rendered
    assert "internal-id" not in rendered
    assert "binding" not in rendered


def _approval_state_with(request_id: str, preview: str) -> ConversationState:
    request = ApprovalRequest(
        request_id=request_id,
        run_id="run-1",
        tool_call_id="call-1",
        binding_digest=f"binding-{request_id}",
        preview=preview,
        tool_name="write_file",
    )
    return replace(
        ConversationState.new("conversation-1"),
        active_run=ActiveRun(
            "run-1",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            pending_request=request,
            tool_calls=(ToolCall("call-1", "write_file", {}),),
        ),
    )


def _local_store(tmp_path: Path, state: ConversationState) -> LocalCheckpointStore:
    import os

    root = tmp_path / "state-root"
    root.mkdir()
    os.chmod(root, 0o700)
    return LocalCheckpointStore.initialize(root / "checkpoint", state)


def test_answer_binds_to_the_snapshot_displayed_before_input(tmp_path: Path) -> None:
    """两调用者竞态：显示 A 之后、输入返回 yes 前 store 漂移到 B，答案仍只绑 A。"""

    state_a = _approval_state_with("approval-a", "write notes/idea.md (12 bytes)")
    store = _local_store(tmp_path, state_a)
    state_b = replace(
        _approval_state_with("approval-b", "write notes/other.md (3 bytes)"),
        revision=state_a.revision + 1,
    )
    runtime = RecordingRuntime()
    output: list[str] = []
    seen_before_input: list[str] = []

    def racing_input(_prompt: str) -> str:
        seen_before_input.append("\n".join(output))
        if len(seen_before_input) == 1:
            lease = store.try_acquire(state_a.conversation_id)
            assert lease is not None
            try:
                store.compare_and_swap(store.load(), state_b)
            finally:
                lease.release()
            return "yes"
        return "/exit"

    exit_code = run_repl(
        runtime,
        store,
        input_fn=racing_input,
        write_fn=output.append,
        run_id_factory=lambda: "run-new",
    )

    assert exit_code == 0
    # 所见：yes 输入前终端显示的是 A 的 pending preview，不是漂移后 B 的。
    assert "write notes/idea.md" in seen_before_input[0]
    assert "write notes/other.md" not in seen_before_input[0]
    # 所批：action 与 snapshot 都来自 A，绝不重绑到 B。
    action = runtime.actions[0]
    assert isinstance(action, ResolveApproval)
    assert action.request_id == "approval-a"
    assert action.expected_revision == state_a.revision
    assert runtime.snapshots[0].state.revision == state_a.revision


def test_drifted_answer_conflicts_with_zero_side_effects(tmp_path: Path) -> None:
    """真实 runtime + 真实 LocalCheckpointStore：drift 后 CAS 使绑定答案零副作用。"""

    from agent.runtime.context import ContextLimits, KernelContextManager
    from agent.runtime.contracts import ModelResponse, ModelTextBlock
    from agent.runtime.loop import AgentRuntime, InvocationLimits
    from agent.runtime.tools import KernelToolRuntime
    from tests.kernel.fakes import CollectingSink, ScriptedProvider

    state_a = _approval_state_with("approval-a", "write notes/idea.md (12 bytes)")
    store = _local_store(tmp_path, state_a)
    state_b = replace(
        _approval_state_with("approval-b", "write notes/other.md (3 bytes)"),
        revision=state_a.revision + 1,
    )
    provider = ScriptedProvider(
        ModelResponse((ModelTextBlock("must not run"),))
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-race",
    )
    output: list[str] = []

    def racing_input(_prompt: str) -> str:
        lease = store.try_acquire(state_a.conversation_id)
        assert lease is not None
        try:
            store.compare_and_swap(store.load(), state_b)
        finally:
            lease.release()
        return "yes"

    exit_code = run_repl(
        runtime,
        store,
        input_fn=racing_input,
        write_fn=output.append,
        run_id_factory=lambda: "run-new",
    )

    # CAS fail closed：CONFLICT 退出，不重试、不重绑、provider 零调用。
    assert exit_code == 2
    assert provider.calls == []
    final = store.load().state
    assert final.revision == state_b.revision
    active = final.active_run
    assert active is not None and isinstance(active.pending_request, ApprovalRequest)
    assert active.pending_request.request_id == "approval-b"


@pytest.mark.parametrize("pending_kind", ["disclosure", "approval", "recovery"])
@pytest.mark.parametrize("scenario", ["startup", "after_action"])
def test_pending_decision_is_displayed_from_state_before_each_input(
    pending_kind: str,
    scenario: str,
) -> None:
    """event 全部丢失时，决策提示仍从 authoritative snapshot 在每次输入前显示。"""

    if pending_kind == "disclosure":
        pending = _disclosure_state()
        expected = "Allow this information to be sent? [y/N]"
    elif pending_kind == "approval":
        pending = _approval_state()[0]
        expected = "Execute this operation? [y/N]"
    else:
        pending = _recovery_state()[0]
        expected = "Reply with 'success', 'failed', or 'stop'."
    if scenario == "startup":
        store = SequencedStore([pending])
        first_input = "stop-answer-unused"
    else:
        store = SequencedStore([ConversationState.new("conversation-1"), pending])
        first_input = "hello"
    runtime = RecordingRuntime()
    output: list[str] = []
    seen_before_input: list[str] = []

    def recording_input(_prompt: str) -> str:
        seen_before_input.append("\n".join(output))
        return "/exit" if len(seen_before_input) > 1 else first_input

    exit_code = run_repl(
        runtime,
        store,
        input_fn=recording_input,
        write_fn=output.append,
        run_id_factory=lambda: "run-new",
    )

    assert exit_code == 0
    if scenario == "startup":
        # REPL 启动后第一次输入前就显示决策提示。
        assert expected in seen_before_input[0]
    else:
        # 启动时无 pending 不显示；完成 hello 这个 action 后、下一次输入前显示。
        assert expected not in seen_before_input[0]
        assert expected in seen_before_input[1]


def _goal_scoped_approval_state(
    *,
    path: str = "notes/idea.md",
    targets: tuple[str, ...] = ("notes/idea.md", "reports"),
    request_id: str = "approval-internal-id",
    preview: str | None = None,
    admitted_paths: tuple[str, ...] = (),
) -> ConversationState:
    """R4 现场构造：活跃 Goal 的文件写入待审批；path 决定短命令适用范围。

    ``admitted_paths`` 追加 W2 场景的 Runtime 已准入 FILESYSTEM_DIGEST
    criterion（真实链路里由 `_admit_approved_file_criterion` 在用户批准
    写入时铸造；这里只构造同一 durable 状态形状）。
    """

    admitted = tuple(
        AdmittedCriterion(
            criterion_id=f"criterion:approved-write:{index}",
            description="the approved write bound this exact file",
            source_fact_id="user-1",
            oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
            predicate={"path": admitted_path, "sha256": "a" * 64},
            required_evidence_class="workspace_file",
            admission_digest="b" * 64,
        )
        for index, admitted_path in enumerate(admitted_paths)
    )

    goal = GoalFrame(
        goal_id="goal-1",
        revision=1,
        created_from_fact_ids=("user-1",),
        workspace_identity_digest="workspace-1",
        user_outcome="write the requested note and report",
        beneficiary="user",
        targets=targets,
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(ProposedCriterion("criterion-1", "files exist"),),
        admitted_criteria=admitted,
        authority_snapshot="authority-1",
        status=GoalStatus.GOAL_READY,
        created_at="2026-08-02T00:00:00Z",
        updated_at="2026-08-02T00:00:00Z",
    )
    request = ApprovalRequest(
        request_id=request_id,
        run_id="run-1",
        tool_call_id="call-1",
        binding_digest="approval-binding",
        preview=preview or f"write {path} (12 bytes)",
        tool_name="write_file",
        side_effect=SideEffectClass.WRITE.value,
    )
    return replace(
        ConversationState.new("conversation-1"),
        goal=goal,
        active_run=ActiveRun(
            "run-1",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            pending_request=request,
            tool_calls=(ToolCall("call-1", "write_file", {"path": path}),),
        ),
    )


@pytest.mark.parametrize(
    ("command", "authorize_target", "authorize_directory"),
    [
        ("/approve-goal-target", True, False),
        ("/approve-goal-directory", False, True),
    ],
)
def test_goal_scope_short_command_without_id_binds_the_displayed_prompt(
    command: str,
    authorize_target: bool,
    authorize_directory: bool,
) -> None:
    """R4：默认提示不暴露内部 ID；无参数短命令绑定刚显示的同一 pending request。"""

    states = {
        "/approve-goal-target": _goal_scoped_approval_state(),
        # directory 短命令要求写入路径严格位于 Goal 已声明的目录 target 之下。
        "/approve-goal-directory": _goal_scoped_approval_state(
            path="reports/daily/final.md"
        ),
    }
    state = states[command]
    runtime, output, _ = _run(state, command, "/exit")

    assert output[0].startswith("Approval required")
    assert command in output[0]
    action = runtime.actions[0]
    assert isinstance(action, ResolveApproval)
    pending = state.active_run.pending_request
    assert action.request_id == pending.request_id
    assert action.binding_digest == pending.binding_digest
    assert action.approved is True
    assert action.authorize_goal_target is authorize_target
    assert action.authorize_goal_directory is authorize_directory


def test_goal_scope_short_command_rejects_stale_id_without_fallback() -> None:
    """带参数时仍是 exact-ID 合同：错误 ID 拒绝，不回落到无参数绑定。"""

    state = _goal_scoped_approval_state()
    runtime, output, _ = _run(state, "/approve-goal-target approval-wrong", "/exit")

    assert runtime.actions == []
    assert any("exact pending request ID" in item for item in output)


def test_goal_scope_short_command_refuses_non_matching_scope() -> None:
    """范围不适用时无参数短命令拒绝执行，不静默降级为逐笔批准。"""

    state = _goal_scoped_approval_state(path="outside/other.md")
    runtime, output, _ = _run(state, "/approve-goal-target", "/exit")

    assert runtime.actions == []
    assert any("Goal" in item for item in output)
    # 不适用范围的默认提示也不展示该短命令。
    assert "/approve-goal-target" not in output[0]


def test_write_outside_goal_targets_states_no_reusable_scope() -> None:
    """E1-A 透明度：写入不在 Goal targets 内时提示如实说明无复用 scope。"""

    state = _goal_scoped_approval_state(path="outside/other.md")
    _runtime, output, _ = _run(state, "/exit")

    assert "No reusable Goal scope for this write" in output[0]
    assert "covers only this one operation" in output[0]


def test_write_inside_goal_targets_keeps_r4_prompt_without_transparency_note() -> None:
    """scope 适用时保持 R4 原提示；不追加复用不可用说明。"""

    state = _goal_scoped_approval_state()
    _runtime, output, _ = _run(state, "/exit")

    assert "/approve-goal-target" in output[0]
    assert "No reusable Goal scope" not in output[0]


def test_prose_target_write_reuses_runtime_admitted_file_scope() -> None:
    """W2（P2 原场景）：散文 targets 下 Runtime 已准入的当前文件成为精确复用候选。

    targets 是模型草稿的散文目标；notes/idea.md 有当前 Goal 的
    FILESYSTEM_DIGEST admitted criterion（真实链路来自用户首次 y 批准写入）。
    显示、解析与铸造共享同一 scope 判断：默认提示出现短命令，短命令解析为
    authorize_goal_target 的 ResolveApproval。
    """

    state = _goal_scoped_approval_state(
        targets=("实现 SPEC.md 中要求的笔记功能",),
        admitted_paths=("notes/idea.md",),
    )
    runtime, output, _ = _run(state, "/approve-goal-target", "/exit")

    assert output[0].startswith("Approval required")
    assert "/approve-goal-target" in output[0]
    assert "No reusable Goal scope" not in output[0]
    assert len(runtime.actions) == 1
    action = runtime.actions[0]
    assert isinstance(action, ResolveApproval)
    pending = state.active_run.pending_request
    assert action.request_id == pending.request_id
    assert action.binding_digest == pending.binding_digest
    assert action.authorize_goal_target is True
    assert action.authorize_goal_directory is False


def test_prose_target_without_admitted_criterion_stays_single_shot() -> None:
    """散文 targets 且无任何准入绑定时保持原 P2 行为：无复用 scope。"""

    state = _goal_scoped_approval_state(targets=("实现 SPEC.md 中要求的笔记功能",))
    runtime, output, _ = _run(state, "/approve-goal-target", "/exit")

    assert runtime.actions == []
    assert "No reusable Goal scope for this write" in output[0]


@pytest.mark.parametrize(
    "path",
    (
        "notes/idea.md.bak",
        "notes",
        "notes/other.md",
        "other/idea.md",
        ".env",
    ),
)
def test_admitted_file_scope_fails_closed_outside_exact_binding(path: str) -> None:
    """准入候选只对同一路径生效：相邻前缀/父目录/兄弟路径/敏感路径不放行。"""

    state = _goal_scoped_approval_state(
        path=path,
        targets=("实现 SPEC.md 中要求的笔记功能",),
        admitted_paths=("notes/idea.md",),
    )
    runtime, output, _ = _run(state, "/approve-goal-target", "/exit")

    assert runtime.actions == []
    assert "No reusable Goal scope for this write" in output[0]


def test_plain_yes_stays_single_shot_at_goal_scoped_prompt() -> None:
    """短命令在场时 `yes` 语义不变：两 flag 均为 False，只批准这一次操作。"""

    state = _goal_scoped_approval_state()
    runtime, output, _ = _run(state, "yes", "/exit")

    assert "yes approves only this one operation" in output[0]
    action = runtime.actions[0]
    assert isinstance(action, ResolveApproval)
    assert action.approved is True
    assert action.authorize_goal_target is False
    assert action.authorize_goal_directory is False


def test_scope_short_command_binds_displayed_snapshot_under_drift(
    tmp_path: Path,
) -> None:
    """显示 A 之后、输入返回前 store 漂移到 B：无参数短命令仍只绑 A，不重绑 B。"""

    state_a = _goal_scoped_approval_state(
        request_id="approval-a", preview="write notes/idea.md (12 bytes)"
    )
    store = _local_store(tmp_path, state_a)
    state_b = _goal_scoped_approval_state(
        request_id="approval-b", preview="write notes/other.md (3 bytes)"
    )
    state_b = replace(state_b, revision=state_a.revision + 1)
    runtime = RecordingRuntime()
    output: list[str] = []
    seen_before_input: list[str] = []

    def racing_input(_prompt: str) -> str:
        seen_before_input.append("\n".join(output))
        if len(seen_before_input) == 1:
            lease = store.try_acquire(state_a.conversation_id)
            assert lease is not None
            try:
                store.compare_and_swap(store.load(), state_b)
            finally:
                lease.release()
            return "/approve-goal-target"
        return "/exit"

    exit_code = run_repl(
        runtime,
        store,
        input_fn=racing_input,
        write_fn=output.append,
        run_id_factory=lambda: "run-new",
    )

    assert exit_code == 0
    # 所见：输入前终端显示的是 A 的短命令提示，不是漂移后 B 的。
    assert "write notes/idea.md" in seen_before_input[0]
    assert "write notes/other.md" not in seen_before_input[0]
    # 所批：action 与 snapshot 都绑定显示时的 A，绝不重绑到 B。
    action = runtime.actions[0]
    assert isinstance(action, ResolveApproval)
    assert action.request_id == "approval-a"
    assert action.authorize_goal_target is True
    assert runtime.snapshots[0].state.revision == state_a.revision


def test_no_argument_scope_command_reaches_real_runtime_and_reuses_scope() -> None:
    """R4 验收链：默认提示 → 无参数命令 → 真实 Runtime 铸授权并同目标复用。"""

    from agent.runtime.context import ContextLimits, KernelContextManager
    from agent.runtime.contracts import (
        ApprovalPolicy,
        ExecutionAuthorityClass,
        ModelResponse,
        ModelToolCall,
        OutputPolicy,
        ToolRisk,
        ToolSpec,
    )
    from agent.runtime.loop import AgentRuntime, InvocationLimits, RetryableProviderError
    from agent.runtime.tools import KernelToolRuntime, RegisteredTool
    from tests.kernel.fakes import (
        CollectingSink,
        InMemoryCheckpointStore,
        ScriptedProvider,
        conversation_with_active_goal,
        goal_noop_response,
    )

    calls: list[str] = []
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="write_file",
        version="1",
        description="Write an exact workspace fixture",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={"workspace_scoped": True},
        output_limit_chars=50,
    )
    provider = ScriptedProvider(
        goal_noop_response("r4-cli-consent-user-supplement"),
        ModelResponse(
            (
                ModelToolCall(
                    "write-1", "write_file", {"path": "note.txt", "content": "one"}
                ),
            )
        ),
        ModelResponse(
            (
                ModelToolCall(
                    "write-2", "write_file", {"path": "note.txt", "content": "two"}
                ),
            )
        ),
        RetryableProviderError("stop after both writes"),
    )
    initial = conversation_with_active_goal()
    assert initial.goal is not None
    initial = replace(initial, goal=replace(initial.goal, targets=("note.txt",)))
    store = InMemoryCheckpointStore(initial)
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(
            (
                RegisteredTool(
                    spec,
                    lambda intent: calls.append(intent.arguments["content"])
                    or "written",
                    prepare_binding=lambda arguments: {
                        "effect_preview": f"write {arguments['path']}",
                    },
                ),
            ),
            clock=lambda: "2026-09-04T00:30:00Z",
        ),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-r4-cli-consent",
    )
    paused = runtime.run_turn(
        SubmitMessage(
            conversation_id=initial.conversation_id,
            action_seq=initial.next_action_seq,
            expected_revision=initial.revision,
            run_id="run-r4-cli-consent",
            message="write the requested target",
        ),
        store.load(),
    )
    assert paused.status is RunStatus.AWAITING_APPROVAL
    assert paused.request is not None

    output: list[str] = []
    values = iter(("/approve-goal-target", "/exit"))
    exit_code = run_repl(
        runtime,
        store,
        input_fn=lambda _: next(values),
        write_fn=output.append,
        run_id_factory=lambda: "run-r4-cli-consent",
        approval_time_factory=lambda: "2026-09-04T00:00:00Z",
    )

    assert exit_code == 0
    prompt = next(item for item in output if "Approval required" in item)
    assert "/approve-goal-target" in prompt
    assert paused.request.request_id not in prompt
    # 真实 Runtime：无参数命令精确绑定刚显示的 request（授权 source_id 即其
    # request_id），第二次同目标写入复用授权，无第二次审批暂停。
    assert calls == ["one", "two"]
    assert len(store.state.goal_authorizations) == 1
    binding = store.state.goal_authorizations[0]
    assert binding.source_id == paused.request.request_id
    assert binding.normalized_target == "note.txt"
    assert binding.uses_consumed == 2
    assert binding.remaining_uses == 14
