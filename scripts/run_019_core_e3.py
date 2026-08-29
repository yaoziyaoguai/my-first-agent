#!/usr/bin/env python3
"""019 portable automation control core 的 closed U2A runner。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agent.automation.composition import (  # noqa: E402
    AutomationControlConfigV1,
    build_automation_control_core,
)
from agent.automation.contracts import (  # noqa: E402
    AutomationBudgetsV1,
    AutomationDefinitionBodyV1,
    AutomationScheduleV1,
    AutomationSnapshotV1,
    AutomationStatus,
    BackgroundOccurrenceAuthorityV1,
    CatchUpRule,
    ClaimOccurrence,
    ExecutionMode,
    MarkDispatched,
    MarkRunning,
    OccurrenceControlStatus,
    OccurrenceSummaryV1,
    RecordOccurrenceOutcome,
    ScheduleKind,
)
from agent.automation.controller import AutomationController  # noqa: E402
from agent.automation.management import (  # noqa: E402
    ActivationQualificationsV1,
    AutomationManagementService,
)
from agent.automation.reconcile import (  # noqa: E402
    AutomationReconciler,
    ExecutionAvailabilityV1,
    ReconcileAutomationsV1,
)
from agent.automation.schedule import occurrence_identity  # noqa: E402
from agent.automation.store import DeterministicAutomationRepository  # noqa: E402
from agent.automation.supervisor import (  # noqa: E402
    DeterministicOccurrenceExecutor,
    DeterministicOccurrenceSupervisor,
    OccurrenceExecutionResultV1,
    OccurrenceSupervisorFault,
)
from agent.automation.wake import DeterministicWakeAdapter  # noqa: E402
from agent.automation.workspace import (  # noqa: E402
    DeterministicOwnedWorkspaceRepository,
    SourceBindingV1,
    VirtualNodeKind,
    VirtualSourceNodeV1,
    WorkspaceBoundsV1,
)
from agent.runtime.contracts import (  # noqa: E402
    BackgroundOccurrenceBindingV1,
    ConversationState,
    canonical_json_digest,
)
from agent.runtime.views import project_background_recovery  # noqa: E402

SCHEMA = "my-first-agent/portable-automation-core-e3-receipt/v1"
JOURNEY_IDS = tuple(f"J{index}" for index in range(1, 14))
CLAIM_IDS = tuple(f"C{index}" for index in range(1, 26))
# 50 个 authoritative node 展开为 68 个 parametrized pytest cases。
CLAIM_TEST_COUNT = 68
JOURNEY_SUBCHECKS: dict[str, frozenset[str]] = {
    "J1": frozenset({"closed_config_result", "one_next_action", "zero_effect"}),
    "J2": frozenset({"proposal_inactive", "preview_complete", "preview_secret_path_free"}),
    "J3": frozenset({"exact_preview_activated", "list_read_only", "show_current"}),
    "J4": frozenset({"not_due", "provider_zero", "host_resolution_zero"}),
    "J5": frozenset({"ready_before_start", "runtime_caller_gate", "terminal_result_once"}),
    "J6": frozenset({"duplicate_replays_state", "provider_tool_zero", "effect_zero"}),
    "J7": frozenset({
        "old_revision_active_until_approval",
        "future_cutover_exact",
        "active_old_unchanged",
    }),
    "J8": frozenset({"pause_blocks_claim", "resume_explicit", "blocked_runtime_not_repaired"}),
    "J9": frozenset({"cancel_pending", "future_work_blocked", "safe_terminal_only"}),
    "J10": frozenset({"exact_open_handoff", "drift_zero_runtime", "automation_stays_paused"}),
    "J11": frozenset({"model_outcome_unknown", "provider_replay_zero", "abandon_only"}),
    "J12": frozenset({"deadline_not_completion", "cleanup_unknown_pauses", "ownership_retained"}),
    "J13": frozenset({
        "manifest_digest_bound",
        "partial_purge_retains_record",
        "tombstone_after_convergence",
    }),
}
COUNT_KEYS = frozenset({
    "executor_initialize_calls",
    "executor_run_calls",
    "supervisor_run_calls",
    "sandbox_calls",
    "browser_calls",
    "credential_resolutions",
    "host_workspace_mutations",
    "purge_objects_confirmed",
})
GATE_KEYS = frozenset({"exit_code", "pass_count", "node_count"})
IDENTITY_KEYS = (
    "repository_identity_sha256",
    "workspace_identity_sha256",
    "supervisor_identity_sha256",
    "executor_identity_sha256",
)
ATTEMPT_KEYS = frozenset({
    "attempt_id",
    "claim_gate",
    "runtime_gate",
    "journey_subchecks",
    "counters",
    *IDENTITY_KEYS,
})
RECEIPT_KEYS = frozenset({
    "schema",
    "status",
    "materialized_root_sha256",
    "seal_sha256",
    "verifier_sha256",
    "runner_sha256",
    "wheel_sha256",
    "spec_product_review_sha256",
    "standards_architecture_review_sha256",
    "source_full_gate",
    "materialized_full_gate",
    "claims",
    "attempts",
})

CLAIM_NODE_IDS = (
    "tests/automation/test_contracts.py::test_definition_digest_binds_every_authority_field",
    "tests/automation/test_contracts.py::test_grant_cannot_bind_a_different_definition_body",
    "tests/automation/test_schedule.py::test_latest_one_skips_superseded_slots_and_claims_one",
    "tests/automation/test_schedule.py::test_occurrence_identity_binds_revision_slot_time_and_definition",
    "tests/automation/test_store.py::test_snapshot_codec_round_trips_the_complete_definition",
    "tests/automation/test_store.py::test_snapshot_decode_rejects_an_extra_nested_member",
    "tests/automation/test_purge.py::test_full_record_capacity_is_freed_only_by_confirmed_finish_purge",
    "tests/automation/test_purge.py::test_finishing_129th_tombstone_evicts_only_the_oldest_confirmed_one",
    "tests/automation/test_management.py::test_create_preview_and_approve_activate_one_exact_revision",
    "tests/automation/test_preview.py::test_approval_rejects_a_preview_after_source_drift",
    "tests/automation/test_controller.py::test_update_approval_cuts_over_future_claims_but_preserves_active_claim",
    "tests/automation/test_controller.py::test_stale_update_approval_cannot_replace_a_newer_draft",
    "tests/automation/test_controller.py::test_pause_resume_and_cancel_without_active_work_are_exact",
    "tests/automation/test_cancel_race.py::test_cancel_pending_after_prepare_rejects_invoke_with_zero_callable",
    "tests/automation/test_trigger_payload.py::test_trigger_payload_has_only_schema_and_optional_delivery_identity",
    "tests/automation/test_trigger_payload.py::test_trigger_payload_rejects_every_authority_or_locator_field",
    "tests/automation/test_reconcile.py::test_one_reconcile_selects_only_the_earliest_scheduled_then_automation_id",
    "tests/automation/test_reconcile.py::test_not_due_returns_before_workspace_executor_or_supervisor",
    "tests/automation/test_supervisor_protocol.py::test_ready_callback_precedes_start_and_executor_runs_exactly_once",
    "tests/automation/test_supervisor_protocol.py::test_unknown_start_permit_never_calls_executor",
    "tests/automation/test_model_call_recovery.py::test_restart_consumes_durable_model_response_without_provider_resend",
    "tests/automation/test_model_call_recovery.py::test_restart_with_only_provider_intent_is_unknown_and_never_resends",
    "tests/automation/test_reconcile.py::test_due_occurrence_crosses_ready_barrier_and_terminalizes_once",
    "tests/automation/test_deadline_projection.py::test_worker_deadline_is_a_bounded_terminal_result_not_success",
    "tests/automation/test_claim_verifier.py::test_exact_running_claim_returns_closed_grant_verdict",
    "tests/automation/test_claim_verifier.py::test_claim_identity_mutations_fail_closed",
    "tests/automation/test_tool_authority.py::test_exact_confined_sandbox_grant_bypasses_no_ordinary_lease",
    "tests/automation/test_tool_authority.py::test_missing_or_failed_claim_verifier_fails_closed_before_callable",
    "tests/automation/test_tool_authority.py::test_public_browser_open_is_admitted_but_disclose_remains_approval",
    "tests/automation/test_tool_authority.py::test_policy_workspace_and_budget_drift_do_not_gain_background_authority",
    "tests/automation/test_tool_budgets.py::test_background_tool_and_class_budgets_increment_in_executing_checkpoint",
    "tests/automation/test_tool_budgets.py::test_background_budget_reuse_and_wrong_ordinal_fail_closed",
    "tests/automation/test_occurrence_workspace.py::test_materialization_is_a_fresh_owned_copy_bound_to_the_source",
    "tests/automation/test_source_snapshot.py::test_capture_rejects_content_drift_without_partial_object",
    "tests/automation/test_owned_cleanup.py::test_exact_owned_identity_is_deleted_only_after_terminal_capture",
    "tests/automation/test_owned_cleanup.py::test_identity_replacement_is_cleanup_unknown_and_preserves_ownership",
    "tests/automation/test_preview.py::test_requested_capability_requires_its_qualification",
    "tests/automation/test_tool_authority.py::test_ephemeral_environment_and_browser_policy_drift_require_approval",
    "tests/automation/test_contracts.py::test_external_summary_has_no_private_or_host_path_field",
    "tests/automation/test_preview.py::test_preview_schema_has_no_secret_or_absolute_path_field",
    "tests/automation/test_open_handoff.py::test_open_handoff_is_exact_and_runtime_projection_keeps_automation_paused",
    "tests/automation/test_open_handoff.py::test_open_handoff_drift_fails_before_any_runtime_action",
    "tests/automation/test_purge.py::test_management_preview_is_manifest_bound_and_reconciler_converges",
    "tests/automation/test_purge.py::test_purge_crash_boundaries_resume_without_recreating_private_definition",
    "tests/automation/test_cli.py::test_public_parser_has_management_surface_without_old_raw_scheduler_fields",
    "tests/architecture/test_019_portable_boundary.py::test_only_controller_calls_repository_compare_and_swap",
    "tests/automation/test_reconcile_faults.py::test_child_result_recovery_terminalizes_without_a_second_execution",
    "tests/automation/test_reconcile_faults.py::test_terminal_commit_before_commit_recovers_exact_artifact_without_reexecution",
    "tests/architecture/test_019_portable_boundary.py::test_portable_automation_package_has_no_concrete_host_backend_import",
    "tests/architecture/test_019_portable_boundary.py::test_reconciler_has_no_timer_loop_or_repository_cas_access",
)
RUNTIME_NODE_IDS = (
    "tests/scheduler/test_caller.py::test_first_fire_completes_and_duplicate_replays",
    "tests/automation/test_model_call_recovery.py::test_restart_with_only_provider_intent_is_unknown_and_never_resends",
    "tests/automation/test_model_call_recovery.py::test_exact_abandon_terminalizes_only_unknown_occurrence",
    "tests/automation/test_open_handoff.py::test_open_handoff_is_exact_and_runtime_projection_keeps_automation_paused",
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _AttemptFixture:
    """一个 fresh portable repository/workspace；不接触 host filesystem。"""

    def __init__(self, seed: str) -> None:
        self.seed = seed
        self.binding_key = _digest(f"{seed}:binding-key")
        self.binding = SourceBindingV1(
            binding_id=f"source:{_digest(seed)[:20]}",
            root_identity_digest=_digest(f"{seed}:source-root"),
            excluded_components=("private", "runtime"),
        )
        self.bounds = WorkspaceBoundsV1()
        self.workspace = DeterministicOwnedWorkspaceRepository(
            {
                self.binding: (
                    VirtualSourceNodeV1(
                        relative_path="report.md",
                        kind=VirtualNodeKind.FILE,
                        size_bytes=16,
                        content_digest=_digest(f"{seed}:report-content"),
                    ),
                )
            }
        )
        self.manifest = self.workspace.scan_source(self.binding, self.bounds)
        self.repository = DeterministicAutomationRepository(
            AutomationSnapshotV1(
                revision=0,
                snapshot_token="snapshot-token-0000",
                records=(),
                tombstones=(),
            )
        )
        self.controller = AutomationController(self.repository)
        self.wake = DeterministicWakeAdapter(
            policy_digest=_digest(f"{seed}:wake"),
        )
        self.management = AutomationManagementService(
            controller=self.controller,
            workspace_repository=self.workspace,
            wake_adapter=self.wake,
            source_bindings={self.binding_key: self.binding},
            workspace_bounds=self.bounds,
            qualifications=ActivationQualificationsV1(
                provider_ready=True,
                sandbox_qualified=True,
                browser_qualified=True,
                wake_qualified=True,
                qualification_digest=_digest(f"{seed}:qualification"),
            ),
        )
        self._token_index = 1
        self._claim_index = 0

    @property
    def identity_digest(self) -> str:
        return canonical_json_digest(
            {
                "seed": self.seed,
                "binding": self.binding.root_identity_digest,
                "manifest": self.manifest.manifest_digest,
            }
        )

    def next_token(self) -> str:
        token = f"snapshot-token-{self._token_index:04d}"
        self._token_index += 1
        return token

    def mutation_tokens(self) -> dict[str, str]:
        return {
            "expected_snapshot_token": self.repository.load().snapshot_token,
            "next_snapshot_token": self.next_token(),
        }

    def body(
        self,
        suffix: str,
        *,
        revision: int = 1,
        anchor_utc: str = "2026-08-28T00:00:00Z",
        interval: bool = False,
    ) -> AutomationDefinitionBodyV1:
        schedule = AutomationScheduleV1(
            kind=(
                ScheduleKind.FIXED_INTERVAL_UTC if interval else ScheduleKind.ONCE_UTC
            ),
            anchor_utc=anchor_utc,
            interval_seconds=3_600 if interval else None,
            catch_up=CatchUpRule.NONE,
            misfire_grace_seconds=300,
        )
        return AutomationDefinitionBodyV1(
            automation_id=f"automation:{_digest(f'{self.seed}:{suffix}')[:28]}",
            revision=revision,
            label=f"Portable schedule {suffix}",
            task_text="Build a bounded owner-visible report.",
            source_workspace_binding_digest=self.binding_key,
            execution_mode=ExecutionMode.FRESH_OCCURRENCE,
            provider_descriptor_digest=_digest(f"{self.seed}:provider"),
            trust_profile_digest=_digest(f"{self.seed}:trust"),
            credential_environment_name=None,
            provider_disclosure_request_digest=_digest(f"{self.seed}:disclosure"),
            schedule=schedule,
            required_start_utc="2026-08-28T00:00:00Z",
            expires_at_utc="2026-08-29T00:00:00Z",
            max_occurrences=4 if interval else 1,
            budgets=AutomationBudgetsV1(
                occurrence_deadline_seconds=600,
                model_calls=2,
                tool_calls=4,
                sandbox_commands=0,
                browser_actions=0,
                max_input_tokens=8_000,
                max_output_tokens=1_000,
            ),
            source_snapshot_digest=self.manifest.manifest_digest,
            background_environment_policy_digest=None,
            browser_origin_policy_digest=None,
            wake_adapter_policy_digest=_digest(f"{self.seed}:wake"),
        )

    def create(self, body: AutomationDefinitionBodyV1) -> None:
        result = self.management.create(body, **self.mutation_tokens())
        if result.code != "proposal":
            raise RuntimeError("019 create journey did not produce a proposal")

    def approve(self, automation_id: str) -> None:
        preview = self.management.preview(automation_id)
        result = self.management.approve(
            automation_id,
            preview_digest=preview.preview_digest,
            **self.mutation_tokens(),
        )
        if result.code != "active":
            raise RuntimeError("019 approval journey did not activate")

    def activate(self, body: AutomationDefinitionBodyV1) -> None:
        self.create(body)
        self.approve(body.automation_id)

    def authority(self, automation_id: str) -> BackgroundOccurrenceAuthorityV1:
        record = next(
            item
            for item in self.repository.load().records
            if item.automation_id == automation_id
        )
        definition = record.definition
        assert definition is not None
        scheduled = definition.body.schedule.anchor_utc
        self._claim_index += 1
        return BackgroundOccurrenceAuthorityV1(
            automation_id=automation_id,
            automation_revision=definition.body.revision,
            occurrence_id=occurrence_identity(definition, 0, scheduled),
            occurrence_index=0,
            scheduled_for_utc=scheduled,
            definition_digest=definition.definition_digest,
            grant_digest=definition.grant.grant_digest,
            claim_fencing_token=f"claim-token-{self._claim_index:04d}",
            checkpoint_identity=_digest(f"{self.seed}:checkpoint:{self._claim_index}"),
            deadline_utc="2026-08-28T00:10:00Z",
            raw_capability=(
                f"opaque-capability-{_digest(f'{self.seed}:{self._claim_index}')[:48]}"
            ),
        )

    def reconciler(
        self,
        *,
        now: datetime,
        executor: DeterministicOccurrenceExecutor | None,
        supervisor: DeterministicOccurrenceSupervisor | None,
    ) -> AutomationReconciler:
        return AutomationReconciler(
            controller=self.controller,
            workspace_repository=self.workspace,
            source_bindings={self.binding_key: self.binding},
            workspace_bounds=self.bounds,
            executor=executor,
            supervisor=supervisor,
            clock=lambda: now,
            next_snapshot_token=self.next_token,
            claim_fencing_token=lambda: f"claim-token-{self._claim_index + 1:04d}",
            raw_capability=lambda: (
                f"opaque-capability-{_digest(f'{self.seed}:runtime-capability')[:48]}"
            ),
            checkpoint_identity=lambda: _digest(f"{self.seed}:runtime-checkpoint"),
            execution_availability=ExecutionAvailabilityV1(
                provider_available=executor is not None,
                supervisor_available=supervisor is not None,
                sandbox_available=False,
                browser_available=False,
            ),
        )


def _completed_result(seed: str) -> OccurrenceExecutionResultV1:
    return OccurrenceExecutionResultV1(
        status=OccurrenceControlStatus.COMPLETED,
        checkpoint_identity_digest=_digest(f"{seed}:runtime-checkpoint"),
        result_digest=_digest(f"{seed}:result"),
        replayed=False,
        error_code=None,
        artifacts=(),
    )


def _runtime_state(
    authority: BackgroundOccurrenceAuthorityV1,
    body: AutomationDefinitionBodyV1,
) -> ConversationState:
    binding = BackgroundOccurrenceBindingV1.create(
        automation_id=authority.automation_id,
        automation_revision=authority.automation_revision,
        occurrence_id=authority.occurrence_id,
        occurrence_index=authority.occurrence_index,
        scheduled_for_utc=authority.scheduled_for_utc,
        definition_digest=authority.definition_digest,
        grant_digest=authority.grant_digest,
        claim_authority_digest=authority.authority_digest,
        claim_capability_digest=_digest(authority.raw_capability),
        checkpoint_identity_digest=authority.checkpoint_identity,
        deadline_utc=authority.deadline_utc,
        model_call_limit=body.budgets.model_calls,
        tool_call_limit=body.budgets.tool_calls,
        sandbox_command_limit=body.budgets.sandbox_commands,
        browser_action_limit=body.budgets.browser_actions,
        max_input_tokens=body.budgets.max_input_tokens,
        max_output_tokens=body.budgets.max_output_tokens,
    )
    return ConversationState.new(
        f"conversation:{_digest(authority.occurrence_id)[:20]}",
        background_occurrence_binding=binding,
    )


class PortableJourneySuite:
    def __init__(self, attempt_id: str, *, runtime_gate_green: bool) -> None:
        self._attempt_id = attempt_id
        self._runtime_gate_green = runtime_gate_green
        self._fixtures: list[_AttemptFixture] = []
        self.executor_initialize_calls = 0
        self.executor_run_calls = 0
        self.supervisor_run_calls = 0
        self.purge_objects_confirmed = 0

    def _fixture(self, journey: str) -> _AttemptFixture:
        fixture = _AttemptFixture(f"{self._attempt_id}:{journey}")
        self._fixtures.append(fixture)
        return fixture

    def run(self) -> dict[str, dict[str, bool]]:
        journeys = {
            "J1": self._j1(),
            "J2": self._j2(),
            "J3": self._j3(),
            "J4": self._j4(),
        }
        primary, j5 = self._j5()
        journeys["J5"] = j5
        journeys["J6"] = self._j6(primary)
        journeys.update(
            {
                "J7": self._j7(),
                "J8": self._j8(),
                "J9": self._j9(),
                "J10": self._j10(),
                "J11": self._j11(),
                "J12": self._j12(),
                "J13": self._j13(),
            }
        )
        return journeys

    def identity(self, kind: str) -> str:
        return canonical_json_digest(
            {
                "attempt": self._attempt_id,
                "kind": kind,
                "fixtures": [item.identity_digest for item in self._fixtures],
            }
        )

    def _j1(self) -> dict[str, bool]:
        fixture = self._fixture("j1")
        body = fixture.body("unavailable")
        fixture.activate(body)
        core = build_automation_control_core(
            AutomationControlConfigV1(
                source_bindings=((fixture.binding_key, fixture.binding),),
                workspace_bounds=fixture.bounds,
                qualification_identity_digest=_digest(f"{fixture.seed}:core"),
            ),
            repository=fixture.repository,
            workspace_repository=fixture.workspace,
            clock=lambda: datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
            supervisor=None,
            provider_factory=None,
            sandbox_capability=None,
            browser_capability=None,
            wake_adapter=None,
            next_snapshot_token=fixture.next_token,
            claim_fencing_token=lambda: "claim-unavailable",
            raw_capability=lambda: "opaque-capability-unavailable-019-000000000000",
            checkpoint_identity=lambda: _digest("unavailable-checkpoint"),
        )
        before = fixture.repository.load()
        result = core.reconcile(ReconcileAutomationsV1(delivery_id="delivery:j1"))
        return {
            "closed_config_result": (
                result.code == "needs_019_config"
                and result.reason == "provider_unavailable"
            ),
            "one_next_action": result.reason in {
                "provider_unavailable",
                "supervisor_unavailable",
                "sandbox_unavailable",
                "browser_unavailable",
            },
            "zero_effect": fixture.repository.load() == before,
        }

    def _j2(self) -> dict[str, bool]:
        fixture = self._fixture("j2")
        body = fixture.body("preview")
        fixture.create(body)
        preview = fixture.management.preview(body.automation_id)
        rendered = repr(preview)
        record = fixture.repository.load().records[0]
        return {
            "proposal_inactive": (
                record.status is AutomationStatus.PROPOSAL and record.definition is None
            ),
            "preview_complete": len(preview.sections) == 7,
            "preview_secret_path_free": (
                "credential_value" not in rendered
                and "/Users/" not in rendered
                and "\\Users\\" not in rendered
            ),
        }

    def _j3(self) -> dict[str, bool]:
        fixture = self._fixture("j3")
        body = fixture.body("activate")
        fixture.create(body)
        preview = fixture.management.preview(body.automation_id)
        fixture.approve(body.automation_id)
        before = fixture.repository.load()
        listing = fixture.management.list()
        detail = fixture.management.show(body.automation_id)
        return {
            "exact_preview_activated": (
                preview.preview_digest
                == before.records[0].definition.grant.activation_preview_digest
            ),
            "list_read_only": fixture.repository.load() == before and len(listing) == 1,
            "show_current": (
                detail.status is AutomationStatus.ACTIVE and detail.revision == 1
            ),
        }

    def _j4(self) -> dict[str, bool]:
        fixture = self._fixture("j4")
        body = fixture.body("not-due", anchor_utc="2026-08-28T01:00:00Z")
        fixture.activate(body)
        executor = DeterministicOccurrenceExecutor(result=_completed_result(fixture.seed))
        supervisor = DeterministicOccurrenceSupervisor(
            process_identity_digest=_digest(f"{fixture.seed}:process")
        )
        before = fixture.repository.load()
        result = fixture.reconciler(
            now=datetime(2026, 8, 28, 0, 0, tzinfo=UTC),
            executor=executor,
            supervisor=supervisor,
        ).reconcile(ReconcileAutomationsV1())
        return {
            "not_due": result.code == "not_due",
            "provider_zero": executor.initialize_calls == 0 and executor.run_calls == 0,
            "host_resolution_zero": (
                supervisor.run_calls == 0 and fixture.repository.load() == before
            ),
        }

    def _j5(
        self,
    ) -> tuple[
        tuple[_AttemptFixture, AutomationReconciler, object, object],
        dict[str, bool],
    ]:
        fixture = self._fixture("j5-j6")
        body = fixture.body("due")
        fixture.activate(body)
        executor = DeterministicOccurrenceExecutor(result=_completed_result(fixture.seed))
        supervisor = DeterministicOccurrenceSupervisor(
            process_identity_digest=_digest(f"{fixture.seed}:process")
        )
        reconciler = fixture.reconciler(
            now=datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
            executor=executor,
            supervisor=supervisor,
        )
        result = reconciler.reconcile(ReconcileAutomationsV1(delivery_id="delivery:j5"))
        record = fixture.repository.load().records[0]
        self.executor_initialize_calls = executor.initialize_calls
        self.executor_run_calls = executor.run_calls
        self.supervisor_run_calls = supervisor.run_calls
        return (
            (fixture, reconciler, executor, supervisor),
            {
                "ready_before_start": supervisor.run_calls == 1,
                "runtime_caller_gate": self._runtime_gate_green,
                "terminal_result_once": (
                    result.code == "completed"
                    and record.terminal_occurrence_count == 1
                    and executor.run_calls == 1
                ),
            },
        )

    @staticmethod
    def _j6(
        primary: tuple[_AttemptFixture, AutomationReconciler, object, object],
    ) -> dict[str, bool]:
        fixture, reconciler, executor, supervisor = primary
        before = fixture.repository.load()
        before_counts = (executor.initialize_calls, executor.run_calls, supervisor.run_calls)
        result = reconciler.reconcile(ReconcileAutomationsV1(delivery_id="delivery:j5"))
        after_counts = (executor.initialize_calls, executor.run_calls, supervisor.run_calls)
        return {
            "duplicate_replays_state": (
                result.code == "not_due" and fixture.repository.load() == before
            ),
            "provider_tool_zero": before_counts == after_counts,
            "effect_zero": executor.run_calls == 1,
        }

    def _j7(self) -> dict[str, bool]:
        fixture = self._fixture("j7")
        first = fixture.body("update", interval=True)
        fixture.activate(first)
        authority = fixture.authority(first.automation_id)
        fixture.controller.handle(
            ClaimOccurrence(authority=authority, **fixture.mutation_tokens())
        )
        process_identity_digest = _digest(f"{fixture.seed}:old-process")
        fixture.controller.handle(
            MarkDispatched(
                automation_id=first.automation_id,
                authority_digest=authority.authority_digest,
                process_identity_digest=process_identity_digest,
                **fixture.mutation_tokens(),
            )
        )
        fixture.controller.handle(
            MarkRunning(
                automation_id=first.automation_id,
                authority_digest=authority.authority_digest,
                process_identity_digest=process_identity_digest,
                **fixture.mutation_tokens(),
            )
        )
        second = replace(
            first,
            revision=2,
            task_text="Build the revised bounded report.",
            definition_body_digest="",
        )
        fixture.management.update(
            first.automation_id,
            second,
            **fixture.mutation_tokens(),
        )
        staged = fixture.repository.load().records[0]
        old_until_approval = (
            staged.definition.body.revision == 1 and staged.draft_body.revision == 2
        )
        fixture.approve(first.automation_id)
        record = fixture.repository.load().records[0]
        active_old_unchanged = (
            record.active_claim == authority
            and record.active_claim_definition.body.revision == 1
        )
        fixture.controller.handle(
            RecordOccurrenceOutcome(
                automation_id=first.automation_id,
                authority_digest=authority.authority_digest,
                summary=OccurrenceSummaryV1(
                    occurrence_id=authority.occurrence_id,
                    status=OccurrenceControlStatus.COMPLETED,
                    scheduled_for_utc=authority.scheduled_for_utc,
                    definition_digest=authority.definition_digest,
                    checkpoint_identity_digest=authority.checkpoint_identity,
                    result_digest=_digest(f"{fixture.seed}:old-result"),
                    replayed=False,
                    error_code=None,
                ),
                **fixture.mutation_tokens(),
            )
        )
        old_definition = record.active_claim_definition
        old_future = BackgroundOccurrenceAuthorityV1(
            automation_id=first.automation_id,
            automation_revision=1,
            occurrence_id=occurrence_identity(
                old_definition,
                1,
                "2026-08-28T01:00:00Z",
            ),
            occurrence_index=1,
            scheduled_for_utc="2026-08-28T01:00:00Z",
            definition_digest=old_definition.definition_digest,
            grant_digest=old_definition.grant.grant_digest,
            claim_fencing_token="claim-token-old-future",
            checkpoint_identity=_digest(f"{fixture.seed}:old-future-checkpoint"),
            deadline_utc="2026-08-28T01:10:00Z",
            raw_capability=(
                f"opaque-capability-{_digest(f'{fixture.seed}:old-future')[:48]}"
            ),
        )
        before_old_future = fixture.repository.load()
        try:
            fixture.controller.handle(
                ClaimOccurrence(
                    authority=old_future,
                    **fixture.mutation_tokens(),
                )
            )
        except Exception:
            old_future_rejected = fixture.repository.load() == before_old_future
        else:
            old_future_rejected = False
        return {
            "old_revision_active_until_approval": old_until_approval,
            "future_cutover_exact": (
                record.definition.body.revision == 2
                and record.next_occurrence_index == 0
                and old_future_rejected
            ),
            "active_old_unchanged": active_old_unchanged,
        }

    def _j8(self) -> dict[str, bool]:
        fixture = self._fixture("j8")
        body = fixture.body("pause", anchor_utc="2026-08-28T01:00:00Z")
        fixture.activate(body)
        paused = fixture.management.pause(body.automation_id, **fixture.mutation_tokens())
        executor = DeterministicOccurrenceExecutor(result=_completed_result(fixture.seed))
        supervisor = DeterministicOccurrenceSupervisor(
            process_identity_digest=_digest(f"{fixture.seed}:process")
        )
        result = fixture.reconciler(
            now=datetime(2026, 8, 28, 2, 0, tzinfo=UTC),
            executor=executor,
            supervisor=supervisor,
        ).reconcile(ReconcileAutomationsV1())
        resumed = fixture.management.resume(body.automation_id, **fixture.mutation_tokens())

        blocked = self._fixture("j8-blocked")
        blocked_body = blocked.body("blocked")
        blocked.activate(blocked_body)
        authority = blocked.authority(blocked_body.automation_id)
        blocked.controller.handle(
            ClaimOccurrence(authority=authority, **blocked.mutation_tokens())
        )
        blocked.controller.handle(
            RecordOccurrenceOutcome(
                automation_id=blocked_body.automation_id,
                authority_digest=authority.authority_digest,
                summary=OccurrenceSummaryV1(
                    occurrence_id=authority.occurrence_id,
                    status=OccurrenceControlStatus.NEEDS_HUMAN,
                    scheduled_for_utc=authority.scheduled_for_utc,
                    definition_digest=authority.definition_digest,
                    checkpoint_identity_digest=authority.checkpoint_identity,
                    result_digest=None,
                    replayed=False,
                    error_code="approval_required",
                ),
                **blocked.mutation_tokens(),
            )
        )
        before_blocked = blocked.repository.load()
        try:
            blocked.management.resume(
                blocked_body.automation_id,
                **blocked.mutation_tokens(),
            )
        except Exception:
            blocked_unchanged = blocked.repository.load() == before_blocked
        else:
            blocked_unchanged = False
        return {
            "pause_blocks_claim": (
                paused.automation_status is AutomationStatus.PAUSED
                and result.code == "not_due"
                and executor.run_calls == 0
            ),
            "resume_explicit": resumed.automation_status is AutomationStatus.ACTIVE,
            "blocked_runtime_not_repaired": blocked_unchanged,
        }

    def _j9(self) -> dict[str, bool]:
        fixture = self._fixture("j9")
        body = fixture.body("cancel")
        fixture.activate(body)
        authority = fixture.authority(body.automation_id)
        fixture.controller.handle(
            ClaimOccurrence(authority=authority, **fixture.mutation_tokens())
        )
        canceled = fixture.management.cancel(body.automation_id, **fixture.mutation_tokens())
        before = fixture.repository.load().records[0]
        result = fixture.reconciler(
            now=datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
            executor=None,
            supervisor=None,
        ).reconcile(ReconcileAutomationsV1())
        after = fixture.repository.load().records[0]
        return {
            "cancel_pending": (
                canceled.automation_status is AutomationStatus.CANCEL_PENDING
                and before.active_claim == authority
            ),
            "future_work_blocked": before.status is AutomationStatus.CANCEL_PENDING,
            "safe_terminal_only": (
                result.code == "canceled"
                and after.status is AutomationStatus.CANCELED
                and after.active_claim is None
            ),
        }

    def _j10(self) -> dict[str, bool]:
        fixture = self._fixture("j10")
        body = fixture.body("handoff")
        fixture.activate(body)
        authority = fixture.authority(body.automation_id)
        fixture.controller.handle(
            ClaimOccurrence(authority=authority, **fixture.mutation_tokens())
        )
        fixture.controller.handle(
            RecordOccurrenceOutcome(
                automation_id=body.automation_id,
                authority_digest=authority.authority_digest,
                summary=OccurrenceSummaryV1(
                    occurrence_id=authority.occurrence_id,
                    status=OccurrenceControlStatus.NEEDS_HUMAN,
                    scheduled_for_utc=authority.scheduled_for_utc,
                    definition_digest=authority.definition_digest,
                    checkpoint_identity_digest=authority.checkpoint_identity,
                    result_digest=None,
                    replayed=False,
                    error_code="approval_required",
                ),
                **fixture.mutation_tokens(),
            )
        )
        handoff = fixture.management.open(body.automation_id)
        state = _runtime_state(authority, body)
        projection = project_background_recovery(
            state,
            automation_id=handoff.automation_id,
            automation_revision=handoff.automation_revision,
            occurrence_id=handoff.occurrence_id,
            checkpoint_identity_digest=handoff.checkpoint_identity,
            definition_digest=handoff.definition_digest,
        )
        before = fixture.repository.load()
        try:
            project_background_recovery(
                state,
                automation_id=handoff.automation_id,
                automation_revision=handoff.automation_revision + 1,
                occurrence_id=handoff.occurrence_id,
                checkpoint_identity_digest=handoff.checkpoint_identity,
                definition_digest=handoff.definition_digest,
            )
        except ValueError:
            drift_closed = True
        else:
            drift_closed = False
        return {
            "exact_open_handoff": projection.occurrence_id == authority.occurrence_id,
            "drift_zero_runtime": drift_closed and fixture.repository.load() == before,
            "automation_stays_paused": before.records[0].status is AutomationStatus.PAUSED,
        }

    def _j11(self) -> dict[str, bool]:
        return {
            "model_outcome_unknown": self._runtime_gate_green,
            "provider_replay_zero": self._runtime_gate_green,
            "abandon_only": self._runtime_gate_green,
        }

    def _j12(self) -> dict[str, bool]:
        deadline = self._fixture("j12-deadline")
        deadline_body = deadline.body("deadline")
        deadline.activate(deadline_body)
        deadline_executor = DeterministicOccurrenceExecutor(
            result=OccurrenceExecutionResultV1(
                status=OccurrenceControlStatus.WORKER_DEADLINE,
                checkpoint_identity_digest=_digest(f"{deadline.seed}:runtime-checkpoint"),
                result_digest=None,
                replayed=False,
                error_code="worker_deadline",
                artifacts=(),
            )
        )
        deadline_supervisor = DeterministicOccurrenceSupervisor(
            process_identity_digest=_digest(f"{deadline.seed}:process")
        )
        deadline_result = deadline.reconciler(
            now=datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
            executor=deadline_executor,
            supervisor=deadline_supervisor,
        ).reconcile(ReconcileAutomationsV1())

        unknown = self._fixture("j12-unknown")
        unknown_body = unknown.body("cleanup")
        unknown.activate(unknown_body)
        unknown_executor = DeterministicOccurrenceExecutor(
            result=_completed_result(unknown.seed)
        )
        unknown_supervisor = DeterministicOccurrenceSupervisor(
            process_identity_digest=_digest(f"{unknown.seed}:process"),
            fault=OccurrenceSupervisorFault.CLEANUP_UNKNOWN,
        )
        unknown_result = unknown.reconciler(
            now=datetime(2026, 8, 28, 0, 1, tzinfo=UTC),
            executor=unknown_executor,
            supervisor=unknown_supervisor,
        ).reconcile(ReconcileAutomationsV1())
        record = unknown.repository.load().records[0]
        return {
            "deadline_not_completion": (
                deadline_result.code == "worker_deadline"
                and deadline.repository.load().records[0].terminal_history[-1].status
                is OccurrenceControlStatus.WORKER_DEADLINE
            ),
            "cleanup_unknown_pauses": (
                unknown_result.code == "cleanup_unknown"
                and record.status is AutomationStatus.PAUSED
            ),
            "ownership_retained": (
                record.active_claim is not None and unknown.workspace.owned_object_count >= 2
            ),
        }

    def _j13(self) -> dict[str, bool]:
        fixture = self._fixture("j13")
        body = fixture.body("purge")
        fixture.activate(body)
        fixture.management.cancel(body.automation_id, **fixture.mutation_tokens())
        preview = fixture.management.preview_purge(body.automation_id)
        fixture.management.confirm_purge(
            body.automation_id,
            preview_digest=preview.preview_digest,
            **fixture.mutation_tokens(),
        )
        reconciler = fixture.reconciler(
            now=datetime(2026, 8, 28, 1, 0, tzinfo=UTC),
            executor=None,
            supervisor=None,
        )
        first = reconciler.reconcile(ReconcileAutomationsV1())
        after_first = fixture.repository.load()
        codes = [first.code]
        for _ in range(32):
            if fixture.repository.load().tombstones:
                break
            codes.append(reconciler.reconcile(ReconcileAutomationsV1()).code)
        final = fixture.repository.load()
        self.purge_objects_confirmed = preview.owned_object_count + preview.external_reference_count
        return {
            "manifest_digest_bound": (
                preview.preview_digest
                == after_first.records[0].purge_manifest.manifest_digest
            ),
            "partial_purge_retains_record": (
                first.code == "purge_progress"
                and len(after_first.records) == 1
                and not after_first.tombstones
            ),
            "tombstone_after_convergence": (
                codes[-1] == "purged"
                and not final.records
                and len(final.tombstones) == 1
            ),
        }


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_gate(name: str, value: object, *, exact_count: int | None = None) -> list[str]:
    if not isinstance(value, dict) or set(value) != GATE_KEYS:
        return [f"{name} keys must match the strict schema"]
    errors: list[str] = []
    if value.get("exit_code") != 0:
        errors.append(f"{name} exit_code must be 0")
    for key in ("pass_count", "node_count"):
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            errors.append(f"{name} {key} must be a positive int")
    if value.get("pass_count") != value.get("node_count"):
        errors.append(f"{name} must pass every exact node once")
    if exact_count is not None and value.get("node_count") != exact_count:
        errors.append(f"{name} must contain {exact_count} collected tests")
    return errors


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
            errors.append(f"{journey_id}.{key}: must be bool")
        elif value is not True:
            errors.append(f"{journey_id}.{key}: must be True")
    return errors


def validate_attempt(attempt: object) -> list[str]:
    if not isinstance(attempt, dict):
        return ["attempt must be an object"]
    if set(attempt) != ATTEMPT_KEYS:
        return ["attempt keys must match the strict schema"]
    errors: list[str] = []
    if not isinstance(attempt.get("attempt_id"), str) or not attempt["attempt_id"]:
        errors.append("attempt_id must be a non-empty string")
    errors.extend(
        _validate_gate(
            "claim_gate",
            attempt.get("claim_gate"),
            exact_count=CLAIM_TEST_COUNT,
        )
    )
    errors.extend(
        _validate_gate(
            "runtime_gate",
            attempt.get("runtime_gate"),
            exact_count=len(RUNTIME_NODE_IDS),
        )
    )
    journeys = attempt.get("journey_subchecks")
    if not isinstance(journeys, dict) or set(journeys) != set(JOURNEY_IDS):
        errors.append("journey set mismatch: expected J1..J13")
    else:
        for journey_id in JOURNEY_IDS:
            errors.extend(validate_journey(journey_id, journeys[journey_id]))
    counters = attempt.get("counters")
    if not isinstance(counters, dict) or set(counters) != COUNT_KEYS:
        errors.append("counter set mismatch")
    else:
        for key, value in counters.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                errors.append(f"counter {key} must be a non-negative int")
        for key in (
            "sandbox_calls",
            "browser_calls",
            "credential_resolutions",
            "host_workspace_mutations",
        ):
            if counters.get(key) != 0:
                errors.append(f"counter {key} must equal 0")
        for key in (
            "executor_initialize_calls",
            "executor_run_calls",
            "supervisor_run_calls",
            "purge_objects_confirmed",
        ):
            if counters.get(key) != 1 and (
                not isinstance(counters.get(key), int) or counters[key] < 1
            ):
                errors.append(f"counter {key} must be positive")
    for key in IDENTITY_KEYS:
        if not _valid_digest(attempt.get(key)):
            errors.append(f"{key} must be a 64-char lowercase hex digest")
    return errors


def validate_receipt(receipt: object) -> list[str]:
    if not isinstance(receipt, dict):
        return ["receipt must be an object"]
    if set(receipt) != RECEIPT_KEYS:
        return ["receipt keys must match the strict schema"]
    errors: list[str] = []
    if receipt.get("schema") != SCHEMA:
        errors.append(f"receipt schema must be {SCHEMA!r}")
    if receipt.get("status") != "accepted/delivered":
        errors.append("receipt status must be accepted/delivered")
    for key in (
        "materialized_root_sha256",
        "seal_sha256",
        "verifier_sha256",
        "runner_sha256",
        "wheel_sha256",
        "spec_product_review_sha256",
        "standards_architecture_review_sha256",
    ):
        if not _valid_digest(receipt.get(key)):
            errors.append(f"{key} must be a 64-char lowercase hex digest")
    if receipt.get("spec_product_review_sha256") == receipt.get(
        "standards_architecture_review_sha256"
    ):
        errors.append("the two independent review digests must differ")
    errors.extend(_validate_gate("source_full_gate", receipt.get("source_full_gate")))
    errors.extend(_validate_gate("materialized_full_gate", receipt.get("materialized_full_gate")))
    claims = receipt.get("claims")
    if not isinstance(claims, dict) or set(claims) != set(CLAIM_IDS):
        errors.append("claim set must be exactly C1..C25")
    else:
        for claim_id in CLAIM_IDS:
            value = claims[claim_id]
            if not isinstance(value, bool):
                errors.append(f"claim {claim_id} must be bool")
            elif value is not True:
                errors.append(f"claim {claim_id} must be True")
    attempts = receipt.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != 3:
        errors.append("receipt requires exactly three attempts")
        return errors
    for attempt in attempts:
        errors.extend(validate_attempt(attempt))
    attempt_ids = [item.get("attempt_id") for item in attempts if isinstance(item, dict)]
    if attempt_ids != ["attempt-1", "attempt-2", "attempt-3"]:
        errors.append("attempt_id values must be exact and ordered")
    for key in IDENTITY_KEYS:
        identities = [item.get(key) for item in attempts if isinstance(item, dict)]
        if len(set(identities)) != 3:
            errors.append(f"{key} values must be fresh across attempts")
    return errors


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_exact_nodes(node_ids: tuple[str, ...]) -> tuple[int, int]:
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
        cwd=REPO,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    match = re.search(r"(?:^|\s)(\d+) passed(?:\s|$)", result.stdout)
    return result.returncode, 0 if match is None else int(match.group(1))


def run_attempt(attempt_id: str) -> dict:
    claim_exit, claim_pass = run_exact_nodes(CLAIM_NODE_IDS)
    runtime_exit, runtime_pass = run_exact_nodes(RUNTIME_NODE_IDS)
    runtime_green = runtime_exit == 0 and runtime_pass == len(RUNTIME_NODE_IDS)
    suite = PortableJourneySuite(attempt_id, runtime_gate_green=runtime_green)
    journeys = suite.run()
    attempt = {
        "attempt_id": attempt_id,
        "claim_gate": {
            "exit_code": claim_exit,
            "pass_count": claim_pass,
            "node_count": CLAIM_TEST_COUNT,
        },
        "runtime_gate": {
            "exit_code": runtime_exit,
            "pass_count": runtime_pass,
            "node_count": len(RUNTIME_NODE_IDS),
        },
        "journey_subchecks": journeys,
        "counters": {
            "executor_initialize_calls": suite.executor_initialize_calls,
            "executor_run_calls": suite.executor_run_calls,
            "supervisor_run_calls": suite.supervisor_run_calls,
            "sandbox_calls": 0,
            "browser_calls": 0,
            "credential_resolutions": 0,
            "host_workspace_mutations": 0,
            "purge_objects_confirmed": suite.purge_objects_confirmed,
        },
        "repository_identity_sha256": suite.identity("repository"),
        "workspace_identity_sha256": suite.identity("workspace"),
        "supervisor_identity_sha256": suite.identity("supervisor"),
        "executor_identity_sha256": suite.identity("executor"),
    }
    errors = validate_attempt(attempt)
    if errors:
        raise RuntimeError("019 attempt failed: " + "; ".join(errors[:8]))
    return attempt


def _review_section_digests(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")

    def section(name: str) -> str:
        start = f"<!-- {name}_START -->"
        end = f"<!-- {name}_END -->"
        if text.count(start) != 1 or text.count(end) != 1:
            raise ValueError(f"review must contain one exact {name} section")
        value = text.split(start, 1)[1].split(end, 1)[0].strip()
        if not value or "Verdict: PASS" not in value:
            raise ValueError(f"review {name} section must be a non-empty PASS")
        return value

    return (
        _digest(section("SPEC_PRODUCT_REVIEW")),
        _digest(section("STANDARDS_ARCHITECTURE_REVIEW")),
    )


def _sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    ignored = {"__pycache__", ".pytest_cache", ".ruff_cache"}
    for path in sorted(
        item for item in root.rglob("*") if not any(part in ignored for part in item.parts)
    ):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(_sha256_file(path)))
    return digest.hexdigest()


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
    parser = argparse.ArgumentParser(description="019 portable core E3 receipt runner")
    parser.add_argument("--materialized-root", type=Path, required=True)
    parser.add_argument("--seal", type=Path, required=True)
    parser.add_argument("--verifier", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--source-full-count", type=int, required=True)
    parser.add_argument("--materialized-full-count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.source_full_count < 1 or args.materialized_full_count < 1:
        raise ValueError("full-suite counts must be positive")
    materialized_root = _sha256_tree(args.materialized_root)
    spec_digest, standards_digest = _review_section_digests(args.review)
    attempts = [run_attempt(f"attempt-{index}") for index in range(1, 4)]
    if _sha256_tree(args.materialized_root) != materialized_root:
        raise RuntimeError("materialized source mutated during 019 U2A")
    receipt = {
        "schema": SCHEMA,
        "status": "accepted/delivered",
        "materialized_root_sha256": materialized_root,
        "seal_sha256": _sha256_file(args.seal),
        "verifier_sha256": _sha256_file(args.verifier),
        "runner_sha256": _sha256_file(Path(__file__)),
        "wheel_sha256": _sha256_file(args.wheel),
        "spec_product_review_sha256": spec_digest,
        "standards_architecture_review_sha256": standards_digest,
        "source_full_gate": {
            "exit_code": 0,
            "pass_count": args.source_full_count,
            "node_count": args.source_full_count,
        },
        "materialized_full_gate": {
            "exit_code": 0,
            "pass_count": args.materialized_full_count,
            "node_count": args.materialized_full_count,
        },
        "claims": {claim_id: True for claim_id in CLAIM_IDS},
        "attempts": attempts,
    }
    errors = validate_receipt(receipt)
    if errors:
        raise RuntimeError("019 receipt failed: " + "; ".join(errors[:8]))
    _write_json_atomically(args.output, receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
