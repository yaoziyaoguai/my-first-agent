from __future__ import annotations

import json
from dataclasses import replace

import pytest

from agent.automation.claim_verifier import AutomationClaimVerifier
from agent.browser.contracts import BrowserMode
from agent.composition import BrowserReadiness, build_browser_resources
from agent.runtime.contracts import (
    ApprovalRequired,
    ExecutionIntent,
    ToolCall,
    ToolResult,
)
from agent.runtime.tools import KernelToolRuntime
from scripts.browser_e3_fixture import (
    FixturePlaywrightFactory,
    FixtureResolver,
    start_hostile_tls_fixture,
)
from tests.automation.test_claim_verifier import (
    _execution_authority,
    _running_claim,
)
from tests.automation.test_tool_authority import _browser_registration, _context


def _fixture_or_skip(tmp_path, *, attempt_id: str):  # noqa: ANN001, ANN202
    try:
        return start_hostile_tls_fixture(tmp_path, attempt_id=attempt_id)
    except PermissionError as error:
        if error.errno == 1:
            pytest.skip("current managed Coding sandbox forbids loopback fixture sockets")
        raise


def test_background_browser_grant_does_not_broaden_forbidden_classes() -> None:
    repository, _ = _running_claim()
    verifier = AutomationClaimVerifier(repository)
    registrations = []
    for consequence in ("disclose", "commit", "download", "upload"):
        registrations.append(_browser_registration(consequence=consequence))
    site_bound = _browser_registration(consequence="observe")
    original_binding = site_bound.prepare_binding
    site_bound = replace(
        site_bound,
        prepare_binding=lambda arguments: {
            **original_binding(arguments),
            "mode": BrowserMode.SITE_BOUND_INTERACTIVE.value,
            "profile_ref": "profile:test",
            "profile_revision": 1,
            "allowed_origins": ["https://example.test"],
        },
    )
    registrations.append(site_bound)

    for index, registration in enumerate(registrations):
        runtime = KernelToolRuntime(
            (registration,),
            background_claim_verifier=verifier,
            clock=lambda: "2026-08-28T00:01:00Z",
        )
        outcome = runtime.prepare(
            ToolCall(f"call-{index}", registration.spec.name, {}),
            _context(),
        )
        assert isinstance(outcome, ApprovalRequired)


def _prepare(
    runtime: KernelToolRuntime,
    call: ToolCall,
    *,
    browser_actions_used: int,
):
    return runtime.prepare(
        call,
        _context(
            background_browser_actions_used=browser_actions_used,
        ),
    )


def test_real_public_browser_observation_uses_background_authority_and_budget(
    tmp_path,
) -> None:
    repository, authority = _running_claim()
    fixture = _fixture_or_skip(tmp_path / "fixture", attempt_id="background")
    resources = build_browser_resources(
        tmp_path / "workspace",
        tmp_path / "state",
        enabled=True,
        resolver=FixtureResolver(),
        playwright_factory=FixturePlaywrightFactory(port=fixture.port),
    )
    assert resources.readiness is BrowserReadiness.READY
    runtime = KernelToolRuntime(
        resources.registrations,
        background_claim_verifier=AutomationClaimVerifier(repository),
        clock=lambda: "2026-08-28T00:01:00Z",
    )
    execution_authority = _execution_authority(authority)

    try:
        opened = runtime.prepare(
            ToolCall(
                "call-open",
                "browser_open",
                {
                    "mode": BrowserMode.PUBLIC_READ_EPHEMERAL.value,
                    "action_budget": 3,
                },
            ),
            _context(background_execution_authority=execution_authority),
        )
        assert isinstance(opened, ExecutionIntent)
        assert opened.background_action_authority is not None
        assert opened.background_action_authority.action_class == (
            "browser_public_observe"
        )
        open_result = runtime.invoke(opened)
        session_ref = open_result.metadata["session_ref"]
        assert isinstance(session_ref, str)

        observed = runtime.prepare(
            ToolCall("call-observe", "browser_observe", {"session_ref": session_ref}),
            _context(
                background_execution_authority=execution_authority,
                background_browser_actions_used=1,
                background_tool_calls_used=1,
            ),
        )
        assert isinstance(observed, ExecutionIntent)
        observation = runtime.invoke(observed)
        payload = json.loads(observation.content)

        navigated = runtime.prepare(
            ToolCall(
                "call-navigate",
                "browser_act",
                {
                    "session_ref": session_ref,
                    "kind": "navigate",
                    "observation_digest": observation.metadata["observation_digest"],
                    "page_id": payload["page_id"],
                    "frame_id": payload["frame_id"],
                    "params": {"url": fixture.origin},
                },
            ),
            _context(
                background_execution_authority=execution_authority,
                background_browser_actions_used=2,
                background_tool_calls_used=2,
            ),
        )
        assert isinstance(navigated, ExecutionIntent)
        assert navigated.safety_binding["consequence"] == "observe"
        assert runtime.invoke(navigated).executed is True

        exhausted = runtime.prepare(
            ToolCall(
                "call-over-budget",
                "browser_observe",
                {"session_ref": session_ref},
            ),
            _context(
                background_execution_authority=execution_authority,
                background_browser_actions_used=3,
                background_tool_calls_used=3,
            ),
        )
        assert isinstance(exhausted, ToolResult)
        assert exhausted.metadata["code"] == (
            "background_browser_public_observe_budget_exhausted"
        )
    finally:
        for closeable in reversed(resources.closeables):
            closeable()
        fixture.close()


def test_real_public_browser_does_not_self_authorize_disclose_commit_or_download(
    tmp_path,
) -> None:
    repository, authority = _running_claim()
    fixture = _fixture_or_skip(tmp_path / "fixture", attempt_id="deny-effects")
    resources = build_browser_resources(
        tmp_path / "workspace",
        tmp_path / "state",
        enabled=True,
        resolver=FixtureResolver(),
        playwright_factory=FixturePlaywrightFactory(port=fixture.port),
    )
    assert resources.readiness is BrowserReadiness.READY
    runtime = KernelToolRuntime(
        resources.registrations,
        background_claim_verifier=AutomationClaimVerifier(repository),
        clock=lambda: "2026-08-28T00:01:00Z",
    )
    execution_authority = _execution_authority(authority)
    context = _context(background_execution_authority=execution_authority)

    try:
        opened = runtime.prepare(
            ToolCall(
                "call-open",
                "browser_open",
                {"mode": BrowserMode.PUBLIC_READ_EPHEMERAL.value},
            ),
            context,
        )
        assert isinstance(opened, ExecutionIntent)
        open_result = runtime.invoke(opened)
        session_ref = open_result.metadata["session_ref"]
        observed = _prepare(
            runtime,
            ToolCall("call-observe", "browser_observe", {"session_ref": session_ref}),
            browser_actions_used=1,
        )
        assert isinstance(observed, ExecutionIntent)
        observation = runtime.invoke(observed)
        blank = json.loads(observation.content)
        navigate = _prepare(
            runtime,
            ToolCall(
                "call-navigate",
                "browser_act",
                {
                    "session_ref": session_ref,
                    "kind": "navigate",
                    "observation_digest": observation.metadata["observation_digest"],
                    "page_id": blank["page_id"],
                    "frame_id": blank["frame_id"],
                    "params": {"url": fixture.origin},
                },
            ),
            browser_actions_used=2,
        )
        assert isinstance(navigate, ExecutionIntent)
        runtime.invoke(navigate)

        fresh_intent = runtime.prepare(
            ToolCall("call-fresh", "browser_observe", {"session_ref": session_ref}),
            _context(background_execution_authority=execution_authority),
        )
        assert isinstance(fresh_intent, ExecutionIntent)
        fresh = runtime.invoke(fresh_intent)
        payload = json.loads(fresh.content)
        refs = {
            item["name"]: item["ref"]
            for item in payload["element_refs"]
            if item.get("name") in {"Email", "Sign in", "Download result"}
        }
        common = {
            "session_ref": session_ref,
            "observation_digest": fresh.metadata["observation_digest"],
            "page_id": payload["page_id"],
            "frame_id": payload["frame_id"],
        }
        calls = (
            ToolCall(
                "call-disclose",
                "browser_act",
                {
                    **common,
                    "kind": "fill_form",
                    "target_ref": refs["Email"],
                    "params": {"fields": {"email": "not-sent@example.test"}},
                },
            ),
            ToolCall(
                "call-commit",
                "browser_act",
                {**common, "kind": "click", "target_ref": refs["Sign in"]},
            ),
            ToolCall(
                "call-download",
                "browser_act",
                {
                    **common,
                    "kind": "download",
                    "target_ref": refs["Download result"],
                },
            ),
        )

        for call in calls:
            outcome = runtime.prepare(call, context)
            assert isinstance(outcome, ApprovalRequired)
    finally:
        for closeable in reversed(resources.closeables):
            closeable()
        fixture.close()
