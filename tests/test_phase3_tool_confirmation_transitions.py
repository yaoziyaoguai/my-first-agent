"""Phase 3 tool confirmation 两个真实入口的副作用顺序测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.state import create_agent_state
from agent.tool_executor import AWAITING_USER, TRANSITION_DENIED


def _block():
    return SimpleNamespace(
        id="toolu_phase3_confirm",
        name="dangerous_tool",
        input={"path": "workspace/output.txt"},
        type="tool_use",
    )


def _turn_state():
    return SimpleNamespace(
        round_tool_traces=[],
        on_display_event=lambda _event: None,
        on_runtime_event=None,
        on_trace_event=None,
    )


@pytest.mark.parametrize("origin_status", ["idle", "running"])
def test_tool_executor_confirmation_applies_before_event_and_saves_last(
    monkeypatch,
    origin_status,
):
    import agent.tool_executor as executor

    state = create_agent_state(system_prompt="test")
    state.task.status = origin_status
    order = []
    monkeypatch.setattr(executor, "_normalize_tool_name", lambda name: name)
    monkeypatch.setattr(executor, "is_meta_tool", lambda _name: False)
    monkeypatch.setattr(executor, "needs_tool_confirmation", lambda *_args: True)
    monkeypatch.setattr(
        executor,
        "execute_tool",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("confirmation entry must not execute tool")
        ),
    )
    monkeypatch.setattr(
        executor,
        "emit_tool_audit_event",
        lambda **_kwargs: order.append("audit"),
    )
    monkeypatch.setattr(
        executor,
        "emit_display_event",
        lambda *_args, **_kwargs: order.append("display"),
    )
    monkeypatch.setattr(
        executor,
        "save_checkpoint",
        lambda *_args, **_kwargs: order.append("save"),
    )

    result = executor.execute_single_tool(
        _block(),
        state=state,
        turn_state=_turn_state(),
        turn_context={},
        messages=state.conversation.messages,
    )

    assert result == AWAITING_USER
    assert state.task.status == "awaiting_tool_confirmation"
    assert state.task.pending_tool == {
        "tool_use_id": "toolu_phase3_confirm",
        "tool": "dangerous_tool",
        "input": {"path": "workspace/output.txt"},
    }
    assert order == ["audit", "display", "save"]


def test_tool_executor_confirmation_denied_has_no_side_effects(monkeypatch):
    import agent.tool_executor as executor

    state = create_agent_state(system_prompt="test")
    state.task.status = "done"
    original_pending = {"existing": True}
    state.task.pending_tool = original_pending
    messages = list(state.conversation.messages)
    calls = []
    monkeypatch.setattr(executor, "_normalize_tool_name", lambda name: name)
    monkeypatch.setattr(executor, "is_meta_tool", lambda _name: False)
    monkeypatch.setattr(executor, "needs_tool_confirmation", lambda *_args: True)
    monkeypatch.setattr(executor, "save_checkpoint", lambda *_a, **_k: calls.append("save"))
    monkeypatch.setattr(executor, "emit_tool_audit_event", lambda **_k: calls.append("audit"))
    monkeypatch.setattr(executor, "emit_display_event", lambda *_a, **_k: calls.append("display"))
    monkeypatch.setattr(
        executor,
        "execute_tool",
        lambda *_args, **_kwargs: calls.append("execute"),
    )

    result = executor.execute_single_tool(
        _block(),
        state=state,
        turn_state=_turn_state(),
        turn_context={},
        messages=state.conversation.messages,
    )

    assert result == TRANSITION_DENIED
    assert state.task.status == "done"
    assert state.task.pending_tool == original_pending
    assert state.conversation.messages == messages
    assert calls == []


class _ConfirmationDispatcher:
    def __init__(self, order):
        self.order = order
        self.action_log = []

    def route_from_runtime_loop(self, request, **_kwargs):
        action_type = str(request.action_type)
        if action_type == "tool.gate":
            self.order.append("gate")
            return SimpleNamespace(
                payload={
                    "gate_disposition": "confirmation_required",
                    "rejection_reason": None,
                    "evidence_extra": {},
                }
            )
        self.order.append("result")
        return SimpleNamespace(payload={})


@pytest.mark.parametrize("origin_status", ["idle", "running"])
def test_mediator_confirmation_routes_event_then_saves_once(
    monkeypatch,
    origin_status,
):
    import agent.checkpoint as checkpoint
    import agent.tool_runtime_mediator as mediator_module

    state = create_agent_state(system_prompt="test")
    state.task.status = origin_status
    order = []
    monkeypatch.setattr(
        checkpoint,
        "save_checkpoint",
        lambda *_args, **_kwargs: order.append("save"),
    )
    monkeypatch.setattr(
        mediator_module,
        "execute_single_tool",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("confirmation entry must not execute tool")
        ),
    )
    mediator = mediator_module.ToolRuntimeMediator(
        _ConfirmationDispatcher(order),
        state=state,
        turn_state=_turn_state(),
        turn_context={},
        messages=state.conversation.messages,
    )

    result = mediator.mediate(_block())

    assert result == AWAITING_USER
    assert state.task.status == "awaiting_tool_confirmation"
    assert state.task.pending_tool["tool_use_id"] == "toolu_phase3_confirm"
    assert order == ["gate", "result", "save"]


def test_mediator_confirmation_denied_has_no_side_effects(monkeypatch):
    import agent.checkpoint as checkpoint
    import agent.tool_runtime_mediator as mediator_module

    state = create_agent_state(system_prompt="test")
    state.task.status = "done"
    original_pending = {"existing": True}
    state.task.pending_tool = original_pending
    order = []
    monkeypatch.setattr(
        checkpoint,
        "save_checkpoint",
        lambda *_args, **_kwargs: order.append("save"),
    )
    monkeypatch.setattr(
        mediator_module,
        "execute_single_tool",
        lambda *_args, **_kwargs: order.append("execute"),
    )
    mediator = mediator_module.ToolRuntimeMediator(
        _ConfirmationDispatcher(order),
        state=state,
        turn_state=_turn_state(),
        turn_context={},
        messages=state.conversation.messages,
    )

    result = mediator.mediate(_block())

    assert result == TRANSITION_DENIED
    assert state.task.status == "done"
    assert state.task.pending_tool == original_pending
    assert order == ["gate"]
