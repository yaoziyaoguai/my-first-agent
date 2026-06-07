"""Phase 3 task-runtime transition 与真实 caller 副作用顺序测试。"""

from __future__ import annotations

from types import SimpleNamespace

from agent.confirmation.dispatcher import ConfirmationContext
from agent.input_resolution import COLLECT_INPUT_ANSWER, InputResolution
from agent.state import create_agent_state


def _plan(step_count: int = 2) -> dict:
    return {
        "goal": "demo",
        "steps": [
            {
                "step_id": f"step-{index + 1}",
                "title": f"step {index + 1}",
                "description": "demo",
                "step_type": "report",
            }
            for index in range(step_count)
        ],
    }


def _state(*, status: str, step_count: int = 2, step_index: int = 0):
    state = create_agent_state(system_prompt="test")
    state.task.status = status
    state.task.current_plan = _plan(step_count)
    state.task.current_step_index = step_index
    state.task.confirm_each_step = False
    return state


def _mark_current_step_complete(state) -> None:
    state.task.tool_execution_log["mark"] = {
        "tool": "mark_step_complete",
        "input": {
            "completion_score": 100,
            "summary": "done",
            "outstanding": "",
        },
        "step_index": state.task.current_step_index,
    }


def _checkpoint_spy(monkeypatch, module):
    calls = {"save": 0, "clear": 0}
    monkeypatch.setattr(
        module,
        "save_checkpoint",
        lambda *_args, **_kwargs: calls.__setitem__("save", calls["save"] + 1),
    )
    monkeypatch.setattr(
        module,
        "clear_checkpoint",
        lambda *_args, **_kwargs: calls.__setitem__("clear", calls["clear"] + 1),
    )
    return calls


def test_collect_answer_advances_then_saves_once(monkeypatch):
    from agent import checkpoint
    from agent.transitions import apply_user_replied_transition

    calls = _checkpoint_spy(monkeypatch, checkpoint)
    state = _state(status="awaiting_user_input")
    result = apply_user_replied_transition(
        state=state,
        messages=state.conversation.messages,
        resolution=InputResolution(
            kind=COLLECT_INPUT_ANSWER,
            content="answer",
            should_advance_step=True,
        ),
    )

    assert result.should_continue_loop is True
    assert state.task.status == "running"
    assert state.task.current_step_index == 1
    assert len(state.conversation.messages) == 1
    assert calls == {"save": 1, "clear": 0}


def test_collect_answer_last_step_clears_once_without_save(monkeypatch):
    from agent import checkpoint
    from agent.transitions import apply_user_replied_transition

    calls = _checkpoint_spy(monkeypatch, checkpoint)
    state = _state(status="awaiting_user_input", step_count=1)
    result = apply_user_replied_transition(
        state=state,
        messages=state.conversation.messages,
        resolution=InputResolution(
            kind=COLLECT_INPUT_ANSWER,
            content="answer",
            should_advance_step=True,
        ),
    )

    assert result.should_continue_loop is False
    assert "任务已完成" in result.reply
    assert state.task.status == "idle"
    assert calls == {"save": 0, "clear": 1}


def test_collect_answer_denied_has_no_side_effects(monkeypatch):
    from agent import checkpoint
    from agent.transitions import apply_user_replied_transition

    calls = _checkpoint_spy(monkeypatch, checkpoint)
    state = _state(status="idle")
    before_messages = list(state.conversation.messages)

    result = apply_user_replied_transition(
        state=state,
        messages=state.conversation.messages,
        resolution=InputResolution(
            kind=COLLECT_INPUT_ANSWER,
            content="answer",
            should_advance_step=True,
        ),
    )

    assert result.should_continue_loop is False
    assert "状态迁移失败" in result.reply
    assert state.task.status == "idle"
    assert state.task.current_step_index == 0
    assert state.conversation.messages == before_messages
    assert calls == {"save": 0, "clear": 0}


def _step_context(state, continue_calls):
    return ConfirmationContext(
        state=state,
        turn_state=SimpleNamespace(),
        client=None,
        model_name="test",
        continue_fn=lambda _turn_state: continue_calls.append(1) or "continued",
    )


def test_step_confirmation_advances_then_saves_once(monkeypatch):
    import agent.confirmation.plan as plan_confirmation

    calls = _checkpoint_spy(monkeypatch, plan_confirmation)
    state = _state(status="awaiting_step_confirmation")
    continues = []

    reply = plan_confirmation.handle_step_confirmation(
        "y",
        _step_context(state, continues),
    )

    assert reply == "continued"
    assert state.task.status == "running"
    assert state.task.current_step_index == 1
    assert len(state.conversation.messages) == 1
    assert calls == {"save": 1, "clear": 0}
    assert continues == [1]


def test_step_confirmation_last_step_clears_once_without_save(monkeypatch):
    import agent.confirmation.plan as plan_confirmation

    calls = _checkpoint_spy(monkeypatch, plan_confirmation)
    state = _state(status="awaiting_step_confirmation", step_count=1)
    continues = []

    reply = plan_confirmation.handle_step_confirmation(
        "y",
        _step_context(state, continues),
    )

    assert "任务已完成" in reply
    assert state.task.status == "idle"
    assert calls == {"save": 0, "clear": 1}
    assert continues == []


def test_step_confirmation_denied_has_no_side_effects(monkeypatch):
    import agent.confirmation.plan as plan_confirmation

    calls = _checkpoint_spy(monkeypatch, plan_confirmation)
    state = _state(status="idle")
    continues = []
    before_messages = list(state.conversation.messages)

    reply = plan_confirmation.handle_step_confirmation(
        "y",
        _step_context(state, continues),
    )

    assert "状态迁移失败" in reply
    assert state.task.status == "idle"
    assert state.task.current_step_index == 0
    assert state.conversation.messages == before_messages
    assert calls == {"save": 0, "clear": 0}
    assert continues == []


def test_running_handler_advances_then_saves_once(monkeypatch):
    import agent.response_handlers as response_handlers

    calls = _checkpoint_spy(monkeypatch, response_handlers)
    state = _state(status="running")
    _mark_current_step_complete(state)

    reply = response_handlers._maybe_advance_step(state)

    assert reply is None
    assert state.task.status == "running"
    assert state.task.current_step_index == 1
    assert calls == {"save": 1, "clear": 0}


def test_running_handler_last_step_clears_once_without_save(monkeypatch):
    import agent.response_handlers as response_handlers

    calls = _checkpoint_spy(monkeypatch, response_handlers)
    state = _state(status="running", step_count=1)
    _mark_current_step_complete(state)

    reply = response_handlers._maybe_advance_step(state)

    assert reply == "好的，任务已完成。"
    assert state.task.status == "idle"
    assert calls == {"save": 0, "clear": 1}


def test_running_handler_denied_has_no_side_effects(monkeypatch):
    import agent.response_handlers as response_handlers

    calls = _checkpoint_spy(monkeypatch, response_handlers)
    state = _state(status="idle")
    _mark_current_step_complete(state)
    before_messages = list(state.conversation.messages)

    reply = response_handlers._maybe_advance_step(state)

    assert "状态迁移失败" in reply
    assert state.task.status == "idle"
    assert state.task.current_step_index == 0
    assert state.conversation.messages == before_messages
    assert calls == {"save": 0, "clear": 0}
