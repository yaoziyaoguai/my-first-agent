from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest


def test_provider_blocks_are_frozen_and_response_handler_compatible():
    from agent.provider.protocol import ProviderResponse, ProviderTextBlock, ToolUseBlock

    tool_block = ToolUseBlock(id="toolu_1", name="read_file", input={"path": "a.txt"})
    text_block = ProviderTextBlock(text="hello")
    response = ProviderResponse(
        content=[text_block, tool_block],
        stop_reason="tool_use",
        usage={"input_tokens": 1, "output_tokens": 2},
        raw_provider_name="anthropic_compatible",
    )

    assert tool_block.type == "tool_use"
    assert text_block.type == "text"
    assert response.content == [text_block, tool_block]
    with pytest.raises(FrozenInstanceError):
        tool_block.name = "write_file"  # type: ignore[misc]


def test_agent_provider_config_redacts_secret_from_repr_and_summary():
    from agent.provider.config import AgentProviderConfig

    config = AgentProviderConfig(
        provider_type="anthropic_compatible",
        api_key="secret-token-must-not-leak",
        api_key_env="ANTHROPIC_API_KEY",
        base_url="https://provider.example",
        model="claude-compatible",
        max_tokens=64,
        timeout=3.0,
        supports_tools=True,
        supports_streaming=False,
        auth_scheme="bearer",
        request_path="/v1/messages",
        compatibility_mode="anthropic_messages",
    )

    assert "secret-token-must-not-leak" not in repr(config)
    assert "secret-token-must-not-leak" not in str(config)
    summary = config.redacted_summary()
    assert summary["api_key"] == "SET"
    assert "secret-token-must-not-leak" not in repr(summary)


def test_agent_provider_config_loads_anthropic_compatible_from_env_without_dotenv():
    from agent.provider.config import load_agent_provider_config

    env = {
        "MY_FIRST_AGENT_LLM_PROVIDER": "anthropic_compatible",
        "ANTHROPIC_API_KEY": "secret-token-must-not-leak",
        "ANTHROPIC_BASE_URL": "https://provider.example/root/",
        "ANTHROPIC_MODEL": "claude-compatible",
    }

    config = load_agent_provider_config(env=env)

    assert config.provider_type == "anthropic_compatible"
    assert config.api_key == "secret-token-must-not-leak"
    assert config.base_url == "https://provider.example/root/"
    assert config.model == "claude-compatible"
    assert config.request_path == "/v1/messages"
    assert config.auth_scheme == "auto"
    assert "secret-token-must-not-leak" not in repr(config.redacted_summary())


def test_openai_native_is_implemented_and_returns_provider():
    from agent.provider.config import AgentProviderConfig
    from agent.provider.factory import build_model_provider

    config = AgentProviderConfig(
        provider_type="openai_native",
        api_key="sk-test",
        api_key_env="OPENAI_API_KEY",
        base_url=None,
        model="gpt-test",
        max_tokens=64,
        timeout=3.0,
        supports_tools=True,
        supports_streaming=False,
        auth_scheme="bearer",
        request_path="/v1/chat/completions",
        compatibility_mode="openai",
    )

    provider = build_model_provider(config)
    assert provider.provider_type == "openai_native"
    assert provider.supports_tools is True
    assert provider.supports_streaming is False


def test_openai_compatible_is_implemented_and_returns_provider():
    from agent.provider.config import AgentProviderConfig
    from agent.provider.factory import build_model_provider

    config = AgentProviderConfig(
        provider_type="openai_compatible",
        api_key="sk-test",
        api_key_env="OPENAI_API_KEY",
        base_url="https://openai-compat.example/",
        model="gpt-compat",
        max_tokens=64,
        timeout=3.0,
        supports_tools=True,
        supports_streaming=False,
        auth_scheme="bearer",
        request_path="/v1/chat/completions",
        compatibility_mode="openai",
    )

    provider = build_model_provider(config)
    assert provider.provider_type == "openai_compatible"
    assert provider.supports_tools is True
    assert provider.supports_streaming is False
