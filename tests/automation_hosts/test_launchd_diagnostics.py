from __future__ import annotations

from pathlib import Path

from agent.automation.wake import WakeInstallOutcome
from agent.automation_hosts.launchd import LaunchdConfigurationV1, LaunchdWakeAdapter


def test_command_exception_returns_only_a_closed_unknown_result(tmp_path: Path) -> None:
    executable = tmp_path / "first-agent-schedule"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    launch_agents = tmp_path / "LaunchAgents"
    launch_agents.mkdir(mode=0o700)
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    configuration = LaunchdConfigurationV1(
        installed_executable=executable,
        launch_agents_root=launch_agents,
        state_root=state_root,
        start_interval_seconds=60,
        policy_digest="8" * 64,
    )

    def raise_private_text(argv, timeout_seconds):  # noqa: ANN001, ARG001
        raise RuntimeError("TASK_SENTINEL /private/path CREDENTIAL_SENTINEL")

    result = LaunchdWakeAdapter(
        configuration,
        command_runner=raise_private_text,
    ).install(configuration.policy_digest)

    assert result.outcome is WakeInstallOutcome.UNKNOWN
    assert "SENTINEL" not in repr(result)
    assert not hasattr(result, "stdout")
    assert not hasattr(result, "stderr")
