"""Runtime observer 只验证观测日志格式，不验证业务状态转移。"""

from __future__ import annotations


def test_log_event_outputs_event_fields(capsys):
    from agent.runtime_observer import log_event

    log_event(
        "model.requested_user_input",
        event_source="model",
        event_payload={"question": "不应完整打印"},
        event_channel="tool_use",
    )

    out = capsys.readouterr().out
    assert "[RUNTIME_EVENT]" in out
    assert "event_type=model.requested_user_input" in out
    assert "event_source=model" in out
    assert "event_channel=tool_use" in out
    assert "不应完整打印" not in out


def test_log_resolution_outputs_resolution_kind_and_simple_details(capsys):
    from agent.runtime_observer import log_resolution

    log_resolution(
        "runtime_user_input_answer",
        event_type="user.replied",
        details={"should_advance_step": False},
    )

    out = capsys.readouterr().out
    assert "[INPUT_RESOLUTION]" in out
    assert "resolution_kind=runtime_user_input_answer" in out
    assert "event_type=user.replied" in out
    assert "should_advance_step=false" in out


def test_log_transition_outputs_state_fields(capsys):
    from agent.runtime_observer import log_transition

    log_transition(
        from_state="awaiting_user_input",
        event_type="user.replied",
        target_state="running",
    )

    out = capsys.readouterr().out
    assert "[TRANSITION]" in out
    assert "from_state=awaiting_user_input" in out
    assert "event_type=user.replied" in out
    assert "target_state=running" in out


def test_log_actions_outputs_action_names(capsys):
    from agent.runtime_observer import log_actions

    log_actions(["append_step_input", "advance_step", "save_checkpoint"])

    out = capsys.readouterr().out
    assert "[ACTIONS]" in out
    assert "action_names=append_step_input,advance_step,save_checkpoint" in out


def test_runtime_debug_logs_false_suppresses_output(monkeypatch, capsys):
    import agent.runtime_observer as observer

    monkeypatch.setattr(observer, "RUNTIME_DEBUG_LOGS", False)

    observer.log_event("model.requested_user_input", event_source="model")
    observer.log_resolution("collect_input_answer")
    observer.log_transition(
        from_state="awaiting_user_input",
        event_type="user.replied",
        target_state="running",
    )
    observer.log_actions(["save_checkpoint"])

    assert capsys.readouterr().out == ""
