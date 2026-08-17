"""015 process admission（KTD5/KTD7）：在任何 effect 之前解析 command identity。

只消费 token / search_paths / workspace_root，返回 closed ``ExecutableIdentityV1`` 或
pre-spawn ``KnownNotExecuted``。不创建 HOME/TMPDIR 或任何资源（那由 runner 在 EXECUTING
checkpoint 之后做）。revalidation 缩小 drift race，不宣称消除 kernel-level TOCTOU。
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from agent.process.contracts import (
    EnvironmentProfileV1,
    ExecutableIdentityV1,
    KnownNotExecuted,
    ResourceProfile,
    ResourceProfileV1,
    _canonical_digest,
)

_EXECUTABLE_HASH_CAP = 256 * 1024 * 1024
_SYMLINK_MAX_DEPTH = 40


def build_environment_plan(*, captured_path: str) -> EnvironmentProfileV1:
    """构造 immutable environment plan（allowlist + locale + 捕获 PATH 的 digest）。"""

    return EnvironmentProfileV1.build(captured_path=captured_path)


def resolve_executable(
    token: str,
    *,
    search_paths: tuple[str, ...] = (),
    workspace_root: str | os.PathLike | None = None,
) -> ExecutableIdentityV1 | KnownNotExecuted:
    """解析 executable token 为 closed identity，或返回 pre-spawn 拒绝。"""

    candidate = _locate(token, search_paths=search_paths, workspace_root=workspace_root)
    if candidate is None:
        return KnownNotExecuted(
            code="not_found",
            message=f"executable not found: {token}",
        )
    return _bind_identity(str(token), candidate)


def revalidate_executable(
    identity: ExecutableIdentityV1,
) -> ExecutableIdentityV1 | KnownNotExecuted:
    """紧邻 spawn 时重验 identity；任一 binding 漂移返回 ``executable_identity_changed``。"""

    try:
        info = os.stat(identity.resolved_path)
    except OSError:
        return KnownNotExecuted(
            code="executable_identity_changed",
            message="executable vanished before spawn",
        )
    try:
        content_digest = _hash_file(identity.resolved_path)
    except OSError:
        return KnownNotExecuted(
            code="executable_identity_changed",
            message="executable unreadable before spawn",
        )
    if (
        info.st_dev != identity.st_dev
        or info.st_ino != identity.st_ino
        or info.st_mode != identity.mode
        or info.st_size != identity.size
        or info.st_mtime_ns != identity.mtime_ns
        or content_digest != identity.content_digest
    ):
        return KnownNotExecuted(
            code="executable_identity_changed",
            message="executable identity drifted after approval",
        )
    return identity


def _locate(
    token: str,
    *,
    search_paths: tuple[str, ...],
    workspace_root: str | os.PathLike | None,
) -> Path | None:
    """token 为路径时按原意解析（workspace-relative 解析到 workspace）；bare name 走 PATH。"""

    if os.path.sep in token or token.startswith("."):
        path = Path(token)
        if not path.is_absolute() and workspace_root is not None:
            path = Path(workspace_root) / token
        return path
    for directory in search_paths:
        search_root = Path(directory)
        if not search_root.is_absolute():
            # 相对 PATH 会在 admission 与 spawn 的不同 cwd 下解析成不同程序，不能绑定。
            continue
        candidate = search_root / token
        if candidate.exists():
            return candidate
    if workspace_root is not None:
        ws_candidate = Path(workspace_root) / token
        if ws_candidate.exists():
            return ws_candidate
    return None


def _bind_identity(
    token: str,
    path: Path,
) -> ExecutableIdentityV1 | KnownNotExecuted:
    try:
        resolved = _resolve_symlink_chain(path)
    except OSError:
        return KnownNotExecuted(
            code="symlink_loop",
            message=f"executable symlink chain could not be resolved: {token}",
        )
    final = Path(resolved.final)
    try:
        info = os.stat(final)
    except OSError:
        return KnownNotExecuted(code="not_found", message=f"executable not found: {token}")
    if not stat.S_ISREG(info.st_mode):
        return KnownNotExecuted(
            code="not_regular",
            message=f"executable is not a regular file: {token}",
        )
    # P3（冻结合同）：超过 hash cap 的 executable 必须拒绝——``_hash_file`` 只 hash
    # 前 ``_EXECUTABLE_HASH_CAP`` 字节，超大文件不得以 prefix digest 冒充 identity。
    if info.st_size > _EXECUTABLE_HASH_CAP:
        cap = ResourceProfileV1.for_profile(
            ResourceProfile.STANDARD
        ).executable_hash_max_bytes
        return KnownNotExecuted(
            code="executable_too_large",
            message=f"executable exceeds the {cap}-byte admission cap",
        )
    if not (info.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
        return KnownNotExecuted(
            code="not_executable",
            message=f"file is not executable: {token}",
        )
    try:
        content_digest = _hash_file(final)
    except OSError:
        return KnownNotExecuted(
            code="not_readable",
            message=f"executable unreadable: {token}",
        )
    return ExecutableIdentityV1(
        token=token,
        resolved_path=str(final),
        symlink_chain=tuple(resolved.chain),
        st_dev=info.st_dev,
        st_ino=info.st_ino,
        file_type="regular",
        mode=info.st_mode,
        size=info.st_size,
        mtime_ns=info.st_mtime_ns,
        content_digest=content_digest,
        is_regular_executable=True,
        identity_digest=_identity_digest(token, str(final), resolved.chain, info, content_digest),
    )


class _Resolved:
    __slots__ = ("chain", "final")

    def __init__(self, chain: list, final: str) -> None:
        self.chain = chain
        self.final = final


def _resolve_symlink_chain(path: Path) -> _Resolved:
    """逐段解析 symlink，绑定每段 path/target/stat；loop 或过深抛 OSError。"""

    chain: list[dict] = []
    visited: set[str] = set()
    current = path
    depth = 0
    while True:
        try:
            target = os.readlink(current)
        except OSError:
            return _Resolved(chain, str(current))
        try:
            info = current.lstat()
        except OSError as error:
            raise OSError("symlink component vanished") from error
        chain.append(
            {
                "path": str(current),
                "target": target,
                "stat_digest": _stat_digest(info),
            }
        )
        canonical = os.path.realpath(str(current))
        if canonical in visited or depth >= _SYMLINK_MAX_DEPTH:
            raise OSError("symlink loop or chain too deep")
        visited.add(canonical)
        resolved_target = Path(target)
        if not resolved_target.is_absolute():
            resolved_target = current.parent / target
        current = resolved_target
        depth += 1


def _hash_file(path: os.PathLike | str) -> str:
    """bounded streaming SHA-256（受 ``_EXECUTABLE_HASH_CAP`` 限制）。"""

    digest = hashlib.sha256()
    remaining = _EXECUTABLE_HASH_CAP
    with open(path, "rb") as handle:
        while remaining > 0:
            chunk = handle.read(min(65_536, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def _stat_digest(info: os.stat_result) -> str:
    return _canonical_digest(
        {
            "device": info.st_dev,
            "inode": info.st_ino,
            "mode": info.st_mode,
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
        }
    )


def _identity_digest(
    token: str,
    resolved_path: str,
    chain: list[dict],
    info: os.stat_result,
    content_digest: str,
) -> str:
    return _canonical_digest(
        {
            "token": token,
            "resolved_path": resolved_path,
            "symlink_chain": chain,
            "device": info.st_dev,
            "inode": info.st_ino,
            "mode": info.st_mode,
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "content_digest": content_digest,
        }
    )
