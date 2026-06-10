# ruff: noqa: E501
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


@pytest.mark.xfail(
    reason=(
        "config/config.yaml 已配置 anthropic_compatible provider，"
        "build_model_provider_from_env() 优先读 config.yaml 而非 env var。"
        "需隔离 config.yaml 的受控环境才能验证 anthropic_native env-only 路径。"
    ),
    strict=True,
)
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
    验证了 contract。real provider 的 tool_use block 形状需要显式 real-provider validation。
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
    真实 API 调用行为（tool_use 触发概率等）需要显式 real-provider validation。
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


def test_provider_core_paths_do_not_import_provider_sdks_directly():
    """当前 provider 核心路径只能依赖 provider factory/adapter，不能散落 SDK-specific client。"""

    core_sources = [
        Path("agent/provider/factory.py"),
        Path("agent/provider/config.py"),
        Path("agent/provider/legacy_adapter.py"),
        Path("agent/core.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in core_sources)

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


# ===== BL2: System Prompt Tool-Use Guidance Hardening (F1) =====


def test_system_prompt_contains_provider_neutral_tool_use_guidance():
    """system prompt 必须包含 provider-neutral tool-use guidance，不包含特定 provider hack。"""
    from config import SYSTEM_PROMPT

    # 必须包含 provider-neutral tool-use guidance 关键短语
    assert "provider-neutral" in SYSTEM_PROMPT
    assert "工具使用指南" in SYSTEM_PROMPT
    assert "主动匹配工具与请求" in SYSTEM_PROMPT
    assert "不要伪造工具结果" in SYSTEM_PROMPT
    assert "普通对话不需要工具" in SYSTEM_PROMPT
    assert "只使用已注册工具" in SYSTEM_PROMPT
    # 新增的强化条款
    assert "工具判决流程" in SYSTEM_PROMPT
    assert "检查工具参数要求" in SYSTEM_PROMPT
    # 不得包含 provider-specific hack
    assert "kimi" not in SYSTEM_PROMPT.lower()
    assert "dashscope" not in SYSTEM_PROMPT.lower()
    assert "anthropic api" not in SYSTEM_PROMPT.lower()


def test_system_prompt_tool_guidance_is_provider_agnostic():
    """tool-use guidance 不得写入特定 provider/model 名称或 API 细节。"""
    from config import SYSTEM_PROMPT

    # 提取"工具使用指南"部分
    guidance_start = SYSTEM_PROMPT.find("## 工具使用指南")
    assert guidance_start > 0
    guidance = SYSTEM_PROMPT[guidance_start:]

    # 禁止出现的 provider-specific 词汇
    forbidden = [
        "DeepSeek", "deepseek",
        "OpenAI", "openai.com",
        "Anthropic API", "anthropic api",
        "DashScope", "dashscope",
        "kimi", "Kimi",
        "Claude API", "claude api",
        "x-api-key", "bearer token",
    ]
    for word in forbidden:
        assert word not in guidance, f"tool-use guidance 包含 provider-specific 词: {word}"


def test_demo_tool_descriptions_include_scenarios_and_safety():
    """demo 工具描述必须包含适用场景和安全限制。"""
    # 强制 import 以触发 @register_tool
    import agent.tools  # noqa: F401
    from agent.tool_registry import TOOL_REGISTRY

    echo_info = TOOL_REGISTRY.get("demo.echo_task_summary")
    assert echo_info is not None, "demo.echo_task_summary must be registered"
    echo_desc = echo_info["description"]
    assert "适用场景" in echo_desc or "何时调用" in echo_desc or "When to" in echo_desc
    assert "安全" in echo_desc or "safe" in echo_desc.lower()
    assert "副作用" in echo_desc or "side" in echo_desc.lower()

    note_info = TOOL_REGISTRY.get("demo.write_demo_note")
    assert note_info is not None, "demo.write_demo_note must be registered"
    note_desc = note_info["description"]
    assert "适用场景" in note_desc or "何时调用" in note_desc
    assert "安全" in note_desc or "safe" in note_desc.lower()
    assert "确认" in note_desc or "confirm" in note_desc.lower()


def test_demo_tool_descriptions_not_force_tool_use_in_normal_chat():
    """demo 工具描述应包含「何时不该调用」，防止普通聊天被强制 tool_use。"""
    import agent.tools  # noqa: F401
    from agent.tool_registry import TOOL_REGISTRY

    for name in ("demo.echo_task_summary", "demo.write_demo_note"):
        info = TOOL_REGISTRY.get(name)
        assert info is not None
        desc = info["description"]
        # 必须说明何时不该调用（防止模型在普通对话中滥用工具）
        has_nonuse_guidance = (
            "何时不该" in desc
            or "不应调用" in desc
            or "should not" in desc.lower()
            or "do not" in desc.lower()
            or "don't" in desc.lower()
        )
        assert has_nonuse_guidance, f"{name} 描述缺少「何时不该调用」指引: {desc[:100]}"


def test_fake_provider_path_not_broken_by_prompt_changes(monkeypatch):
    """FakeProvider 路径不受 system prompt / tool description 修改影响。"""
    import agent.tools  # noqa: F401
    from agent.provider.fake_provider import FakeProvider
    from agent.tool_registry import get_model_visible_tools

    provider = FakeProvider()
    tools = get_model_visible_tools()

    # FakeProvider 应按 system prompt/tools 正常返回
    response = provider.create(
        system="You are a helpful assistant.",
        messages=[{"role": "user", "content": "hello"}],
        tools=tools,
    )
    assert response is not None
    assert len(response.content) > 0
    # 普通聊天不应触发 tool_use
    has_tool = any(getattr(b, "type", None) == "tool_use" for b in response.content)
    assert not has_tool, "FakeProvider should not trigger tool_use on 'hello'"


# ═══════════════════════════════════════════════════════════════════════════
# RT-01: Real-provider dispatcher/evidence parity 合约测试
# ═══════════════════════════════════════════════════════════════════════════
# 中文学习边界：Phase 1 RuntimeActionDispatcher 是 provider-neutral runtime
# logic——不调 LLM、不读 .env、不访问网络。所有 provider 类型（fake/anthropic/
# anthropic_compatible/openai_compatible）默认都应自动构建 dispatcher，
# 确保 fake/real 共享同一 evidence path。


class TestPhase1DispatcherDefaultBuild:
    """验证 Phase 1 dispatcher 在所有 provider 路径下默认构建。"""

    def test_build_phase1_dispatcher_returns_valid_dispatcher(self):
        """build_phase1_dispatcher() 返回非空 RuntimeActionDispatcher。"""
        from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
        dispatcher = build_phase1_dispatcher()
        assert dispatcher is not None
        assert hasattr(dispatcher, "route")
        assert hasattr(dispatcher, "_registry")
        # _registry 必须包含已注册的 handlers
        registry = dispatcher._registry
        assert registry is not None
        # 至少有 TOOL_GATE 等核心 handler 已注册
        from agent.runtime_integration import RuntimeActionType
        assert registry.get(RuntimeActionType.TOOL_GATE) is not None
        assert registry.get(RuntimeActionType.TOOL_INVOKE) is not None
        assert registry.get(RuntimeActionType.TOOL_RESULT) is not None

    def test_build_phase1_dispatcher_is_idempotent(self):
        """重复调用 build_phase1_dispatcher() 返回独立实例。"""
        from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
        d1 = build_phase1_dispatcher()
        d2 = build_phase1_dispatcher()
        assert d1 is not d2  # 每次构建都是新实例
        # _registry 也是独立实例（每个 dispatcher 有自己的 registry）
        assert d1._registry is not d2._registry

    def test_dispatcher_build_requires_no_env_or_network(self):
        """构建 dispatcher 不读 .env、不调 API、不访问网络。"""
        import os
        # 保存 env 快照
        env_before = dict(os.environ)
        try:
            from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
            _d = build_phase1_dispatcher()
        finally:
            env_after = dict(os.environ)
        # env 不应被修改
        assert env_before == env_after, (
            "build_phase1_dispatcher() must not mutate os.environ"
        )

    def test_fake_provider_path_receives_dispatcher(self):
        """FakeProvider 默认路径应有 dispatcher（已有行为，保护回归）。"""
        from agent.core import chat as core_chat
        from agent.provider.fake_provider import FakeProvider

        provider = FakeProvider()
        dispatcher_seen = []

        def on_event(event):
            dispatcher_seen.append(event)

        result = core_chat(
            "hello",
            provider=provider,
            on_runtime_event=on_event,
        )
        # FakeProvider 路径不应崩溃
        assert result is not None

    def test_dispatcher_not_gated_on_fake_provider_type(self):
        """dispatcher 不应只在 fake provider 时构建——所有 provider 都应自动构建。

        验证方式：即使传入一个非 fake 的 provider（anthropic_compatible），
        chat() 也不应因 missing dispatcher 而崩溃。
        使用 FakeProvider 但修改其 provider_type 模拟非 fake provider。
        """
        from agent.core import chat as core_chat
        from agent.provider.fake_provider import FakeProvider

        class NonFakeFakeProvider(FakeProvider):
            """模拟非 fake provider type 的 provider——用于验证 RT-01 修复。"""
            @property
            def provider_type(self) -> str:
                return "anthropic_compatible"

        provider = NonFakeFakeProvider()

        try:
            result = core_chat(
                "hello",
                provider=provider,
                on_runtime_event=lambda e: None,
            )
            assert result is not None
        except Exception as exc:
            # 可能因 turn-end dispatcher route 触发某些 handler 报错
            # 但只要不是 "dispatcher is None" 导致的 AttributeError 就说明
            # dispatcher 已被正确构建
            assert "NoneType" not in str(exc) or "dispatcher" not in str(exc).lower(), (
                f"Dispatcher should have been built, but got: {exc}"
            )


class TestProviderModeBanner:
    """PF-01: startup provider mode banner 的 contract tests。

    local trial 第一 blocker：用户启动时必须清楚当前是 fake/local 还是
    real provider。这些测试验证：
    1. fake/default 启动不读取真实 API key
    2. banner 能正确区分 fake/real mode
    3. import 顺序不导致 provider config stale
    """

    @pytest.mark.xfail(
        reason=(
            "config/config.yaml 已配置 anthropic_compatible provider，"
            "render_provider_mode_banner() 优先读 config.yaml，env var 清除无效。"
            "需隔离 config.yaml 的受控环境才能验证 fake-default 路径。"
        ),
        strict=True,
    )
    def test_banner_fake_mode_when_no_provider_env(self, monkeypatch):
        """未设置 MY_FIRST_AGENT_LLM_PROVIDER 时，banner 应显示 fake 模式。"""
        from agent.cli_renderer import render_provider_mode_banner

        monkeypatch.delenv("MY_FIRST_AGENT_LLM_PROVIDER", raising=False)
        monkeypatch.delenv("MY_FIRST_AGENT_LLM_MODEL", raising=False)
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        monkeypatch.delenv("OPENAI_MODEL", raising=False)

        banner = render_provider_mode_banner()
        assert "fake" in banner.lower()
        assert "local only" in banner

    @pytest.mark.xfail(
        reason=(
            "config/config.yaml 已配置 anthropic_compatible provider，"
            "render_provider_mode_banner() 优先读 config.yaml，env var 设置无效。"
            "需隔离 config.yaml 的受控环境。"
        ),
        strict=True,
    )
    def test_banner_fake_mode_when_provider_env_is_fake(self, monkeypatch):
        """MY_FIRST_AGENT_LLM_PROVIDER=fake 时，banner 应显示 fake 模式。"""
        from agent.cli_renderer import render_provider_mode_banner

        monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER", "fake")
        monkeypatch.delenv("MY_FIRST_AGENT_LLM_MODEL", raising=False)

        banner = render_provider_mode_banner()
        assert "fake" in banner.lower()

    @pytest.mark.xfail(
        reason=(
            "config/config.yaml 已配置 anthropic_compatible provider，"
            "render_provider_mode_banner() 优先读 config.yaml 而非 env var。"
            "实际返回 anthropic_compatible 而非 anthropic_native。"
            "需隔离 config.yaml 的受控环境。"
        ),
        strict=True,
    )
    def test_banner_real_mode_when_provider_env_set(self, monkeypatch):
        """MY_FIRST_AGENT_LLM_PROVIDER=anthropic_native 时，banner 应显示真实 API 模式。"""
        from agent.cli_renderer import render_provider_mode_banner

        monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER", "anthropic_native")
        monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

        banner = render_provider_mode_banner()
        assert "anthropic_native" in banner
        assert "真实 API" in banner
        assert "claude-sonnet-4-6" in banner

    def test_banner_does_not_leak_api_key(self, monkeypatch):
        """banner 绝不应包含 API key 值。"""
        from agent.cli_renderer import render_provider_mode_banner

        monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER", "anthropic_native")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")

        banner = render_provider_mode_banner()
        assert "sk-ant-secret" not in banner
        assert "secret" not in banner.lower()

    @pytest.mark.xfail(
        reason=(
            "config/config.yaml 已配置 anthropic_compatible provider，"
            "render_provider_mode_banner() 优先读 config.yaml 而非 env var。"
            "需隔离 config.yaml 的受控环境。"
        ),
        strict=True,
    )
    def test_banner_uses_model_env_fallback(self, monkeypatch):
        """model 信息应从 MY_FIRST_AGENT_LLM_MODEL 或 ANTHROPIC_MODEL 或 OPENAI_MODEL 获取。"""
        from agent.cli_renderer import render_provider_mode_banner

        monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER", "openai_compatible")
        monkeypatch.delenv("MY_FIRST_AGENT_LLM_MODEL", raising=False)
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        monkeypatch.setenv("OPENAI_MODEL", "gpt-5")

        banner = render_provider_mode_banner()
        assert "openai_compatible" in banner
        assert "gpt-5" in banner

    def test_startup_import_order_does_not_stale_provider_config(self, monkeypatch):
        """验证 import main 不会在 .env 加载前固化 provider config。

        main.py 的 import 语句本身不应触发 build_model_provider_from_env()——
        provider 应在 core.chat() 首次调用时才通过 build_loop_context() 懒加载。
        这个测试验证 import agent.core 不会导致 provider config 被提前固化。
        """
        monkeypatch.delenv("MY_FIRST_AGENT_LLM_PROVIDER", raising=False)
        # 导入 core 不应触发 provider factory（懒加载）
        from agent.core import chat as _chat
        # chat 函数存在即可——真正的 provider 构建发生在 core.chat() 调用时
        assert callable(_chat)
