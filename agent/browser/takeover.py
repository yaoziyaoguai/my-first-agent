"""Browser takeover completion 的 Runtime-owned external transition port。"""

from __future__ import annotations

from agent.browser.profile_store import (
    BrowserProfileStore,
    ProfileIntegrityError,
    ProfileLockHeldError,
    ProfileLockUnknownError,
    ProfileNotFoundError,
    ProfileRevisionConflict,
    ProfileRevokedError,
    ProfileWriterLeaseV1,
)
from agent.runtime.contracts import BrowserTakeoverRequestV1


def complete_browser_takeover_profile(
    request: BrowserTakeoverRequestV1,
    store: BrowserProfileStore,
    *,
    lease: ProfileWriterLeaseV1,
    browser_identity_digest: str,
) -> int:
    """校验 exact lease-bound session，并幂等推进绑定 profile revision 一次。

    只有持有原 session exact writer lease 的 browser tool owner 才能调用：
    lease 在 store 层与四字段 writer.lock 全等校验后，revision 从
    acquisition revision CAS 推进一次；同一 lease 的重试幂等返回，不推进
    到下一次。任何身份漂移都以 ``ValueError`` 拒绝且零 mutation。
    """

    if request.browser_identity_digest != browser_identity_digest:
        raise ValueError("browser identity changed during takeover")
    if lease.profile.profile_id != request.profile_ref:
        raise ValueError("browser takeover lease does not bind the request profile")
    if lease.profile.revision != request.profile_revision:
        raise ValueError("browser takeover lease revision does not match the request")
    try:
        advanced = store.advance_revision(
            lease,
            expected_revision=request.profile_revision,
        )
    except (
        ProfileIntegrityError,
        ProfileLockHeldError,
        ProfileLockUnknownError,
        ProfileNotFoundError,
        ProfileRevisionConflict,
        ProfileRevokedError,
    ) as error:
        raise ValueError("browser profile could not be advanced") from error
    if advanced.revision != request.profile_revision + 1:
        raise ValueError("browser profile revision advanced unexpectedly")
    return advanced.revision


__all__ = ["complete_browser_takeover_profile"]
