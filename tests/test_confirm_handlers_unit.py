"""confirm_handlers 纯单元边界测试。

这些测试保护 `confirm_handlers` 只做确认流分流，不承载 memory / tool /
checkpoint 的业务细节。Memory confirmation 必须委托给 memory_interaction；
普通 awaiting_user_input 回复必须继续通过 TransitionResult 边界恢复状态，
避免 handler 在重构中重新散落 state mutation。
"""

from __future__ import annotations

from types import SimpleNamespace

from agent.confirm_handlers import ConfirmationContext, handle_user_input_step
from agent.transitions import TransitionResult


def _make_context(*, awaiting_kind: str | None = None, memory_runtime=None):
    """构造最小 ConfirmationContext，测试只关注分流边界。"""

    pending = {"awaiting_kind": awaiting_kind} if awaiting_kind is not None else None
    state = SimpleNamespace(
        task=SimpleNamespace(
            status="awaiting_user_input",
            pending_user_input_request=pending,
            current_plan={"steps": [{"description": "collect user input"}]},
            current_step_index=0,
            confirm_each_step=False,
        ),
        conversation=SimpleNamespace(messages=[]),
        reset_task=lambda: None,
    )
    turn_state = SimpleNamespace(on_runtime_event=lambda _event: None)
    return ConfirmationContext(
        state=state,
        turn_state=turn_state,
        client=None,
        model_name="test-model",
        continue_fn=lambda _turn_state: "continued-from-loop",
        memory_runtime=memory_runtime,
    )


def test_memory_confirmation_delegates_to_memory_interaction(monkeypatch):
    """memory_confirmation 只能按 awaiting_kind 委托，不在 handler 里写 store。"""

    calls = []

    def fake_handle(user_input, ctx, *, memory_runtime, on_runtime_event, dispatcher=None):
        calls.append((user_input, ctx, memory_runtime, on_runtime_event))
        return "memory-confirmation-result"

    import agent.memory_interaction as memory_interaction

    monkeypatch.setattr(
        memory_interaction,
        "handle_memory_confirmation_reply",
        fake_handle,
    )
    runtime = object()
    ctx = _make_context(awaiting_kind="memory_confirmation", memory_runtime=runtime)

    assert handle_user_input_step("accept", ctx) == "memory-confirmation-result"
    assert calls and calls[0][0] == "accept"
    assert calls[0][2] is runtime


def test_memory_inline_confirmation_delegates_with_store(monkeypatch):
    """memory_inline_confirmation 分支只传递 store，不解析 memory metadata。"""

    calls = []

    def fake_handle(user_input, ctx, *, store, on_runtime_event):
        calls.append((user_input, ctx, store, on_runtime_event))
        return "inline-confirmation-result"

    import agent.memory_interaction as memory_interaction

    monkeypatch.setattr(
        memory_interaction,
        "handle_inline_confirmation_reply",
        fake_handle,
    )
    store = object()
    runtime = SimpleNamespace(_store=store)
    ctx = _make_context(
        awaiting_kind="memory_inline_confirmation",
        memory_runtime=runtime,
    )

    assert handle_user_input_step("reject", ctx) == "inline-confirmation-result"
    assert calls and calls[0][2] is store


def test_unknown_awaiting_kind_uses_generic_transition(monkeypatch):
    """未知 awaiting_kind 不能被误处理成 memory 分支，必须走 TransitionResult。

    Global P3 Hardening 后，handle_user_input_step 已迁移到
    agent.confirmation.user_input；mock 路径同步更新。
    """

    resolution = SimpleNamespace(kind="collect_input_answer", content="answer")
    calls = []

    monkeypatch.setattr(
        "agent.confirmation.user_input.resolve_user_input",
        lambda state, user_input: resolution,
    )

    def fake_transition(*, state, messages, resolution):
        calls.append((state, messages, resolution))
        return TransitionResult(should_continue_loop=True)

    monkeypatch.setattr(
        "agent.confirmation.user_input.apply_user_replied_transition",
        fake_transition,
    )
    ctx = _make_context(awaiting_kind="future_kind")

    assert handle_user_input_step("answer", ctx) == "continued-from-loop"
    assert calls and calls[0][2] is resolution
