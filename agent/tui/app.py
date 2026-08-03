"""Optional Textual TUI app（lazy import）。

base install、headless、普通 CLI 不导入 Textual。App 表达全部 typed actions：
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
    build_cancel_goal,
    build_pause_goal,
    build_resolve_approval,
    build_resolve_recovery,
    build_resume,
    build_resume_goal,
    build_submit,
)
from agent.runtime.contracts import (
    Action,
    ControlRequestKind,
    ConversationState,
    RecoveryResolution,
)
from agent.tui.adapter import TuiAdapter
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
):
    _require_textual()
    from textual import work
    from textual.app import App, ComposeResult
    from textual.containers import Vertical
    from textual.widgets import Footer, Input, Static

    class FocusStatic(Static):
        """可聚焦的只读区域，用于 approval/recovery 表单获得键盘焦点。"""

        can_focus = True

    class FirstAgentTui(App):
        CSS = ""
        BINDINGS = [
            ("a", "approve", "Approve"),
            ("r", "reject", "Reject"),
            ("s", "mark_succeeded", "Mark Succeeded"),
            ("f", "mark_failed", "Mark Failed"),
            ("u", "resume", "Resume"),
            ("p", "pause_goal", "Pause Goal"),
            ("c", "cancel", "Cancel"),
            ("d", "ack_provider", "Acknowledge Provider"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self._adapter = adapter
            self._run_id_factory = run_id_factory
            self.close_deadline_seconds = close_deadline_seconds
            self.projection: TuiProjection | None = None
            self.form_text: str = ""
            # 最近一次 worker 失败的有界提示（observability）；成功刷新会清回 None。
            self._last_worker_error: str | None = None
            # approval preview 是否超过显示 cap：True 时 approve 被 fail-closed gate 屏蔽。
            self._preview_too_large: bool = False
            # lifecycle：active worker 收到 quit 后进入 closing_requested；不能安全收口则
            # shutdown_blocked，且不提前关闭 resources。
            self.closing_requested = False
            self.shutdown_blocked = False

        def compose(self) -> ComposeResult:
            yield Vertical(
                Static("", id="status"),
                FocusStatic("", id="form"),
                Input(placeholder="message (Enter to submit)", id="message"),
                Static("", id="action_hints"),
                Footer(),
            )

        def on_mount(self) -> None:
            self._refresh()

        def _current_projection(self) -> TuiProjection:
            return project(self._adapter.load_view().snapshot.state)

        def _refresh(self, result=None, worker_error: str | None = None) -> None:
            from rich.text import Text

            # worker 失败提示仅在 worker 完成那次刷新时传入；其它刷新（mount/close 等）
            # 传 None 以清除上次提示，避免 stale 错误长期滞留。
            self._last_worker_error = worker_error

            view = self._adapter.load_view()
            projection = project(view.snapshot.state, result)
            self.projection = projection

            main_text = projection.main_text
            if result is not None:
                label = run_status_label(result.status)
                main_text = f"{label}: {result.message or projection.main_text}"
            if worker_error is not None:
                # 用户可见的有界失败提示（不含原始异常敏感内容）；状态来自 authoritative
                # checkpoint 重新投影（action 未推进）。
                main_text = worker_error
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
                escaped_form = safe_display(
                    "approval preview exceeds display cap; approve disabled "
                    "— reject or reduce the effect"
                )
            self.query_one("#form", Static).update(Text(escaped_form))

            # preview 过大时从 hints 移除 approve，避免误导用户以为可批准。
            display_actions = projection.actions
            if self._preview_too_large:
                display_actions = tuple(a for a in display_actions if a != "approve")
            hints = self._format_hints(display_actions)
            self.query_one("#action_hints", Static).update(Text(safe_display(hints)))

            msg_input = self.query_one("#message", Input)
            if (
                "submit" in projection.actions or "correct_goal" in projection.actions
            ) and not self.closing_requested:
                msg_input.disabled = False
                msg_input.value = ""
                msg_input.focus()
            else:
                msg_input.disabled = True
                # approval/recovery 表单聚焦；其它非 submit 状态取消 input 焦点。
                if projection.form_kind is not None:
                    self.query_one("#form", FocusStatic).focus()

            # events 只 advisory：drain queue 后不写入 terminal renderer。
            self._adapter.event_sink.drain()

            # closing 收口：worker 已安全返回且 reload 完 authoritative checkpoint 后才退出。
            if (
                self.closing_requested
                and not self.shutdown_blocked
                and not self._adapter.is_active
            ):
                self.exit()

        @staticmethod
        def _render_form(projection: TuiProjection) -> str:
            if not projection.form_fields:
                return ""
            return "\n".join(f"{label}: {value}" for label, value in projection.form_fields)

        @staticmethod
        def _format_hints(actions: tuple[str, ...]) -> str:
            labels = {
                "submit": "Enter: submit",
                "approve": "a: approve",
                "reject": "r: reject",
                "mark_succeeded": "s: mark succeeded",
                "mark_failed": "f: mark failed",
                "resume": "u: resume",
                "cancel": "c: cancel",
                "pause_goal": "p: pause goal",
                "resume_goal": "u: resume goal",
                "correct_goal": "Enter: correct goal",
                "cancel_goal": "c: cancel goal",
                "ack_provider": "d: acknowledge provider",
            }
            parts = [labels.get(a, a) for a in actions]
            return " | ".join(parts) if parts else "no actions"

        def _permitted_state(self, name: str) -> ConversationState | None:
            """只有当前 authoritative 投影允许、且未进入 closing 时才返回 state。"""
            if self.closing_requested or self.shutdown_blocked:
                return None
            if self._adapter.is_active:
                # worker 在跑：禁止新 action，避免撞 single-flight 或绕过 unknown effect。
                return None
            if self._preview_too_large and name == "approve":
                # approval preview 超过显示 cap → fail closed：approve 明确不可批准，
                # 不能让用户批准无法完整查看关键内容的 effect。reject 不受影响（不执行 effect）。
                return None
            state = self._adapter.load_view().snapshot.state
            projection = project(state)
            if name not in projection.actions:
                return None
            return state

        def request_close(self) -> None:
            """active worker 收到 quit 时的优雅收口入口。

            不 cancel worker；若 worker 已返回则立即 reload authoritative checkpoint
            再退出，否则进入 closing_requested 并 arm deadline——deadline 超时仍未收口
            则 shutdown_blocked，UI 与 resources 保持存活，不 force-exit。
            """
            if self.shutdown_blocked:
                return
            self.closing_requested = True
            if self._adapter.is_active:
                self.set_timer(self.close_deadline_seconds, self._on_close_deadline)
            else:
                self._safe_exit()

        def action_quit(self) -> None:  # type: ignore[override]
            # 覆盖默认 quit：走优雅收口，避免在 active worker 上 force-exit。
            self.request_close()

        def _on_close_deadline(self) -> None:
            if self.closing_requested and self._adapter.is_active:
                self.shutdown_blocked = True
                self._refresh()

        def _safe_exit(self) -> None:
            self._refresh()
            self.exit()

        @work(thread=True, exclusive=True)
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
            # worker 完成后回到 app 线程刷新；handler 不阻塞 await，UI 在 worker 在跑时
            # 仍可响应（request_close 才能观察到 closing_requested）。
            self.call_from_thread(self._refresh, result, worker_error)
            return result

        def _run_action(self, action: Action) -> None:
            self._execute(action)

        async def on_input_submitted(self, event: Input.Submitted) -> None:
            if self._adapter.is_active:
                if event.value.strip():
                    self._adapter.request_control(
                        ControlRequestKind.CORRECT,
                        message=event.value,
                    )
                return
            state = self._permitted_state("submit")
            if state is None:
                state = self._permitted_state("correct_goal")
            if state is None:
                return
            if not event.value.strip():
                return
            action = build_submit(
                state, message=event.value, run_id=self._run_id_factory()
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
            if self._adapter.is_active:
                self._adapter.request_control(ControlRequestKind.CANCEL)
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
            if self._adapter.is_active:
                self._adapter.request_control(ControlRequestKind.PAUSE)
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

    return FirstAgentTui()


def run_tui(adapter: TuiAdapter, *, run_id_factory: Callable[[], str]) -> int:
    app = build_app(adapter, run_id_factory=run_id_factory)
    app.run()
    return 0
