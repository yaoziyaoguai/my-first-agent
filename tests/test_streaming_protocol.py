"""Provider-neutral streaming protocol contract tests.

这些测试只使用 fake provider events，不调用真实 LLM、不读取 `.env`。目标是
把 core.py 从 Anthropic SDK stream 事件中解耦出来，同时固定最小事件 schema。
"""

from __future__ import annotations

from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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


def test_streaming_protocol_doc_event_types_match_runtime_schema() -> None:
    """文档列出的 event_type 必须与 provider-neutral runtime schema 对齐。

    这是 P3 文档一致性护栏：只读 canonical streaming 文档，不改变 streaming
    runtime 行为，避免后续把旧 ``delta`` 名称误认为真实协议字段。
    """

    from agent.provider.streaming import ProviderStreamEvent

    doc = (PROJECT_ROOT / "docs/02-architecture/STREAMING_PROTOCOL.zh.md").read_text(
        encoding="utf-8"
    )
    event_type_row = re.search(r"\| `event_type` \| (?P<types>[^|]+) \|", doc)
    assert event_type_row is not None

    documented_event_types = {
        item.strip().strip("`")
        for item in event_type_row.group("types").split("/")
    }
    runtime_event_types = {
        ProviderStreamEvent.delta(sequence=1, text_delta="x").event_type,
        ProviderStreamEvent.tool_request(sequence=2).event_type,
        ProviderStreamEvent.final(sequence=3).event_type,
        ProviderStreamEvent.error_event(sequence=4, error="e").event_type,
    }

    assert documented_event_types == runtime_event_types


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


def test_model_call_without_provider_fails_closed_before_legacy_stream() -> None:
    """没有 ModelProvider 时必须 fail closed，不能回退直连 SDK stream。

    这是最终审计 P2 的回归护栏：legacy_client 只保留为旧签名兼容，不能再让
    真实 Anthropic client 或 fake SDK shape 绕过 provider factory。
    """

    import pytest

    from agent.model_call import call_model
    from agent.provider.protocol import ProviderNotImplementedError

    class ForbiddenLegacyClient:
        @property
        def messages(self):  # noqa: ANN201
            raise AssertionError("legacy stream path must not be touched")

    with pytest.raises(ProviderNotImplementedError, match="model_provider_required"):
        call_model(
            provider=None,
            legacy_client=ForbiddenLegacyClient(),
            model_name="fake-model",
            system_prompt="system",
            messages=[],
            tools=[],
            emit_text_delta=None,
            emit_tool_request=None,
            print_assistant_newline=False,
        )
