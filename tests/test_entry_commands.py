"""Entry command clarification contract tests.

守护 main.py 入口命令语义：
- --plain → simple/plain CLI backend
- --tui / --textual → textual backend
- --shell → deprecated, prints warning, still works as plain CLI
- default (no flags) → plain CLI
"""

from __future__ import annotations

import main as main_module


def _mock_main_runtime(monkeypatch):
    """Mock 所有 main() 中的 runtime/session 操作，只留纯入口逻辑。"""
    monkeypatch.setattr(main_module, "load_legacy_dotenv_config", lambda project_root: None)
    monkeypatch.setattr(main_module, "_init_mcp_bridge_if_enabled", lambda **kw: None)
    monkeypatch.setattr(main_module, "init_session", lambda **kw: None)
    monkeypatch.setattr(main_module, "try_resume_from_checkpoint", lambda: None)


# ── --plain ──


def test_plain_flag_sets_simple_backend(monkeypatch):
    """--plain 明确进入 simple/plain CLI backend。"""
    import os

    monkeypatch.delenv(main_module.INPUT_BACKEND_ENV, raising=False)
    _mock_main_runtime(monkeypatch)
    monkeypatch.setattr(main_module, "main_loop", lambda **kw: None)

    assert main_module.main(["--plain"]) == 0
    assert os.environ.get(main_module.INPUT_BACKEND_ENV, "simple") == "simple"


def test_plain_flag_does_not_set_textual_env(monkeypatch):
    """--plain 不应该设置 MY_FIRST_AGENT_INPUT_BACKEND=textual。"""
    import os
    monkeypatch.delenv(main_module.INPUT_BACKEND_ENV, raising=False)
    _mock_main_runtime(monkeypatch)
    monkeypatch.setattr(main_module, "main_loop", lambda **kw: None)

    main_module.main(["--plain"])
    assert os.environ.get(main_module.INPUT_BACKEND_ENV, "simple") == "simple"


# ── --tui ──


def test_tui_flag_sets_textual_backend(monkeypatch):
    """--tui 设置 MY_FIRST_AGENT_INPUT_BACKEND=textual 并进入 textual backend。"""
    import os

    monkeypatch.setattr(os, "environ", {})
    _mock_main_runtime(monkeypatch)
    monkeypatch.setattr(main_module, "run_textual_main_loop", lambda **kw: None)

    exit_code = main_module.main(["--tui"])
    assert exit_code == 0
    assert os.environ.get(main_module.INPUT_BACKEND_ENV) == "textual"


def test_tui_flag_calls_run_textual_main_loop(monkeypatch):
    """--tui 应调用 run_textual_main_loop 而非 main_loop。"""
    import os

    calls = []

    monkeypatch.setattr(os, "environ", {})
    _mock_main_runtime(monkeypatch)
    monkeypatch.setattr(main_module, "run_textual_main_loop", lambda **kw: calls.append("textual"))
    monkeypatch.setattr(main_module, "main_loop", lambda **kw: calls.append("simple"))

    assert main_module.main(["--tui"]) == 0
    assert "textual" in calls
    assert "simple" not in calls


# ── --textual ──


def test_textual_flag_is_alias_for_tui(monkeypatch):
    """--textual 是 --tui 的别名，同样设置 textual backend。"""
    import os

    monkeypatch.setattr(os, "environ", {})
    _mock_main_runtime(monkeypatch)
    monkeypatch.setattr(main_module, "run_textual_main_loop", lambda **kw: None)

    exit_code = main_module.main(["--textual"])
    assert exit_code == 0
    assert os.environ.get(main_module.INPUT_BACKEND_ENV) == "textual"


# ── --shell (deprecated) ──


def test_shell_flag_prints_deprecation_warning(monkeypatch, capsys):
    """--shell 输出清晰的弃用提示，明确引导用户使用 --plain 或 --tui。"""
    _mock_main_runtime(monkeypatch)
    monkeypatch.setattr(main_module, "main_loop", lambda **kw: None)

    main_module.main(["--shell"])
    captured = capsys.readouterr()
    stderr_output = captured.err

    assert "--shell" in stderr_output
    assert "deprecated" in stderr_output.lower()
    assert "--plain" in stderr_output
    assert "--tui" in stderr_output


def test_shell_flag_still_works_as_plain_cli(monkeypatch):
    """--shell 虽然弃用，但仍正确进入 plain CLI（backward compatibility）。"""
    calls = []

    _mock_main_runtime(monkeypatch)
    monkeypatch.setattr(main_module, "main_loop", lambda **kw: calls.append("loop"))
    monkeypatch.setattr(main_module, "_selected_input_backend", lambda: "simple")

    assert main_module.main(["--shell"]) == 0
    assert calls == ["loop"]


def test_shell_flag_does_not_activate_textual(monkeypatch):
    """--shell 不应该激活 textual backend。"""
    import os

    monkeypatch.setattr(os, "environ", {})
    _mock_main_runtime(monkeypatch)
    monkeypatch.setattr(main_module, "main_loop", lambda **kw: None)

    main_module.main(["--shell"])
    assert os.environ.get(main_module.INPUT_BACKEND_ENV, "simple") == "simple"


# ── 默认（无 flag） ──


def test_default_no_flags_still_plain_cli(monkeypatch):
    """不传任何 flag 的默认行为仍是 plain CLI，不改变。"""
    calls = []

    _mock_main_runtime(monkeypatch)
    monkeypatch.setattr(main_module, "main_loop", lambda **kw: calls.append("loop"))
    monkeypatch.setattr(main_module, "_selected_input_backend", lambda: "simple")

    assert main_module.main([]) == 0
    assert calls == ["loop"]


# ── 组合 flag 行为 ──


def test_help_flag_still_works(monkeypatch, capsys):
    """--help / -h 仍输出 onboarding 文案，不被新 flag 干扰。"""
    monkeypatch.setattr(main_module, "load_legacy_dotenv_config", lambda project_root: None)
    assert main_module.main(["--help"]) == 0
    assert "First Agent" in capsys.readouterr().out


def test_unknown_command_still_falls_through(monkeypatch):
    """未知的 positional arg 不应被新 flag 吃掉，delegate 给 maintenance dispatch。"""
    monkeypatch.setattr(main_module, "load_legacy_dotenv_config", lambda project_root: None)
    monkeypatch.setattr(main_module, "dispatch_maintenance_command", lambda argv, project_root: 42)
    assert main_module.main(["demo"]) == 42
