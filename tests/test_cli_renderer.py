"""v0.3 M1 · 基础 CLI Shell 渲染器测试。

只测纯函数渲染契约，不起 Runtime / 不触发 health check / 不读 checkpoint。
对应 docs/CLI_OUTPUT_CONTRACT.md（后续 M1 收口时会补 §9）。
"""
from __future__ import annotations

import pytest

from agent import cli_renderer as r


def test_session_header_includes_session_id_cwd_and_stage():
    out = r.render_session_header(
        session_id="abc12345-deadbeef",
        cwd="/tmp/work",
    )
    assert r.STAGE_LABEL in out
    # 短哈希前 8 位必须出现
    assert "abc12345" in out
    # 完整 session id 也保留（兼容 v0.2 grep）
    assert "abc12345-deadbeef" in out
    assert "/tmp/work" in out
    # 用法提示沿用 quit；v0.3 M3 起不再印 /reload_skills（无 handler，会误导）
    assert "quit" in out
    assert "/reload_skills" not in out
    # M3 必须明确告诉用户 Skill 仍是实验性能力
    assert "实验性" in out


def test_session_header_omits_health_line_when_none():
    out = r.render_session_header(session_id="x", cwd=".")
    assert "health" not in out


def test_session_header_includes_health_summary_when_present():
    out = r.render_session_header(
        session_id="x", cwd=".", health_summary="2 warn (log_size, sessions)"
    )
    assert "2 warn (log_size, sessions)" in out


def test_session_header_does_not_dump_protocol_or_secrets():
    out = r.render_session_header(
        session_id="abc12345",
        cwd="/tmp",
        health_summary="all checks passed",
    )
    forbidden = [
        "api_key",
        "ANTHROPIC_API_KEY",
        "sk-ant-",
        "RuntimeEvent",
        "DisplayEvent",
        "event_type=",
        "BEGIN PRIVATE KEY",
    ]
    for bad in forbidden:
        assert bad not in out, f"session header 不应包含 {bad!r}"


@pytest.mark.parametrize(
    "results,expected_keyword",
    [
        ({"a": {"status": "pass"}, "b": {"status": "pass"}}, "all checks passed"),
        ({"a": {"status": "warn"}}, "1 warn (a)"),
        (
            {"a": {"status": "warn"}, "b": {"status": "warn"}, "c": {"status": "pass"}},
            "2 warn (a, b)",
        ),
        ({"a": {"status": "error"}}, "1 error (a)"),
        ({}, "skipped"),
        (None, "skipped"),
    ],
)
def test_summarize_health_returns_compact_one_line(results, expected_keyword):
    summary = r.summarize_health(results)
    assert isinstance(summary, str)
    assert "\n" not in summary, "health 摘要必须是单行，避免刷屏"
    assert expected_keyword in summary


def test_resume_status_renders_no_checkpoint():
    out = r.render_resume_status(None)
    assert "未发现断点" in out


def test_resume_status_renders_idle_residue_silently_cleaned():
    out = r.render_resume_status({"actionable": False})
    assert "idle 残留" in out
    assert "已静默清理" in out


def test_resume_status_renders_actionable_summary():
    out = r.render_resume_status(
        {
            "actionable": True,
            "user_goal": "写 summary.md",
            "status": "awaiting_tool_confirmation",
            "current_step_index": 2,
            "message_count": 7,
            "pending_tool_name": "write_file",
        }
    )
    assert "写 summary.md" in out
    assert "awaiting_tool_confirmation" in out
    assert "步骤索引：2" in out
    assert "7 条对话历史" in out
    assert "待确认工具：write_file" in out


def test_resume_status_does_not_dump_raw_messages_or_secrets():
    """render_resume_status 只读 summary dict 字段，
    若调用方不小心传了 messages / api_key，渲染层也不会回显。"""
    out = r.render_resume_status(
        {
            "actionable": True,
            "user_goal": "g",
            "status": "running",
            "current_step_index": 1,
            "message_count": 1,
            "pending_tool_name": None,
            # 故意塞两个不该被打印的字段
            "messages": [{"role": "user", "content": "secret raw text"}],
            "api_key": "sk-ant-PRETEND",
        }
    )
    assert "secret raw text" not in out
    assert "sk-ant-PRETEND" not in out
    assert "api_key" not in out
    assert "messages" not in out


def test_status_line_handles_none_summary():
    out = r.render_status_line(None)
    assert out.startswith("[status]")
    assert "no session" in out


def test_status_line_includes_status_step_pending_msgs():
    out = r.render_status_line(
        {
            "status": "awaiting_tool_confirmation",
            "current_step_index": 3,
            "plan_total_steps": 5,
            "pending_tool_name": "write_file",
            "message_count": 12,
        }
    )
    assert "status=awaiting_tool_confirmation" in out
    assert "step=3/5" in out
    assert "pending_tool=write_file" in out
    assert "msgs=12" in out


def test_status_line_is_single_line():
    out = r.render_status_line(
        {
            "status": "running",
            "current_step_index": 1,
            "plan_total_steps": 2,
            "message_count": 3,
        }
    )
    assert "\n" not in out, "status line 必须单行，避免刷屏"
