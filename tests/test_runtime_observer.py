"""Runtime observer 只验证观测日志格式，不验证业务状态转移。

observer 是 Harness 的观测层：它让 Event / Resolution / Transition / Actions
可见，但不应该改变业务行为。这里特别保护两个边界：
- event_channel 用来区分 tool_use / assistant_text 等观测通道，不等于 event_source；
- payload 不完整打印，是为了日志可读性和隐私，不把用户输入或工具参数直接打出。
"""

from __future__ import annotations

import json


def _read_jsonl(path):
    """读取测试专用 JSONL 日志。"""

    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_log_event_outputs_event_fields(capsys):
    from agent.runtime_observer import log_event

    # event_channel 表示“从哪个通道观察到事件”，不是事件来源主体。
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


def test_log_event_persists_short_payload_without_full_text(monkeypatch, tmp_path):
    """observer 持久日志只写短字段，不写完整长文本。"""

    import agent.logger as logger
    from agent.runtime_observer import log_event

    log_path = tmp_path / "agent_log.jsonl"
    monkeypatch.setattr(logger, "LOG_FILE", log_path)

    long_text = "x" * 300
    log_event(
        "model.end_turn",
        event_source="model",
        event_payload={"text_preview": long_text, "text_length": len(long_text)},
        event_channel="end_turn",
    )

    entries = _read_jsonl(log_path)
    assert entries[-1]["event"] == "runtime_observer"
    payload = entries[-1]["data"]["payload"]
    assert payload["text_length"] == 300
    assert len(payload["text_preview"]) < 140
    assert long_text not in json.dumps(entries[-1], ensure_ascii=False)


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

    # 关闭的是观测输出，不应该影响真实 runtime 的状态转移或 action 执行。
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
