from __future__ import annotations

import json

import httpx
import pytest

from agent.provider.config import AgentProviderConfig
from agent.provider.normalize import context_to_openai_messages
from agent.provider.openai_http import OpenAICompatibleProvider
from agent.provider.protocol import (
    ProviderConfigurationError,
    ProviderProtocolError,
    ProviderStreamCancelledError,
    ProviderStreamInterruptedError,
)
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    RESERVED_CONTROL_NAME,
    BudgetReport,
    ContextPack,
    ConversationState,
    ExecutionAuthorityClass,
    ModelMessage,
    ModelTextBlock,
    ModelToolCall,
    ProviderContinuationV1,
    RunStatus,
    SubmitMessage,
    ToolDefinition,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore


def _config(**overrides) -> AgentProviderConfig:
    values = {
        "provider_type": "openai_compatible",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "credential": "fixture-secret",
        "thinking_mode": "enabled",
        "reasoning_effort": "max",
        "timeout": 2.0,
    }
    values.update(overrides)
    return AgentProviderConfig(**values)


def _context(*, continuation: ProviderContinuationV1 | None = None) -> ContextPack:
    return ContextPack(
        system="Use only the supplied tools.",
        messages=(
            ModelMessage(
                role="assistant",
                content=(
                    {
                        "type": "tool_call",
                        "tool_call_id": "call-prev",
                        "name": "read_file",
                        "arguments": {"path": "fixture.txt"},
                    },
                ),
                provider_continuation=continuation,
            ),
            ModelMessage(
                role="user",
                content=(
                    {
                        "type": "tool_result",
                        "tool_call_id": "call-prev",
                        "text": "fixture",
                        "is_error": False,
                    },
                ),
            ),
        ),
        tools=(
            ToolDefinition(
                execution_authority=ExecutionAuthorityClass.IN_PROCESS,
                name="read_file",
                description="Read a fixture",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
            ),
        ),
        budget=BudgetReport(2_000, 100, 200),
    )


def _sse(*events: dict, done: bool = True) -> bytes:
    body = b"".join(
        b"data: " + json.dumps(event, separators=(",", ":")).encode() + b"\n\n"
        for event in events
    )
    return body + (b"data: [DONE]\n\n" if done else b"")


def _chunk(delta: dict, finish_reason=None, usage=None, *, model="deepseek-v4-flash") -> dict:
    payload = {
        "id": "response-1",
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    if usage is not None:
        payload["usage"] = usage
    return payload


@pytest.mark.parametrize(
    "overrides",
    [
        {"base_url": "https://provider.invalid"},
        {"base_url": "https://api.deepseek.com/beta"},
        {"model": "fixture-model"},
        {"reasoning_effort": None},
        {"reasoning_effort": "ultra"},
        {"strict_tools": True},
    ],
)
def test_enabled_thinking_is_closed_to_the_supported_deepseek_flash_chain(
    overrides: dict,
) -> None:
    with pytest.raises(ProviderConfigurationError):
        _config(**overrides)


def test_current_deepseek_flash_alias_is_an_explicit_supported_identity() -> None:
    config = _config(model="deepseek-flash")

    assert config.model == "deepseek-flash"
    assert config.max_tokens == 384_000


def test_deepseek_flash_thinking_uses_the_documented_output_bound() -> None:
    assert _config().max_tokens == 384_000


def test_deepseek_flash_stream_bound_scales_with_its_output_capacity() -> None:
    provider = OpenAICompatibleProvider(config=_config())

    assert provider._max_response_bytes == 384_000 * 512


def test_explicit_deepseek_output_bound_is_preserved() -> None:
    assert _config(max_tokens=8_192).max_tokens == 8_192


def test_non_thinking_compatible_provider_keeps_the_small_default_bound() -> None:
    config = AgentProviderConfig(
        provider_type="openai_compatible",
        model="fixture-model",
        base_url="https://provider.invalid",
        thinking_mode="disabled",
    )

    assert config.max_tokens == 4_096


def test_unofficial_compatible_endpoint_does_not_inherit_deepseek_capacity() -> None:
    config = AgentProviderConfig(
        provider_type="openai_compatible",
        model="deepseek-v4-flash",
        base_url="https://provider.invalid",
        thinking_mode="disabled",
    )

    assert config.max_tokens == 4_096


def test_official_deepseek_beta_endpoint_inherits_model_capacity() -> None:
    config = AgentProviderConfig(
        provider_type="openai_compatible",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com/beta",
        request_path="/chat/completions",
        thinking_mode="disabled",
        strict_tools=True,
    )

    assert config.max_tokens == 384_000


def test_v4_request_accepts_the_current_server_flash_response_alias() -> None:
    config = _config()
    continuation = ProviderContinuationV1.create(
        provider_identity_digest=config.descriptor().identity_digest,
        opaque_payload="previous",
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(
                _chunk({"reasoning_content": "private"}, model="deepseek-flash"),
                _chunk(
                    {"content": "OK"},
                    "stop",
                    {"prompt_tokens": 7, "completion_tokens": 1},
                    model="deepseek-flash",
                ),
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = OpenAICompatibleProvider(config=config, http_client=client).generate(
            _context(continuation=continuation)
        )

    assert response.blocks == (ModelTextBlock("OK"),)


def test_deepseek_stream_still_rejects_an_unrelated_response_model() -> None:
    config = _config()
    continuation = ProviderContinuationV1.create(
        provider_identity_digest=config.descriptor().identity_digest,
        opaque_payload="previous",
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(_chunk({"content": "wrong"}, model="deepseek-v4-pro")),
        )

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ProviderStreamInterruptedError),
    ):
        OpenAICompatibleProvider(config=config, http_client=client).generate(
            _context(continuation=continuation)
        )


def test_non_thinking_compatible_profiles_cannot_set_reasoning_effort() -> None:
    with pytest.raises(ProviderConfigurationError):
        AgentProviderConfig(
            provider_type="openai_compatible",
            model="fixture-model",
            base_url="https://provider.invalid",
            thinking_mode="disabled",
            reasoning_effort="max",
        )


def test_streamed_reasoning_and_multi_tool_calls_are_normalized_once() -> None:
    requests: list[httpx.Request] = []
    deltas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(
                _chunk({"role": "assistant", "reasoning_content": "private "}),
                _chunk({"reasoning_content": "reasoning"}),
                _chunk({"content": "Checking both files."}),
                _chunk(
                    {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-a",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path":"a',
                                },
                            },
                            {
                                "index": 1,
                                "id": "call-b",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path":"b',
                                },
                            },
                        ]
                    }
                ),
                _chunk(
                    {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": '.txt"}'},
                            },
                            {
                                "index": 1,
                                "function": {"arguments": '.txt"}'},
                            },
                        ]
                    }
                ),
                _chunk(
                    {},
                    "tool_calls",
                    {"prompt_tokens": 12, "completion_tokens": 7},
                ),
            ),
        )

    class Observer:
        def on_text_delta(self, text: str) -> None:
            deltas.append(text)

    config = _config()
    previous = ProviderContinuationV1.create(
        provider_identity_digest=config.descriptor().identity_digest,
        opaque_payload="previous reasoning",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = OpenAICompatibleProvider(config=config, http_client=client).generate(
            _context(continuation=previous), delta_observer=Observer()
        )

    assert response.blocks == (
        ModelTextBlock("Checking both files."),
        ModelToolCall("call-a", "read_file", {"path": "a.txt"}),
        ModelToolCall("call-b", "read_file", {"path": "b.txt"}),
    )
    assert response.stop_reason == "tool_use"
    assert response.input_tokens == 12
    assert response.output_tokens == 7
    assert response.provider_continuation is not None
    assert response.provider_continuation.opaque_payload == "private reasoning"
    assert response.provider_continuation.provider_identity_digest == (
        config.descriptor().identity_digest
    )
    assert deltas == ["Checking both files."]

    body = json.loads(requests[0].content)
    assert body["model"] == "deepseek-v4-flash"
    assert body["max_tokens"] == 384_000
    assert body["thinking"] == {"type": "enabled"}
    assert body["reasoning_effort"] == "max"
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert "temperature" not in body
    assert "fixture-secret" not in requests[0].content.decode()


def test_matching_continuation_is_replayed_but_never_exposed_as_content() -> None:
    config = _config()
    continuation = ProviderContinuationV1.create(
        provider_identity_digest=config.descriptor().identity_digest,
        opaque_payload="private reasoning",
    )

    messages = context_to_openai_messages(
        _context(continuation=continuation),
        provider_identity_digest=config.descriptor().identity_digest,
        require_reasoning_continuity=True,
    )

    assistant = next(message for message in messages if message["role"] == "assistant")
    assert assistant["reasoning_content"] == "private reasoning"
    assert assistant["content"] == ""


def test_missing_or_mismatched_continuation_fails_before_http() -> None:
    config = _config()
    wrong = ProviderContinuationV1.create(
        provider_identity_digest="a" * 64,
        opaque_payload="must not leak",
    )
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(config=config, http_client=client)
        with pytest.raises(ProviderProtocolError, match="missing_reasoning_continuity"):
            provider.generate(_context())
        with pytest.raises(ProviderProtocolError, match="provider_continuity_mismatch"):
            provider.generate(_context(continuation=wrong))
    assert calls == 0


@pytest.mark.parametrize(
    "content",
    [
        _sse(_chunk({"content": "partial"}), done=False),
        b'data: {"broken":\n\n',
        _sse(_chunk({"content": "partial"}), _chunk({}, "stop"), done=False),
    ],
)
def test_incomplete_or_malformed_stream_is_unknown_not_a_partial_response(
    content: bytes,
) -> None:
    config = _config()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=content,
        )

    continuation = ProviderContinuationV1.create(
        provider_identity_digest=config.descriptor().identity_digest,
        opaque_payload="previous",
    )
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ProviderStreamInterruptedError),
    ):
        OpenAICompatibleProvider(config=config, http_client=client).generate(
            _context(continuation=continuation)
        )


@pytest.mark.parametrize(
    "events",
    [
        (
            _chunk({"reasoning_content": "private"}),
            _chunk({}, "stop"),
        ),
        (
            _chunk({"reasoning_content": "private"}),
            _chunk(
                {},
                "insufficient_system_resource",
                {"prompt_tokens": 1, "completion_tokens": 1},
            ),
        ),
        (
            _chunk({"reasoning_content": "private"}),
            _chunk(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call-a",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path":"a.txt"}',
                            },
                        }
                    ]
                }
            ),
            _chunk({}, "stop", {"prompt_tokens": 1, "completion_tokens": 1}),
        ),
    ],
)
def test_stream_requires_usage_and_matching_terminal_reason(
    events: tuple[dict, ...],
) -> None:
    config = _config()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(*events),
        )

    continuation = ProviderContinuationV1.create(
        provider_identity_digest=config.descriptor().identity_digest,
        opaque_payload="previous",
    )
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ProviderStreamInterruptedError),
    ):
        OpenAICompatibleProvider(config=config, http_client=client).generate(
            _context(continuation=continuation)
        )


def test_stream_response_bound_counts_reasoning_and_wire_bytes() -> None:
    config = _config()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(_chunk({"reasoning_content": "x" * 100})),
        )

    continuation = ProviderContinuationV1.create(
        provider_identity_digest=config.descriptor().identity_digest,
        opaque_payload="previous",
    )
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ProviderStreamInterruptedError),
    ):
        OpenAICompatibleProvider(
            config=config,
            http_client=client,
            max_response_bytes=32,
        ).generate(_context(continuation=continuation))


def test_cooperative_stream_cancel_closes_before_accepting_partial_output() -> None:
    config = _config()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(
                _chunk({"reasoning_content": "private"}),
                _chunk({"content": "partial public text"}),
                _chunk({}, "stop", {"prompt_tokens": 1, "completion_tokens": 1}),
            ),
        )

    class Observer:
        cancelled = False

        def on_text_delta(self, _text: str) -> None:
            self.cancelled = True

        def cancellation_requested(self) -> bool:
            return self.cancelled

    continuation = ProviderContinuationV1.create(
        provider_identity_digest=config.descriptor().identity_digest,
        opaque_payload="previous",
    )
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ProviderStreamCancelledError),
    ):
        OpenAICompatibleProvider(config=config, http_client=client).generate(
            _context(continuation=continuation),
            delta_observer=Observer(),
        )


def test_runtime_replays_reasoning_on_the_next_user_turn_without_exposing_it() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        turn = len(requests)
        if turn == 2:
            prior = next(
                message for message in body["messages"] if message["role"] == "assistant"
            )
            assert prior["content"] == "first answer"
            assert prior["reasoning_content"] == "private first reasoning"
        arguments = json.dumps(
            {
                "kind": "direct_response",
                "correlation_id": f"direct-{turn}",
                "text": f"{'first' if turn == 1 else 'second'} answer",
            },
            separators=(",", ":"),
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(
                _chunk(
                    {
                        "role": "assistant",
                        "reasoning_content": (
                            "private first reasoning"
                            if turn == 1
                            else "private second reasoning"
                        ),
                    }
                ),
                _chunk(
                    {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": f"control-{turn}",
                                "type": "function",
                                "function": {
                                    "name": RESERVED_CONTROL_NAME,
                                    "arguments": arguments,
                                },
                            }
                        ]
                    }
                ),
                _chunk({}, "tool_calls", {"prompt_tokens": 10, "completion_tokens": 4}),
            ),
        )

    state_store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        runtime = AgentRuntime(
            provider=OpenAICompatibleProvider(
                config=_config(),
                http_client=client,
            ),
            context_manager=KernelContextManager(
                system_policy="policy",
                limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
            ),
            tool_runtime=KernelToolRuntime(()),
            checkpoint_store=state_store,
            event_sink=CollectingSink(),
            limits=InvocationLimits(max_model_calls=4),
            invocation_id_factory=lambda: "invocation-1",
        )
        first = runtime.run_turn(
            SubmitMessage(
                conversation_id="conversation-1",
                action_seq=1,
                expected_revision=0,
                run_id="run-1",
                message="first question",
            ),
            state_store.load(),
        )
        snapshot = state_store.load()
        second = runtime.run_turn(
            SubmitMessage(
                conversation_id="conversation-1",
                action_seq=snapshot.state.next_action_seq,
                expected_revision=snapshot.state.revision,
                run_id="run-2",
                message="second question",
            ),
            snapshot,
        )

    assert first.status is RunStatus.COMPLETED
    assert second.status is RunStatus.COMPLETED
    assert first.message == "first answer"
    assert second.message == "second answer"
    assert len(requests) == 2
    assert "private first reasoning" not in first.message
    assert "private second reasoning" not in second.message


def test_flash_default_thinking_json_response_keeps_reasoning_continuity() -> None:
    """2026-10-09 真实 dogfood 实测缺陷回归：DeepSeek-flash 官方端点默认即
    思考模式——未显式 --thinking-mode enabled（thinking_mode=None）时响应仍
    携带 reasoning_content。family 识别后按预期处理：请求侧连续性回放 +
    归一化放行并铸造 provider continuation；否则 unsupported_response_block
    fail closed。"""

    config = _config(thinking_mode=None, reasoning_effort=None)
    continuation = ProviderContinuationV1.create(
        provider_identity_digest=config.descriptor().identity_digest,
        opaque_payload="previous",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        # 默认（非显式思考）走非流式 JSON 路径。
        assert "stream" not in body
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "OK",
                            "reasoning_content": "fresh reasoning",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 1},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = OpenAICompatibleProvider(
            config=config, http_client=client
        ).generate(_context(continuation=continuation))

    assert response.blocks == (ModelTextBlock("OK"),)
    assert response.provider_continuation is not None
    assert (
        response.provider_continuation.provider_identity_digest
        == config.descriptor().identity_digest
    )
    assert response.provider_continuation.opaque_payload == "fresh reasoning"


def test_w3_explicit_disabled_official_flash_accepts_plain_json_response() -> None:
    """W3（2026-10-12）：family 推断不得覆盖显式 disabled。官方 Flash 端点
    + thinking_mode=disabled：请求体真实表达 disabled（thinking={"type":
    "disabled"}，无 stream/reasoning_effort），纯文本 JSON 响应必须放行，
    不得以 missing_reasoning_continuity 拒绝。"""


    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.update(body)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 1},
            },
        )

    config = _config(thinking_mode="disabled", reasoning_effort=None)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = OpenAICompatibleProvider(
            config=config, http_client=client
        ).generate(_context())

    assert response.blocks == (ModelTextBlock("OK"),)  # w3-t1
    assert captured["thinking"] == {"type": "disabled"}
    assert "stream" not in captured
    assert "reasoning_effort" not in captured
    assert response.provider_continuation is None


def test_w3_disabled_session_rejects_legacy_enabled_continuation() -> None:
    """W3 矩阵行：disabled 会话收到旧 enabled 会话的 continuation → 拒绝，
    不回放、不静默丢弃（fail closed）。"""

    config = _config(thinking_mode="disabled", reasoning_effort=None)
    continuation = ProviderContinuationV1.create(
        provider_identity_digest=config.descriptor().identity_digest,
        opaque_payload="legacy reasoning",
    )

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)  # 若发起 HTTP 即失败，证明拒绝发生在 HTTP 前。

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(
        ProviderProtocolError, match="provider_continuity_mismatch"
    ):
        OpenAICompatibleProvider(
            config=config, http_client=client
        ).generate(_context(continuation=continuation))
    assert calls == 0
