"""Textual-free single-flight TUI adapter。

只提供同步 ``execute_once``、single-flight gate、thread-safe event queue 与只读
``load_view``。adapter 自己不创建 thread；唯一 production thread owner 是 Textual worker，
它只调用一次 ``execute_once``。event sink 只把 immutable event 入队，禁止同步重入 Runtime。
不导入 Textual，也不做任何业务决策。
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from uuid import uuid4

from agent.runtime.contracts import (
    Action,
    ControlInboxRequest,
    ControlRequestKind,
    LoadedSnapshot,
    RunResult,
    RuntimeEvent,
)
from agent.runtime.control import ControlInbox
from agent.runtime.views import GoalView, project_goal_view


class AdapterBusyError(RuntimeError):
    """同一 conversation 同时只能有一个 worker（single-flight）。"""


class AdapterControlUnavailableError(RuntimeError):
    """S1-C：无活跃 invocation/binding 可接受 cooperative control。

    窄失败类型：binding 缺失/已关闭/被替换、store.load 等基础设施失败、inbox
    exact 绑定校验失败都归入本类型；UI 据此给出固定受控反馈，不重试、不借
    未来 Goal 重绑重发，也不向用户泄漏原始异常内容。
    """


class QueueingEventSink:
    """thread-safe event queue；``emit`` 不可同步重入 Runtime。"""

    def __init__(self) -> None:
        self._queue: queue.Queue[RuntimeEvent] = queue.Queue()

    def emit(self, event: RuntimeEvent) -> None:
        self._queue.put(event)

    def drain(self) -> list[RuntimeEvent]:
        drained: list[RuntimeEvent] = []
        while True:
            try:
                drained.append(self._queue.get_nowait())
            except queue.Empty:
                return drained


@dataclass(frozen=True, slots=True)
class TuiView:
    """authoritative 只读 view（startup/reopen/worker 结果共用）。"""

    snapshot: LoadedSnapshot
    goal: GoalView


class TuiAdapter:
    def __init__(
        self,
        runtime,
        store,
        *,
        event_sink: QueueingEventSink | None = None,
        control_inbox: ControlInbox | None = None,
    ) -> None:
        self._runtime = runtime
        self._store = store
        self.event_sink = event_sink or QueueingEventSink()
        self._control_inbox = control_inbox
        self._active_lock = threading.Lock()
        self._active = False

    @property
    def is_active(self) -> bool:
        with self._active_lock:
            return self._active

    def load_view(self) -> TuiView:
        """startup/reopen 的只读 authoritative load：不提交 action，不调用 provider/tool。"""
        snapshot = self._store.load()
        return TuiView(snapshot=snapshot, goal=project_goal_view(snapshot.state))

    def execute_once(self, action: Action) -> RunResult:
        with self._active_lock:
            if self._active:
                raise AdapterBusyError("a runtime worker is already active for this conversation")
            self._active = True
        try:
            snapshot = self._store.load()
            return self._runtime.run_turn(action, snapshot)
        finally:
            with self._active_lock:
                self._active = False

    def request_control(
        self,
        kind: ControlRequestKind,
        *,
        message: str | None = None,
        expected: tuple[str, str, int] | None = None,
    ) -> ControlInboxRequest:
        """向活跃 invocation 提交绑定请求；durable mutation 仍只由 Runtime 完成。

        ``expected=(conversation_id, goal_id, goal_revision)`` 来自界面当前展示的
        意图：adapter 只用它核对最新 binding，绝不把请求改绑到另一个（未来的）
        Goal；已关闭/被替换的 binding 与基础设施失败都抛窄的
        ``AdapterControlUnavailableError``，不泄漏原始异常内容。
        """

        if self._control_inbox is None:
            raise AdapterControlUnavailableError(
                "active goal controls are not configured"
            )
        try:
            state = self._store.load().state
        except Exception as error:
            raise AdapterControlUnavailableError(
                "control unavailable: could not read current state"
            ) from error
        binding = self._control_inbox.current(state.conversation_id)
        if binding is None:
            raise AdapterControlUnavailableError(
                "no active goal invocation accepts cooperative control"
            )
        if expected is not None and (
            binding.conversation_id != expected[0]
            or binding.goal_id != expected[1]
            or binding.goal_revision != expected[2]
        ):
            raise AdapterControlUnavailableError(
                "the displayed goal binding is no longer the active invocation"
            )
        request = ControlInboxRequest(
            request_id=f"tui-control:{uuid4()}",
            kind=kind,
            conversation_id=binding.conversation_id,
            goal_id=binding.goal_id,
            goal_revision=binding.goal_revision,
            invocation_id=binding.invocation_id,
            message=message,
        )
        try:
            self._control_inbox.submit(request)
        except ValueError as error:
            raise AdapterControlUnavailableError(
                "control request does not bind the active invocation"
            ) from error
        return request
