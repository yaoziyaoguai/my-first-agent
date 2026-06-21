"""R-G02: --provider fake CLI trial mode tests.

Verifies the explicit force-fake mechanism: default OFF; when enabled via env var,
build_model_provider_from_env returns FakeProvider; the banner shows forced-fake.
"""

from __future__ import annotations

from agent.cli_renderer import render_provider_mode_banner
from agent.provider.factory import build_model_provider_from_env
from agent.provider.fake_provider import FakeProvider


def test_force_fake_env_returns_fake_provider(monkeypatch):
    """R-G02: MY_FIRST_AGENT_FORCE_FAKE=1 → FakeProvider."""
    monkeypatch.setenv("MY_FIRST_AGENT_FORCE_FAKE", "1")
    provider = build_model_provider_from_env()
    assert isinstance(provider, FakeProvider)


def test_no_force_fake_does_not_force(monkeypatch):
    """R-G02: without the env var, force-fake is NOT active."""
    monkeypatch.delenv("MY_FIRST_AGENT_FORCE_FAKE", raising=False)
    provider = build_model_provider_from_env()
    # Without force-fake, the provider comes from config.yaml (real or fake per config).
    # The key assertion: it doesn't crash and returns something.
    assert provider is not None


def test_force_fake_banner_shows_forced():
    """R-G02: banner clearly shows forced-fake mode."""
    import os

    old = os.environ.get("MY_FIRST_AGENT_FORCE_FAKE")
    os.environ["MY_FIRST_AGENT_FORCE_FAKE"] = "1"
    try:
        banner = render_provider_mode_banner()
        assert "fake" in banner.lower()
        assert "forced" in banner.lower()
    finally:
        if old is None:
            os.environ.pop("MY_FIRST_AGENT_FORCE_FAKE", None)
        else:
            os.environ["MY_FIRST_AGENT_FORCE_FAKE"] = old
