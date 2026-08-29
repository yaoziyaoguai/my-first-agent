"""Human-first, CLI-neutral management orchestration for portable 019 automations.

The service renders and binds proposals, then delegates every authority mutation to the sole
AutomationController.  It does not open Runtime checkpoints or answer pending approvals.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.automation.contracts import (
    ApproveRevision,
    AutomationDefinitionBodyV1,
    AutomationDefinitionV1,
    AutomationStatus,
    BeginPurge,
    CancelAutomation,
    CreateProposal,
    OccurrenceControlStatus,
    PauseAutomation,
    PurgeObjectKind,
    PurgeOwnershipManifestV1,
    ResumeAutomation,
    StageRevision,
)
from agent.automation.controller import AutomationController
from agent.automation.store import AutomationRepositoryConflictError
from agent.automation.wake import (
    WakeAdapter,
    WakeInstallOutcome,
    WakeReadbackOutcome,
    WakeRemoveOutcome,
)
from agent.automation.workspace import (
    OwnedWorkspaceRepository,
    SourceBindingV1,
    WorkspaceBoundsV1,
)
from agent.runtime.contracts import canonical_json_digest


class PreviewConflictError(RuntimeError):
    """Approval no longer binds the complete current preview."""


class ActivationUnavailableError(RuntimeError):
    """One requested unattended capability is not currently qualified."""


@dataclass(frozen=True, slots=True)
class ActivationQualificationsV1:
    provider_ready: bool
    sandbox_qualified: bool
    browser_qualified: bool
    wake_qualified: bool
    qualification_digest: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, bool)
            for value in (
                self.provider_ready,
                self.sandbox_qualified,
                self.browser_qualified,
                self.wake_qualified,
            )
        ):
            raise ValueError("qualification flags must be bools")
        _require_digest(self.qualification_digest, "qualification_digest")


@dataclass(frozen=True, slots=True)
class PreviewSectionV1:
    title: str
    lines: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.title or not self.lines or any(not line for line in self.lines):
            raise ValueError("preview section must contain bounded visible text")
        if len(self.lines) > 16 or any(len(line) > 500 for line in self.lines):
            raise ValueError("preview section exceeds its text bound")

    def identity_values(self) -> dict[str, object]:
        return {"title": self.title, "lines": list(self.lines)}


@dataclass(frozen=True, slots=True)
class AutomationPreviewV1:
    automation_id: str
    revision: int
    definition_body_digest: str
    source_manifest_digest: str
    qualification_digest: str
    sections: tuple[PreviewSectionV1, ...]
    preview_digest: str = ""

    def __post_init__(self) -> None:
        for value, field in (
            (self.definition_body_digest, "definition_body_digest"),
            (self.source_manifest_digest, "source_manifest_digest"),
            (self.qualification_digest, "qualification_digest"),
        ):
            _require_digest(value, field)
        if not isinstance(self.sections, tuple) or len(self.sections) != 7:
            raise ValueError("activation preview requires exactly seven sections")
        digest = canonical_json_digest(
            {
                "automation_id": self.automation_id,
                "revision": self.revision,
                "definition_body_digest": self.definition_body_digest,
                "source_manifest_digest": self.source_manifest_digest,
                "qualification_digest": self.qualification_digest,
                "sections": [section.identity_values() for section in self.sections],
            }
        )
        if self.preview_digest and self.preview_digest != digest:
            raise ValueError("activation preview digest mismatch")
        object.__setattr__(self, "preview_digest", digest)


@dataclass(frozen=True, slots=True)
class ManagementResultV1:
    code: str
    snapshot_token: str
    automation_status: AutomationStatus


@dataclass(frozen=True, slots=True)
class WakeManagementResultV1:
    code: str
    policy_digest: str
    manual_reconcile_required: bool = False


@dataclass(frozen=True, slots=True)
class AutomationListItemV1:
    automation_id: str
    label: str
    revision: int
    status: AutomationStatus
    terminal_occurrence_count: int


@dataclass(frozen=True, slots=True)
class AutomationDetailV1:
    automation_id: str
    label: str
    revision: int
    status: AutomationStatus
    next_actions: tuple[str, ...]
    active_occurrence_id: str | None
    needs_human_reason: str | None


@dataclass(frozen=True, slots=True)
class RuntimeOpenHandoffV1:
    automation_id: str
    automation_revision: int
    occurrence_id: str
    checkpoint_identity: str
    definition_digest: str


@dataclass(frozen=True, slots=True)
class PurgePreviewV1:
    automation_id: str
    automation_revision: int
    occurrence_count: int
    checkpoint_count: int
    owned_object_count: int
    external_reference_count: int
    preview_digest: str
    warnings: tuple[str, ...]


class AutomationManagementService:
    def __init__(
        self,
        *,
        controller: AutomationController,
        workspace_repository: OwnedWorkspaceRepository,
        wake_adapter: WakeAdapter,
        source_bindings: dict[str, SourceBindingV1],
        workspace_bounds: WorkspaceBoundsV1,
        qualifications: ActivationQualificationsV1,
    ) -> None:
        self._controller = controller
        self._workspace_repository = workspace_repository
        self._wake_adapter = wake_adapter
        self._source_bindings = dict(source_bindings)
        self._workspace_bounds = workspace_bounds
        self._qualifications = qualifications

    def wake_enable(self) -> WakeManagementResultV1:
        policy_digest = self._wake_adapter.configured_policy_digest
        if not self._qualifications.wake_qualified:
            return WakeManagementResultV1("wake_enable_unavailable", policy_digest)
        readback = self._wake_adapter.readback(policy_digest)
        if readback.outcome is WakeReadbackOutcome.INSTALLED:
            return WakeManagementResultV1("wake_already_enabled", policy_digest)
        if readback.outcome is not WakeReadbackOutcome.ABSENT:
            return WakeManagementResultV1("wake_enable_unknown", policy_digest)
        installed = self._wake_adapter.install(policy_digest)
        if installed.outcome is WakeInstallOutcome.INSTALLED:
            return WakeManagementResultV1("wake_enabled", policy_digest)
        if installed.outcome is WakeInstallOutcome.FAILED:
            return WakeManagementResultV1("wake_enable_failed", policy_digest)
        return WakeManagementResultV1("wake_enable_unknown", policy_digest)

    def wake_disable(self) -> WakeManagementResultV1:
        policy_digest = self._wake_adapter.configured_policy_digest
        if not self._qualifications.wake_qualified:
            return WakeManagementResultV1("wake_disable_unavailable", policy_digest)
        if any(record.active_claim is not None for record in self._controller.snapshot().records):
            return WakeManagementResultV1("wake_disable_refused_active", policy_digest)
        readback = self._wake_adapter.readback(policy_digest)
        if readback.outcome is WakeReadbackOutcome.ABSENT:
            return WakeManagementResultV1(
                "wake_already_disabled",
                policy_digest,
                manual_reconcile_required=True,
            )
        if readback.outcome is not WakeReadbackOutcome.INSTALLED:
            return WakeManagementResultV1("wake_disable_unknown", policy_digest)
        removed = self._wake_adapter.remove(policy_digest)
        if removed.outcome is WakeRemoveOutcome.REMOVED:
            return WakeManagementResultV1(
                "wake_disabled",
                policy_digest,
                manual_reconcile_required=True,
            )
        if removed.outcome is WakeRemoveOutcome.BUSY:
            return WakeManagementResultV1("wake_disable_refused_active", policy_digest)
        if removed.outcome is WakeRemoveOutcome.FAILED:
            return WakeManagementResultV1("wake_disable_failed", policy_digest)
        return WakeManagementResultV1("wake_disable_unknown", policy_digest)

    def create(
        self,
        body: AutomationDefinitionBodyV1,
        *,
        expected_snapshot_token: str,
        next_snapshot_token: str,
    ) -> ManagementResultV1:
        result = self._controller.handle(
            CreateProposal(expected_snapshot_token, next_snapshot_token, body)
        )
        return _management_result("proposal", result.snapshot, body.automation_id)

    def update(
        self,
        automation_id: str,
        body: AutomationDefinitionBodyV1,
        *,
        expected_snapshot_token: str,
        next_snapshot_token: str,
    ) -> ManagementResultV1:
        result = self._controller.handle(
            StageRevision(
                expected_snapshot_token,
                next_snapshot_token,
                automation_id,
                body,
            )
        )
        return _management_result("proposal", result.snapshot, automation_id)

    def preview(self, automation_id: str) -> AutomationPreviewV1:
        record = _find_record(self._controller, automation_id)
        body = record.draft_body
        if body is None:
            if record.definition is None:
                raise ActivationUnavailableError("automation has no definition to preview")
            body = record.definition.body
        self._require_qualifications(body)
        binding = self._source_bindings.get(body.source_workspace_binding_digest)
        if binding is None:
            raise ActivationUnavailableError("source workspace binding is unavailable")
        manifest = self._workspace_repository.scan_source(binding, self._workspace_bounds)
        if manifest.manifest_digest != body.source_snapshot_digest:
            raise PreviewConflictError("source manifest does not match the proposal")
        wake = self._wake_adapter.readback(body.wake_adapter_policy_digest)
        if wake.outcome in {WakeReadbackOutcome.DRIFT, WakeReadbackOutcome.UNKNOWN}:
            raise ActivationUnavailableError("wake adapter readback is not exact")
        return AutomationPreviewV1(
            automation_id=body.automation_id,
            revision=body.revision,
            definition_body_digest=body.definition_body_digest,
            source_manifest_digest=manifest.manifest_digest,
            qualification_digest=self._qualifications.qualification_digest,
            sections=_preview_sections(body),
        )

    def approve(
        self,
        automation_id: str,
        *,
        preview_digest: str,
        expected_snapshot_token: str,
        next_snapshot_token: str,
    ) -> ManagementResultV1:
        preview = self.preview(automation_id)
        if preview.preview_digest != preview_digest:
            raise PreviewConflictError("approval does not match the current preview")
        record = _find_record(self._controller, automation_id)
        body = record.draft_body
        if body is None:
            raise PreviewConflictError("automation has no inactive draft to approve")
        binding = self._source_bindings[body.source_workspace_binding_digest]
        manifest = self._workspace_repository.scan_source(binding, self._workspace_bounds)
        self._workspace_repository.capture_source(
            binding,
            manifest,
            self._workspace_bounds,
            owner_automation_id=body.automation_id,
        )
        wake = self._wake_adapter.readback(body.wake_adapter_policy_digest)
        if wake.outcome is WakeReadbackOutcome.ABSENT:
            installed = self._wake_adapter.install(body.wake_adapter_policy_digest)
            if installed.outcome is WakeInstallOutcome.FAILED:
                return _management_result(
                    "not_activated_install_failed",
                    self._controller.snapshot(),
                    automation_id,
                )
            if installed.outcome is WakeInstallOutcome.UNKNOWN:
                return _management_result(
                    "not_activated_install_unknown",
                    self._controller.snapshot(),
                    automation_id,
                )
        elif wake.outcome is not WakeReadbackOutcome.INSTALLED:
            return _management_result(
                "not_activated_install_unknown",
                self._controller.snapshot(),
                automation_id,
            )
        definition = AutomationDefinitionV1.create_from_body(
            body,
            activation_preview_digest=preview.preview_digest,
            sandbox_confined=body.budgets.sandbox_commands > 0,
            browser_public_observe=body.budgets.browser_actions > 0,
        )
        try:
            result = self._controller.handle(
                ApproveRevision(
                    expected_snapshot_token,
                    next_snapshot_token,
                    automation_id,
                    definition,
                    preview.preview_digest,
                )
            )
        except AutomationRepositoryConflictError:
            return _management_result(
                "adapter_installed_activation_conflict",
                self._controller.snapshot(),
                automation_id,
            )
        return _management_result("active", result.snapshot, automation_id)

    def list(self) -> tuple[AutomationListItemV1, ...]:
        snapshot = self._controller.snapshot()
        records = tuple(_list_item(record) for record in snapshot.records)
        tombstones = tuple(
            AutomationListItemV1(
                automation_id=item.automation_id,
                label="purged automation",
                revision=item.purged_revision,
                status=AutomationStatus.PURGED,
                terminal_occurrence_count=0,
            )
            for item in snapshot.tombstones
        )
        return tuple(sorted((*records, *tombstones), key=lambda item: item.automation_id))

    def show(self, automation_id: str) -> AutomationDetailV1:
        snapshot = self._controller.snapshot()
        tombstone = next(
            (item for item in snapshot.tombstones if item.automation_id == automation_id),
            None,
        )
        if tombstone is not None:
            return AutomationDetailV1(
                automation_id=automation_id,
                label="purged automation",
                revision=tombstone.purged_revision,
                status=AutomationStatus.PURGED,
                next_actions=(),
                active_occurrence_id=None,
                needs_human_reason=None,
            )
        record = _find_record(self._controller, automation_id)
        body = record.draft_body if record.definition is None else record.definition.body
        label = "purge pending" if body is None else body.label
        revision = (
            record.purge_manifest.automation_revision
            if body is None and record.purge_manifest is not None
            else body.revision
        )
        return AutomationDetailV1(
            automation_id=automation_id,
            label=label,
            revision=revision,
            status=record.status,
            next_actions=_next_actions(record.status, record.active_claim is not None),
            active_occurrence_id=(
                None if record.active_claim is None else record.active_claim.occurrence_id
            ),
            needs_human_reason=record.needs_human_reason,
        )

    def open(self, automation_id: str) -> RuntimeOpenHandoffV1:
        record = _find_record(self._controller, automation_id)
        if record.active_claim is None or record.status not in {
            AutomationStatus.PAUSED,
            AutomationStatus.CANCEL_PENDING,
        }:
            raise ActivationUnavailableError("automation has no recoverable occurrence")
        return RuntimeOpenHandoffV1(
            automation_id=automation_id,
            automation_revision=record.active_claim.automation_revision,
            occurrence_id=record.active_claim.occurrence_id,
            checkpoint_identity=record.active_claim.checkpoint_identity,
            definition_digest=record.active_claim.definition_digest,
        )

    def preview_purge(self, automation_id: str) -> PurgePreviewV1:
        record = _find_record(self._controller, automation_id)
        if record.status is not AutomationStatus.CANCELED or record.active_claim is not None:
            raise ActivationUnavailableError("only a fully terminal automation can be purged")
        if any(
            item.status
            in {
                OccurrenceControlStatus.NEEDS_HUMAN,
                OccurrenceControlStatus.START_OUTCOME_UNKNOWN,
                OccurrenceControlStatus.MODEL_OUTCOME_UNKNOWN,
                OccurrenceControlStatus.EFFECT_OUTCOME_UNKNOWN,
                OccurrenceControlStatus.CLEANUP_UNKNOWN,
            }
            for item in record.terminal_history
        ):
            raise ActivationUnavailableError("automation still has unresolved occurrence state")
        definition = record.definition
        assert definition is not None
        objects = self._workspace_repository.owned_objects(automation_id)
        checkpoint_count = sum(
            item.kind is PurgeObjectKind.RUNTIME_CHECKPOINT for item in objects
        )
        manifest = PurgeOwnershipManifestV1(
            automation_id=automation_id,
            automation_revision=definition.body.revision,
            occurrence_count=record.terminal_occurrence_count,
            checkpoint_count=checkpoint_count,
            objects=objects,
        )
        external_count = sum(
            item.kind is PurgeObjectKind.GOVERNED_EXTERNAL_REFERENCE
            for item in objects
        )
        return PurgePreviewV1(
            automation_id=automation_id,
            automation_revision=definition.body.revision,
            occurrence_count=record.terminal_occurrence_count,
            checkpoint_count=checkpoint_count,
            owned_object_count=len(objects) - external_count,
            external_reference_count=external_count,
            preview_digest=manifest.manifest_digest,
            warnings=(
                "Purge permanently removes 019-owned snapshots, workspaces, diffs, "
                "artifacts and checkpoints.",
                "Governed external artifacts are only unlinked; detailed results and "
                "evidence are lost.",
                "The irreversible confirmation is bound to this exact ownership manifest.",
            ),
        )

    def confirm_purge(
        self,
        automation_id: str,
        *,
        preview_digest: str,
        expected_snapshot_token: str,
        next_snapshot_token: str,
    ) -> ManagementResultV1:
        preview = self.preview_purge(automation_id)
        if preview.preview_digest != preview_digest:
            raise PreviewConflictError("purge confirmation does not match current ownership")
        record = _find_record(self._controller, automation_id)
        definition = record.definition
        assert definition is not None
        manifest = PurgeOwnershipManifestV1(
            automation_id=automation_id,
            automation_revision=definition.body.revision,
            occurrence_count=record.terminal_occurrence_count,
            checkpoint_count=preview.checkpoint_count,
            objects=self._workspace_repository.owned_objects(automation_id),
        )
        result = self._controller.handle(
            BeginPurge(
                expected_snapshot_token=expected_snapshot_token,
                next_snapshot_token=next_snapshot_token,
                automation_id=automation_id,
                manifest=manifest,
                preview_digest=preview_digest,
            )
        )
        return _management_result("purge_pending", result.snapshot, automation_id)

    def pause(
        self,
        automation_id: str,
        *,
        expected_snapshot_token: str,
        next_snapshot_token: str,
    ) -> ManagementResultV1:
        result = self._controller.handle(
            PauseAutomation(expected_snapshot_token, next_snapshot_token, automation_id)
        )
        return _management_result("paused", result.snapshot, automation_id)

    def resume(
        self,
        automation_id: str,
        *,
        expected_snapshot_token: str,
        next_snapshot_token: str,
    ) -> ManagementResultV1:
        result = self._controller.handle(
            ResumeAutomation(expected_snapshot_token, next_snapshot_token, automation_id)
        )
        return _management_result("active", result.snapshot, automation_id)

    def cancel(
        self,
        automation_id: str,
        *,
        expected_snapshot_token: str,
        next_snapshot_token: str,
    ) -> ManagementResultV1:
        result = self._controller.handle(
            CancelAutomation(expected_snapshot_token, next_snapshot_token, automation_id)
        )
        record = next(
            item for item in result.snapshot.records if item.automation_id == automation_id
        )
        return _management_result(record.status.value, result.snapshot, automation_id)

    def _require_qualifications(self, body: AutomationDefinitionBodyV1) -> None:
        if not self._qualifications.provider_ready:
            raise ActivationUnavailableError("provider qualification is unavailable")
        if body.budgets.sandbox_commands > 0 and not self._qualifications.sandbox_qualified:
            raise ActivationUnavailableError("sandbox qualification is unavailable")
        if body.budgets.browser_actions > 0 and not self._qualifications.browser_qualified:
            raise ActivationUnavailableError("browser qualification is unavailable")
        if not self._qualifications.wake_qualified:
            raise ActivationUnavailableError("wake qualification is unavailable")


def _preview_sections(body: AutomationDefinitionBodyV1) -> tuple[PreviewSectionV1, ...]:
    capabilities = []
    if body.budgets.sandbox_commands:
        capabilities.append("sandbox_confined")
    if body.budgets.browser_actions:
        capabilities.append("browser_public_observe")
    data_classes = ["task", "source_snapshot"]
    if body.budgets.sandbox_commands:
        data_classes.append("command_output")
    if body.budgets.browser_actions:
        data_classes.append("public_browser_content")
    return (
        PreviewSectionV1(
            "task_schedule_cancel",
            (
                f"task: {body.task_text}",
                f"schedule: {body.schedule.kind.value} at {body.schedule.anchor_utc}",
                f"expiry: {body.expires_at_utc}",
                "cancel: first-agent-schedule cancel <automation-id>",
            ),
        ),
        PreviewSectionV1(
            "isolated_workspace",
            (
                f"source binding: {body.source_workspace_binding_digest}",
                f"immutable snapshot: {body.source_snapshot_digest}",
                "writes stay in a fresh 019-owned occurrence workspace",
            ),
        ),
        PreviewSectionV1(
            "unattended_and_prohibited",
            (
                f"unattended: {','.join(capabilities) or 'none'}",
                "prohibited: host writes, site-bound browser, commit/disclose, self-management",
                "human approval pauses this automation",
            ),
        ),
        PreviewSectionV1(
            "provider_and_data",
            (
                f"provider descriptor: {body.provider_descriptor_digest}",
                f"trust profile: {body.trust_profile_digest}",
                f"disclosure: {body.provider_disclosure_request_digest}",
                f"data classes: {','.join(data_classes)}",
            ),
        ),
        PreviewSectionV1(
            "origins_network_and_budgets",
            (
                f"browser origin policy: {body.browser_origin_policy_digest or 'none'}",
                "sandbox network: off",
                f"deadline seconds: {body.budgets.occurrence_deadline_seconds}",
                f"calls: model={body.budgets.model_calls}, tool={body.budgets.tool_calls}",
            ),
        ),
        PreviewSectionV1(
            "credential_purpose",
            (
                "credential purpose: provider authentication only",
                f"environment name: {body.credential_environment_name or 'none'}",
                "credential value is never persisted or rendered",
            ),
        ),
        PreviewSectionV1(
            "wake_and_recovery",
            (
                f"wake policy: {body.wake_adapter_policy_digest}",
                "wake adapter must qualify and match exactly",
                "unknown outcomes pause and require owner recovery",
            ),
        ),
    )


def _find_record(controller: AutomationController, automation_id: str):  # noqa: ANN202
    record = next(
        (item for item in controller.snapshot().records if item.automation_id == automation_id),
        None,
    )
    if record is None:
        raise ActivationUnavailableError("automation not found")
    return record


def _list_item(record) -> AutomationListItemV1:  # noqa: ANN001
    body = record.definition.body if record.definition is not None else record.draft_body
    if body is None:
        assert record.purge_manifest is not None
        return AutomationListItemV1(
            automation_id=record.automation_id,
            label="purge pending",
            revision=record.purge_manifest.automation_revision,
            status=record.status,
            terminal_occurrence_count=record.terminal_occurrence_count,
        )
    return AutomationListItemV1(
        automation_id=record.automation_id,
        label=body.label,
        revision=body.revision,
        status=record.status,
        terminal_occurrence_count=record.terminal_occurrence_count,
    )


def _management_result(code, snapshot, automation_id) -> ManagementResultV1:  # noqa: ANN001
    record = next(item for item in snapshot.records if item.automation_id == automation_id)
    return ManagementResultV1(code, snapshot.snapshot_token, record.status)


def _next_actions(status: AutomationStatus, has_active_claim: bool) -> tuple[str, ...]:
    if status is AutomationStatus.PROPOSAL:
        return ("preview",)
    if status is AutomationStatus.ACTIVE:
        return ("pause", "cancel", "update")
    if status in {AutomationStatus.PAUSED, AutomationStatus.CANCEL_PENDING}:
        return ("open",) if has_active_claim else ("resume", "cancel")
    if status is AutomationStatus.CANCELED:
        return ("preview_purge",)
    if status is AutomationStatus.PURGE_PENDING:
        return ("reconcile_purge",)
    return ()


def _require_digest(value: object, field: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be bare hex64")
