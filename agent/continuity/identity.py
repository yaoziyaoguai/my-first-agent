"""不读取 workspace 内容的 canonical workspace identity。"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from agent.runtime.contracts import canonical_json_digest


@dataclass(frozen=True, slots=True)
class WorkspaceIdentityV1:
    canonical_path: str
    device: int
    inode: int
    scope_digest: str
    identity_digest: str

    @classmethod
    def resolve(cls, workspace: Path) -> WorkspaceIdentityV1:
        canonical = workspace.resolve(strict=True)
        info = canonical.stat(follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("workspace must be a real directory")
        canonical_path = os.fspath(canonical)
        scope_digest = canonical_json_digest(
            {"version": 1, "canonical_path": canonical_path}
        )
        identity_digest = canonical_json_digest(
            {
                "version": 1,
                "canonical_path": canonical_path,
                "device": info.st_dev,
                "inode": info.st_ino,
            }
        )
        return cls(
            canonical_path=canonical_path,
            device=info.st_dev,
            inode=info.st_ino,
            scope_digest=scope_digest,
            identity_digest=f"workspace:v1:{identity_digest}",
        )
