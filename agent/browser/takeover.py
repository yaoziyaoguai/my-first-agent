"""Browser takeover completion 的 Runtime-owned external transition port。"""

from __future__ import annotations

from collections.abc import Callable

from agent.browser.profile_store import (
    BrowserProfileStore,
    ProfileIntegrityError,
    ProfileNotFoundError,
    ProfileRevisionConflict,
    ProfileRevokedError,
)
from agent.runtime.contracts import BrowserTakeoverRequestV1


def complete_browser_takeover_profile(
    request: BrowserTakeoverRequestV1,
    store: BrowserProfileStore,
    *,
    browser_identity_digest: str,
    session_is_active: Callable[[str], bool],
) -> int:
    """校验 exact headed session，并幂等推进绑定 profile revision。"""

    if request.browser_identity_digest != browser_identity_digest:
        raise ValueError("browser identity changed during takeover")
    if not session_is_active(request.session_ref):
        raise ValueError("browser takeover session is missing or drifted")
    try:
        current = store.open(request.profile_ref)
        if current.browser_identity_digest != browser_identity_digest:
            raise ValueError("browser profile binding changed during takeover")
        if current.revision == request.profile_revision + 1:
            return current.revision
        if current.revision != request.profile_revision:
            raise ValueError("browser profile binding changed during takeover")
        advanced = store.advance_revision(
            current,
            expected_revision=request.profile_revision,
        )
    except (
        ProfileIntegrityError,
        ProfileNotFoundError,
        ProfileRevisionConflict,
        ProfileRevokedError,
    ) as error:
        raise ValueError("browser profile could not be advanced") from error
    return advanced.revision


__all__ = ["complete_browser_takeover_profile"]
