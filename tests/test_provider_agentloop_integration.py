from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_response_handlers_serialize_provider_tool_use_block():
    from agent.provider.protocol import ProviderResponse, ProviderTextBlock, ToolUseBlock
    from agent.response_handlers import _serialize_assistant_content

    response = ProviderResponse(
        content=[
            ProviderTextBlock(text="I will call a tool."),
            ToolUseBlock(id="toolu_1", name="read_file", input={"path": "README.md"}),
        ],
        stop_reason="tool_use",
        usage={},
    )

    assert _serialize_assistant_content(response.content) == [
        {"type": "text", "text": "I will call a tool."},
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "read_file",
            "input": {"path": "README.md"},
        },
    ]


def test_call_model_uses_non_streaming_provider_when_loop_context_has_provider(monkeypatch):
    pytest.importorskip("anthropic")
    import agent.core as core
    from agent.loop_context import LoopContext
    from agent.provider.protocol import ProviderResponse, ProviderTextBlock
    from agent.state import create_agent_state

    class _Provider:
        provider_type = "anthropic_compatible"
        supports_tools = True
        supports_streaming = False

        def __init__(self):
            self.requests = []

        def create(self, *, system, messages, tools):
            self.requests.append({
                "system": system,
                "messages": messages,
                "tools": tools,
            })
            return ProviderResponse(
                content=[ProviderTextBlock(text="provider-ok")],
                stop_reason="end_turn",
                usage={"input_tokens": 1, "output_tokens": 1},
                raw_provider_name="anthropic_compatible",
            )

    state = create_agent_state(system_prompt="test")
    state.conversation.messages.append({"role": "user", "content": "hi"})
    monkeypatch.setattr(core, "state", state)
    monkeypatch.setattr(
        core,
        "get_model_visible_tools",
        lambda max_mcp_tools=5, explicit_allowlist=None: [
            {"name": "fake_tool", "input_schema": {"type": "object"}}
        ],
    )

    provider = _Provider()
    emitted = []
    turn_state = core.TurnState(
        system_prompt="sys",
        on_runtime_event=lambda event: emitted.append(event),
    )
    loop_ctx = LoopContext(
        client=SimpleNamespace(messages=SimpleNamespace()),
        model_name="unused-by-provider",
        max_loop_iterations=10,
        model_provider=provider,
    )

    response = core._call_model(turn_state, loop_ctx)

    assert response.content[0].text == "provider-ok"
    assert provider.requests[0]["tools"] == [
        {"name": "fake_tool", "input_schema": {"type": "object"}}
    ]
    assert provider.requests[0]["messages"][-1] == {"role": "user", "content": "hi"}
    assert emitted


def test_build_loop_context_builds_compatible_provider_from_env(monkeypatch):
    pytest.importorskip("anthropic")
    import agent.core as core
    import agent.core_contexts as core_contexts

    class _Provider:
        provider_type = "anthropic_compatible"
        supports_tools = True
        supports_streaming = False

    captured = {}

    def _fake_build_provider_from_env():
        captured["called"] = True
        return _Provider()

    monkeypatch.setattr(
        core_contexts,
        "build_model_provider_from_env",
        _fake_build_provider_from_env,
    )

    loop_ctx = core._build_loop_context(
        SimpleNamespace(messages=SimpleNamespace()),
        model_name="claude-compatible",
        max_loop_iterations=10,
    )

    assert captured["called"] is True
    assert loop_ctx.model_provider.provider_type == "anthropic_compatible"
