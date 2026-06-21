"""R-G03: CLI-level resume validation via subprocess.

Creates a real checkpoint, starts main.py (--provider fake, safe), and verifies the CLI
detects + reports the saved checkpoint on startup. Uses --provider fake so no real API
calls are made. This upgrades R-G03 from contract-only to CLI-level validation.
"""

from __future__ import annotations

import subprocess
import sys

from agent.checkpoint import CHECKPOINT_PATH, clear_checkpoint, save_checkpoint
from agent.state import create_agent_state


def test_cli_startup_detects_and_reports_checkpoint():
    """R-G03: CLI startup detects a saved checkpoint and reports resume status."""
    clear_checkpoint(path=CHECKPOINT_PATH)
    state = create_agent_state(system_prompt="cli resume test")
    state.task.status = "running"
    state.task.user_goal = "cli resume subprocess test"
    save_checkpoint(state, source="r_g03_cli_test", path=CHECKPOINT_PATH)
    try:
        result = subprocess.run(
            [sys.executable, "main.py", "--provider", "fake"],
            input="quit\n",
            capture_output=True,
            text=True,
            timeout=45,
        )
        output = result.stdout + result.stderr
        assert "resume" in output.lower() or "断点" in output or "恢复" in output
    finally:
        clear_checkpoint(path=CHECKPOINT_PATH)
