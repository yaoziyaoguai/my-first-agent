from __future__ import annotations

import httpx
import pytest


def _config(**overrides):
    from agent.provider.config import AgentProviderConfig

    values = {
        "provider_type": "anthropic_compatible",
        "api_key": "secret-token-must-not-leak",
        "api_key_env": "ANTHROPIC_API_KEY",
        "base_url": "https://provider.example/root/",
        "model": "claude-compatible",
        "max_tokens": 64,
        "timeout": 3.0,
        "supports_tools": True,
        "supports_streaming": False,
        "auth_scheme": "bearer",
        "request_path": "/v1/messages",
        "compatibility_mode": "anthropic_messages",
    }
    values.update(overrides)
    return AgentProviderConfig(**values)


def test_anthropic_compatible_http_bearer_request_includes_tools_and_custom_path():
    from agent.provider.anthropic_http import AnthropicCompatibleProvider
    from agent.provider.protocol import ToolUseBlock

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        seen["x_api_key"] = request.headers.get("x-api-key")
        seen["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "calling"},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "read_file",
                        "input": {"path": "README.md"},
                    },
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 5, "output_tokens": 6},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = AnthropicCompatibleProvider(
        config=_config(request_path="messages"), http_client=client
    )

    response = provider.create(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"name": "read_file", "input_schema": {"type": "object"}}],
    )

    assert seen["url"] == "https://provider.example/root/messages"
    assert seen["authorization"] == "Bearer secret-token-must-not-leak"
    assert seen["x_api_key"] is None
    assert '"tools":[{"name":"read_file","input_schema":{"type":"object"}}]' in seen["body"]
    assert response.content[1] == ToolUseBlock(
        id="toolu_1",
        name="read_file",
        input={"path": "README.md"},
    )


def test_anthropic_compatible_http_x_api_key_auth_header():
    from agent.provider.anthropic_http import AnthropicCompatibleProvider

    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["x_api_key"] = request.headers.get("x-api-key")
        return httpx.Response(200, json={"content": [], "stop_reason": "end_turn"})

    provider = AnthropicCompatibleProvider(
        config=_config(auth_scheme="x-api-key"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    provider.create(system="", messages=[{"role": "user", "content": "hi"}], tools=[])

    assert seen["authorization"] is None
    assert seen["x_api_key"] == "secret-token-must-not-leak"


def test_anthropic_compatible_http_401_is_auth_error_without_key_leak():
    from agent.provider.anthropic_http import AnthropicCompatibleProvider
    from agent.provider.protocol import ProviderAuthError

    provider = AnthropicCompatibleProvider(
        config=_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, text="bad secret-token-must-not-leak")
            )
        ),
    )

    with pytest.raises(ProviderAuthError) as excinfo:
        provider.create(system="", messages=[{"role": "user", "content": "hi"}], tools=[])

    assert "secret-token-must-not-leak" not in str(excinfo.value)
    assert "401" in str(excinfo.value)


def test_anthropic_compatible_http_malformed_response_is_classified_without_body_leak():
    from agent.provider.anthropic_http import AnthropicCompatibleProvider
    from agent.provider.protocol import ProviderResponseError

    provider = AnthropicCompatibleProvider(
        config=_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"content": "not-a-list"})
            )
        ),
    )

    with pytest.raises(ProviderResponseError) as excinfo:
        provider.create(system="", messages=[{"role": "user", "content": "hi"}], tools=[])

    assert "not-a-list" not in str(excinfo.value)
    assert "malformed_response" in str(excinfo.value)


def test_anthropic_compatible_http_timeout_is_classified():
    from agent.provider.anthropic_http import AnthropicCompatibleProvider
    from agent.provider.protocol import ProviderTimeoutError

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout with secret-token-must-not-leak")

    provider = AnthropicCompatibleProvider(
        config=_config(), http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(ProviderTimeoutError) as excinfo:
        provider.create(system="", messages=[{"role": "user", "content": "hi"}], tools=[])

    assert "secret-token-must-not-leak" not in str(excinfo.value)
