"""Safe metadata projector.

`mask_user_visible_secrets` is the canonical secret-mask function in
`agent.display_events`. Multiple call sites inside the runtime_integration
trust boundary currently re-import it inline and add ad-hoc post-processing
(length cap, type coercion, etc.). This module is the minimal, import-stable
projector for that boundary:

- `project_safe_metadata_text(text, max_length=None)` runs the canonical
  masker FIRST so secrets are never truncated mid-pattern, then applies an
  optional `max_length` cap.
- Future migrations route their call sites through this projector instead of
  re-importing `mask_user_visible_secrets` directly. The first migrated site
  is `evidence._checkpoint_safe_summary_adapter`.

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
