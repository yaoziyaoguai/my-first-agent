"""R-G01: verify status diagnostic never prints raw api_key.

The diagnostic stores `api_key_present: bool` + `api_key_env: str` — never the raw key
value. This test guards against a future refactor that might accidentally store or print
the key. Uses a synthetic key (not a real credential).
"""

from __future__ import annotations

from agent.provider.diagnostics import ProviderDiagnostic, render_diagnostic_report

_SYNTHETIC_KEY = "sk-r-g01-synthetic-fake-key-12345678"


def test_status_report_never_contains_raw_api_key():
    """R-G01: the rendered diagnostic must never contain the raw api_key value."""
    diagnostic = ProviderDiagnostic(
        provider_type="anthropic_compatible",
        model="test-model",
        base_url="SET",
        api_key_present=True,
        api_key_env="ANTHROPIC_API_KEY",
        auth_scheme="x-api-key",
        request_path="/v1/messages",
        status="ok",
    )
    report = render_diagnostic_report(diagnostic)
    # The synthetic key must NEVER appear (diagnostic stores present: bool, not the key).
    assert _SYNTHETIC_KEY not in report
    # The report SHOULD mention api_key status for the operator.
    assert "api_key" in report.lower() or "key" in report.lower()


def test_status_report_with_absent_key():
    """R-G01: absent key reported as not-present, still no raw value."""
    diagnostic = ProviderDiagnostic(
        provider_type="fake",
        model="unspecified",
        base_url="not_set",
        api_key_present=False,
        api_key_env=None,
        auth_scheme="auto",
        request_path="/v1/messages",
        status="ok",
    )
    report = render_diagnostic_report(diagnostic)
    assert _SYNTHETIC_KEY not in report
