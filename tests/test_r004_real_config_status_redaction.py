"""R-004 (Phase 0 / G-004): real-config status redaction reproducible check.

`python main.py status` must never echo the REAL api_key configured in
config/config.yaml. The synthetic R-G01 tests (test_r_status_redaction.py and
test_provider_diagnostics.py::test_main_status_command_no_secret_leakage) prove
the redaction code path with placeholder keys. This opt-in test repeats the
check against the REAL configured key — closing the R-004 gap (the prior proof
was synthetic/static only).

Opt-in only (skip by default):
  - MY_FIRST_AGENT_RUN_REAL_PROVIDER_SMOKE=1, AND
  - config/config.yaml has a real, non-placeholder inline api_key.

Safety: the real key is read into a local variable only to test for substring
presence; it is never printed. The assertion uses a precomputed boolean so
pytest never displays the key-bearing output on failure.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

# If the configured key contains any of these fragments it is a placeholder,
# not a real credential — the test skips (cannot prove real-config redaction).
_PLACEHOLDER_FRAGMENTS = (
    "test",
    "fake",
    "dummy",
    "placeholder",
    "replace",
    "example",
    "changeme",
    "your-api-key",
    "your-key",
    "must-not-leak",
)


def _load_real_api_key() -> str:
    """Return the inline api_key from config/config.yaml, or '' if absent.

    Never raises on missing/unreadable config; returns '' so the test can skip.
    """
    try:
        import yaml  # type: ignore[import-untyped]

        cfg = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    except FileNotFoundError:
        return ""
    except Exception:
        return ""
    provider = cfg.get("provider") or {}
    key = provider.get("api_key")
    if isinstance(key, str) and key:
        return key
    return ""


def _real_ready() -> tuple[bool, str]:
    opt_in = os.environ.get("MY_FIRST_AGENT_RUN_REAL_PROVIDER_SMOKE", "") == "1"
    if not opt_in:
        return False, "set MY_FIRST_AGENT_RUN_REAL_PROVIDER_SMOKE=1 to run R-004 real-config check"
    key = _load_real_api_key()
    if not key or len(key) < 12:
        return False, "no real inline api_key in config/config.yaml"
    if any(frag in key.lower() for frag in _PLACEHOLDER_FRAGMENTS):
        return False, "configured api_key looks like a placeholder"
    return True, ""


_READY, _REASON = _real_ready()
pytestmark = pytest.mark.skipif(not _READY, reason=_REASON)


def test_real_config_status_does_not_echo_real_api_key() -> None:
    """R-004: main.py status must not echo the real configured api_key.

    The real key lives only in a local variable for a substring check; it is
    never printed. On failure the message names the leak without revealing the
    key or the status output.
    """
    real_key = _load_real_api_key()
    assert real_key and len(real_key) >= 12  # gating invariant

    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py"), "status"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(PROJECT_ROOT),
        env=os.environ,
    )
    output = result.stdout + result.stderr
    # Precompute so pytest never displays key-bearing output on failure.
    leaked = real_key in output
    assert not leaked, (
        "R-004 FAIL: real configured api_key leaked into 'main.py status' output "
        "(key value and output suppressed)"
    )
