"""同步 Runtime 的 process-local 控制收件箱；它从不直接修改 durable state。"""

from __future__ import annotations

import threading

from agent.runtime.contracts import (
    ControlBinding,
    ControlInboxRequest,
    ControlRequestKind,
)

__all__ = [
    "ControlBinding",
    "ControlInbox",
    "ControlInboxRequest",
    "ControlRequestKind",
]


class ControlInbox:
    """单进程线程安全队列；open/submit/poll 都不持有 ConversationState 引用。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bindings: dict[str, ControlBinding] = {}
        self._requests: list[ControlInboxRequest] = []

    def open(self, binding: ControlBinding) -> None:
        with self._lock:
            current = self._bindings.get(binding.conversation_id)
            if current is not None and current != binding:
                raise RuntimeError("control inbox already has an active invocation")
            self._bindings[binding.conversation_id] = binding

    def current(self, conversation_id: str) -> ControlBinding | None:
        with self._lock:
            return self._bindings.get(conversation_id)

    def submit(self, request: ControlInboxRequest) -> None:
        with self._lock:
            binding = self._bindings.get(request.conversation_id)
            if binding is None or binding != ControlBinding(
                conversation_id=request.conversation_id,
                goal_id=request.goal_id,
                goal_revision=request.goal_revision,
                invocation_id=request.invocation_id,
            ):
                raise ValueError("control request does not bind the active invocation and goal")
            if any(item.request_id == request.request_id for item in self._requests):
                raise ValueError("control request_id must be unique")
            self._requests.append(request)

    def poll(self, binding: ControlBinding) -> ControlInboxRequest | None:
        with self._lock:
            if self._bindings.get(binding.conversation_id) != binding:
                return None
            for index, request in enumerate(self._requests):
                if (
                    request.conversation_id == binding.conversation_id
                    and request.goal_id == binding.goal_id
                    and request.goal_revision == binding.goal_revision
                    and request.invocation_id == binding.invocation_id
                ):
                    return self._requests.pop(index)
            return None

    def close(self, binding: ControlBinding) -> None:
        with self._lock:
            if self._bindings.get(binding.conversation_id) == binding:
                del self._bindings[binding.conversation_id]
            self._requests = [
                request
                for request in self._requests
                if not (
                    request.conversation_id == binding.conversation_id
                    and request.invocation_id == binding.invocation_id
                )
            ]
