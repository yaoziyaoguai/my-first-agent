from __future__ import annotations

from types import SimpleNamespace


def test_normalize_anthropic_text_response_preserves_stop_reason_and_usage():
    from agent.provider.normalize import normalize_anthropic_response
    from agent.provider.protocol import ProviderTextBlock

    raw = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="hello")],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=10, output_tokens=4),
    )

    response = normalize_anthropic_response(raw, raw_provider_name="anthropic_native")

    assert response.stop_reason == "end_turn"
    assert response.content == [ProviderTextBlock(text="hello")]
    assert response.usage == {"input_tokens": 10, "output_tokens": 4}
    assert response.raw_provider_name == "anthropic_native"


def test_normalize_anthropic_tool_use_response_returns_provider_tool_block():
    from agent.provider.normalize import normalize_anthropic_response
    from agent.provider.protocol import ToolUseBlock

    raw = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="I will read it."),
            SimpleNamespace(
                type="tool_use",
                id="toolu_1",
                name="read_file",
                input={"path": "README.md"},
            ),
        ],
        stop_reason="tool_use",
        usage={"input_tokens": 3, "output_tokens": 2},
    )

    response = normalize_anthropic_response(raw)

    assert response.content[1] == ToolUseBlock(
        id="toolu_1",
        name="read_file",
        input={"path": "README.md"},
    )
    assert response.stop_reason == "tool_use"
    assert response.usage == {"input_tokens": 3, "output_tokens": 2}


def test_normalize_malformed_tool_input_uses_empty_dict_without_leaking_raw_value():
    from agent.provider.normalize import normalize_anthropic_response

    raw = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                id="toolu_1",
                name="read_file",
                input='{"path": ',
            )
        ],
        stop_reason="tool_use",
        usage=None,
    )

    response = normalize_anthropic_response(raw)

    tool_block = response.content[0]
    assert tool_block.input == {}
    assert '{"path": ' not in repr(response)


def test_anthropic_native_provider_wraps_messages_create_and_normalizes():
    from agent.provider.anthropic_native import AnthropicNativeProvider
    from agent.provider.config import AgentProviderConfig
    from agent.provider.protocol import ProviderTextBlock

    class _Messages:
        def __init__(self):
            self.requests = []

        def create(self, **kwargs):
            self.requests.append(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="native-ok")],
                stop_reason="end_turn",
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            )

    class _Client:
        def __init__(self):
            self.messages = _Messages()

    config = AgentProviderConfig(
        provider_type="anthropic_native",
        api_key="secret-token-must-not-leak",
        api_key_env="ANTHROPIC_API_KEY",
        base_url=None,
        model="claude-native",
        max_tokens=32,
        timeout=3.0,
        supports_tools=True,
        supports_streaming=True,
        auth_scheme="x-api-key",
        request_path="/v1/messages",
        compatibility_mode="anthropic_messages",
    )
    provider = AnthropicNativeProvider(config=config, client=_Client())

    response = provider.create(
        system="You are a test assistant.",
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
    )

    assert response.content == [ProviderTextBlock(text="native-ok")]
    assert "secret-token-must-not-leak" not in repr(provider.config)
