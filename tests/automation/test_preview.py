from __future__ import annotations

from dataclasses import replace

import pytest

from agent.automation.management import (
    ActivationQualificationsV1,
    ActivationUnavailableError,
    PreviewConflictError,
)
from agent.automation.workspace import VirtualNodeKind, VirtualSourceNodeV1

from .test_management import _service


def test_approval_rejects_a_preview_after_source_drift() -> None:
    service, _, workspace, body = _service()
    service.create(
        body,
        expected_snapshot_token="snapshot-token-0000",
        next_snapshot_token="snapshot-token-0001",
    )
    preview = service.preview(body.automation_id)
    workspace.replace_source_nodes(
        "source:workspace",
        (
            VirtualSourceNodeV1(
                relative_path="report.md",
                kind=VirtualNodeKind.FILE,
                size_bytes=10,
                content_digest="b" * 64,
            ),
        ),
    )

    with pytest.raises(PreviewConflictError):
        service.approve(
            body.automation_id,
            preview_digest=preview.preview_digest,
            expected_snapshot_token="snapshot-token-0001",
            next_snapshot_token="snapshot-token-0002",
        )


def test_stale_preview_cannot_approve_a_newer_draft() -> None:
    service, _, _, body = _service()
    service.create(
        body,
        expected_snapshot_token="snapshot-token-0000",
        next_snapshot_token="snapshot-token-0001",
    )
    initial = service.preview(body.automation_id)
    service.approve(
        body.automation_id,
        preview_digest=initial.preview_digest,
        expected_snapshot_token="snapshot-token-0001",
        next_snapshot_token="snapshot-token-0002",
    )
    old = service.preview(body.automation_id)
    changed = replace(
        body,
        revision=2,
        task_text="Changed task",
        definition_body_digest="",
    )
    service.update(
        body.automation_id,
        changed,
        expected_snapshot_token="snapshot-token-0002",
        next_snapshot_token="snapshot-token-0003",
    )

    with pytest.raises(PreviewConflictError):
        service.approve(
            body.automation_id,
            preview_digest=old.preview_digest,
            expected_snapshot_token="snapshot-token-0003",
            next_snapshot_token="snapshot-token-0004",
        )


def test_requested_capability_requires_its_qualification() -> None:
    service, _, _, body = _service(
        qualifications=ActivationQualificationsV1(
            provider_ready=True,
            sandbox_qualified=True,
            browser_qualified=False,
            wake_qualified=True,
            qualification_digest="b" * 64,
        )
    )
    service.create(
        body,
        expected_snapshot_token="snapshot-token-0000",
        next_snapshot_token="snapshot-token-0001",
    )

    with pytest.raises(ActivationUnavailableError, match="browser"):
        service.preview(body.automation_id)


def test_preview_schema_has_no_secret_or_absolute_path_field() -> None:
    service, _, _, body = _service()
    service.create(
        body,
        expected_snapshot_token="snapshot-token-0000",
        next_snapshot_token="snapshot-token-0001",
    )
    preview = service.preview(body.automation_id)

    assert "credential_value" not in preview.__dataclass_fields__
    assert "workspace_path" not in preview.__dataclass_fields__
    assert "state_path" not in preview.__dataclass_fields__
