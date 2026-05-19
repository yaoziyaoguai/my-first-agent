from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

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
    assert config.provider_name == "anthropic_compatible"
    assert config.api_key == "secret-token-must-not-leak"
    assert config.base_url == "https://provider.example/root/"
    assert config.model == "claude-compatible"
    assert config.request_path == "/v1/messages"
    assert config.auth_scheme == "auto"
    assert "secret-token-must-not-leak" not in repr(config.redacted_summary())


def test_agent_provider_config_uses_explicit_provider_name_without_url_inference():
    """provider 身份来自配置字段；新增 compatible provider 不需要改 runner 逻辑。"""
    from agent.provider.config import load_agent_provider_config

    env = {
        "MY_FIRST_AGENT_LLM_PROVIDER": "anthropic_compatible",
        "MY_FIRST_AGENT_LLM_PROVIDER_NAME": "new-compatible-provider",
        "ANTHROPIC_API_KEY": "secret-token-must-not-leak",
        "ANTHROPIC_BASE_URL": "https://example.invalid/custom/messages",
        "ANTHROPIC_MODEL": "custom-model",
    }

    config = load_agent_provider_config(env=env)

    assert config.provider_type == "anthropic_compatible"
    assert config.provider_name == "new-compatible-provider"
    assert config.base_url == "https://example.invalid/custom/messages"
    assert "secret-token-must-not-leak" not in repr(config.redacted_summary())


def test_provider_factory_covers_four_configured_api_styles():
    """四种 API style 都通过 AgentProviderConfig 进入统一 factory。"""
    from agent.provider.config import AgentProviderConfig
    from agent.provider.factory import build_model_provider

    cases = [
        ("anthropic_native", "anthropic", "ANTHROPIC_API_KEY", None, "claude-native", "x-api-key", "/v1/messages", "anthropic_messages"),
        ("anthropic_compatible", "custom-anthropic-compatible", "ANTHROPIC_API_KEY", "https://example.invalid/messages", "claude-compatible", "bearer", "/v1/messages", "anthropic_messages"),
        ("openai_native", "openai", "OPENAI_API_KEY", None, "gpt-native", "bearer", "/v1/chat/completions", "openai"),
        ("openai_compatible", "custom-openai-compatible", "OPENAI_API_KEY", "https://example.invalid/v1", "gpt-compatible", "bearer", "/v1/chat/completions", "openai"),
    ]

    for (
        provider_type,
        provider_name,
        api_key_env,
        base_url,
        model,
        auth_scheme,
        request_path,
        compatibility_mode,
    ) in cases:
        config = AgentProviderConfig(
            provider_type=provider_type,
            provider_name=provider_name,
            api_key="secret-token-must-not-leak",
            api_key_env=api_key_env,
            base_url=base_url,
            model=model,
            max_tokens=64,
            timeout=3.0,
            supports_tools=True,
            supports_streaming=provider_type == "anthropic_native",
            auth_scheme=auth_scheme,
            request_path=request_path,
            compatibility_mode=compatibility_mode,
        )

        provider = build_model_provider(config)

        assert provider.provider_type == provider_type
        assert provider.config.provider_name == provider_name
        assert "secret-token-must-not-leak" not in repr(config.redacted_summary())


def test_build_model_provider_from_env_returns_anthropic_native(monkeypatch):
    """Anthropic native 也必须是一等 provider，不能回退到 core.py SDK path。"""

    from agent.provider.factory import build_model_provider_from_env

    monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER", "anthropic_native")
    monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER_NAME", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-token-must-not-leak")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-native")

    provider = build_model_provider_from_env()

    assert provider is not None
    assert provider.provider_type == "anthropic_native"
    assert provider.config.provider_name == "anthropic"
    assert "secret-token-must-not-leak" not in repr(provider.config)


def test_provider_backed_messages_forwards_supported_legacy_overrides():
    """legacy messages facade 不得静默丢弃 Anthropic-style request overrides。

    planner/context/memory 仍使用 ``client.messages.create`` 形状；这个 facade
    只能把参数显式投影到 provider interface，不能假装接收后丢弃。
    """

    from agent.provider.legacy_adapter import ProviderBackedMessages
    from agent.provider.protocol import ProviderResponse

    class RecordingProvider:
        def __init__(self) -> None:
            self.request = None

        def create(self, **kwargs):  # noqa: ANN001, ANN202
            self.request = kwargs
            return ProviderResponse(content=[], stop_reason="end_turn")

    provider = RecordingProvider()
    response = ProviderBackedMessages(provider).create(
        model="override-model",
        max_tokens=123,
        temperature=0.2,
        system="system",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
    )

    assert response.stop_reason == "end_turn"
    assert provider.request == {
        "system": "system",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [],
        "model": "override-model",
        "max_tokens": 123,
        "temperature": 0.2,
    }


def test_provider_backed_messages_rejects_unknown_legacy_overrides():
    """不认识的 legacy SDK 参数必须 fail closed，避免抽象层继续失真。"""

    import pytest

    from agent.provider.legacy_adapter import ProviderBackedMessages
    from agent.provider.protocol import ProviderCapabilityError

    class RecordingProvider:
        def create(self, **kwargs):  # noqa: ANN001, ANN202
            raise AssertionError("unsupported legacy args must fail before provider call")

    with pytest.raises(ProviderCapabilityError, match="unsupported_legacy_message_args"):
        ProviderBackedMessages(RecordingProvider()).create(
            model="override-model",
            messages=[],
            tools=[],
            top_p=0.9,
        )


def test_dogfood_runners_do_not_import_provider_sdks_directly():
    """dogfood runner 只能依赖 provider factory，不能散落 SDK-specific client。"""

    global_source = Path("scripts/dogfood_global_real_api.py").read_text(encoding="utf-8")
    skill_source = Path("scripts/dogfood_skill_system.py").read_text(encoding="utf-8")
    combined = f"{global_source}\n{skill_source}"

    assert "import anthropic" not in combined
    assert "import openai" not in combined
    assert "anthropic.Anthropic" not in combined
    assert "openai.OpenAI" not in combined


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


def test_provider_capability_matrix_exposes_streaming_limitations():
    """四路 provider 的 streaming 能力必须显式可查，不能靠调用方猜。"""
    from agent.provider.config import AgentProviderConfig
    from agent.provider.factory import build_model_provider

    cases = {
        "anthropic_native": True,
        "anthropic_compatible": False,
        "openai_native": False,
        "openai_compatible": False,
    }

    for provider_type, supports_streaming in cases.items():
        config = AgentProviderConfig(
            provider_type=provider_type,
            provider_name=provider_type,
            api_key="secret-token-must-not-leak",
            api_key_env="OPENAI_API_KEY" if provider_type.startswith("openai") else "ANTHROPIC_API_KEY",
            base_url="https://example.invalid/v1" if "compatible" in provider_type else None,
            model="fake-model",
            max_tokens=64,
            timeout=3.0,
            supports_tools=True,
            supports_streaming=supports_streaming,
            auth_scheme="bearer",
            request_path="/v1/chat/completions" if provider_type.startswith("openai") else "/v1/messages",
            compatibility_mode="openai" if provider_type.startswith("openai") else "anthropic_messages",
        )

        provider = build_model_provider(config)

        assert provider is not None
        assert provider.supports_streaming is supports_streaming


def test_openai_compatible_streaming_fails_closed_without_http_fallback():
    """openai_compatible 不支持 streaming 时必须 fail closed，不能悄悄转 non-streaming。"""
    from agent.provider.config import AgentProviderConfig
    from agent.provider.factory import build_model_provider
    from agent.provider.protocol import ProviderCapabilityError

    class ForbiddenHTTPClient:
        def post(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
            raise AssertionError("streaming unsupported path must not call HTTP")

    config = AgentProviderConfig(
        provider_type="openai_compatible",
        provider_name="custom-openai-compatible",
        api_key="secret-token-must-not-leak",
        api_key_env="OPENAI_API_KEY",
        base_url="https://example.invalid/v1",
        model="gpt-compatible",
        max_tokens=64,
        timeout=3.0,
        supports_tools=True,
        supports_streaming=False,
        auth_scheme="bearer",
        request_path="/v1/chat/completions",
        compatibility_mode="openai",
    )
    provider = build_model_provider(config)
    provider._http = ForbiddenHTTPClient()  # type: ignore[attr-defined]

    with pytest.raises(ProviderCapabilityError, match="streaming_not_supported"):
        list(provider.stream(system="system", messages=[], tools=[]))
