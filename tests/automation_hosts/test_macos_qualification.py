from __future__ import annotations

from dataclasses import replace

import pytest

from agent.automation_hosts.macos_profile import (
    MacOSAutomationHostProfile,
    MacOSHostProfileConfigV1,
)
from agent.runtime.contracts import ProviderDescriptor, canonical_json_digest
from agent.sandbox.contracts import (
    SandboxBackendIdentityV1,
    SandboxQualificationV1,
)
from tests.automation.test_contracts import _definition


def _descriptor() -> ProviderDescriptor:
    return ProviderDescriptor(
        family="openai_compatible",
        model="bounded-model",
        canonical_destination="https://provider.example/v1/chat/completions",
        trust_profile="remote-https-v1",
        remote=True,
    )


def _sandbox_qualification() -> SandboxQualificationV1:
    return SandboxQualificationV1(
        available=True,
        reason_code="qualified",
        backend_identity=SandboxBackendIdentityV1(
            executable_path="/usr/bin/sandbox-exec",
            platform_system="Darwin",
            platform_release="24.5.0",
            functional_probe_digest="1" * 64,
            probe_profile_digest="2" * 64,
        ),
    )


def _config() -> MacOSHostProfileConfigV1:
    sandbox = _sandbox_qualification()
    assert sandbox.backend_identity is not None
    return MacOSHostProfileConfigV1.create(
        supervisor_identity_digest="3" * 64,
        sandbox_backend_identity_digest=(
            sandbox.backend_identity.backend_identity_digest
        ),
        background_policy_digest="4" * 64,
        browser_identity_digest="5" * 64,
        browser_origin_policy_digest="6" * 64,
        provider_descriptor_digest=_descriptor().identity_digest,
        trust_profile_digest=canonical_json_digest("remote-https-v1"),
        credential_environment_name="MODEL_API_KEY",
        provider_disclosure_request_digest="7" * 64,
    )


def _profile(
    *,
    credential: str | None = "opaque-value",
    platform_system: str = "Darwin",
    supervisor_identity_digest: str = "3" * 64,
    browser_identity_digest: str | None = "5" * 64,
    sandbox_qualification: SandboxQualificationV1 | None = None,
    provider_descriptor: ProviderDescriptor | None = None,
) -> MacOSAutomationHostProfile:
    return MacOSAutomationHostProfile(
        config=_config(),
        platform_system=platform_system,
        supervisor_identity_digest=supervisor_identity_digest,
        sandbox_qualification=sandbox_qualification or _sandbox_qualification(),
        browser_identity_digest=browser_identity_digest,
        provider_descriptor=provider_descriptor or _descriptor(),
        credential_lookup=lambda name: credential if name == "MODEL_API_KEY" else None,
    )


def _matching_definition():  # noqa: ANN202
    config = _config()
    return _definition(
        provider_descriptor_digest=config.provider_descriptor_digest,
        trust_profile_digest=config.trust_profile_digest,
        credential_environment_name=config.credential_environment_name,
        background_environment_policy_digest=config.background_policy_digest,
        browser_origin_policy_digest=config.browser_origin_policy_digest,
        provider_disclosure_request_digest=(
            config.provider_disclosure_request_digest
        ),
    )


def test_exact_static_macos_profile_qualifies_without_persisting_credential() -> None:
    profile = _profile()

    result = profile.qualify(_matching_definition())

    assert result.available is True
    assert result.reason_code == "qualified"
    assert result.qualification_identity_digest == _config().config_digest
    assert "opaque-value" not in repr(profile)
    assert "opaque-value" not in repr(result)


@pytest.mark.parametrize(
    ("profile", "body_change", "reason"),
    [
        (_profile(platform_system="Linux"), {}, "unsupported_platform"),
        (
            _profile(supervisor_identity_digest="a" * 64),
            {},
            "supervisor_identity_drift",
        ),
        (
            _profile(browser_identity_digest="b" * 64),
            {},
            "browser_identity_drift",
        ),
        (
            _profile(browser_identity_digest=None),
            {},
            "browser_unavailable",
        ),
        (
            _profile(
                sandbox_qualification=SandboxQualificationV1(
                    False,
                    "functional_probe_failed",
                )
            ),
            {},
            "sandbox_unavailable",
        ),
        (
            _profile(
                sandbox_qualification=SandboxQualificationV1(
                    available=True,
                    reason_code="qualified",
                    backend_identity=SandboxBackendIdentityV1(
                        executable_path="/usr/bin/sandbox-exec",
                        platform_system="Darwin",
                        platform_release="24.6.0",
                        functional_probe_digest="1" * 64,
                        probe_profile_digest="2" * 64,
                    ),
                )
            ),
            {},
            "sandbox_backend_identity_drift",
        ),
        (
            _profile(credential=None),
            {},
            "credential_unavailable",
        ),
        (
            _profile(),
            {"provider_descriptor_digest": "c" * 64},
            "provider_profile_identity_drift",
        ),
        (
            _profile(
                provider_descriptor=ProviderDescriptor(
                    family="openai_compatible",
                    model="different-model",
                    canonical_destination=(
                        "https://provider.example/v1/chat/completions"
                    ),
                    trust_profile="remote-https-v1",
                    remote=True,
                )
            ),
            {},
            "provider_profile_identity_drift",
        ),
        (
            _profile(),
            {"trust_profile_digest": "d" * 64},
            "provider_profile_identity_drift",
        ),
        (
            _profile(),
            {"credential_environment_name": "OTHER_API_KEY"},
            "provider_profile_identity_drift",
        ),
        (
            _profile(),
            {"provider_disclosure_request_digest": "e" * 64},
            "provider_profile_identity_drift",
        ),
        (
            _profile(),
            {"background_environment_policy_digest": "d" * 64},
            "sandbox_policy_identity_drift",
        ),
        (
            _profile(),
            {"browser_origin_policy_digest": "e" * 64},
            "browser_policy_identity_drift",
        ),
    ],
)
def test_qualification_drift_fails_before_occurrence_composition(
    profile: MacOSAutomationHostProfile,
    body_change: dict[str, object],
    reason: str,
) -> None:
    definition = _matching_definition()
    if body_change:
        body = replace(
            definition.body,
            **body_change,
            definition_body_digest="",
        )
        definition = type(definition).create_from_body(
            body,
            activation_preview_digest="9" * 64,
            sandbox_confined=True,
            browser_public_observe=True,
        )

    result = profile.qualify(definition)

    assert result.available is False
    assert result.reason_code == reason
    assert result.qualification_identity_digest is None
    assert profile.composition_calls == 0
