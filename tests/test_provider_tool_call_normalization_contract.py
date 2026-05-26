"""Provider Tool-Call Normalization 合同测试（Phase 3）。

本文件测试跨 provider 的 tool-call normalization 合同不变量。
所有测试都用 fake/stub provider response objects，不调用真实 API。

合同不变量（来自 AD docs/design/provider-tool-call-normalization-contract.md）：

1. ToolUseBlock 始终是 frozen dataclass（不可变）
2. ``input`` 始终是 dict（不可能是 None / str / list）
3. ``name`` 始终是 str（不可能是 None）
4. ``id`` 始终是 str（缺失时用空字符串）
5. malformed JSON arguments → ``{}``（不抛异常，不泄露原始字符串）
6. 缺失 tool name → ProviderResponseError
7. ProviderResponse.content 顺序与原始 response 一致
8. usage 按统一 key 标准化

为什么跨 provider contract 重要：
- Tool Pipeline / confirmation / audit / dispatcher 不感知 provider-specific 格式
- Provider adapter 之间的差异由 normalization 层吸收
- contract 测试防止 provider-specific bug 漏到 runtime
- 新增 provider 时只需增加 normalization 路径，不改 Tool Pipeline 主流程

中文学习边界：
- 合同不变量是 L3 evidence——不依赖真实 API 也能验证
- fake/stub input 构造的是 provider SDK 可能返回的 object 形状
- 测试不模拟完整 HTTP 交互，只验证 normalization 函数行为
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from agent.provider.protocol import (
    ProviderResponseError,
    ProviderTextBlock,
    ToolUseBlock,
)

# =========================================================================
# 不变量 1: ToolUseBlock 是不可变 frozen dataclass
# =========================================================================


def test_tool_use_block_is_frozen():
    """ToolUseBlock 必须是不可变的——frozen dataclass，字段不可修改。

    为什么：Tool Pipeline 消费 ToolUseBlock 后不应被下游修改。
    不可变性确保 audit trail 的完整性和多 consumer 的线程安全。
    """
    block = ToolUseBlock(id="toolu_1", name="read_file", input={"path": "a.txt"})
    with pytest.raises(FrozenInstanceError):
        block.name = "write_file"  # type: ignore[misc]


# =========================================================================
# 不变量 2-4: 字段类型保证
# =========================================================================


def test_tool_use_block_defaults():
    """ToolUseBlock 构造时即可设定默认值。

    id 和 name 默认为空字符串，input 默认为空 dict。
    """
    block = ToolUseBlock(id="", name="", input={})
    assert block.id == ""
    assert block.name == ""
    assert block.input == {}
    assert block.type == "tool_use"


def test_tool_use_block_type_never_changes():
    """ToolUseBlock.type 始终返回 'tool_use'——这是类型鉴别器字段。"""
    block = ToolUseBlock(id="x", name="y", input={})
    assert block.type == "tool_use"


# =========================================================================
# 不变量 5: Anthropic tool_use normalization
# =========================================================================


def test_anthropic_normalize_text_content():
    """Anthropic 文本响应应产出 ProviderTextBlock。"""
    from agent.provider.normalize import normalize_anthropic_response

    raw = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="hello world")],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=5, output_tokens=3),
    )
    response = normalize_anthropic_response(raw, raw_provider_name="anthropic_native")
    assert response.content == [ProviderTextBlock(text="hello world")]
    assert response.stop_reason == "end_turn"
    assert response.usage == {"input_tokens": 5, "output_tokens": 3}
    assert response.raw_provider_name == "anthropic_native"


def test_anthropic_normalize_tool_use_with_dict_input():
    """Anthropic tool_use 块 dict input 应原样保留。"""
    from agent.provider.normalize import normalize_anthropic_response

    raw = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                id="toolu_001",
                name="read_file",
                input={"path": "/tmp/test.txt", "encoding": "utf-8"},
            ),
        ],
        stop_reason="tool_use",
        usage={"input_tokens": 10, "output_tokens": 5},
    )
    response = normalize_anthropic_response(raw)
    block = response.content[0]
    assert isinstance(block, ToolUseBlock)
    assert block.id == "toolu_001"
    assert block.name == "read_file"
    assert block.input == {"path": "/tmp/test.txt", "encoding": "utf-8"}


def test_anthropic_normalize_tool_use_with_json_string_input():
    """Anthropic tool_use 块 JSON string input 应解析为 dict。

    某些兼容端点可能返回 JSON string 而不是 dict。
    """
    from agent.provider.normalize import normalize_anthropic_response

    raw = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                id="toolu_002",
                name="search",
                input='{"query": "hello", "limit": 10}',
            ),
        ],
        stop_reason="tool_use",
        usage=None,
    )
    response = normalize_anthropic_response(raw)
    block = response.content[0]
    assert isinstance(block, ToolUseBlock)
    assert block.input == {"query": "hello", "limit": 10}


def test_anthropic_normalize_malformed_json_input():
    """Malformed JSON string input 应返回空 dict，不抛异常，不泄露原文。"""
    from agent.provider.normalize import normalize_anthropic_response

    raw = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                id="toolu_003",
                name="broken_tool",
                input='{"path": ',
            ),
        ],
        stop_reason="tool_use",
        usage=None,
    )
    response = normalize_anthropic_response(raw)
    block = response.content[0]
    assert block.input == {}
    assert '{"path": ' not in repr(response)


def test_anthropic_normalize_non_dict_non_json_input():
    """非 dict 非 JSON string 的 input 应回退为空 dict。

    这是防御性编程——provider 行为可能不同于 SDK 文档。
    """
    from agent.provider.normalize import normalize_anthropic_response

    raw = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                id="toolu_004",
                name="weird_tool",
                input=42,  # 整数，不是 dict/string
            ),
        ],
        stop_reason="tool_use",
        usage=None,
    )
    response = normalize_anthropic_response(raw)
    block = response.content[0]
    assert block.input == {}


def test_anthropic_normalize_text_and_tool_use_ordering():
    """text block 和 tool_use block 的顺序必须与原始 response 一致。

    为什么：Tool Pipeline 按 content 顺序处理——text 是模型解释，
    tool_use 是行动请求，顺序颠倒会改变语义。
    """
    from agent.provider.normalize import normalize_anthropic_response

    raw = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="I will read the file"),
            SimpleNamespace(
                type="tool_use",
                id="toolu_010",
                name="read_file",
                input={"path": "README.md"},
            ),
            SimpleNamespace(type="text", text="Done reading"),
        ],
        stop_reason="end_turn",
        usage={"input_tokens": 20, "output_tokens": 30},
    )
    response = normalize_anthropic_response(raw)
    assert len(response.content) == 3
    assert isinstance(response.content[0], ProviderTextBlock)
    assert isinstance(response.content[1], ToolUseBlock)
    assert isinstance(response.content[2], ProviderTextBlock)
    assert response.content[0].text == "I will read the file"
    assert response.content[1].name == "read_file"
    assert response.content[2].text == "Done reading"


# =========================================================================
# 不变量 5: OpenAI tool_calls normalization
# =========================================================================


def test_openai_normalize_text_content():
    """OpenAI 文本响应应产出 ProviderTextBlock。"""
    from agent.provider.openai_http import normalize_openai_response

    raw: dict = {
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "Hello from OpenAI"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }
    response = normalize_openai_response(raw, raw_provider_name="openai_native")
    assert response.content == [ProviderTextBlock(text="Hello from OpenAI")]
    assert response.stop_reason == "end_turn"
    assert response.usage == {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}


def test_openai_normalize_tool_calls():
    """OpenAI tool_calls 应正确转为 ToolUseBlock 列表。

    OpenAI 的 function.arguments 是 JSON string，需要解析为 dict。
    """
    from agent.provider.openai_http import normalize_openai_response

    raw: dict = {
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city": "Beijing", "unit": "celsius"}',
                        },
                    },
                ],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }
    response = normalize_openai_response(raw, raw_provider_name="openai_compatible")
    assert len(response.content) == 1
    block = response.content[0]
    assert isinstance(block, ToolUseBlock)
    assert block.id == "call_abc123"
    assert block.name == "get_weather"
    assert block.input == {"city": "Beijing", "unit": "celsius"}
    assert response.stop_reason == "tool_use"


def test_openai_normalize_multiple_tool_calls():
    """多个 tool_calls 应对应多个 ToolUseBlock，顺序一致。"""
    from agent.provider.openai_http import normalize_openai_response

    raw: dict = {
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "a.txt"}',
                        },
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "write_file",
                            "arguments": '{"path": "b.txt", "content": "hello"}',
                        },
                    },
                ],
            },
            "finish_reason": "tool_calls",
        }],
    }
    response = normalize_openai_response(raw)
    assert len(response.content) == 2
    assert response.content[0].name == "read_file"
    assert response.content[1].name == "write_file"


def test_openai_normalize_mixed_content_and_tool_calls():
    """OpenAI 可能同时返回 content 和 tool_calls——顺序为 text 在前。"""
    from agent.provider.openai_http import normalize_openai_response

    raw: dict = {
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Let me check the weather for you.",
                "tool_calls": [
                    {
                        "id": "call_wx",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city": "Shanghai"}',
                        },
                    },
                ],
            },
            "finish_reason": "tool_calls",
        }],
    }
    response = normalize_openai_response(raw)
    assert len(response.content) == 2
    assert isinstance(response.content[0], ProviderTextBlock)
    assert isinstance(response.content[1], ToolUseBlock)


def test_openai_normalize_malformed_arguments():
    """OpenAI tool_calls 中 malformed arguments JSON 应回退为空 dict。"""
    from agent.provider.openai_http import normalize_openai_response

    raw: dict = {
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_broken",
                        "type": "function",
                        "function": {
                            "name": "broken_func",
                            "arguments": '{"path": ',
                        },
                    },
                ],
            },
            "finish_reason": "tool_calls",
        }],
    }
    response = normalize_openai_response(raw)
    block = response.content[0]
    assert block.input == {}


def test_openai_normalize_missing_tool_name():
    """缺失 function.name 应抛出 ProviderResponseError——工具调用必须有名称。"""
    from agent.provider.openai_http import normalize_openai_response

    raw: dict = {
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_nameless",
                        "type": "function",
                        "function": {
                            "name": "",  # 空名
                            "arguments": "{}",
                        },
                    },
                ],
            },
            "finish_reason": "tool_calls",
        }],
    }
    with pytest.raises(ProviderResponseError, match="tool_call_missing_name"):
        normalize_openai_response(raw)


def test_openai_normalize_empty_choices():
    """空 choices 列表应抛出 ProviderResponseError。"""
    from agent.provider.openai_http import normalize_openai_response

    raw: dict = {"choices": []}
    with pytest.raises(ProviderResponseError, match="no_choices"):
        normalize_openai_response(raw)


# =========================================================================
# 不变量 6: Namespaced tool name 保留原样
# =========================================================================


def test_anthropic_normalize_namespaced_tool_name_preserved():
    """Namespaced tool name（如 mcp__filesystem__read）应保留原样。

    为什么：namespace 前缀是 ToolRegistry 路由的关键信息。
    normalization 层不做 prefix strip，路由决策交给 ToolRegistry。
    """
    from agent.provider.normalize import normalize_anthropic_response

    raw = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                id="toolu_ns_1",
                name="mcp__filesystem__read_file",
                input={"path": "/tmp/test.txt"},
            ),
        ],
        stop_reason="tool_use",
        usage=None,
    )
    response = normalize_anthropic_response(raw)
    block = response.content[0]
    assert block.name == "mcp__filesystem__read_file"


def test_openai_normalize_namespaced_tool_name_preserved():
    """OpenAI tool_calls 中的 namespaced name 也应保留原样。"""
    from agent.provider.openai_http import normalize_openai_response

    raw: dict = {
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_ns",
                        "type": "function",
                        "function": {
                            "name": "mcp__github__search_code",
                            "arguments": '{"query": "test"}',
                        },
                    },
                ],
            },
            "finish_reason": "tool_calls",
        }],
    }
    response = normalize_openai_response(raw)
    assert response.content[0].name == "mcp__github__search_code"


# =========================================================================
# 不变量 7: finish_reason 映射
# =========================================================================


def test_openai_finish_reason_mapping():
    """OpenAI finish_reason 映射为内部 stop_reason。

    stop → end_turn, tool_calls → tool_use, length → max_tokens。
    """
    from agent.provider.openai_http import normalize_openai_response

    # stop → end_turn
    raw_stop: dict = {
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "done"},
            "finish_reason": "stop",
        }],
    }
    assert normalize_openai_response(raw_stop).stop_reason == "end_turn"

    # length → max_tokens
    raw_length: dict = {
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "truncated"},
            "finish_reason": "length",
        }],
    }
    assert normalize_openai_response(raw_length).stop_reason == "max_tokens"

    # unknown → 原值保留
    raw_unknown: dict = {
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "hmm"},
            "finish_reason": "content_filter",
        }],
    }
    assert normalize_openai_response(raw_unknown).stop_reason == "content_filter"


# =========================================================================
# 不变量 8: usage 标准化
# =========================================================================


def test_anthropic_usage_normalization():
    """Anthropic usage 字段按统一 key 标准化。

    输入 input_tokens/output_tokens → 输出 input_tokens/output_tokens（key 不变）。
    """
    from agent.provider.normalize import normalize_anthropic_response

    raw = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ok")],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
    )
    response = normalize_anthropic_response(raw)
    assert response.usage["input_tokens"] == 100
    assert response.usage["output_tokens"] == 50


def test_openai_usage_normalization():
    """OpenAI usage 字段按统一 key 标准化。

    输入 prompt_tokens/completion_tokens → 输出 input_tokens/output_tokens。
    """
    from agent.provider.openai_http import normalize_openai_response

    raw: dict = {
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "ok"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }
    response = normalize_openai_response(raw)
    assert response.usage["input_tokens"] == 100
    assert response.usage["output_tokens"] == 50
    assert response.usage["total_tokens"] == 150


# =========================================================================
# 不变量 9: ProviderTextBlock 行为
# =========================================================================


def test_provider_text_block_type():
    """ProviderTextBlock.type 始终返回 'text'。"""
    block = ProviderTextBlock(text="hello")
    assert block.type == "text"


def test_provider_text_block_is_frozen():
    """ProviderTextBlock 也是不可变的 frozen dataclass。"""
    block = ProviderTextBlock(text="hello")
    with pytest.raises(FrozenInstanceError):
        block.text = "world"  # type: ignore[misc]
