from __future__ import annotations

import os
import plistlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.automation_hosts.launchd import (
    LAUNCHD_E3_LABEL,
    LAUNCHD_PRODUCT_LABEL,
    LaunchdConfigurationV1,
    LaunchdWakeAdapter,
    standard_user_launch_agents_root,
)


def _configuration(tmp_path: Path, *, interval: int = 60) -> LaunchdConfigurationV1:
    executable = tmp_path / "bin" / "first-agent-schedule"
    executable.parent.mkdir(mode=0o700)
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    launch_agents = tmp_path / "LaunchAgents"
    launch_agents.mkdir(mode=0o700)
    state_root = tmp_path / "wake-state"
    state_root.mkdir(mode=0o700)
    return LaunchdConfigurationV1(
        installed_executable=executable,
        launch_agents_root=launch_agents,
        state_root=state_root,
        start_interval_seconds=interval,
        policy_digest="8" * 64,
    )


def test_canonical_plist_contains_only_the_fixed_global_wake_contract(
    tmp_path: Path,
) -> None:
    configuration = _configuration(tmp_path)

    payload = LaunchdWakeAdapter.render(configuration)
    document = plistlib.loads(payload)

    assert document == {
        "Label": LAUNCHD_PRODUCT_LABEL,
        "ProgramArguments": [
            os.fspath(configuration.installed_executable),
            "reconcile",
        ],
        "RunAtLoad": False,
        "StartInterval": 60,
    }
    assert payload == LaunchdWakeAdapter.render(configuration)
    for sentinel in (
        "TASK_SENTINEL",
        "CREDENTIAL_SENTINEL",
        "AUTOMATION_SENTINEL",
        "https://private.invalid",
        "--state-root",
        "EnvironmentVariables",
        "/bin/sh",
    ):
        assert sentinel.encode() not in payload


@pytest.mark.parametrize("interval", [0, 14, 3601, True])
def test_configuration_rejects_an_unbounded_start_interval(
    tmp_path: Path,
    interval: object,
) -> None:
    with pytest.raises(ValueError, match="start_interval_seconds"):
        _configuration(tmp_path, interval=interval)  # type: ignore[arg-type]


def test_configuration_rejects_symlinked_or_non_executable_program(
    tmp_path: Path,
) -> None:
    configuration = _configuration(tmp_path)
    target = configuration.installed_executable
    linked = target.with_name("linked-schedule")
    linked.symlink_to(target)

    with pytest.raises(ValueError, match="installed_executable"):
        LaunchdConfigurationV1(
            installed_executable=linked,
            launch_agents_root=configuration.launch_agents_root,
            state_root=configuration.state_root,
            start_interval_seconds=60,
            policy_digest="8" * 64,
        )


def test_only_the_fixed_product_and_dedicated_e3_labels_are_accepted(
    tmp_path: Path,
) -> None:
    configuration = _configuration(tmp_path)
    e3 = LaunchdConfigurationV1(
        installed_executable=configuration.installed_executable,
        launch_agents_root=configuration.launch_agents_root,
        state_root=configuration.state_root,
        start_interval_seconds=60,
        policy_digest="8" * 64,
        label=LAUNCHD_E3_LABEL,
    )
    assert plistlib.loads(LaunchdWakeAdapter.render(e3))["Label"] == LAUNCHD_E3_LABEL

    unique_e3_label = f"{LAUNCHD_E3_LABEL}.0123456789ab"
    unique_e3 = LaunchdConfigurationV1(
        installed_executable=configuration.installed_executable,
        launch_agents_root=configuration.launch_agents_root,
        state_root=configuration.state_root,
        start_interval_seconds=60,
        policy_digest="8" * 64,
        label=unique_e3_label,
    )
    assert plistlib.loads(LaunchdWakeAdapter.render(unique_e3))["Label"] == unique_e3_label

    with pytest.raises(ValueError, match="fixed product labels"):
        LaunchdConfigurationV1(
            installed_executable=configuration.installed_executable,
            launch_agents_root=configuration.launch_agents_root,
            state_root=configuration.state_root,
            start_interval_seconds=60,
            policy_digest="8" * 64,
            label="com.example.user-controlled",
        )


def test_standard_launch_agents_root_comes_from_the_account_database(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "agent.automation_hosts.launchd.pwd.getpwuid",
        lambda uid: SimpleNamespace(pw_dir=f"/Users/owner-{uid}"),
    )

    assert standard_user_launch_agents_root(uid=501) == Path(
        "/Users/owner-501/Library/LaunchAgents"
    )
