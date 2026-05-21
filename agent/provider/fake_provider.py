"""Fake/deterministic ModelProvider for Phase 1 E2E testing.

中文学习边界：
FakeProvider 是 Phase 1 专用确定性 provider，实现 ModelProvider 协议。
它不读 .env、不调用外部 API、不执行工具副作用。目的是让 core.chat() →
run_main_loop() → call_model() 全链路可走通，从而证明 RuntimeAction 确实
由真实 core loop 触发，而非 dogfood harness 直接调用 dispatcher。

为什么需要 FakeProvider：
- core.chat() 依赖 provider 调用模型，没有 provider 则 call_model() fail closed
- 真实 LLM 在 Phase 1 被禁止（不读 .env、不调外部 API）
- FakeProvider 让 runtime loop 全链路可运行，同时保持 100% 确定性

不对什么负责：
- 不做真实 LLM 推理
- 不做工具调用
- 不做流式 SSE 协议
- 不模拟 provider error/latency/retry（那是 Phase 2+ 的职责）
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from agent.provider.protocol import ProviderResponse, ProviderTextBlock
from agent.provider.streaming import ProviderStreamEvent


def _default_response_fn(messages: list[dict[str, Any]]) -> str:
    """默认确定性响应：返回最后一条 user message 的回显。"""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                return f"已收到你的消息：「{content[:80]}」"
    return "已收到你的消息。"


class FakeProvider:
    """确定性 fake provider，实现 ModelProvider 协议。

    用法：
        provider = FakeProvider()
        response = provider.create(system="...", messages=[...], tools=[])
        # response.stop_reason == "end_turn"
        # response.content[0].text == "已收到你的消息：「你好」"

    也支持自定义响应函数：
        provider = FakeProvider(response_fn=lambda msgs: "自定义回复")
    """

    provider_type = "fake"
    supports_tools = False
    supports_streaming = True

    def __init__(
        self,
        *,
        response_fn: Callable[[list[dict[str, Any]]], str] | None = None,
        stop_reason: str = "end_turn",
    ) -> None:
        self._response_fn = response_fn or _default_response_fn
        self._stop_reason = stop_reason

    def create(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ProviderResponse:
        """非流式创建响应。"""
        text = self._response_fn(messages)
        return ProviderResponse(
            content=[ProviderTextBlock(text=text)],
            stop_reason=self._stop_reason,
            raw_provider_name="fake",
        )

    def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Iterator[ProviderStreamEvent]:
        """流式响应：把文本拆成 delta 事件，以 final 事件结束。"""
        text = self._response_fn(messages)
        seq = 0
        # 按字符拆分模拟流式输出（保持语义可读性，按 3 字符一组）
        chunk_size = 3
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i + chunk_size]
            seq += 1
            yield ProviderStreamEvent.delta(sequence=seq, text_delta=chunk)
        seq += 1
        yield ProviderStreamEvent.final(sequence=seq)
