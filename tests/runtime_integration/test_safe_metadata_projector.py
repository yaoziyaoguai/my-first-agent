"""Safe metadata projector characterization tests.

`mask_user_visible_secrets` is the canonical secret-mask function (declared in
`agent.display_events`). Multiple call sites currently re-import it inline and
add ad-hoc post-processing (length cap, type coercion). These tests protect:

1. The projector `project_safe_metadata_text` is a thin wrapper that
   delegates to the canonical masker and applies an optional `max_length`.
2. `evidence._checkpoint_safe_summary_adapter` (the first migrated call site)
   now delegates to the projector instead of inline-importing the masker.
3. The projector is importable from the runtime_integration trust boundary.
"""

from __future__ import annotations

import re

import pytest

from agent.display_events import mask_user_visible_secrets
from agent.runtime_integration.safe_metadata import project_safe_metadata_text


def test_projector_masks_known_secret_pattern() -> None:
    """Projector must redact canonical secret patterns from its input."""

    text = "api_key=sk-testsecret1234567890123 and token=ghp_abcdef0123456789"
    projected = project_safe_metadata_text(text)
    # canonical masker redacts api_key=, token=, sk-, etc.
    assert "[REDACTED]" in projected
    assert "sk-testsecret" not in projected
    assert "ghp_abcdef" not in projected


def test_projector_redacts_with_or_without_max_length() -> None:
    """Mask-before-truncate must hold even when max_length would normally cut
    the pattern short. The projector must not leak partial secrets regardless
    of length cap.
    """

    secret = "sk-" + "X" * 200
    for cap in (None, 500):
        out = project_safe_metadata_text(secret, max_length=cap)
        assert "sk-" not in out, (
            f"sk- prefix survived projection with cap={cap}: {out!r}"
        )
        assert "[REDACTED]" in out
    # When max_length truncates the redacted marker itself, the secret prefix
    # is still gone — we just don't require the full "[REDACTED]" word.
    for cap in (5, 50):
        out = project_safe_metadata_text(secret, max_length=cap)
        assert "sk-" not in out, (
            f"sk- prefix survived projection with cap={cap}: {out!r}"
        )


def test_projector_applies_max_length() -> None:
    """max_length caps the projected output at the requested length."""

    text = "x" * 5000
    projected = project_safe_metadata_text(text, max_length=200)
    assert len(projected) == 200


def test_projector_without_max_length_passes_through() -> None:
    """Without max_length the projector returns the full masked string."""

    text = "safe text without secrets"
    projected = project_safe_metadata_text(text)
    assert projected == "safe text without secrets"


def test_projector_handles_empty_input() -> None:
    """Empty input should produce empty output without raising."""

    assert project_safe_metadata_text("") == ""
    assert project_safe_metadata_text("", max_length=100) == ""


def test_checkpoint_safe_summary_adapter_uses_projector() -> None:
    """First migrated call site: evidence._checkpoint_safe_summary_adapter must
    delegate to project_safe_metadata_text (not re-import mask_user_visible_secrets).
    """

    import inspect

    from agent.runtime_integration import evidence

    source = inspect.getsource(evidence._checkpoint_safe_summary_adapter)
    assert "project_safe_metadata_text" in source, (
        "_checkpoint_safe_summary_adapter must call project_safe_metadata_text"
    )
    assert "mask_user_visible_secrets" not in source, (
        "_checkpoint_safe_summary_adapter must not inline-import "
        "mask_user_visible_secrets after migration"
    )


def test_projector_does_not_leak_secret_pattern_after_truncation() -> None:
    """Even after truncation, the masker must run BEFORE the cap so secrets
    truncated mid-pattern do not survive in the projection.
    """

    text = "sk-" + "A" * 100  # canonical secret pattern, 103 chars
    projected = project_safe_metadata_text(text, max_length=10)
    # Mask runs first, so even the truncated projection never starts with "sk-".
    assert not projected.startswith("sk-"), (
        f"secret prefix leaked through truncation: {projected!r}"
    )


@pytest.mark.parametrize(
    "secret_input",
    [
        "api_key=secret123",
        "password=hunter2",
        "token=abc.def.ghi",
        "sk-ant-api03-abcdef",
        "-----BEGIN RSA PRIVATE KEY-----",
    ],
)
def test_projector_redacts_documented_secrets(secret_input: str) -> None:
    """Every documented secret pattern from display_events must be redacted."""

    projected = project_safe_metadata_text(secret_input)
    # canonical masker redacts all of these (sanity check parametrization)
    secret_patterns = r"secret123|hunter2|abc\.def\.ghi|sk-ant|PRIVATE KEY"
    assert re.search(secret_patterns, projected) is None, (
        f"secret pattern leaked through projector: {projected!r}"
    )


def test_projector_masks_before_truncation() -> None:
    """projector 必须先 mask 再 truncate；反之 secret 会在 truncation 后幸存。

    这个测试 P0：约束 projector 的 mask-then-truncate 顺序不可漂移。"""

    secret = "sk-" + "abcdefghijklmnop"  # canonical sk- prefix triggers masker
    truncated_only = project_safe_metadata_text(secret, max_length=4)
    assert "sk-" not in truncated_only, (
        f"secret prefix survived truncation: {truncated_only!r}"
    )


def test_projector_equivalent_to_inline_pipeline() -> None:
    """project_safe_metadata_text 必须与 inline \"mask + truncate\" 等价。"""

    text = "api_key=abc123def456 token=xyz789 short"
    projector = project_safe_metadata_text(text, max_length=10)
    masker = mask_user_visible_secrets(text)
    inline = masker[:10] if len(masker) > 10 else masker
    assert projector == inline, (
        f"projector diverges from inline pipeline: "
        f"projector={projector!r} inline={inline!r}"
    )
