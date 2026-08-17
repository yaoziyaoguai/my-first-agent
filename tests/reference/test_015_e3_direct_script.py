"""015 E3 runner direct-script import path test.

Red: running `.venv/bin/python scripts/run_015_e3.py` directly must be able to
import `agent.*` modules in the config-present path. Before fix, sys.path only
contained scripts/, causing ModuleNotFoundError at `from agent.provider.config import ...`.
After fix, REPO is in sys.path.

This test does NOT make real network calls or read keys. It uses dummy config
and a short timeout — the script starts offline gates (which take >2 min), gets
killed, and we assert no ModuleNotFoundError appeared in stderr before the kill.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_015_e3.py"


def test_015_e3_direct_script_can_import_agent_in_config_present_path() -> None:
    """Direct script execution must import agent.* without ModuleNotFoundError.

    Before fix: crash at `from agent.provider.config import AgentProviderConfig`.
    After fix: starts offline gates (killed by timeout, no import error).
    """

    env = {
        **os.environ,
        "FIRST_AGENT_015_E3_PROVIDER": "openai_compatible",
        "FIRST_AGENT_015_E3_BASE_URL": "https://invalid.example",
        "FIRST_AGENT_015_E3_MODEL": "test-model",
        "FIRST_AGENT_015_E3_API_KEY": "dummy-key-not-used",
    }
    proc = subprocess.Popen(
        [sys.executable, str(SCRIPT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(ROOT),
    )
    try:
        proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
    else:
        stdout, stderr = proc.communicate()

    combined = (stdout + stderr).decode("utf-8", errors="replace")
    assert "No module named 'agent'" not in combined, (
        f"ModuleNotFoundError in direct script path:\n{combined}"
    )
    assert "ModuleNotFoundError" not in combined, (
        f"ModuleNotFoundError in direct script path:\n{combined}"
    )
