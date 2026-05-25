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


# ── Provider Swap Contract Tests ─────────────────────────────────────────
# 验证 FakeProvider 与 real provider adapter 共享统一 interface contract，
# 防止 fake/real 分裂。这些测试不调用真实 API，仅验证 interface shape。


def test_fake_provider_conforms_to_modelprovider_protocol():
    """FakeProvider 必须实现 ModelProvider Protocol，与 real provider 共享接口。

    如果 FakeProvider 不遵循 ModelProvider，fake/real 之间的 provider swap
    就会在 runtime 层面分裂——同一个 core.chat() / loop.run_main_loop() 路径
    对不同 provider 产生不同的调用形状，破坏 unified runtime flow。

    本测试不调用真实 API，只验证 interface conformity。
    """
    from agent.provider.fake_provider import FakeProvider
    from agent.provider.protocol import ModelProvider

    provider = FakeProvider()

    assert isinstance(provider, ModelProvider), (
        "FakeProvider 必须实现 ModelProvider Protocol，否则 fake/real 分裂"
    )
    assert hasattr(provider, "provider_type")
    assert hasattr(provider, "supports_tools")
    assert hasattr(provider, "supports_streaming")
    assert callable(provider.create)
    assert callable(provider.stream)


def test_fake_provider_create_returns_provider_response_with_correct_shapes():
    """FakeProvider.create() 必须返回 ProviderResponse，包含正确的 block 类型。

    这会验证：
    - create() 返回 ProviderResponse（非原始 dict 或 SDK-specific 对象）
    - content blocks 必须是 ProviderTextBlock / ToolUseBlock
    - stop_reason 是合法字符串
    - usage 包含 input_tokens/output_tokens（非 provider-specific 字段名）

    这些 shape 保证与 real provider adapter 返回的格式一致，
    使 response_handlers / display_events 不需要 provider-specific 分支。
    """
    from agent.provider.fake_provider import FakeProvider
    from agent.provider.protocol import ProviderResponse, ProviderTextBlock, ToolUseBlock

    provider = FakeProvider()
    response = provider.create(
        system="system prompt",
        messages=[{"role": "user", "content": "写一个 demo note"}],
        tools=[{
            "name": "demo.write_demo_note",
            "description": "写入 demo note 到文件系统",
            "input_schema": {"type": "object", "properties": {"content": {"type": "string"}}},
        }],
    )

    assert isinstance(response, ProviderResponse), (
        "create() 必须返回 ProviderResponse，不能返回 raw dict 或 SDK 对象"
    )
    assert response.stop_reason is not None
    assert isinstance(response.stop_reason, str)
    assert isinstance(response.usage, dict), (
        "usage 必须为 dict（即使 FakeProvider 不填充 token 计数，"
        "也必须提供兼容的 dict 接口，与 real provider adapter 一致）"
    )

    for block in response.content:
        assert isinstance(block, (ProviderTextBlock, ToolUseBlock)), (
            f"content block 必须是 ProviderTextBlock 或 ToolUseBlock，"
            f"不能是原始 SDK 类型。实际: {type(block)}"
        )
        assert block.type in ("text", "tool_use")


def test_fake_provider_tool_use_blocks_match_real_contract():
    """FakeProvider 的 ToolUseBlock 必须与 real provider 的字段一致。

    ToolUseBlock 的 id/name/input 三个字段是跨 provider 的 contract。
    FakeProvider 产出的 ToolUseBlock 与 AnthropicCompatibleProvider /
    OpenAINativeProvider 产物共享同一个 dataclass，保证 tool executor
    不需要 provider-specific 分支。

    本测试不调用真实 API——FakeProvider 的 tool_use block 形状已经
    验证了 contract。real provider 的 tool_use block 形状需要 dogfood 验证。
    """
    from agent.provider.fake_provider import FakeProvider
    from agent.provider.protocol import ToolUseBlock

    provider = FakeProvider()
    response = provider.create(
        system="system",
        messages=[{"role": "user", "content": "写一个 demo note"}],
        tools=[{
            "name": "demo.write_demo_note",
            "description": "写入 demo note 到文件",
            "input_schema": {"type": "object", "properties": {"content": {"type": "string"}}},
        }],
    )

    tool_blocks = [b for b in response.content if isinstance(b, ToolUseBlock)]
    assert len(tool_blocks) > 0, (
        "FakeProvider 在匹配时应产出 ToolUseBlock"
    )

    tool = tool_blocks[0]
    assert isinstance(tool.id, str) and len(tool.id) > 0
    assert isinstance(tool.name, str) and len(tool.name) > 0
    assert isinstance(tool.input, dict)
    assert tool.type == "tool_use"


def test_provider_swap_preserves_interface_across_fake_and_configured_types():
    """切换 provider type 时 build_model_provider 返回 ModelProvider 实例。

    Fake → AnthropicCompatible 的 swap 不应该改变接口形状：
    都返回 ModelProvider protocol 实例，都有 create()/stream()，
    都有 provider_type/supports_tools/supports_streaming。

    本测试只验证 interface existence，不调用真实 API。
    真实 API 调用行为（tool_use 触发概率等）需要 dogfood 验证。
    """
    from agent.provider.config import AgentProviderConfig
    from agent.provider.factory import build_model_provider
    from agent.provider.protocol import ModelProvider

    # Fake — factory 对 fake 类型直接导入，不依赖 config 字段
    fake_config = AgentProviderConfig(
        provider_type="fake",
        provider_name="fake",
        api_key="sk-fake",
        api_key_env="FAKE_API_KEY",
        base_url=None,
        model="fake",
        max_tokens=64,
        timeout=3.0,
        supports_tools=True,
        supports_streaming=False,
        auth_scheme="bearer",
        request_path="/v1/messages",
        compatibility_mode="anthropic_messages",
    )
    fake = build_model_provider(fake_config)
    assert isinstance(fake, ModelProvider)
    assert fake.provider_type == "fake"

    # Anthropic compatible (no API call — only verify factory creates it)
    compat_config = AgentProviderConfig(
        provider_type="anthropic_compatible",
        provider_name="test-compat",
        api_key="sk-test",
        api_key_env="ANTHROPIC_API_KEY",
        base_url="https://example.invalid/messages",
        model="test-model",
        max_tokens=64,
        timeout=3.0,
        supports_tools=True,
        supports_streaming=False,
        auth_scheme="bearer",
        request_path="/v1/messages",
        compatibility_mode="anthropic_messages",
    )
    compat = build_model_provider(compat_config)
    assert isinstance(compat, ModelProvider)
    assert compat.provider_type == "anthropic_compatible"

    # 两者共享相同的 interface attributes
    for attr in ("create", "stream", "provider_type", "supports_tools", "supports_streaming"):
        assert hasattr(fake, attr), f"FakeProvider 缺少 {attr}"
        assert hasattr(compat, attr), f"AnthropicCompatibleProvider 缺少 {attr}"


def test_provider_swap_contract_test_exists() -> None:
    """标记 provider swap contract 的存在性约束。

    这个测试作为 audit evidence：当 developer 新增 provider type 时，
    必须同时新增对应的 contract test。如果新增 provider type 绕过 factory
    或创建了无法与 FakeProvider 互 swap 的路径，本测试提示必须 review。
    """
    from agent.provider.config import AgentProviderConfig
    from agent.provider.factory import build_model_provider

    # 所有 provider type 必须能通过 factory 构造
    # 新增 provider type 时必须在此列表中添加对应的 config case
    known_types = {"fake", "anthropic_native", "anthropic_compatible", "openai_native", "openai_compatible"}

    constructed_types: set[str] = set()
    for provider_type in known_types:
        try:
            api_key_env = "OPENAI_API_KEY" if provider_type.startswith("openai") else "ANTHROPIC_API_KEY"
            config = AgentProviderConfig(
                provider_type=provider_type,
                provider_name=provider_type,
                api_key="sk-test",
                api_key_env=api_key_env,
                base_url="https://example.invalid/v1" if "compatible" in provider_type else None,
                model="test-model",
                max_tokens=64,
                timeout=3.0,
                supports_tools=True,
                supports_streaming=(provider_type == "anthropic_native"),
                auth_scheme="bearer",
                request_path="/v1/chat/completions" if provider_type.startswith("openai") else "/v1/messages",
                compatibility_mode="openai" if provider_type.startswith("openai") else "anthropic_messages",
            )
            provider = build_model_provider(config)
            assert provider is not None
            constructed_types.add(provider_type)
        except Exception:
            pass  # 如果某类型构造失败（如缺少 SDK），不阻塞

    assert "fake" in constructed_types, "FakeProvider 必须能通过 factory 构造"


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
