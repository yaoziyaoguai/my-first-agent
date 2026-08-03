from __future__ import annotations

import subprocess
import sys


def test_base_imports_work_without_textual() -> None:
    code = (
        "import sys\n"
        "sys.modules['textual'] = None\n"
        "import agent.cli.actions, agent.tui.adapter, agent.tui.render\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_run_tui_gives_install_hint_without_textual() -> None:
    code = (
        "import sys\n"
        "sys.modules['textual'] = None\n"
        "from agent.tui.app import run_tui, TextualNotInstalledError\n"
        "try:\n"
        "    run_tui(None, run_id_factory=lambda: 'r')\n"
        "except TextualNotInstalledError as error:\n"
        "    print('HINT', 'tui' in str(error).lower() and 'extra' in str(error).lower())\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "HINT True" in result.stdout
