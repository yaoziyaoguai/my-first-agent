"""v0.3 M1 · session 摘要与启动渲染集成测试。

测两件事：
1) summarize_session_status 返回字段完备且不含 raw messages / api 配置；
2) init_session 输出符合 v0.3 M1 shell header 契约（structured stdout，
   不刷屏，不 dump 健康检查长块）。
"""
from __future__ import annotations

import io
from contextlib import redirect_stdout

from agent import session as session_mod


# ============== summarize_session_status ==============


def test_summarize_session_status_handles_none():
    summary = session_mod.summarize_session_status(None)
    assert summary["status"] == "idle"
    assert summary["actionable"] is False
    assert summary["message_count"] == 0
    assert summary["pending_tool_name"] is None


class _FakeTask:
    def __init__(
        self,
        status="idle",
        user_goal=None,
        current_step_index=0,
        current_plan=None,
        pending_tool=None,
        pending_user_input_request=None,
    ):
        self.status = status
        self.user_goal = user_goal
        self.current_step_index = current_step_index
        self.current_plan = current_plan
        self.pending_tool = pending_tool
        self.pending_user_input_request = pending_user_input_request


class _FakeConv:
    def __init__(self, messages=None):
        self.messages = messages or []


class _FakeState:
    def __init__(self, task, conv=None):
        self.task = task
        self.conversation = conv or _FakeConv()


def test_summarize_idle_with_no_messages_is_not_actionable():
    state = _FakeState(_FakeTask(status="idle"))
    summary = session_mod.summarize_session_status(state)
    assert summary["actionable"] is False
    assert summary["status"] == "idle"


def test_summarize_pending_tool_is_actionable():
    state = _FakeState(
        _FakeTask(
            status="awaiting_tool_confirmation",
            pending_tool={"tool": "write_file", "tool_use_id": "t1", "input": {}},
            current_step_index=2,
        )
    )
    summary = session_mod.summarize_session_status(state)
    assert summary["actionable"] is True
    assert summary["pending_tool_name"] == "write_file"
    assert summary["current_step_index"] == 2


def test_summarize_includes_plan_total_steps_when_plan_present():
    state = _FakeState(
        _FakeTask(
            status="running",
            current_plan={"steps": [{"id": 1}, {"id": 2}, {"id": 3}]},
            current_step_index=1,
        )
    )
    summary = session_mod.summarize_session_status(state)
    assert summary["plan_total_steps"] == 3
    assert summary["current_step_title"] is None


def test_summarize_includes_current_step_title_when_present():
    state = _FakeState(
        _FakeTask(
            status="running",
            current_plan={
                "steps": [
                    {"title": "读取 README"},
                    {"description": "写总结"},
                ]
            },
            current_step_index=1,
        )
    )
    summary = session_mod.summarize_session_status(state)
    assert summary["plan_total_steps"] == 2
    assert summary["current_step_title"] == "写总结"


def test_summarize_does_not_leak_raw_messages():
    """summary 必须只暴露 message 数量，不暴露内容。"""
    conv = _FakeConv(
        messages=[
            {"role": "user", "content": "secret raw text from user"},
            {"role": "assistant", "content": "secret raw text from model"},
        ]
    )
    state = _FakeState(_FakeTask(status="running"), conv)
    summary = session_mod.summarize_session_status(state)
    assert summary["message_count"] == 2
    # 显式检查没有 raw content 字段
    for value in summary.values():
        if isinstance(value, str):
            assert "secret raw text" not in value


# ============== init_session 输出契约 ==============


def test_init_session_outputs_structured_header_without_health_dump(monkeypatch):
    """init_session 不应再打印 v0.2 的「🏥 项目健康检查报告」长块。"""
    monkeypatch.setattr(session_mod, "init_memory", lambda: None)
    monkeypatch.setattr(session_mod, "cleanup_old_episodes", lambda: None)
    monkeypatch.setattr(session_mod, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(
        session_mod,
        "run_health_check",
        lambda verbose=True: {
            "workspace_lint": {"status": "warn"},
            "log_size": {"status": "pass"},
        },
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        session_mod.init_session()
    out = buf.getvalue()

    assert "Runtime v0.3 basic CLI shell" in out
    assert "session" in out
    assert "cwd" in out
    assert "python main.py health" in out
    assert "python main.py logs" in out
    # 健康检查只能是单行紧凑摘要，不能是长块报告
    assert "🏥 项目健康检查报告" not in out
    assert "1 warn (workspace_lint)" in out
    assert "quit" in out


def test_init_session_calls_health_check_in_silent_mode(monkeypatch):
    """避免 init_session 同时打两份健康输出（紧凑 + 长块）。"""
    monkeypatch.setattr(session_mod, "init_memory", lambda: None)
    monkeypatch.setattr(session_mod, "cleanup_old_episodes", lambda: None)
    monkeypatch.setattr(session_mod, "log_event", lambda *a, **k: None)

    captured_kwargs = {}

    def fake_health(verbose=True):
        captured_kwargs["verbose"] = verbose
        return {}

    monkeypatch.setattr(session_mod, "run_health_check", fake_health)

    with redirect_stdout(io.StringIO()):
        session_mod.init_session()

    assert captured_kwargs.get("verbose") is False


def test_init_session_does_not_leak_raw_state_or_secrets(monkeypatch):
    monkeypatch.setattr(session_mod, "init_memory", lambda: None)
    monkeypatch.setattr(session_mod, "cleanup_old_episodes", lambda: None)
    monkeypatch.setattr(session_mod, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(session_mod, "run_health_check", lambda verbose=True: {})

    buf = io.StringIO()
    with redirect_stdout(buf):
        session_mod.init_session()
    out = buf.getvalue()

    for forbidden in (
        "ANTHROPIC_API_KEY",
        "sk-ant-",
        "RuntimeEvent",
        "DisplayEvent",
        "BEGIN PRIVATE KEY",
        "event_type=",
    ):
        assert forbidden not in out
