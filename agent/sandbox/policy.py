"""017 native sandbox policy builder 与 Seatbelt profile compiler。

唯一 admission 点 ``build_sandbox_policy``：canonical 路径、root 不重叠、
git metadata（可读禁写）与 unreadable carveout 派生。profile compiler 只
输出固定子句 + 经单一转义函数的路径（spec §5；plan Task 1 Step 5）。
"""

from __future__ import annotations

import stat
from pathlib import Path

from agent.sandbox.contracts import (
    SandboxMode,
    SandboxNetworkMode,
    SandboxPolicyV1,
)

# 敏感文件名模式（spec §5「`.env`/secret 文件名模式」；plan Task 1 Step 2
# 冻结的六个）——编译为 deny read/write 的路径段 regex 子句。
SENSITIVE_FILENAME_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
)
_GIT_METADATA_NAMES = (".git", ".codex")
_GITDIR_PREFIX = "gitdir: "
_GITDIR_MAX_BYTES = 256
_BACKEND_WRITE_LITERALS = ("/dev/null",)


def escape_seatbelt_path(value: str) -> str:
    """单一转义点：拒绝 NUL/换行/引号/反斜杠，其余原样（SBCL 字符串内安全）。"""

    if not isinstance(value, str):
        raise ValueError(f"seatbelt path must be a string: {value!r}")
    if any(ch in value for ch in ("\x00", "\n", "\r")):
        raise ValueError(f"seatbelt path contains control characters: {value!r}")
    if '"' in value or "\\" in value:
        raise ValueError(f"seatbelt path contains quote/backslash: {value!r}")
    return value


def deny_write_subpath(path: str) -> str:
    return f'(deny file-write* (subpath "{escape_seatbelt_path(path)}"))'


def deny_read_subpath(path: str) -> str:
    return f'(deny file-read* (subpath "{escape_seatbelt_path(path)}"))'


def allow_write_subpath(path: str) -> str:
    return f'(allow file-write* (subpath "{escape_seatbelt_path(path)}"))'


def allow_backend_literals() -> list[str]:
    return [
        f'(allow file-write* (literal "{escape_seatbelt_path(path)}"))'
        for path in _BACKEND_WRITE_LITERALS
    ]


def _fnmatch_to_regex(pattern: str) -> str:
    """fnmatch 形状 → 锚定路径段 regex（仅支持前导 `*` 与 `.*` 两种冻结形状）。"""

    if pattern.startswith("*"):
        core = re_escape_segment(pattern[1:])
        return rf'(^|/)[^/]*{core}$'
    if pattern.endswith(".*"):
        core = re_escape_segment(pattern[:-2])
        return rf'(^|/){core}(\.[^/]*)?$'
    core = re_escape_segment(pattern)
    return rf'(^|/){core}$'


def re_escape_segment(value: str) -> str:
    # 仅转义 regex 元字符；路径中已被 escape_seatbelt_path 排除引号/反斜杠
    return value.replace(".", r"\.")


def _sensitive_pattern_clauses() -> list[str]:
    clauses: list[str] = []
    for pattern in SENSITIVE_FILENAME_PATTERNS:
        regex = _fnmatch_to_regex(pattern)
        clauses.append(f'(deny file-read* (regex #"{regex}"))')
        clauses.append(f'(deny file-write* (regex #"{regex}"))')
    return clauses


def _canonical_existing(path: object, name: str) -> str:
    candidate = Path(path)  # type: ignore[arg-type]
    if not candidate.is_absolute():
        raise ValueError(f"{name} must be a canonical absolute path")
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise ValueError(f"{name} must be a canonical existing path") from error
    if str(candidate) != str(resolved):
        raise ValueError(
            f"{name} must be canonical (symlink/non-normalized input rejected): "
            f"{candidate} != {resolved}",
        )
    return str(resolved)


def _require_disjoint(roots: list[str]) -> None:
    for index, left in enumerate(roots):
        for right in roots[index + 1:]:
            left_path, right_path = Path(left), Path(right)
            if left == right or left_path in right_path.parents or right_path in left_path.parents:
                raise ValueError(
                    f"roots must not overlap: {left} vs {right}",
                )


def _resolve_private(workspace: str, entry: object) -> str:
    if not isinstance(entry, str) or not entry:
        raise ValueError("private_roots entries must be non-empty strings")
    if any(character in entry for character in ("\x00", "\n", "\r")):
        raise ValueError("private_roots entries must not contain control characters")
    candidate = Path(entry)
    if not candidate.is_absolute():
        if ".." in candidate.parts:
            raise ValueError("private_roots entries must not escape their anchor")
        candidate = Path(workspace) / entry
    try:
        info = candidate.lstat()
    except FileNotFoundError:
        try:
            resolved = candidate.resolve(strict=False)
        except OSError as error:
            raise ValueError("private_roots entry cannot be resolved") from error
        if candidate != resolved:
            raise ValueError(
                "private_roots entry must not traverse symlinks or non-normalized paths"
            ) from None
        return str(candidate)
    except OSError as error:
        raise ValueError("private_roots entry cannot be inspected") from error
    if stat.S_ISLNK(info.st_mode):
        raise ValueError("private_roots entry must not be a symlink")
    return _canonical_existing(candidate, "private_roots entry")


def resolve_private_roots(anchor: object, entries: tuple) -> tuple[str, ...]:
    """把可信 anchor 下的 closed private paths 解析为稳定的绝对拒读集合。"""

    canonical_anchor = _canonical_existing(anchor, "private_roots anchor")
    if not Path(canonical_anchor).is_dir():
        raise ValueError("private_roots anchor must be a real directory")
    resolved_entries: list[str] = []
    for entry in entries:
        if not isinstance(entry, str) or not entry or Path(entry).is_absolute():
            raise ValueError(
                "private_roots closed entries must be non-empty relative paths"
            )
        resolved_entries.append(_resolve_private(canonical_anchor, entry))
    resolved = tuple(resolved_entries)
    if len(resolved) != len(set(resolved)):
        raise ValueError("private_roots entries must resolve to distinct paths")
    return resolved


def _git_metadata_roots(workspace: str) -> tuple[str, ...]:
    roots: list[str] = []
    workspace_path = Path(workspace)
    for name in _GIT_METADATA_NAMES:
        candidate = workspace_path / name
        if not candidate.exists():
            continue
        if candidate.is_dir():
            roots.append(str(candidate))
            continue
        if name != ".git" or not candidate.is_file():
            continue
        raw = candidate.read_bytes()
        if len(raw) > _GITDIR_MAX_BYTES:
            raise ValueError("gitdir pointer exceeds bounded size")
        try:
            text = raw.decode("utf-8", errors="strict").strip()
        except UnicodeDecodeError as error:
            raise ValueError("gitdir pointer malformed") from error
        if not text.startswith(_GITDIR_PREFIX) or "\n" in text:
            raise ValueError("gitdir pointer malformed")
        target_raw = text[len(_GITDIR_PREFIX):].strip()
        target = Path(target_raw)
        if not target.is_absolute():
            target = workspace_path / target
        try:
            resolved = target.resolve(strict=True)
        except (FileNotFoundError, OSError) as error:
            raise ValueError("gitdir target does not resolve") from error
        if not (resolved == workspace_path.parent or workspace_path.parent in resolved.parents):
            raise ValueError(
                "gitdir target escapes the workspace parent; refusing policy",
            )
        # gitfile 本身也决定仓库身份，必须与已验证的 target 一起保持可读禁写。
        roots.append(str(candidate))
        roots.append(str(resolved))
    return tuple(roots)


def build_sandbox_policy(
    *,
    mode: SandboxMode,
    network: SandboxNetworkMode,
    workspace: object,
    temp_root: object,
    state_root: object,
    home: object,
    private_roots: tuple = (),
) -> SandboxPolicyV1:
    """policy 唯一 admission：canonical + 不重叠 + carveout 派生。

    - confined modes：writable = workspace + temp（workspace-write）或空
      （read-only）；git metadata 可读禁写；state/private roots unreadable。
    - danger-full-access：不携带任何 Seatbelt filesystem root；network=off
      时仍编译 network-only profile，只有 network=full 无 profile。
    """

    workspace_canonical = _canonical_existing(workspace, "workspace")
    temp_canonical = _canonical_existing(temp_root, "temp_root")
    state_canonical = _canonical_existing(state_root, "state_root")
    home_canonical = _canonical_existing(home, "home")
    _require_disjoint(
        [workspace_canonical, temp_canonical, state_canonical, home_canonical],
    )
    private = tuple(
        _resolve_private(workspace_canonical, entry) for entry in private_roots
    )
    if mode is SandboxMode.DANGER_FULL_ACCESS:
        git_roots: tuple[str, ...] = ()
        unreadable: tuple[str, ...] = ()
    else:
        git_roots = _git_metadata_roots(workspace_canonical)
        unreadable = (state_canonical, *private)
    writable: tuple[str, ...] = ()
    if mode is SandboxMode.WORKSPACE_WRITE:
        writable = (workspace_canonical, temp_canonical)
    return SandboxPolicyV1(
        mode=mode,
        network=network,
        workspace_root=workspace_canonical,
        temp_root=temp_canonical,
        state_root=state_canonical,
        home_root=home_canonical,
        writable_roots=writable,
        git_metadata_roots=git_roots,
        unreadable_roots=unreadable,
    )


# danger+off 的 network-only profile（Oracle 审计方案 1）：只叠网络限制，
# 不携带任何 filesystem 子句——danger 不提供 filesystem 隔离。
NETWORK_ONLY_SEATBELT_PROFILE = "(version 1)\n(allow default)\n(deny network*)\n"


def compile_seatbelt_profile(policy: SandboxPolicyV1) -> str:
    """固定子句 + policy 派生路径；danger+full bypass 没有 profile（plan Step 5）。"""

    if policy.mode is SandboxMode.DANGER_FULL_ACCESS:
        if policy.network is SandboxNetworkMode.FULL:
            raise ValueError("unconfined bypass has no Seatbelt profile")
        # danger+off：精确三行 network-only profile，绝不落入 filesystem 模板。
        return NETWORK_ONLY_SEATBELT_PROFILE
    clauses = ["(version 1)", "(allow default)", "(deny file-write*)"]
    clauses += allow_backend_literals()
    clauses += [allow_write_subpath(root) for root in policy.writable_roots]
    # Seatbelt deny 优先于 allow：carveout 拒绝写在 allow-write 之后仍然生效
    # （由 Task 2 的 functional probe 在真实 sandbox-exec 上实证）。
    clauses += [deny_write_subpath(root) for root in policy.git_metadata_roots]
    clauses += [deny_read_subpath(root) for root in policy.unreadable_roots]
    clauses += [deny_write_subpath(root) for root in policy.unreadable_roots]
    clauses += _sensitive_pattern_clauses()
    if policy.network is SandboxNetworkMode.OFF:
        clauses.append("(deny network*)")
    return "\n".join(clauses) + "\n"
