from __future__ import annotations

import os
import plistlib
import subprocess
from types import SimpleNamespace

import pytest

from agent.automation.wake import (
    WakeReadbackOutcome,
    WakeRemoveOutcome,
)
from agent.automation_hosts.macos_profile import (
    BackgroundSeatbeltPolicyV1,
    compile_background_seatbelt_profile,
)
from agent.sandbox.contracts import (
    SandboxBackendIdentityV1,
    SandboxQualificationV1,
)
from scripts import run_019_core_e3 as core_runner
from scripts import run_019_macos_e3 as runner


def _receipt() -> dict[str, object]:
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
        "mutation_gate": {
            "exit_code": 0,
            "pass_count": runner.U2B_MUTATION_NODE_COUNT,
            "node_count": runner.U2B_MUTATION_NODE_COUNT,
        },
        "source_full_gate": {"exit_code": 0, "pass_count": 100, "node_count": 100},
        "materialized_full_gate": {
            "exit_code": 0,
            "pass_count": 100,
            "node_count": 100,
        },
    }


def _correct_plist(executable) -> bytes:  # noqa: ANN001
    return plistlib.dumps(
        {
            "Label": runner._u2b_label(executable.parents[1]),
            "ProgramArguments": [str(executable), "reconcile"],
            "RunAtLoad": False,
            "StartInterval": runner.u2b_host._WAKE_INTERVAL_SECONDS,
        },
        sort_keys=True,
    )


def test_receipt_rejects_a_false_claim() -> None:
    receipt = _receipt()
    receipt["journey"] = dict(receipt["journey"])
    receipt["journey"]["seatbelt_nonvacuous"] = False

    assert runner.validate_u2b_receipt(receipt)


def test_receipt_rejects_a_counter_drift() -> None:
    receipt = _receipt()
    receipt["counters"] = dict(receipt["counters"])
    receipt["counters"]["real_wakes"] = 2

    assert runner.validate_u2b_receipt(receipt)


def test_receipt_rejects_an_unknown_key() -> None:
    receipt = _receipt()
    receipt["raw_diagnostic"] = "not allowed"

    assert runner.validate_u2b_receipt(receipt)


def test_plist_oracle_rejects_a_task_argument(tmp_path) -> None:
    executable = tmp_path / "bin" / "first-agent-schedule"
    payload = plistlib.loads(_correct_plist(executable))
    payload["ProgramArguments"].append("private task")

    assert not runner._plist_allowlist_exact(plistlib.dumps(payload), executable)


def test_plist_oracle_rejects_a_shell_wrapper(tmp_path) -> None:
    executable = tmp_path / "bin" / "first-agent-schedule"
    payload = plistlib.loads(_correct_plist(executable))
    payload["ProgramArguments"] = ["/bin/sh", "-c", str(executable)]

    assert not runner._plist_allowlist_exact(plistlib.dumps(payload), executable)


def test_kickstart_budget_exceeds_launchd_default_throttle(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def fake_run(argv, **kwargs):  # noqa: ANN001
        observed["argv"] = argv
        observed["timeout"] = kwargs["timeout"]
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    runner._kickstart("com.my-first-agent.schedule.e3.0123456789ab")

    assert observed["timeout"] > 10


def test_u2b_uses_the_portable_materialized_tree_identity(tmp_path) -> None:
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / ".ruff_cache").mkdir()
    (tmp_path / ".ruff_cache" / "ignored").write_text("cache\n", encoding="utf-8")

    assert runner._sha256_tree(tmp_path) == core_runner._sha256_tree(tmp_path)


def test_private_result_rejects_an_open_code() -> None:
    with pytest.raises(ValueError, match="not closed"):
        runner._validate_private_result(
            {
                "schema": runner._U2B_RESULT_SCHEMA,
                "code": "raw_exception",
                "automation_id": None,
                "occurrence_id": None,
                "status": None,
                "reason": None,
            }
        )


@pytest.mark.parametrize(
    "mutation",
    [
        {
            "code": "not_due",
            "automation_id": "automation:unexpected",
            "occurrence_id": None,
            "status": None,
            "reason": None,
        },
        {
            "code": "completed",
            "automation_id": "automation:one",
            "occurrence_id": "occurrence:one",
            "status": "misfire_skipped",
            "reason": None,
        },
        {
            "code": "misfire_skipped",
            "automation_id": "automation:one",
            "occurrence_id": "occurrence:one",
            "status": "misfire_skipped",
            "reason": "private-detail",
        },
    ],
)
def test_private_result_rejects_inconsistent_closed_fields(
    mutation: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="inconsistent"):
        runner._validate_private_result(
            {
                "schema": runner._U2B_RESULT_SCHEMA,
                **mutation,
            }
        )


def test_private_result_discovery_rejects_a_symlink(tmp_path) -> None:
    target = tmp_path / "outside.json"
    target.write_text("{}", encoding="utf-8")
    results = tmp_path / "results"
    results.mkdir(mode=0o700)
    (results / "result.json").symlink_to(target)

    with pytest.raises(ValueError, match="regular owner-only"):
        runner._result_paths(results)


def test_closed_writer_does_not_replace_a_dangling_symlink(tmp_path) -> None:
    destination = tmp_path / "result.json"
    destination.symlink_to(tmp_path / "missing.json")

    with pytest.raises(FileExistsError):
        runner._write_new_file(destination, b"closed\n")

    assert os.path.lexists(destination)
    assert destination.is_symlink()


def test_u2b_host_binds_the_strict_background_profile_compiler(
    tmp_path,
    monkeypatch,
) -> None:
    paths = runner.u2b_host.U2BHostPathsV1.from_root(tmp_path)
    paths.child_executable.parent.mkdir(mode=0o700)
    for executable in (paths.child_executable, paths.schedule_executable):
        executable.write_bytes(b"#!/bin/sh\nexit 0\n")
        executable.chmod(0o700)
    runner.u2b_host.initialize_u2b_repository(tmp_path)
    captured: list[object] = []
    qualification = SandboxQualificationV1(
        available=True,
        reason_code="qualified",
        backend_identity=SandboxBackendIdentityV1(
            executable_path="/usr/bin/sandbox-exec",
            platform_system="Darwin",
            platform_release="test-release",
            functional_probe_digest="1" * 64,
            probe_profile_digest="2" * 64,
        ),
    )

    class _Confiner:
        def qualify(self):  # noqa: ANN201
            return qualification

    def build_confiner(  # noqa: ANN001, ANN202
        *, profile_compiler=None, legacy_policy_type=None
    ):
        captured.append((profile_compiler, legacy_policy_type))
        return _Confiner()

    monkeypatch.setattr(runner.u2b_host, "SeatbeltConfiner", build_confiner)

    runner.u2b_host.build_u2b_host(tmp_path)

    assert captured == [
        (compile_background_seatbelt_profile, BackgroundSeatbeltPolicyV1)
    ]


def test_failed_u2b_with_confirmed_process_cleanup_removes_test_wake() -> None:
    calls: list[str] = []

    class _Management:
        def wake_disable(self):  # noqa: ANN201
            calls.append("management")
            return SimpleNamespace(code="wake_disable_refused_active")

    class _Wake:
        configured_policy_digest = "a" * 64

        def remove(self, _policy_digest):  # noqa: ANN001, ANN201
            calls.append("adapter")
            return SimpleNamespace(outcome=WakeRemoveOutcome.REMOVED)

        def readback(self, _policy_digest):  # noqa: ANN001, ANN201
            return SimpleNamespace(outcome=WakeReadbackOutcome.ABSENT)

    host = SimpleNamespace(
        core=SimpleNamespace(management=_Management()),
        wake_adapter=_Wake(),
    )

    assert runner._cleanup_u2b_wake(host, process_cleanup_confirmed=True)
    assert calls == ["management", "adapter"]


def test_failed_u2b_does_not_force_wake_removal_while_process_is_unconfirmed() -> None:
    calls: list[str] = []

    class _Management:
        def wake_disable(self):  # noqa: ANN201
            calls.append("management")
            return SimpleNamespace(code="wake_disable_refused_active")

    class _Wake:
        configured_policy_digest = "a" * 64

        def remove(self, _policy_digest):  # noqa: ANN001, ANN201
            calls.append("adapter")
            return SimpleNamespace(outcome=WakeRemoveOutcome.REMOVED)

    host = SimpleNamespace(
        core=SimpleNamespace(management=_Management()),
        wake_adapter=_Wake(),
    )

    assert not runner._cleanup_u2b_wake(host, process_cleanup_confirmed=False)
    assert calls == ["management"]


def test_installed_host_imports_only_from_the_materialized_bundle(tmp_path) -> None:
    materialized = tmp_path / "materialized"
    (materialized / "agent").mkdir(parents=True)
    (materialized / "agent" / "__init__.py").write_text(
        'BUNDLE_MARKER = "materialized-agent"\n',
        encoding="utf-8",
    )
    (materialized / "scripts").mkdir()
    (materialized / "scripts" / "_019_macos_u2b_host.py").write_text(
        "from __future__ import annotations\n"
        "import os\n"
        "import sys\n"
        "from agent import BUNDLE_MARKER\n"
        "assert sys.flags.isolated == 1\n"
        "assert set(os.environ) == {'PATH', 'PYTHONDONTWRITEBYTECODE'}\n"
        "print(BUNDLE_MARKER)\n",
        encoding="utf-8",
    )
    (materialized / "scripts" / "browser_e3_fixture.py").write_text(
        "# bounded fixture\n",
        encoding="utf-8",
    )
    installed_root = tmp_path / "installed"

    paths = runner._prepare_installed_host(
        installed_root,
        materialized_root=materialized,
        fixture_port=8443,
    )
    result = subprocess.run(
        [os.fspath(paths.schedule_executable)],
        cwd="/",
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "U2B_AMBIENT_SENTINEL": "must-not-cross-host-boundary",
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == b"materialized-agent\n"
    assert result.stderr == b""


def test_checkpoint_metrics_require_a_sandbox_receipt() -> None:
    metrics = {
        "checkpoint_count": 1,
        "tool_calls": 1,
        "sandbox_receipts": 0,
        "blocked_terminal": True,
    }

    assert not runner._checkpoint_metrics_valid(metrics)


def test_process_cleanup_rejects_a_live_group(monkeypatch) -> None:
    monkeypatch.setattr(runner, "group_alive", lambda _pgid: True)

    assert not runner._processes_are_gone(
        (
            {
                "leader_pid": 101,
                "process_group_id": 101,
            },
        )
    )


@pytest.mark.parametrize(
    "observation",
    [
        {
            "schema": runner._U2B_PROCESS_SCHEMA,
            "leader_pid": 101,
            "process_group_id": 102,
            "descendant_pid": None,
            "descendant_process_group_id": None,
        },
        {
            "schema": runner._U2B_PROCESS_SCHEMA,
            "leader_pid": 101,
            "process_group_id": 101,
            "descendant_pid": 103,
            "descendant_process_group_id": None,
        },
    ],
)
def test_process_observation_requires_an_exact_group_binding(
    tmp_path,
    observation: dict[str, object],
) -> None:
    paths = runner.u2b_host.U2BHostPathsV1.from_root(tmp_path)
    paths.process_observations_root.mkdir(mode=0o700)
    payload = runner._json(observation).encode()
    runner._write_new_file(paths.process_observations_root / "result.json", payload)

    with pytest.raises(ValueError, match="process identity"):
        runner._process_observations(paths)


def test_browser_proof_requires_storage_isolation() -> None:
    storage = {"storage_not_reused_after_close": False}
    guard = {"production_guard_rejects_loopback": True}

    assert not runner._browser_proof_valid(storage, guard, observations=2)


def test_duplicate_delta_requires_every_zero() -> None:
    assert not runner._duplicate_delta_valid(
        {"provider": 0, "tools": 0, "effects": 0, "processes": 1}
    )


def test_misfire_requires_no_composition_delta() -> None:
    assert not runner._misfire_delta_valid(
        {"provider": 0, "tools": 0, "effects": 1, "processes": 0}
    )


def test_secrecy_scan_rejects_every_private_sentinel() -> None:
    for sentinel in runner._PRIVATE_TEXT_SENTINELS:
        assert not runner._secret_free(f"prefix {sentinel} suffix".encode())
