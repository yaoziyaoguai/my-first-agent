"""Anthropic transport 修复包:B(协作取消)与 C(响应预算随 max_tokens 缩放)。

全部用 httpx.MockTransport 进程内验证,零真实网络。B 的取消语义与 openai 侧
`_read_deepseek_stream` 的 cancellation_requested 检查点同形;C 与 openai 构造器
的 compute-if-unspecified 策略对齐(anthropic 无条件流式,不加 thinking 门控)。
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from agent.provider import anthropic_http
from agent.provider.anthropic_http import AnthropicCompatibleProvider
from agent.provider.config import AgentProviderConfig
from agent.provider.protocol import (
    ProviderProtocolError,
    ProviderStreamCancelledError,
)
from agent.runtime.contracts import (
    BudgetReport,
    ContextPack,
    ModelMessage,
    ModelTextBlock,
)


def _context() -> ContextPack:
    return ContextPack(
        system="fixture system",
        messages=(
            ModelMessage(role="user", content=({"type": "text", "text": "hi"},)),
        ),
        tools=(),
        budget=BudgetReport(
            input_limit=2_000,
            estimated_input_tokens=10,
            output_reserve=100,
        ),
    )


def _config(**overrides: Any) -> AgentProviderConfig:
    params: dict[str, Any] = {
        "provider_type": "anthropic_compatible",
        "model": "fixture-model",
        "base_url": "https://provider.invalid",
        "credential": "fixture-secret",
        "timeout": 2.0,
    }
    params.update(overrides)
    return AgentProviderConfig(**params)


def _sse(*lines: str) -> bytes:
    return "\n".join(f"data: {line}" for line in lines).encode("utf-8") + b"\n\n"


_TEXT_STREAM = _sse(
    '{"type":"message_start","message":{"usage":{"input_tokens":7}}}',
    '{"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
    '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hel"}}',
    '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"lo"}}',
    '{"type":"content_block_stop","index":0}',
    '{"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":2}}',
    '{"type":"message_stop"}',
)


class _CancelAfterTextObserver:
    """首个 text 增量外发后请求取消(模拟用户在输出中途 Ctrl-C)。"""

    def __init__(self) -> None:
        self.deltas: list[str] = []
        self.cancelled = False

    def on_text_delta(self, text: str) -> None:
        self.deltas.append(text)
        self.cancelled = True

    def cancellation_requested(self) -> bool:
        return self.cancelled


class _PreCancelledObserver:
    """进入 generate 前取消已 pending。"""

    def __init__(self) -> None:
        self.deltas: list[str] = []

    def on_text_delta(self, text: str) -> None:
        self.deltas.append(text)

    def cancellation_requested(self) -> bool:
        return True


class _FlagObserver:
    """flag 由流 body 一侧(handler/content 迭代器)翻转:证明取消检查点
    不依赖 on_text_delta 回调(thinking/tool JSON 阶段同样生效)。"""

    def __init__(self) -> None:
        self.deltas: list[str] = []
        self.cancelled = False

    def on_text_delta(self, text: str) -> None:
        self.deltas.append(text)

    def cancellation_requested(self) -> bool:
        return self.cancelled


def _sse_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# B:协作取消
# ---------------------------------------------------------------------------


def test_cancel_before_send_makes_zero_http_requests() -> None:
    """B(a):取消已 pending 时,generate 不得发起任何网络 I/O。"""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=_TEXT_STREAM
        )

    observer = _PreCancelledObserver()
    with (
        _sse_client(handler) as client,
        pytest.raises(ProviderStreamCancelledError),
    ):
        AnthropicCompatibleProvider(config=_config(), http_client=client).generate(
            _context(), delta_observer=observer
        )

    assert calls == []
    assert observer.deltas == []


def test_cancel_during_text_stream_mid_flight() -> None:
    """B(b):首个 text 增量后取消——后续检查点必须在重建完成前 raise,
    不得等流自然结束或超时。"""
    observer = _CancelAfterTextObserver()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=_TEXT_STREAM
        )

    with (
        _sse_client(handler) as client,
        pytest.raises(ProviderStreamCancelledError),
    ):
        AnthropicCompatibleProvider(config=_config(), http_client=client).generate(
            _context(), delta_observer=observer
        )

    # 首个增量已 advisory 外发;取消后第二个增量不再到达。
    assert observer.deltas == ["Hel"]


def test_cancel_during_thinking_phase_before_any_text() -> None:
    """B(c):thinking 阶段(无任何 text 到达前)取消即生效——取消检查点
    不只挂在 text 增量上。"""
    observer = _FlagObserver()
    head = _sse(
        '{"type":"message_start","message":{"usage":{"input_tokens":5}}}',
        '{"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":""}}',
        '{"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"private"}}',
    )
    tail = _sse(
        '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hel"}}',
        '{"type":"content_block_stop","index":0}',
        '{"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":2}}',
        '{"type":"message_stop"}',
    )

    def content():
        yield head
        # 第一个 chunk(仅 thinking 事件)已交付后、第二个 chunk 前用户取消。
        observer.cancelled = True
        yield tail

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=content()
        )

    with (
        _sse_client(handler) as client,
        pytest.raises(ProviderStreamCancelledError),
    ):
        AnthropicCompatibleProvider(config=_config(), http_client=client).generate(
            _context(), delta_observer=observer
        )

    assert observer.deltas == []


def test_cancel_during_input_json_delta_mints_no_tool(monkeypatch) -> None:
    """B(d):tool_use 的 input_json_delta 半途取消——normalize 不得运行,
    半途参数绝不铸造为 tool call。"""
    observer = _FlagObserver()
    head = _sse(
        '{"type":"message_start","message":{"usage":{"input_tokens":3}}}',
        '{"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"call-1","name":"read_file","input":{}}}',
        '{"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\"pa"}}',
    )
    tail = _sse(
        '{"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta"'
        ',"partial_json":"th\\": 1}"}}',
        '{"type":"content_block_stop","index":0}',
        '{"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":9}}',
        '{"type":"message_stop"}',
    )

    def content():
        yield head
        observer.cancelled = True
        yield tail

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=content()
        )

    normalize_calls: list[object] = []
    real_normalize = anthropic_http.normalize_anthropic_response

    def spying_normalize(payload, **kwargs):
        normalize_calls.append(payload)
        return real_normalize(payload, **kwargs)

    monkeypatch.setattr(
        anthropic_http, "normalize_anthropic_response", spying_normalize
    )

    with (
        _sse_client(handler) as client,
        pytest.raises(ProviderStreamCancelledError),
    ):
        AnthropicCompatibleProvider(config=_config(), http_client=client).generate(
            _context(), delta_observer=observer
        )

    assert normalize_calls == []


def test_cancel_during_non_sse_json_fallback() -> None:
    """B(e):非 SSE JSON fallback 读取中途取消同样生效。"""
    observer = _FlagObserver()
    full = b'{"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"}'

    def content():
        yield full[:16]
        observer.cancelled = True
        yield full[16:]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "application/json"}, content=content()
        )

    with (
        _sse_client(handler) as client,
        pytest.raises(ProviderStreamCancelledError),
    ):
        AnthropicCompatibleProvider(config=_config(), http_client=client).generate(
            _context(), delta_observer=observer
        )

    assert observer.deltas == []


def test_cancel_closes_streaming_body() -> None:
    """B(f):取消后连接确实关闭——body 迭代器记录 close,断言其 closed。"""

    class RecordingBodyStream(httpx.SyncByteStream):
        def __init__(self, observer: _FlagObserver) -> None:
            self._observer = observer
            self.closed = False

        def __iter__(self):
            yield _sse(
                '{"type":"message_start","message":{"usage":{"input_tokens":5}}}',
                '{"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
                '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"part"}}',
            )
            self._observer.cancelled = True
            yield _sse(
                '{"type":"content_block_stop","index":0}',
                '{"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":1}}',
                '{"type":"message_stop"}',
            )

        def close(self) -> None:
            self.closed = True

    observer = _FlagObserver()
    body = RecordingBodyStream(observer)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=body
        )

    with (
        _sse_client(handler) as client,
        pytest.raises(ProviderStreamCancelledError),
    ):
        AnthropicCompatibleProvider(config=_config(), http_client=client).generate(
            _context(), delta_observer=observer
        )

    assert body.closed is True


def test_normal_stream_without_cancel_completes() -> None:
    """B(g) 对照:不取消时正常路径产出完整响应。"""
    observer = _FlagObserver()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=_TEXT_STREAM
        )

    with _sse_client(handler) as client:
        response = AnthropicCompatibleProvider(
            config=_config(), http_client=client
        ).generate(_context(), delta_observer=observer)

    assert observer.cancelled is False
    assert observer.deltas == ["Hel", "lo"]
    assert response.blocks == (ModelTextBlock("Hello"),)
    assert response.stop_reason == "end_turn"


# ---------------------------------------------------------------------------
# C:响应预算随 max_tokens 缩放
# ---------------------------------------------------------------------------


def _padded_json_body(padding: int) -> bytes:
    return (
        b'{"padding": "'
        + b"x" * padding
        + b'", "content": [{"type": "text", "text": "ok"}], '
        b'"stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}}'
    )


def test_default_budget_scales_with_max_tokens() -> None:
    """C:默认预算 = max(4MB, max_tokens * 512)。max_tokens=9000 →
    4_608_000:>4MB 且 <缩放界的响应被接纳;超过缩放界仍 fail-closed 硬拒。"""
    config = _config(max_tokens=9_000)

    def json_client(body: bytes) -> httpx.Client:
        return _sse_client(
            lambda _request: httpx.Response(
                200, headers={"content-type": "application/json"}, content=body
            )
        )

    accepted = _padded_json_body(4_500_000)  # 总长 ≈ 4_500_110 ∈ (4MB, 4_608_000)
    with json_client(accepted) as client:
        response = AnthropicCompatibleProvider(
            config=config, http_client=client
        ).generate(_context())
    assert response.blocks == (ModelTextBlock("ok"),)

    rejected = _padded_json_body(4_700_000)  # 总长 ≈ 4_700_110 > 4_608_000
    with (
        json_client(rejected) as client,
        pytest.raises(ProviderProtocolError, match="response_too_large"),
    ):
        AnthropicCompatibleProvider(config=config, http_client=client).generate(
            _context()
        )


def test_default_budget_keeps_4mb_floor_for_small_max_tokens() -> None:
    """C:max_tokens=1000 → 1000*512=512_000 < 4MB:预算仍取 4MB 下限,
    介于两者之间的响应被接纳(不因缩放而变小)。"""
    config = _config(max_tokens=1_000)
    body = _padded_json_body(1_000_000)  # 总长 ≈ 1_000_110 ∈ (512_000, 4MB)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "application/json"}, content=body
        )

    with _sse_client(handler) as client:
        response = AnthropicCompatibleProvider(
            config=config, http_client=client
        ).generate(_context())
    assert response.blocks == (ModelTextBlock("ok"),)


def test_explicit_small_budget_still_hard_rejects() -> None:
    """C:显式传入的小预算精确生效——10 字节预算对任何真实响应硬拒。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b'{"content": [{"type": "text", "text": "ok"}]}',
        )

    with (
        _sse_client(handler) as client,
        pytest.raises(ProviderProtocolError, match="response_too_large"),
    ):
        AnthropicCompatibleProvider(
            config=_config(), http_client=client, max_response_bytes=10
        ).generate(_context())
