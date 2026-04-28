"""验证 `python main.py health` 子命令独立可运行（v0.2 release 收口）。

run_health_check 已经存在；本测试只确保 main.py 暴露的健康检查入口
不会因为后续重构悄悄断掉。它对应 docs/V0_2_HEALTH_MAINTENANCE.md。
"""
import main as main_module


def test_health_subcommand_invokes_health_check(monkeypatch, capsys):
    called = {"n": 0}

    def fake_health():
        called["n"] += 1
        return {"workspace_lint": {"status": "pass"}}

    import agent.health_check as hc

    monkeypatch.setattr(hc, "run_health_check", fake_health)

    rc = main_module.main(["health"])

    assert rc == 0
    assert called["n"] == 1


def test_health_subcommand_does_not_start_main_loop(monkeypatch):
    """health 子命令必须不调用 init_session / main_loop / try_resume，
    避免人工 health 检查时被强制进入对话或 resume prompt。"""
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

    monkeypatch.setattr(hc, "run_health_check", lambda: {})

    rc = main_module.main(["health"])

    assert rc == 0
    assert triggered == [], f"health 子命令不应触发主循环，但触发了：{triggered}"
