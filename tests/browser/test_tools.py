"""018 Task 6：五个 governed browser registrations 的 closed surface。"""

from dataclasses import fields
from datetime import datetime

import pytest

from agent.browser.contracts import (
    BrowserActionOutcome,
    BrowserActionReceiptV1,
    BrowserCleanupOutcome,
    BrowserCleanupReceiptV1,
    BrowserHandleV1,
    BrowserMode,
    BrowserObservationV1,
)
from agent.browser.ports import BrowserEnvironment, BrowserOpenNotStartedError
from agent.browser.profile_store import BrowserProfileStore, ProfileLockHeldError
from agent.browser.session_store import BrowserSessionStore, SessionRecovery
from agent.browser.tools import build_browser_tool_registrations
from agent.browser.url_policy import browser_site_policy_digest
from agent.runtime.contracts import (
    ApprovalGrant,
    ApprovalRequired,
    BrowserAuthorityLeaseV1,
    ExecutionAuthorityClass,
    ExecutionIntent,
    ToolCall,
    ToolPrepareContext,
    ToolResult,
)
from agent.runtime.tools import KernelToolRuntime
from tests.browser.profile_probe import DeterministicProcessIdentityProbe


def _profile_store(tmp_path) -> BrowserProfileStore:
    return BrowserProfileStore(
        root=tmp_path / "profiles",
        process_probe=DeterministicProcessIdentityProbe(),
    )


class NeverCalledEnvironment:
    def open(self, _spec):
        raise AssertionError("registration construction must not open a browser")

    def observe(self, _handle):
        raise AssertionError("registration construction must not observe a browser")

    def execute(self, _handle, _action, *, binding=None):
        raise AssertionError("registration construction must not execute a browser action")

    def close(self, _handle):
        raise AssertionError("registration construction must not close a browser")


class RecordingEnvironment:
    def __init__(self) -> None:
        self.opened = []
        self.observed = []
        self.executed = []
        self.closed = []
        self.profile_revision = None

    def open(self, spec):
        self.opened.append(spec)
        self.profile_revision = spec.profile_revision
        return BrowserHandleV1(
            session_ref="session-0123456789abcdef",
            mode=spec.mode,
            authority_digest=spec.identity_digest,
        )

    def observe(self, handle):
        self.observed.append(handle)
        return _observation(handle, profile_revision=self.profile_revision)

    def execute(self, handle, action, *, binding=None):
        self.executed.append((handle, action, binding))
        return BrowserActionReceiptV1(
            action_digest=action.identity_digest,
            pre_observation_digest=action.observation_digest,
            post_observation_digest="2" * 64,
            outcome=BrowserActionOutcome.EFFECT_APPLIED,
        )

    def close(self, handle):
        self.closed.append(handle)
        return BrowserCleanupReceiptV1(
            session_ref=handle.session_ref,
            outcome=BrowserCleanupOutcome.CLEANED,
        )


class UnknownActionEnvironment(RecordingEnvironment):
    def execute(self, handle, action, *, binding=None):
        self.executed.append((handle, action, binding))
        raise RuntimeError("injected browser unknown outcome")


class CleanupUnknownEnvironment(RecordingEnvironment):
    def close(self, handle):
        self.closed.append(handle)
        return BrowserCleanupReceiptV1(
            session_ref=handle.session_ref,
            outcome=BrowserCleanupOutcome.CLEANUP_UNKNOWN,
        )


class ForgedHandleEnvironment(RecordingEnvironment):
    def open(self, spec):
        self.opened.append(spec)
        return BrowserHandleV1(
            session_ref="session-0123456789abcdef",
            mode=spec.mode,
            authority_digest="f" * 64,
        )


class PrestartUnavailableEnvironment(RecordingEnvironment):
    def open(self, _spec):
        raise BrowserOpenNotStartedError("browser_binary_missing")


def _observation(handle, *, profile_revision):
    return BrowserObservationV1(
        session_ref=handle.session_ref,
        page_id=handle.session_ref,
        frame_id="main",
        navigation_revision=1,
        browser_revision="b" * 64,
        profile_revision=profile_revision,
        canonical_url="https://site.example.test/page",
        canonical_origin="https://site.example.test",
        frame_tree_digest="f" * 64,
        aria_projection="link Docs",
        element_refs=(),
        node_count=1,
        byte_size=9,
        truncated=False,
        observed_at=datetime.fromisoformat(
            "2026-08-28T10:00:00+00:00"
        ).timestamp(),
    )


def _registrations(tmp_path):
    return build_browser_tool_registrations(
        environment=NeverCalledEnvironment(),
        profile_store=_profile_store(tmp_path),
        session_store=BrowserSessionStore(root=tmp_path / "sessions"),
        browser_identity_digest="b" * 64,
        clock=lambda: "2026-08-28T10:00:00+00:00",
        monotonic_clock=lambda: 1000.0,
    )


def test_registration_surface_is_exact_and_browser_governed(tmp_path):
    registrations = _registrations(tmp_path)
    assert tuple(item.spec.name for item in registrations) == (
        "browser_open",
        "browser_observe",
        "browser_act",
        "browser_close",
        "browser_begin_takeover",
    )
    assert all(
        item.spec.execution_authority is ExecutionAuthorityClass.BROWSER_SESSION
        for item in registrations
    )
    assert all(item.spec.input_schema["additionalProperties"] is False for item in registrations)


def test_surface_exposes_no_raw_browser_or_host_escape(tmp_path):
    registrations = _registrations(tmp_path)
    forbidden = {
        "javascript",
        "script",
        "css",
        "xpath",
        "cdp",
        "launch_args",
        "executable_path",
        "host_path",
        "storage_state",
        "cookies",
        "headers",
    }
    for registration in registrations:
        properties = set(registration.spec.input_schema["properties"])
        assert properties.isdisjoint(forbidden), registration.spec.name
        if registration.spec.name == "browser_act":
            params = registration.spec.input_schema["properties"]["params"]
            assert params["additionalProperties"] is False
            assert set(params["properties"]).isdisjoint(forbidden)
        assert registration.spec.output_limit_chars <= 64_000

    port_parameters = BrowserEnvironment.execute.__annotations__
    assert "upload_path" not in port_parameters
    assert "quarantine" not in port_parameters
    assert "upload_staging" in port_parameters


def test_registration_closures_do_not_capture_runtime_owners(tmp_path):
    registrations = _registrations(tmp_path)
    forbidden_types = {"AgentRuntime", "ContextManager", "CheckpointStore", "ModelProvider"}
    for registration in registrations:
        closure = registration.func.__closure__ or ()
        captured_type_names = {type(cell.cell_contents).__name__ for cell in closure}
        assert captured_type_names.isdisjoint(forbidden_types), registration.spec.name
        # RegisteredTool 仍只暴露既有五个静态 seam，没有 browser 自建 loop。
        assert {item.name for item in fields(registration)} == {
            "spec",
            "func",
            "prepare_binding",
            "prepare_authority_binding",
            "policy",
            "exposure",
        }


def _context(*, browser_leases=()) -> ToolPrepareContext:
    return ToolPrepareContext(
        conversation_id="conversation-1",
        run_id="run-1",
        state_revision=7,
        approval_basis_revision=7,
        goal_id="goal-1",
        goal_revision=1,
        workspace_identity_digest="w" * 64,
        browser_leases=tuple(browser_leases),
    )


def test_public_read_open_observe_act_close_uses_one_governed_runtime(tmp_path):
    environment = RecordingEnvironment()
    registrations = build_browser_tool_registrations(
        environment=environment,
        profile_store=_profile_store(tmp_path),
        session_store=BrowserSessionStore(root=tmp_path / "sessions"),
        browser_identity_digest="b" * 64,
        clock=lambda: "2026-08-28T10:00:00+00:00",
        monotonic_clock=lambda: 1000.0,
    )
    runtime = KernelToolRuntime(registrations, clock=lambda: "2026-08-28T10:00:00+00:00")
    open_call = ToolCall(
        "open-1", "browser_open", {"mode": "public_read_ephemeral"}
    )
    approval = runtime.prepare(open_call, _context())
    assert isinstance(approval, ApprovalRequired)
    prepared_open = runtime.prepare(
        open_call,
        _context(),
        approval=ApprovalGrant(
            request_id=approval.request.request_id,
            binding_digest=approval.request.binding_digest,
            approval_basis_revision=7,
        ),
    )
    assert isinstance(prepared_open, ExecutionIntent)
    opened = runtime.invoke(prepared_open)
    assert isinstance(opened, ToolResult)
    assert opened.metadata["browser_result_kind"] == "browser_open"
    session_ref = opened.metadata["session_ref"]

    observe_call = ToolCall("observe-1", "browser_observe", {"session_ref": session_ref})
    prepared_observe = runtime.prepare(observe_call, _context())
    assert isinstance(prepared_observe, ExecutionIntent)
    observed = runtime.invoke(prepared_observe)
    assert observed.metadata["browser_result_kind"] == "browser_observe"
    observation_digest = observed.metadata["observation_digest"]

    act_call = ToolCall(
        "act-1",
        "browser_act",
        {
            "session_ref": session_ref,
            "kind": "navigate",
            "observation_digest": observation_digest,
            "page_id": session_ref,
            "frame_id": "main",
            "params": {"url": "https://site.example.test/docs"},
        },
    )
    prepared_act = runtime.prepare(act_call, _context())
    assert isinstance(prepared_act, ExecutionIntent)
    assert prepared_act.browser_lease is None  # OBSERVE consequence无需 effect lease。
    acted = runtime.invoke(prepared_act)
    assert acted.metadata["browser_receipt_kind"] == "browser_action_v1"

    close_call = ToolCall("close-1", "browser_close", {"session_ref": session_ref})
    prepared_close = runtime.prepare(close_call, _context())
    assert isinstance(prepared_close, ExecutionIntent)
    closed = runtime.invoke(prepared_close)
    assert closed.metadata["cleanup_outcome"] == "cleaned"
    assert len(environment.opened) == 1
    assert len(environment.observed) == 1
    assert len(environment.executed) == 1
    assert len(environment.closed) == 1


def test_unknown_action_can_cleanup_resource_without_erasing_recovery(tmp_path) -> None:
    environment = UnknownActionEnvironment()
    sessions = BrowserSessionStore(root=tmp_path / "sessions")
    runtime = KernelToolRuntime(
        build_browser_tool_registrations(
            environment=environment,
            profile_store=_profile_store(tmp_path),
            session_store=sessions,
            browser_identity_digest="b" * 64,
            clock=lambda: "2026-08-28T10:00:00+00:00",
            monotonic_clock=lambda: 1000.0,
        ),
        clock=lambda: "2026-08-28T10:00:00+00:00",
    )
    open_call = ToolCall("open-unknown", "browser_open", {"mode": "public_read_ephemeral"})
    approval = runtime.prepare(open_call, _context())
    opened = runtime.invoke(
        runtime.prepare(
            open_call,
            _context(),
            approval=ApprovalGrant(
                request_id=approval.request.request_id,
                binding_digest=approval.request.binding_digest,
                approval_basis_revision=7,
            ),
        )
    )
    session_ref = opened.metadata["session_ref"]
    observed = runtime.invoke(
        runtime.prepare(
            ToolCall("observe-unknown", "browser_observe", {"session_ref": session_ref}),
            _context(),
        )
    )
    action = ToolCall(
        "act-unknown",
        "browser_act",
        {
            "session_ref": session_ref,
            "kind": "navigate",
            "observation_digest": observed.metadata["observation_digest"],
            "page_id": session_ref,
            "frame_id": "main",
            "params": {"url": "https://site.example.test/unknown"},
        },
    )
    with pytest.raises(RuntimeError, match="unknown outcome"):
        runtime.invoke(runtime.prepare(action, _context()))

    close_call = ToolCall("close-unknown", "browser_close", {"session_ref": session_ref})
    closed = runtime.invoke(runtime.prepare(close_call, _context()))

    assert closed.is_error is True
    assert closed.metadata["cleanup_outcome"] == "cleaned"
    assert closed.metadata["session_recovery"] == "unknown_outcome"
    assert len(environment.closed) == 1
    loaded = sessions.load(session_ref)
    assert sessions.pending_recovery(loaded) is SessionRecovery.UNKNOWN_OUTCOME


def test_cleanup_unknown_keeps_site_profile_writer_quarantined(tmp_path) -> None:
    environment = CleanupUnknownEnvironment()
    profiles = _profile_store(tmp_path)
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
        ),
        clock=lambda: "2026-08-28T10:00:00+00:00",
    )
    open_call = ToolCall(
        "open-cleanup-unknown",
        "browser_open",
        {
            "mode": "site_bound_interactive",
            "profile_ref": profile.profile_id,
            "profile_revision": profile.revision,
            "allowed_origins": ["https://site.example.test"],
        },
    )
    request = runtime.prepare(open_call, _context())
    opened = runtime.invoke(
        runtime.prepare(
            open_call,
            _context(),
            approval=ApprovalGrant(
                request_id=request.request.request_id,
                binding_digest=request.request.binding_digest,
                approval_basis_revision=7,
            ),
        )
    )
    closed = runtime.invoke(
        runtime.prepare(
            ToolCall(
                "close-cleanup-unknown",
                "browser_close",
                {"session_ref": opened.metadata["session_ref"]},
            ),
            _context(),
        )
    )

    assert closed.is_error is True
    assert closed.metadata["cleanup_outcome"] == "cleanup_unknown"
    with pytest.raises(ProfileLockHeldError):
        _profile_store(tmp_path).acquire_writer(profile)


def test_forged_open_handle_is_closed_before_reporting_failure(tmp_path) -> None:
    environment = ForgedHandleEnvironment()
    runtime = KernelToolRuntime(
        build_browser_tool_registrations(
            environment=environment,
            profile_store=_profile_store(tmp_path),
            session_store=BrowserSessionStore(root=tmp_path / "sessions"),
            browser_identity_digest="b" * 64,
            clock=lambda: "2026-08-28T10:00:00+00:00",
            monotonic_clock=lambda: 1000.0,
        ),
        clock=lambda: "2026-08-28T10:00:00+00:00",
    )
    call = ToolCall(
        "open-forged", "browser_open", {"mode": "public_read_ephemeral"}
    )
    request = runtime.prepare(call, _context())
    with pytest.raises(RuntimeError, match="cleanup confirmed"):
        runtime.invoke(
            runtime.prepare(
                call,
                _context(),
                approval=ApprovalGrant(
                    request_id=request.request.request_id,
                    binding_digest=request.request.binding_digest,
                    approval_basis_revision=7,
                ),
            )
        )
    assert len(environment.closed) == 1


def test_prestart_open_failure_releases_profile_writer(tmp_path) -> None:
    profiles = _profile_store(tmp_path)
    profile = profiles.create(
        site_policy_digest=browser_site_policy_digest(
            ("https://site.example.test",)
        ),
        account_label="test account",
        browser_identity_digest="b" * 64,
    )
    runtime = KernelToolRuntime(
        build_browser_tool_registrations(
            environment=PrestartUnavailableEnvironment(),
            profile_store=profiles,
            session_store=BrowserSessionStore(root=tmp_path / "sessions"),
            browser_identity_digest="b" * 64,
            clock=lambda: "2026-08-28T10:00:00+00:00",
            monotonic_clock=lambda: 1000.0,
        ),
        clock=lambda: "2026-08-28T10:00:00+00:00",
    )
    call = ToolCall(
        "open-prestart",
        "browser_open",
        {
            "mode": "site_bound_interactive",
            "profile_ref": profile.profile_id,
            "profile_revision": profile.revision,
            "allowed_origins": ["https://site.example.test"],
        },
    )
    request = runtime.prepare(call, _context())
    result = runtime.invoke(
        runtime.prepare(
            call,
            _context(),
            approval=ApprovalGrant(
                request_id=request.request.request_id,
                binding_digest=request.request.binding_digest,
                approval_basis_revision=7,
            ),
        )
    )

    assert result.executed is False
    assert result.metadata["code"] == "browser_open_unavailable"
    writer = profiles.acquire_writer(profile)
    profiles.release_writer(writer)


def test_disclose_action_needs_exact_browser_lease_before_adapter_call(tmp_path):
    environment = RecordingEnvironment()
    profiles = _profile_store(tmp_path)
    profile = profiles.create(
        site_policy_digest=browser_site_policy_digest(
            ("https://site.example.test",)
        ),
        account_label="test account",
        browser_identity_digest="b" * 64,
    )
    registrations = build_browser_tool_registrations(
        environment=environment,
        profile_store=profiles,
        session_store=BrowserSessionStore(root=tmp_path / "sessions"),
        browser_identity_digest="b" * 64,
        clock=lambda: "2026-08-28T10:00:00+00:00",
        monotonic_clock=lambda: 1000.0,
    )
    runtime = KernelToolRuntime(registrations, clock=lambda: "2026-08-28T10:00:00+00:00")
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
    open_approval = runtime.prepare(open_call, _context())
    assert isinstance(open_approval, ApprovalRequired)
    opened = runtime.invoke(
        runtime.prepare(
            open_call,
            _context(),
            approval=ApprovalGrant(
                request_id=open_approval.request.request_id,
                binding_digest=open_approval.request.binding_digest,
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
    act_call = ToolCall(
        "act-1",
        "browser_act",
        {
            "session_ref": session_ref,
            "kind": "fill_form",
            "observation_digest": observed.metadata["observation_digest"],
            "page_id": session_ref,
            "frame_id": "main",
            "target_ref": "form-1",
            "params": {"fields": {"Email": "user@example.test"}},
        },
    )
    approval = runtime.prepare(act_call, _context())
    assert isinstance(approval, ApprovalRequired)
    assert environment.executed == []
    candidate = approval.request.browser_action_candidate
    assert candidate is not None and candidate.consequence == "disclose"
    assert candidate.issued_at == "2026-08-28T10:00:00+00:00"
    lease = BrowserAuthorityLeaseV1.create(
        lease_id="browser-lease-1",
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
        approved_request_identity=approval.request.request_id,
        issued_at=candidate.issued_at,
        expires_at=candidate.expires_at,
    )
    prepared = runtime.prepare(act_call, _context(browser_leases=(lease,)))
    assert isinstance(prepared, ExecutionIntent)
    assert prepared.browser_lease == lease
    result = runtime.invoke(prepared)
    assert result.metadata["browser_receipt_kind"] == "browser_action_v1"
    assert len(environment.executed) == 1

    # 释放 persistent profile writer；close 仍走同一 ToolRuntime。
    runtime.invoke(
        runtime.prepare(
            ToolCall("close-1", "browser_close", {"session_ref": session_ref}),
            _context(),
        )
    )


def test_interactive_open_rejects_profile_for_another_site_policy(tmp_path):
    environment = RecordingEnvironment()
    profiles = _profile_store(tmp_path)
    profile = profiles.create(
        site_policy_digest=browser_site_policy_digest(
            ("https://other.example.test",)
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
        ),
        clock=lambda: "2026-08-28T10:00:00+00:00",
    )

    rejected = runtime.prepare(
        ToolCall(
            "open-wrong-site",
            "browser_open",
            {
                "mode": "site_bound_interactive",
                "profile_ref": profile.profile_id,
                "profile_revision": profile.revision,
                "allowed_origins": ["https://site.example.test"],
            },
        ),
        _context(),
    )
    assert isinstance(rejected, ToolResult)
    assert rejected.is_error is True
    assert rejected.metadata["code"] == "binding_failure"
    assert environment.opened == []


def test_takeover_revision_invalidates_old_session_but_still_allows_close(tmp_path):
    environment = RecordingEnvironment()
    profiles = _profile_store(tmp_path)
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
    approval = runtime.prepare(open_call, _context())
    assert isinstance(approval, ApprovalRequired)
    opened = runtime.invoke(
        runtime.prepare(
            open_call,
            _context(),
            approval=ApprovalGrant(
                request_id=approval.request.request_id,
                binding_digest=approval.request.binding_digest,
                approval_basis_revision=7,
            ),
        )
    )
    session_ref = opened.metadata["session_ref"]

    profiles.advance_revision(profile, expected_revision=profile.revision)
    rejected = runtime.prepare(
        ToolCall("observe-stale", "browser_observe", {"session_ref": session_ref}),
        _context(),
    )

    assert isinstance(rejected, ToolResult)
    assert rejected.metadata["code"] == "binding_failure"
    assert environment.observed == []
    closed = runtime.invoke(
        runtime.prepare(
            ToolCall("close-stale", "browser_close", {"session_ref": session_ref}),
            _context(),
        )
    )
    assert closed.metadata["cleanup_outcome"] == "cleaned"
    assert len(environment.closed) == 1


def test_runtime_denial_then_approval_preserves_effect_order_and_single_use(tmp_path):
    from agent.runtime.context import ContextLimits, KernelContextManager
    from agent.runtime.contracts import (
        ModelResponse,
        ModelToolCall,
        ResolveApproval,
        RunStatus,
        SubmitMessage,
    )
    from agent.runtime.loop import AgentRuntime, InvocationLimits
    from agent.runtime.ports import RetryableProviderError
    from tests.kernel.fakes import (
        CollectingSink,
        InMemoryCheckpointStore,
        ScriptedProvider,
        conversation_with_active_goal,
        goal_noop_response,
    )

    environment = RecordingEnvironment()
    profiles = _profile_store(tmp_path)
    profile = profiles.create(
        site_policy_digest=browser_site_policy_digest(
            ("https://site.example.test",)
        ),
        account_label="test account",
        browser_identity_digest="b" * 64,
    )
    session_ref = "session-0123456789abcdef"
    observation = _observation(
        BrowserHandleV1(
            session_ref=session_ref,
            mode=BrowserMode.SITE_BOUND_INTERACTIVE,
            authority_digest="placeholder",
        ),
        profile_revision=profile.revision,
    )
    provider = ScriptedProvider(
        goal_noop_response("delta-browser"),
        ModelResponse(
            (
                ModelToolCall(
                    "open-1",
                    "browser_open",
                    {
                        "mode": "site_bound_interactive",
                        "profile_ref": profile.profile_id,
                        "profile_revision": profile.revision,
                        "allowed_origins": ["https://site.example.test"],
                    },
                ),
            )
        ),
        ModelResponse(
            (ModelToolCall("observe-1", "browser_observe", {"session_ref": session_ref}),)
        ),
        ModelResponse(
            (
                ModelToolCall(
                    "act-1",
                    "browser_act",
                    {
                        "session_ref": session_ref,
                        "kind": "fill_form",
                        "observation_digest": observation.observation_digest,
                        "page_id": session_ref,
                        "frame_id": "main",
                        "target_ref": "form-1",
                        "params": {"fields": {"Email": "user@example.test"}},
                    },
                ),
            )
        ),
        ModelResponse(
            (ModelToolCall("close-1", "browser_close", {"session_ref": session_ref}),)
        ),
        RetryableProviderError("stop-after-browser-flow"),
    )
    state = conversation_with_active_goal()
    store = InMemoryCheckpointStore(state)
    registrations = build_browser_tool_registrations(
        environment=environment,
        profile_store=profiles,
        session_store=BrowserSessionStore(root=tmp_path / "sessions"),
        browser_identity_digest="b" * 64,
        clock=lambda: "2026-08-28T10:00:00+00:00",
        monotonic_clock=lambda: 1000.0,
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="Be concise.",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=500),
        ),
        tool_runtime=KernelToolRuntime(
            registrations, clock=lambda: "2026-08-28T10:00:00+00:00"
        ),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    submitted = runtime.run_turn(
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-1",
            message="use the site to finish the task",
        ),
        store.load(),
    )
    assert submitted.status is RunStatus.AWAITING_APPROVAL
    assert environment.opened == [] and environment.executed == []
    open_request = submitted.request
    opened = runtime.run_turn(
        ResolveApproval(
            conversation_id=submitted.state.conversation_id,
            action_seq=submitted.state.next_action_seq,
            expected_revision=submitted.state.revision,
            request_id=open_request.request_id,
            binding_digest=open_request.binding_digest,
            approved=True,
            approved_at="2026-08-28T10:00:00+00:00",
        ),
        store.load(),
    )
    assert opened.status is RunStatus.AWAITING_APPROVAL
    assert len(environment.opened) == 1
    assert environment.executed == []  # DISCLOSE 未批准，adapter effect 为零。
    action_request = opened.request
    assert action_request.browser_action_candidate is not None

    finished = runtime.run_turn(
        ResolveApproval(
            conversation_id=opened.state.conversation_id,
            action_seq=opened.state.next_action_seq,
            expected_revision=opened.state.revision,
            request_id=action_request.request_id,
            binding_digest=action_request.binding_digest,
            approved=True,
            approved_at="2026-08-28T10:00:00+00:00",
        ),
        store.load(),
    )
    assert finished.status is RunStatus.FAILED_RETRYABLE
    assert len(environment.executed) == 1
    assert len(environment.closed) == 1
    assert finished.state.browser_leases[0].uses_consumed == 1
