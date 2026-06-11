"""Safe metadata projector.

`mask_user_visible_secrets` is the canonical secret-mask function in
`agent.display_events`. Multiple call sites inside the runtime_integration
trust boundary currently re-import it inline and add ad-hoc post-processing
(length cap, type coercion, etc.). This module is the minimal, import-stable
projector for that boundary:

- `project_safe_metadata_text(text, max_length=None)` runs the canonical
  masker FIRST so secrets are never truncated mid-pattern, then applies an
  optional `max_length` cap.
- `project_safe_metadata_text_with_marker(text, max_length, marker="...")`
  runs the masker first, then truncates the masked output to `max_length`
  minus the marker, and appends the marker. This variant is for log/observer
  surfaces that want a visible "truncated" signal in the JSONL stream.
- Future migrations route their call sites through this projector instead of
  re-importing `mask_user_visible_secrets` directly. Migrated sites:
    D1 `agent.runtime_observer._safe_log_value` (log/observer)
    `evidence._checkpoint_safe_summary_adapter` (D2 partial; was first)

This module is a thin wrapper, not a replacement. The canonical masker stays
in `agent.display_events` because it lives with the UI-projection code that
defines the regexes. The projector only adds a stable import surface and a
sane truncation order for runtime_integration trust-boundary callers.
"""

from __future__ import annotations

import re

from agent.display_events import mask_user_visible_secrets

# Defense-in-depth redactors for the evidence_persistence trust boundary
# (D2). The canonical masker is chat-surface focused; these catch
# additional secret shapes the leak-gate property test exercises. They
# live here (not in display_events) because the leak-gate contract is a
# projector-level invariant for the evidence_persistence boundary, and
# display_events intentionally keeps its regex set narrow.
_EXTRA_REDACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    # AWS access key id.
    re.compile(r"\bAKIA[0-9A-Z]{12,}\b"),
    # GitHub classic + fine-grained PATs.
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    # Google OAuth refresh / access tokens (ya29.* family).
    re.compile(r"\bya29\.[A-Za-z0-9_\-]{16,}\b"),
    # Slack bot / user / app tokens.
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    # Generic JWT (3 base64url segments separated by dots).
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
    # "Bearer <token>" prefix form.
    re.compile(r"(?<![A-Za-z0-9])Bearer\s+[A-Za-z0-9._\-]{12,}", re.IGNORECASE),
)


def project_safe_metadata_text(
    text: str,
    *,
    max_length: int | None = None,
) -> str:
    """Run the canonical secret masker, then apply an optional length cap.

    Order matters: masker first, cap second. If the cap ran first, a secret
    pattern truncated mid-token could leak through unmasked.
    """

    masked = mask_user_visible_secrets(text)
    if max_length is not None and len(masked) > max_length:
        return masked[:max_length]
    return masked


def project_safe_metadata_text_with_marker(
    text: str,
    *,
    max_length: int,
    marker: str = "...",
) -> str:
    """Variant of :func:`project_safe_metadata_text` for log/observer surfaces.

    Runs the canonical masker first, then truncates the masked output to
    ``max_length - len(marker)`` and appends ``marker``. The marker is added
    AFTER masking, so it never participates in the masker's regex evaluation.

    Trust boundary: D1 (runtime_observer) uses this variant so a visible
    truncation signal lands in ``agent_log.jsonl`` without ever exposing a
    raw secret prefix that the cap would otherwise cut mid-pattern.
    """

    if max_length <= 0:
        return ""
    masked = mask_user_visible_secrets(text)
    for pattern in _EXTRA_REDACT_PATTERNS:
        masked = pattern.sub("[REDACTED]", masked)
    cap = max(0, max_length - len(marker))
    if len(masked) <= cap:
        return masked
    return masked[:cap] + marker
