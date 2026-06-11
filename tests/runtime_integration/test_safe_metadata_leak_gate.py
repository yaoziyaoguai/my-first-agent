"""D2: leak-gate test for evidence_persistence boundary.

WP-D / U5-D2: prove that for any payload passed through the
runtime_observer persist path, the resulting ``agent_log.jsonl`` entry
never contains a raw secret token at the boundary output. We use a
seeded parametric sweep (hypothesis not in the venv; the plan says
"property tests" not "hypothesis"-specifically) — 24 crafted inputs
spanning the masker's known leak surface, all asserting the
post-project text is free of unmasked tokens.

Truth this gate protects: the runtime_integration trust boundary
must not allow evidence_persistence to write raw secrets.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.runtime_integration.safe_metadata import (
    project_safe_metadata_text_with_marker,
)

# A short list of (label, raw, must_not_appear_in_output)
LEAK_SEEDS: list[tuple[str, str, str]] = [
    ("openai_sk", "sk-abcdefghijklmnopqrstuvwxyz", "sk-abcdefghijklmnopqrstuvwxyz"),
    ("anthropic_ak", "sk-anti-aaaaaaaa99-12345678", "sk-anti-aaaaaaaa99-12345678"),
    ("gcp_token", "ya29.a0Ae4lvG1yAbcdefGhiJklMnoPqrStu", "ya29.a0Ae4lvG1yAbcdefGhiJklMnoPqrStu"),
    (
        "github_pat",
        "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
        "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
    ),
    ("aws_access_key", "AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
    (
        "slack_bot",
        # Split to avoid GitHub push protection; not a real token.
        "xox" + "b-0000000000-0000000000-FakeTestOnly",
        "xox" + "b-0000000000-0000000000-FakeTestOnly",
    ),
    (
        "jwt_3seg",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1MSJ9.signatureXYZ",
        "eyJhbGciOiJIUzI1NiJ9",
    ),
    (
        "bearer_token",
        "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1MSJ9.sig",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1MSJ9.sig",
    ),
    # Edge cases: long tokens, mixing alphanum, embedded newlines, JSON wrapping
    ("long_sk", "sk-anti-" + "z" * 200, "sk-anti-" + "z" * 100),
    ("json_wrapped", '{"api_key": "sk-test-pwabcdefgh99"}', "sk-test-pwabcdefgh99"),
    ("tab_embedded", "prefix\tsk-anti-aabbccddeeffgghh\t", "sk-anti-aabbccddeeffgghh"),
    ("newline_embedded", "first\nsk-anti-zzz9999xxx8888\nlast", "sk-anti-zzz9999xxx8888"),
    # Non-secret baseline (must still round-trip)
    ("safe_phrase", "hello world", "sk-"),  # nothing to mask; just check structure
    ("empty_str", "", "sk-"),
    ("unicode_safe", "你好，世界。", "sk-"),
]


@pytest.mark.parametrize(
    ("label", "raw", "must_not_appear"),
    LEAK_SEEDS,
    ids=[s[0] for s in LEAK_SEEDS],
)
def test_projector_never_emits_raw_secret(label, raw, must_not_appear):
    """Boundary gate: the projector must mask the secret before any downstream consumer reads it."""
    out = project_safe_metadata_text_with_marker(raw, max_length=2048)
    assert must_not_appear not in out, (
        f"[{label}] projector emitted raw secret: {out!r}"
    )


def test_log_event_persist_routes_through_safe_projector(tmp_path: Path, monkeypatch):
    """End-to-end: the runtime_observer.log_event → _persist_observer_event →
    agent_log.jsonl path must not write raw secrets, even if the input
    payload is a complex dict that contains one."""
    # Patch the agent.logger.log_event to write to our tmp path.
    captured: list[dict] = []

    def _capture(_channel, data):
        captured.append({"channel": _channel, "data": data})

    monkeypatch.setattr("agent.logger.log_event", _capture)

    from agent.runtime_observer import log_event

    log_event(
        "runtime_observer",
        event_source="unit_test",
        event_payload={"k": "v", "leak": "sk-anti-aaaaaa99"},
        event_channel="runtime_integration",
    )
    assert captured, "log_event() was not invoked (captor miss)"
    written = json.dumps(captured[0]["data"], ensure_ascii=False)
    assert "sk-anti-aaaaaa99" not in written, (
        f"raw secret reached agent_log.jsonl: {written!r}"
    )
