from __future__ import annotations

from dataclasses import replace

from agent.cli.app import run_repl
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    ApprovalRequest,
    AuthoritySourceKind,
    BrowserTakeoverRequestV1,
    CancelBrowserTakeover,
    CancelGoal,
    CompleteBrowserTakeover,
    ContinuationPhase,
    ConversationState,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    GoalAuthorizationBinding,
    GoalStatus,
    LoadedSnapshot,
    PauseGoal,
    RecoveryRequest,
    RecoveryResolution,
    ResolveApproval,
    ResolveUnknownToolOutcome,
    Resume,
    ResumeGoal,
    RevokeGoalTargetAuthority,
    RunResult,
    RunStatus,
    SubmitMessage,
    ToolCall,
)
from agent.runtime.state import begin_browser_takeover
from tests.kernel.fakes import conversation_with_active_goal, conversation_with_terminal_goal


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


class InterruptingRuntime:
    def run_turn(self, action, snapshot):  # noqa: ANN001, ARG002
        raise KeyboardInterrupt


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

    # 2026-10-21 consent-ux W3/S2：Goal 不存在时没有可复用 scope，显式 ID 的
    # scoped 审批也必须明确拒绝且零 action（N1：不适用范围不展示且不接受），
    # 不再回退到旧的"带 ID 即铸造"宽松语义。
    scoped_runtime, scoped_output, _ = _run_once(
        state,
        "/approve-goal-target approval-full-id",
    )
    assert scoped_runtime.actions == []
    assert any("no matching Goal scope" in item for item in scoped_output)

    directory_runtime, directory_output, _ = _run_once(
        state,
        "/approve-goal-directory approval-full-id",
    )
    assert directory_runtime.actions == []
    assert any("no matching Goal scope" in item for item in directory_output)


def test_revoke_goal_target_command_maps_to_typed_action() -> None:
    state = conversation_with_active_goal()
    assert state.goal is not None
    binding = GoalAuthorizationBinding.create(
        binding_id="goal-target-authority:one",
        goal_id=state.goal.goal_id,
        goal_revision=state.goal.revision,
        workspace_identity_digest=state.goal.workspace_identity_digest,
        operation="write_file",
        normalized_target="note.txt",
        source_kind=AuthoritySourceKind.HUMAN_APPROVAL,
        source_id="approval-one",
        source_digest="action-one",
        issued_at="2026-09-04T00:00:00Z",
        expires_at="2026-09-04T01:00:00Z",
    )
    state = replace(state, goal_authorizations=(binding,))

    runtime, _, _ = _run_once(state, "/revoke-goal-target")

    assert isinstance(runtime.actions[0], RevokeGoalTargetAuthority)


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


def test_cli_terminal_follow_up_uses_existing_snapshot_bound_submit() -> None:
    state = conversation_with_terminal_goal(GoalStatus.VERIFIED_DONE)

    runtime, _, exit_code = _run_once(state, "Explain the completed result.")

    assert exit_code == 0
    assert len(runtime.actions) == 1
    action = runtime.actions[0]
    assert isinstance(action, SubmitMessage)
    assert action.conversation_id == state.conversation_id
    assert action.action_seq == state.next_action_seq
    assert action.expected_revision == state.revision
    assert action.run_id == "run-new"
    assert action.message == "Explain the completed result."


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


def test_help_is_read_only_and_lists_real_commands() -> None:
    runtime, output, exit_code = _run_once(ConversationState.new("conversation-1"), "/help")

    assert exit_code == 0
    assert runtime.actions == []
    rendered = "\n".join(output)
    for command in (
        "/new",
        "/sources",
        "/leases",
        "/browser-profiles",
        "/pause",
        "/resume",
        "/cancel",
        "/exit",
    ):
        assert command in rendered
    assert "Unknown command" not in rendered


def test_help_does_not_resolve_or_replace_a_pending_approval() -> None:
    request = ApprovalRequest(
        request_id="approval-help",
        run_id="run-help",
        tool_call_id="call-help",
        binding_digest="binding-help",
        preview="write fixture.txt (7 bytes)",
    )
    waiting = replace(
        ConversationState.new("conversation-help"),
        active_run=ActiveRun(
            "run-help",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            pending_request=request,
            tool_calls=(ToolCall("call-help", "write_file", {}),),
        ),
    )

    runtime, output, exit_code = _run_once(waiting, "/help")

    assert exit_code == 0
    assert runtime.actions == []
    assert any("write fixture.txt" in item for item in output)
    # P5（2026-10-24）：无参 /approve 绑定 pending，ID 变为可选（[request-id]）。
    assert any("/approve [request-id]" in item for item in output)


def test_provider_wait_interrupt_exits_cleanly_and_keeps_saved_state() -> None:
    output: list[str] = []
    state = conversation_with_active_goal()

    exit_code = run_repl(
        InterruptingRuntime(),
        StaticStore(state),
        input_fn=lambda _prompt: "continue the task",
        write_fn=output.append,
        run_id_factory=lambda: "run-interrupted",
    )

    assert exit_code == 130
    assert output[0] == "Working..."
    assert "Saved state was kept" in output[-1]
    assert "may still have completed" in output[-1]


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


def test_browser_takeover_commands_reach_runtime_as_typed_actions() -> None:
    ready = conversation_with_active_goal()
    request = BrowserTakeoverRequestV1(
        request_id="takeover-1",
        session_ref="session-0123456789abcdef",
        profile_ref="profile-0123456789abcdef",
        profile_revision=3,
        browser_identity_digest="a" * 64,
        goal_id=ready.goal.goal_id,
        goal_revision=ready.goal.revision,
        requested_at="2026-08-28T10:00:00+00:00",
    )
    waiting = begin_browser_takeover(ready, request)

    runtime = RecordingRuntime()
    inputs = iter(("/browser-done", "/exit"))
    assert run_repl(
        runtime,
        StaticStore(waiting),
        input_fn=lambda _: next(inputs),
    ) == 0
    complete = runtime.actions[0]
    assert isinstance(complete, CompleteBrowserTakeover)
    assert complete.conversation_id == waiting.conversation_id
    assert complete.action_seq == waiting.next_action_seq
    assert complete.expected_revision == waiting.revision
    assert complete.request_id == request.request_id
    assert complete.session_ref == request.session_ref
    assert complete.expected_profile_revision == request.profile_revision

    runtime, _, _ = _run_once(waiting, "/browser-cancel")
    browser_cancel = runtime.actions[0]
    assert isinstance(browser_cancel, CancelBrowserTakeover)
    assert browser_cancel.conversation_id == waiting.conversation_id
    assert browser_cancel.action_seq == waiting.next_action_seq
    assert browser_cancel.expected_revision == waiting.revision
    assert browser_cancel.request_id == request.request_id

    runtime, _, _ = _run_once(waiting, "/cancel")
    assert runtime.actions[0] == browser_cancel


def test_browser_done_submits_only_typed_runtime_action() -> None:
    ready = conversation_with_active_goal()
    request = BrowserTakeoverRequestV1(
        request_id="takeover-1",
        session_ref="session-0123456789abcdef",
        profile_ref="profile-0123456789abcdef",
        profile_revision=3,
        browser_identity_digest="a" * 64,
        goal_id=ready.goal.goal_id,
        goal_revision=ready.goal.revision,
        requested_at="2026-08-28T10:00:00+00:00",
    )
    waiting = begin_browser_takeover(ready, request)
    runtime = RecordingRuntime()
    inputs = iter(("/browser-done", "/exit"))

    assert run_repl(
        runtime,
        StaticStore(waiting),
        input_fn=lambda _: next(inputs),
    ) == 0

    assert len(runtime.actions) == 1
    assert isinstance(runtime.actions[0], CompleteBrowserTakeover)


def test_browser_profile_command_is_reachable_without_runtime_mutation() -> None:
    state = conversation_with_active_goal()
    runtime = RecordingRuntime()
    inputs = iter(("/browser-profiles list", "/exit"))
    output: list[str] = []
    commands: list[str] = []

    assert run_repl(
        runtime,
        StaticStore(state),
        input_fn=lambda _: next(inputs),
        write_fn=output.append,
        browser_profile_command=lambda command: (
            commands.append(command) or "Browser profiles:\nprofile-0123456789abcdef"
        ),
    ) == 0
    assert commands == ["list"]
    assert output == ["Browser profiles:\nprofile-0123456789abcdef"]
    assert runtime.actions == []


def test_new_command_with_terminal_goal_requests_new_session() -> None:
    """/new(r19 小步 2):Goal 终态且无 pending 决策时请求新会话。

    合同性:新建动作本身不进 Runtime(零 run_turn → 零 provider/工具调用);
    以 NEW_SESSION_REQUESTED 退出码交还装配层重建 conversation;旧 checkpoint
    不被触碰。"""
    from agent.cli.app import NEW_SESSION_REQUESTED

    state = conversation_with_terminal_goal(GoalStatus.VERIFIED_DONE)
    runtime, output, exit_code = _run_once(state, "/new")
    assert runtime.actions == []
    assert exit_code == NEW_SESSION_REQUESTED
    assert any("new task" in item.lower() for item in output)


def test_new_command_with_pending_approval_is_refused() -> None:
    """/new 不得绕开 pending 决策:拒绝切换并说明原因,会话继续。"""
    from agent.cli.app import NEW_SESSION_REQUESTED

    request = ApprovalRequest(
        request_id="approval-full-id",
        run_id="run-1",
        tool_call_id="call-1",
        binding_digest="binding-1",
        preview="write note.txt (5 bytes)",
    )
    state = replace(
        ConversationState.new("conversation-1"),
        goal=conversation_with_active_goal().goal,
        active_run=ActiveRun(
            "run-1",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            pending_request=request,
            tool_calls=(ToolCall("call-1", "write_file", {}),),
        ),
    )
    runtime, output, exit_code = _run_once(state, "/new")
    assert runtime.actions == []
    assert exit_code == 0  # 拒绝后会话继续(经 /exit 正常退出)
    assert exit_code != NEW_SESSION_REQUESTED
    assert any("pending" in item.lower() or "resolve" in item.lower() for item in output)


def test_new_command_with_active_goal_is_refused() -> None:
    """/new 不清空、不重开活跃 Goal:非终态 Goal 必须先完成或取消。"""
    from agent.cli.app import NEW_SESSION_REQUESTED

    state = conversation_with_active_goal()
    runtime, output, exit_code = _run_once(state, "/new")
    assert runtime.actions == []
    assert exit_code == 0
    assert exit_code != NEW_SESSION_REQUESTED
    assert any("goal" in item.lower() for item in output)


def test_help_lists_artifact_confirmation_arguments_in_parser_order() -> None:
    """R4：/approve-artifact 帮助参数顺序与实际解析一致（<sha256> 在前）。"""

    runtime, output, _ = _run_once(ConversationState.new("conversation-1"), "/help")

    rendered = "\n".join(output)
    line = next(item for item in rendered.splitlines() if "/approve-artifact" in item)
    assert line.index("<sha256>") < line.index("<workspace-relative-path>")


def test_status_is_read_only_and_renders_goal_view() -> None:
    """`/status`（2026-10-25）：会话内任务状态查询。

    此前唯一的 goal 状态入口是重启进程加 `--status`；/sources 与 /leases 有
    会话内视图而任务状态没有——用户问"现在做到哪"必须退出重启。渲染走与
    headless 相同的 `project_goal_view` 纯投影，零 action 提交。
    """
    state = conversation_with_active_goal("conversation-status")
    goal = state.goal
    assert goal is not None
    state = replace(
        state,
        goal=replace(
            goal,
            status=GoalStatus.EXECUTING,
            progress_summary="app.py 已写入",
            next_step="运行 check.py 验证",
        ),
    )
    runtime, output, exit_code = _run_once(state, "/status")

    assert exit_code == 0
    assert runtime.actions == []
    rendered = "\n".join(output)
    assert "Task status: executing" in rendered
    assert f"revision {state.goal.revision}" in rendered
    assert state.goal.user_outcome[:20] in rendered
    assert "app.py 已写入" in rendered
    assert "运行 check.py 验证" in rendered
    assert "Criteria verified: 0/0" in rendered


def test_status_without_goal_shows_no_active_task() -> None:
    runtime, output, exit_code = _run_once(ConversationState.new("conversation-2"), "/status")

    assert exit_code == 0
    assert runtime.actions == []
    assert "no active task" in "\n".join(output)


def test_exact_match_commands_tolerate_trailing_whitespace() -> None:
    # 第九轮审计 R2：/help 列表内的命令带尾随空格不应被判 Unknown command
    # （"/exit " 甚至无法退出）；与 /help 的既有 strip 处理对齐。strip 判等
    # 的自然结果=前导空格同样被接受（PR #19 gate LOW），与本 runtime 层
    # casefold 归一一致——在此钉住，防回归为单侧容错。
    runtime, output, exit_code = _run_once(ConversationState.new("conversation-1"), "/status ")
    assert "Unknown command" not in "\n".join(output)
    assert any("no active task" in line for line in output)
    # /status 真实渲染（不是拒绝文案）

    runtime_lead, output_lead, _ = _run_once(
        ConversationState.new("conversation-1"), " /status"
    )
    assert "Unknown command" not in "\n".join(output_lead)
    assert any("no active task" in line for line in output_lead)

    runtime2 = RecordingRuntime()
    inputs = iter(("/exit ",))
    output2: list[str] = []
    exit2 = run_repl(
        runtime2,
        StaticStore(ConversationState.new("conversation-1")),
        input_fn=lambda _: next(inputs),
        write_fn=output2.append,
    )
    assert exit2 == 0
    assert runtime2.actions == []


def test_browser_profiles_unavailable_message_explains_the_remedy() -> None:
    # 第九轮审计 R4：默认启动（无 --browser）下 /browser-profiles 的拒绝
    # 必须说明原因与补救，不让 /help 列出的命令变成无出路的拒绝。
    runtime, output, exit_code = _run_once(
        ConversationState.new("conversation-1"), "/browser-profiles list"
    )
    assert "unavailable in this session" in output[0]
    assert "restart with --browser to enable browser features" in output[0]
