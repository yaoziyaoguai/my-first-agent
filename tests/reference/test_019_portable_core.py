from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

U1_CLAIM_TESTS: dict[str, tuple[str, str]] = {
    "C1": (
        "tests/automation/test_contracts.py::test_definition_digest_binds_every_authority_field",
        "tests/automation/test_contracts.py::test_grant_cannot_bind_a_different_definition_body",
    ),
    "C2": (
        "tests/automation/test_schedule.py::test_latest_one_skips_superseded_slots_and_claims_one",
        "tests/automation/test_schedule.py::test_occurrence_identity_binds_revision_slot_time_and_definition",
    ),
    "C3": (
        "tests/automation/test_store.py::test_snapshot_codec_round_trips_the_complete_definition",
        "tests/automation/test_store.py::test_snapshot_decode_rejects_an_extra_nested_member",
    ),
    "C4": (
        "tests/automation/test_purge.py::test_full_record_capacity_is_freed_only_by_confirmed_finish_purge",
        "tests/automation/test_purge.py::test_finishing_129th_tombstone_evicts_only_the_oldest_confirmed_one",
    ),
    "C5": (
        "tests/automation/test_management.py::test_create_preview_and_approve_activate_one_exact_revision",
        "tests/automation/test_preview.py::test_approval_rejects_a_preview_after_source_drift",
    ),
    "C6": (
        "tests/automation/test_controller.py::test_update_approval_cuts_over_future_claims_but_preserves_active_claim",
        "tests/automation/test_controller.py::test_stale_update_approval_cannot_replace_a_newer_draft",
    ),
    "C7": (
        "tests/automation/test_controller.py::test_pause_resume_and_cancel_without_active_work_are_exact",
        "tests/automation/test_cancel_race.py::test_cancel_pending_after_prepare_rejects_invoke_with_zero_callable",
    ),
    "C8": (
        "tests/automation/test_trigger_payload.py::test_trigger_payload_has_only_schema_and_optional_delivery_identity",
        "tests/automation/test_trigger_payload.py::test_trigger_payload_rejects_every_authority_or_locator_field",
    ),
    "C9": (
        "tests/automation/test_reconcile.py::test_one_reconcile_selects_only_the_earliest_scheduled_then_automation_id",
        "tests/automation/test_reconcile.py::test_not_due_returns_before_workspace_executor_or_supervisor",
    ),
    "C10": (
        "tests/automation/test_supervisor_protocol.py::test_ready_callback_precedes_start_and_executor_runs_exactly_once",
        "tests/automation/test_supervisor_protocol.py::test_unknown_start_permit_never_calls_executor",
    ),
    "C11": (
        "tests/automation/test_model_call_recovery.py::test_restart_consumes_durable_model_response_without_provider_resend",
        "tests/automation/test_model_call_recovery.py::test_restart_with_only_provider_intent_is_unknown_and_never_resends",
    ),
    "C12": (
        "tests/automation/test_reconcile.py::test_due_occurrence_crosses_ready_barrier_and_terminalizes_once",
        "tests/automation/test_deadline_projection.py::test_worker_deadline_is_a_bounded_terminal_result_not_success",
    ),
    "C13": (
        "tests/automation/test_claim_verifier.py::test_exact_running_claim_returns_closed_grant_verdict",
        "tests/automation/test_claim_verifier.py::test_claim_identity_mutations_fail_closed",
    ),
    "C14": (
        "tests/automation/test_tool_authority.py::test_exact_confined_sandbox_grant_bypasses_no_ordinary_lease",
        "tests/automation/test_tool_authority.py::test_missing_or_failed_claim_verifier_fails_closed_before_callable",
    ),
    "C15": (
        "tests/automation/test_tool_authority.py::test_public_browser_open_is_admitted_but_disclose_remains_approval",
        "tests/automation/test_tool_authority.py::test_policy_workspace_and_budget_drift_do_not_gain_background_authority",
    ),
    "C16": (
        "tests/automation/test_tool_budgets.py::test_background_tool_and_class_budgets_increment_in_executing_checkpoint",
        "tests/automation/test_tool_budgets.py::test_background_budget_reuse_and_wrong_ordinal_fail_closed",
    ),
    "C17": (
        "tests/automation/test_occurrence_workspace.py::test_materialization_is_a_fresh_owned_copy_bound_to_the_source",
        "tests/automation/test_source_snapshot.py::test_capture_rejects_content_drift_without_partial_object",
    ),
    "C18": (
        "tests/automation/test_owned_cleanup.py::test_exact_owned_identity_is_deleted_only_after_terminal_capture",
        "tests/automation/test_owned_cleanup.py::test_identity_replacement_is_cleanup_unknown_and_preserves_ownership",
    ),
    "C19": (
        "tests/automation/test_preview.py::test_requested_capability_requires_its_qualification",
        "tests/automation/test_tool_authority.py::test_ephemeral_environment_and_browser_policy_drift_require_approval",
    ),
    "C20": (
        "tests/automation/test_contracts.py::test_external_summary_has_no_private_or_host_path_field",
        "tests/automation/test_preview.py::test_preview_schema_has_no_secret_or_absolute_path_field",
    ),
    "C21": (
        "tests/automation/test_open_handoff.py::test_open_handoff_is_exact_and_runtime_projection_keeps_automation_paused",
        "tests/automation/test_open_handoff.py::test_open_handoff_drift_fails_before_any_runtime_action",
    ),
    "C22": (
        "tests/automation/test_purge.py::test_management_preview_is_manifest_bound_and_reconciler_converges",
        "tests/automation/test_purge.py::test_purge_crash_boundaries_resume_without_recreating_private_definition",
    ),
    "C23": (
        "tests/automation/test_cli.py::test_public_parser_has_management_surface_without_old_raw_scheduler_fields",
        "tests/architecture/test_019_portable_boundary.py::test_only_controller_calls_repository_compare_and_swap",
    ),
    "C24": (
        "tests/automation/test_reconcile_faults.py::test_child_result_recovery_terminalizes_without_a_second_execution",
        "tests/automation/test_reconcile_faults.py::test_terminal_commit_before_commit_recovers_exact_artifact_without_reexecution",
    ),
    "C25": (
        "tests/architecture/test_019_portable_boundary.py::test_portable_automation_package_has_no_concrete_host_backend_import",
        "tests/architecture/test_019_portable_boundary.py::test_reconciler_has_no_timer_loop_or_repository_cas_access",
    ),
}


def test_every_frozen_claim_has_one_behavior_and_one_unique_mutation_node() -> None:
    assert tuple(U1_CLAIM_TESTS) == tuple(f"C{index}" for index in range(1, 26))
    nodes = tuple(node for pair in U1_CLAIM_TESTS.values() for node in pair)
    assert len(nodes) == 50
    assert len(set(nodes)) == len(nodes)


def test_every_mapped_u1_node_exists_as_a_collected_test_function() -> None:
    by_file: dict[Path, set[str]] = {}
    for pair in U1_CLAIM_TESTS.values():
        for node in pair:
            relative, function_name = node.split("::", 1)
            by_file.setdefault(ROOT / relative, set()).add(function_name)
    for path, expected_functions in by_file.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert expected_functions <= functions, path
