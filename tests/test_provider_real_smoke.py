"""Opt-in real anthropic_compatible provider smoke.

This file is skipped unless ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, and
ANTHROPIC_MODEL are present. It never prints key values.
"""

from __future__ import annotations

import os

import pytest


def _compatible_env_ready() -> bool:
    return all(
        os.environ.get(name)
        for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL")
    )


pytestmark = pytest.mark.skipif(
    not _compatible_env_ready(),
    reason="anthropic_compatible smoke requires ANTHROPIC_API_KEY/BASE_URL/MODEL",
)


def test_real_anthropic_compatible_minimal_text_smoke(monkeypatch):
    from agent.provider.config import load_agent_provider_config
    from agent.provider.factory import build_model_provider

    monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER", "anthropic_compatible")
    config = load_agent_provider_config()
    provider = build_model_provider(config)

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
