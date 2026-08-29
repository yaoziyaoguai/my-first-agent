"""018 Task 7：download receipt 不泄漏内部 quarantine path。"""

from dataclasses import asdict
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
    BrowserObservationV1,
    BrowserSessionSpecV1,
)
from agent.browser.playwright_adapter import (
    BrowserUnavailableError,
    PlaywrightBrowserEnvironment,
)
from agent.browser.profile_store import BrowserProfileStore
from agent.browser.quarantine import BrowserQuarantine, BrowserQuarantineError
from agent.browser.session_store import BrowserSessionStore
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
from agent.runtime.tools import KernelToolRuntime
from tests.browser.fakes import FakeDownload, FakeResolver, Journal, make_fake_factory
from tests.browser.profile_probe import DeterministicProcessIdentityProbe


def test_download_receipt_contains_only_bounded_identity_and_metadata(tmp_path):
    source = tmp_path / "download.tmp"
    source.write_bytes(b"payload")
    quarantine = BrowserQuarantine(tmp_path / "browser-state" / "quarantine")
    receipt = quarantine.store(
        source,
        session_ref="session-0123456789abcdef",
        action_digest="a" * 64,
        browser_identity_digest="b" * 64,
        source_origin="https://site.example.test",
        suggested_name="invoice.pdf",
        mime_type="application/pdf",
    )

    projected = asdict(receipt)
    assert set(projected) == {
        "quarantine_id",
        "session_ref",
        "action_digest",
        "browser_identity_digest",
        "source_origin",
        "suggested_name_digest",
        "normalized_name",
        "mime_type",
        "byte_size",
        "sha256",
        "receipt_digest",
    }
    assert str(tmp_path) not in repr(projected)


class DownloadRecordingEnvironment:
    def __init__(self, source, quarantine: BrowserQuarantine) -> None:
        self.source = source
        self.quarantine = quarantine
        self.download_count = 0

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
            canonical_url="https://site.example.test/download",
            canonical_origin="https://site.example.test",
            frame_tree_digest="f" * 64,
            aria_projection="button Download",
            element_refs=(
                BrowserElementRefV1(ref="download-1", role="button", name="Download"),
            ),
            node_count=1,
            byte_size=15,
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
        del upload_staging, binding
        self.download_count += 1
        download = self.quarantine.store(
            self.source,
            session_ref=handle.session_ref,
            action_digest=action.identity_digest,
            browser_identity_digest="b" * 64,
            source_origin="https://site.example.test",
            suggested_name="invoice.pdf",
            mime_type="application/pdf",
        )
        return BrowserActionReceiptV1(
            action_digest=action.identity_digest,
            pre_observation_digest=action.observation_digest,
            post_observation_digest="2" * 64,
            outcome=BrowserActionOutcome.EFFECT_APPLIED,
            download=download,
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
    return BrowserAuthorityLeaseV1.create(
        lease_id="browser-lease-download",
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


def test_download_requires_exact_lease_and_returns_quarantine_receipt_only(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "download.tmp"
    source.write_bytes(b"download payload")
    quarantine = BrowserQuarantine(tmp_path / "quarantine")
    environment = DownloadRecordingEnvironment(source, quarantine)
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
    runtime = KernelToolRuntime(
        build_browser_tool_registrations(
            environment=environment,
            profile_store=profiles,
            session_store=BrowserSessionStore(root=tmp_path / "sessions"),
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
            "mode": "site_bound_interactive",
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
        "download-1",
        "browser_act",
        {
            "session_ref": session_ref,
            "kind": "download",
            "observation_digest": observed.metadata["observation_digest"],
            "page_id": session_ref,
            "frame_id": "main",
            "target_ref": "download-1",
        },
    )
    approval = runtime.prepare(call, _context())
    assert isinstance(approval, ApprovalRequired)
    assert environment.download_count == 0
    prepared = runtime.prepare(call, _context(leases=(_lease(approval.request),)))
    assert isinstance(prepared, ExecutionIntent)
    result = runtime.invoke(prepared)
    assert environment.download_count == 1
    assert result.metadata["browser_receipt_kind"] == "browser_action_v1"
    assert result.metadata["download_receipt_kind"] == "quarantined_download_v1"
    assert "path" not in result.metadata
    assert not any(workspace.iterdir())


def test_playwright_download_saves_only_to_quarantine(tmp_path):
    profile_root = tmp_path / "profiles-real"
    profile_root.mkdir(mode=0o700)
    quarantine = BrowserQuarantine(tmp_path / "quarantine")
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
    playwright.last_page.download_payload = b"download payload"
    playwright.last_page.download_suggested_name = "../../invoice.pdf"
    playwright.last_page.nodes = [
        {"ref": "download-1", "role": "button", "name": "Download"}
    ]
    observation = environment.observe(handle)
    action = BrowserActionV1(
        kind=BrowserActionKind.DOWNLOAD,
        observation_digest=observation.observation_digest,
        page_id=observation.page_id,
        frame_id=observation.frame_id,
        target_ref="download-1",
    )
    binding = BrowserActionPolicy.prepare(observation, action)

    receipt = environment.execute(
        handle,
        action,
        binding=binding,
    )

    assert receipt.download is not None
    assert receipt.download.byte_size == len(b"download payload")
    assert quarantine.inspect(receipt.download) == receipt.download
    assert journal.calls("download", "save_as")


def test_playwright_cancels_download_without_current_approved_action(tmp_path):
    profile_root = tmp_path / "profiles-real"
    profile_root.mkdir(mode=0o700)
    quarantine = BrowserQuarantine(tmp_path / "quarantine")
    journal = Journal()
    playwright, factory = make_fake_factory(journal)
    environment = PlaywrightBrowserEnvironment(
        playwright_factory=factory,
        resolver=FakeResolver({"site.example.test": ("93.184.216.34",)}),
        profile_root=profile_root,
        quarantine=quarantine,
    )
    handle = environment.open(
        BrowserSessionSpecV1.site_bound(
            goal_id="goal-1",
            goal_revision=1,
            profile_ref="profile-0123456789abcdef",
            allowed_origins=("https://site.example.test",),
            action_budget=8,
            profile_revision=1,
            browser_identity_digest="a" * 64,
            expiry_monotonic=1e18,
        )
    )
    page = playwright.last_page
    page._expected_download = FakeDownload(page)

    page._emit_download()

    assert len(journal.calls("download", "cancel")) == 1
    assert journal.calls("download", "save_as") == []
    environment.close(handle)


def test_download_quarantine_failure_after_click_is_unknown_and_poisons_session(
    tmp_path, monkeypatch,
):
    profile_root = tmp_path / "profiles-real"
    profile_root.mkdir(mode=0o700)
    quarantine = BrowserQuarantine(tmp_path / "quarantine")
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
        {"ref": "download-1", "role": "button", "name": "Download"}
    ]
    observation = environment.observe(handle)
    action = BrowserActionV1(
        kind=BrowserActionKind.DOWNLOAD,
        observation_digest=observation.observation_digest,
        page_id=observation.page_id,
        frame_id=observation.frame_id,
        target_ref="download-1",
    )
    binding = BrowserActionPolicy.prepare(observation, action)

    def fail_after_download(*args, **kwargs):
        del args, kwargs
        raise BrowserQuarantineError("quarantine write failed")

    monkeypatch.setattr(quarantine, "store", fail_after_download)
    with pytest.raises(BrowserQuarantineError, match="quarantine write failed"):
        environment.execute(
            handle,
            action,
            binding=binding,
        )

    assert len(journal.calls("page", "click")) == 1
    assert len(journal.calls("download", "save_as")) == 1
    with pytest.raises(BrowserUnavailableError, match="browser_session_unusable"):
        environment.observe(handle)
