"""Provider-neutral streaming protocol contract tests.

这些测试只使用 fake provider events，不调用真实 LLM、不读取 `.env`。目标是
把 core.py 从 Anthropic SDK stream 事件中解耦出来，同时固定最小事件 schema。
"""

from __future__ import annotations


def test_streaming_event_schema_sequence_and_final_response() -> None:
    """delta 事件必须可聚合成最终 ProviderResponse，且 sequence 单调。"""

    from agent.provider.protocol import ProviderTextBlock
    from agent.provider.streaming import ProviderStreamEvent, collect_stream_response

    events = [
        ProviderStreamEvent.delta(sequence=1, text_delta="hel"),
        ProviderStreamEvent.delta(sequence=2, text_delta="lo"),
        ProviderStreamEvent.final(sequence=3),
    ]

    response = collect_stream_response(events)

    assert [event.sequence for event in events] == [1, 2, 3]
    assert events[-1].is_final is True
    assert response.content == [ProviderTextBlock(text="hello")]
    assert response.stop_reason == "end_turn"


def test_streaming_error_event_fails_closed() -> None:
    """provider stream error 只能变成安全异常，不能继续伪造最终响应。"""

    import pytest

    from agent.provider.protocol import ProviderResponseError
    from agent.provider.streaming import ProviderStreamEvent, collect_stream_response

    events = [
        ProviderStreamEvent.delta(sequence=1, text_delta="partial"),
        ProviderStreamEvent.error_event(sequence=2, error="provider_timeout"),
    ]

    with pytest.raises(ProviderResponseError, match="provider_stream_error"):
        collect_stream_response(events)


def test_streaming_secret_like_payload_is_redacted() -> None:
    """streaming delta 进入 RuntimeEvent 前必须先脱敏。"""

    from agent.provider.streaming import ProviderStreamEvent, sanitize_stream_text

    raw = "token sk-proj-abcdefghijklmnopqrstuvwxyz1234567890 should not leak"
    event = ProviderStreamEvent.delta(sequence=1, text_delta=raw)

    redacted = sanitize_stream_text(event.text_delta)

    assert "sk-proj-" not in redacted
    assert "[REDACTED_SECRET]" in redacted


def test_core_call_model_uses_provider_stream_interface(monkeypatch) -> None:
    """_call_model 只依赖 provider.stream，不触碰 loop_ctx.client.messages.stream。"""

    from types import SimpleNamespace

    from agent import core
    from agent.loop_context import LoopContext
    from agent.provider.streaming import ProviderStreamEvent

    class ForbiddenClient:
        @property
        def messages(self):  # noqa: ANN201
            raise AssertionError("core.py must not use legacy SDK stream client")

    class FakeStreamingProvider:
        provider_type = "fake_stream"
        supports_tools = True
        supports_streaming = True

        def stream(self, *, system, messages, tools):  # noqa: ANN001
            yield ProviderStreamEvent.delta(sequence=1, text_delta="hi")
            yield ProviderStreamEvent.final(sequence=2)

    emitted: list[str] = []
    monkeypatch.setattr(core, "build_execution_messages_from_state", lambda _state: [])
    monkeypatch.setattr(core, "get_model_visible_tools", lambda max_mcp_tools=5: [])

    turn_state = SimpleNamespace(
        system_prompt="system",
        on_runtime_event=lambda event: emitted.append(event.text),
        print_assistant_newline=False,
    )
    loop_ctx = LoopContext(
        client=ForbiddenClient(),
        model_name="fake-model",
        max_loop_iterations=3,
        model_provider=FakeStreamingProvider(),
    )

    response = core._call_model(turn_state, loop_ctx)

    assert emitted == ["hi"]
    assert response.content[0].text == "hi"
