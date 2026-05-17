"""Provider-backed model call boundary for runtime core.

core.py 是主循环编排者，不应该知道 Anthropic/OpenAI SDK stream 事件形状。
本模块集中处理 provider routing、stream event 消费与 legacy fake client 兼容，
让后续新增 provider 时不需要修改 core 主循环。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent.provider.factory import build_model_provider_from_env
from agent.provider.legacy_adapter import ProviderBackedClient
from agent.provider.streaming import collect_stream_response


def build_default_model_client() -> tuple[Any | None, Any]:
    """构造模块级默认 provider/client。

    provider 存在时，client 只是给 legacy planner/compress 使用的 facade；
    provider 缺失时返回显式 object，让测试可以 monkeypatch core.client。
    """

    provider = build_model_provider_from_env()
    if provider is None:
        return None, object()
    return provider, ProviderBackedClient(provider)


def call_model(
    *,
    provider: Any | None,
    legacy_client: Any,
    model_name: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    emit_text_delta: Callable[[str], None] | None,
    emit_tool_request: Callable[[], None] | None,
    print_assistant_newline: bool,
) -> Any:
    """通过 provider abstraction 调用模型，并兼容测试 fake client。

    Provider path 是生产路径；legacy_client path 只用于已有 fake client 测试。
    这里不写 checkpoint、不改 state，只把 provider stream 聚合为最终 response。
    """

    if provider is None and hasattr(legacy_client, "provider"):
        provider = legacy_client.provider

    if provider is not None:
        if hasattr(provider, "stream"):
            stream_events = provider.stream(system=system_prompt, messages=messages, tools=tools)
            observed_events = []
            for event in stream_events:
                observed_events.append(event)
                if event.event_type == "tool_request":
                    if emit_tool_request is not None:
                        emit_tool_request()
                elif event.text_delta and emit_text_delta is not None:
                    emit_text_delta(event.text_delta)
            response = collect_stream_response(observed_events)
        else:
            # 兼容旧测试 fake provider；正式 provider contract 已要求 stream()，
            # 这里仍只走 provider interface，不回退任何 SDK client。
            response = provider.create(system=system_prompt, messages=messages, tools=tools)
            if emit_text_delta is not None:
                for block in getattr(response, "content", []) or []:
                    text = getattr(block, "text", None)
                    if isinstance(text, str) and text:
                        emit_text_delta(text)
    else:
        with legacy_client.messages.stream(
            model=model_name,
            system=system_prompt,
            messages=messages,
            tools=tools,
        ) as stream:
            for event in stream:
                event_type = getattr(event, "type", "")
                if event_type == "content_block_delta":
                    delta_text = getattr(getattr(event, "delta", None), "text", "")
                    if delta_text and emit_text_delta is not None:
                        emit_text_delta(delta_text)
                elif event_type == "content_block_start":
                    block = getattr(event, "content_block", None)
                    if getattr(block, "type", "") == "tool_use" and emit_tool_request is not None:
                        emit_tool_request()
            response = stream.get_final_message()

    if print_assistant_newline:
        print()
    return response
