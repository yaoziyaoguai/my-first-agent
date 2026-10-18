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
    GoalFrame,
    GoalStatus,
    ProcessAuthorityCandidateV1,
    ProposedCriterion,
    ProviderDisclosureReceipt,
    ProviderDisclosureRequest,
    RecoveryRequest,
    RunResult,
    RunStatus,
    RuntimeEvent,
    RuntimeEventKind,
    SideEffectClass,
    ToolCall,
)
from tests.kernel.fakes import conversation_with_terminal_goal


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


def test_verification_scope_message_does_not_overclaim_semantic_correctness() -> None:
    message = TerminalRenderer._verification_scope_message(  # noqa: SLF001
        (
            "exact current bytes of report.csv",
            "approved local process exited with code 0",
        )
    )

    assert "exact current bytes of report.csv" in message
    assert "approved local process exited with code 0" in message
    assert "does not independently establish numerical or semantic correctness" in message


def test_completed_goal_renders_authoritative_verification_scope() -> None:
    output: list[str] = []
    renderer = TerminalRenderer(output.append)

    renderer.render_result(
        RunResult(
            RunStatus.COMPLETED,
            conversation_with_terminal_goal(GoalStatus.VERIFIED_DONE),
            message="The report is ready.",
        )
    )

    assert output[0] == "The report is ready."
    assert "Verified delivery:" in output[1]
    assert "Targets: workspace" in output[1]
    assert "Required evidence: 1/1 passed" in output[1]
    assert "Durable task permissions: closed." in output[1]
    assert "User acceptance: not established by these evidence checks." in output[1]
    assert "Evidence scope: exact current bytes of reports/final.md" in output[-2]
    assert "does not independently establish numerical or semantic correctness" in output[-2]
    assert output[-1] == "Task is closed. Use /new to start another task in this workspace."


def test_terminal_goal_points_to_new_once_without_changing_goal_state() -> None:
    output: list[str] = []
    renderer = TerminalRenderer(output.append)
    state = conversation_with_terminal_goal(GoalStatus.CANCELLED)
    result = RunResult(RunStatus.CANCELLED, state)

    renderer.render_result(result)
    renderer.render_result(result)

    assert output == [
        "Run cancelled.",
        "Task is closed. Use /new to start another task in this workspace.",
        "Run cancelled.",
    ]


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


def test_budget_exhausted_limit_names_the_real_continuation_path() -> None:
    """E1-A 真实旅程回归：预算耗尽后的 /resume 不可能再派发，提示必须指明
    同 ledger 提高 --max-model-attempts 的真实继续路径，而不是误导性 /resume。"""

    output: list[str] = []
    renderer = TerminalRenderer(output.append)

    renderer.render_result(
        RunResult(
            RunStatus.LIMIT_REACHED,
            ConversationState.new("conversation-1"),
            error_code="model_attempt_budget_exhausted",
        )
    )

    assert "/resume cannot send new model requests" in output[0]
    assert "--max-model-attempts" in output[0]
    assert "--transport-audit-ledger" in output[0]


def test_auth_failure_names_configured_credential_env() -> None:
    """B2 回归：401 恢复提示点名 profile 配置的环境变量名（不含 value）；
    未提供（fake/测试）时保持通用文案。"""

    with_env: list[str] = []
    TerminalRenderer(with_env.append, credential_env="DEEPSEEK_API_KEY").render_result(
        RunResult(
            RunStatus.FAILED_FATAL,
            ConversationState.new("conversation-1"),
            error_code="provider_auth_error",
        )
    )
    assert "DEEPSEEK_API_KEY" in with_env[0]
    assert "in this shell" in with_env[0]

    without_env: list[str] = []
    TerminalRenderer(without_env.append).render_result(
        RunResult(
            RunStatus.FAILED_FATAL,
            ConversationState.new("conversation-1"),
            error_code="provider_auth_error",
        )
    )
    assert without_env[0] == (
        "Provider authentication failed. Check the configured credential "
        "and run first-agent again."
    )


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


def test_renderer_shows_only_real_slow_provider_waiting_heartbeat() -> None:
    output: list[str] = []
    renderer = TerminalRenderer(output.append)

    renderer.emit(
        _event(
            RuntimeEventKind.MODEL_PROGRESS,
            event_id="model-waiting",
            payload={"phase": "provider_waiting", "elapsed_seconds": 15.0},
        )
    )

    assert output == ["Model is still working (15.0s elapsed)..."]


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


def _resumed_disclosure_pending_state(status: GoalStatus) -> ConversationState:
    """E1-B 缺口形态（2026-10-17）：/pause 停掉 active run 后挂起披露仍 durable。"""
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
        status=status,
        created_at="2026-10-17T00:00:00Z",
        updated_at="2026-10-17T00:00:00Z",
    )
    return replace(
        ConversationState.new("conversation-1"),
        goal=goal,
        provider_disclosure_request=request,
    )


def test_render_pending_re_raises_disclosure_only_after_goal_resume() -> None:
    """/resume 完成后必须重升挂起披露（等价审批的重升语义）；Goal 仍 PAUSED
    时不升——先 /resume 才可应答，避免暂停窗口里的误导提示。"""

    resumed: list[str] = []
    TerminalRenderer(resumed.append).render_pending(
        _resumed_disclosure_pending_state(GoalStatus.GOAL_READY)
    )
    assert any(
        line.startswith("Remote provider disclosure required") for line in resumed
    )

    paused: list[str] = []
    TerminalRenderer(paused.append).render_pending(
        _resumed_disclosure_pending_state(GoalStatus.PAUSED)
    )
    assert paused == []


def test_release_b_render_uses_one_predicate_for_both_pending_shapes() -> None:
    """B（2026-10-18）：render_pending 与 y/n/空回车共用同一只读 pending 判定——
    已 receipt 的活跃形状不再是 answerable pending，不得渲染 [y/N] 提示。"""

    request = ProviderDisclosureRequest.create(
        disclosure_id="disclosure-1",
        provider_descriptor_digest="descriptor-1",
        canonical_destination="https://provider.example/v1",
        model="daily-model",
        data_classes=("user_message",),
    )
    state = replace(
        _disclosure_pending_state(),
        provider_disclosure_receipt=ProviderDisclosureReceipt(
            receipt_id="receipt-1",
            request_digest=request.request_digest,
            acknowledged_action_seq=1,
            acknowledged_at="2026-10-18T00:00:00Z",
        ),
    )
    output: list[str] = []

    TerminalRenderer(output.append).render_pending(state)

    assert output == []


def test_render_pending_artifact_generation_defers_content_confirmation() -> None:
    """未来产物先批准生成；提示不得让普通用户猜或手抄摘要。"""

    output: list[str] = []
    renderer = TerminalRenderer(output.append)

    renderer.render_pending(_artifact_approval_pending_state())

    prompt = output[0]
    assert "artifact.out" in prompt
    assert "[y/N]" in prompt
    assert "separate confirmation" in prompt
    assert "/approve-artifact" not in prompt
    assert re.search(r"[0-9a-f]{64}", prompt) is None


def test_render_pending_confirm_file_shows_readable_literal_content() -> None:
    output: list[str] = []
    renderer = TerminalRenderer(output.append)
    request = ApprovalRequest(
        request_id="approval-confirm",
        run_id="run-1",
        tool_call_id="confirm-1",
        binding_digest="binding-confirm",
        preview=(
            "confirm current content of report.txt:\n"
            "--- begin current content ---\n"
            "count=12\nerrors=3\x1b[2J\n"
            "--- end current content ---"
        ),
        tool_name="confirm_file",
    )
    state = replace(
        ConversationState.new("conversation-1"),
        active_run=ActiveRun(
            "run-1",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            pending_request=request,
            tool_calls=(ToolCall("confirm-1", "confirm_file", {"path": "report.txt"}),),
        ),
    )

    renderer.render_pending(state)

    prompt = output[0]
    assert "count=12\nerrors=3" in prompt
    assert "\x1b" not in prompt
    assert "\\u001b[2J" in prompt
    assert "[y/N]" in prompt
    assert "sha256" not in prompt.lower()


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


def test_model_text_delta_uses_literal_terminal_display_without_changing_final_text() -> None:
    """流式通道与最终回答共用 literal display；显示转义不能污染权威原文去重。"""

    output: list[str] = []
    deltas: list[str] = []
    renderer = TerminalRenderer(output.append, delta_write_fn=deltas.append)
    raw = "safe\x1b[2J\ntext\u202ereversed"

    renderer.emit(
        _event(
            RuntimeEventKind.MODEL_TEXT_DELTA,
            event_id="delta-unsafe",
            payload={"text": raw},
        )
    )
    renderer.render_result(
        RunResult(
            RunStatus.COMPLETED,
            ConversationState.new("conversation-1"),
            run_id="run-1",
            message=raw,
        )
    )

    assert deltas == ["safe\\u001b[2J\ntext\\u202ereversed"]
    assert output == []


def test_model_text_delta_deduplication_is_scoped_to_one_rendered_result() -> None:
    """同一 REPL renderer 连续处理回答时，每轮只与该轮流式原文比较。"""

    output: list[str] = []
    deltas: list[str] = []
    renderer = TerminalRenderer(output.append, delta_write_fn=deltas.append)

    for index, answer in enumerate(("first answer", "second answer"), start=1):
        renderer.emit(
            _event(
                RuntimeEventKind.MODEL_TEXT_DELTA,
                event_id=f"delta-{index}",
                payload={"text": answer},
            )
        )
        renderer.render_result(
            RunResult(
                RunStatus.COMPLETED,
                ConversationState.new("conversation-1"),
                run_id=f"run-{index}",
                message=answer,
            )
        )

    assert deltas == ["first answer", "second answer"]
    assert output == []


def test_model_text_delta_deduplication_tracks_the_latest_provider_response() -> None:
    """一次 action 内多次模型响应时，最终回答只与最后一个响应去重。"""

    output: list[str] = []
    deltas: list[str] = []
    renderer = TerminalRenderer(output.append, delta_write_fn=deltas.append)
    first_response = replace(
        _event(
            RuntimeEventKind.MODEL_TEXT_DELTA,
            event_id="delta-response-1",
            payload={"text": "I will inspect the file."},
        ),
        revision=3,
        causation_id="model-delta:run-1:3",
    )
    final_response = replace(
        _event(
            RuntimeEventKind.MODEL_TEXT_DELTA,
            event_id="delta-response-2",
            payload={"text": "The file is valid."},
        ),
        revision=4,
        causation_id="model-delta:run-1:4",
    )

    renderer.emit(first_response)
    renderer.emit(final_response)
    renderer.render_result(
        RunResult(
            RunStatus.COMPLETED,
            ConversationState.new("conversation-1"),
            run_id="run-1",
            message="The file is valid.",
        )
    )

    assert deltas == ["I will inspect the file.", "The file is valid."]
    assert output == []


def _goal_scoped_approval_state(
    *,
    path: str = "notes/idea.md",
    targets: tuple[str, ...] = ("notes", "notes/idea.md"),
) -> ConversationState:
    """R4 现场构造：活跃 Goal 声明目录与精确文件 target 的待审批 write。"""

    goal = GoalFrame(
        goal_id="goal-1",
        revision=1,
        created_from_fact_ids=("user-1",),
        workspace_identity_digest="workspace-1",
        user_outcome="write the requested note under notes",
        beneficiary="user",
        targets=targets,
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(ProposedCriterion("criterion-1", "note exists"),),
        admitted_criteria=(),
        authority_snapshot="authority-1",
        status=GoalStatus.GOAL_READY,
        created_at="2026-08-02T00:00:00Z",
        updated_at="2026-08-02T00:00:00Z",
    )
    request = ApprovalRequest(
        request_id="approval-scoped-internal-id",
        run_id="run-1",
        tool_call_id="call-1",
        binding_digest="approval-binding",
        preview=f"write {path} (12 bytes)",
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


def test_render_pending_shows_scoped_short_commands_with_accurate_bounds() -> None:
    """R4：文件审批默认提示展示无参数范围授权短命令与准确边界，不暴露内部 ID。"""

    output: list[str] = []
    renderer = TerminalRenderer(output.append)

    renderer.render_pending(_goal_scoped_approval_state())

    prompt = output[0]
    assert "[y/N]" in prompt
    assert "/approve-goal-target" in prompt
    assert "/approve-goal-directory" in prompt
    # 精确范围：target 命令只提该文件；directory 命令只提 Goal 已声明的目录。
    assert "notes/idea.md" in prompt
    assert "notes" in prompt
    # 有限次数/时效与可撤销；yes 仍只批准一次。
    assert "16" in prompt and "60 minutes" in prompt
    assert "/revoke-goal-target" in prompt
    assert "yes approves only this one operation" in prompt
    # 不暴露内部 request identity 或 digest。
    assert "approval-scoped-internal-id" not in prompt
    assert re.search(r"[0-9a-f]{64}", prompt) is None


def test_render_pending_hides_short_commands_without_matching_goal_scope() -> None:
    """范围不适用（写入路径不在 Goal targets 之下）时默认提示不展示短命令。"""

    output: list[str] = []
    renderer = TerminalRenderer(output.append)

    renderer.render_pending(_goal_scoped_approval_state(path="outside/other.md"))

    prompt = output[0]
    assert "[y/N]" in prompt
    assert "/approve-goal-target" not in prompt
    assert "/approve-goal-directory" not in prompt
