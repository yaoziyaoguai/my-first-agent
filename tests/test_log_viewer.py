"""v0.3 M4 · 可读 observer/logs viewer 测试。

覆盖：
- iter_log_entries 基本读取 + 损坏行容忍
- 默认隐藏 runtime_observer，--include-observer 打开
- filter_entries 按 session 前缀 / event / tool 过滤
- format_entry 4 类工具结局可区分
- format_entry **不打印** raw content / result / system_prompt（脱敏边界）
- format_entry 兜底脱敏 sk-ant- / private key / api_key=xxx
- render_logs tail 截尾稳定
- main.py logs 子命令端到端
- log_size health action 指向 logs viewer
- 不会自动删除任何文件
"""
from __future__ import annotations

import json
from pathlib import Path

import main as main_module
from agent import log_viewer


def _write_log(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "agent_log.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return p


# ---------- 基本读取 + 损坏行 ----------

def test_iter_log_entries_skips_broken_lines(tmp_path):
    p = tmp_path / "agent_log.jsonl"
    p.write_text(
        json.dumps({"event": "user_input", "session_id": "abc", "data": {"content": "hi"}})
        + "\n{not json\n"
        + json.dumps({"event": "agent_reply", "session_id": "abc", "data": {"content": "ok"}})
        + "\n",
        encoding="utf-8",
    )
    out = list(log_viewer.iter_log_entries(log_path=p))
    assert len(out) == 3
    assert out[0]["event"] == "user_input"
    assert out[1].get("_broken") is True
    assert out[2]["event"] == "agent_reply"


def test_iter_returns_nothing_when_log_missing(tmp_path):
    out = list(log_viewer.iter_log_entries(log_path=tmp_path / "nope.jsonl"))
    assert out == []


def test_iter_hides_runtime_observer_by_default(tmp_path):
    p = _write_log(
        tmp_path,
        [
            {"event": "user_input", "session_id": "a", "data": {"content": "x"}},
            {"event": "runtime_observer", "session_id": "a", "data": {"event_type": "x"}},
        ],
    )
    out = list(log_viewer.iter_log_entries(log_path=p))
    assert [e["event"] for e in out] == ["user_input"]


def test_iter_includes_runtime_observer_when_opted_in(tmp_path):
    p = _write_log(
        tmp_path,
        [
            {"event": "runtime_observer", "session_id": "a", "data": {"event_type": "x"}},
        ],
    )
    out = list(log_viewer.iter_log_entries(log_path=p, include_observer=True))
    assert len(out) == 1


# ---------- 过滤 ----------

def test_filter_by_session_prefix():
    entries = [
        {"event": "x", "session_id": "abc12345-foo"},
        {"event": "x", "session_id": "def00000-bar"},
    ]
    out = list(log_viewer.filter_entries(entries, session_id="abc12345"))
    assert len(out) == 1
    assert out[0]["session_id"].startswith("abc12345")


def test_filter_by_event():
    entries = [
        {"event": "user_input", "session_id": "a"},
        {"event": "tool_executed", "session_id": "a", "data": {"tool": "calc"}},
    ]
    out = list(log_viewer.filter_entries(entries, event="tool_executed"))
    assert len(out) == 1


def test_filter_by_tool():
    entries = [
        {"event": "tool_executed", "data": {"tool": "calculate"}},
        {"event": "tool_executed", "data": {"tool": "read_file"}},
    ]
    out = list(log_viewer.filter_entries(entries, tool="calculate"))
    assert len(out) == 1


# ---------- 4 类工具结局可区分 ----------

def test_format_entry_distinguishes_tool_outcomes():
    success = log_viewer.format_entry(
        {
            "timestamp": "t",
            "session_id": "abc12345",
            "event": "tool_executed",
            "data": {"tool": "calc", "result": "42"},
        }
    )
    rejected = log_viewer.format_entry(
        {
            "timestamp": "t",
            "session_id": "abc12345",
            "event": "tool_rejected",
            "data": {"tool": "write_file"},
        }
    )
    blocked = log_viewer.format_entry(
        {
            "timestamp": "t",
            "session_id": "abc12345",
            "event": "tool_blocked_sensitive_read",
            "data": {"tool": "read_file", "path": ".env"},
        }
    )
    assert "tool_executed" in success and "calc" in success
    assert "tool_rejected" in rejected and "write_file" in rejected
    assert "tool_blocked_sensitive_read" in blocked and ".env" in blocked


# ---------- 脱敏边界（核心） ----------

def test_format_entry_never_prints_raw_tool_result():
    """tool_executed.result 含完整文件正文时不应被渲染，只显示长度。"""
    raw = "import os\n" + "x" * 5000
    out = log_viewer.format_entry(
        {
            "timestamp": "t",
            "session_id": "abc",
            "event": "tool_executed",
            "data": {"tool": "read_file", "result": raw, "input": {"path": "x.py"}},
        }
    )
    assert "import os" not in out
    assert "xxxx" not in out
    assert "result_len=" in out


def test_format_entry_never_prints_user_input_content():
    out = log_viewer.format_entry(
        {
            "timestamp": "t",
            "session_id": "a",
            "event": "user_input",
            "data": {"content": "我的密码是 hunter2"},
        }
    )
    assert "hunter2" not in out
    assert "密码" not in out
    assert "len=" in out


def test_format_entry_never_prints_agent_reply_content():
    out = log_viewer.format_entry(
        {
            "timestamp": "t",
            "session_id": "a",
            "event": "agent_reply",
            "data": {"content": "BEGIN PRIVATE KEY"},
        }
    )
    assert "PRIVATE KEY" not in out


def test_format_entry_never_prints_system_prompt():
    out = log_viewer.format_entry(
        {
            "timestamp": "t",
            "session_id": "a",
            "event": "session_start",
            "data": {"system_prompt": "You are a math tutor with secret xyz"},
        }
    )
    assert "secret" not in out
    assert "math tutor" not in out
    assert "system_prompt_len=" in out


def test_mask_secrets_redacts_known_patterns():
    leaked = (
        "tool_executed result_len=99 sk-ant-api03-AbCdEfGhIjKl_more_chars "
        "ANTHROPIC_API_KEY=sk-foo BEGIN RSA PRIVATE KEY"
    )
    out = log_viewer.mask_secrets(leaked)
    assert "sk-ant-api03" not in out
    assert "PRIVATE KEY" not in out
    assert "[REDACTED]" in out


def test_format_entry_redacts_residual_secrets_in_fallback_path():
    """对未显式枚举的 event，兜底渲染也必须经 mask_secrets。"""
    out = log_viewer.format_entry(
        {
            "timestamp": "t",
            "session_id": "a",
            "event": "some_unknown_event",
            "data": {"note": "key=sk-ant-api03-xxxxxxxxxxxx"},
        }
    )
    assert "sk-ant-api03" not in out


def test_format_entry_does_not_dump_nested_dicts():
    """fallback 路径不应递归 dump 嵌套结构（可能含 secret）。"""
    out = log_viewer.format_entry(
        {
            "timestamp": "t",
            "session_id": "a",
            "event": "some_unknown_event",
            "data": {"payload": {"deep": "BEGIN RSA PRIVATE KEY"}},
        }
    )
    assert "PRIVATE KEY" not in out
    assert "payload" not in out  # dict 值被跳过


# ---------- render_logs 截尾 + 端到端 ----------

def test_render_logs_tail_truncates(tmp_path):
    entries = [
        {"timestamp": f"t{i}", "event": "user_input", "session_id": "abc12345", "data": {"content": "x"}}
        for i in range(20)
    ]
    p = _write_log(tmp_path, entries)
    out = log_viewer.render_logs(log_path=p, tail=5)
    assert "showing last 5 entries" in out
    # 应保留最后 5 条 t15..t19
    assert "t15" in out and "t19" in out
    assert "t14" not in out


def test_render_logs_handles_empty(tmp_path):
    out = log_viewer.render_logs(log_path=tmp_path / "missing.jsonl", tail=10)
    assert "no matching entries" in out


def test_render_logs_reports_broken_count(tmp_path):
    p = tmp_path / "agent_log.jsonl"
    p.write_text(
        json.dumps({"event": "user_input", "session_id": "a", "data": {"content": "x"}})
        + "\nBROKEN_LINE\nALSO_BROKEN\n",
        encoding="utf-8",
    )
    out = log_viewer.render_logs(log_path=p, tail=50)
    assert "跳过了 2 条损坏" in out


# ---------- main.py logs 子命令 ----------

def test_main_logs_subcommand_runs(monkeypatch, capsys, tmp_path):
    fake_log = _write_log(
        tmp_path,
        [
            {"timestamp": "t", "session_id": "abc12345", "event": "user_input", "data": {"content": "hi"}},
        ],
    )
    monkeypatch.setattr(log_viewer, "LOG_FILE", str(fake_log))
    rc = main_module.main(["logs", "--tail", "10"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Runtime logs" in out
    assert "user_input" in out


def test_main_logs_subcommand_rejects_bad_tail(capsys):
    rc = main_module.main(["logs", "--tail", "abc"])
    assert rc == 2
    assert "整数" in capsys.readouterr().out


def test_main_logs_does_not_start_main_loop(monkeypatch):
    triggered = []
    monkeypatch.setattr(main_module, "init_session", lambda: triggered.append("init"))
    monkeypatch.setattr(main_module, "main_loop", lambda: triggered.append("loop"))
    monkeypatch.setattr(
        main_module, "try_resume_from_checkpoint", lambda: triggered.append("resume")
    )
    rc = main_module.main(["logs", "--tail", "1"])
    assert rc == 0
    assert triggered == []


# ---------- M4 不删除任何文件 ----------

def test_render_logs_does_not_modify_log(tmp_path):
    p = _write_log(
        tmp_path,
        [{"timestamp": "t", "session_id": "a", "event": "user_input", "data": {"content": "x"}}],
    )
    before = p.read_bytes()
    log_viewer.render_logs(log_path=p, tail=10)
    after = p.read_bytes()
    assert before == after


# ---------- M2 health action 联动 ----------

def test_health_log_size_action_points_to_logs_viewer(tmp_path, monkeypatch):
    from agent import health_check

    monkeypatch.setattr(health_check, "PROJECT_DIR", tmp_path)
    (tmp_path / "agent_log.jsonl").write_text("x" * (11 * 1024 * 1024))
    result = health_check.check_log_size()
    assert result["status"] == "warn"
    assert "python main.py logs" in result["action"]
