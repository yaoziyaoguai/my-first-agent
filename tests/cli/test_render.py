from __future__ import annotations

import re
from dataclasses import replace

from agent.cli.render import TerminalRenderer
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    ApprovalRequest,
    ArtifactConfirmationRequirementV1,
    ContinuationPhase,
    ConversationState,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    ProcessAuthorityCandidateV1,
    ProviderDisclosureRequest,
    RecoveryRequest,
    RunResult,
    RunStatus,
    RuntimeEvent,
    RuntimeEventKind,
    ToolCall,
)


def _event(kind: RuntimeEventKind, *, event_id: str = "event-1", payload=None):
    return RuntimeEvent(
        event_id=event_id,
        kind=kind,
        conversation_id="conversation-1",
        run_id="run-1",
        revision=3,
        causation_id="action:1",
        payload=payload or {},
    )


def test_pending_events_render_no_second_actionable_prompt() -> None:
    """pending 类 advisory event 不是可操作提示权威；render_pending 才是。"""

    output: list[str] = []
    renderer = TerminalRenderer(output.append)
    renderer.emit(
        _event(
            RuntimeEventKind.APPROVAL_REQUESTED,
            payload={
                "request_id": "approval-full-id",
                "tool_call_id": "call-1",
                "tool_name": "write_file",
                "preview": "write note.txt (5 bytes)",
                "risk": "high",
                "side_effect": "write",
            },
        )
    )
    renderer.emit(
        _event(
            RuntimeEventKind.DISCLOSURE_REQUESTED,
            event_id="disclosure",
            payload={
                "request_digest": "internal-disclosure-digest",
                "destination": "https://provider.example/v1",
                "model": "daily-model",
                "data_classes": ["user_message"],
            },
        )
    )
    renderer.emit(
        _event(
            RuntimeEventKind.RECOVERY_REQUESTED,
            event_id="recovery",
            payload={
                "request_id": "internal-recovery-id",
                "summary": "the previous write may have completed",
            },
        )
    )

    assert output == []

    # warning/informational 事件仍保留，去重仍生效。
    warning = _event(
        RuntimeEventKind.WARNING,
        event_id="warning-1",
        payload={"message": "delivery degraded"},
    )
    renderer.emit(warning)
    renderer.emit(warning)
    assert output == ["Warning: delivery degraded"]


def test_run_result_owns_final_text_and_terminal_status() -> None:
    output: list[str] = []
    renderer = TerminalRenderer(output.append)
    state = ConversationState.new("conversation-1")

    renderer.emit(_event(RuntimeEventKind.COMPLETED))
    renderer.render_result(
        RunResult(RunStatus.COMPLETED, state, run_id="run-1", message="final answer")
    )

    assert output == ["final answer"]


def test_conflict_and_retryable_results_give_operator_guidance() -> None:
    output: list[str] = []
    renderer = TerminalRenderer(output.append)
    state = ConversationState.new("conversation-1")

    renderer.render_result(RunResult(RunStatus.CONFLICT, state, error_code="revision"))
    renderer.render_result(RunResult(RunStatus.FAILED_RETRYABLE, state))

    assert "restart" in output[0].lower() or "reload" in output[0].lower()
    assert "/resume" in output[1]


def test_limit_result_names_the_exact_recovery_action() -> None:
    output: list[str] = []
    renderer = TerminalRenderer(output.append)

    renderer.render_result(
        RunResult(RunStatus.LIMIT_REACHED, ConversationState.new("conversation-1"))
    )

    assert output == [
        "Task paused at a safe execution limit. Run /resume to continue or /cancel."
    ]


def test_renderer_escapes_terminal_control_characters_in_event_fields() -> None:
    # pending 事件已静音，转义覆盖改用仍会输出的 WARNING 载体；
    # terminal_text 本身的合同（非 printable → \\uXXXX）不变。
    output: list[str] = []
    renderer = TerminalRenderer(output.append)
    renderer.emit(
        _event(
            RuntimeEventKind.WARNING,
            event_id="event-unsafe",
            payload={"message": "write note\n\x1b[2J.txt"},
        )
    )

    assert len(output) == 1
    assert "\x1b" not in output[0]
    assert "\\u000a" in output[0]
    assert "\\u001b" in output[0]


def test_default_renderer_hides_model_and_tool_progress_noise() -> None:
    output: list[str] = []
    renderer = TerminalRenderer(output.append)

    renderer.emit(_event(RuntimeEventKind.MODEL_PROGRESS, event_id="model-progress"))
    renderer.emit(
        _event(
            RuntimeEventKind.TOOL_REQUESTED,
            event_id="tool-requested",
            payload={"tool_name": "list_files"},
        )
    )
    renderer.emit(
        _event(
            RuntimeEventKind.TOOL_RESULT,
            event_id="tool-result",
            payload={"tool_call_id": "internal-call-id"},
        )
    )

    assert output == []


def test_render_pending_owns_contextual_prompts_without_protocol_ids() -> None:
    """可操作提示由 authoritative state 的 render_pending 投影，不暴露内部 identity。"""

    output: list[str] = []
    renderer = TerminalRenderer(output.append)

    renderer.render_pending(_disclosure_pending_state())
    renderer.render_pending(_recovery_pending_state())

    rendered = "\n".join(output)
    assert "https://provider.example/v1" in rendered
    assert "daily-model" in rendered
    assert "[y/N]" in rendered
    assert "success" in rendered and "failed" in rendered and "stop" in rendered
    assert "internal-disclosure-digest" not in rendered
    assert "internal-recovery-id" not in rendered
    assert "/ack-provider" not in rendered


def test_render_pending_artifact_approval_shows_exact_special_command() -> None:
    """artifact approval 不显示通用 [y/N]；只展示精确 special command 与实际 path。"""

    output: list[str] = []
    renderer = TerminalRenderer(output.append)

    renderer.render_pending(_artifact_approval_pending_state())

    prompt = output[0]
    assert "/approve-artifact <64-lowercase-hex-sha256> artifact.out" in prompt
    assert "artifact.out" in prompt
    assert "[y/N]" not in prompt
    # 不自动填 digest：提示里不得出现 64 位 hex。
    assert re.search(r"[0-9a-f]{64}", prompt) is None
    # 明确 no 可拒绝。
    assert "reject" in prompt.lower()


def test_fatal_result_carries_bounded_exception_summary() -> None:
    # 016 真实 E3 第 19/24 轮 J8:runtime_failure 的异常细节在 RunResult.message
    # 里,但渲染只打 error_code,产品缺口无法定诊(REPL 退出码 1 且无 traceback)。
    # FAILED_FATAL 渲染必须携带 bounded 的异常摘要。
    output: list[str] = []
    renderer = TerminalRenderer(output.append)
    state = ConversationState.new("conversation-1")

    renderer.render_result(
        RunResult(
            RunStatus.FAILED_FATAL,
            state,
            error_code="runtime_failure",
            message="CheckpointConflictError: revision 7 != 6 at checkpoint append",
        )
    )
    renderer.render_result(
        RunResult(
            RunStatus.FAILED_FATAL,
            state,
            error_code="runtime_failure",
            message=" ".join(["detail"] * 2000),
        )
    )

    assert "Run failed: runtime_failure" in output[0]
    assert "CheckpointConflictError" in output[0]
    assert "revision 7 != 6" in output[0]
    assert len(output[1]) < 400


def _disclosure_pending_state() -> ConversationState:
    request = ProviderDisclosureRequest.create(
        disclosure_id="disclosure-1",
        provider_descriptor_digest="descriptor-1",
        canonical_destination="https://provider.example/v1",
        model="daily-model",
        data_classes=("user_message",),
    )
    return replace(
        ConversationState.new("conversation-1"),
        active_run=ActiveRun("run-1", status=ActiveRunStatus.AWAITING_DISCLOSURE),
        provider_disclosure_request=request,
    )


def _recovery_pending_state() -> ConversationState:
    request = RecoveryRequest(
        request_id="internal-recovery-id",
        run_id="run-1",
        tool_call_id="call-1",
        binding_digest="recovery-binding",
        summary="the previous write may have completed",
    )
    return replace(
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


def _artifact_approval_pending_state() -> ConversationState:
    candidate = ProcessAuthorityCandidateV1.create(
        candidate_id="candidate-artifact",
        goal_id="goal-artifact",
        goal_revision=1,
        workspace_identity_digest="workspace-artifact",
        command_fingerprint="f" * 64,
        readable_command="./writer artifact.out",
        executable_digest="e" * 64,
        argv_digest="v" * 64,
        cwd_digest="d" * 64,
        resource_profile="short",
        environment_policy_digest="p" * 64,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        trust_notice_digest="t" * 64,
        issued_at="2026-09-08T00:00:00Z",
    )
    request = ApprovalRequest(
        request_id="approval-artifact",
        run_id="run-1",
        tool_call_id="call-1",
        binding_digest="approval-binding",
        preview="run ./writer artifact.out",
        tool_name="local_process",
        process_authority_candidate=candidate,
        artifact_confirmation_requirement=ArtifactConfirmationRequirementV1(
            criterion_id="criterion-artifact",
            artifact_path="artifact.out",
        ),
    )
    return replace(
        ConversationState.new("conversation-1"),
        active_run=ActiveRun(
            "run-1",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            pending_request=request,
            tool_calls=(ToolCall("call-1", "local_process", {}),),
        ),
    )


def test_model_text_delta_streams_and_dedupes_final_message() -> None:
    """r19 小步 3:delta 经专用无换行通道实时呈现;最终权威 message 与已流式
    文本完全一致时不重复打印;重复 event_id 的增量只呈现一次(丢失/重复不改
    权威,显示可由权威结果校正)。"""
    deltas: list[str] = []
    renderer = TerminalRenderer(
        lambda message: None, delta_write_fn=deltas.append
    )
    renderer.emit(
        _event(RuntimeEventKind.MODEL_TEXT_DELTA, event_id="delta-1", payload={"text": "Hel"})
    )
    renderer.emit(
        _event(RuntimeEventKind.MODEL_TEXT_DELTA, event_id="delta-2", payload={"text": "lo"})
    )
    # 同 event_id 的重复增量被去重。
    renderer.emit(
        _event(RuntimeEventKind.MODEL_TEXT_DELTA, event_id="delta-2", payload={"text": "lo"})
    )
    assert deltas == ["Hel", "lo"]

    completed = replace(
        RunResult(RunStatus.COMPLETED, ConversationState.new("conversation-1")),
        message="Hello",
    )
    assert renderer._result_message(completed) is None  # noqa: SLF001
    other = replace(
        RunResult(RunStatus.COMPLETED, ConversationState.new("conversation-1")),
        message="Corrected final text",
    )
    assert renderer._result_message(other) == "Corrected final text"  # noqa: SLF001
