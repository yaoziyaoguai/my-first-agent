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
from agent.provider.protocol import ProviderNotImplementedError
from agent.provider.streaming import collect_stream_response


def build_default_model_client() -> tuple[Any | None, Any]:
    """构造模块级默认 provider/client。

    provider 存在时，client 只是给 legacy planner/compress 使用的 facade；
    provider 缺失时返回显式 object，让测试可以 monkeypatch core.client。

    ⛔ Sunset: ProviderBackedClient + legacy client facade 在 v0.4+ 移除，
    届时 planner/compress 直接使用 provider.create()。Not default path。
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
    _streaming_events_out: list | None = None,
) -> Any:
    """通过 provider abstraction 调用模型，并兼容测试 fake client。

    Provider path 是唯一生产路径。legacy_client 参数只为旧调用签名保留
    （⛔ DEPRECATED, sunset v0.4+）；没有 ModelProvider 时 fail closed，
    避免真实 SDK client 绕过 provider factory。
    这里不写 checkpoint、不改 state，只把 provider stream 聚合为最终 response。
    """

    if provider is None and hasattr(legacy_client, "provider"):
        provider = legacy_client.provider

    if provider is None:
        raise ProviderNotImplementedError(
            "未配置 LLM provider，无法调用模型。请检查 config/config.yaml 中 "
            "provider 配置，或确认环境变量 MY_FIRST_AGENT_LLM_PROVIDER 已设置。"
        )

    if getattr(provider, "supports_streaming", False):
        stream_events = provider.stream(system=system_prompt, messages=messages, tools=tools)
        observed_events = []
        has_tool_request = False
        for event in stream_events:
            observed_events.append(event)
            if event.event_type == "tool_request":
                has_tool_request = True
                if emit_tool_request is not None:
                    emit_tool_request()
            elif event.text_delta and emit_text_delta is not None:
                emit_text_delta(event.text_delta)
        if _streaming_events_out is not None:
            _streaming_events_out.extend(observed_events)
        if has_tool_request:
            # stream() 无法产出 ToolUseBlock——回退 create() 获取含完整
            # ToolUseBlock 的 ProviderResponse。文本 deltas 已在上方 emit，
            # 不再重复 emit text（避免用户看到双重输出）。
            response = provider.create(
                system=system_prompt,
                messages=messages,
                tools=tools,
            )
        else:
            response = collect_stream_response(observed_events)
    else:
        # 非 streaming provider：走 create() 获取完整响应。
        response = provider.create(
            system=system_prompt,
            messages=messages,
            tools=tools,
        )
        # 检查响应中是否包含 tool_use block，若有则发射 tool_requested 事件。
        # 非 streaming provider 没有 stream event 可消费，必须在这里补发，
        # 否则 tool.requested RuntimeEvent 永远不会触发。
        has_tool_use = any(
            getattr(b, "type", None) == "tool_use"
            for b in (getattr(response, "content", []) or [])
        )
        if has_tool_use and emit_tool_request is not None:
            emit_tool_request()
        if emit_text_delta is not None:
            for block in getattr(response, "content", []) or []:
                text = getattr(block, "text", None)
                if isinstance(text, str) and text:
                    emit_text_delta(text)

    if print_assistant_newline:
        print()
    return response
