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
    ApprovalRequest,
    ContinuationPhase,
    ConversationState,
    EgressClass,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    LoadedSnapshot,
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
    # 输入前显示的是 disclosure 决策提示；退出消息是最后一行且未伪造任何发送。
    assert output[0].startswith("Remote provider disclosure required")
    assert output[-1] == "Nothing was sent."


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
