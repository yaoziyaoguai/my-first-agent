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
    ) -> ControlInboxRequest:
        """向活跃 invocation 提交绑定请求；durable mutation 仍只由 Runtime 完成。"""

        if self._control_inbox is None:
            raise RuntimeError("active goal controls are not configured")
        state = self._store.load().state
        binding = self._control_inbox.current(state.conversation_id)
        if binding is None:
            raise RuntimeError("no active goal invocation accepts cooperative control")
        request = ControlInboxRequest(
            request_id=f"tui-control:{uuid4()}",
            kind=kind,
            conversation_id=binding.conversation_id,
            goal_id=binding.goal_id,
            goal_revision=binding.goal_revision,
            invocation_id=binding.invocation_id,
            message=message,
        )
        self._control_inbox.submit(request)
        return request
