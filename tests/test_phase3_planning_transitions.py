"""Phase 3 planning transition 的真实 schema 分支与失败清理测试。"""

from __future__ import annotations

import json

import pytest

from agent.loop_context import LoopContext
from agent.skill_system.lifecycle import get_default_lifecycle, reset_default_lifecycle
from tests.conftest import FakeAnthropicClient, text_response


def _legacy_raw() -> dict:
    return {
        "steps_estimate": 2,
        "goal": "demo",
        "thinking": "plan",
        "needs_confirmation": True,
        "steps": [
            {
                "step_id": "s1",
                "title": "first",
                "description": "first",
                "step_type": "read",
            },
            {
                "step_id": "s2",
                "title": "second",
                "description": "second",
                "step_type": "report",
            },
        ],
    }


def _action_raw() -> dict:
    return {
        "steps_estimate": 2,
        "plan_id": "p1",
        "entry_node_id": "n1",
        "nodes": [
            {
                "node_id": "n1",
                "action_type": "TOOL_CALL",
                "target": "read_file",
                "params": {"path": "README.md"},
            },
            {
                "node_id": "n2",
                "action_type": "TOOL_CALL",
                "target": "write_file",
                "params": {"path": "report.txt"},
                "depends_on": ["n1"],
            },
        ],
    }


def _planning_context(raw: dict):
    client = FakeAnthropicClient([text_response(json.dumps(raw))])
    return LoopContext(
        client=client,
        model_name="test-model",
        max_loop_iterations=3,
    )


def _planning_context_with_session(raw: dict, session_id: str):
    from agent.runtime_identity import RuntimeIdentity

    client = FakeAnthropicClient([text_response(json.dumps(raw))])
    return LoopContext(
        client=client,
        model_name="test-model",
        max_loop_iterations=3,
        runtime_identity=RuntimeIdentity(
            session_id=session_id,
            run_id="test-run",
            instance_id=session_id,
        ),
    )


def _install_state(monkeypatch, *, status: str):
    from agent import core
    from agent.state import create_agent_state

    state = create_agent_state(system_prompt="test")
    state.task.status = status
    monkeypatch.setattr(core, "state", state)
    return core, state


def _turn_state(core, events):
    return core.TurnState(
        system_prompt="test",
        on_runtime_event=events.append,
    )


def _assert_lifecycle_boundary_clean(session_id: str, *, stale_body: str) -> None:
    from agent import core

    lifecycle = get_default_lifecycle(session_id)
    assert lifecycle.get_active() is None

    prompt, _ = core.refresh_runtime_system_prompt(namespace_key=session_id)
    assert stale_body not in prompt

    visible_tool_names = _visible_tool_names_for_session(core, session_id)
    assert "run_shell" in visible_tool_names
    assert visible_tool_names != {"read_file", "SKILL_SELECT"}


def _visible_tool_names_for_session(core, session_id: str) -> set[str]:
    client = FakeAnthropicClient([text_response("done")])
    loop_ctx = _planning_context_with_session(_action_raw(), session_id)
    loop_ctx = type(loop_ctx)(
        client=client,
        model_name=loop_ctx.model_name,
        max_loop_iterations=loop_ctx.max_loop_iterations,
        runtime_identity=loop_ctx.runtime_identity,
    )
    turn_state = core.TurnState(system_prompt="test")

    core._call_model(turn_state, loop_ctx)

    return {
        item["name"]
        for item in client.requests[-1]["tools"]
    }


def test_legacy_plan_from_idle_applies_then_saves_once(monkeypatch):
    core, state = _install_state(monkeypatch, status="idle")
    saves = []
    events = []
    monkeypatch.setattr(
        core,
        "_dispatch_checkpoint_save",
        lambda *_args, **_kwargs: saves.append(1),
    )

    result = core._run_planning_phase(
        "demo task",
        _turn_state(core, events),
        _planning_context(_legacy_raw()),
    )

    assert result == "awaiting_plan_confirmation"
    assert state.task.status == "awaiting_plan_confirmation"
    assert state.task.current_plan["goal"] == "demo"
    assert state.task.user_goal == "demo task"
    assert state.task.current_step_index == 0
    assert state.conversation.messages == [{"role": "user", "content": "demo task"}]
    assert saves == [1]
    assert len(events) == 1


def test_action_plan_from_idle_handoffs_then_saves_once(monkeypatch):
    core, state = _install_state(monkeypatch, status="idle")
    saves = []
    events = []
    loaded = []
    scheduler = type("Scheduler", (), {"load_plan": lambda self, plan: loaded.append(plan)})()
    monkeypatch.setattr(
        core,
        "_dispatch_checkpoint_save",
        lambda *_args, **_kwargs: saves.append(1),
    )

    result = core._run_planning_phase(
        "demo task",
        _turn_state(core, events),
        _planning_context(_action_raw()),
        action_scheduler=scheduler,
    )

    assert result == "awaiting_plan_confirmation"
    assert state.task.status == "awaiting_plan_confirmation"
    assert state.task.current_plan["plan_id"] == "p1"
    assert state.conversation.messages == [{"role": "user", "content": "demo task"}]
    assert len(loaded) == 1
    assert saves == [1]
    assert len(events) == 1


@pytest.mark.parametrize("raw", [_legacy_raw(), _action_raw()])
def test_planning_from_running_is_denied_without_state_side_effects(
    monkeypatch,
    raw,
):
    core, state = _install_state(monkeypatch, status="running")
    state.task.current_plan = {"existing": True}
    state.task.user_goal = "existing goal"
    state.task.current_step_index = 7
    state.conversation.messages = [{"role": "user", "content": "existing"}]
    before_messages = list(state.conversation.messages)
    saves = []
    events = []
    monkeypatch.setattr(
        core,
        "_dispatch_checkpoint_save",
        lambda *_args, **_kwargs: saves.append(1),
    )

    result = core._run_planning_phase(
        "new task",
        _turn_state(core, events),
        _planning_context(raw),
    )

    assert result == "planning_transition_denied"
    assert state.task.status == "running"
    assert state.task.current_plan == {"existing": True}
    assert state.task.user_goal == "existing goal"
    assert state.task.current_step_index == 7
    assert state.conversation.messages == before_messages
    assert saves == []
    assert events == []


def test_action_plan_scheduler_failure_cleans_task_without_save_or_confirmation(
    monkeypatch,
):
    reset_default_lifecycle()
    session_id = "planning-action-handoff-failed"
    stale_body = "STALE_ACTION_SKILL_BODY"
    core, state = _install_state(monkeypatch, status="idle")
    state.memory.session_id = session_id
    get_default_lifecycle(session_id).activate(
        "stale-action-skill",
        body=stale_body,
        allowed_tools=("read_file",),
    )
    saves = []
    events = []

    class FailingScheduler:
        def load_plan(self, _plan):
            raise RuntimeError("load failed")

    monkeypatch.setattr(
        core,
        "_dispatch_checkpoint_save",
        lambda *_args, **_kwargs: saves.append(1),
    )

    result = core._run_planning_phase(
        "demo task",
        _turn_state(core, events),
        _planning_context_with_session(_action_raw(), session_id),
        action_scheduler=FailingScheduler(),
    )

    assert result == "planning_handoff_failed"
    assert state.task.status == "idle"
    assert state.task.current_plan is None
    assert state.task.user_goal is None
    assert saves == []
    assert events == []
    _assert_lifecycle_boundary_clean(session_id, stale_body=stale_body)


def test_legacy_plan_with_scheduler_does_not_enter_handoff_boundary(
    monkeypatch,
):
    reset_default_lifecycle()
    session_id = "planning-legacy-handoff-unreachable"
    stale_body = "STALE_LEGACY_SKILL_BODY"
    core, state = _install_state(monkeypatch, status="idle")
    state.memory.session_id = session_id
    get_default_lifecycle(session_id).activate(
        "stale-legacy-skill",
        body=stale_body,
        allowed_tools=("read_file",),
    )
    saves = []
    events = []

    class FailingScheduler:
        def load_plan(self, _plan):
            raise RuntimeError("legacy load failed")

    monkeypatch.setattr(
        core,
        "_dispatch_checkpoint_save",
        lambda *_args, **_kwargs: saves.append(1),
    )

    result = core._run_planning_phase(
        "demo task",
        _turn_state(core, events),
        _planning_context_with_session(_legacy_raw(), session_id),
        action_scheduler=FailingScheduler(),
    )

    assert result == "ok"
    assert state.task.status == "idle"
    assert state.task.current_plan is None
    assert state.task.user_goal is None
    assert saves == []
    assert len(events) == 1
    assert get_default_lifecycle(session_id).get_active() is not None


def test_legacy_scheduler_handoff_reset_branch_is_not_reachable() -> None:
    """1742 是历史 defensive 分支；当前 scheduler 模式不会构造 legacy_plan。"""
    import inspect

    from agent import core

    src = inspect.getsource(core._run_planning_phase)
    assert (
        "if action_plan is None and raw is not None and action_scheduler is None:"
        in src
    )
    assert "action_scheduler.load_plan(legacy_action_plan)" in src


def test_planning_failure_results_do_not_enter_main_loop(monkeypatch):
    from agent import core

    monkeypatch.setattr(
        core,
        "_run_main_loop",
        lambda *_args, **_kwargs: pytest.fail("failure result must not continue loop"),
    )
    turn_state = core.TurnState(system_prompt="test")
    loop_ctx = LoopContext(client=object(), model_name="test", max_loop_iterations=1)

    assert "状态迁移失败" in core._handle_planning_phase_result(
        "planning_transition_denied",
        turn_state,
        loop_ctx,
    )
    assert "调度器" in core._handle_planning_phase_result(
        "planning_handoff_failed",
        turn_state,
        loop_ctx,
    )
