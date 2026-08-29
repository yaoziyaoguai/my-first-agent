#!/usr/bin/env python3
"""018 E3 runner：真实 TLS/Chromium 的 13 journey × 3 fresh attempt。

输出只包含 closed booleans、counts、enums 与 digests；不保存 transcript、页面
正文、profile path 或 credential。fixture 只负责把 deterministic loopback TLS
映射为 production egress guard 可验证的公共 host，browser/tool/state/evidence
路径全部使用产品实现。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.browser_e3_fixture import start_hostile_tls_fixture  # noqa: E402
from scripts.browser_e3_journeys import (  # noqa: E402
    BrowserE3JourneySuite,
    RealBrowserFlow,
)

E3_VARS = (
    "FIRST_AGENT_018_E3_BROWSER_ROOT",
    "FIRST_AGENT_018_E3_FIXTURE_ROOT",
)
NEEDS_MARKER = "NEEDS_018_BROWSER_CONFIG(stage=U2,reason=" + ",".join(E3_VARS) + ")"

SCHEMA = "my-first-agent/browser-e3-receipt/v1"
JOURNEY_IDS = tuple(f"J{index}" for index in range(1, 14))
JOURNEY_SUBCHECKS: dict[str, frozenset[str]] = {
    "J1": frozenset({
        "readiness_reported_one_reason_or_ready",
        "base_cli_starts_without_browser",
        "readiness_line_count_one",
    }),
    "J2": frozenset({
        "session_opened",
        "observation_bounded",
        "observation_digest_present",
        "storage_not_reused_after_close",
    }),
    "J3": frozenset({
        "loopback_listener_reachable",
        "production_guard_rejects_loopback",
        "server_request_count_zero",
    }),
    "J4": frozenset({
        "redirect_disallowed_zero_effect",
        "popup_disallowed_zero_effect",
        "iframe_disallowed_zero_effect",
        "subresource_disallowed_zero_effect",
        "websocket_disallowed_zero_effect",
        "allowed_fixture_path_normal",
    }),
    "J5": frozenset({
        "hostile_text_observed",
        "goal_not_changed",
        "tool_surface_not_changed",
        "origin_not_expanded",
        "unauthorized_effect_zero",
    }),
    "J6": frozenset({
        "pending_before_headed_activation",
        "headed_activation_observed",
        "takeover_pending_persisted",
        "provider_calls_during_takeover_zero",
        "tool_calls_during_takeover_zero",
        "observe_calls_during_takeover_zero",
        "credential_sentinel_zero",
        "credential_absent_from_tool_results",
        "credential_absent_from_checkpoint",
        "credential_absent_from_render",
        "complete_revision_incremented",
    }),
    "J7": frozenset({
        "fill_disclose_approved",
        "draft_only_before_submit",
        "submit_count_before_approval_zero",
        "submit_count_after_approval_one",
        "readback_proves_result",
    }),
    "J8": frozenset({
        "submit_denied",
        "submit_count_zero_after_denial",
        "safe_read_continues",
        "goal_not_verified_done",
        "denial_user_explanation_accurate",
        "opposite_denial_explanation_rejected",
    }),
    "J9": frozenset({
        "stale_target_detected",
        "known_not_executed_returned",
        "effect_count_zero",
    }),
    "J10": frozenset({
        "upload_approved_once",
        "server_received_approved_digest_only",
        "changed_digest_zero_upload",
        "symlink_zero_upload",
        "other_field_mutation_zero_upload",
    }),
    "J11": frozenset({
        "download_approved_once",
        "receipt_digest_matches_file",
        "workspace_tree_unchanged",
        "unapproved_no_receipt",
        "oversize_no_receipt",
        "no_open_execute",
    }),
    "J12": frozenset({
        "crash_classified_or_unknown",
        "readback_classifies_without_replay",
        "unclassifiable_projects_needs_human",
        "no_auto_replay",
        "resume_effect_count_not_increased",
    }),
    "J13": frozenset({
        "revoked_session_blocked",
        "cleanup_confirmed",
        "profile_clear_confirmed",
        "old_profile_session_and_lease_unusable",
        "quarantine_cleanup_confirmed",
        "browser_process_cleanup_confirmed",
        "verified_done_only_with_readback",
        "verified_done_denied_without_readback",
    }),
}

CLAIM_NODE_IDS: tuple[str, ...] = (
    "tests/cli/test_018_browser_experience.py::"
    "test_composition_integrates_browser_in_existing_root_only",
    "tests/browser/test_profile_store.py::"
    "test_profile_metadata_is_owner_only_and_opaque",
    "tests/browser/test_profile_store.py::"
    "test_store_root_symlink_fails_closed_before_writing",
    "tests/browser/test_session_store.py::"
    "test_illegal_phase_transitions_fail_closed",
    "tests/browser/test_session_store.py::"
    "test_cas_cannot_bypass_domain_specific_apis",
    "tests/browser/test_egress_guard.py::"
    "test_every_request_kind_uses_the_same_guard_admission",
    "tests/browser/test_egress_guard.py::"
    "test_rejected_requests_increment_attempts_but_never_send",
    "tests/browser/test_egress_guard.py::"
    "test_dns_rebinding_address_drift_fails_closed",
    "tests/browser/test_observation.py::test_password_values_never_projected",
    "tests/browser/test_observation.py::"
    "test_observation_contract_stores_no_raw_page_state",
    "tests/browser/test_interactive_actions.py::"
    "test_drifted_targets_are_known_not_executed_with_zero_effect",
    "tests/browser/test_interactive_actions.py::"
    "test_same_origin_url_drift_is_stale",
    "tests/browser/test_interactive_actions.py::"
    "test_frame_tree_drift_is_stale",
    "tests/browser/test_action_policy.py::test_closed_consequence_matrix",
    "tests/browser/test_action_policy.py::test_model_risk_low_is_ignored",
    "tests/browser/test_tool_authority.py::"
    "test_stale_or_consumed_browser_lease_cannot_authorize_changed_action",
    "tests/browser/test_tool_authority.py::"
    "test_browser_lease_use_is_consumed_in_executing_checkpoint",
    "tests/continuity/test_browser_takeover_flow.py::"
    "test_takeover_tool_result_returns_waiting_without_second_model_call",
    "tests/browser/test_upload.py::"
    "test_upload_rejects_paths_outside_closed_workspace_boundary",
    "tests/browser/test_upload.py::"
    "test_upload_executes_once_only_after_exact_lease_and_removes_staging",
    "tests/browser/test_download.py::"
    "test_download_requires_exact_lease_and_returns_quarantine_receipt_only",
    "tests/browser/test_download.py::"
    "test_download_quarantine_failure_after_click_is_unknown_and_poisons_session",
    "tests/browser/test_browser_cleanup.py::"
    "test_worker_exception_returns_error_and_poisons_handle",
    "tests/continuity/test_browser_verified_done.py::"
    "test_dom_or_prose_alone_cannot_verify",
    "tests/continuity/test_browser_verified_done.py::"
    "test_internally_consistent_old_goal_id_evidence_fails_closed",
    "tests/cli/test_018_browser_experience.py::"
    "test_unavailable_browser_gives_one_reason_and_one_next_action",
    "tests/cli/test_018_browser_experience.py::"
    "test_browser_act_approval_preview_is_exact_and_bounded",
)
CLAIM_TEST_COUNT = 63

COUNT_KEYS = frozenset(
    {
        "provider_calls",
        "browser_prepare_calls",
        "browser_execute_calls",
        "network_guard_attempts",
        "network_sends",
        "browser_submit_count",
        "browser_upload_count",
        "browser_download_count",
        "profile_revision_at_start",
        "profile_revision_at_end",
        "quarantine_mutations",
        "workspace_mutations",
        "completion_claims",
    }
)
CLAIM_GATE_KEYS = frozenset({"exit_code", "pass_count", "node_count"})
ATTEMPT_KEYS = frozenset({
    "attempt_id",
    "claim_gate",
    "journey_subchecks",
    "counters",
    "profile_identity_sha256",
    "session_identity_sha256",
    "quarantine_identity_sha256",
})
RECEIPT_KEYS = frozenset({
    "schema",
    "materialized_root_sha256",
    "seal_sha256",
    "verifier_sha256",
    "runner_sha256",
    "wheel_sha256",
    "playwright_version",
    "chromium_revision",
    "chromium_executable_sha256",
    "egress_fixture_sha256",
    "attempts",
})


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def validate_journey(journey_id: str, subchecks: object) -> list[str]:
    if not isinstance(subchecks, dict):
        return [f"{journey_id}: subchecks must be an object"]
    expected = JOURNEY_SUBCHECKS[journey_id]
    actual = set(subchecks)
    errors: list[str] = []
    if expected - actual:
        errors.append(f"{journey_id}: missing subchecks {sorted(expected - actual)}")
    if actual - expected:
        errors.append(f"{journey_id}: extra subchecks {sorted(actual - expected)}")
    for key in expected & actual:
        value = subchecks[key]
        if not isinstance(value, bool):
            errors.append(
                f"{journey_id}.{key}: must be bool, got {type(value).__name__}"
            )
        elif value is not True:
            errors.append(f"{journey_id}.{key}: must be True")
    return errors


def validate_attempt(attempt: object) -> list[str]:
    if not isinstance(attempt, dict):
        return ["attempt must be an object"]
    errors: list[str] = []
    if set(attempt) != ATTEMPT_KEYS:
        return [
            f"attempt keys mismatch: expected {sorted(ATTEMPT_KEYS)}, "
            f"got {sorted(attempt)}"
        ]
    if not isinstance(attempt.get("attempt_id"), str) or not attempt["attempt_id"]:
        errors.append("attempt_id must be a non-empty string")
    for key in (
        "profile_identity_sha256",
        "session_identity_sha256",
        "quarantine_identity_sha256",
    ):
        if not _valid_digest(attempt.get(key)):
            errors.append(f"{key} must be a 64-char lowercase hex digest")
    journeys = attempt.get("journey_subchecks")
    if not isinstance(journeys, dict) or set(journeys) != set(JOURNEY_IDS):
        errors.append(
            f"journey set mismatch: expected {len(JOURNEY_IDS)}, "
            f"got {len(journeys) if isinstance(journeys, dict) else 'non-dict'}"
        )
    else:
        for journey_id in JOURNEY_IDS:
            errors.extend(validate_journey(journey_id, journeys[journey_id]))
    gate = attempt.get("claim_gate")
    if not isinstance(gate, dict) or set(gate) != CLAIM_GATE_KEYS:
        errors.append("claim_gate keys must match the strict schema")
    else:
        if gate.get("exit_code") != 0:
            errors.append("claim_gate exit_code must be 0")
        for key in ("pass_count", "node_count"):
            value = gate.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                errors.append(f"claim_gate {key} must be a positive int")
        if gate.get("pass_count") != gate.get("node_count"):
            errors.append("claim_gate must pass every exact node once")
        if gate.get("node_count") != CLAIM_TEST_COUNT:
            errors.append(
                f"claim_gate must contain {CLAIM_TEST_COUNT} collected tests"
            )
    counters = attempt.get("counters")
    if not isinstance(counters, dict) or set(counters) != COUNT_KEYS:
        errors.append(f"counter set mismatch: expected {len(COUNT_KEYS)}")
    else:
        for key, value in counters.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"counter {key} must be a non-negative int")
        exact = {
            # J6 用唯一 production AgentRuntime：GoalDelta、takeover tool call，
            # 以及交还控制后的 bounded retryable sentinel 各一次。pending 窗口
            # 内的零调用由 journey closed subcheck 单独证明。
            "provider_calls": 3,
            "browser_submit_count": 1,
            "browser_upload_count": 1,
            "browser_download_count": 1,
            "quarantine_mutations": 1,
            "workspace_mutations": 0,
            "completion_claims": 2,
        }
        for key, expected in exact.items():
            if counters.get(key) != expected:
                errors.append(f"counter {key} must equal {expected}")
        minimum = {
            "browser_prepare_calls": 1,
            "browser_execute_calls": 1,
            "network_guard_attempts": 6,
            "network_sends": 1,
            "profile_revision_at_start": 1,
        }
        for key, expected in minimum.items():
            value = counters.get(key)
            if type(value) is int and value < expected:
                errors.append(f"counter {key} must be at least {expected}")
        start = counters.get("profile_revision_at_start")
        end = counters.get("profile_revision_at_end")
        if type(start) is int and type(end) is int and end != start + 1:
            errors.append("profile revision must increase exactly once")
    return errors


def validate_receipt(receipt: object) -> list[str]:
    if not isinstance(receipt, dict):
        return ["receipt must be an object"]
    if set(receipt) != RECEIPT_KEYS:
        return ["receipt keys must match the strict schema"]
    errors: list[str] = []
    if receipt.get("schema") != SCHEMA:
        errors.append(f"receipt schema must be {SCHEMA!r}")
    for key in (
        "materialized_root_sha256",
        "seal_sha256",
        "verifier_sha256",
        "runner_sha256",
        "wheel_sha256",
        "chromium_executable_sha256",
        "egress_fixture_sha256",
    ):
        if not _valid_digest(receipt.get(key)):
            errors.append(f"{key} must be a 64-char lowercase hex digest")
    for key in ("playwright_version", "chromium_revision"):
        value = receipt.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{key} must be a non-empty string")
    attempts = receipt.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != 3:
        errors.append("receipt requires exactly three attempts")
        return errors
    for attempt in attempts:
        errors.extend(validate_attempt(attempt))
    attempt_ids = [item.get("attempt_id") for item in attempts if isinstance(item, dict)]
    if len(set(attempt_ids)) != 3:
        errors.append("attempt_id values must be unique")
    for key in (
        "profile_identity_sha256",
        "session_identity_sha256",
        "quarantine_identity_sha256",
    ):
        identities = [item.get(key) for item in attempts if isinstance(item, dict)]
        if len(set(identities)) != 3:
            errors.append(f"{key} values must be fresh across attempts")
    return errors


def run_claim_nodes(node_ids: tuple[str, ...] = CLAIM_NODE_IDS) -> tuple[int, int]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--color=no",
            "--tb=short",
            *node_ids,
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=600,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    match = re.search(r"(?:^|\s)(\d+) passed(?:\s|$)", result.stdout)
    pass_count = int(match.group(1)) if match is not None else 0
    return result.returncode, pass_count


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_tree(path: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file()
        and not {"__pycache__", ".pytest_cache"}.intersection(
            candidate.relative_to(path).parts
        )
        and candidate.suffix != ".pyc"
    )
    for item in files:
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(_sha256_file(item)))
    return digest.hexdigest()


def _browser_identity() -> tuple[bool, str, str, str, str]:
    try:
        import playwright
    except ImportError:
        return False, "browser_package_missing", "", "", ""
    try:
        package_version = importlib.metadata.version("playwright")
        browsers = json.loads(
            (
                Path(playwright.__file__).resolve().parent
                / "driver"
                / "package"
                / "browsers.json"
            ).read_text(encoding="utf-8")
        )["browsers"]
        chromium_revision = next(
            item["revision"] for item in browsers if item.get("name") == "chromium"
        )
        # sync_playwright 的 connection event-loop 不得先在 runner 主线程
        # 启停、再在 product worker thread 启动；macOS 下会留下 pending Task。
        # qualification 在独立短进程完成，真实 journey 仍只用 adapter worker。
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from playwright.sync_api import sync_playwright; "
                    "p=sync_playwright().start(); "
                    "print(p.chromium.executable_path); p.stop()"
                ),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if probe.returncode != 0:
            return False, "browser_startup_failed", package_version, chromium_revision, ""
        executable = probe.stdout.strip()
    except Exception:
        return False, "browser_startup_failed", "", "", ""
    if not executable or not os.path.exists(executable):
        return False, "browser_binary_missing", package_version, chromium_revision, ""
    return (
        True,
        "",
        package_version,
        chromium_revision,
        _sha256_file(Path(executable)),
    )


def run_attempt(attempt_id: str, fixture_root: Path) -> dict:
    """执行一次 fresh U1 + 13 条真实 browser journey。"""

    counters = {key: 0 for key in COUNT_KEYS}
    claim_exit, claim_pass = run_claim_nodes()
    if claim_exit != 0 or claim_pass != CLAIM_TEST_COUNT:
        raise RuntimeError(
            f"U1 claim gate failed: exit={claim_exit}, passed={claim_pass}, "
            f"expected={CLAIM_TEST_COUNT}"
        )
    available, reason, _pw_version, _revision, exec_sha = _browser_identity()
    if not available:
        print(f"NEEDS_018_BROWSER_CONFIG(stage=U2,reason={reason})")
        raise SystemExit(3)

    fixture = start_hostile_tls_fixture(fixture_root, attempt_id=attempt_id)
    flow: RealBrowserFlow | None = None
    temporary: tempfile.TemporaryDirectory[str] | None = None
    try:
        temporary = tempfile.TemporaryDirectory(
            prefix=f"{attempt_id}-",
            dir=fixture_root.parent,
        )
        flow = RealBrowserFlow(
            root=Path(temporary.name),
            fixture=fixture,
            browser_identity_digest=exec_sha,
            counters=counters,
        )
        journey_subchecks = BrowserE3JourneySuite(flow).run()
        if tuple(journey_subchecks) != JOURNEY_IDS:
            raise RuntimeError("018 journey set drifted")
        counters["network_guard_attempts"] += flow.environment.egress_attempts()
        counters["network_sends"] += flow.environment.egress_sends()
        identity_fields = flow.identity_fields()
    finally:
        try:
            if flow is not None:
                flow.shutdown()
        finally:
            try:
                if temporary is not None:
                    temporary.cleanup()
            finally:
                fixture.close()

    return {
        "attempt_id": attempt_id,
        "claim_gate": {
            "exit_code": claim_exit,
            "pass_count": claim_pass,
            "node_count": CLAIM_TEST_COUNT,
        },
        "journey_subchecks": journey_subchecks,
        "counters": counters,
        **identity_fields,
    }


def _write_json_atomically(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="018 E3 receipt runner")
    parser.add_argument("--materialized-root", type=Path, required=True)
    parser.add_argument("--seal", type=Path, required=True)
    parser.add_argument("--verifier", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    materialized_root = _sha256_tree(args.materialized_root)
    args.fixture_root.mkdir(parents=True, exist_ok=True)
    attempts = [
        run_attempt(f"attempt-{index}", args.fixture_root) for index in range(1, 4)
    ]
    if _sha256_tree(args.materialized_root) != materialized_root:
        raise RuntimeError("materialized source mutated during E3")
    available, reason, pw_version, chromium_revision, exec_sha = _browser_identity()
    if not available:
        print(f"NEEDS_018_BROWSER_CONFIG(stage=U2,reason={reason})")
        return 3
    receipt = {
        "schema": SCHEMA,
        "materialized_root_sha256": materialized_root,
        "seal_sha256": _sha256_file(args.seal),
        "verifier_sha256": _sha256_file(args.verifier),
        "runner_sha256": _sha256_file(Path(__file__)),
        "wheel_sha256": _sha256_file(args.wheel),
        "playwright_version": pw_version,
        "chromium_revision": chromium_revision,
        "chromium_executable_sha256": exec_sha,
        "egress_fixture_sha256": _sha256_tree(args.fixture_root),
        "attempts": attempts,
    }
    errors = validate_receipt(receipt)
    if errors:
        raise RuntimeError("receipt validation failed: " + "; ".join(errors[:8]))
    _write_json_atomically(args.output, receipt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
