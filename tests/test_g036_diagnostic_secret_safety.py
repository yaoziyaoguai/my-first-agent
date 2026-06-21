"""G-036 (Phase 1): broad diagnostic-output secret safety contract.

R-004 (G-004) real-config-verified redaction for `main.py status`. This test
extends the secret-safety contract to the BROADER diagnostic surface: no
diagnostic command (`status`, `health`, `provider-diagnostics`) may emit a
secret-shaped token or a raw config body, regardless of the configured key.

Runs by default (it is a static output contract — these commands must never leak
a secret; the assertion holds whether or not a real key is configured).
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

# A secret-shaped token: the common api-key prefix followed by enough chars to
# be a real credential (not a short placeholder word).
_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{12,}")
# A raw config body leak: an api_key assignment with a long inline value.
_RAW_KEY_ASSIGNMENT = re.compile(r'api[_-]key["\']?\s*[:=]\s*["\']?sk-[A-Za-z0-9_-]{8,}')

_DIAGNOSTIC_COMMANDS = [
    pytest.param("status", id="status"),
    pytest.param("health", id="health"),
    pytest.param("provider-diagnostics", id="provider-diagnostics"),
]


def _run(cmd: str) -> str:
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py"), cmd],
        capture_output=True,
        text=True,
        timeout=40,
        cwd=str(PROJECT_ROOT),
        env=os.environ,
    )
    assert result.returncode in {0, 1, 2}, (
        f"main.py {cmd} exited {result.returncode}; stderr={result.stderr[:300]!r}"
    )
    return result.stdout + result.stderr


@pytest.mark.parametrize("cmd", _DIAGNOSTIC_COMMANDS)
def test_diagnostic_command_does_not_leak_secret(cmd: str) -> None:
    """No diagnostic command may emit a secret-shaped token or raw key body."""
    output = _run(cmd)
    assert not _SECRET_PATTERN.search(output), (
        f"main.py {cmd} leaked a secret-shaped token (output suppressed)"
    )
    assert not _RAW_KEY_ASSIGNMENT.search(output), (
        f"main.py {cmd} leaked a raw api_key assignment (output suppressed)"
    )
