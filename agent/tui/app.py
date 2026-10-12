"""Optional Textual TUI app（lazy import）。

base install、headless、普通 CLI 不导入 Textual。App 表达当前 v1 键盘 adapter 的 actions：
submit（Enter）、approve（a）、reject（r）、mark succeeded（s）、mark failed（f）、
resume（u）、合法 paused cancel（c）。所有 action 经 shared ``agent.cli.actions``
builder 从 authoritative state 构造，并由 projection 的可用 action 集合 gate——只有
当前 authoritative 投影允许的 action 才会 dispatch，因此重开 EXECUTING 时 Cancel 不
dispatch、Resume 才提交。single-flight Textual worker 调用 ``TuiAdapter.execute_once``；
RunResult/checkpoint 始终权威，events 只 advisory（drain 后不写入 terminal renderer）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from agent.cli.actions import (
    build_ack_provider,
    build_cancel,
    build_cancel_browser_takeover,
    build_cancel_goal,
    build_complete_browser_takeover,
    build_pause_goal,
    build_recover_unknown_observation,
    build_resolve_approval,
    build_resolve_recovery,
    build_resume,
    build_resume_goal,
    build_revoke_goal_target_authority,
    build_revoke_process_authority,
    build_submit,
    parse_artifact_confirmation,
    utc_now_rfc3339,
)
from agent.runtime.contracts import (
    Action,
    ControlRequestKind,
    ConversationState,
    FactKind,
    GoalStatus,
    RecoveryResolution,
    ResolveApproval,
    RuntimeEventKind,
)
from agent.runtime.views import project_visible_source_views, verification_scope_message
from agent.tui.adapter import AdapterControlUnavailableError, TuiAdapter
from agent.tui.dialogs import build_f3_pages, build_facts_review_screen, build_multiline_edit_screen
from agent.tui.render import (
    SafeDisplayTooLargeError,
    TuiProjection,
    project,
    run_status_label,
    safe_display,
)

_LOG = logging.getLogger("agent.tui.app")

# approval preview 的显示 cap（escape 后字符数）。这是 effect 前的安全关键面：超过 cap 时
# 绝不静默截断（会掩盖用户即将批准的关键 effect 内容），而是 fail closed——屏蔽 approve，
# 明确不可批准，用户只能 reject 或缩小 effect。status/hints 不是审批面，不施加此 cap。
_PREVIEW_DISPLAY_CAP = 4_000


class TextualNotInstalledError(RuntimeError):
    """未安装 Textual 时给出明确安装提示。"""


def parse_process_command(
    value: str,
    state,
    *,
    approval_time_factory: Callable[[], str] = utc_now_rfc3339,
) -> tuple | None:  # noqa: ANN001
    """F5/R11：TUI 输入的 process-authority 命令翻译（纯函数，adapter 自有层）。

    返回 ``("action", RevokeProcessAuthority)`` / ``("leases", views)`` /
    ``("error", message)``；普通消息返回 ``None``（走 submit 路径）。与 CLI 共用
    ``build_revoke_process_authority`` typed builder 与 ``project_process_leases``
    投影——同一 reducer 入口，不复制状态机。
    """

    from agent.runtime.views import project_process_leases

    text = value.strip()
    if not text.startswith("/"):
        return None
    command, _, argument = text.partition(" ")
    if command == "/new":
        # r19 小步 2:显式新任务入口,与 CLI 共享 new_session_gate 同一合法性
        # 判断。允许时返回 ("new_session", None) 由 app 以 NEW_SESSION_REQUESTED
        # 退出码交还装配层重建 conversation;拒绝时如常显示原因并继续。
        from agent.cli.actions import new_session_gate

        refusal = new_session_gate(state)
        if refusal is not None:
            return ("error", refusal)
        return ("new_session", None)
    if command == "/approve-artifact":
        active = state.active_run
        request = active.pending_request if active is not None else None
        requirement = getattr(request, "artifact_confirmation_requirement", None)
        if requirement is None:
            return ("error", "The pending approval has no artifact requirement.")
        try:
            path, sha256 = parse_artifact_confirmation(argument)
        except ValueError as error:
            return ("error", str(error))
        if path != requirement.artifact_path:
            return ("error", "Artifact path must exactly match the pending requirement.")
        return (
            "action",
            build_resolve_approval(
                state,
                request_id=request.request_id,
                binding_digest=request.binding_digest,
                approved=True,
                approved_at=approval_time_factory(),
                confirmed_artifact_path=path,
                confirmed_artifact_sha256=sha256,
            ),
        )
    if command == "/leases":
        advanced = argument.strip() == "--advanced"
        return ("leases", project_process_leases(state, advanced=advanced))
    if command == "/revoke":
        target_text = argument.strip()
        if not target_text:
            return ("error", "Use /revoke <lease_id> or /revoke all.")
        target = None if target_text == "all" else target_text
        try:
            return ("action", build_revoke_process_authority(state, lease_id=target))
        except ValueError as error:
            return ("error", str(error))
    if command == "/revoke-goal-target":
        if argument.strip():
            return ("error", "/revoke-goal-target does not accept arguments.")
        try:
            return ("action", build_revoke_goal_target_authority(state))
        except ValueError as error:
            return ("error", str(error))
    return None


def _bounded_worker_error(error: BaseException) -> str:
    """worker 异常的有界、不泄露提示：仅取异常类型名 + 固定说明。

    不包含 ``str(error)``——原始异常消息可能含 secret/路径/敏感细节，不能进入用户可见面
    或日志。类型名是安全的（无数据），足以让用户/操作者知道发生了哪类故障。"""
    return f"{type(error).__name__}: action not applied; reloaded from last checkpoint"


def _require_textual():
    try:
        from textual.app import App, ComposeResult  # noqa: F401
        from textual.containers import Vertical  # noqa: F401
        from textual.widgets import Footer, Input, Static  # noqa: F401
    except ImportError as error:
        raise TextualNotInstalledError(
            "the TUI requires the optional 'tui' extra "
            "(textual>=8.2,<9); install it or use the plain CLI"
        ) from error


def build_app(
    adapter: TuiAdapter,
    *,
    run_id_factory: Callable[[], str],
    close_deadline_seconds: float = 30.0,
    approval_time_factory: Callable[[], str] = utc_now_rfc3339,
):
    _require_textual()
    from textual import work
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Vertical
    from textual.widgets import Footer, Input, Static

    class FocusStatic(Static):
        """可聚焦的只读区域，用于 approval/recovery 表单获得键盘焦点。"""

        can_focus = True

    class FirstAgentTui(App):
        CSS = ""
        BINDINGS = [
            ("a", "approve", "Approve"),
            ("shift+a", "approve_goal_target", "Approve exact task target"),
            ("shift+d", "approve_goal_directory", "Approve task directory"),
            ("r", "reject", "Reject"),
            ("s", "mark_succeeded", "Mark Succeeded"),
            ("f", "mark_failed", "Mark Failed"),
            ("o", "record_observation_unknown", "Record Observation Unknown"),
            ("u", "resume", "Resume"),
            ("p", "pause_goal", "Pause Goal"),
            ("c", "cancel", "Cancel"),
            Binding("ctrl+c", "cancel", "Cancel active task", priority=True),
            ("d", "ack_provider", "Acknowledge Provider"),
            ("b", "browser_done", "Browser done — return control"),
            ("f2", "toggle_source_refs", "Toggle Source Refs"),
            ("f3", "review_facts", "Review recent content"),
            ("f4", "multiline_edit", "Multi-line edit"),
            ("ctrl+q", "quit", "Quit"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self._adapter = adapter
            # UI-03（2026-10-11）：丢弃判定需要只读观察活跃 control binding；
            # adapter 未配置 inbox 时返回 None（无协作控制能力），判定整体跳过。
            self._control_inbox = getattr(adapter, "active_control_binding", None)
            self._dropped_control_notice = False
            self._run_id_factory = run_id_factory
            self.close_deadline_seconds = close_deadline_seconds
            self.projection: TuiProjection | None = None
            # 用户手势必须绑定到实际展示的 immutable snapshot；执行时 adapter 仍会
            # fresh-load checkpoint，让 Kernel 以 revision/request binding 拒绝 stale action。
            self._displayed_state: ConversationState | None = None
            self.form_text: str = ""
            # 最近一次 worker 失败的有界提示（observability）；成功刷新会清回 None。
            self._last_worker_error: str | None = None
            # approval preview 是否超过显示 cap：True 时 approve 被 fail-closed gate 屏蔽。
            self._preview_too_large: bool = False
            self._advanced_sources: bool = False
            # lifecycle：active worker 收到 quit 后进入 closing_requested；不 cancel
            # worker；deadline 到仍未收口时如实提示超时等待（不是永久 latch）；
            # callable 真正返回且权威 reload 成功后自动自然退出。
            self.closing_requested = False
            # S1-B（2026-10-09）：提交簿记在 _run_action 内同步落位——已排队尚未
            # 开始的 worker 也算 busy；deadline timer 只在首次关闭请求时 arm 一次；
            # reload 失败时业务动作禁用，重复 Ctrl-Q 每次仅做一次只读 reload 重试。
            self._dispatch_pending = False
            self._close_deadline_armed = False
            self._reload_failed = False
            self._close_deadline_timer = None
            # S1-C：已排队未应用的 pause/cancel（同一 binding 上合并重复点击）。
            self._pending_control_kinds: set[str] = set()
            # deadline 曾超时的如实提示（display-only；不阻止后续自然收口）。
            self.shutdown_blocked = False
            # 最近一次完成的 worker 是否报错（决定关闭收口退出码 0/2）。
            self._last_worker_had_error = False
            # S2-A（2026-10-09）：UI 本地草稿。只有 durable 接收证明（action replay
            # 的 user fact 文本 / 匹配的 ControlReceipt）才消费草稿；_refresh 是展示，
            # 不无条件清 Input；等待中输入的新版本不被迟到回调覆盖。
            self.draft_text: str = ""
            self.draft_revision: int = 0
            self._pending_submission: tuple[str, int] | None = None
            self._pending_control_texts: dict[str, tuple[str, int]] = {}
            self._restoring_draft = False
            # S2-A 流式展示窗口：每次 UI dispatch 打开，run_turn 结果 reload 后关闭；
            # 窗口外旧 delta/waiting 一律忽略（advisory）。
            self._stream_open = False
            self._stream_conversation: str | None = None
            self._stream_run: str | None = None
            self._stream_identity: tuple[str, str | None, int, str] | None = None
            self._stream_watermark = 0
            self._stream_seen: set[str] = set()
            self._stream_degraded = False

        def compose(self) -> ComposeResult:
            yield Vertical(
                Static("", id="status"),
                FocusStatic("", id="form"),
                Input(placeholder="message (Enter to submit)", id="message"),
                Static("", id="action_hints"),
                Footer(),
            )

        def on_mount(self) -> None:
            # r19 小步 3:周期 drain 流式增量事件,worker 运行期间也能在状态区
            # 看到回答片段(advisory;权威结果仍由 _refresh 从 checkpoint 投影)。
            self._streamed_answer = ""
            self.set_interval(0.5, self._drain_delta_events)
            self._refresh()

        def on_input_changed(self, event) -> None:  # noqa: ANN001
            # S2-A：用户输入即同步 UI 草稿（programmatic restore 的回声不计新
            # 版本：值与当前草稿一致时忽略）。
            if self._restoring_draft:
                return
            if getattr(event, "control", None) is not self.query_one("#message", Input):
                return
            if event.value == self.draft_text:
                return
            if "\n" in event.value:
                # F4：单行 Input 收到多行 paste → 转入同一多行 modal，保留换行、
                # 不截成首行、不自动发消息。
                multiline = event.value
                self._restoring_draft = True
                try:
                    event.control.value = ""
                finally:
                    self._restoring_draft = False
                self.draft_text = ""
                self.push_screen(
                    build_multiline_edit_screen(multiline),
                    self._on_multiline_result,
                )
                return
            self.draft_text = event.value
            self.draft_revision += 1

        def _restore_draft(self) -> None:
            # 展示恢复：把 UI 草稿放回 Input，不触发新的 draft revision。
            msg_input = self.query_one("#message", Input)
            if "\n" in self.draft_text:
                # UI-01：多行草稿不压进单行 Input（会丢换行）；主界面只保留本地
                # 草稿与状态提示，用户经 F4 继续编辑或提交。
                if msg_input.value:
                    self._restoring_draft = True
                    try:
                        msg_input.value = ""
                    finally:
                        self._restoring_draft = False
                return
            if msg_input.value != self.draft_text:
                self._restoring_draft = True
                try:
                    msg_input.value = self.draft_text
                finally:
                    self._restoring_draft = False

        def _consume_pending_if_durably_accepted(self, state) -> None:  # noqa: ANN001
            # S2-A：只有 durable 接收证明才消费草稿——SubmitMessage 需要 replay 的
            # ``action:{seq}:user`` fact 实际文本；correction 需要匹配 request_id 的
            # ControlReceipt。排队、worker 已调度、RunStatus.COMPLETED、无异常都不
            # 是消费证明。消费只清除"仍为同一 draft_revision 的那份文本"；等待中
            # 输入的新版本不被迟到回调覆盖。接收情况未知时保留草稿，不自动重发。
            pending = self._pending_submission
            if pending is not None:
                # UI-02（2026-10-11）：待确认条目绑定确切 conversation/action
                # identity（本次 dispatch 的 action_seq），不以"任意 action: 前缀
                # + 文本相等"判定；历史同文、不同会话同文、迟到回执都不能消费
                # 本次文本。
                conversation_id, action_seq, text, revision = pending
                fact_id = f"action:{action_seq}:user"
                if state.conversation_id == conversation_id and any(
                    fact.fact_id == fact_id
                    and fact.kind is FactKind.USER_MESSAGE
                    and fact.content.get("text") == text
                    for fact in state.facts
                ):
                    self._pending_submission = None
                    if self.draft_revision == revision:
                        self.draft_text = ""
            # UI-03（2026-10-11）：队列关闭导致未应用的纠正必须有明确结局。
            # ControlInbox.close 丢弃未消费请求；TUI 在收尾刷新时对照 inbox
            # 判断——请求既无 receipt、又已不在 inbox 且 binding 已关闭，即
            # "已明确丢弃"：解除 dedup、保留文本供用户显式重发（不自动重试）。
            self._resolve_dropped_control_requests(state)
            for request_id, entry in list(self._pending_control_texts.items()):
                message, revision = entry
                if any(
                    receipt.correlation_id == request_id
                    for receipt in state.control_receipts
                ):
                    del self._pending_control_texts[request_id]
                    if self.draft_revision == revision and self.draft_text == message:
                        self.draft_text = ""

        def _resolve_dropped_control_requests(self, state) -> None:  # noqa: ANN001
            """把"已明确丢弃"的纠正从 pending 账转为可重发状态。

            区分三种结局（UI-03 冻结语义）：

            - 已应用：durable ControlReceipt 存在（上面的消费分支处理）；
            - 已明确丢弃：请求不再在 inbox 且当前无活跃 binding（run 已收尾，
              Runtime 的 ``close`` 丢弃了未消费请求）→ 解除 dedup 并保留文本；
            - 接收未知：inbox 仍持有该请求或 binding 仍活跃 → 保持 pending，
              不自动重试、也不允许重复发送。

            只读 inbox 观察，不修改 durable state、不重发请求。
            """

            binding_observer = self._control_inbox
            if binding_observer is None or not self._pending_control_texts:
                return
            binding = binding_observer(state.conversation_id)
            if binding is not None:
                # 仍有活跃 invocation：未收到 receipt 的请求可能仍在排队，
                # 保持 pending（未知），不做任何清理。
                return
            dropped = [
                request_id
                for request_id in self._pending_control_texts
                if not any(
                    receipt.correlation_id == request_id
                    for receipt in state.control_receipts
                )
            ]
            if not dropped:
                return
            for request_id in dropped:
                message, revision = self._pending_control_texts.pop(request_id)
                if self.draft_revision == revision and not self.draft_text:
                    # 文本保留为可编辑草稿：用户可显式重发一次。
                    self.draft_text = message
            self._dropped_control_notice = True

        def _open_stream_window(self, displayed_state) -> None:  # noqa: ANN001
            # S2-A：每次 UI dispatch 打开流式展示窗口；只保存 expected conversation，
            # 首个合法事件再精确绑定 run。新 run 只可绑定本次合法 action 的首个事件。
            self._stream_conversation = (
                displayed_state.conversation_id
                if displayed_state is not None
                else None
            )
            self._stream_run = None
            self._stream_identity = None
            self._stream_open = True
            self._stream_watermark = 0
            self._stream_seen = set()
            self._stream_degraded = False
            self._streamed_answer = ""

        def _close_stream_window(self) -> None:
            # run_turn 结果/错误返回并处理权威 reload 后关闭窗口；之后到达的
            # 旧 delta/waiting 一律忽略，不能覆盖 final。
            self._stream_open = False
            self._stream_run = None
            self._stream_identity = None
            self._streamed_answer = ""

        def _stream_update_status(self) -> None:
            from rich.text import Text

            if self._stream_degraded:
                display = "· 流式预览不完整，等待最终结果 ·"
            elif self._streamed_answer:
                tail = self._streamed_answer[-2000:]
                display = f"· 生成中 · {tail}"
            else:
                return
            self.query_one("#status", Static).update(Text(safe_display(display)))

        def _drain_delta_events(self) -> None:
            drained = self._adapter.event_sink.drain()
            if not drained:
                return
            # S1-C 状态优先级：关闭等待/读取失败/控制请求待确认的反馈优先于
            # provider waiting。
            priority_status = (
                self.closing_requested
                or self._reload_failed
                or bool(self._pending_control_kinds)
            )
            from rich.text import Text

            for event in drained:
                if not self._stream_open:
                    return  # 窗口外旧 delta/waiting 一律忽略
                if (
                    self._stream_conversation is not None
                    and event.conversation_id != self._stream_conversation
                ):
                    continue  # 其它 conversation 的先到事件不绑定本窗口
                if (
                    self._stream_run is not None
                    and event.run_id != self._stream_run
                ):
                    continue  # 精确 run 绑定后拒绝其它 run 的事件
                if event.kind is RuntimeEventKind.MODEL_PROGRESS:
                    if self._stream_run is None and event.run_id is not None:
                        self._stream_run = event.run_id
                    phase = str(event.payload.get("phase", ""))
                    if priority_status:
                        continue
                    if phase == "provider_waiting":
                        elapsed = event.payload.get("elapsed_seconds", 0)
                        self.query_one("#status", Static).update(
                            Text(
                                safe_display(
                                    f"· 模型仍在工作 · 已等待 {elapsed} 秒"
                                )
                            )
                        )
                    elif phase == "provider_finished":
                        self._stream_update_status()
                    continue
                if event.kind is not RuntimeEventKind.MODEL_TEXT_DELTA:
                    continue
                if self._stream_run is None:
                    if event.run_id is None:
                        continue  # 新 run 只绑定带 run 身份的首个事件
                    self._stream_run = event.run_id
                    self._streamed_answer = ""
                    self._stream_watermark = 0
                    self._stream_seen = set()
                    self._stream_degraded = False
                identity = (
                    event.conversation_id,
                    event.run_id,
                    event.revision,
                    event.causation_id,
                )
                if (
                    self._stream_identity is not None
                    and identity != self._stream_identity
                ):
                    if event.revision > self._stream_identity[2]:
                        # 同 run 较新 revision = 新响应：清空当前 preview。
                        self._stream_identity = identity
                        self._streamed_answer = ""
                        self._stream_watermark = 0
                        self._stream_seen = set()
                        self._stream_degraded = False
                    else:
                        continue  # 较旧 revision/已封闭 identity 的迟到事件不切回
                elif self._stream_identity is None:
                    self._stream_identity = identity
                # 有限 cache 去重（cap 256，溢出降级；序号水位避免无限集合）。
                if event.event_id in self._stream_seen:
                    continue
                if len(self._stream_seen) >= 256:
                    self._stream_degraded = True
                    self._stream_update_status()
                    continue
                self._stream_seen.add(event.event_id)
                try:
                    sequence = int(event.event_id.rsplit(":", 1)[1])
                except (IndexError, ValueError):
                    self._stream_degraded = True
                    self._stream_update_status()
                    continue
                if sequence == self._stream_watermark:
                    continue  # 重复忽略
                if sequence != self._stream_watermark + 1:
                    # 缺口/逆序：降级为不完整预览，不猜测拼接。
                    self._stream_degraded = True
                    self._stream_update_status()
                    continue
                self._stream_watermark = sequence
                text = str(event.payload.get("text", ""))
                if priority_status:
                    continue
                if text:
                    self._streamed_answer += text
                self._stream_update_status()

        def _current_projection(self) -> TuiProjection:
            return project(self._adapter.load_view().snapshot.state)

        def _refresh(self, result=None, worker_error: str | None = None) -> None:
            from rich.text import Text

            # worker 失败提示仅在 worker 完成那次刷新时传入；其它刷新（mount/close 等）
            # 传 None 以清除上次提示，避免 stale 错误长期滞留。
            self._last_worker_error = worker_error

            view = self._adapter.load_view()
            # reload 成功即解除"读取失败"停用态；后续 Ctrl-Q 不再是重试路径。
            self._reload_failed = False
            # S2-A：先用 durable facts 消费草稿账，再渲染（消费后的文本不再展示）。
            self._consume_pending_if_durably_accepted(view.snapshot.state)
            projection = project(view.snapshot.state, result)

            main_text = projection.main_text
            if (
                result is not None
                and projection.form_kind == "browser_takeover"
                and result.error_code == "browser_takeover_completion_failed"
            ):
                main_text = (
                    f"{projection.main_text}\nCompletion could not be confirmed; this "
                    "takeover is still pending. Use Browser cancel after restarting or "
                    "when the original browser window is unavailable."
                )
            elif result is not None and projection.form_kind is None:
                # S2-A（UI-04）：snapshot 是状态权威。approval/recovery/disclosure/
                # takeover 等 pending 表单与 paused 状态不被旧 result 覆盖；结果
                # 文本只在无表单的终端/继续态上叠加。
                # UI-05（2026-10-11）：叠加而非替换——VERIFIED_DONE 的权威交付
                # 摘要（目标/产物/证据计数/权限状态）来自 snapshot 投影，普通
                # result.message 只能附加，不能把它整体顶掉。
                label = run_status_label(result.status)
                result_line = f"{label}: {result.message or projection.main_text}"
                if (
                    result.message
                    and projection.goal is not None
                    and projection.goal.verification_scope
                ):
                    result_line = (
                        f"{result_line}\n"
                        f"{verification_scope_message(projection.goal.verification_scope)}"
                    )
                main_text = (
                    result_line
                    if projection.main_text == "ready"
                    else f"{projection.main_text}\n{result_line}"
                )
            sources = (
                project_visible_source_views(view.snapshot.state, advanced=True)
                if self._advanced_sources
                else projection.sources
            )
            if sources:
                source_lines = ["Sources:"]
                source_lines.extend(
                    (
                        f"- {source.source_kind} · {source.title} · {source.locator} · "
                        f"{source.observed_at} · {source.status}"
                        + (
                            f" · {source.source_ref}"
                            if self._advanced_sources and source.source_ref is not None
                            else ""
                        )
                    )
                    for source in sources
                )
                main_text = f"{main_text}\n" + "\n".join(source_lines)
            if worker_error is not None:
                # 用户可见的有界失败提示（不含原始异常敏感内容）；状态来自 authoritative
                # checkpoint 重新投影（action 未推进）。
                main_text = worker_error
            if self._dropped_control_notice:
                # UI-03（2026-10-11）：run 收尾关闭 control 队列时未应用的纠正
                # 必须有明确、用户可见的结局；文本已保留为草稿，可检查后重新
                # 提交（不自动重试）。提示只展示一次，随下次刷新自然消失。
                main_text = (
                    f"{main_text}\n已明确丢弃：队列关闭前未应用的纠正没有执行；"
                    "文本已保留为草稿，可检查后重新提交。"
                )
                self._dropped_control_notice = False
            self.query_one("#status", Static).update(Text(safe_display(main_text)))

            self.form_text = self._render_form(projection)
            # approval preview 是 effect 前的安全关键面：施加显示 cap。超过 cap 绝不静默截断
            # （会掩盖即将批准的关键 effect 内容），改为 fail closed——屏蔽 approve、显示有界
            # 警告，用户只能 reject 或缩小 effect。见 _permitted_state 的 approve gate。
            try:
                escaped_form = safe_display(self.form_text, cap=_PREVIEW_DISPLAY_CAP)
                self._preview_too_large = False
            except SafeDisplayTooLargeError:
                self._preview_too_large = True
                overflow_message = (
                    "browser takeover details exceed display cap; Browser done disabled "
                    "— use Browser cancel"
                    if projection.form_kind == "browser_takeover"
                    else "approval preview exceeds display cap; approve disabled "
                    "— reject or reduce the effect"
                )
                escaped_form = safe_display(overflow_message)
            self.query_one("#form", Static).update(Text(escaped_form))

            # preview 过大时从 hints 移除 approve，避免误导用户以为可批准。
            display_actions = projection.actions
            if self._preview_too_large:
                display_actions = tuple(
                    action
                    for action in display_actions
                    if action not in {"approve", "browser_done"}
                )
            hints = self._format_hints(projection, display_actions)
            self.query_one("#action_hints", Static).update(Text(safe_display(hints)))

            msg_input = self.query_one("#message", Input)
            if (
                "submit" in projection.actions
                or "correct_goal" in projection.actions
                or projection.focus == "input"
            ) and not self.closing_requested:
                msg_input.disabled = False
                # S2-A：_refresh 是展示，不无条件清 Input；草稿只在 durable 消费
                # 后清除（F2/回看/审批/状态/错误刷新都不消费草稿）。
                self._restore_draft()
                msg_input.focus()
            else:
                msg_input.disabled = True
                # approval/recovery 表单聚焦；其它非 submit 状态取消 input 焦点。
                if projection.form_kind is not None:
                    self.query_one("#form", FocusStatic).focus()

            # 只有 status/form/hints/focus 都成功更新后，才让后续手势观察这份 state。
            # 这不是 UI-owned mutation authority，只是“用户刚刚看到了什么”的绑定。
            self.projection = projection
            self._displayed_state = view.snapshot.state

            # events 只 advisory：drain queue 后不写入 terminal renderer。
            self._adapter.event_sink.drain()

            # closing 收口：worker 已安全返回且 reload 完 authoritative checkpoint 后
            # 才退出。退出码：worker 曾报错 → 2（可能需要恢复）；正常 → 0。
            if (
                self.closing_requested
                and not self._dispatch_pending
                and not self._adapter.is_active
                and not self._reload_failed
            ):
                self.exit(return_code=2 if self._last_worker_had_error else 0)

        @staticmethod
        def _render_form(projection: TuiProjection) -> str:
            if not projection.form_fields:
                return ""
            return "\n".join(f"{label}: {value}" for label, value in projection.form_fields)

        @staticmethod
        def _format_hints(
            projection: TuiProjection,
            actions: tuple[str, ...],
        ) -> str:
            goal = projection.goal
            if goal is not None and actions == ("submit",):
                if goal.status == GoalStatus.VERIFIED_DONE.value:
                    return (
                        "Task finished · Enter: ask a follow-up "
                        "(does not start a new task) | /new: start a new task "
                        "(keeps this task's records) | Ctrl-Q: quit"
                    )
                if goal.status == GoalStatus.CANCELLED.value:
                    return (
                        "Task cancelled · Enter: ask a follow-up "
                        "(task remains cancelled; does not start a new task) | "
                        "/new: start a new task | Ctrl-Q: quit"
                    )
            labels = {
                "submit": "Enter: submit",
                "approve": "a: approve",
                "reject": "r: reject",
                "mark_succeeded": "s: mark succeeded",
                "mark_failed": "f: mark failed",
                "record_observation_unknown": "o: record observation unknown",
                "resume": "u: resume",
                "cancel": "c: cancel",
                "pause_goal": "p: pause goal",
                "resume_goal": "u: resume goal",
                "correct_goal": "Enter: correct goal",
                "cancel_goal": "c: cancel goal",
                "ack_provider": "d: acknowledge provider",
                "browser_done": "b: Browser done — return control",
                "browser_cancel": "c: Browser cancel — cancel this takeover",
            }
            parts = [labels.get(a, a) for a in actions]
            action_text = " | ".join(parts) if parts else "no actions"
            return f"{action_text} | Ctrl-Q: quit"

        def _busy(self) -> bool:
            # S1-B：已排队尚未开始（pending）与 adapter single-flight 都算 busy。
            return self._dispatch_pending or self._adapter.is_active

        def _permitted_state(self, name: str) -> ConversationState | None:
            """只有当前 authoritative 投影允许、且未进入 closing 时才返回 state。"""
            if self.closing_requested or self._reload_failed:
                return None
            if self._busy():
                # 已排队/运行中的 worker：禁止新 action，避免撞 single-flight 或绕过
                # unknown effect。
                return None
            if self._preview_too_large and name in {"approve", "browser_done"}:
                # approval/takeover effect 详情超过显示 cap → fail closed；对应的
                # approve/done 不可用，仍保留 reject/browser cancel 这类非完成选择。
                return None
            state = self._displayed_state
            projection = self.projection
            if state is None or projection is None or name not in projection.actions:
                return None
            return state

        def _permitted_artifact_approval_state(self) -> ConversationState | None:
            """typed artifact approval 复用 approval preview 的同一 fail-closed gate。"""

            if (
                self.closing_requested
                or self._reload_failed
                or self._busy()
                or self._preview_too_large
            ):
                return None
            state = self._displayed_state
            if state is None or self.projection is None:
                return None
            active = state.active_run
            request = active.pending_request if active is not None else None
            if getattr(request, "artifact_confirmation_requirement", None) is None:
                return None
            return state

        def request_close(self) -> None:
            """S1-B 关闭收口：不 cancel worker，分四种情况如实收口。

            - 已排队/运行中：closing_requested + 只在首次请求时 arm 一个 deadline
              timer；重复 Ctrl-Q 不重置/叠加 timer。
            - deadline 超时：如实显示仍在等待（display-only，非永久 latch）；
              callable 返回后仍会自动收口。
            - callable 已返回：一次权威 reload 后按结果收口（成功 0 / worker 报错 2）。
            - reload 失败：保留固定错误、禁用业务动作；重复 Ctrl-Q 每次只做一次
              只读 reload 重试，不重做 action。
            """
            self.closing_requested = True
            if self._busy():
                if not self._close_deadline_armed:
                    self._close_deadline_armed = True
                    self._close_deadline_timer = self.set_timer(
                        self.close_deadline_seconds, self._on_close_deadline
                    )
                self._show_control_request_received(
                    "关闭请求已记录；等待当前调用收口，不代表已取消。"
                )
                return
            try:
                self._refresh()
            except Exception:
                self._on_reload_failed()

        def action_quit(self) -> None:  # type: ignore[override]
            # 覆盖默认 quit：走优雅收口，避免在 active worker 上 force-exit。
            self.request_close()

        def _on_close_deadline(self) -> None:
            # deadline 到仍未收口：如实提示仍在等待；不是永久 latch——callable
            # 返回后的完成回调仍会自动收口。
            if self.closing_requested and self._busy():
                self.shutdown_blocked = True
                self._show_control_request_received(
                    "关闭等待已超过时限：仍在等待当前调用收口（不会强制取消；"
                    "调用返回后会自动继续关闭）。"
                )

        def _on_reload_failed(self) -> None:
            self._reload_failed = True
            self._show_control_request_received(
                "无法从 checkpoint 读取当前状态；业务操作已停用。"
                "再次按 Ctrl-Q 仅重试读取状态。"
            )

        def _on_action_worker_finished(self, result, worker_error: str | None) -> None:
            # S1-B：UI 线程在对应 worker 完成（callable 已返回/抛错）后统一清除
            # 提交簿记，再 reload/render/close。意外 CANCELLED 不会进入本回调，
            # 簿记保持 busy，不会在无证据时收口。
            self._dispatch_pending = False
            # 已排队控制请求已到达安全边界（被 Runtime 消费或丢弃），解除合并。
            self._pending_control_kinds.clear()
            # S2-A：run_turn 已返回，关闭流式窗口；旧事件一律忽略。
            self._close_stream_window()
            self._last_worker_had_error = worker_error is not None
            try:
                self._refresh(result, worker_error)
            except Exception:
                self._on_reload_failed()
            finally:
                # 提交账只在完成时释放：refresh 已按 durable 事实消费并清草稿；
                # 未消费说明 action 未落盘（草稿保留，允许用户手动重发）。
                self._pending_submission = None

        @work(thread=True)
        def _execute(self, action: Action) -> object:
            result = None
            worker_error: str | None = None
            try:
                result = self._adapter.execute_once(action)
            except Exception as error:
                # worker 抛出（store.load 失败或 run_turn 的 invariant re-raise）：adapter
                # 的 finally 已复位 single-flight。Runtime 已把可恢复错误转成 RunResult，故能
                # 到这里的都是不可恢复的基础设施故障——不能让它传播成 Textual panic 把整个
                # 交互会话崩掉。但仍必须可观察：记录 bounded 失败到日志、向用户呈现有界错误
                # （不含原始异常敏感内容），随后回到 app 线程从 authoritative checkpoint 重新
                # 投影，让用户看到真实状态（action 未推进），而不是停在 worker 启动前的视图
                # （TUI_DESIGN 44/109）。绝不静默吞掉。
                worker_error = _bounded_worker_error(error)
                _LOG.error("tui worker failure: %s", worker_error)
                result = None
            # S1-B：worker 只返回有界 outcome；不在返回前触发 exit。UI 线程在完成
            # 通知里统一 reload/render/close。
            self.call_from_thread(self._on_action_worker_finished, result, worker_error)
            return result

        def _run_action(self, action: Action) -> None:
            # S1-B：提交即落位 busy 簿记——已排队尚未开始的 worker 也算 busy，
            # 阻止二次调度；完成回调统一清除。
            self._dispatch_pending = True
            # S2-A：打开本 dispatch 的流式展示窗口。
            self._open_stream_window(self._displayed_state)
            self._execute(action)

        def _displayed_control_identity(self) -> tuple[str, str, int] | None:
            # S1-C：界面意图对应的 conversation/Goal/revision；invocation 由
            # adapter 用最新 binding 核对。
            state = self._displayed_state
            if state is None or state.goal is None:
                return None
            return (state.conversation_id, state.goal.goal_id, state.goal.revision)

        def _request_control_safely(
            self,
            kind: ControlRequestKind,
            message: str | None = None,
        ):
            """S1-C：仅 exact 当前 binding 的 submit 成功才返回请求对象。

            无 Goal/binding、已关闭/被替换的 binding、store.load 失败都转成固定
            受控失败反馈并返回 None；不崩溃、不借未来 Goal 重绑重发、不把未入队
            请求当成功。同一 binding 的重复 pause/cancel 在 UI 合并；不同纠正内容
            不合并。
            """
            if (
                kind in {ControlRequestKind.PAUSE, ControlRequestKind.CANCEL}
                and kind.value in self._pending_control_kinds
            ):
                return "already-pending"
            try:
                request = self._adapter.request_control(
                    kind,
                    message=message,
                    expected=self._displayed_control_identity(),
                )
            except AdapterControlUnavailableError:
                self._show_control_request_received(
                    "当前没有可接受该请求的安全边界（无进行中的调用或绑定已变化）；"
                    "请求未发送。"
                )
                return None
            except Exception:
                self._show_control_request_received(
                    "控制请求暂时不可用（基础设施错误）；请求未发送。"
                )
                return None
            if kind in {ControlRequestKind.PAUSE, ControlRequestKind.CANCEL}:
                self._pending_control_kinds.add(kind.value)
            elif message is not None:
                # S2-A：纠正消费账——durable ControlReceipt 到达前保留原文与版本。
                self._pending_control_texts[request.request_id] = (
                    message,
                    self.draft_revision,
                )
            return request

        def _show_control_request_received(self, message: str) -> None:
            """只确认请求已入队；真正状态仍由 Runtime 在安全边界写入。"""

            from rich.text import Text

            self.query_one("#status", Static).update(Text(safe_display(message)))

        async def on_input_submitted(self, event: Input.Submitted) -> None:
            self._submit_text(event.value, allow_commands=True)

        def action_review_facts(self) -> None:
            # F3（S2-B）：冻结当前只读 snapshot 回看最近保留内容；打开/翻页/
            # 关闭不提交 action、不调用 provider/tool、不写状态、不随后台刷新
            # 跳页；Esc 返回时草稿与焦点原样保留。
            state = self._displayed_state
            if state is None:
                try:
                    state = self._adapter.load_view().snapshot.state
                except Exception:
                    self._show_control_request_received(
                        "无法读取当前状态；回看暂不可用。"
                    )
                    return
            pages, shown = build_f3_pages(state.facts)
            self.push_screen(build_facts_review_screen(pages, shown))

        def action_multiline_edit(self) -> None:
            # F4（S2-B）：多行编辑 modal；提交走与主输入同一 displayed-state
            # gate 与 SubmitMessage/control 路径；Esc 存草稿返回。
            self.push_screen(
                build_multiline_edit_screen(self.draft_text),
                self._on_multiline_result,
            )

        def _on_multiline_result(self, result) -> None:  # noqa: ANN001
            if result is None:
                return
            disposition, text = result
            if disposition == "send":
                # UI-01（2026-10-11）：任何发送尝试前先保存完整文本与本地版本。
                # 门槛拒绝（审批/暂停/busy/接管 pending）、排队未落盘、持久化前
                # 异常都不清空；只有 durable 接收证明（见
                # `_consume_pending_if_durably_accepted`）才消费该版本。
                self.draft_text = text
                self.draft_revision += 1
                # modal 内 slash 文本是普通消息内容：不解析命令。
                self._submit_text(text, allow_commands=False)
                return
            self.draft_text = text
            self.draft_revision += 1
            if "\n" in text:
                # 多行草稿留在 UI 本地，不压进单行 Input 丢换行；主界面显示
                # "N行草稿，F4继续编辑"。
                line_count = text.count("\n") + 1
                self._show_control_request_received(
                    f"已保存 {line_count} 行草稿；按 F4 继续编辑。"
                )
                return
            self._restore_draft()

        def _submit_text(self, value: str, *, allow_commands: bool) -> None:
            if self._busy():
                displayed = self._displayed_state
                if (
                    displayed is not None
                    and displayed.browser_takeover_pending is not None
                ):
                    return
                if value.strip():
                    queued = self._request_control_safely(
                        ControlRequestKind.CORRECT,
                        message=value,
                    )
                    if queued:
                        self._show_control_request_received(
                            "已收到新要求；当前步骤结束后会在安全边界应用。"
                        )
                return
            if self.closing_requested or self._reload_failed:
                return
            state = self._displayed_state
            if state is None:
                return
            command_result = (
                parse_process_command(
                    value,
                    state,
                    approval_time_factory=approval_time_factory,
                )
                if allow_commands
                else None
            )
            if command_result is not None:
                kind, payload = command_result
                if kind == "new_session":
                    # /new 允许后以 NEW_SESSION_REQUESTED 退出码交还装配层
                    # (main 会话循环)重建 conversation;不重启进程。
                    if self._busy():
                        return
                    from agent.cli.actions import NEW_SESSION_REQUESTED

                    self.exit(return_code=NEW_SESSION_REQUESTED)
                    return
                if kind == "action":
                    if (
                        isinstance(payload, ResolveApproval)
                        and self._permitted_artifact_approval_state() is None
                    ):
                        return
                    self._run_action(payload)
                elif kind == "leases":
                    from rich.text import Text

                    lines = ["Active process leases:"]
                    for index, lease in enumerate(payload):
                        lines.append(
                            f"[{index}] {lease.readable_command} · "
                            f"profile={lease.resource_profile} · "
                            f"uses left={lease.remaining_uses} · "
                            f"expires={lease.expires_at}"
                        )
                    lines.append(
                        "Revoke with /revoke <lease_id> or /revoke all "
                        "(ids via /leases --advanced)."
                    )
                    self.query_one("#status", Static).update(
                        Text(safe_display("\n".join(lines)))
                    )
                else:
                    from rich.text import Text

                    self.query_one("#status", Static).update(Text(safe_display(payload)))
                return
            state = self._permitted_state("submit")
            if state is None:
                state = self._permitted_state("correct_goal")
            if state is None:
                return
            if not value.strip():
                return
            # S2-A：已入 inbox 且未消费的同一纠正文本不重复发送；提交路径的
            # 重复保护只针对"排队等待"的纠正（提交在 busy 期间走纠正入口）。
            if any(
                message == value
                for message, _revision in self._pending_control_texts.values()
            ):
                self._show_control_request_received(
                    "尚不能确认上一次提交已被接收；草稿已保留，请勿重复发送。"
                )
                return
            action = build_submit(
                state, message=value, run_id=self._run_id_factory()
            )
            # UI-02：绑定本次 action 的确切 fact identity（conversation + action_seq），
            # 消费判定只认这条 fact，不认历史同文。
            self._pending_submission = (
                state.conversation_id,
                action.action_seq,
                value,
                self.draft_revision,
            )
            self._run_action(action)

        # --- keyboard action methods（全部经 projection gate）---

        async def action_approve(self) -> None:
            state = self._permitted_state("approve")
            if state is None:
                return
            req = state.active_run.pending_request
            self._run_action(
                build_resolve_approval(
                    state,
                    request_id=req.request_id,
                    binding_digest=req.binding_digest,
                    approved=True,
                    approved_at=approval_time_factory(),
                    defer_artifact_confirmation=(
                        req.artifact_confirmation_requirement is not None
                    ),
                )
            )

        async def action_approve_goal_target(self) -> None:
            state = self._permitted_state("approve")
            if state is None:
                return
            req = state.active_run.pending_request
            self._run_action(
                build_resolve_approval(
                    state,
                    request_id=req.request_id,
                    binding_digest=req.binding_digest,
                    approved=True,
                    approved_at=approval_time_factory(),
                    defer_artifact_confirmation=(
                        req.artifact_confirmation_requirement is not None
                    ),
                    authorize_goal_target=True,
                )
            )

        async def action_approve_goal_directory(self) -> None:
            state = self._permitted_state("approve")
            if state is None:
                return
            req = state.active_run.pending_request
            self._run_action(
                build_resolve_approval(
                    state,
                    request_id=req.request_id,
                    binding_digest=req.binding_digest,
                    approved=True,
                    approved_at=approval_time_factory(),
                    defer_artifact_confirmation=(
                        req.artifact_confirmation_requirement is not None
                    ),
                    authorize_goal_directory=True,
                )
            )

        async def action_reject(self) -> None:
            state = self._permitted_state("reject")
            if state is None:
                return
            req = state.active_run.pending_request
            self._run_action(
                build_resolve_approval(
                    state,
                    request_id=req.request_id,
                    binding_digest=req.binding_digest,
                    approved=False,
                )
            )

        async def action_mark_succeeded(self) -> None:
            state = self._permitted_state("mark_succeeded")
            if state is None:
                return
            req = state.active_run.pending_request
            self._run_action(
                build_resolve_recovery(
                    state,
                    request_id=req.request_id,
                    binding_digest=req.binding_digest,
                    resolution=RecoveryResolution.MARK_SUCCEEDED,
                )
            )

        async def action_mark_failed(self) -> None:
            state = self._permitted_state("mark_failed")
            if state is None:
                return
            req = state.active_run.pending_request
            self._run_action(
                build_resolve_recovery(
                    state,
                    request_id=req.request_id,
                    binding_digest=req.binding_digest,
                    resolution=RecoveryResolution.MARK_FAILED,
                )
            )

        async def action_record_observation_unknown(self) -> None:
            state = self._permitted_state("record_observation_unknown")
            if state is None:
                return
            self._run_action(build_recover_unknown_observation(state))

        async def action_resume(self) -> None:
            state = self._permitted_state("resume_goal")
            if state is not None:
                self._run_action(build_resume_goal(state))
                return
            state = self._permitted_state("resume")
            if state is None:
                return
            self._run_action(build_resume(state))

        async def action_cancel(self) -> None:
            displayed = self._displayed_state
            if displayed is not None and displayed.browser_takeover_pending is not None:
                state = self._permitted_state("browser_cancel")
                if state is not None:
                    self._run_action(build_cancel_browser_takeover(state))
                return
            if self._busy():
                queued = self._request_control_safely(ControlRequestKind.CANCEL)
                if queued:
                    self._show_control_request_received(
                        "已收到取消请求；正在等待当前模型或工具步骤到达安全边界，"
                        "此时尚未真正停止。"
                    )
                return
            state = self._permitted_state("cancel_goal")
            if state is not None:
                self._run_action(build_cancel_goal(state))
                return
            state = self._permitted_state("cancel")
            if state is None:
                return
            self._run_action(build_cancel(state))

        async def action_pause_goal(self) -> None:
            displayed = self._displayed_state
            if displayed is not None and displayed.browser_takeover_pending is not None:
                return
            if self._busy():
                queued = self._request_control_safely(ControlRequestKind.PAUSE)
                if queued:
                    self._show_control_request_received(
                        "已收到暂停请求；当前步骤结束后会在安全边界暂停。"
                    )
                return
            state = self._permitted_state("pause_goal")
            if state is not None:
                self._run_action(build_pause_goal(state))

        async def action_ack_provider(self) -> None:
            state = self._permitted_state("ack_provider")
            if state is not None:
                self._run_action(
                    build_ack_provider(state, acknowledged_at="operator-confirmed")
                )

        async def action_browser_done(self) -> None:
            state = self._permitted_state("browser_done")
            if state is not None:
                self._run_action(build_complete_browser_takeover(state))

        def action_toggle_source_refs(self) -> None:
            self._advanced_sources = not self._advanced_sources
            self._refresh()

    return FirstAgentTui()


def run_tui(adapter: TuiAdapter, *, run_id_factory: Callable[[], str]) -> int:
    app = build_app(adapter, run_id_factory=run_id_factory)
    app.run()
    # /new 经 self.exit(return_code=NEW_SESSION_REQUESTED) 退出时,App.run()
    # 返回该码,由 main 会话循环重建 conversation;正常退出仍为 0。
    return int(app.return_code or 0)
