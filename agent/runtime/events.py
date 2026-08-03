"""Best-effort Runtime Event sinks。"""

from __future__ import annotations

from collections.abc import Callable
from threading import local

from agent.runtime.contracts import RuntimeEvent


class EventReentryError(RuntimeError):
    pass


class CollectingEventSink:
    def __init__(self) -> None:
        self.events: list[RuntimeEvent] = []

    def emit(self, event: RuntimeEvent) -> None:
        self.events.append(event)


class CallbackEventSink:
    """把事件交给同步 callback，同时拒绝 callback 重入同一个 sink。"""

    def __init__(self, callback: Callable[[RuntimeEvent], None]) -> None:
        self._callback = callback
        self._guard = local()

    def emit(self, event: RuntimeEvent) -> None:
        if getattr(self._guard, "active", False):
            raise EventReentryError("event sink cannot synchronously re-enter")
        self._guard.active = True
        try:
            self._callback(event)
        finally:
            self._guard.active = False

