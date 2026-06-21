"""R-series: provider tool-name sanitization (real-provider trial finding).

Provider APIs (Anthropic / OpenAI / DeepSeek) require tool names matching
`^[a-zA-Z0-9_-]+$`. Internal namespaced tools use dots (e.g. `demo.write_demo_note`).
The `anthropic_compatible` adapter must sanitize names on the outgoing request and
restore them on the tool_use response so the runtime dispatches to the real tool.

Root-cause evidence (real DeepSeek `/anthropic` call, 2026-06-21):
`Invalid 'tools[0].function.name': string does not match pattern '^[a-zA-Z0-9_-]+$'.`
"""

from __future__ import annotations

import re

import pytest

from agent.provider.anthropic_http import AnthropicCompatibleProvider
from agent.provider.config import AgentProviderConfig
from agent.provider.protocol import ProviderResponseError, ToolUseBlock

_VALID = re.compile(r"^[a-zA-Z0-9_-]+$")


def _config() -> AgentProviderConfig:
    return AgentProviderConfig(
        provider_type="anthropic_compatible",
        model="m",
        base_url="https://x.test",
        api_key="k",
        max_tokens=16,
    )


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.captured: dict = {}

    def post(self, url, *, headers=None, json=None, **kw):  # noqa: ANN001
        self.captured["url"] = url
        self.captured["tools"] = (json or {}).get("tools")
        self.captured["body_keys"] = sorted((json or {}).keys())
        return _FakeResp(self._payload)


def test_dotted_tool_name_sanitized_on_send():
    client = _FakeClient(
        {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn", "usage": {}}
    )
    provider = AnthropicCompatibleProvider(config=_config(), http_client=client)
    provider.create(
        system="s",
        messages=[{"role": "user", "content": "c"}],
        tools=[{"name": "demo.write_demo_note", "description": "d", "input_schema": {}}],
    )
    sent_names = [t["name"] for t in client.captured["tools"]]
    assert "demo.write_demo_note" not in sent_names
    assert all(_VALID.match(n) for n in sent_names)


def test_tool_use_response_name_restored_to_dotted():
    payload = {
        "content": [
            {
                "type": "tool_use",
                "id": "t1",
                "name": "demo_write_demo_note",
                "input": {"path": "x"},
            }
        ],
        "stop_reason": "tool_use",
        "usage": {},
    }
    client = _FakeClient(payload)
    provider = AnthropicCompatibleProvider(config=_config(), http_client=client)
    resp = provider.create(
        system="s",
        messages=[{"role": "user", "content": "c"}],
        tools=[{"name": "demo.write_demo_note", "description": "d", "input_schema": {}}],
    )
    tool_uses = [b for b in resp.content if isinstance(b, ToolUseBlock)]
    assert tool_uses and tool_uses[0].name == "demo.write_demo_note"


def test_already_valid_tool_name_unchanged():
    client = _FakeClient(
        {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn", "usage": {}}
    )
    provider = AnthropicCompatibleProvider(config=_config(), http_client=client)
    provider.create(
        system="s",
        messages=[{"role": "user", "content": "c"}],
        tools=[{"name": "write_file", "description": "d", "input_schema": {}}],
    )
    assert client.captured["tools"][0]["name"] == "write_file"


def test_no_tools_omits_tools_field():
    client = _FakeClient(
        {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn", "usage": {}}
    )
    provider = AnthropicCompatibleProvider(config=_config(), http_client=client)
    provider.create(system="s", messages=[{"role": "user", "content": "c"}], tools=[])
    assert "tools" not in client.captured["body_keys"]


def test_collision_safe_distinct_provider_names_and_restore():
    # demo.a_b 与 demo.a.b 都会基础清洗成 demo_a_b —— 必须区分，不能塌缩成同一个。
    payload = {
        "content": [
            {"type": "tool_use", "id": "t1", "name": "demo_a_b", "input": {}},
            {"type": "tool_use", "id": "t2", "name": "demo_a_b_2", "input": {}},
        ],
        "stop_reason": "tool_use",
        "usage": {},
    }
    client = _FakeClient(payload)
    provider = AnthropicCompatibleProvider(config=_config(), http_client=client)
    resp = provider.create(
        system="s",
        messages=[{"role": "user", "content": "c"}],
        tools=[
            {"name": "demo.a_b", "description": "d", "input_schema": {}},
            {"name": "demo.a.b", "description": "d", "input_schema": {}},
        ],
    )
    sent_names = [t["name"] for t in client.captured["tools"]]
    # distinct + collision-suffixed + provider-valid
    assert sent_names == ["demo_a_b", "demo_a_b_2"]
    assert all(_VALID.match(n) for n in sent_names)
    # restore: each sanitized name maps back to its DISTINCT original (no ambiguity)
    restored = sorted((b.id, b.name) for b in resp.content if isinstance(b, ToolUseBlock))
    assert restored == [("t1", "demo.a_b"), ("t2", "demo.a.b")]


def test_model_visible_tools_are_top_level_anthropic_style():
    # 合约守卫：adapter 依赖 get_model_visible_tools 产出顶层 Anthropic-style
    # ({name, description, input_schema})，而非 OpenAI nested function.name。
    # 若未来改成 nested 结构，本测试会失败 → 强制同步更新 adapter 清洗逻辑。
    import agent.tools  # noqa: F401  triggers @register_tool registrations
    from agent.tool_registry import get_model_visible_tools

    tools = get_model_visible_tools(max_mcp_tools=5, explicit_allowlist=None)
    assert tools, "expected registered model-visible tools"
    for tool in tools:
        assert isinstance(tool.get("name"), str) and tool["name"]
        assert "function" not in tool  # top-level Anthropic-style, not nested OpenAI
        assert "input_schema" in tool


def test_stream_path_sanitizes_and_completes():
    # stream() 委托 create() —— send 清洗 + restore 同样生效；stream 正常完成。
    payload = {
        "content": [
            {"type": "tool_use", "id": "t1", "name": "demo_write_demo_note", "input": {}}
        ],
        "stop_reason": "tool_use",
        "usage": {},
    }
    client = _FakeClient(payload)
    provider = AnthropicCompatibleProvider(config=_config(), http_client=client)
    events = list(
        provider.stream(
            system="s",
            messages=[{"role": "user", "content": "c"}],
            tools=[{"name": "demo.write_demo_note", "description": "d", "input_schema": {}}],
        )
    )
    sent_names = [t["name"] for t in client.captured["tools"]]
    assert all(_VALID.match(n) for n in sent_names)
    assert events, "stream should yield events (create restored the tool_use)"
    # stream yields a tool_request for the (restored) tool_use + a final marker
    assert any(getattr(e, "event_type", None) for e in events)


def test_provider_4xx_error_includes_actionable_hint_and_body():
    """R-051: a 4xx error must include an actionable hint + redacted body preview."""

    class _ErrResp:
        status_code = 400
        text = '{"error":{"message":"Invalid tools[0].function.name: pattern"}}'

        def json(self):
            return {}

    class _ErrClient:
        captured: dict = {}

        def post(self, url, *, headers=None, json=None, **kw):  # noqa: ANN001
            return _ErrResp()

    provider = AnthropicCompatibleProvider(config=_config(), http_client=_ErrClient())
    with pytest.raises(ProviderResponseError) as exc_info:
        provider.create(system="s", messages=[{"role": "user", "content": "c"}], tools=[])
    error_msg = str(exc_info.value)
    assert "http_status:400" in error_msg
    assert "tool-name" in error_msg.lower() or "protocol" in error_msg.lower()
    assert "body:" in error_msg
    assert "pattern" in error_msg
