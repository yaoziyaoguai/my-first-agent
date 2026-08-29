from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from agent.automation.wake import WakeInstallOutcome, WakeRemoveOutcome
from agent.automation_hosts.launchd import (
    LAUNCHD_E3_LABEL,
    LaunchdCommandOutcome,
    LaunchdCommandResultV1,
    LaunchdConfigurationV1,
    LaunchdWakeAdapter,
    standard_user_launch_agents_root,
)


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS launchd is required")
def test_real_launchd_wakes_one_fixed_reconcile_command_and_cleans_up(
) -> None:
    if os.environ.get("FIRST_AGENT_RUN_REAL_LAUNCHD") != "1":
        pytest.skip("real launchd probe requires explicit host gate")
    root = Path(tempfile.mkdtemp(prefix="first-agent-019-launchd-", dir="/private/tmp"))
    root.chmod(0o700)
    bin_root = root / "bin"
    launch_agents = standard_user_launch_agents_root()
    state_root = root / "state"
    for directory in (bin_root, state_root):
        directory.mkdir(mode=0o700)
    marker = root / "wake-marker"
    executable = bin_root / "first-agent-schedule"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "from pathlib import Path\n"
        "if sys.argv[1:] != ['reconcile']:\n"
        "    raise SystemExit(64)\n"
        f"Path({os.fspath(marker)!r}).touch()\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    suffix = hashlib.sha256(os.fspath(root).encode()).hexdigest()[:12]
    configuration = LaunchdConfigurationV1(
        installed_executable=executable,
        launch_agents_root=launch_agents,
        state_root=state_root,
        start_interval_seconds=15,
        policy_digest="8" * 64,
        label=f"{LAUNCHD_E3_LABEL}.{suffix}",
    )
    diagnostics: dict[str, object] = {}

    def run_launchctl(
        argv: tuple[str, ...],
        timeout_seconds: float,
    ) -> LaunchdCommandResultV1:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
        combined = (completed.stdout + completed.stderr)[:4_096]
        diagnostics.update(
            {
                "returncode": completed.returncode,
                "permission_denied": b"Operation not permitted" in combined,
                "io_error": b"Input/output error" in combined,
                "already_loaded": b"already loaded" in combined.lower(),
            }
        )
        return LaunchdCommandResultV1(
            LaunchdCommandOutcome.SUCCEEDED
            if completed.returncode == 0
            else LaunchdCommandOutcome.UNKNOWN
        )

    adapter = LaunchdWakeAdapter(configuration, command_runner=run_launchctl)
    installed = adapter.install(configuration.policy_digest)
    removed: WakeRemoveOutcome | None = None
    try:
        if installed.outcome is WakeInstallOutcome.UNKNOWN and diagnostics.get(
            "io_error"
        ) is True:
            pytest.skip("current managed host cannot bootstrap a test LaunchAgent")
        assert installed.outcome is WakeInstallOutcome.INSTALLED, diagnostics
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline and not marker.exists():
            time.sleep(0.1)
        assert marker.is_file()
    finally:
        if installed.outcome is WakeInstallOutcome.INSTALLED:
            removed = adapter.remove(configuration.policy_digest).outcome
            assert removed is WakeRemoveOutcome.REMOVED
        if installed.outcome is WakeInstallOutcome.FAILED:
            removed = WakeRemoveOutcome.REMOVED
        if removed is WakeRemoveOutcome.REMOVED:
            shutil.rmtree(root)
