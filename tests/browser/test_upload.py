"""018 Task 7：workspace upload snapshot 与 one-shot staging。"""

import hashlib
import os
from datetime import datetime

import pytest

from agent.browser.action_policy import BrowserActionPolicy
from agent.browser.contracts import (
    BrowserActionKind,
    BrowserActionOutcome,
    BrowserActionReceiptV1,
    BrowserActionV1,
    BrowserCleanupOutcome,
    BrowserCleanupReceiptV1,
    BrowserElementRefV1,
    BrowserHandleV1,
    BrowserMode,
    BrowserObservationV1,
    BrowserSessionSpecV1,
)
from agent.browser.playwright_adapter import PlaywrightBrowserEnvironment
from agent.browser.profile_store import BrowserProfileStore
from agent.browser.quarantine import (
    UPLOAD_MAX_BYTES,
    BrowserQuarantine,
    BrowserQuarantineError,
)
from agent.browser.session_store import (
    BrowserSessionStore,
    SessionPhase,
)
from agent.browser.tools import build_browser_tool_registrations
from agent.browser.url_policy import browser_site_policy_digest
from agent.runtime.contracts import (
    ApprovalGrant,
    ApprovalRequired,
    BrowserAuthorityLeaseV1,
    ExecutionIntent,
    ToolCall,
    ToolPrepareContext,
)
from agent.runtime.tools import IntentConflictError, KernelToolRuntime
from tests.browser.fakes import FakeResolver, Journal, make_fake_factory
from tests.browser.profile_probe import DeterministicProcessIdentityProbe


def test_upload_snapshot_then_stage_binds_exact_digest_and_is_one_shot(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    payload = b"approved upload"
    (workspace / "report.txt").write_bytes(payload)
    quarantine = BrowserQuarantine(tmp_path / "state" / "browser-quarantine")
    digest = hashlib.sha256(payload).hexdigest()

    snapshot = quarantine.inspect_upload(
        workspace,
        "report.txt",
        expected_sha256=digest,
    )
    staged = quarantine.stage_upload(
        snapshot,
        session_ref="session-0123456789abcdef",
        action_digest="a" * 64,
    )

    assert staged.sha256 == digest
    assert staged.byte_size == len(payload)
    assert staged.path.read_bytes() == payload
    assert not staged.path.is_relative_to(workspace)
    quarantine.delete_staging(staged)
    assert not staged.path.exists()
    with pytest.raises(BrowserQuarantineError, match="staging is unavailable"):
        quarantine.delete_staging(staged)


@pytest.mark.parametrize(
    "path_factory",
    [
        pytest.param(lambda root: "/etc/passwd", id="absolute"),
        pytest.param(lambda root: "../outside", id="traversal"),
        pytest.param(lambda root: ".env", id="sensitive"),
        pytest.param(lambda root: "private/value.txt", id="private"),
        pytest.param(lambda root: "runtime/state.json", id="runtime"),
    ],
)
def test_upload_rejects_paths_outside_closed_workspace_boundary(tmp_path, path_factory):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "private").mkdir()
    (workspace / "private" / "value.txt").write_text("x")
    (workspace / "runtime").mkdir()
    (workspace / "runtime" / "state.json").write_text("x")
    quarantine = BrowserQuarantine(tmp_path / "quarantine")
    with pytest.raises(BrowserQuarantineError):
        quarantine.inspect_upload(
            workspace,
            path_factory(workspace),
            expected_sha256="0" * 64,
        )


def test_upload_rejects_symlink_directory_device_oversize_and_drift(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    file = workspace / "report.txt"
    file.write_bytes(b"before")
    link = workspace / "link.txt"
    link.symlink_to(file)
    quarantine = BrowserQuarantine(tmp_path / "quarantine")

    with pytest.raises(BrowserQuarantineError):
        quarantine.inspect_upload(workspace, "link.txt", expected_sha256="0" * 64)
    with pytest.raises(BrowserQuarantineError):
        quarantine.inspect_upload(workspace, ".", expected_sha256="0" * 64)

    oversized = workspace / "oversized.bin"
    with oversized.open("wb") as stream:
        stream.truncate(UPLOAD_MAX_BYTES + 1)
    with pytest.raises(BrowserQuarantineError, match="upload exceeds"):
        quarantine.inspect_upload(workspace, "oversized.bin", expected_sha256="0" * 64)

    digest = hashlib.sha256(b"before").hexdigest()
    snapshot = quarantine.inspect_upload(workspace, "report.txt", expected_sha256=digest)
    file.write_bytes(b"after")
    with pytest.raises(BrowserQuarantineError, match="upload source changed"):
        quarantine.stage_upload(
            snapshot,
            session_ref="session-0123456789abcdef",
            action_digest="a" * 64,
        )


class UploadRecordingEnvironment:
    def __init__(self, quarantine: BrowserQuarantine) -> None:
        self.quarantine = quarantine
        self.uploaded: list[bytes] = []

    def open(self, spec):
        return BrowserHandleV1(
            session_ref="session-0123456789abcdef",
            mode=spec.mode,
            authority_digest=spec.identity_digest,
        )

    def observe(self, handle):
        return BrowserObservationV1(
            session_ref=handle.session_ref,
            page_id=handle.session_ref,
            frame_id="main",
            navigation_revision=1,
            browser_revision="b" * 64,
            profile_revision=1,
            canonical_url="https://site.example.test/upload",
            canonical_origin="https://site.example.test",
            frame_tree_digest="f" * 64,
            aria_projection="input Upload",
            element_refs=(
                BrowserElementRefV1(
                    ref="upload-1",
                    role="textbox",
                    name="Upload",
                    input_type="file",
                ),
            ),
            node_count=1,
            byte_size=12,
            truncated=False,
            observed_at=datetime.fromisoformat(
                "2026-08-28T10:00:00+00:00"
            ).timestamp(),
        )

    def execute(
        self,
        handle,
        action,
        *,
        binding=None,
        upload_staging=None,
    ):
        del handle, binding
        assert upload_staging is not None
        upload_path = self.quarantine.resolve_staging(upload_staging)
        self.uploaded.append(upload_path.read_bytes())
        return BrowserActionReceiptV1(
            action_digest=action.identity_digest,
            pre_observation_digest=action.observation_digest,
            post_observation_digest="2" * 64,
            outcome=BrowserActionOutcome.EFFECT_APPLIED,
        )

    def close(self, handle):
        return BrowserCleanupReceiptV1(
            session_ref=handle.session_ref,
            outcome=BrowserCleanupOutcome.CLEANED,
        )


def _context(*, leases=()):
    return ToolPrepareContext(
        conversation_id="conversation-1",
        run_id="run-1",
        state_revision=7,
        approval_basis_revision=7,
        goal_id="goal-1",
        goal_revision=1,
        workspace_identity_digest="w" * 64,
        browser_leases=tuple(leases),
    )


def _lease(request):
    candidate = request.browser_action_candidate
    assert candidate is not None
    return BrowserAuthorityLeaseV1.create(
        lease_id="browser-lease-upload",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        session_ref=candidate.session_ref,
        browser_identity_digest=candidate.browser_identity_digest,
        profile_ref=candidate.profile_ref,
        profile_revision=candidate.profile_revision,
        allowed_origins=candidate.allowed_origins,
        mode=candidate.mode,
        page_id=candidate.page_id,
        frame_id=candidate.frame_id,
        observation_digest=candidate.observation_digest,
        action_digest=candidate.action_digest,
        consequence=candidate.consequence,
        approved_request_identity=request.request_id,
        issued_at=candidate.issued_at,
        expires_at=candidate.expires_at,
    )


@pytest.mark.parametrize(
    "mutation_stage",
    [
        pytest.param("none", id="stable"),
        pytest.param("before-prepare", id="same-content-new-inode-before-prepare"),
        pytest.param("before-invoke", id="same-content-new-inode-before-invoke"),
    ],
)
def test_upload_executes_once_only_after_exact_lease_and_removes_staging(
    tmp_path, mutation_stage,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    payload = b"approved upload"
    (workspace / "report.txt").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    quarantine = BrowserQuarantine(tmp_path / "quarantine")
    environment = UploadRecordingEnvironment(quarantine)
    profiles = BrowserProfileStore(
        root=tmp_path / "profiles",
        process_probe=DeterministicProcessIdentityProbe(),
    )
    profile = profiles.create(
        site_policy_digest=browser_site_policy_digest(
            ("https://site.example.test",)
        ),
        account_label="test account",
        browser_identity_digest="b" * 64,
    )
    session_store = BrowserSessionStore(root=tmp_path / "sessions")
    runtime = KernelToolRuntime(
        build_browser_tool_registrations(
            environment=environment,
            profile_store=profiles,
            session_store=session_store,
            browser_identity_digest="b" * 64,
            clock=lambda: "2026-08-28T10:00:00+00:00",
            monotonic_clock=lambda: 1000.0,
            workspace=workspace,
            quarantine=quarantine,
        ),
        clock=lambda: "2026-08-28T10:00:00+00:00",
    )
    open_call = ToolCall(
        "open-1",
        "browser_open",
        {
            "mode": BrowserMode.SITE_BOUND_INTERACTIVE.value,
            "profile_ref": profile.profile_id,
            "profile_revision": profile.revision,
            "allowed_origins": ["https://site.example.test"],
        },
    )
    open_request = runtime.prepare(open_call, _context())
    opened = runtime.invoke(
        runtime.prepare(
            open_call,
            _context(),
            approval=ApprovalGrant(
                request_id=open_request.request.request_id,
                binding_digest=open_request.request.binding_digest,
                approval_basis_revision=7,
            ),
        )
    )
    session_ref = opened.metadata["session_ref"]
    observed = runtime.invoke(
        runtime.prepare(
            ToolCall("observe-1", "browser_observe", {"session_ref": session_ref}),
            _context(),
        )
    )
    call = ToolCall(
        "upload-1",
        "browser_act",
        {
            "session_ref": session_ref,
            "kind": "upload",
            "observation_digest": observed.metadata["observation_digest"],
            "page_id": session_ref,
            "frame_id": "main",
            "target_ref": "upload-1",
            "params": {
                "path": "report.txt",
                "sha256": digest,
                "purpose": "attach the approved report",
            },
        },
    )

    approval = runtime.prepare(call, _context())
    assert isinstance(approval, ApprovalRequired)
    assert environment.uploaded == []
    assert "report.txt" in approval.request.preview
    if mutation_stage == "before-prepare":
        replacement = workspace / "replacement.txt"
        replacement.write_bytes(payload)
        os.replace(replacement, workspace / "report.txt")
        rejected = runtime.prepare(call, _context(leases=(_lease(approval.request),)))
        assert rejected.executed is False
        assert rejected.is_error is True
        assert rejected.metadata["code"] == "binding_failure"
        assert environment.uploaded == []
        assert list((quarantine.root / "staging").iterdir()) == []
        return
    prepared = runtime.prepare(call, _context(leases=(_lease(approval.request),)))
    assert isinstance(prepared, ExecutionIntent)
    if mutation_stage == "before-invoke":
        replacement = workspace / "replacement.txt"
        replacement.write_bytes(payload)
        os.replace(replacement, workspace / "report.txt")
        with pytest.raises(IntentConflictError):
            runtime.invoke(prepared)
        record = session_store.load(session_ref)
        assert record.phase is SessionPhase.ACTIVE
        assert environment.uploaded == []
        assert list((quarantine.root / "staging").iterdir()) == []
        return
    result = runtime.invoke(prepared)
    assert result.executed is True
    assert environment.uploaded == [payload]
    assert list((quarantine.root / "staging").iterdir()) == []


def test_playwright_upload_receives_only_one_shot_staging_path(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    payload = b"approved payload"
    (workspace / "report.txt").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    quarantine = BrowserQuarantine(tmp_path / "quarantine")
    snapshot = quarantine.inspect_upload(
        workspace, "report.txt", expected_sha256=digest
    )
    staging = quarantine.stage_upload(
        snapshot,
        session_ref="session-0123456789abcdef",
        action_digest="a" * 64,
    )
    profile_root = tmp_path / "profiles-real"
    profile_root.mkdir(mode=0o700)
    journal = Journal()
    playwright, factory = make_fake_factory(journal)
    environment = PlaywrightBrowserEnvironment(
        playwright_factory=factory,
        resolver=FakeResolver({"site.example.test": ("93.184.216.34",)}),
        profile_root=profile_root,
        quarantine=quarantine,
    )
    spec = BrowserSessionSpecV1.site_bound(
        goal_id="goal-1",
        goal_revision=1,
        profile_ref="profile-0123456789abcdef",
        allowed_origins=("https://site.example.test",),
        action_budget=8,
        profile_revision=1,
        browser_identity_digest="a" * 64,
        expiry_monotonic=1e18,
    )
    handle = environment.open(spec)
    playwright.last_page.nodes = [
        {
            "ref": "upload-1",
            "role": "textbox",
            "name": "Upload",
            "input_type": "file",
        }
    ]
    observation = environment.observe(handle)
    action = BrowserActionV1(
        kind=BrowserActionKind.UPLOAD,
        observation_digest=observation.observation_digest,
        page_id=observation.page_id,
        frame_id=observation.frame_id,
        target_ref="upload-1",
        params={"path": "report.txt", "sha256": digest, "purpose": "attach report"},
    )
    binding = BrowserActionPolicy.prepare(observation, action)

    receipt = environment.execute(
        handle,
        action,
        binding=binding,
        upload_staging=staging.capability,
    )

    assert receipt.executed is True
    calls = journal.calls("page", "set_input_files")
    assert len(calls) == 1
    assert calls[0][2]["path"] == str(staging.path)
    quarantine.delete_staging(staging)
