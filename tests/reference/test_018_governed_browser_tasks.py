"""018 Task 9：U1 claim matrix——完整 pytest node IDs，subprocess 实际执行。

不做 source-string 扫描。node IDs 由 runner 的 `run_claim_nodes` subprocess
真实运行；unit test 验证执行 seam 本身（注入 subprocess + 执行已知 node）。
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# U1 claim → 完整 pytest node IDs（与 runner 的 CLAIM_NODE_IDS 同步）。
CLAIM_MATRIX: dict[str, tuple[str, ...]] = {
    "owners_single_runtime_and_toolruntime": (
        "tests/cli/test_018_browser_experience.py::"
        "test_composition_integrates_browser_in_existing_root_only",
    ),
    "profile_isolation_owner_only_and_opaque": (
        "tests/browser/test_profile_store.py::"
        "test_profile_metadata_is_owner_only_and_opaque",
        "tests/browser/test_profile_store.py::"
        "test_store_root_symlink_fails_closed_before_writing",
    ),
    "session_modes_no_silent_switch": (
        "tests/browser/test_session_store.py::"
        "test_illegal_phase_transitions_fail_closed",
        "tests/browser/test_session_store.py::"
        "test_cas_cannot_bypass_domain_specific_apis",
    ),
    "egress_all_event_kinds_same_guard": (
        "tests/browser/test_egress_guard.py::"
        "test_every_request_kind_uses_the_same_guard_admission",
        "tests/browser/test_egress_guard.py::"
        "test_rejected_requests_increment_attempts_but_never_send",
        "tests/browser/test_egress_guard.py::"
        "test_dns_rebinding_address_drift_fails_closed",
    ),
    "observation_bounded_and_secret_free": (
        "tests/browser/test_observation.py::"
        "test_password_values_never_projected",
        "tests/browser/test_observation.py::"
        "test_observation_contract_stores_no_raw_page_state",
    ),
    "target_binding_stale_drift_zero_effect": (
        "tests/browser/test_interactive_actions.py::"
        "test_drifted_targets_are_known_not_executed_with_zero_effect",
        "tests/browser/test_interactive_actions.py::"
        "test_same_origin_url_drift_is_stale",
        "tests/browser/test_interactive_actions.py::"
        "test_frame_tree_drift_is_stale",
    ),
    "consequence_closed_and_risk_low_ignored": (
        "tests/browser/test_action_policy.py::"
        "test_closed_consequence_matrix",
        "tests/browser/test_action_policy.py::"
        "test_model_risk_low_is_ignored",
    ),
    "denial_zero_effect": (
        "tests/browser/test_tool_authority.py::"
        "test_stale_or_consumed_browser_lease_cannot_authorize_changed_action",
        "tests/browser/test_tool_authority.py::"
        "test_browser_lease_use_is_consumed_in_executing_checkpoint",
    ),
    "takeover_pending_zero_activity": (
        "tests/continuity/test_browser_takeover_flow.py::"
        "test_takeover_tool_result_returns_waiting_without_second_model_call",
    ),
    "upload_workspace_relative_bounded": (
        "tests/browser/test_upload.py::"
        "test_upload_rejects_paths_outside_closed_workspace_boundary",
        "tests/browser/test_upload.py::"
        "test_upload_executes_once_only_after_exact_lease_and_removes_staging",
    ),
    "download_quarantine_only": (
        "tests/browser/test_download.py::"
        "test_download_requires_exact_lease_and_returns_quarantine_receipt_only",
        "tests/browser/test_download.py::"
        "test_download_quarantine_failure_after_click_is_unknown_and_poisons_session",
    ),
    "unknown_recovery_no_replay": (
        "tests/browser/test_browser_cleanup.py::"
        "test_worker_exception_returns_error_and_poisons_handle",
    ),
    "completion_browser_readback_only": (
        "tests/continuity/test_browser_verified_done.py::"
        "test_dom_or_prose_alone_cannot_verify",
        "tests/continuity/test_browser_verified_done.py::"
        "test_internally_consistent_old_goal_id_evidence_fails_closed",
    ),
    "ux_one_readiness_one_action": (
        "tests/cli/test_018_browser_experience.py::"
        "test_unavailable_browser_gives_one_reason_and_one_next_action",
        "tests/cli/test_018_browser_experience.py::"
        "test_browser_act_approval_preview_is_exact_and_bounded",
    ),
}


def all_node_ids() -> tuple[str, ...]:
    seen: list[str] = []
    for ids in CLAIM_MATRIX.values():
        for node_id in ids:
            if node_id not in seen:
                seen.append(node_id)
    return tuple(seen)


def run_claim_nodes(node_ids: tuple[str, ...]) -> tuple[int, int]:
    """subprocess 执行 node IDs；返回 (exit_code, pass_count)。"""

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--color=no",
            "--tb=short",
            *node_ids,
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=600,
    )
    match = re.search(r"(?:^|\s)(\d+) passed(?:\s|$)", result.stdout)
    pass_count = int(match.group(1)) if match is not None else 0
    return result.returncode, pass_count


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_claim_matrix_covers_all_u1_axes():
    assert len(CLAIM_MATRIX) == 14
    assert len(all_node_ids()) >= 20


def test_claim_nodes_actually_execute_green():
    """subprocess 实际执行全部 claim node IDs；exit 0 + pass_count ≥ node 数。"""

    node_ids = all_node_ids()
    exit_code, pass_count = run_claim_nodes(node_ids)
    assert exit_code == 0, f"claim execution failed: exit {exit_code}"
    assert pass_count >= len(node_ids), (
        f"pass_count {pass_count} < node IDs {len(node_ids)}"
    )


def test_runner_exposes_execution_seam():
    """runner 模块必须暴露 run_claim_nodes 并实际执行（非 collect-only）。"""

    runner_path = REPO / "scripts" / "run_018_e3.py"
    assert runner_path.exists()
    spec = importlib.util.spec_from_file_location("runner_018", runner_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.run_claim_nodes)
    # 用一个已知 node 验证 seam 真的执行了 pytest（非 collect）。
    test_node = (
        "tests/browser/test_contracts.py::test_browser_modes_are_closed_enums"
    )
    exit_code, pass_count = module.run_claim_nodes((test_node,))
    assert exit_code == 0
    assert pass_count >= 1


def test_runner_does_not_import_test_fakes():
    """runner 不得 import tests.* 或 fake transport（U2 production 路径）。"""

    source = (REPO / "scripts" / "run_018_e3.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(name == "tests" or name.startswith("tests.") for name in imports)
    loaded_names = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }
    assert not loaded_names & {"FakeResolver", "FakeTransport", "make_fake_factory"}


def test_sealed_fixture_is_real_tls_and_manifest_contains_no_private_key(tmp_path):
    from scripts.browser_e3_fixture import start_hostile_tls_fixture

    try:
        fixture = start_hostile_tls_fixture(tmp_path, attempt_id="attempt-test")
    except PermissionError:
        pytest.skip("verification host forbids local listener creation")
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ssl._create_unverified_context()),
        )
        response = opener.open(f"https://127.0.0.1:{fixture.port}/", timeout=5)
        assert b"Governed Browser Fixture" in response.read()
        assert fixture.state.request_count == 1
        manifest = json.loads(fixture.manifest_path.read_text(encoding="utf-8"))
        assert manifest["attempt_id"] == "attempt-test"
        assert "private" not in fixture.manifest_path.read_text(encoding="utf-8")
        assert not any(path.suffix == ".pem" for path in tmp_path.rglob("*"))
    finally:
        fixture.close()


def test_journey_verdicts_are_observations_not_literal_true() -> None:
    violations: list[str] = []
    for relative in ("scripts/run_018_e3.py", "scripts/browser_e3_journeys.py"):
        tree = ast.parse((REPO / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or not node.name.lstrip("_").startswith("j"):
                continue
            for returned in (
                item for item in ast.walk(node) if isinstance(item, ast.Return)
            ):
                if not isinstance(returned.value, ast.Dict):
                    continue
                for value in returned.value.values:
                    if isinstance(value, ast.Constant) and value.value is True:
                        violations.append(f"{relative}:{node.name}:{value.lineno}")
    assert violations == [], "literal journey verdicts: " + ", ".join(violations)


def test_runner_writes_three_fresh_attempts_atomically(tmp_path, monkeypatch) -> None:
    runner_path = REPO / "scripts" / "run_018_e3.py"
    spec = importlib.util.spec_from_file_location("runner_018_atomic", runner_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    harness_path = REPO / "tests" / "reference" / "test_018_e3_harness.py"
    harness_spec = importlib.util.spec_from_file_location("harness_018", harness_path)
    harness = importlib.util.module_from_spec(harness_spec)
    harness_spec.loader.exec_module(harness)

    monkeypatch.setattr(
        module,
        "run_attempt",
        lambda attempt_id, _fixture_root: harness.make_valid_attempt(attempt_id),
    )
    monkeypatch.setattr(
        module,
        "_browser_identity",
        lambda: (True, "", "1.62.0", "1234", "f" * 64),
    )
    materialized = tmp_path / "materialized"
    fixture = tmp_path / "fixture"
    materialized.mkdir()
    fixture.mkdir()
    (materialized / "source.py").write_text("source", encoding="utf-8")
    (fixture / "site.html").write_text("fixture", encoding="utf-8")
    seal = tmp_path / "seal.json"
    verifier = tmp_path / "verifier.py"
    wheel = tmp_path / "first_agent.whl"
    for path in (seal, verifier, wheel):
        path.write_bytes(path.name.encode("utf-8"))
    output = tmp_path / "receipt.json"

    assert module.main(
        [
            "--materialized-root", str(materialized),
            "--seal", str(seal),
            "--verifier", str(verifier),
            "--wheel", str(wheel),
            "--fixture-root", str(fixture),
            "--output", str(output),
        ]
    ) == 0
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert [attempt["attempt_id"] for attempt in receipt["attempts"]] == [
        "attempt-1",
        "attempt-2",
        "attempt-3",
    ]
    assert harness.validate_receipt(receipt) == []

    def invalid_attempt(attempt_id, _fixture_root):  # noqa: ANN001, ANN202
        attempt = harness.make_valid_attempt(attempt_id)
        attempt["counters"]["provider_calls"] = 1
        return attempt

    monkeypatch.setattr(module, "run_attempt", invalid_attempt)
    invalid_output = tmp_path / "invalid-receipt.json"
    with pytest.raises(RuntimeError, match="receipt validation failed"):
        module.main(
            [
                "--materialized-root", str(materialized),
                "--seal", str(seal),
                "--verifier", str(verifier),
                "--wheel", str(wheel),
                "--fixture-root", str(fixture),
                "--output", str(invalid_output),
            ]
        )
    assert invalid_output.exists() is False
