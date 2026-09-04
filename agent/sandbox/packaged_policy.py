"""strict packaged-Skill policy 的 canonical admission 与 Seatbelt 编译。"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

from agent.runtime.contracts import canonical_json_digest
from agent.sandbox.contracts import (
    PackagedSkillResourceLimitsV1,
    PackagedSkillSandboxPolicyV1,
    SandboxMode,
    SandboxNetworkMode,
)
from agent.sandbox.policy import escape_seatbelt_path


def _canonical_existing(path: object, name: str, *, directory: bool) -> str:
    try:
        candidate = Path(path)  # type: ignore[arg-type]
    except TypeError as error:
        raise ValueError(f"{name} must be a canonical absolute path") from error
    if not candidate.is_absolute():
        raise ValueError(f"{name} must be a canonical absolute path")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"{name} must be a canonical existing path") from error
    if candidate != resolved:
        raise ValueError(f"{name} must be canonical (symlink/non-normalized input rejected)")
    if directory and not resolved.is_dir():
        raise ValueError(f"{name} must be a directory")
    if not directory and not resolved.is_file():
        expected = "directory" if directory else "regular file"
        raise ValueError(f"{name} must be a {expected}")
    return str(resolved)


def _canonical_roots(
    value: object,
    name: str,
    *,
    allow_empty: bool = False,
    require_sorted: bool = True,
) -> tuple[str, ...]:
    if not isinstance(value, tuple) or (not value and not allow_empty):
        raise ValueError(f"{name} must be a non-empty tuple of roots")
    roots = tuple(_canonical_existing(item, name, directory=True) for item in value)
    if require_sorted and roots != tuple(sorted(roots)):
        raise ValueError(f"{name} must be sorted canonical roots")
    return roots


def _canonicalize_roots(
    value: object, name: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    roots = _canonical_roots(
        value, name, allow_empty=allow_empty, require_sorted=False
    )
    if len(set(roots)) != len(roots):
        raise ValueError(f"{name} must not contain duplicate roots")
    return tuple(sorted(roots))


def _require_no_overlap(roots: tuple[str, ...]) -> None:
    for index, left in enumerate(roots):
        left_path = Path(left)
        for right in roots[index + 1 :]:
            right_path = Path(right)
            if left == right or left_path in right_path.parents or right_path in left_path.parents:
                raise ValueError(f"roots must not overlap: {left} vs {right}")


def _canonical_package_read_paths(package: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple) or any(not isinstance(item, str) for item in value):
        raise ValueError("package_read_paths must be a tuple of relative paths")
    paths: list[str] = []
    for item in value:
        parts = item.split("/")
        if (
            not item
            or item.startswith("/")
            or "\\" in item
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError("package_read_paths must contain canonical relative paths")
        target = Path(package, *parts)
        canonical = _canonical_existing(target, "package_read_path", directory=False)
        if not _is_within(canonical, package):
            raise ValueError("package_read_path must remain under package_root")
        paths.append(item)
    if len(set(paths)) != len(paths):
        raise ValueError("package_read_paths must not contain duplicates")
    return tuple(sorted(paths))


def _is_within(child: str, parent: str) -> bool:
    child_path, parent_path = Path(child), Path(parent)
    return child_path == parent_path or parent_path in child_path.parents


def _validate_resource_limits(limits: object) -> None:
    if type(limits) is not PackagedSkillResourceLimitsV1:
        raise ValueError("resource_limits must use a closed packaged profile")
    expected = PackagedSkillResourceLimitsV1.for_profile(limits.profile)
    if limits != expected:
        raise ValueError("packaged resource limits do not match their closed profile")


def _validate_digest(value: object, name: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} must be bare hex64")


def validate_packaged_skill_policy(policy: PackagedSkillSandboxPolicyV1) -> None:
    """在每次 profile emit 前重验 strict policy 的全部 authority。"""

    if type(policy) is not PackagedSkillSandboxPolicyV1:
        raise ValueError("packaged policy type is required")
    if policy.mode is not SandboxMode.READ_ONLY or policy.network is not SandboxNetworkMode.OFF:
        raise ValueError("packaged policy mode/network must remain closed")
    _validate_resource_limits(policy.resource_limits)
    _validate_digest(policy.runtime_closure_digest, "runtime_closure_digest")
    _validate_digest(policy.system_runtime_digest, "system_runtime_digest")
    expected_digest = canonical_json_digest(policy.identity_values())
    if policy.policy_digest != expected_digest:
        raise ValueError("packaged sandbox policy digest mismatch")

    interpreter = _canonical_existing(policy.interpreter_path, "interpreter_path", directory=False)
    if not os.stat(interpreter, follow_symlinks=False).st_mode & 0o111:
        raise ValueError("interpreter_path must be executable")
    runtime = _canonical_roots(policy.runtime_roots, "runtime_roots")
    package = _canonical_existing(policy.package_root, "package_root", directory=True)
    package_read_paths = _canonical_package_read_paths(
        package, policy.package_read_paths
    )
    if package_read_paths != policy.package_read_paths:
        raise ValueError("package_read_paths must be sorted canonical paths")
    temp = _canonical_existing(policy.temp_root, "temp_root", directory=True)
    system = _canonical_roots(policy.system_runtime_roots, "system_runtime_roots")
    workspace = _canonical_existing(policy.workspace_root, "workspace_root", directory=True)
    home = _canonical_existing(policy.home_root, "home_root", directory=True)
    state = _canonical_existing(policy.state_root, "state_root", directory=True)
    private = _canonical_roots(
        policy.private_roots, "private_roots", allow_empty=True
    )
    read_roots = (*runtime, package, *system)
    if any(root == "/" for root in read_roots):
        raise ValueError("runtime_roots must not admit filesystem root")
    _require_no_overlap((*runtime, package, temp, *system, workspace, home, state, *private))
    if any(_is_within(package, denied) for denied in (workspace, home, state)):
        raise ValueError("package_root must not be under a denied root")
    if not any(_is_within(interpreter, root) for root in (*runtime, *system)):
        raise ValueError(
            "interpreter_path must be under a qualified runtime/system root"
        )
    # runtime 是调用方（composition root）提供的 trusted application runtime：
    # 应用自身 interpreter/stdlib/固定 runner 所在目录，天然 owner-writable 且
    # 可能位于 product tree。sandbox 不对它做 host 侧完整性或漂移保证（那是
    # 部署边界的职责）；这里只约束 child 侧：strict profile 拒绝对 runtime 的
    # 一切写入，读取范围精确到上述 root。


def build_packaged_skill_policy(
    *,
    interpreter_path: object,
    runtime_roots: object,
    package_root: object,
    temp_root: object,
    system_runtime_roots: object,
    workspace_root: object,
    home_root: object,
    state_root: object,
    private_roots: object,
    runtime_closure_digest: str,
    system_runtime_digest: str,
    resource_limits: PackagedSkillResourceLimitsV1,
    package_read_paths: object = (),
) -> PackagedSkillSandboxPolicyV1:
    """构造唯一 strict packaged policy；任一 root identity 不确定即拒绝。"""

    interpreter = _canonical_existing(interpreter_path, "interpreter_path", directory=False)
    runtime = _canonicalize_roots(runtime_roots, "runtime_roots")
    package = _canonical_existing(package_root, "package_root", directory=True)
    package_reads = _canonical_package_read_paths(package, package_read_paths)
    temp = _canonical_existing(temp_root, "temp_root", directory=True)
    system = _canonicalize_roots(system_runtime_roots, "system_runtime_roots")
    workspace = _canonical_existing(workspace_root, "workspace_root", directory=True)
    home = _canonical_existing(home_root, "home_root", directory=True)
    state = _canonical_existing(state_root, "state_root", directory=True)
    private = _canonicalize_roots(
        private_roots, "private_roots", allow_empty=True
    )
    policy = PackagedSkillSandboxPolicyV1(
        interpreter_path=interpreter,
        runtime_roots=runtime,
        package_root=package,
        temp_root=temp,
        system_runtime_roots=system,
        workspace_root=workspace,
        home_root=home,
        state_root=state,
        private_roots=private,
        runtime_closure_digest=runtime_closure_digest,
        system_runtime_digest=system_runtime_digest,
        resource_limits=resource_limits,
        package_read_paths=package_reads,
    )
    validate_packaged_skill_policy(policy)
    return policy


def _session_root(policy: PackagedSkillSandboxPolicyV1, environment: Mapping[str, str]) -> str:
    session = environment.get("TMPDIR")
    if not isinstance(session, str):
        raise ValueError("TMPDIR must name a session root")
    canonical = _canonical_existing(session, "TMPDIR", directory=True)
    if Path(canonical).parent != Path(policy.temp_root):
        raise ValueError("TMPDIR must be a canonical direct child of policy.temp_root")
    return canonical


def compile_packaged_skill_profile(
    policy: PackagedSkillSandboxPolicyV1,
    environment: Mapping[str, str],
) -> str:
    """编译无默认许可、仅两个 literal 输出文件的 Seatbelt profile。"""

    validate_packaged_skill_policy(policy)
    session = _session_root(policy, environment)
    clauses = [
        "(version 1)",
        "(deny default)",
        "(allow process-info*)",
        "(allow signal (target self))",
        "(allow sysctl-read)",
        '(allow file-read-data (literal "/"))',
        f'(allow process-exec (literal "{escape_seatbelt_path(policy.interpreter_path)}"))',
        "(deny process-fork)",
        "(deny network*)",
    ]
    clauses += [
        f'(allow file-read* (subpath "{escape_seatbelt_path(root)}"))'
        for root in (*policy.runtime_roots, *policy.system_runtime_roots)
    ]
    readable_directories = {policy.package_root}
    for relative in policy.package_read_paths:
        target = Path(policy.package_root, *relative.split("/"))
        readable_directories.update(
            str(parent)
            for parent in target.parents
            if parent == Path(policy.package_root)
            or Path(policy.package_root) in parent.parents
        )
        clauses.append(
            f'(allow file-read* (literal "{escape_seatbelt_path(str(target))}"))'
        )
    # 目录字面量需要 file-read-data：runner 以 O_NOFOLLOW fd 链从 package
    # root 逐层打开目录做 TOCTOU 安全遍历，仅 metadata 无法 opendir。这同时
    # 允许 child 列出这些目录的文件名（内容仍仅限精确 package_read_paths）。
    clauses += [
        f'(allow file-read* (literal "{escape_seatbelt_path(path)}"))'
        for path in sorted(readable_directories)
    ]
    clauses.append(f'(allow file-read* (subpath "{escape_seatbelt_path(session)}"))')
    clauses.append(
        f'(allow file-write-data (literal "{escape_seatbelt_path(session)}/result.json"))'
    )
    clauses.append(
        f'(allow file-write-data (literal "{escape_seatbelt_path(session)}/artifact.bin"))'
    )
    return "\n".join(clauses) + "\n"
