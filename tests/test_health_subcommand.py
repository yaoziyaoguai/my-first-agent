"""验证 `python main.py health` 子命令独立可运行（v0.2 release 收口，
v0.3 M2 升级为结构化报告 + --json 入口）。
"""
import json

import main as main_module


def test_health_subcommand_invokes_collector(monkeypatch, capsys):
    """默认 health 走 format_health_report 文本输出。"""
    called = {"n": 0}

    def fake_collect():
        called["n"] += 1
        return {
            "workspace_lint": {
                "status": "pass",
                "current_value": "0 文件",
                "path": "workspace",
                "risk": "无",
                "action": "无需操作",
                "message": "ok",
            }
        }

    import agent.health_check as hc

    monkeypatch.setattr(hc, "collect_health_results", fake_collect)

    rc = main_module.main(["health"])

    assert rc == 0
    assert called["n"] == 1
    out = capsys.readouterr().out
    assert "项目健康检查报告" in out
    assert "workspace_lint" in out


def test_health_subcommand_does_not_start_main_loop(monkeypatch):
    triggered = []

    monkeypatch.setattr(
        main_module, "init_session", lambda: triggered.append("init_session")
    )
    monkeypatch.setattr(
        main_module,
        "try_resume_from_checkpoint",
        lambda: triggered.append("resume"),
    )
    monkeypatch.setattr(
        main_module, "main_loop", lambda: triggered.append("main_loop")
    )

    import agent.health_check as hc

    monkeypatch.setattr(hc, "collect_health_results", lambda: {})

    rc = main_module.main(["health"])

    assert rc == 0
    assert triggered == []


def test_health_json_subcommand_emits_valid_json(monkeypatch, capsys):
    """`python main.py health --json` 必须输出可解析 JSON，schema 稳定。"""
    import agent.health_check as hc

    monkeypatch.setattr(
        hc,
        "collect_health_results",
        lambda: {
            "log_size": {
                "status": "warn",
                "current_value": "12.5 MB",
                "path": "agent_log.jsonl",
                "risk": "占空间",
                "action": "归档命令",
                "message": "warn",
            }
        },
    )

    rc = main_module.main(["health", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["overall"] == "warn"
    assert "log_size" in payload["checks"]
    assert payload["checks"]["log_size"]["status"] == "warn"
    assert payload["checks"]["log_size"]["current_value"] == "12.5 MB"
