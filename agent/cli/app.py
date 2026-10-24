"""把终端输入或 headless typed action 交给同一个 Runtime。"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from agent.cli.actions import (
    NEW_SESSION_REQUESTED,
    build_cancel_browser_takeover,
    build_cancel_goal,
    build_complete_browser_takeover,
    build_grant_provider_consent,
    build_grant_provider_workspace_read_consent,
    build_pause_goal,
    build_recover_unknown_observation,
    build_resolve_approval,
    build_resume_goal,
    build_revoke_goal_target_authority,
    build_revoke_process_authority,
    build_revoke_provider_consent,
    new_session_gate,
    parse_artifact_confirmation,
    utc_now_rfc3339,
)
from agent.cli.render import TerminalRenderer
from agent.runtime.contracts import (
    AcknowledgeProviderDisclosure,
    Action,
    ActiveRunStatus,
    ApprovalRequest,
    CancelRun,
    ConversationState,
    EgressClass,
    GoalStatus,
    GrantProviderConsent,
    RecoveryRequest,
    RecoveryResolution,
    ResolveUnknownToolOutcome,
    Resume,
    RevokeProviderConsent,
    RunResult,
    RunStatus,
    SubmitMessage,
)
from agent.runtime.loop import AgentRuntime
from agent.runtime.ports import CheckpointStore
from agent.runtime.views import (
    GoalView,
    SourceView,
    pending_provider_disclosure_decision,
    project_goal_authorization_scopes,
    project_goal_view,
    project_obligation_rebind_disclosure,
    project_process_leases,
    project_visible_source_views,
)

_AFFIRMATIVE = frozenset({"y", "yes", "是", "允许"})
_NEGATIVE = frozenset({"n", "no", "否", "不允许"})
# B（2026-10-18）：拒绝/默认拒绝 pending 外发确认的安全退出文案。只陈述本次
# 待确认内容未发送，不笼统声称历史上 Nothing was sent——此前别的请求可能已发送。
_PENDING_DISCLOSURE_REFUSAL = (
    "The pending disclosure was not sent. The task is preserved; leaving this session."
)
_RECOVERY_SUCCEEDED = frozenset({"已成功", "成功", "succeeded", "success"})
_RECOVERY_FAILED = frozenset({"未成功", "失败", "failed", "failure"})
_RECOVERY_STOP = frozenset({"先停止", "停止", "stop"})
# 2026-10-24 P3：这些 CONFLICT 是"当前输入不可受理"而非本地 state 漂移——
# 未知效果待分类、另一进程持锁。REPL 存活并按 render 的指引继续，不退出。
_SURVIVABLE_CONFLICT_CODES = frozenset(
    {"unknown_effect_recovery_required", "conversation_busy"}
)
_OBSERVATION_CONTINUE = frozenset({"继续", "continue", "record unknown"})
_HELP_TEXT = """Commands:
/new — start a new conversation when no decision is pending
/sources [--advanced] — show recorded sources
/leases [--advanced] — show active process permissions
/browser-profiles [list|create|revoke|clear] — manage browser profiles
/pause, /resume, /cancel — control the current task or run
/approve [request-id], /reject [request-id] — resolve an exact approval (without
  an ID it binds the prompt just shown)
/approve-goal-target [request-id] — approve the exact file target for the current
  task (without an ID it binds the prompt just shown)
/approve-goal-directory [request-id] — approve files under an explicit Goal
  directory (without an ID it binds the prompt just shown)
/approve-artifact <sha256> <workspace-relative-path> — approve an exact artifact
/ack-provider <digest> — acknowledge an exact provider disclosure
/revoke-provider-consent — revoke the current conversation provider permission
/resolve-success [request-id], /resolve-failed [request-id] — resolve an unknown
  effect (without an ID it binds the prompt just shown)
/record-observation-unknown — continue after an unknown public observation
/revoke <lease-id|all> — revoke process permission
/revoke-goal-target — revoke all current-task file permissions
/browser-done, /browser-cancel — finish or cancel browser takeover
/exit — leave First Agent safely
When a prompt offers y/n, success/failed/stop, or continue/stop, you may answer it directly."""


def run_headless(
    runtime: AgentRuntime,
    store: CheckpointStore,
    action: Action,
) -> RunResult:
    """无隐式 I/O 地加载一次 snapshot 并执行一个 typed action。"""

    return runtime.run_turn(action, store.load())


def load_headless_view(store: CheckpointStore) -> GoalView:
    """headless/CLI 共用的只读状态投影；load 不会推进产品循环。"""

    return project_goal_view(store.load().state)


def load_headless_sources(
    store: CheckpointStore,
    *,
    advanced: bool = False,
) -> tuple[SourceView, ...]:
    """返回与 CLI/TUI 同源的只读来源投影；advanced 才含 opaque ref。"""

    return project_visible_source_views(store.load().state, advanced=advanced)


def load_headless_leases(
    store: CheckpointStore,
    *,
    advanced: bool = False,
):
    """F5/R11：headless 与 CLI/TUI 同源的 active lease readable 投影。"""

    return project_process_leases(store.load().state, advanced=advanced)


def run_repl(
    runtime: AgentRuntime,
    store: CheckpointStore,
    *,
    input_fn: Callable[[str], str] = input,
    write_fn: Callable[[str], None] = print,
    run_id_factory: Callable[[], str] | None = None,
    renderer: TerminalRenderer | None = None,
    approval_time_factory: Callable[[], str] = utc_now_rfc3339,
    browser_profile_command: Callable[[str], str] | None = None,
) -> int:
    make_run_id = run_id_factory or (lambda: str(uuid4()))
    renderer = renderer or TerminalRenderer(write_fn)
    while True:
        # 所见即所批：先取权威 snapshot 并投影 pending 决策，再读输入；
        # 该输入解析出的 action 与 run_turn 严格绑定同一 snapshot。
        # 若等待输入期间 store 漂移，现有 expected_revision/token CAS 会让
        # 该答案零副作用地 fail closed，且不重绑到新请求。
        snapshot = store.load()
        renderer.render_pending(snapshot.state)
        try:
            raw = input_fn("> ")
        except (EOFError, KeyboardInterrupt, StopIteration):
            return 0
        if raw == "/exit":
            return 0
        if raw == "/new":
            # r19 小步 2:显式新任务入口。合法性判断与 TUI 共享(new_session_gate);
            # 新建动作本身不进 Runtime(零 provider/工具调用),以专用退出码把
            # conversation 重建交还装配层,旧 checkpoint 与 evidence 原样保留。
            refusal = new_session_gate(snapshot.state)
            if refusal is not None:
                write_fn(refusal)
                continue
            write_fn("Starting a new task in this workspace (previous task kept).")
            return NEW_SESSION_REQUESTED
        if raw.strip() == "/help":
            write_fn(_HELP_TEXT)
            continue
        if not raw.strip():
            # B（2026-10-18）：answerable pending disclosure 上的空回车/纯空格
            # 与 [y/N] 提示一致地默认拒绝——安全退出，保留任务；无 pending 时
            # 保留既有忽略行为。
            if pending_provider_disclosure_decision(snapshot.state):
                write_fn(_PENDING_DISCLOSURE_REFUSAL)
                return 0
            continue
        if raw.strip().startswith("/browser-profiles"):
            if browser_profile_command is None:
                write_fn("Browser profiles are unavailable in this session.")
                continue
            suffix = raw.strip()[len("/browser-profiles") :].strip() or "list"
            try:
                write_fn(browser_profile_command(suffix))
            except ValueError as error:
                write_fn(str(error))
            except OSError:
                write_fn("Browser profile store is unavailable.")
            continue

        if raw == "/sources":
            renderer.render_sources(snapshot.state)
            continue
        if raw == "/sources --advanced":
            renderer.render_sources(snapshot.state, advanced=True)
            continue
        if raw == "/leases":
            renderer.render_leases(snapshot.state)
            continue
        if raw == "/leases --advanced":
            renderer.render_leases(snapshot.state, advanced=True)
            continue
        contextual_exit = _contextual_exit_message(raw, snapshot.state)
        if contextual_exit is not None:
            write_fn(contextual_exit)
            return 0
        action, error = _parse_action(
            raw,
            snapshot.state,
            make_run_id,
            approval_time_factory=approval_time_factory,
        )
        if error is not None:
            write_fn(error)
            continue
        if action is None:
            continue

        renderer.render_working()
        try:
            result = runtime.run_turn(action, snapshot)
        except KeyboardInterrupt:
            write_fn(
                "Run interrupted. Saved state was kept; restart First Agent to inspect "
                "or recover the task. A remote request or in-flight effect may still "
                "have completed."
            )
            return 130
        renderer.render_result(result)
        if isinstance(action, (GrantProviderConsent, RevokeProviderConsent)) and (
            result.status not in {RunStatus.CONFLICT, RunStatus.FAILED_FATAL}
        ):
            renderer.render_provider_consent(result.state)
        if result.status is RunStatus.CONFLICT:
            # 2026-10-24 P3：恢复边界的合法状态拒绝与另一进程持锁不终止会话
            # ——本地 state 未漂移，pending 决策仍在；继续循环让用户按指引作答
            # 或 /exit 干净退出。其余 CONFLICT（CAS 失配、event 重入等）保持
            # 退出码 2 的 fail-closed 语义。
            if result.error_code in _SURVIVABLE_CONFLICT_CODES:
                continue
            return 2
        if result.status is RunStatus.FAILED_FATAL:
            return 1
        if result.status is RunStatus.CONVERSATION_LIMIT_REACHED:
            return 2


def _parse_action(
    raw: str,
    state: ConversationState,
    make_run_id: Callable[[], str],
    *,
    approval_time_factory: Callable[[], str] = utc_now_rfc3339,
) -> tuple[Action | None, str | None]:
    common = {
        "conversation_id": state.conversation_id,
        "action_seq": state.next_action_seq,
        "expected_revision": state.revision,
    }
    command, separator, argument = raw.partition(" ")
    normalized = raw.strip().casefold()

    disclosure = state.provider_disclosure_request
    goal = state.goal
    # B（2026-10-18）：活跃与恢复形状共用唯一只读判定（views 谓词）；
    # render/yes/no/空白同源，Runtime 仍校验 action 合法性。
    disclosure_pending = pending_provider_disclosure_decision(state)
    if disclosure_pending and normalized == "s":
        if (
            state.active_run is None
            and goal is not None
            and goal.status is GoalStatus.PAUSED
        ):
            return (
                None,
                "The task is paused; run /resume before answering the pending disclosure.",
            )
        try:
            return build_grant_provider_consent(state), None
        except ValueError as error:
            return None, str(error)
    if disclosure_pending and normalized == "r":
        # item 1（2026-10-24）：读/验证类输出的显式会话许可——常规范围之上
        # 并入 proof-backed workspace_excerpt；与 s 分开键位，不静默升级。
        if (
            state.active_run is None
            and goal is not None
            and goal.status is GoalStatus.PAUSED
        ):
            return (
                None,
                "The task is paused; run /resume before answering the pending disclosure.",
            )
        try:
            return build_grant_provider_workspace_read_consent(state), None
        except ValueError as error:
            return None, str(error)
    if disclosure_pending and normalized in _AFFIRMATIVE:
        assert disclosure is not None
        return (
            AcknowledgeProviderDisclosure(
                **common,
                request_digest=disclosure.request_digest,
                acknowledged_at="operator-confirmed",
            ),
            None,
        )
    if disclosure_pending and (normalized in _NEGATIVE or not normalized):
        # REPL 在到达 parse 前已由 contextual exit/空输入路径安全退出；
        # 该兜底只约束直接调用方（如 TUI/probe）不把拒绝写成业务 SubmitMessage。
        return None, _PENDING_DISCLOSURE_REFUSAL
    if (
        disclosure is not None
        and state.provider_disclosure_receipt is None
        and state.active_run is None
        and goal is not None
        and goal.status is GoalStatus.PAUSED
        and (normalized in _AFFIRMATIVE | _NEGATIVE or normalized in {"s", "r"})
    ):
        # 窄范围 PAUSED 保护：暂停窗口里的裸 yes/no/s 不产生业务消息，先 /resume。
        # S2：有 pending 但选项不适用时给明确错误、零模型/效果，不当作新业务消息。
        return (
            None,
            "The task is paused; run /resume before answering the pending disclosure.",
        )

    approval = _approval_request(state)
    if approval is not None and normalized in {"f", "d"}:
        if approval.artifact_confirmation_requirement is not None:
            return (
                None,
                "Artifact generation keeps its separate content confirmation; "
                "answer y to approve generation once.",
            )
        command_for_scope = (
            "/approve-goal-target" if normalized == "f" else "/approve-goal-directory"
        )
        return _build_goal_scoped_approval(
            state,
            command_for_scope,
            approval_time_factory=approval_time_factory,
        )
    if approval is not None and normalized in _AFFIRMATIVE | _NEGATIVE:
        approved = normalized in _AFFIRMATIVE
        return (
            build_resolve_approval(
                state,
                request_id=approval.request_id,
                binding_digest=approval.binding_digest,
                approved=approved,
                approved_at=(approval_time_factory() if normalized in _AFFIRMATIVE else None),
                defer_artifact_confirmation=(
                    normalized in _AFFIRMATIVE
                    and approval.artifact_confirmation_requirement is not None
                ),
                # P2（对抗审查 2026-10-18）：重绑定只在审批提示已如实披露时
                # 随这次批准授权——用户看到的那条提示就是他的同意范围。
                authorize_obligation_rebind=(
                    approved and project_obligation_rebind_disclosure(state) is not None
                ),
            ),
            None,
        )

    recovery = _recovery_request(state)
    if recovery is not None:
        if _is_public_observation_recovery(state):
            if normalized in _OBSERVATION_CONTINUE:
                return build_recover_unknown_observation(state), None
            if not command.startswith("/"):
                return (
                    None,
                    "The public request may have been sent, but no usable response was "
                    "recorded. Reply with 'continue' to record no evidence and proceed, "
                    "or 'stop'. It will not retry automatically.",
                )
        resolution = None
        if normalized in _RECOVERY_SUCCEEDED:
            resolution = RecoveryResolution.MARK_SUCCEEDED
        elif normalized in _RECOVERY_FAILED:
            resolution = RecoveryResolution.MARK_FAILED
        if resolution is not None:
            return (
                ResolveUnknownToolOutcome(
                    **common,
                    request_id=recovery.request_id,
                    binding_digest=recovery.binding_digest,
                    resolution=resolution,
                ),
                None,
            )
        if not command.startswith("/"):
            return (
                None,
                "The previous operation has an unknown outcome. "
                "Reply with 'success', 'failed', or 'stop'.",
            )

    if command == "/ack-provider":
        request = state.provider_disclosure_request
        if request is None:
            return None, "No provider disclosure is pending."
        if not separator or argument != request.request_digest:
            return None, "Use the exact pending disclosure digest."
        return (
            AcknowledgeProviderDisclosure(
                **common,
                request_digest=request.request_digest,
                acknowledged_at="operator-confirmed",
            ),
            None,
        )

    if command == "/approve-artifact":
        request = _approval_request(state)
        if request is None:
            return None, "No approval request is pending."
        requirement = request.artifact_confirmation_requirement
        if requirement is None:
            return None, "The pending approval has no artifact requirement."
        try:
            path, sha256 = parse_artifact_confirmation(argument if separator else "")
        except ValueError as error:
            return None, str(error)
        if path != requirement.artifact_path:
            return None, "Artifact path must exactly match the pending requirement."
        return (
            build_resolve_approval(
                state,
                request_id=request.request_id,
                binding_digest=request.binding_digest,
                approved=True,
                approved_at=approval_time_factory(),
                confirmed_artifact_path=path,
                confirmed_artifact_sha256=sha256,
            ),
            None,
        )

    if command in {
        "/approve",
        "/approve-goal-target",
        "/approve-goal-directory",
        "/reject",
    }:
        request = _approval_request(state)
        if request is None:
            return None, "No approval request is pending."
        if command in {"/approve-goal-target", "/approve-goal-directory"}:
            return _build_goal_scoped_approval(
                state,
                command,
                request_id=(argument if separator else None),
                approval_time_factory=approval_time_factory,
            )
        # P5（2026-10-24）：无参数时绑定刚显示的 pending（与 /approve-goal-target
        # 的无参语义对齐）；带参数仍必须精确匹配——错误 ID 不许静默重绑。
        if separator and argument != request.request_id:
            return None, "Use the exact pending request ID."
        return (
            build_resolve_approval(
                state,
                request_id=request.request_id,
                binding_digest=request.binding_digest,
                approved=command != "/reject",
                approved_at=(
                    approval_time_factory()
                    if command == "/approve"
                    else None
                ),
                defer_artifact_confirmation=(
                    command != "/reject" and request.artifact_confirmation_requirement is not None
                ),
                authorize_obligation_rebind=(
                    command == "/approve"
                    and project_obligation_rebind_disclosure(state) is not None
                ),
            ),
            None,
        )

    if command in {"/resolve-success", "/resolve-failed"}:
        request = _recovery_request(state)
        if request is None:
            return None, "No recovery request is pending."
        if _is_public_observation_recovery(state):
            return None, "Public observation recovery cannot be guessed as success or failure."
        # P5（2026-10-24）：无参数绑定 pending recovery；带参数仍须精确匹配。
        if separator and argument != request.request_id:
            return None, "Use the exact pending request ID."
        return (
            ResolveUnknownToolOutcome(
                **common,
                request_id=request.request_id,
                binding_digest=request.binding_digest,
                resolution=(
                    RecoveryResolution.MARK_SUCCEEDED
                    if command == "/resolve-success"
                    else RecoveryResolution.MARK_FAILED
                ),
            ),
            None,
        )

    if command == "/record-observation-unknown":
        if separator:
            return None, "/record-observation-unknown does not accept arguments."
        if not _is_public_observation_recovery(state):
            return None, "No public observation recovery is pending."
        return build_recover_unknown_observation(state), None

    if command == "/resume":
        if separator:
            return None, "/resume does not accept arguments."
        if (
            state.goal is not None
            and state.goal.status in {GoalStatus.PAUSED, GoalStatus.BLOCKED}
            and state.active_run is None
        ):
            return build_resume_goal(state), None
        if state.active_run is None:
            return None, "No run is paused."
        return Resume(**common), None

    if command == "/pause":
        if separator:
            return None, "/pause does not accept arguments."
        if state.goal is None:
            return None, "No goal is active."
        return build_pause_goal(state), None

    if command == "/browser-done":
        if separator:
            return None, "/browser-done does not accept arguments."
        if state.browser_takeover_pending is None:
            return None, "No browser takeover is pending."
        return build_complete_browser_takeover(state), None

    if command == "/browser-cancel":
        if separator:
            return None, "/browser-cancel does not accept arguments."
        if state.browser_takeover_pending is None:
            return None, "No browser takeover is pending."
        return build_cancel_browser_takeover(state), None

    if command == "/cancel":
        if separator:
            return None, "/cancel does not accept arguments."
        if state.browser_takeover_pending is not None:
            return build_cancel_browser_takeover(state), None
        if state.goal is not None and state.goal.status not in {
            GoalStatus.CANCELLED,
            GoalStatus.VERIFIED_DONE,
        }:
            return build_cancel_goal(state), None
        if state.active_run is None:
            return None, "No run is paused."
        return CancelRun(**common), None

    if command == "/revoke":
        # F5/R11：`/revoke <lease_id>` 撤销单条；`/revoke all` 撤销全部。
        # 经共享 builder 翻译为 RevokeProcessAuthority（CAS expected_revision）；
        # 未知 id / 无 active lease 给 typed 反馈，不静默。
        if not separator or not argument.strip():
            return None, "Use /revoke <lease_id> or /revoke all."
        target = None if argument.strip() == "all" else argument.strip()
        try:
            return build_revoke_process_authority(state, lease_id=target), None
        except ValueError as error:
            return None, str(error)

    if command == "/revoke-goal-target":
        if separator:
            return None, "/revoke-goal-target does not accept arguments."
        try:
            return build_revoke_goal_target_authority(state), None
        except ValueError as error:
            return None, str(error)

    if command == "/revoke-provider-consent":
        if separator:
            return None, "/revoke-provider-consent does not accept arguments."
        try:
            return build_revoke_provider_consent(state), None
        except ValueError as error:
            return None, str(error)

    if command.startswith("/"):
        return None, "Unknown command. Run /help to see available commands."
    if (
        state.active_run is not None
        and state.active_run.status is not ActiveRunStatus.AWAITING_APPROVAL
    ):
        # P5（2026-10-24）：披露挂起时裸文本既不是业务消息也不是保留命令；
        # 指明提示实际接受的三个选项，不用"reserved command"误导。
        if disclosure_pending:
            return None, (
                "The pending disclosure expects 'y' (allow once), 's' (allow "
                "this task's routine scope), or 'n' (do not send)."
            )
        status = state.active_run.status.value
        return None, f"A run is paused ({status}); use its matching reserved command."
    return SubmitMessage(**common, run_id=make_run_id(), message=raw), None


def _build_goal_scoped_approval(
    state: ConversationState,
    command: str,
    *,
    request_id: str | None = None,
    approval_time_factory: Callable[[], str] = utc_now_rfc3339,
) -> tuple[Action | None, str | None]:
    """文件 f/d 与既有无参数 slash 共用的唯一范围审批构造路径。"""

    request = _approval_request(state)
    if request is None:
        return None, "No approval request is pending."
    if request_id is not None and request_id != request.request_id:
        return None, "Use the exact pending request ID."
    file_scope, directory_scope = project_goal_authorization_scopes(state)
    applicable = file_scope if command == "/approve-goal-target" else directory_scope
    if applicable is None:
        return None, "The pending approval has no matching Goal scope for this command."
    return (
        build_resolve_approval(
            state,
            request_id=request.request_id,
            binding_digest=request.binding_digest,
            approved=True,
            approved_at=approval_time_factory(),
            defer_artifact_confirmation=(
                request.artifact_confirmation_requirement is not None
            ),
            authorize_goal_target=command == "/approve-goal-target",
            authorize_goal_directory=command == "/approve-goal-directory",
        ),
        None,
    )


def _approval_request(state: ConversationState) -> ApprovalRequest | None:
    active = state.active_run
    if active is None or active.status is not ActiveRunStatus.AWAITING_APPROVAL:
        return None
    return active.pending_request if isinstance(active.pending_request, ApprovalRequest) else None


def _recovery_request(state: ConversationState) -> RecoveryRequest | None:
    active = state.active_run
    if active is None or active.status is not ActiveRunStatus.AWAITING_RECOVERY:
        return None
    return active.pending_request if isinstance(active.pending_request, RecoveryRequest) else None


def _is_public_observation_recovery(state: ConversationState) -> bool:
    active = state.active_run
    return bool(
        active is not None
        and active.status is ActiveRunStatus.AWAITING_RECOVERY
        and active.executing_intent is not None
        and active.executing_intent.egress is EgressClass.PUBLIC_NETWORK
    )


def _contextual_exit_message(raw: str, state: ConversationState) -> str | None:
    """拒绝 disclosure 或停止 unknown-outcome 时安全退出，且不伪造状态变更。"""

    normalized = raw.strip().casefold()
    if pending_provider_disclosure_decision(state) and normalized in _NEGATIVE:
        # B（2026-10-18）：活跃与恢复形状同判；拒绝零副作用退出。文案只陈述
        # 本次 pending 未发送，不声称历史零发送。
        return _PENDING_DISCLOSURE_REFUSAL
    if _recovery_request(state) is not None and normalized in _RECOVERY_STOP:
        return "Stopped without classifying or retrying the previous operation."
    return None
