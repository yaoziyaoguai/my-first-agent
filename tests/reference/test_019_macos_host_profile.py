from __future__ import annotations

import json
import os
import stat
import subprocess
from dataclasses import replace

import pytest

from agent.runtime.contracts import BudgetReport, ContextPack, ModelMessage
from scripts import _019_macos_u2b_host as host_fixture
from scripts import run_019_macos_e3 as runner
from scripts.run_019_macos_e3 import SCHEMA, MacOSU2BPreflightV1

ROOT = runner.REPO


def _preflight() -> MacOSU2BPreflightV1:
    return MacOSU2BPreflightV1(
        schema=SCHEMA,
        status="qualified",
        reason="qualified",
        launchd_wake_observed=True,
        launchd_cleanup_confirmed=True,
        seatbelt_available=True,
        browser_runtime_available=True,
        probe_identity_digest="1" * 64,
    )


def _u2b_receipt() -> dict[str, object]:
    return {
        "schema": runner.U2B_RECEIPT_SCHEMA,
        "status": "qualified",
        "materialized_root_sha256": "1" * 64,
        "seal_sha256": "2" * 64,
        "verifier_sha256": "3" * 64,
        "runner_sha256": "4" * 64,
        "wheel_sha256": "5" * 64,
        "host_profile_sha256": "6" * 64,
        "sandbox_backend_sha256": "7" * 64,
        "browser_identity_sha256": "8" * 64,
        "launchd_adapter_sha256": "9" * 64,
        "supervisor_identity_sha256": "a" * 64,
        "fixture_sha256": "b" * 64,
        "host_root_identity_sha256": "c" * 64,
        "spec_product_review_sha256": "d" * 64,
        "standards_architecture_review_sha256": "e" * 64,
        "journey": {key: True for key in runner.U2B_JOURNEY_KEYS},
        "counters": {
            "real_wakes": 3,
            "child_dispatches": 1,
            "provider_calls": 3,
            "tool_calls": 1,
            "sandbox_receipts": 1,
            "browser_observations": 1,
            "duplicate_provider_delta": 0,
            "duplicate_tool_delta": 0,
            "duplicate_effect_delta": 0,
            "misfire_provider_delta": 0,
            "misfire_tool_delta": 0,
            "misfire_effect_delta": 0,
        },
        "mutation_gate": {"exit_code": 0, "pass_count": 12, "node_count": 12},
        "source_full_gate": {"exit_code": 0, "pass_count": 100, "node_count": 100},
        "materialized_full_gate": {
            "exit_code": 0,
            "pass_count": 100,
            "node_count": 100,
        },
    }


def test_preflight_result_is_closed_and_contains_no_host_or_private_payload() -> None:
    result = _preflight()
    rendered = repr(result)

    assert set(result.__dataclass_fields__) == {
        "schema",
        "status",
        "reason",
        "launchd_wake_observed",
        "launchd_cleanup_confirmed",
        "seatbelt_available",
        "browser_runtime_available",
        "probe_identity_digest",
    }
    for forbidden in ("path", "task", "credential", "stdout", "stderr", "traceback"):
        assert forbidden not in rendered.casefold()


@pytest.mark.parametrize(
    "mutation",
    [
        {"status": "qualified", "reason": "seatbelt_unavailable"},
        {"status": "not_qualified", "reason": "qualified"},
        {"reason": "raw_exception"},
        {"probe_identity_digest": "not-a-digest"},
    ],
)
def test_preflight_rejects_open_or_inconsistent_results(
    mutation: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        replace(_preflight(), **mutation)


def test_launchd_probe_uses_the_standard_user_launch_agents_root(
    tmp_path,
    monkeypatch,
) -> None:
    launch_agents = tmp_path / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True)
    observed: list[object] = []

    class _Configuration:
        policy_digest = "8" * 64

        def __init__(self, **values: object) -> None:
            observed.append(values["launch_agents_root"])

    class _Adapter:
        def __init__(self, configuration: _Configuration) -> None:
            self.configuration = configuration

        def install(self, _policy_digest: str):  # noqa: ANN202
            return type("Install", (), {"outcome": runner.WakeInstallOutcome.FAILED})()

    monkeypatch.setattr(runner, "standard_user_launch_agents_root", lambda: launch_agents)
    monkeypatch.setattr(runner, "LaunchdConfigurationV1", _Configuration)
    monkeypatch.setattr(runner, "LaunchdWakeAdapter", _Adapter)

    wake, cleanup, reason = runner._launchd_wake_probe()

    assert (wake, cleanup, reason) == (
        False,
        True,
        "launchd_bootstrap_unavailable",
    )
    assert observed == [launch_agents]


def test_launchd_probe_reports_an_unavailable_standard_root_without_leaking_test_state(
    tmp_path,
    monkeypatch,
) -> None:
    probe_root = tmp_path / "probe"
    missing_launch_agents = tmp_path / "missing" / "LaunchAgents"
    monkeypatch.setattr(
        runner.tempfile,
        "mkdtemp",
        lambda **_values: str(probe_root.mkdir(mode=0o700) or probe_root),
    )
    monkeypatch.setattr(
        runner,
        "standard_user_launch_agents_root",
        lambda: missing_launch_agents,
    )

    assert runner._launchd_wake_probe() == (
        False,
        True,
        "launchd_bootstrap_unavailable",
    )
    assert not probe_root.exists()


def test_preflight_does_not_touch_launchd_when_seatbelt_is_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(runner.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(runner, "_launchd_domain_available", lambda: True)
    monkeypatch.setattr(runner, "_seatbelt_available", lambda: False)
    monkeypatch.setattr(runner, "_browser_runtime_available", lambda: True)
    monkeypatch.setattr(
        runner,
        "_launchd_wake_probe",
        lambda: (_ for _ in ()).throw(AssertionError("launchd must stay untouched")),
    )

    result = runner.run_preflight()

    assert result.status == "not_qualified"
    assert result.reason == "seatbelt_unavailable"
    assert result.launchd_wake_observed is False
    assert result.launchd_cleanup_confirmed is True


@pytest.mark.parametrize(
    "probe",
    [runner._launchd_domain_available, runner._seatbelt_available],
)
def test_host_binary_probe_failure_is_closed_not_unhandled(
    probe,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            FileNotFoundError("host binary unavailable")
        ),
    )

    assert probe() is False


def test_installed_provider_has_one_goal_one_confined_call_and_closed_terminal() -> None:
    provider = host_fixture._U2BProvider()
    empty = ContextPack(
        system="policy",
        messages=(),
        tools=(),
        budget=BudgetReport(1_000, 10, 100),
    )

    draft = provider.generate(empty)
    command = provider.generate(empty)
    terminal = provider.generate(
        ContextPack(
            system="policy",
            messages=(
                ModelMessage(
                    role="user",
                    content=(
                        {
                            "type": "trusted_goal",
                            "goal_id": "goal:u2b",
                            "goal_revision": 1,
                        },
                    ),
                ),
            ),
            tools=(),
            budget=BudgetReport(1_000, 10, 100),
        )
    )

    assert draft.control is not None
    assert command.blocks[0].name == "sandbox_exec"
    assert command.blocks[0].arguments == {
        "executable": "/usr/bin/touch",
        "argv": ["u2b-effect-marker"],
        "cwd": ".",
        "mode": "workspace-write",
        "network": "off",
    }
    assert terminal.control is not None
    assert terminal.control.goal_id == "goal:u2b"
    assert terminal.control.goal_revision == 1


def test_installed_entrypoint_renders_only_a_closed_failure_code(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        host_fixture,
        "build_u2b_host",
        lambda _root: (_ for _ in ()).throw(
            host_fixture.U2BHostUnavailableError("private-path-do-not-render")
        ),
    )
    monkeypatch.setattr(host_fixture.sys, "argv", ["first-agent-schedule", "reconcile"])
    monkeypatch.setattr(host_fixture, "__file__", "/tmp/u2b/bin/first-agent-schedule")

    assert host_fixture.main() == 2
    assert capsys.readouterr().out.strip() == '{"code":"needs_019_config"}'


def test_installed_browser_fixture_loads_under_its_bound_module_identity(tmp_path) -> None:
    paths = host_fixture.U2BHostPathsV1.from_root(tmp_path)
    fixture = paths.root / "host" / "browser_e3_fixture.py"
    fixture.parent.mkdir(mode=0o700)
    fixture.write_text(
        "from __future__ import annotations\n"
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class FixtureResolver:\n"
        "    marker: int = 1\n"
        "@dataclass\n"
        "class FixturePlaywrightFactory:\n"
        "    port: int\n",
        encoding="utf-8",
    )
    (paths.root / "browser-fixture.json").write_text(
        json.dumps(
            {
                "schema": "my-first-agent/macos-u2b-browser-fixture/v1",
                "port": 443,
            }
        ),
        encoding="utf-8",
    )

    resolver, factory = host_fixture._browser_fixture_ports(paths)

    assert resolver.marker == 1
    assert factory.port == 443


def test_u2b_receipt_schema_requires_every_closed_host_claim() -> None:
    receipt = _u2b_receipt()

    assert runner.validate_u2b_receipt(receipt) == []
    assert all(receipt["journey"].values())
    assert receipt["counters"]["real_wakes"] == 3

    missing = dict(receipt)
    missing["journey"] = dict(receipt["journey"])
    missing["journey"].pop("sandbox_receipt_observed")
    false_claim = dict(receipt)
    false_claim["journey"] = dict(receipt["journey"])
    false_claim["journey"]["duplicate_zero_effects"] = False

    assert runner.validate_u2b_receipt(missing)
    assert runner.validate_u2b_receipt(false_claim)


def test_u2b_run_stops_before_receipt_when_host_is_not_qualified(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    output = tmp_path / "receipt.json"
    unavailable = replace(
        _preflight(),
        status="not_qualified",
        reason="seatbelt_unavailable",
        seatbelt_available=False,
    )
    monkeypatch.setattr(runner, "run_preflight", lambda: unavailable)

    exit_code = runner.main(
        [
            "--run",
            "--materialized-root",
            str(tmp_path),
            "--seal",
            str(tmp_path / "seal.json"),
            "--verifier",
            str(tmp_path / "verifier.py"),
            "--wheel",
            str(tmp_path / "wheel.whl"),
            "--review",
            str(tmp_path / "review.md"),
            "--output",
            str(output),
            "--source-full-count",
            "100",
            "--materialized-full-count",
            "100",
        ]
    )

    rendered = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert rendered["status"] == "not_qualified"
    assert rendered["reason"] == "seatbelt_unavailable"
    assert not output.exists()


def test_u2b_installs_two_fixed_executables_and_a_closed_invalid_surface(
    tmp_path,
) -> None:
    paths = runner._prepare_installed_host(
        tmp_path,
        materialized_root=ROOT,
        fixture_port=443,
    )

    for executable in (paths.schedule_executable, paths.child_executable):
        assert stat.S_IMODE(executable.stat().st_mode) == 0o700
        assert executable.read_bytes().startswith(
            f"#!{runner.sys.executable} -I\n".encode()
        )
    completed = subprocess.run(
        (str(paths.schedule_executable), "not-reconcile"),
        cwd=tmp_path,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        check=False,
        timeout=10,
    )

    assert completed.returncode == 64
    assert completed.stdout.strip() == '{"code":"invalid_installed_invocation"}'
    assert completed.stderr == ""
