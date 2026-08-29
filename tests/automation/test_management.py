from __future__ import annotations

from dataclasses import replace

from agent.automation.controller import AutomationController
from agent.automation.management import (
    ActivationQualificationsV1,
    AutomationManagementService,
)
from agent.automation.store import DeterministicAutomationRepository
from agent.automation.wake import DeterministicWakeAdapter, WakeAdapter
from agent.automation.workspace import (
    DeterministicOwnedWorkspaceRepository,
    SourceBindingV1,
    VirtualNodeKind,
    VirtualSourceNodeV1,
    WorkspaceBoundsV1,
)

from .test_contracts import _body
from .test_controller import _empty_snapshot


def _service(
    *,
    wake_adapter: WakeAdapter | None = None,
    qualifications: ActivationQualificationsV1 | None = None,
):
    binding = SourceBindingV1(
        binding_id="source:workspace",
        root_identity_digest="1" * 64,
        excluded_components=("private", "runtime"),
    )
    workspace = DeterministicOwnedWorkspaceRepository(
        {
            binding: (
                VirtualSourceNodeV1(
                    relative_path="report.md",
                    kind=VirtualNodeKind.FILE,
                    size_bytes=10,
                    content_digest="2" * 64,
                ),
            )
        }
    )
    manifest = workspace.scan_source(binding, WorkspaceBoundsV1())
    body = replace(
        _body(),
        source_snapshot_digest=manifest.manifest_digest,
        definition_body_digest="",
    )
    repository = DeterministicAutomationRepository(_empty_snapshot())
    service = AutomationManagementService(
        controller=AutomationController(repository),
        workspace_repository=workspace,
        wake_adapter=wake_adapter or DeterministicWakeAdapter(),
        source_bindings={body.source_workspace_binding_digest: binding},
        workspace_bounds=WorkspaceBoundsV1(),
        qualifications=qualifications
        or ActivationQualificationsV1(
            provider_ready=True,
            sandbox_qualified=True,
            browser_qualified=True,
            wake_qualified=True,
            qualification_digest="a" * 64,
        ),
    )
    return service, repository, workspace, body


def test_create_preview_and_approve_activate_one_exact_revision() -> None:
    service, repository, workspace, body = _service()
    created = service.create(
        body,
        expected_snapshot_token="snapshot-token-0000",
        next_snapshot_token="snapshot-token-0001",
    )
    assert created.code == "proposal"
    preview = service.preview(body.automation_id)
    assert tuple(section.title for section in preview.sections) == (
        "task_schedule_cancel",
        "isolated_workspace",
        "unattended_and_prohibited",
        "provider_and_data",
        "origins_network_and_budgets",
        "credential_purpose",
        "wake_and_recovery",
    )

    activated = service.approve(
        body.automation_id,
        preview_digest=preview.preview_digest,
        expected_snapshot_token="snapshot-token-0001",
        next_snapshot_token="snapshot-token-0002",
    )

    assert activated.code == "active"
    assert repository.load().records[0].definition is not None
    assert workspace.owned_object_count == 1


def test_list_and_show_are_bounded_owner_views() -> None:
    service, _, _, body = _service()
    service.create(
        body,
        expected_snapshot_token="snapshot-token-0000",
        next_snapshot_token="snapshot-token-0001",
    )

    assert service.list()[0].automation_id == body.automation_id
    detail = service.show(body.automation_id)
    assert detail.next_actions == ("preview",)
    assert not hasattr(detail, "credential_value")
    assert not hasattr(detail, "state_path")
