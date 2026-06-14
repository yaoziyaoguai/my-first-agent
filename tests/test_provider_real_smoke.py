"""Opt-in real anthropic_compatible provider smoke.

This file is skipped unless ALL of the following are true:

1. MY_FIRST_AGENT_RUN_REAL_PROVIDER_SMOKE=1 (explicit opt-in)
2. ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL / ANTHROPIC_MODEL are present
3. ANTHROPIC_API_KEY is not a known fake placeholder

It never prints key values.
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

# conftest.py setdefault 注入的假 key，以及常见占位符。
_FAKE_KEY_PATTERNS = (
    "test-key",
    "sk-test-",
    "secret-token-must-not-leak",
    "fake",
    "dummy",
    "placeholder",
    "your-api-key",
    "your-key",
    "changeme",
    "example.invalid",
)


def _real_anthropic_compatible_env_ready() -> tuple[bool, str]:
    """检查是否具备运行真实 anthropic_compatible smoke 的条件。

    Returns:
        (ready, reason) — ready 为 True 表示可以安全运行。
    """
    opt_in = os.environ.get("MY_FIRST_AGENT_RUN_REAL_PROVIDER_SMOKE", "")
    if opt_in != "1":
        return False, (
            "real provider smoke 需要显式 opt-in；"
            "请设置 MY_FIRST_AGENT_RUN_REAL_PROVIDER_SMOKE=1"
        )

    missing = []
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL"):
        if not os.environ.get(name):
            missing.append(name)
    if missing:
        return False, f"缺少环境变量: {', '.join(missing)}"

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    for pattern in _FAKE_KEY_PATTERNS:
        if pattern.lower() in api_key.lower() or pattern.lower() in base_url.lower():
            return False, (
                f"ANTHROPIC_API_KEY 或 ANTHROPIC_BASE_URL 包含已知假值模式 "
                f"({pattern})，拒绝运行 real smoke；"
                "请设置真实 ANTHROPIC_API_KEY 或检查 .env"
            )

    return True, "ready"


_READY, _SKIP_REASON = _real_anthropic_compatible_env_ready()
pytestmark = pytest.mark.skipif(not _READY, reason=_SKIP_REASON)


def test_real_anthropic_compatible_minimal_text_smoke(monkeypatch):
    from agent.provider.config import load_agent_provider_config
    from agent.provider.factory import build_model_provider

    monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER", "anthropic_compatible")
    config = load_agent_provider_config()
    provider = build_model_provider(config)

    # 安全门控：确认 provider 不是 FakeProvider
    provider_type = getattr(provider, "provider_type", "unknown")
    assert provider_type != "fake", (
        f"real smoke 需要真实 provider，当前为 {provider_type}。"
        "请检查环境变量配置"
    )

    response = provider.create(
        system="You are a test assistant.",
        messages=[{"role": "user", "content": "Reply with exactly: provider-ok"}],
        tools=[],
    )

    text = "\n".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()
    assert "provider-ok" in text


def test_real_anthropic_compatible_accepts_model_visible_tools_param(monkeypatch):
    from agent.provider.config import load_agent_provider_config
    from agent.provider.factory import build_model_provider
    from agent.tool_registry import get_model_visible_tools

    monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER", "anthropic_compatible")
    config = load_agent_provider_config()
    provider = build_model_provider(config)

    tools = get_model_visible_tools(max_mcp_tools=1)
    response = provider.create(
        system="You are a test assistant.",
        messages=[{"role": "user", "content": "Reply with exactly: provider-ok"}],
        tools=tools[:1],
    )

    assert response.stop_reason in {"end_turn", "tool_use", "max_tokens"}


def test_real_anthropic_compatible_mcp_readonly_integration(monkeypatch):
    """anthropic_compatible provider + MCP tool_executor manual round-trip。

    验证范围：anthropic_compatible provider adapter + tool_executor 的手动集成，
    不是完整 AgentLoop（core.py/chat/response_handlers）自动闭环。

    具体验证链路：
    MCP registration → tool exposure → model selection → execute_tool →
    manual tool_result append → second provider.create → final response。

    使用本地 deterministic MCP fixture（echo tool）。直调测试，不声称 E2E。
    """
    from agent.mcp import MCPServerConfig, register_mcp_tools
    from agent.mcp_stdio import StdioMCPClient
    from agent.provider.config import load_agent_provider_config
    from agent.provider.factory import build_model_provider
    from agent.tool_registry import TOOL_REGISTRY, execute_tool, get_model_visible_tools

    monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER", "anthropic_compatible")

    _fixture_server = (
        pathlib.Path(__file__).resolve().parents[1]
        / "tests" / "fixtures" / "minimal_mcp_stdio_server.py"
    )
    server_name = "e2e_real_mcp"

    try:
        # ── 1. 注册 MCP tool ──
        server = MCPServerConfig(
            name=server_name,
            command=sys.executable,
            args=(str(_fixture_server),),
            enabled=True,
        )
        client = StdioMCPClient(timeout_seconds=5)
        mcp_names = register_mcp_tools(
            [server], client,
            server_allowlist=frozenset({server_name}),
            dry_run=False,
        )
        assert len(mcp_names) > 0, "MCP registration 应注册至少 1 个 tool"

        # ── 2. 验证 model-visible tools ──
        tools = get_model_visible_tools(max_mcp_tools=1)
        mcp_tool_names = [t["name"] for t in tools if t["name"].startswith("mcp__")]
        assert len(mcp_tool_names) >= 1, "model-visible tools 应包含 MCP tool"

        # 不含 destructive MCP tools
        for t in tools:
            if t["name"].startswith("mcp__"):
                assert "write" not in t["name"].lower(), (
                    f"MCP tool 不应包含 destructive: {t['name']}"
                )
                assert "delete" not in t["name"].lower(), (
                    f"MCP tool 不应包含 destructive: {t['name']}"
                )

        # 不含 key pattern
        tools_str = str(tools)
        assert "sk-ant-" not in tools_str
        assert "sk-" not in tools_str

        # ── 3. 构建 provider ──
        config = load_agent_provider_config()
        provider = build_model_provider(config)

        # ── 4. 第一轮：让模型使用 echo tool ──
        test_message = "hello from anthropic-compatible MCP E2E"
        response1 = provider.create(
            system="You are a test assistant. Use tools when asked.",
            messages=[{
                "role": "user",
                "content": (
                    f"请使用 echo 工具发送消息 '{test_message}'。"
                    "不要直接回复文本，先调用工具。"
                ),
            }],
            tools=tools,
        )

        # key 不进 response
        response1_str = str(response1.content)
        assert "sk-ant-" not in response1_str
        assert "sk-" not in response1_str

        # ── 5. 检查模型是否选择了 MCP tool ──
        tool_blocks = [
            b for b in response1.content
            if getattr(b, "type", None) == "tool_use"
        ]

        if not tool_blocks:
            # 安全打印：只显示 stop_reason，不输出模型原始文本
            # provider response content 可能包含不安全的 provider 输出
            pytest.skip(
                f"模型未选择 MCP tool "
                f"(stop_reason={response1.stop_reason})——"
                f"provider reachable, tools accepted, "
                f"model did not select tool"
            )

        tb = tool_blocks[0]
        assert tb.name.startswith("mcp__"), (
            f"模型应选择 MCP tool，实际选择了: {tb.name}"
        )
        print(f"\n  ✅ 模型选择了 MCP tool: {tb.name}")

        # tool_use input 不含 key
        assert "sk-" not in str(tb.input).lower(), "tool_use input 不应含 key"

        # ── 6. 执行 tool ──
        tool_result = execute_tool(tb.name, tb.input)
        assert tool_result is not None, "tool_executor 应返回结果"
        result_str = str(tool_result)
        assert len(result_str) > 0, "tool_result 不应为空"
        print(f"  ✅ tool_executor 执行成功: {result_str[:100]}")

        # ── 7. 第二轮：tool_result 回 messages ──
        messages: list[dict] = [
            {"role": "user", "content": f"请使用 echo 工具发送消息 '{test_message}'。"},
            {
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "id": tb.id,
                    "name": tb.name,
                    "input": tb.input,
                }],
            },
            {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tb.id,
                    "content": result_str,
                }],
            },
        ]

        # 验证 messages 不含 key
        messages_str = str(messages)
        assert "sk-ant-" not in messages_str, "messages 不应含 API key"
        assert "sk-" not in messages_str, "messages 不应含 API key"

        response2 = provider.create(
            system="You are a test assistant.",
            messages=messages,
            tools=tools,
        )

        # ── 8. 验证最终响应 ──
        final_text = "\n".join(
            block.text
            for block in response2.content
            if getattr(block, "type", None) == "text"
        ).strip()

        assert len(final_text) > 0, "final response 应有文本内容"
        # 验证模型确实使用了 tool_result 中的内容
        assert (
            test_message in final_text
            or "echo:" in final_text
            or "E2E" in final_text
        ), (
            f"final response 应引用 tool_result 内容\n"
            f"  final_text[:300]: {final_text[:300]}"
        )
        print("  ✅ final response 正确引用了 tool_result")

        # key 不进第二轮 response
        response2_str = str(response2.content)
        assert "sk-ant-" not in response2_str
        assert "sk-" not in response2_str

    finally:
        for name in list(TOOL_REGISTRY):
            if name.startswith(f"mcp__{server_name}__"):
                TOOL_REGISTRY.pop(name, None)
