from __future__ import annotations

from dataclasses import replace

from agent.cli.app import run_repl
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    ApprovalRequest,
    CancelGoal,
    ContinuationPhase,
    ConversationState,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    GoalStatus,
    LoadedSnapshot,
    PauseGoal,
    RecoveryRequest,
    RecoveryResolution,
    ResolveApproval,
    ResolveUnknownToolOutcome,
    Resume,
    ResumeGoal,
    RunResult,
    RunStatus,
    ToolCall,
)
from tests.kernel.fakes import conversation_with_active_goal


class StaticStore:
    def __init__(self, state: ConversationState) -> None:
        self.state = state

    def load(self) -> LoadedSnapshot:
        return LoadedSnapshot(self.state, "token-1")


class RecordingRuntime:
    def __init__(self) -> None:
        self.actions = []

    def run_turn(self, action, snapshot):
        self.actions.append(action)
        return RunResult(RunStatus.COMPLETED, snapshot.state)


def _run_once(state: ConversationState, raw: str):
    runtime = RecordingRuntime()
    inputs = iter((raw, "/exit"))
    output: list[str] = []
    exit_code = run_repl(
        runtime,
        StaticStore(state),
        input_fn=lambda _: next(inputs),
        write_fn=output.append,
        run_id_factory=lambda: "run-new",
    )
    return runtime, output, exit_code


def test_approval_commands_require_the_exact_pending_id() -> None:
    request = ApprovalRequest(
        request_id="approval-full-id",
        run_id="run-1",
        tool_call_id="call-1",
        binding_digest="binding-1",
        preview="write note.txt (5 bytes)",
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

    wrong_runtime, wrong_output, _ = _run_once(state, "/approve approval")
    assert wrong_runtime.actions == []
    assert any("exact pending request ID" in item for item in wrong_output)

    runtime, _, exit_code = _run_once(state, "/reject approval-full-id")
    assert exit_code == 0
    assert len(runtime.actions) == 1
    action = runtime.actions[0]
    assert isinstance(action, ResolveApproval)
    assert action.request_id == request.request_id
    assert action.binding_digest == request.binding_digest
    assert action.approved is False


def test_recovery_and_resume_commands_map_to_typed_actions() -> None:
    request = RecoveryRequest(
        request_id="recovery-full-id",
        run_id="run-1",
        tool_call_id="call-1",
        binding_digest="binding-1",
        summary="unknown outcome",
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
                intent_digest="binding-1",
                idempotency_key="key-1",
            ),
            tool_calls=(ToolCall("call-1", "write_file", {}),),
        ),
    )

    runtime, _, _ = _run_once(state, "/resolve-success recovery-full-id")
    action = runtime.actions[0]
    assert isinstance(action, ResolveUnknownToolOutcome)
    assert action.resolution is RecoveryResolution.MARK_SUCCEEDED

    runtime, _, _ = _run_once(state, "/resume")
    assert isinstance(runtime.actions[0], Resume)


def test_normal_text_is_rejected_while_a_run_is_paused() -> None:
    state = replace(
        ConversationState.new("conversation-1"),
        active_run=ActiveRun("run-1", status=ActiveRunStatus.PAUSED_RETRYABLE),
    )

    runtime, output, _ = _run_once(state, "ordinary text")

    assert runtime.actions == []
    assert any("paused" in item.lower() for item in output)


def test_exit_eof_and_idle_interrupt_never_submit_cancel() -> None:
    state = replace(
        ConversationState.new("conversation-1"),
        active_run=ActiveRun("run-1", status=ActiveRunStatus.PAUSED_RETRYABLE),
    )
    for terminal in ("exit", "eof", "interrupt"):
        runtime = RecordingRuntime()

        def terminal_input(_prompt: str, *, terminal_kind: str = terminal) -> str:
            if terminal_kind == "exit":
                return "/exit"
            if terminal_kind == "eof":
                raise EOFError
            raise KeyboardInterrupt

        assert run_repl(runtime, StaticStore(state), input_fn=terminal_input) == 0
        assert runtime.actions == []


def test_goal_controls_map_to_exact_typed_actions() -> None:
    ready = conversation_with_active_goal()
    runtime, _, _ = _run_once(ready, "/pause")
    assert isinstance(runtime.actions[0], PauseGoal)
    assert runtime.actions[0].goal_revision == ready.goal.revision

    paused = replace(ready, goal=replace(ready.goal, status=GoalStatus.PAUSED))
    runtime, _, _ = _run_once(paused, "/resume")
    assert isinstance(runtime.actions[0], ResumeGoal)

    runtime, _, _ = _run_once(ready, "/cancel")
    assert isinstance(runtime.actions[0], CancelGoal)
