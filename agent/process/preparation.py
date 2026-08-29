"""exact process preparation 共享 seam（017 Task 3）。

local_process 与 sandbox_exec 共用的 admission/revalidation/environment
builder：closed 参数解析、executable identity 解析、cwd descriptor 绑定、
封闭 env 构造。本模块是纯/bounded 逻辑——不 spawn、不认识 Goal/approval。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agent.process import admission
from agent.process.contracts import (
    SAFE_LOCALE,
    KnownNotExecuted,
    ProcessCommandV1,
    ResourceProfile,
    ResourceProfileV1,
)
from agent.tools.path_safety import WorkspaceBoundary, WorkspaceSecurityError


@dataclass(frozen=True, slots=True)
class PreparedProcessV1:
    """approval 前解析出的 exact command + 执行上下文（KTD5/F3 语义）。"""

    command: ProcessCommandV1
    cwd_path: str
    workspace_root: str
    search_paths: tuple[str, ...]
    child_path: str
    boundary: WorkspaceBoundary


@dataclass(frozen=True, slots=True)
class RevalidatedProcessV1:
    """spawn 前重验后的 exact command + cwd。"""

    command: ProcessCommandV1
    cwd_path: str


def sanitize_captured_path(captured_path: str) -> tuple[tuple[str, ...], str]:
    """PATH 只保留已解析的绝对目录，admission 与 child 共用同一份。"""

    admitted: list[str] = []
    for raw in captured_path.split(os.pathsep):
        if not raw or not Path(raw).is_absolute():
            continue
        try:
            resolved = str(Path(raw).resolve(strict=True))
        except OSError:
            continue
        if not Path(resolved).is_dir() or resolved in admitted:
            continue
        admitted.append(resolved)
    return tuple(admitted), os.pathsep.join(admitted)


def parse_process_arguments(arguments: dict) -> tuple[str, list[str], str, str]:
    executable = arguments.get("executable")
    argv = arguments.get("argv") or []
    cwd = arguments.get("cwd") or "."
    profile = arguments.get("profile") or "standard"
    if not isinstance(executable, str) or not executable or "\x00" in executable:
        raise ValueError("executable must be a non-empty NUL-free string")
    if not isinstance(argv, list) or any(
        not isinstance(item, str) or "\x00" in item for item in argv
    ):
        raise ValueError("argv must be a list of NUL-free strings")
    # F1：closed Resource Profiles 的 argv 上限（approval 前 fail closed）。
    limits = ResourceProfileV1.for_profile(ResourceProfile("standard"))
    if len(argv) > limits.argv_max_items:
        raise ValueError(
            f"argv exceeds profile limit: {len(argv)} > {limits.argv_max_items} items"
        )
    if any(len(item.encode("utf-8")) > limits.argv_item_max_bytes for item in argv):
        raise ValueError(
            f"argv item exceeds profile limit: > {limits.argv_item_max_bytes} bytes"
        )
    total = sum(len(item.encode("utf-8")) for item in argv)
    if total > limits.argv_total_max_bytes:
        raise ValueError(
            f"argv total exceeds profile limit: {total} > {limits.argv_total_max_bytes} bytes"
        )
    if len(executable.encode("utf-8")) > limits.argv_item_max_bytes:
        raise ValueError("executable token exceeds profile item byte limit")
    if not isinstance(cwd, str) or "\x00" in cwd:
        raise ValueError("cwd must be a NUL-free string")
    # F2：cwd 必须是 workspace-relative——绝对路径与 `..` approval 前拒绝。
    if cwd.startswith("/") or ".." in cwd.split("/"):
        raise ValueError("cwd must be workspace-relative (no absolute path, no ..)")
    if profile not in ("short", "standard", "long"):
        raise ValueError("profile must be short/standard/long")
    return executable, list(argv), cwd, profile


def _resolve_workspace_cwd(
    boundary: WorkspaceBoundary, cwd: str
) -> tuple[Path, str] | KnownNotExecuted:
    try:
        return boundary.resolve_directory(cwd)
    except WorkspaceSecurityError:
        return KnownNotExecuted(
            code="cwd_boundary_denied",
            message="cwd was denied by the workspace security boundary",
        )


def prepare_process(
    arguments: dict,
    *,
    workspace,
    captured_path: str,
    boundary: WorkspaceBoundary | None = None,
):  # noqa: ANN001, ANN202
    """approval 前的 exact admission：解析失败返回 KnownNotExecuted（调用方
    决定提升为 binding ValueError 还是透传）；成功返回 PreparedProcessV1。"""

    workspace_root = str(Path(workspace).absolute())
    resolved_boundary = boundary or WorkspaceBoundary(Path(workspace_root))
    if resolved_boundary.root != Path(workspace_root):
        raise ValueError("workspace boundary does not match workspace")
    search_paths, child_path = sanitize_captured_path(str(captured_path))
    executable, argv, cwd, profile = parse_process_arguments(arguments)
    identity = admission.resolve_executable(
        executable, search_paths=search_paths, workspace_root=workspace_root
    )
    if isinstance(identity, KnownNotExecuted):
        return identity
    cwd_admission = _resolve_workspace_cwd(resolved_boundary, cwd)
    if isinstance(cwd_admission, KnownNotExecuted):
        return cwd_admission
    cwd_path, cwd_descriptor = cwd_admission
    env_plan = admission.build_environment_plan(captured_path=child_path)
    command = ProcessCommandV1(
        executable_token=executable,
        argv=tuple(argv),
        cwd=cwd,
        profile=ResourceProfile(profile),
        executable_identity=identity,
        environment_policy=env_plan,
        expected_artifact_digest=None,
        cwd_descriptor=cwd_descriptor,
    )
    return PreparedProcessV1(
        command=command,
        cwd_path=str(cwd_path),
        workspace_root=workspace_root,
        search_paths=search_paths,
        child_path=child_path,
        boundary=resolved_boundary,
    )


def revalidate_process(prepared: PreparedProcessV1):  # noqa: ANN202
    """spawn 前重验：executable identity 与 cwd descriptor 相对 prepared
    快照不得漂移（同路径替换后的新实体必须 fail closed）。"""

    command = prepared.command
    identity = admission.resolve_executable(
        command.executable_token,
        search_paths=prepared.search_paths,
        workspace_root=prepared.workspace_root,
    )
    if isinstance(identity, KnownNotExecuted):
        return KnownNotExecuted(
            code="executable_identity_changed",
            message="executable no longer admitted before spawn",
        )
    if command.executable_identity is None or (
        identity.identity_digest != command.executable_identity.identity_digest
    ):
        return KnownNotExecuted(
            code="executable_identity_changed",
            message="executable identity drifted after approval",
        )
    cwd_admission = _resolve_workspace_cwd(prepared.boundary, command.cwd)
    if isinstance(cwd_admission, KnownNotExecuted):
        return cwd_admission
    cwd_path, cwd_descriptor = cwd_admission
    if cwd_descriptor != command.cwd_descriptor:
        return KnownNotExecuted(
            code="cwd_identity_changed",
            message="cwd directory identity drifted after approval",
        )
    revalidated = ProcessCommandV1(
        executable_token=command.executable_token,
        argv=command.argv,
        cwd=command.cwd,
        profile=command.profile,
        executable_identity=identity,
        environment_policy=command.environment_policy,
        expected_artifact_digest=command.expected_artifact_digest,
        cwd_descriptor=cwd_descriptor,
    )
    return RevalidatedProcessV1(command=revalidated, cwd_path=str(cwd_path))


def closed_process_environment(temp_root: str, captured_path: str) -> dict[str, str]:
    """per-invocation 封闭 env：HOME/TMPDIR 落在 temp_root 下、PATH 用清洗后
    的 child path、其余为 closed 常量——不继承任何 host env。"""

    root = Path(temp_root)
    home = root / "home"
    tmp = root / "tmp"
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp.mkdir(parents=True, exist_ok=True, mode=0o700)
    return {
        "HOME": str(home),
        "TMPDIR": str(tmp),
        "PATH": captured_path,
        "LANG": SAFE_LOCALE,
        "LC_CTYPE": SAFE_LOCALE,
        "TZ": "UTC",
    }
