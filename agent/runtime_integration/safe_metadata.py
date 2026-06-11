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

from agent.display_events import mask_user_visible_secrets


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
    cap = max(0, max_length - len(marker))
    if len(masked) <= cap:
        return masked
    return masked[:cap] + marker
