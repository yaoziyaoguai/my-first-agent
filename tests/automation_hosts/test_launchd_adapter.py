from __future__ import annotations

import os
from pathlib import Path

from agent.automation.wake import (
    WakeInstallOutcome,
    WakeReadbackOutcome,
    WakeRemoveOutcome,
)
from agent.automation_hosts.launchd import (
    LaunchdCommandOutcome,
    LaunchdCommandResultV1,
    LaunchdConfigurationV1,
    LaunchdWakeAdapter,
)


def _configuration(tmp_path: Path) -> LaunchdConfigurationV1:
    executable = tmp_path / "bin" / "first-agent-schedule"
    executable.parent.mkdir(mode=0o700)
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    launch_agents = tmp_path / "LaunchAgents"
    launch_agents.mkdir(mode=0o700)
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    return LaunchdConfigurationV1(
        installed_executable=executable,
        launch_agents_root=launch_agents,
        state_root=state_root,
        start_interval_seconds=60,
        policy_digest="8" * 64,
    )


class _Runner:
    def __init__(self, *outcomes: LaunchdCommandOutcome) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self,
        argv: tuple[str, ...],
        timeout_seconds: float,
    ) -> LaunchdCommandResultV1:
        assert timeout_seconds == 10.0
        self.calls.append(argv)
        return LaunchdCommandResultV1(self.outcomes.pop(0))


def test_install_readback_and_remove_use_exact_launchctl_argv(tmp_path: Path) -> None:
    configuration = _configuration(tmp_path)
    runner = _Runner(
        LaunchdCommandOutcome.SUCCEEDED,
        LaunchdCommandOutcome.SUCCEEDED,
    )
    adapter = LaunchdWakeAdapter(configuration, command_runner=runner)

    installed = adapter.install(configuration.policy_digest)
    readback = adapter.readback(configuration.policy_digest)
    removed = adapter.remove(configuration.policy_digest)

    assert installed.outcome is WakeInstallOutcome.INSTALLED
    assert readback.outcome is WakeReadbackOutcome.INSTALLED
    assert removed.outcome is WakeRemoveOutcome.REMOVED
    assert runner.calls == [
        (
            "/bin/launchctl",
            "bootstrap",
            f"gui/{os.geteuid()}",
            os.fspath(adapter.plist_path),
        ),
        (
            "/bin/launchctl",
            "bootout",
            f"gui/{os.geteuid()}",
            os.fspath(adapter.plist_path),
        ),
    ]
    assert not adapter.plist_path.exists()


def test_unknown_bootstrap_is_durable_and_cannot_be_overwritten(tmp_path: Path) -> None:
    configuration = _configuration(tmp_path)
    first_runner = _Runner(LaunchdCommandOutcome.UNKNOWN)
    first = LaunchdWakeAdapter(configuration, command_runner=first_runner)

    assert first.install(configuration.policy_digest).outcome is WakeInstallOutcome.UNKNOWN

    second_runner = _Runner(LaunchdCommandOutcome.SUCCEEDED)
    second = LaunchdWakeAdapter(configuration, command_runner=second_runner)
    assert second.readback(configuration.policy_digest).outcome is WakeReadbackOutcome.UNKNOWN
    assert second.install(configuration.policy_digest).outcome is WakeInstallOutcome.UNKNOWN
    assert second_runner.calls == []


def test_known_bootstrap_failure_removes_only_the_exact_staged_plist(
    tmp_path: Path,
) -> None:
    configuration = _configuration(tmp_path)
    adapter = LaunchdWakeAdapter(
        configuration,
        command_runner=_Runner(LaunchdCommandOutcome.NOT_EXECUTED),
    )

    assert adapter.install(configuration.policy_digest).outcome is WakeInstallOutcome.FAILED
    assert adapter.readback(configuration.policy_digest).outcome is WakeReadbackOutcome.ABSENT
    assert not adapter.plist_path.exists()


def test_unknown_bootout_preserves_the_plist_and_blocks_repair(tmp_path: Path) -> None:
    configuration = _configuration(tmp_path)
    adapter = LaunchdWakeAdapter(
        configuration,
        command_runner=_Runner(
            LaunchdCommandOutcome.SUCCEEDED,
            LaunchdCommandOutcome.UNKNOWN,
        ),
    )
    assert adapter.install(configuration.policy_digest).outcome is WakeInstallOutcome.INSTALLED

    assert adapter.remove(configuration.policy_digest).outcome is WakeRemoveOutcome.UNKNOWN
    assert adapter.plist_path.exists()

    reopened_runner = _Runner(LaunchdCommandOutcome.SUCCEEDED)
    reopened = LaunchdWakeAdapter(configuration, command_runner=reopened_runner)
    assert reopened.readback(configuration.policy_digest).outcome is WakeReadbackOutcome.UNKNOWN
    assert reopened.install(configuration.policy_digest).outcome is WakeInstallOutcome.UNKNOWN
    assert reopened_runner.calls == []


def test_drifted_replacement_is_never_removed_or_compatibility_repaired(
    tmp_path: Path,
) -> None:
    configuration = _configuration(tmp_path)
    runner = _Runner(LaunchdCommandOutcome.SUCCEEDED)
    adapter = LaunchdWakeAdapter(configuration, command_runner=runner)
    assert adapter.install(configuration.policy_digest).outcome is WakeInstallOutcome.INSTALLED
    adapter.plist_path.write_bytes(b"replacement")
    adapter.plist_path.chmod(0o600)

    assert adapter.readback(configuration.policy_digest).outcome is WakeReadbackOutcome.DRIFT
    assert adapter.remove(configuration.policy_digest).outcome is WakeRemoveOutcome.UNKNOWN
    assert adapter.plist_path.read_bytes() == b"replacement"


def test_disable_refuses_while_a_worker_is_running(tmp_path: Path) -> None:
    configuration = _configuration(tmp_path)
    runner = _Runner(LaunchdCommandOutcome.SUCCEEDED)
    adapter = LaunchdWakeAdapter(
        configuration,
        command_runner=runner,
        worker_running=lambda: True,
    )
    assert adapter.install(configuration.policy_digest).outcome is WakeInstallOutcome.INSTALLED

    assert adapter.remove(configuration.policy_digest).outcome is WakeRemoveOutcome.BUSY
    assert len(runner.calls) == 1
    assert adapter.plist_path.exists()


def test_executable_identity_drift_blocks_install_before_launchctl(tmp_path: Path) -> None:
    configuration = _configuration(tmp_path)
    executable = configuration.installed_executable
    executable.unlink()
    executable.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
    executable.chmod(0o700)
    runner = _Runner(LaunchdCommandOutcome.SUCCEEDED)
    adapter = LaunchdWakeAdapter(configuration, command_runner=runner)

    assert adapter.readback(configuration.policy_digest).outcome is WakeReadbackOutcome.DRIFT
    assert adapter.install(configuration.policy_digest).outcome is WakeInstallOutcome.UNKNOWN
    assert runner.calls == []


def test_symlinked_plist_is_unknown_and_is_not_replaced(tmp_path: Path) -> None:
    configuration = _configuration(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("do not replace", encoding="utf-8")
    outside.chmod(0o600)
    adapter = LaunchdWakeAdapter(configuration, command_runner=_Runner())
    adapter.plist_path.symlink_to(outside)

    assert adapter.readback(configuration.policy_digest).outcome is WakeReadbackOutcome.UNKNOWN
    assert adapter.install(configuration.policy_digest).outcome is WakeInstallOutcome.UNKNOWN
    assert outside.read_text(encoding="utf-8") == "do not replace"


def test_policy_mismatch_never_installs_the_fixed_adapter(tmp_path: Path) -> None:
    configuration = _configuration(tmp_path)
    runner = _Runner(LaunchdCommandOutcome.SUCCEEDED)
    adapter = LaunchdWakeAdapter(configuration, command_runner=runner)

    assert adapter.readback("9" * 64).outcome is WakeReadbackOutcome.DRIFT
    assert adapter.install("9" * 64).outcome is WakeInstallOutcome.UNKNOWN
    assert runner.calls == []
