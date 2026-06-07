"""Phase 3 U1 memory transition 的真实 core.chat 覆盖。"""

from __future__ import annotations

import pytest

from tests.conftest import FakeAnthropicClient
from tests.test_main_loop import _reset_core_module


@pytest.mark.parametrize("origin_status", ["idle", "running"])
def test_w08_core_chat_memory_confirmation_applies_before_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    origin_status: str,
):
    from agent import core
    from agent.memory_runtime import MemoryRuntime
    from agent.memory_store import InMemoryMemoryStore

    state = _reset_core_module(monkeypatch, FakeAnthropicClient(responses=[]))
    state.task.status = origin_status
    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    monkeypatch.setattr(core, "_memory_runtime", runtime)
    save_sources: list[str] = []
    monkeypatch.setattr(
        core,
        "_dispatch_checkpoint_save",
        lambda _dispatcher, _state, source, **_kwargs: save_sources.append(source),
    )
    events: list = []

    reply = core.chat(
        "remember that I like blue",
        on_runtime_event=events.append,
    )

    assert reply == ""
    assert state.task.status == "awaiting_user_input"
    assert state.task.pending_user_input_request["_origin_status"] == origin_status
    assert save_sources == ["memory_confirmation"]
    assert len(events) == 1


def test_w08_core_chat_denied_does_not_overwrite_pending_save_or_emit(
    monkeypatch: pytest.MonkeyPatch,
):
    from agent import core
    from agent.memory_runtime import MemoryRuntime
    from agent.memory_store import InMemoryMemoryStore

    state = _reset_core_module(monkeypatch, FakeAnthropicClient(responses=[]))
    state.task.status = "done"
    original_pending = {"awaiting_kind": "existing", "sentinel": True}
    state.task.pending_user_input_request = original_pending
    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    monkeypatch.setattr(core, "_memory_runtime", runtime)
    save_sources: list[str] = []
    monkeypatch.setattr(
        core,
        "_dispatch_checkpoint_save",
        lambda _dispatcher, _state, source, **_kwargs: save_sources.append(source),
    )
    events: list = []

    reply = core.chat(
        "remember that I like blue",
        on_runtime_event=events.append,
    )

    assert reply == ""
    assert state.task.status == "done"
    assert state.task.pending_user_input_request is original_pending
    assert save_sources == []
    assert events == []
