"""Phase 4 session lifecycle / transient persistence tests.

验证 session-only transient writes 的行为契约：
- awaiting_resume_choice / awaiting_interrupt_choice 不持久化到 checkpoint
- session routing 逻辑与 task transition table 隔离
- handle_resume_choice / handle_interrupt_choice 各路径正确
- reset_task 保持 special factory reset 语义
"""

from __future__ import annotations

from agent.state import create_agent_state


def _patch_get_state(monkeypatch, state):
    """session.py 通过 local import `from agent.core import get_state` 获取 state。"""
    import agent.core as core
    monkeypatch.setattr(core, "get_state", lambda: state)


# ============================================================================
# A. try_resume_from_checkpoint — TTY 模式 transient write
# ============================================================================


def test_try_resume_sets_transient_status_in_tty_mode(monkeypatch):
    """W23: TTY 模式下 try_resume 只在内存设 awaiting_resume_choice。"""
    from agent import session

    state = create_agent_state(system_prompt="test")
    state.task.status = "running"
    _patch_get_state(monkeypatch, state)
    # _load_checkpoint_best_effort 需要返回一个有效 checkpoint dict
    monkeypatch.setattr(session, "_load_checkpoint_best_effort", lambda: {
        "task": {"status": "running", "user_goal": "demo"},
        "conversation": {"messages": [{"role": "user", "content": "hello"}]},
    })
    monkeypatch.setattr(session, "render_resume_status", lambda _summary: "")
    monkeypatch.setattr(
        session, "_checkpoint_has_actionable_resume", lambda _task, _conv: True,
    )
    monkeypatch.setattr("sys.stdin", type("FakeTTY", (), {"isatty": lambda self: True})())

    session.try_resume_from_checkpoint()

    assert state.task.status == "awaiting_resume_choice"


def test_try_resume_pipe_mode_does_not_set_transient(monkeypatch):
    """管道模式 auto-resume 不经过 awaiting_resume_choice。"""
    from agent import session

    state = create_agent_state(system_prompt="test")
    state.task.status = "idle"
    _patch_get_state(monkeypatch, state)
    monkeypatch.setattr(session, "_load_checkpoint_best_effort", lambda: {
        "task": {"status": "running", "user_goal": "demo"},
        "conversation": {"messages": [{"role": "user", "content": "hello"}]},
    })
    monkeypatch.setattr(session, "render_resume_status", lambda _summary: "")
    monkeypatch.setattr(
        session, "_checkpoint_has_actionable_resume", lambda _task, _conv: True,
    )
    monkeypatch.setattr(
        session, "_load_checkpoint_to_state_best_effort", lambda _state: True,
    )
    monkeypatch.setattr(session, "_try_dispatch_checkpoint_resume", lambda _state: None)
    monkeypatch.setattr(session, "_replay_awaiting_prompt", lambda _state: None)
    monkeypatch.setattr("sys.stdin", type("FakePipe", (), {"isatty": lambda self: False})())

    session.try_resume_from_checkpoint()

    assert state.task.status != "awaiting_resume_choice"


# ============================================================================
# B. handle_interrupt_with_checkpoint — W18 transient write
# ============================================================================


def test_interrupt_with_checkpoint_saves_then_sets_transient(monkeypatch):
    """W18: 中断先保存 checkpoint，再设 transient awaiting_interrupt_choice。"""
    from agent import session

    state = create_agent_state(system_prompt="test")
    state.task.status = "running"
    _patch_get_state(monkeypatch, state)
    save_calls = []
    monkeypatch.setattr(
        session, "save_checkpoint",
        lambda _state, session_id=None: save_calls.append(state.task.status),
    )
    monkeypatch.setattr(session, "_resolve_session_id", lambda: "test-session")

    result = session.handle_interrupt_with_checkpoint()

    assert result is False
    # checkpoint 保存时 status 仍为 running（transient 在保存之后设置）
    assert save_calls == ["running"]
    assert state.task.status == "awaiting_interrupt_choice"


def test_interrupt_transient_not_persisted_to_checkpoint(monkeypatch):
    """awaiting_interrupt_choice 是内存态，不应出现在 checkpoint 数据中。"""
    from agent import session

    state = create_agent_state(system_prompt="test")
    state.task.status = "running"
    _patch_get_state(monkeypatch, state)
    saved_states = []
    monkeypatch.setattr(
        session, "save_checkpoint",
        lambda s, session_id=None: saved_states.append(s.task.status),
    )
    monkeypatch.setattr(session, "_resolve_session_id", lambda: "test-session")

    session.handle_interrupt_with_checkpoint()

    # checkpoint 保存时记录的 status 是 running，不是 transient
    assert saved_states[0] == "running"
    # 设 transient 后未再保存
    assert len(saved_states) == 1


# ============================================================================
# C. handle_resume_choice — W19/W20 paths
# ============================================================================


def test_resume_choice_no_resume_clears_and_idles(monkeypatch):
    """W19: 用户选择不恢复 → clear checkpoint → idle。"""
    from agent import session

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_resume_choice"
    _patch_get_state(monkeypatch, state)
    clear_calls = []
    monkeypatch.setattr(session, "clear_checkpoint", lambda: clear_calls.append(1))

    session.handle_resume_choice("n")

    assert state.task.status == "idle"
    assert clear_calls == [1]


def test_resume_choice_restore_success_replays_prompt(monkeypatch):
    """W19 restore success: 恢复状态后 replay awaiting prompt。"""
    from agent import session

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_resume_choice"
    _patch_get_state(monkeypatch, state)
    monkeypatch.setattr(
        session, "_load_checkpoint_to_state_best_effort", lambda _state: True,
    )
    replay_calls = []
    monkeypatch.setattr(
        session, "_try_dispatch_checkpoint_resume", lambda _state: None,
    )
    monkeypatch.setattr(
        session, "_replay_awaiting_prompt",
        lambda _state: replay_calls.append(1),
    )

    session.handle_resume_choice("y")

    assert replay_calls == [1]


def test_resume_choice_restore_failed_falls_to_idle(monkeypatch):
    """W20: 恢复失败 → idle。"""
    from agent import session

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_resume_choice"
    _patch_get_state(monkeypatch, state)
    monkeypatch.setattr(
        session, "_load_checkpoint_to_state_best_effort", lambda _state: False,
    )

    session.handle_resume_choice("y")

    assert state.task.status == "idle"


# ============================================================================
# D. handle_interrupt_choice — W21/W22 paths
# ============================================================================


def test_interrupt_choice_continue_sets_running(monkeypatch):
    """W21: 选择继续 → running。"""
    from agent import session

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_interrupt_choice"
    _patch_get_state(monkeypatch, state)

    result = session.handle_interrupt_choice("1")

    assert result is False
    assert state.task.status == "running"


def test_interrupt_choice_cancel_resets_task(monkeypatch):
    """选择放弃任务 → clear checkpoint + reset_task → idle。"""
    from agent import session

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_interrupt_choice"
    state.task.user_goal = "some goal"
    _patch_get_state(monkeypatch, state)
    clear_calls = []
    monkeypatch.setattr(session, "clear_checkpoint", lambda: clear_calls.append(1))

    result = session.handle_interrupt_choice("2")

    assert result is False
    assert state.task.status == "idle"
    assert state.task.user_goal is None
    assert clear_calls == [1]


def test_interrupt_choice_exit_saves_and_returns_true(monkeypatch):
    """选择退出 → save session + True。"""
    from agent import session

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_interrupt_choice"
    _patch_get_state(monkeypatch, state)
    save_calls = []
    monkeypatch.setattr(
        session, "save_session_snapshot", lambda _msgs: save_calls.append(1),
    )
    monkeypatch.setattr(session, "_record_session_end", lambda **_kw: None)

    result = session.handle_interrupt_choice("3")

    assert result is True
    assert save_calls == [1]


def test_interrupt_choice_invalid_falls_to_idle(monkeypatch):
    """W22: 无效输入 → idle。"""
    from agent import session

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_interrupt_choice"
    _patch_get_state(monkeypatch, state)

    result = session.handle_interrupt_choice("invalid")

    assert result is False
    assert state.task.status == "idle"


# ============================================================================
# E. Session transient states 不被 task transition table 管理
# ============================================================================


def test_session_transient_states_not_in_task_transition_table():
    """session-only transient 不应出现在 _TRANSITION_TABLE from_status 或 to_status。"""
    from agent.transitions import _TRANSITION_TABLE

    session_transients = {"awaiting_resume_choice", "awaiting_interrupt_choice"}

    for (from_status, _event), rule in _TRANSITION_TABLE.items():
        assert from_status not in session_transients, (
            f"Session transient {from_status!r} found as from_status in task table"
        )
        if rule.to_status not in {"<origin_status>", "<memory_origin_status>"}:
            assert rule.to_status not in session_transients, (
                f"Session transient {rule.to_status!r} found as to_status in task table"
            )


# ============================================================================
# F. reset_task special writer 行为
# ============================================================================


def test_reset_task_clears_all_task_state():
    """S01: reset_task 是 factory reset，不是 transition。"""
    state = create_agent_state(system_prompt="test")
    state.task.status = "running"
    state.task.user_goal = "something"
    state.task.current_plan = {"goal": "plan"}
    state.task.current_step_index = 3
    state.task.pending_tool = {"tool": "test"}
    state.task.pending_user_input_request = {"question": "?"}

    state.reset_task()

    assert state.task.status == "idle"
    assert state.task.user_goal is None
    assert state.task.current_plan is None
    assert state.task.current_step_index == 0
    assert state.task.pending_tool is None
    assert state.task.pending_user_input_request is None


def test_reset_task_not_in_transition_table():
    """reset_task 不应通过 transition table 管理。"""
    from agent.transitions import TransitionEvent

    # 不存在 RESET event
    for event in TransitionEvent:
        assert "reset" not in event.value.lower(), (
            f"TransitionEvent {event.value!r} looks like a reset event"
        )


# ============================================================================
# G. Final legal writer inventory — executable verification
# ============================================================================


def test_final_legal_writer_inventory_is_complete():
    """Phase 4 最终合法 writer：8 个写入点，双向验证。

    Final legal writers:
    1. agent/transitions.py::apply_task_transition (普通 task transition)
    2. agent/state.py::AgentState.reset_task (special factory reset)
    3-8. agent/session.py W18-W23 (session-only transient)
    """
    from tests.test_architecture_boundaries import (
        _DIRECT_STATUS_MUTATION_BASELINE,
        _aggregate_mutations,
        _collect_direct_status_mutations,
    )

    mutations = _collect_direct_status_mutations()
    actual = _aggregate_mutations(mutations)

    # 双向：actual 只含 baseline 中的项，baseline 中的项都存在于 actual
    actual_keys = set(actual.keys())
    expected_keys = set(_DIRECT_STATUS_MUTATION_BASELINE.keys())

    unexpected = actual_keys - expected_keys
    missing = expected_keys - actual_keys

    errors = []
    if unexpected:
        errors.append(f"Unexpected writers: {unexpected}")
    if missing:
        errors.append(f"Missing expected writers: {missing}")

    assert not errors, "\n".join(errors)

    # 总写入点数验证
    total_writes = sum(actual.values())
    expected_total = sum(_DIRECT_STATUS_MUTATION_BASELINE.values())
    assert total_writes == expected_total, (
        f"Total write count mismatch: actual={total_writes}, expected={expected_total}"
    )
