from __future__ import annotations

import httpx
import pytest

from agent.provider.anthropic_http import AnthropicCompatibleProvider
from agent.provider.config import AgentProviderConfig
from agent.provider.openai_http import OpenAICompatibleProvider
from agent.provider.protocol import ProviderAuthError, ProviderProtocolError
from agent.runtime.contracts import BudgetReport, ContextPack, ProviderDescriptor


@pytest.mark.parametrize(
    "destination",
    (
        "https://user@example.com/v1",
        "https://example.com/v1?route=other",
        "https://example.com/v1#fragment",
        "http://example.com/v1",
    ),
)
def test_remote_destination_rejects_ambiguous_or_plain_http_url(destination: str) -> None:
    with pytest.raises(ValueError):
        ProviderDescriptor(
            family="openai_compatible",
            model="model",
            canonical_destination=destination,
            trust_profile="remote-https-v1",
            remote=True,
        )


def _context() -> ContextPack:
    return ContextPack(
        system="policy",
        messages=(),
        tools=(),
        budget=BudgetReport(
            input_limit=1_000,
            estimated_input_tokens=10,
            output_reserve=100,
        ),
    )


@pytest.mark.parametrize(
    ("provider_type", "provider_class"),
    (
        ("openai_compatible", OpenAICompatibleProvider),
        ("anthropic_compatible", AnthropicCompatibleProvider),
    ),
)
def test_redirect_is_not_followed(
    provider_type: str,
    provider_class: type[OpenAICompatibleProvider] | type[AnthropicCompatibleProvider],
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://other.example/v1"})

    config = AgentProviderConfig(
        provider_type=provider_type,
        model="model",
        base_url="https://provider.example",
        credential="secret-value",
    )
    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        provider = provider_class(config=config, http_client=client)
        with pytest.raises(ProviderProtocolError):
            provider.generate(_context())

    assert len(requests) == 1
    assert requests[0].url.host == "provider.example"


@pytest.mark.parametrize(
    ("module_name", "provider_type", "provider_class"),
    (
        (
            "agent.provider.openai_http",
            "openai_compatible",
            OpenAICompatibleProvider,
        ),
        (
            "agent.provider.anthropic_http",
            "anthropic_compatible",
            AnthropicCompatibleProvider,
        ),
    ),
)
def test_default_http_client_disables_ambient_environment_and_redirects(
    monkeypatch,
    module_name: str,
    provider_type: str,
    provider_class: type[OpenAICompatibleProvider] | type[AnthropicCompatibleProvider],
) -> None:
    captured: dict[str, object] = {}

    class StubClient:
        pass

    def factory(**kwargs):
        captured.update(kwargs)
        return StubClient()

    module = __import__(module_name, fromlist=["httpx"])
    monkeypatch.setattr(module.httpx, "Client", factory)
    provider = provider_class(
        config=AgentProviderConfig(
            provider_type=provider_type,
            model="model",
            base_url="https://provider.example",
        )
    )

    assert isinstance(provider._client(), StubClient)
    assert captured["trust_env"] is False
    assert captured["follow_redirects"] is False


def test_credential_never_appears_in_descriptor_repr_or_http_error() -> None:
    credential = "credential-must-not-leak"
    config = AgentProviderConfig(
        provider_type="openai_compatible",
        model="model",
        base_url="https://provider.example",
        credential=credential,
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=credential)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(config=config, http_client=client)
        with pytest.raises(ProviderAuthError) as captured:
            provider.generate(_context())

    assert credential not in repr(config)
    assert credential not in repr(config.descriptor())
    assert credential not in str(captured.value)
