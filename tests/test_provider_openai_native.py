"""OpenAI native provider 测试。

使用 httpx.MockTransport 构造 fake HTTP endpoint，验证：
- factory 构建 openai_native
- 默认 base_url 正确（https://api.openai.com/v1）
- bearer auth
- request body 格式
- response normalization（text / tool_calls）
- 错误分类（401 / timeout / malformed）
- key 不泄露进异常
- 不做 Responses API（明确限制）
"""

from __future__ import annotations

import httpx
import pytest


def _config(**overrides):
    from agent.provider.config import AgentProviderConfig

    values: dict = {
        "provider_type": "openai_native",
        "api_key": "sk-test-openai-native-secret",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": None,
        "model": "gpt-test",
        "max_tokens": 64,
        "timeout": 3.0,
        "supports_tools": True,
        "supports_streaming": False,
        "auth_scheme": "bearer",
        "request_path": "/v1/chat/completions",
        "compatibility_mode": "openai",
    }
    values.update(overrides)
    return AgentProviderConfig(**values)


# ============================================================
# factory 构建
# ============================================================


def test_openai_native_factory_builds_with_defaults():
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


# ============================================================
# URL / auth
# ============================================================


def test_openai_native_default_url_is_openai_v1():
    from agent.provider.openai_native import OpenAINativeProvider

    seen_url: str = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_url
        seen_url = str(request.url)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        })

    provider = OpenAINativeProvider(
        config=_config(base_url=None, request_path="/v1/chat/completions"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    provider.create(system="", messages=[{"role": "user", "content": "hi"}], tools=[])
    assert seen_url == "https://api.openai.com/v1/chat/completions"


def test_openai_native_custom_base_url_overrides_default():
    from agent.provider.openai_native import OpenAINativeProvider

    seen_url: str = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_url
        seen_url = str(request.url)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        })

    provider = OpenAINativeProvider(
        config=_config(base_url="https://custom.example/api"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    provider.create(system="", messages=[{"role": "user", "content": "hi"}], tools=[])
    assert seen_url == "https://custom.example/api/v1/chat/completions"


def test_openai_native_bearer_auth():
    from agent.provider.openai_native import OpenAINativeProvider

    seen_auth: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        })

    provider = OpenAINativeProvider(
        config=_config(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    provider.create(system="", messages=[{"role": "user", "content": "hi"}], tools=[])

    assert seen_auth["authorization"] == "Bearer sk-test-openai-native-secret"


# ============================================================
# response normalization
# ============================================================


def test_openai_native_text_response_normalization():
    from agent.provider.openai_native import OpenAINativeProvider

    provider = OpenAINativeProvider(
        config=_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
                "choices": [{
                    "message": {"role": "assistant", "content": "Hello from native!"},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }))
        ),
    )

    response = provider.create(
        system="You are helpful.",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
    )

    assert response.stop_reason == "end_turn"
    assert response.content[0].type == "text"
    assert response.content[0].text == "Hello from native!"
    assert response.usage == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


def test_openai_native_tool_calls_normalization():
    from agent.provider.openai_native import OpenAINativeProvider
    from agent.provider.protocol import ToolUseBlock

    provider = OpenAINativeProvider(
        config=_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "Let me check.",
                        "tool_calls": [{
                            "id": "call_native_1",
                            "type": "function",
                            "function": {
                                "name": "search",
                                "arguments": '{"query": "test"}',
                            },
                        }],
                    },
                    "finish_reason": "tool_calls",
                }],
                "usage": {},
            }))
        ),
    )

    response = provider.create(
        system="",
        messages=[{"role": "user", "content": "search for test"}],
        tools=[{"name": "search", "input_schema": {"type": "object"}}],
    )

    assert response.stop_reason == "tool_use"
    assert response.content[0].text == "Let me check."
    assert response.content[1] == ToolUseBlock(
        id="call_native_1", name="search", input={"query": "test"}
    )


# ============================================================
# 错误分类 / no key leak
# ============================================================


def test_openai_native_401_no_key_leak():
    from agent.provider.openai_native import OpenAINativeProvider
    from agent.provider.protocol import ProviderAuthError

    provider = OpenAINativeProvider(
        config=_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, text="bad sk-test-openai-native-secret")
            )
        ),
    )

    with pytest.raises(ProviderAuthError) as excinfo:
        provider.create(system="", messages=[{"role": "user", "content": "hi"}], tools=[])

    assert "sk-test-openai-native-secret" not in str(excinfo.value)
    assert "401" in str(excinfo.value)


def test_openai_native_timeout_no_key_leak():
    from agent.provider.openai_native import OpenAINativeProvider
    from agent.provider.protocol import ProviderTimeoutError

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout with sk-test-openai-native-secret")

    provider = OpenAINativeProvider(
        config=_config(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ProviderTimeoutError) as excinfo:
        provider.create(system="", messages=[{"role": "user", "content": "hi"}], tools=[])

    assert "sk-test-openai-native-secret" not in str(excinfo.value)


def test_openai_native_malformed_json_no_leak():
    from agent.provider.openai_native import OpenAINativeProvider
    from agent.provider.protocol import ProviderResponseError

    provider = OpenAINativeProvider(
        config=_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, content=b"not json with sk-test-openai-native-secret"
                )
            )
        ),
    )

    with pytest.raises(ProviderResponseError, match="malformed_json"):
        provider.create(system="", messages=[{"role": "user", "content": "hi"}], tools=[])


def test_openai_native_malformed_tool_arguments_safe():
    from agent.provider.openai_native import OpenAINativeProvider

    provider = OpenAINativeProvider(
        config=_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "tool_calls": [{
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "bad_tool",
                                "arguments": "not valid json {{{",
                            },
                        }],
                    },
                    "finish_reason": "tool_calls",
                }],
            }))
        ),
    )

    response = provider.create(
        system="",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
    )

    assert response.content[0].name == "bad_tool"
    assert response.content[0].input == {}


# ============================================================
# 配置
# ============================================================


def test_openai_native_config_loads_from_env_without_base_url():
    from agent.provider.config import load_agent_provider_config

    env = {
        "MY_FIRST_AGENT_LLM_PROVIDER": "openai_native",
        "OPENAI_API_KEY": "sk-secret-native",
        "OPENAI_MODEL": "gpt-4o",
    }

    config = load_agent_provider_config(env=env)

    assert config.provider_type == "openai_native"
    assert config.api_key == "sk-secret-native"
    assert config.base_url is None
    assert config.request_path == "/v1/chat/completions"
    assert config.auth_scheme == "bearer"
    assert "sk-secret-native" not in repr(config.redacted_summary())


def test_openai_native_no_key_raises():
    from agent.provider.config import ProviderConfigurationError, load_agent_provider_config

    with pytest.raises(ProviderConfigurationError, match="api_key_missing"):
        load_agent_provider_config("openai_native", env={})


def test_openai_native_no_model_raises():
    from agent.provider.config import ProviderConfigurationError, load_agent_provider_config

    with pytest.raises(ProviderConfigurationError, match="model_missing"):
        load_agent_provider_config("openai_native", env={"OPENAI_API_KEY": "sk-test"})
