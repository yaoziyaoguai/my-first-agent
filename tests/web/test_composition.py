from __future__ import annotations

from pathlib import Path

import httpx

import main as entrypoint
from agent.composition import build_web_resources
from agent.web.profile import WebProfileV1, save_web_profile


def _profile() -> WebProfileV1:
    return WebProfileV1(
        credential_env="FIRST_AGENT_WEB_API_KEY",
        timeout_seconds=10.0,
        max_results=3,
    )


def test_unconfigured_web_resources_register_nothing() -> None:
    resources = build_web_resources(None, credential=None)

    assert resources.registrations == ()
    assert resources.closeables == ()


def test_configured_web_resources_are_two_static_governed_tools() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                500,
                headers={"content-type": "application/json"},
                json={},
            )
        ),
        follow_redirects=False,
        trust_env=False,
    ) as http_client:
        resources = build_web_resources(
            _profile(),
            credential="secret-value",
            http_client=http_client,
            clock=lambda: "2026-08-04T00:00:00Z",
        )

    assert [item.spec.name for item in resources.registrations] == [
        "web_search",
        "web_fetch",
    ]
    assert resources.closeables == ()
    assert all(item.spec.egress.value == "public_network" for item in resources.registrations)


def test_saved_web_profile_without_exact_credential_fails_before_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    save_web_profile(state_root, _profile())
    monkeypatch.delenv("FIRST_AGENT_WEB_API_KEY", raising=False)
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--provider",
            "fake",
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
        ],
        input_fn=lambda _prompt: "/exit",
        write_fn=output.append,
    )

    assert exit_code == 2
    assert any(
        "Web profile credential environment variable is not set: "
        "FIRST_AGENT_WEB_API_KEY" in line
        for line in output
    )
    assert all("secret-value" not in line for line in output)
