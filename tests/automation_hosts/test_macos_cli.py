from __future__ import annotations

import json
from datetime import UTC, datetime

from agent.automation_hosts.macos_cli import (
    MacOSHostCLIUnavailableError,
    run_macos_cli,
)
from tests.automation.test_composition import _active_core


def test_host_cli_builds_one_trusted_core_then_reuses_the_portable_dispatch() -> None:
    core, _, _, _ = _active_core(now=datetime(2026, 8, 27, tzinfo=UTC))
    factory_calls: list[str] = []
    output: list[str] = []

    result = run_macos_cli(
        ["wake", "enable"],
        core_factory=lambda: factory_calls.append("core") or core,
        write_fn=output.append,
    )

    assert result == 0
    assert factory_calls == ["core"]
    assert json.loads(output[0])["code"] == "wake_enabled"


def test_host_cli_renders_only_a_closed_configuration_reason() -> None:
    output: list[str] = []

    def unavailable():  # noqa: ANN202
        raise MacOSHostCLIUnavailableError("launchd_unavailable")

    result = run_macos_cli(
        ["reconcile"],
        core_factory=unavailable,
        write_fn=output.append,
    )

    assert result == 2
    assert json.loads(output[0]) == {
        "code": "needs_019_config",
        "reason": "launchd_unavailable",
    }


def test_host_cli_never_renders_an_unexpected_exception() -> None:
    output: list[str] = []

    def broken():  # noqa: ANN202
        raise RuntimeError("TASK_SENTINEL /private/path CREDENTIAL_SENTINEL")

    result = run_macos_cli(
        ["reconcile"],
        core_factory=broken,
        write_fn=output.append,
    )

    assert result == 2
    assert json.loads(output[0]) == {
        "code": "needs_019_config",
        "reason": "host_composition_failed",
    }
    assert "SENTINEL" not in output[0]
