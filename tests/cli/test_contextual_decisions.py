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
    ExecutingIntentRecord,
    LoadedSnapshot,
    ProviderDisclosureRequest,
    RecoveryRequest,
    RecoveryResolution,
    ResolveApproval,
    ResolveUnknownToolOutcome,
    RunResult,
    RunStatus,
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

    def run_turn(self, action, snapshot):  # noqa: ANN001
        self.actions.append(action)
        return RunResult(RunStatus.COMPLETED, snapshot.state)


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
                tool_call_id="call-1",
                intent_digest="recovery-binding",
                idempotency_key="idempotency-1",
            ),
            tool_calls=(ToolCall("call-1", "write_file", {}),),
        ),
    )
    return state, request


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
    assert output == ["Nothing was sent."]


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
    assert output == ["Stopped without classifying or retrying the previous operation."]


def test_ambiguous_yes_does_not_classify_unknown_outcome() -> None:
    runtime, output, _ = _run(_recovery_state()[0], "yes", "/exit")

    assert runtime.actions == []
    assert any("success" in message.lower() and "failed" in message.lower() for message in output)


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
    pending = replace(pending, conversation_id=opened.snapshot.state.conversation_id)
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
