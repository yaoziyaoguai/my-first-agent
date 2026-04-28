"""v0.3 M2 · 健康检查结构化报告测试。

覆盖：
- 4 类状态（pass / warn / error / skip）的报告分支
- 每个 check_* 函数返回 schema 完整（current_value / path / risk / action / message）
- format_health_report 在 warn/error 时展开 risk + 建议命令，pass/skip 不刷屏
- format_health_report_json schema 稳定
- collect_health_results 不会自动删除任何用户产物
- workspace_lint warn 时给出可定位的具体来源（不只是「有告警」）
"""
from __future__ import annotations

import json

import pytest

from agent import health_check, health_report

REQUIRED_KEYS = {"status", "current_value", "path", "risk", "action", "message"}
ALLOWED_STATUSES = {"pass", "warn", "error", "skip"}


# ---------- 各 check_* 函数返回值的 schema 守护 ----------

@pytest.mark.parametrize(
    "fn",
    [
        health_check.check_workspace_lint,
        health_check.check_backup_accumulation,
        health_check.check_log_size,
        health_check.check_session_accumulation,
    ],
)
def test_each_check_returns_required_schema(fn):
    result = fn()
    assert isinstance(result, dict)
    missing = REQUIRED_KEYS - set(result.keys())
    assert not missing, f"{fn.__name__} 缺字段：{missing}"
    assert result["status"] in ALLOWED_STATUSES


def test_collect_health_results_includes_all_four_checks():
    results = health_check.collect_health_results()
    assert set(results.keys()) == {
        "workspace_lint",
        "backup_accumulation",
        "log_size",
        "session_accumulation",
    }


# ---------- overall_status 聚合 ----------

def test_overall_status_picks_worst():
    assert health_report.overall_status({}) == "skip"
    assert (
        health_report.overall_status(
            {
                "a": {"status": "pass"},
                "b": {"status": "warn"},
                "c": {"status": "pass"},
            }
        )
        == "warn"
    )
    assert (
        health_report.overall_status(
            {"a": {"status": "warn"}, "b": {"status": "error"}}
        )
        == "error"
    )
    assert (
        health_report.overall_status(
            {"a": {"status": "pass"}, "b": {"status": "skip"}}
        )
        == "pass"
    )


# ---------- format_health_report 文本渲染 ----------

def _fixture_results():
    return {
        "workspace_lint": {
            "status": "warn",
            "current_value": "7 文件，4 lint 错误",
            "path": "workspace",
            "risk": "scratch 目录可能混了过期样本",
            "action": "python -m ruff check workspace",
            "message": "warn",
        },
        "backup_accumulation": {
            "status": "pass",
            "current_value": "2 个 .bak 文件",
            "path": ".",
            "risk": "无",
            "action": "无需操作",
            "message": "ok",
        },
        "log_size": {
            "status": "error",
            "current_value": "999 MB",
            "path": "agent_log.jsonl",
            "risk": "磁盘可能耗尽",
            "action": "mv agent_log.jsonl ...",
            "message": "error",
        },
        "session_accumulation": {
            "status": "skip",
            "current_value": "0 个快照",
            "path": "sessions",
            "risk": "无",
            "action": "无需操作",
            "message": "skip",
        },
    }


def test_format_health_report_renders_all_four_status_categories():
    text = health_report.format_health_report(_fixture_results())
    assert "workspace_lint" in text
    assert "backup_accumulation" in text
    assert "log_size" in text
    assert "session_accumulation" in text
    assert "[warn]" in text
    assert "[pass]" in text
    assert "[error]" in text
    assert "[skip]" in text
    # warn / error 必须展开 risk + 建议
    assert "scratch 目录可能混了过期样本" in text
    assert "python -m ruff check workspace" in text
    assert "磁盘可能耗尽" in text
    # pass / skip 不该带 risk 行（risk 字段是「无」也不渲染）
    assert "无需操作" not in text


def test_format_health_report_marks_overall_worst_status():
    text = health_report.format_health_report(_fixture_results())
    assert "整体状态：" in text
    # 含 error 时整体应为 error
    assert "error" in text.split("整体状态：", 1)[1].splitlines()[0]


def test_format_health_report_does_not_dump_raw_dict():
    """报告必须是渲染后的人话，不能裸出 dict / 单引号 key。"""
    text = health_report.format_health_report(_fixture_results())
    assert "{'status'" not in text
    assert "dict_keys" not in text


def test_format_health_report_empty_input():
    assert "no health results" in health_report.format_health_report({})
    assert "no health results" in health_report.format_health_report(None)


# ---------- JSON schema ----------

def test_format_health_report_json_is_valid_and_stable():
    raw = health_report.format_health_report_json(_fixture_results())
    payload = json.loads(raw)
    assert set(payload.keys()) == {"overall", "checks"}
    assert payload["overall"] == "error"
    for name, check in payload["checks"].items():
        assert REQUIRED_KEYS <= set(check.keys()), f"{name} JSON 缺字段"


def test_format_health_report_json_handles_empty():
    payload = json.loads(health_report.format_health_report_json(None))
    assert payload == {"overall": "skip", "checks": {}}


# ---------- 安全性：不删除产物，不泄漏绝对路径 ----------

def test_collect_health_results_does_not_delete_anything(tmp_path, monkeypatch):
    """守护：M2 报告必须只读，绝对不能删除/移动用户日志、session、workspace。"""
    fake_root = tmp_path
    (fake_root / "workspace").mkdir()
    (fake_root / "sessions").mkdir()
    (fake_root / "agent_log.jsonl").write_text("line\n")
    for i in range(3):
        (fake_root / "sessions" / f"s{i}.json").write_text("{}")

    monkeypatch.setattr(health_check, "PROJECT_DIR", fake_root)

    before = sorted(p.name for p in fake_root.rglob("*"))
    health_check.collect_health_results()
    after = sorted(p.name for p in fake_root.rglob("*"))
    assert before == after, "health 检查不应改动文件系统"


def test_check_log_size_uses_relative_path(tmp_path, monkeypatch):
    """位置字段应是相对路径，不应泄漏 /Users/<name>/ 这种绝对路径。"""
    monkeypatch.setattr(health_check, "PROJECT_DIR", tmp_path)
    (tmp_path / "agent_log.jsonl").write_text("x" * (11 * 1024 * 1024))
    result = health_check.check_log_size()
    assert result["status"] == "warn"
    assert result["path"] == "agent_log.jsonl"
    assert "/Users/" not in result["path"]


def test_check_session_accumulation_warn_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(health_check, "PROJECT_DIR", tmp_path)
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    for i in range(60):
        (sessions / f"s{i}.json").write_text("{}")
    result = health_check.check_session_accumulation()
    assert result["status"] == "warn"
    assert "60" in result["current_value"]
    assert result["path"] == "sessions"
    # 建议不应包含自动 rm；M2 严格要求人工归档
    assert "rm -rf" not in result["action"]


def test_check_workspace_lint_warn_includes_specific_source(tmp_path, monkeypatch):
    """workspace_lint warn 时必须给出具体来源（哪个文件 / 什么错误），
    不能像 v0.2 那样只说「有告警」。"""
    monkeypatch.setattr(health_check, "PROJECT_DIR", tmp_path)
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "bad.py").write_text("import os\n")  # F401 unused import
    result = health_check.check_workspace_lint()
    assert result["status"] == "warn"
    # message 或 issues 必须能定位到具体文件名 / 错误码
    haystack = (result.get("message", "") + " " + result.get("issues", "")).lower()
    assert "bad.py" in haystack or "f401" in haystack


# ---------- run_health_check 兼容入口 ----------

def test_run_health_check_verbose_prints_structured_report(capsys):
    health_check.run_health_check(verbose=True)
    out = capsys.readouterr().out
    assert "项目健康检查报告" in out
    assert "整体状态" in out


def test_run_health_check_silent_returns_results(capsys):
    results = health_check.run_health_check(verbose=False)
    assert isinstance(results, dict)
    assert capsys.readouterr().out == ""
