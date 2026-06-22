"""G-045 (observability): token usage surfacing.

The provider seam parses token usage (openai_http.py:282-297, normalize.py) into
ProviderResponse.usage, but the main loop previously DROPPED it (converted the
response to a str at loop.py:1033). G-045 fixes this by:

1. Capturing `response.usage` at the turn boundary (loop.py:1030) and emitting
   a `llm_usage` log event per turn.
2. Rendering `llm_usage` in `main.py logs` via log_viewer._format_data_summary.

Usage contains only integer token counts (no prompt/completion text), so it is
safe to surface without redaction. FakeProvider returns an empty usage dict, so
the event is correctly NOT emitted for fake/local turns.
"""

from __future__ import annotations

from agent.log_viewer import _format_data_summary
from agent.provider.protocol import ProviderResponse


def test_llm_usage_rendered_with_full_usage():
    """log_viewer renders llm_usage with input/output/total tokens."""
    out = _format_data_summary("llm_usage", {
        "input_tokens": 150,
        "output_tokens": 80,
        "total_tokens": 230,
    })
    assert "in=150" in out
    assert "out=80" in out
    assert "total=230" in out


def test_llm_usage_rendered_with_partial_usage():
    """log_viewer renders llm_usage gracefully when some keys are missing."""
    out = _format_data_summary("llm_usage", {
        "input_tokens": 150,
        "output_tokens": None,
    })
    assert "in=150" in out
    assert "total" not in out


def test_llm_usage_rendered_empty():
    """log_viewer returns empty string for an empty usage dict."""
    out = _format_data_summary("llm_usage", {})
    assert out == ""


def test_fake_provider_usage_is_empty():
    """ProviderResponse default usage is empty — the loop.py `if _turn_usage:`
    guard relies on this so fake/local turns do not emit spurious usage events."""
    response = ProviderResponse(content=[], stop_reason="end_turn")
    assert not response.usage, (
        "ProviderResponse default usage must be empty so the guard works"
    )


def test_provider_response_has_usage_field():
    """ProviderResponse must have a usage dict field (the propagation channel)."""
    response = ProviderResponse(content=[], stop_reason="end_turn")
    assert hasattr(response, "usage")
    assert isinstance(response.usage, dict)
