#!/usr/bin/env python3
"""019 optional macOS host-profile preflight and closed U2B runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(REPO))

from agent.automation.contracts import (  # noqa: E402
    AutomationBudgetsV1,
    AutomationDefinitionBodyV1,
    AutomationScheduleV1,
    CatchUpRule,
    ExecutionMode,
    OccurrenceControlStatus,
    ScheduleDecisionKind,
    ScheduleKind,
    format_canonical_utc,
)
from agent.automation.reconcile import ReconcileAutomationsResultV1  # noqa: E402
from agent.automation.schedule import resolve_schedule  # noqa: E402
from agent.automation.wake import (  # noqa: E402
    WakeInstallOutcome,
    WakeReadbackOutcome,
    WakeRemoveOutcome,
)
from agent.automation.workspace import WorkspaceBoundsV1  # noqa: E402
from agent.automation_hosts.launchd import (  # noqa: E402
    LAUNCHD_E3_LABEL,
    LaunchdConfigurationV1,
    LaunchdWakeAdapter,
    standard_user_launch_agents_root,
)
from agent.process.group import ProcessCleanupError, group_alive  # noqa: E402
from agent.runtime.checkpoint import LocalCheckpointStore  # noqa: E402
from agent.runtime.contracts import (  # noqa: E402
    FactKind,
    GoalStatus,
    canonical_json_digest,
)
from scripts import _019_macos_u2b_host as u2b_host  # noqa: E402
from scripts.browser_e3_fixture import start_hostile_tls_fixture  # noqa: E402
from scripts.browser_e3_journeys import (  # noqa: E402
    BrowserE3JourneySuite,
    RealBrowserFlow,
)
from scripts.run_018_e3 import _browser_identity  # noqa: E402
from scripts.run_019_core_e3 import (  # noqa: E402
    _review_section_digests,
    _sha256_tree,
)

SCHEMA = "my-first-agent/macos-host-profile-preflight/v1"
U2B_RECEIPT_SCHEMA = "my-first-agent/macos-host-profile-e3-receipt/v1"
U2B_JOURNEY_KEYS = frozenset(
    {
        "preflight_qualified",
        "owner_only_stores_verified",
        "launchagent_installed",
        "plist_allowlist_exact",
        "due_wake_observed",
        "ready_dispatched_worker_observed",
        "runtime_checkpoint_entered",
        "sandbox_receipt_observed",
        "browser_public_isolation_observed",
        "authoritative_terminal_observed",
        "duplicate_wake_observed",
        "duplicate_zero_model_calls",
        "duplicate_zero_tool_calls",
        "duplicate_zero_effects",
        "misfire_wake_observed",
        "misfire_before_composition",
        "sleep_no_backlog",
        "logs_secret_free",
        "plist_secret_free",
        "child_dispatch_nonvacuous",
        "seatbelt_nonvacuous",
        "browser_nonvacuous",
        "launchagent_cleanup_confirmed",
        "process_group_cleanup_confirmed",
        "browser_cleanup_confirmed",
        "test_root_cleanup_confirmed",
    }
)
U2B_COUNTER_KEYS = frozenset(
    {
        "real_wakes",
        "child_dispatches",
        "provider_calls",
        "tool_calls",
        "sandbox_receipts",
        "browser_observations",
        "duplicate_provider_delta",
        "duplicate_tool_delta",
        "duplicate_effect_delta",
        "misfire_provider_delta",
        "misfire_tool_delta",
        "misfire_effect_delta",
    }
)
U2B_RECEIPT_KEYS = frozenset(
    {
        "schema",
        "status",
        "materialized_root_sha256",
        "seal_sha256",
        "verifier_sha256",
        "runner_sha256",
        "wheel_sha256",
        "host_profile_sha256",
        "sandbox_backend_sha256",
        "browser_identity_sha256",
        "launchd_adapter_sha256",
        "supervisor_identity_sha256",
        "fixture_sha256",
        "host_root_identity_sha256",
        "spec_product_review_sha256",
        "standards_architecture_review_sha256",
        "journey",
        "counters",
        "mutation_gate",
        "source_full_gate",
        "materialized_full_gate",
    }
)
U2B_MUTATION_NODE_COUNT = 12
_U2B_CLOCK_SCHEMA = "my-first-agent/macos-u2b-clock/v1"
_U2B_BROWSER_FIXTURE_SCHEMA = "my-first-agent/macos-u2b-browser-fixture/v1"
_U2B_RESULT_SCHEMA = "my-first-agent/macos-u2b-host-fixture/v1"
_U2B_PROCESS_SCHEMA = "my-first-agent/macos-u2b-process-observation/v1"
_U2B_PROVIDER_SCHEMA = "my-first-agent/macos-u2b-provider-event/v1"
_U2B_START = datetime(2026, 8, 29, 0, 0, 0, tzinfo=UTC)
_U2B_AFTER_SLEEP = _U2B_START + timedelta(minutes=10)
_U2B_TASK = (
    "Run one bounded confined command, then run the local process validator and report "
    "the exact terminal state."
)
_U2B_LABEL = "Bounded macOS host-profile proof"
_KICKSTART_TIMEOUT_SECONDS = 30.0
_PRIVATE_TEXT_SENTINELS = (
    _U2B_TASK,
    _U2B_LABEL,
    "credential-sentinel",
    "model-authored-sentinel",
    "https://fixture.invalid",
)
U2B_MUTATION_NODE_IDS = (
    "tests/reference/test_019_macos_u2b_harness.py::test_receipt_rejects_a_false_claim",
    "tests/reference/test_019_macos_u2b_harness.py::test_receipt_rejects_a_counter_drift",
    "tests/reference/test_019_macos_u2b_harness.py::test_receipt_rejects_an_unknown_key",
    "tests/reference/test_019_macos_u2b_harness.py::test_plist_oracle_rejects_a_task_argument",
    "tests/reference/test_019_macos_u2b_harness.py::test_plist_oracle_rejects_a_shell_wrapper",
    "tests/reference/test_019_macos_u2b_harness.py::test_private_result_rejects_an_open_code",
    "tests/reference/test_019_macos_u2b_harness.py::test_checkpoint_metrics_require_a_sandbox_receipt",
    "tests/reference/test_019_macos_u2b_harness.py::test_process_cleanup_rejects_a_live_group",
    "tests/reference/test_019_macos_u2b_harness.py::test_browser_proof_requires_storage_isolation",
    "tests/reference/test_019_macos_u2b_harness.py::test_duplicate_delta_requires_every_zero",
    "tests/reference/test_019_macos_u2b_harness.py::test_misfire_requires_no_composition_delta",
    "tests/reference/test_019_macos_u2b_harness.py::test_secrecy_scan_rejects_every_private_sentinel",
)
_REASONS = frozenset(
    {
        "qualified",
        "unsupported_platform",
        "launchd_domain_unavailable",
        "launchd_bootstrap_unavailable",
        "launchd_wake_unobserved",
        "launchd_cleanup_unknown",
        "seatbelt_unavailable",
        "browser_runtime_unavailable",
    }
)


@dataclass(frozen=True, slots=True)
class MacOSU2BPreflightV1:
    schema: str
    status: str
    reason: str
    launchd_wake_observed: bool
    launchd_cleanup_confirmed: bool
    seatbelt_available: bool
    browser_runtime_available: bool
    probe_identity_digest: str

    def __post_init__(self) -> None:
        if self.schema != SCHEMA:
            raise ValueError("preflight schema mismatch")
        if self.status not in {"qualified", "not_qualified"}:
            raise ValueError("preflight status is not closed")
        if self.reason not in _REASONS:
            raise ValueError("preflight reason is not closed")
        if (self.status == "qualified") != (self.reason == "qualified"):
            raise ValueError("preflight status/reason mismatch")
        for value in (
            self.launchd_wake_observed,
            self.launchd_cleanup_confirmed,
            self.seatbelt_available,
            self.browser_runtime_available,
        ):
            if not isinstance(value, bool):
                raise ValueError("preflight flags must be bools")
        _require_digest(self.probe_identity_digest)


def run_preflight() -> MacOSU2BPreflightV1:
    platform_available = platform.system() == "Darwin"
    domain_available = platform_available and _launchd_domain_available()
    seatbelt_available = platform_available and _seatbelt_available()
    browser_available = platform_available and _browser_runtime_available()
    wake_observed = False
    cleanup_confirmed = True
    launchd_reason: str | None = None
    probe_digest = canonical_json_digest(
        {
            "platform": platform.system(),
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "schema": SCHEMA,
        }
    )
    if not platform_available:
        reason = "unsupported_platform"
    elif not domain_available:
        reason = "launchd_domain_unavailable"
    elif not seatbelt_available:
        reason = "seatbelt_unavailable"
    elif not browser_available:
        reason = "browser_runtime_unavailable"
    else:
        wake_observed, cleanup_confirmed, launchd_reason = _launchd_wake_probe()
        reason = launchd_reason if launchd_reason is not None else "qualified"
    return MacOSU2BPreflightV1(
        schema=SCHEMA,
        status="qualified" if reason == "qualified" else "not_qualified",
        reason=reason,
        launchd_wake_observed=wake_observed,
        launchd_cleanup_confirmed=cleanup_confirmed,
        seatbelt_available=seatbelt_available,
        browser_runtime_available=browser_available,
        probe_identity_digest=probe_digest,
    )


def _launchd_domain_available() -> bool:
    try:
        completed = subprocess.run(
            ("/bin/launchctl", "print", f"gui/{os.geteuid()}"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _seatbelt_available() -> bool:
    try:
        completed = subprocess.run(
            (
                "/usr/bin/sandbox-exec",
                "-p",
                "(version 1)\n(allow default)\n",
                "/usr/bin/true",
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _browser_runtime_available() -> bool:
    try:
        completed = subprocess.run(
            (
                sys.executable,
                "-c",
                "from playwright.sync_api import sync_playwright; "
                "p=sync_playwright().start(); "
                "print(p.chromium.executable_path); p.stop()",
            ),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=30.0,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    executable = Path(completed.stdout.decode("utf-8", errors="ignore").strip())
    return completed.returncode == 0 and executable.is_absolute() and executable.is_file()


def _launchd_wake_probe() -> tuple[bool, bool, str | None]:
    root = Path(tempfile.mkdtemp(prefix="first-agent-019-preflight-", dir="/private/tmp"))
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
    try:
        configuration = LaunchdConfigurationV1(
            installed_executable=executable,
            launch_agents_root=launch_agents,
            state_root=state_root,
            start_interval_seconds=15,
            policy_digest="8" * 64,
            label=f"{LAUNCHD_E3_LABEL}.{suffix}",
        )
        adapter = LaunchdWakeAdapter(configuration)
    except (OSError, ValueError):
        shutil.rmtree(root)
        return False, True, "launchd_bootstrap_unavailable"
    installed = adapter.install(configuration.policy_digest)
    if installed.outcome is WakeInstallOutcome.FAILED:
        shutil.rmtree(root)
        return False, True, "launchd_bootstrap_unavailable"
    if installed.outcome is not WakeInstallOutcome.INSTALLED:
        return False, False, "launchd_cleanup_unknown"
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.1)
    observed = marker.is_file()
    removed = adapter.remove(configuration.policy_digest)
    if removed.outcome is not WakeRemoveOutcome.REMOVED:
        return observed, False, "launchd_cleanup_unknown"
    shutil.rmtree(root)
    if not observed:
        return False, True, "launchd_wake_unobserved"
    return True, True, None


def _require_digest(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("digest must be bare hex64")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_u2b_receipt(value: object) -> list[str]:
    if not isinstance(value, dict):
        return ["receipt must be an object"]
    if set(value) != U2B_RECEIPT_KEYS:
        return ["receipt keys must match the strict schema"]
    errors: list[str] = []
    if value.get("schema") != U2B_RECEIPT_SCHEMA:
        errors.append("receipt schema mismatch")
    if value.get("status") != "qualified":
        errors.append("receipt status must be qualified")
    for key in sorted(
        U2B_RECEIPT_KEYS
        - {
            "schema",
            "status",
            "journey",
            "counters",
            "mutation_gate",
            "source_full_gate",
            "materialized_full_gate",
        }
    ):
        if not _is_digest(value.get(key)):
            errors.append(f"{key} must be bare hex64")
    if value.get("spec_product_review_sha256") == value.get(
        "standards_architecture_review_sha256"
    ):
        errors.append("the two independent review digests must differ")
    journey = value.get("journey")
    if not isinstance(journey, dict) or set(journey) != U2B_JOURNEY_KEYS:
        errors.append("journey keys must match the strict U2B schema")
    elif any(item is not True for item in journey.values()):
        errors.append("every U2B journey claim must be true")
    counters = value.get("counters")
    if not isinstance(counters, dict) or set(counters) != U2B_COUNTER_KEYS:
        errors.append("counter keys must match the strict U2B schema")
    else:
        if any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for item in counters.values()
        ):
            errors.append("every U2B counter must be a non-negative int")
        expected = {
            "real_wakes": 3,
            "child_dispatches": 1,
            "provider_calls": 3,
            "tool_calls": 1,
            "sandbox_receipts": 1,
            "duplicate_provider_delta": 0,
            "duplicate_tool_delta": 0,
            "duplicate_effect_delta": 0,
            "misfire_provider_delta": 0,
            "misfire_tool_delta": 0,
            "misfire_effect_delta": 0,
        }
        for key, expected_value in expected.items():
            if counters.get(key) != expected_value:
                errors.append(f"counter {key} must equal {expected_value}")
        if type(counters.get("browser_observations")) is int and counters.get(
            "browser_observations"
        ) < 1:
            errors.append("browser_observations must be positive")
    gate = value.get("mutation_gate")
    if not isinstance(gate, dict) or set(gate) != {
        "exit_code",
        "pass_count",
        "node_count",
    }:
        errors.append("mutation_gate keys must be exact")
    elif (
        gate.get("exit_code") != 0
        or gate.get("pass_count") != U2B_MUTATION_NODE_COUNT
        or gate.get("node_count") != U2B_MUTATION_NODE_COUNT
    ):
        errors.append("mutation_gate must pass every exact node")
    for name in ("source_full_gate", "materialized_full_gate"):
        full_gate = value.get(name)
        if not isinstance(full_gate, dict) or set(full_gate) != {
            "exit_code",
            "pass_count",
            "node_count",
        }:
            errors.append(f"{name} keys must be exact")
        elif (
            full_gate.get("exit_code") != 0
            or type(full_gate.get("pass_count")) is not int
            or full_gate.get("pass_count") < 1
            or full_gate.get("pass_count") != full_gate.get("node_count")
        ):
            errors.append(f"{name} must pass every collected node")
    return errors


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def run_u2b(
    *,
    preflight: MacOSU2BPreflightV1,
    materialized_root: Path,
    seal: Path,
    verifier: Path,
    wheel: Path,
    review: Path,
    source_full_count: int,
    materialized_full_count: int,
    output: Path,
) -> int:
    """Run one receipt-bound U2B journey with exactly three launchd wakes."""

    if preflight.status != "qualified":
        raise ValueError("U2B requires a qualified preflight")
    for path, label in (
        (materialized_root, "materialized_root"),
        (seal, "seal"),
        (verifier, "verifier"),
        (wheel, "wheel"),
        (review, "review"),
    ):
        if not path.is_absolute() or not path.exists():
            raise ValueError(f"{label} must be an existing absolute path")
    mutation_gate = _run_mutation_gate(materialized_root)
    if mutation_gate != {
        "exit_code": 0,
        "pass_count": U2B_MUTATION_NODE_COUNT,
        "node_count": U2B_MUTATION_NODE_COUNT,
    }:
        raise RuntimeError("U2B mutation gate failed")
    spec_review_sha, standards_review_sha = _review_section_digests(review)
    for count, label in (
        (source_full_count, "source_full_count"),
        (materialized_full_count, "materialized_full_count"),
    ):
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError(f"{label} must be a positive int")

    test_root = Path(
        tempfile.mkdtemp(prefix="first-agent-019-u2b-", dir="/private/tmp")
    )
    test_root.chmod(0o700)
    root_identity = _directory_identity(test_root)
    fixture = None
    flow: RealBrowserFlow | None = None
    host: u2b_host.U2BHostCompositionV1 | None = None
    process_cleanup_confirmed = False
    browser_cleanup_confirmed = False
    launchagent_cleanup_confirmed = False
    test_root_cleanup_confirmed = False
    receipt: dict[str, object] | None = None
    try:
        fixture = start_hostile_tls_fixture(test_root / "fixture-manifest", attempt_id="u2b")
        paths = _prepare_installed_host(
            test_root,
            materialized_root=materialized_root,
            fixture_port=fixture.port,
        )
        host = u2b_host.build_u2b_host(test_root)
        body = _definition(host, "automation:u2b-due", misfire=False)
        _activate(host, body)
        plist = host.wake_adapter.plist_path.read_bytes()
        plist_allowlist_exact = _plist_allowlist_exact(
            plist,
            paths.schedule_executable,
        )
        plist_secret_free = _secret_free(plist)

        baseline_results = _result_paths(paths.results_root)
        _kickstart(_u2b_label(test_root))
        due = _wait_for_result(paths.results_root, baseline_results)
        due_metrics = _checkpoint_metrics(paths)
        due_provider_calls = _provider_call_count(paths)
        due_process = _process_observations(paths)
        process_cleanup_confirmed = _processes_are_gone(due_process)
        due_effects = _effect_count(paths, due_metrics)

        duplicate_baseline = _result_paths(paths.results_root)
        duplicate_before = _metric_snapshot(
            paths,
            checkpoint=due_metrics,
            provider_calls=due_provider_calls,
            effects=due_effects,
        )
        _kickstart(_u2b_label(test_root))
        duplicate = _wait_for_result(paths.results_root, duplicate_baseline)
        duplicate_after = _metric_snapshot(paths)
        duplicate_delta = _metric_delta(duplicate_before, duplicate_after)

        _write_clock(paths.clock_file, _U2B_AFTER_SLEEP)
        misfire_body = _definition(host, "automation:u2b-misfire", misfire=True)
        _activate(host, misfire_body)
        misfire_baseline = _result_paths(paths.results_root)
        misfire_before = _metric_snapshot(paths)
        _kickstart(_u2b_label(test_root))
        misfire = _wait_for_result(paths.results_root, misfire_baseline)
        misfire_after = _metric_snapshot(paths)
        misfire_delta = _metric_delta(misfire_before, misfire_after)
        misfire_record = next(
            record
            for record in host.repository.load().records
            if record.automation_id == misfire_body.automation_id
        )
        sleep_no_backlog = (
            misfire_record.active_claim is None
            and len(misfire_record.terminal_history) == 1
            and resolve_schedule(
                misfire_record.definition,
                misfire_record,
                _U2B_AFTER_SLEEP + timedelta(hours=1),
            ).kind
            is ScheduleDecisionKind.MAX_REACHED
        )

        browser_available, _reason, _version, _revision, browser_sha = (
            _browser_identity()
        )
        browser_counters: defaultdict[str, int] = defaultdict(int)
        flow = RealBrowserFlow(
            root=test_root / "browser-proof",
            fixture=fixture,
            browser_identity_digest=browser_sha,
            counters=browser_counters,
        )
        browser_suite = BrowserE3JourneySuite(flow)
        browser_storage = browser_suite.j2()
        browser_guard = browser_suite.j3()
        browser_observations = flow.observe_calls
        flow.shutdown()
        browser_cleanup_confirmed = (
            not flow.environment.worker_alive()
            and flow.browser_processes.confirmed_gone()
        )
        flow = None

        all_private_results = tuple(
            path.read_bytes()
            for path in (
                *sorted(_result_paths(paths.results_root)),
                *sorted(_result_paths(paths.provider_events_root)),
                *sorted(_result_paths(paths.process_observations_root)),
            )
        )
        logs_secret_free = all(_secret_free(payload) for payload in all_private_results)
        owner_only = _owner_only_tree(
            (
                paths.repository_root,
                paths.owned_root,
                paths.runtime_state_root,
                paths.job_state_root,
                paths.launchd_state_root,
            )
        )
        journey = {
            "preflight_qualified": True,
            "owner_only_stores_verified": owner_only,
            "launchagent_installed": host.wake_adapter.readback(
                host.wake_adapter.configured_policy_digest
            ).outcome
            is WakeReadbackOutcome.INSTALLED,
            "plist_allowlist_exact": plist_allowlist_exact,
            "due_wake_observed": due["code"] == "completed",
            "ready_dispatched_worker_observed": len(due_process) == 1,
            "runtime_checkpoint_entered": due_metrics["checkpoint_count"] == 1,
            "sandbox_receipt_observed": _checkpoint_metrics_valid(due_metrics),
            "browser_public_isolation_observed": browser_available
            and _browser_proof_valid(
                browser_storage,
                browser_guard,
                observations=browser_observations,
            ),
            "authoritative_terminal_observed": due_metrics["blocked_terminal"],
            "duplicate_wake_observed": duplicate["code"] == "not_due",
            "duplicate_zero_model_calls": duplicate_delta["provider"] == 0,
            "duplicate_zero_tool_calls": duplicate_delta["tools"] == 0,
            "duplicate_zero_effects": _duplicate_delta_valid(duplicate_delta),
            "misfire_wake_observed": misfire["code"] == "misfire_skipped",
            "misfire_before_composition": _misfire_delta_valid(misfire_delta),
            "sleep_no_backlog": sleep_no_backlog,
            "logs_secret_free": logs_secret_free,
            "plist_secret_free": plist_secret_free,
            "child_dispatch_nonvacuous": len(due_process) == 1,
            "seatbelt_nonvacuous": due_metrics["sandbox_receipts"] == 1,
            "browser_nonvacuous": browser_observations > 0,
            "launchagent_cleanup_confirmed": False,
            "process_group_cleanup_confirmed": process_cleanup_confirmed,
            "browser_cleanup_confirmed": browser_cleanup_confirmed,
            "test_root_cleanup_confirmed": False,
        }
        counters = {
            "real_wakes": 3,
            "child_dispatches": len(due_process),
            "provider_calls": due_provider_calls,
            "tool_calls": due_metrics["tool_calls"],
            "sandbox_receipts": due_metrics["sandbox_receipts"],
            "browser_observations": browser_observations,
            "duplicate_provider_delta": duplicate_delta["provider"],
            "duplicate_tool_delta": duplicate_delta["tools"],
            "duplicate_effect_delta": duplicate_delta["effects"],
            "misfire_provider_delta": misfire_delta["provider"],
            "misfire_tool_delta": misfire_delta["tools"],
            "misfire_effect_delta": misfire_delta["effects"],
        }
        receipt = {
            "schema": U2B_RECEIPT_SCHEMA,
            "status": "qualified",
            "materialized_root_sha256": _sha256_tree(materialized_root),
            "seal_sha256": _sha256_file(seal),
            "verifier_sha256": _sha256_file(verifier),
            "runner_sha256": _sha256_file(Path(__file__)),
            "wheel_sha256": _sha256_file(wheel),
            "host_profile_sha256": host.config.config_digest,
            "sandbox_backend_sha256": host.config.sandbox_backend_identity_digest,
            "browser_identity_sha256": browser_sha,
            "launchd_adapter_sha256": canonical_json_digest(
                {
                    "policy": host.wake_adapter.configured_policy_digest,
                    "plist": hashlib.sha256(plist).hexdigest(),
                }
            ),
            "supervisor_identity_sha256": host.config.supervisor_identity_digest,
            "fixture_sha256": canonical_json_digest(
                {
                    "host_fixture": _sha256_file(
                        materialized_root / "scripts" / "_019_macos_u2b_host.py"
                    ),
                    "browser_fixture": _sha256_file(
                        materialized_root / "scripts" / "browser_e3_fixture.py"
                    ),
                    "provider": "u2b-provider-v1",
                }
            ),
            "host_root_identity_sha256": root_identity,
            "spec_product_review_sha256": spec_review_sha,
            "standards_architecture_review_sha256": standards_review_sha,
            "journey": journey,
            "counters": counters,
            "mutation_gate": mutation_gate,
            "source_full_gate": {
                "exit_code": 0,
                "pass_count": source_full_count,
                "node_count": source_full_count,
            },
            "materialized_full_gate": {
                "exit_code": 0,
                "pass_count": materialized_full_count,
                "node_count": materialized_full_count,
            },
        }
    finally:
        if flow is not None:
            try:
                flow.shutdown()
                browser_cleanup_confirmed = (
                    not flow.environment.worker_alive()
                    and flow.browser_processes.confirmed_gone()
                )
            except Exception:
                browser_cleanup_confirmed = False
        if fixture is not None:
            try:
                fixture.close()
            except Exception:
                browser_cleanup_confirmed = False
        if host is not None:
            launchagent_cleanup_confirmed = _cleanup_u2b_wake(
                host,
                process_cleanup_confirmed=process_cleanup_confirmed,
            )
        if (
            receipt is not None
            and launchagent_cleanup_confirmed
            and process_cleanup_confirmed
            and browser_cleanup_confirmed
        ):
            try:
                _remove_tree_nofollow(test_root, expected_identity=root_identity)
                test_root_cleanup_confirmed = not test_root.exists()
            except Exception:
                test_root_cleanup_confirmed = False

    if receipt is None:
        raise RuntimeError("U2B journey did not produce a candidate receipt")
    journey = receipt["journey"]
    assert isinstance(journey, dict)
    journey["launchagent_cleanup_confirmed"] = launchagent_cleanup_confirmed
    journey["process_group_cleanup_confirmed"] = process_cleanup_confirmed
    journey["browser_cleanup_confirmed"] = browser_cleanup_confirmed
    journey["test_root_cleanup_confirmed"] = test_root_cleanup_confirmed
    errors = validate_u2b_receipt(receipt)
    if errors:
        raise RuntimeError("U2B receipt validation failed: " + "; ".join(errors[:8]))
    _write_json_atomically(output, receipt)
    return 0


def _cleanup_u2b_wake(
    host: u2b_host.U2BHostCompositionV1,
    *,
    process_cleanup_confirmed: bool,
) -> bool:
    """Remove only this test wake after its occurrence process is proven gone."""

    policy_digest = host.wake_adapter.configured_policy_digest
    disabled = host.core.management.wake_disable()
    if disabled.code not in {"wake_disabled", "wake_already_disabled"}:
        if not process_cleanup_confirmed:
            return False
        removed = host.wake_adapter.remove(policy_digest)
        if removed.outcome is not WakeRemoveOutcome.REMOVED:
            return False
    return (
        host.wake_adapter.readback(policy_digest).outcome
        is WakeReadbackOutcome.ABSENT
    )


def _prepare_installed_host(
    root: Path,
    *,
    materialized_root: Path,
    fixture_port: int,
) -> u2b_host.U2BHostPathsV1:
    paths = u2b_host.U2BHostPathsV1.from_root(root)
    for directory in (paths.source_root, root / "bin", root / "host"):
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        directory.chmod(0o700)
    (paths.source_root / "input.txt").write_text(
        "bounded U2B source\n",
        encoding="utf-8",
    )
    (paths.source_root / "input.txt").chmod(0o600)
    _write_clock(paths.clock_file, _U2B_START)
    helper = (materialized_root / "scripts" / "_019_macos_u2b_host.py").read_bytes()
    future_import = b"from __future__ import annotations\n"
    future_offset = helper.find(future_import)
    if future_offset < 0:
        raise ValueError("U2B host fixture is missing its future import")
    insertion_offset = future_offset + len(future_import)
    # launchd 不继承调用者 cwd/PYTHONPATH；绑定本次已验证 bundle，避免回退到脏工作树。
    module_root = os.fspath(materialized_root.resolve(strict=True))
    module_binding = (
        "import os as _u2b_os\n"
        "_u2b_os.environ.clear()\n"
        "_u2b_os.environ.update({"
        "'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'})\n"
        "import sys as _u2b_sys\n"
        "_u2b_sys.dont_write_bytecode = True\n"
        f"_u2b_sys.path.insert(0, {module_root!r})\n"
        "del _u2b_os, _u2b_sys\n"
    ).encode()
    installed = (
        f"#!{sys.executable} -I\n".encode()
        + helper[:insertion_offset]
        + module_binding
        + helper[insertion_offset:]
    )
    for target in (paths.schedule_executable, paths.child_executable):
        _write_new_file(target, installed, mode=0o700)
    fixture_source = materialized_root / "scripts" / "browser_e3_fixture.py"
    _write_new_file(root / "host" / "browser_e3_fixture.py", fixture_source.read_bytes())
    _write_new_file(
        root / "browser-fixture.json",
        (
            _json({"schema": _U2B_BROWSER_FIXTURE_SCHEMA, "port": fixture_port}) + "\n"
        ).encode(),
    )
    u2b_host.initialize_u2b_repository(root)
    return paths


def _definition(
    host: u2b_host.U2BHostCompositionV1,
    automation_id: str,
    *,
    misfire: bool,
) -> AutomationDefinitionBodyV1:
    manifest = host.workspace_repository.scan_source(
        host.source_binding,
        WorkspaceBoundsV1(),
    )
    anchor = _U2B_START
    return AutomationDefinitionBodyV1(
        automation_id=automation_id,
        revision=1,
        label=_U2B_LABEL,
        task_text=_U2B_TASK,
        source_workspace_binding_digest=u2b_host._SOURCE_BINDING_KEY,
        execution_mode=ExecutionMode.FRESH_OCCURRENCE,
        provider_descriptor_digest=host.config.provider_descriptor_digest,
        trust_profile_digest=host.config.trust_profile_digest,
        credential_environment_name=None,
        provider_disclosure_request_digest=(
            host.config.provider_disclosure_request_digest
        ),
        schedule=AutomationScheduleV1(
            kind=ScheduleKind.ONCE_UTC,
            anchor_utc=format_canonical_utc(anchor),
            interval_seconds=None,
            catch_up=CatchUpRule.NONE,
            misfire_grace_seconds=30 if misfire else 60,
        ),
        required_start_utc=format_canonical_utc(anchor),
        expires_at_utc=format_canonical_utc(anchor + timedelta(days=1)),
        max_occurrences=1,
        budgets=AutomationBudgetsV1(
            occurrence_deadline_seconds=120,
            model_calls=4,
            tool_calls=4,
            sandbox_commands=1,
            browser_actions=1,
            max_input_tokens=20_000,
            max_output_tokens=2_000,
        ),
        source_snapshot_digest=manifest.manifest_digest,
        background_environment_policy_digest=host.config.background_policy_digest,
        browser_origin_policy_digest=host.config.browser_origin_policy_digest,
        wake_adapter_policy_digest=host.wake_adapter.configured_policy_digest,
    )


def _activate(
    host: u2b_host.U2BHostCompositionV1,
    body: AutomationDefinitionBodyV1,
) -> None:
    snapshot = host.repository.load()
    created = host.core.management.create(
        body,
        expected_snapshot_token=snapshot.snapshot_token,
        next_snapshot_token="snapshot-" + hashlib.sha256(
            f"{body.automation_id}:create".encode()
        ).hexdigest()[:32],
    )
    preview = host.core.management.preview(body.automation_id)
    activated = host.core.management.approve(
        body.automation_id,
        preview_digest=preview.preview_digest,
        expected_snapshot_token=created.snapshot_token,
        next_snapshot_token="snapshot-" + hashlib.sha256(
            f"{body.automation_id}:approve".encode()
        ).hexdigest()[:32],
    )
    if activated.code != "active":
        raise RuntimeError("U2B automation did not activate")


def _kickstart(label: str) -> None:
    completed = subprocess.run(
        ("/bin/launchctl", "kickstart", "-k", f"gui/{os.geteuid()}/{label}"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=_KICKSTART_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise RuntimeError("launchd_kickstart_failed")


def _u2b_label(root: Path) -> str:
    return f"{LAUNCHD_E3_LABEL}.{canonical_json_digest(os.fspath(root))[:12]}"


def _result_paths(root: Path) -> frozenset[Path]:
    paths: set[Path] = set()
    uid = os.geteuid()
    with os.scandir(root) as entries:
        for entry in entries:
            info = entry.stat(follow_symlinks=False)
            if (
                not entry.name.endswith(".json")
                or not stat.S_ISREG(info.st_mode)
                or info.st_uid != uid
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise ValueError("private result must be a regular owner-only JSON file")
            paths.add(root / entry.name)
    return frozenset(paths)


def _wait_for_result(root: Path, baseline: frozenset[Path]) -> dict[str, object]:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        fresh = _result_paths(root) - baseline
        if len(fresh) == 1:
            value = json.loads(next(iter(fresh)).read_text(encoding="utf-8"))
            _validate_private_result(value)
            return value
        if len(fresh) > 1:
            raise RuntimeError("launchd wake produced multiple reconcile results")
        time.sleep(0.05)
    raise RuntimeError("launchd wake result timeout")


def _validate_private_result(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "code",
        "automation_id",
        "occurrence_id",
        "status",
        "reason",
    }:
        raise ValueError("private reconcile result fields are not exact")
    if value.get("schema") != _U2B_RESULT_SCHEMA or value.get("code") not in {
        "completed",
        "not_due",
        "misfire_skipped",
    }:
        raise ValueError("private reconcile result code is not closed")
    try:
        raw_status = value["status"]
        status = (
            None
            if raw_status is None
            else OccurrenceControlStatus(raw_status)
        )
        ReconcileAutomationsResultV1(
            code=value["code"],
            automation_id=value["automation_id"],
            occurrence_id=value["occurrence_id"],
            status=status,
            reason=value["reason"],
        )
    except (TypeError, ValueError) as error:
        raise ValueError("private reconcile result fields are inconsistent") from error


def _checkpoint_metrics(paths: u2b_host.U2BHostPathsV1) -> dict[str, object]:
    files = tuple(
        path
        for path in paths.runtime_state_root.rglob("*.json")
        if path.is_file() and not path.is_symlink()
    )
    tool_calls = 0
    sandbox_receipts = 0
    blocked_terminal = False
    for path in files:
        state = LocalCheckpointStore(path).load().state
        blocked_terminal = blocked_terminal or (
            state.goal is not None
            and state.goal.status is GoalStatus.BLOCKED
            and state.active_run is None
        )
        for fact in state.facts:
            if fact.kind is FactKind.TOOL_CALLS:
                calls = fact.content.get("calls")
                if isinstance(calls, (tuple, list)):
                    tool_calls += len(calls)
            elif fact.kind is FactKind.TOOL_RESULT:
                metadata = fact.content.get("metadata")
                if isinstance(metadata, dict) and metadata.get(
                    "sandbox_receipt_kind"
                ) == "background_sandbox_v1":
                    sandbox_receipts += 1
    return {
        "checkpoint_count": len(files),
        "tool_calls": tool_calls,
        "sandbox_receipts": sandbox_receipts,
        "blocked_terminal": blocked_terminal,
        "tree_digest": _sha256_tree(paths.runtime_state_root),
    }


def _provider_call_count(paths: u2b_host.U2BHostPathsV1) -> int:
    calls: list[int] = []
    for path in sorted(_result_paths(paths.provider_events_root)):
        value = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or set(value) != {"schema", "call_index"}
            or value.get("schema") != _U2B_PROVIDER_SCHEMA
            or type(value.get("call_index")) is not int
        ):
            raise ValueError("provider event is malformed")
        calls.append(value["call_index"])
    if calls and sorted(calls) != list(range(1, len(calls) + 1)):
        raise ValueError("provider call sequence is not exact")
    return len(calls)


def _process_observations(
    paths: u2b_host.U2BHostPathsV1,
) -> tuple[dict[str, object], ...]:
    observations: list[dict[str, object]] = []
    for path in sorted(_result_paths(paths.process_observations_root)):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != {
            "schema",
            "leader_pid",
            "process_group_id",
            "descendant_pid",
            "descendant_process_group_id",
        }:
            raise ValueError("process observation fields are not exact")
        if value.get("schema") != _U2B_PROCESS_SCHEMA:
            raise ValueError("process observation schema mismatch")
        for key in ("leader_pid", "process_group_id"):
            if type(value.get(key)) is not int or value[key] < 1:
                raise ValueError("process identity is malformed")
        descendant_pid = value["descendant_pid"]
        descendant_group = value["descendant_process_group_id"]
        if (
            value["leader_pid"] != value["process_group_id"]
            or (descendant_pid is None) != (descendant_group is None)
            or (
                descendant_pid is not None
                and (
                    type(descendant_pid) is not int
                    or descendant_pid < 1
                    or type(descendant_group) is not int
                    or descendant_group != value["process_group_id"]
                )
            )
        ):
            raise ValueError("process identity binding is malformed")
        observations.append(value)
    return tuple(observations)


def _processes_are_gone(observations: tuple[dict[str, object], ...]) -> bool:
    if not observations:
        return False
    for value in observations:
        try:
            if group_alive(int(value["process_group_id"])):
                return False
        except (OSError, ProcessCleanupError, ValueError):
            return False
    return True


def _effect_count(
    paths: u2b_host.U2BHostPathsV1,
    checkpoint: dict[str, object] | None = None,
) -> int:
    metrics = checkpoint or _checkpoint_metrics(paths)
    return int(metrics["sandbox_receipts"])


def _metric_snapshot(
    paths: u2b_host.U2BHostPathsV1,
    *,
    checkpoint: dict[str, object] | None = None,
    provider_calls: int | None = None,
    effects: int | None = None,
) -> dict[str, int]:
    metrics = checkpoint or _checkpoint_metrics(paths)
    return {
        "provider": (
            _provider_call_count(paths) if provider_calls is None else provider_calls
        ),
        "tools": int(metrics["tool_calls"]),
        "effects": _effect_count(paths, metrics) if effects is None else effects,
        "processes": len(_process_observations(paths)),
    }


def _metric_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    if set(before) != set(after):
        raise ValueError("metric snapshots must have exact matching keys")
    delta = {key: after[key] - before[key] for key in before}
    if any(value < 0 for value in delta.values()):
        raise ValueError("U2B counters must be monotonic")
    return delta


def _checkpoint_metrics_valid(metrics: dict[str, object]) -> bool:
    return (
        metrics.get("checkpoint_count") == 1
        and metrics.get("tool_calls") == 1
        and metrics.get("sandbox_receipts") == 1
        and metrics.get("blocked_terminal") is True
    )


def _browser_proof_valid(
    storage: dict[str, bool],
    guard: dict[str, bool],
    *,
    observations: int,
) -> bool:
    return (
        type(observations) is int
        and observations > 0
        and bool(storage)
        and bool(guard)
        and all(value is True for value in (*storage.values(), *guard.values()))
    )


def _duplicate_delta_valid(delta: dict[str, int]) -> bool:
    return set(delta) == {"provider", "tools", "effects", "processes"} and all(
        value == 0 for value in delta.values()
    )


def _misfire_delta_valid(delta: dict[str, int]) -> bool:
    return _duplicate_delta_valid(delta)


def _plist_allowlist_exact(payload: bytes, executable: Path) -> bool:
    try:
        value = plistlib.loads(payload)
    except Exception:
        return False
    return value == {
        "Label": _u2b_label(executable.parents[1]),
        "ProgramArguments": [os.fspath(executable), "reconcile"],
        "RunAtLoad": False,
        "StartInterval": u2b_host._WAKE_INTERVAL_SECONDS,
    }


def _secret_free(payload: bytes) -> bool:
    folded = payload.decode("utf-8", errors="ignore").casefold()
    return all(sentinel.casefold() not in folded for sentinel in _PRIVATE_TEXT_SENTINELS)


def _owner_only_tree(roots: tuple[Path, ...]) -> bool:
    uid = os.geteuid()
    for root in roots:
        for path in (root, *root.rglob("*")):
            try:
                info = path.lstat()
            except OSError:
                return False
            if stat.S_ISLNK(info.st_mode) or info.st_uid != uid:
                return False
            expected = 0o700 if stat.S_ISDIR(info.st_mode) else 0o600
            if stat.S_IMODE(info.st_mode) != expected:
                return False
    return True


def _write_clock(path: Path, value: datetime) -> None:
    _write_new_file(
        path,
        (
            _json({"schema": _U2B_CLOCK_SCHEMA, "utc": format_canonical_utc(value)})
            + "\n"
        ).encode(),
        replace=True,
    )


def _write_new_file(
    path: Path,
    payload: bytes,
    *,
    mode: int = 0o600,
    replace: bool = False,
) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.{time.monotonic_ns()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(temporary, flags, mode)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("U2B file write made no progress")
            view = view[written:]
        os.fchmod(fd, mode)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        try:
            existing = path.lstat()
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if not replace:
                raise FileExistsError(path)
            if (
                not stat.S_ISREG(existing.st_mode)
                or existing.st_uid != os.geteuid()
            ):
                raise ValueError("U2B replacement target must be an owner file")
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _directory_identity(path: Path) -> str:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError("U2B root must be a real directory")
    return canonical_json_digest(
        {"device": info.st_dev, "inode": info.st_ino, "owner": info.st_uid}
    )


def _remove_tree_nofollow(root: Path, *, expected_identity: str) -> None:
    if _directory_identity(root) != expected_identity:
        raise ValueError("U2B root identity drift")
    parent_fd = os.open(root.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = os.open(root.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        _remove_directory_contents(root_fd)
        if _directory_identity(root) != expected_identity:
            raise ValueError("U2B root identity drift during cleanup")
        os.rmdir(root.name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        os.close(root_fd)
        os.close(parent_fd)


def _remove_directory_contents(directory_fd: int) -> None:
    for entry in list(os.scandir(directory_fd)):
        info = entry.stat(follow_symlinks=False)
        if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            os.unlink(entry.name, dir_fd=directory_fd)
        elif stat.S_ISDIR(info.st_mode):
            child = os.open(
                entry.name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            try:
                _remove_directory_contents(child)
            finally:
                os.close(child)
            os.rmdir(entry.name, dir_fd=directory_fd)
        else:
            raise ValueError("U2B root contains an unsafe node")


def _run_mutation_gate(materialized_root: Path) -> dict[str, int]:
    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--color=no",
            "--tb=short",
            *U2B_MUTATION_NODE_IDS,
        ),
        cwd=materialized_root,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    match = re.search(r"(?:^|\s)(\d+) passed(?:\s|$)", completed.stdout)
    return {
        "exit_code": completed.returncode,
        "pass_count": 0 if match is None else int(match.group(1)),
        "node_count": len(U2B_MUTATION_NODE_IDS),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomically(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    temporary = path.parent / f".{path.name}.{os.getpid()}.{time.monotonic_ns()}"
    _write_new_file(temporary, encoded)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run-019-macos-e3")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--materialized-root", type=Path)
    parser.add_argument("--seal", type=Path)
    parser.add_argument("--verifier", type=Path)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-full-count", type=int)
    parser.add_argument("--materialized-full-count", type=int)
    args = parser.parse_args(argv)
    result = run_preflight()
    if args.preflight or result.status != "qualified":
        print(_json(asdict(result)))
        return 0 if result.status == "qualified" else 2
    required = {
        "materialized_root": args.materialized_root,
        "seal": args.seal,
        "verifier": args.verifier,
        "wheel": args.wheel,
        "review": args.review,
        "source_full_count": args.source_full_count,
        "materialized_full_count": args.materialized_full_count,
        "output": args.output,
    }
    if any(value is None for value in required.values()):
        parser.error(
            "--run requires materialized-root, seal, verifier, wheel, review and output"
        )
    return run_u2b(preflight=result, **required)


if __name__ == "__main__":
    raise SystemExit(main())
