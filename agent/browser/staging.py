"""Browser upload staging 的跨 port opaque capability。"""

from __future__ import annotations

import re
from dataclasses import dataclass

_STAGING_ID = re.compile(r"upload-[0-9a-f]{16}")
_SESSION_REF = re.compile(r"[A-Za-z0-9._:-]{1,160}")
_HEX64 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class BrowserUploadStagingV1:
    """只暴露 staging identity；host path 永不跨 BrowserEnvironment port。"""

    staging_id: str
    session_ref: str
    action_digest: str
    byte_size: int
    sha256: str

    def __post_init__(self) -> None:
        if _STAGING_ID.fullmatch(self.staging_id) is None:
            raise ValueError("staging_id must be opaque")
        if _SESSION_REF.fullmatch(self.session_ref) is None:
            raise ValueError("session_ref must be a bounded opaque identifier")
        if _HEX64.fullmatch(self.action_digest) is None:
            raise ValueError("action_digest must be 64 lowercase hex chars")
        if _HEX64.fullmatch(self.sha256) is None:
            raise ValueError("sha256 must be 64 lowercase hex chars")
        if (
            isinstance(self.byte_size, bool)
            or not isinstance(self.byte_size, int)
            or self.byte_size < 0
        ):
            raise ValueError("byte_size must be a non-negative int")


__all__ = ["BrowserUploadStagingV1"]
