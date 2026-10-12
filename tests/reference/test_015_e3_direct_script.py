"""015 E3 runner 的有界 direct-script 入口测试。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_015_e3.py"


def test_015_e3_direct_script_help_exits_without_running_gates() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=5,
        cwd=str(ROOT),
        check=False,
    )
    assert result.returncode == 0
    assert "Run the frozen 015 real-model E3" in result.stdout
    assert "[offline]" not in result.stdout + result.stderr


def test_015_e3_direct_script_rejects_unknown_argument_without_running_gates() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--unknown"],
        capture_output=True,
        text=True,
        timeout=5,
        cwd=str(ROOT),
        check=False,
    )
    assert result.returncode == 2
    assert "unrecognized arguments: --unknown" in result.stderr
    assert "[offline]" not in result.stdout + result.stderr
