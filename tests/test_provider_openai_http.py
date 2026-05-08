"""OpenAI-compatible HTTP adapter 测试。

使用 httpx.MockTransport 构造 fake HTTP endpoint，验证：
- request body 格式（messages / tools 转换）
- response normalization（text / tool_calls / finish_reason / usage）
- auth header
- 错误分类（401 / timeout / malformed）
- key 不泄露进异常
- custom request_path
"""

from __future__ import annotations

import json

import httpx
import pytest


def _config(**overrides):
    from agent.provider.config import AgentProviderConfig

    values: dict = {
        "provider_type": "openai_compatible",
        "api_key": "sk-test-openai-key-secret",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "https://openai-compat.example/api",
        "model": "gpt-compat",
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
# 工具 schema 转换测试
# ============================================================


def test_convert_tools_to_openai():
    from agent.provider.openai_http import convert_tools_to_openai

    anthropic_tools = [
        {
            "name": "read_file",
            "description": "Read a file from disk",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        {"name": "noop", "input_schema": {"type": "object", "properties": {}}},
    ]

    result = convert_tools_to_openai(anthropic_tools)

    assert len(result) == 2
    assert result[0]["type"] == "function"
    assert result[0]["function"]["name"] == "read_file"
    assert result[0]["function"]["description"] == "Read a file from disk"
    assert result[0]["function"]["parameters"] == anthropic_tools[0]["input_schema"]
    assert result[1]["function"]["parameters"] == {"type": "object", "properties": {}}


# ============================================================
# 消息转换测试
# ============================================================


def test_convert_messages_system_prompts_as_first_message():
    from agent.provider.openai_http import convert_messages_to_openai

    result = convert_messages_to_openai("You are helpful.", [])

    assert result[0] == {"role": "system", "content": "You are helpful."}


def test_convert_messages_user_text_passes_through():
    from agent.provider.openai_http import convert_messages_to_openai

    result = convert_messages_to_openai("", [
        {"role": "user", "content": "hello world"},
    ])

    assert len(result) == 1
    assert result[0] == {"role": "user", "content": "hello world"}


def test_convert_messages_user_with_text_blocks_flattens():
    from agent.provider.openai_http import convert_messages_to_openai

    result = convert_messages_to_openai("", [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "hello"},
                {"type": "text", "text": "world"},
            ],
        },
    ])

    assert result[0]["role"] == "user"
    assert result[0]["content"] == "hello\nworld"


def test_convert_messages_assistant_with_tool_calls():
    from agent.provider.openai_http import convert_messages_to_openai

    result = convert_messages_to_openai("", [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "I will read the file."},
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "read_file",
                    "input": {"path": "README.md"},
                },
            ],
        },
    ])

    assert result[0]["role"] == "assistant"
    assert result[0]["content"] == "I will read the file."
    assert len(result[0]["tool_calls"]) == 1
    tc = result[0]["tool_calls"][0]
    assert tc["id"] == "call_1"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "read_file"
    assert json.loads(tc["function"]["arguments"]) == {"path": "README.md"}


def test_convert_messages_user_with_tool_results_becomes_tool_messages():
    from agent.provider.openai_http import convert_messages_to_openai

    result = convert_messages_to_openai("", [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_1",
                    "content": "Contents of README.md",
                },
            ],
        },
    ])

    assert result[0]["role"] == "tool"
    assert result[0]["tool_call_id"] == "call_1"
    assert result[0]["content"] == "Contents of README.md"


# ============================================================
# Response normalization 测试
# ============================================================


def test_normalize_openai_text_response():
    from agent.provider.openai_http import normalize_openai_response

    raw = {
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "Hello!"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }

    response = normalize_openai_response(raw)

    assert response.stop_reason == "end_turn"
    assert response.content[0].type == "text"
    assert response.content[0].text == "Hello!"
    assert response.usage == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


def test_normalize_openai_tool_calls_response():
    from agent.provider.openai_http import normalize_openai_response
    from agent.provider.protocol import ToolUseBlock

    raw = {
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_abc123",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"location": "Beijing", "unit": "celsius"}',
                    },
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 20, "completion_tokens": 15, "total_tokens": 35},
    }

    response = normalize_openai_response(raw)

    assert response.stop_reason == "tool_use"
    assert response.content[0] == ToolUseBlock(
        id="call_abc123",
        name="get_weather",
        input={"location": "Beijing", "unit": "celsius"},
    )
    assert response.usage == {"input_tokens": 20, "output_tokens": 15, "total_tokens": 35}


def test_normalize_openai_malformed_tool_arguments_safe():
    from agent.provider.openai_http import normalize_openai_response

    raw = {
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "bad_tool",
                        "arguments": 'not valid json {{{',
                    },
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {},
    }

    response = normalize_openai_response(raw)
    tool_block = response.content[0]
    assert tool_block.name == "bad_tool"
    assert tool_block.input == {}


def test_normalize_openai_no_choices_raises():
    from agent.provider.openai_http import ProviderResponseError, normalize_openai_response

    with pytest.raises(ProviderResponseError, match="no_choices"):
        normalize_openai_response({"choices": []})


def test_normalize_openai_length_maps_to_max_tokens():
    from agent.provider.openai_http import normalize_openai_response

    raw = {
        "choices": [{"message": {"content": "abc"}, "finish_reason": "length"}],
    }
    response = normalize_openai_response(raw)
    assert response.stop_reason == "max_tokens"


# ============================================================
# HTTP adapter 测试
# ============================================================


def test_openai_compatible_http_request_body_has_correct_structure():
    from agent.provider.openai_http import OpenAICompatibleProvider

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.read().decode())
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {},
        })

    provider = OpenAICompatibleProvider(
        config=_config(request_path="v1/chat/completions"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = provider.create(
        system="You are a test assistant.",
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"name": "search", "description": "Search", "input_schema": {"type": "object"}}],
    )

    assert seen["url"] == "https://openai-compat.example/api/v1/chat/completions"
    assert seen["body"]["model"] == "gpt-compat"
    assert seen["body"]["max_tokens"] == 64
    assert seen["body"]["messages"][0] == {"role": "system", "content": "You are a test assistant."}
    assert seen["body"]["messages"][1] == {"role": "user", "content": "hello"}
    assert len(seen["body"]["tools"]) == 1
    assert seen["body"]["tools"][0]["type"] == "function"

    assert response.content[0].text == "ok"


def test_openai_compatible_http_bearer_auth_header():
    from agent.provider.openai_http import OpenAICompatibleProvider

    seen_auth: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        })

    provider = OpenAICompatibleProvider(
        config=_config(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    provider.create(system="", messages=[{"role": "user", "content": "hi"}], tools=[])

    assert seen_auth["authorization"] == "Bearer sk-test-openai-key-secret"


def test_openai_compatible_http_401_no_key_leak():
    from agent.provider.openai_http import OpenAICompatibleProvider
    from agent.provider.protocol import ProviderAuthError

    provider = OpenAICompatibleProvider(
        config=_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, text="bad sk-test-openai-key-secret")
            )
        ),
    )

    with pytest.raises(ProviderAuthError) as excinfo:
        provider.create(system="", messages=[{"role": "user", "content": "hi"}], tools=[])

    assert "sk-test-openai-key-secret" not in str(excinfo.value)
    assert "401" in str(excinfo.value)


def test_openai_compatible_http_timeout_is_classified():
    from agent.provider.openai_http import OpenAICompatibleProvider
    from agent.provider.protocol import ProviderTimeoutError

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout with sk-test-openai-key-secret")

    provider = OpenAICompatibleProvider(
        config=_config(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ProviderTimeoutError) as excinfo:
        provider.create(system="", messages=[{"role": "user", "content": "hi"}], tools=[])

    assert "sk-test-openai-key-secret" not in str(excinfo.value)


def test_openai_compatible_http_malformed_json_is_classified():
    from agent.provider.openai_http import OpenAICompatibleProvider
    from agent.provider.protocol import ProviderResponseError

    provider = OpenAICompatibleProvider(
        config=_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"not json")
            )
        ),
    )

    with pytest.raises(ProviderResponseError, match="malformed_json"):
        provider.create(system="", messages=[{"role": "user", "content": "hi"}], tools=[])


def test_openai_compatible_http_custom_request_path():
    from agent.provider.openai_http import OpenAICompatibleProvider

    seen_url: str = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_url
        seen_url = str(request.url)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        })

    provider = OpenAICompatibleProvider(
        config=_config(request_path="openai/deployments/gpt/chat/completions"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    provider.create(system="", messages=[{"role": "user", "content": "hi"}], tools=[])

    assert seen_url == "https://openai-compat.example/api/openai/deployments/gpt/chat/completions"


def test_openai_compatible_http_empty_request_path():
    from agent.provider.openai_http import OpenAICompatibleProvider

    seen_url: str = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_url
        seen_url = str(request.url)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        })

    provider = OpenAICompatibleProvider(
        config=_config(request_path=""),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    provider.create(system="", messages=[{"role": "user", "content": "hi"}], tools=[])

    assert seen_url == "https://openai-compat.example/api"


def test_openai_compatible_http_tool_calls_roundtrip():
    from agent.provider.openai_http import OpenAICompatibleProvider
    from agent.provider.protocol import ToolUseBlock

    provider = OpenAICompatibleProvider(
        config=_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "Let me check.",
                        "tool_calls": [{
                            "id": "call_xyz",
                            "type": "function",
                            "function": {
                                "name": "search",
                                "arguments": '{"query": "weather"}',
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
        messages=[{"role": "user", "content": "What is the weather?"}],
        tools=[{"name": "search", "input_schema": {"type": "object"}}],
    )

    assert response.stop_reason == "tool_use"
    assert response.content[0].text == "Let me check."
    assert response.content[1] == ToolUseBlock(
        id="call_xyz", name="search", input={"query": "weather"}
    )
