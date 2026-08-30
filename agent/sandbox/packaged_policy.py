"""strict packaged-Skill policy 的 canonical admission 与 Seatbelt 编译。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from agent.sandbox.contracts import (
    PackagedSkillResourceLimitsV1,
    PackagedSkillSandboxPolicyV1,
)
from agent.sandbox.policy import escape_seatbelt_path

_PRODUCT_ROOT = Path(__file__).resolve().parents[2]


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


def _canonical_roots(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value:
        raise ValueError(f"{name} must be a non-empty tuple of roots")
    return tuple(sorted(_canonical_existing(item, name, directory=True) for item in value))


def _require_no_overlap(roots: tuple[str, ...]) -> None:
    for index, left in enumerate(roots):
        left_path = Path(left)
        for right in roots[index + 1 :]:
            right_path = Path(right)
            if left == right or left_path in right_path.parents or right_path in left_path.parents:
                raise ValueError(f"roots must not overlap: {left} vs {right}")


def _require_read_only(path: str, name: str) -> None:
    if os.stat(path, follow_symlinks=False).st_mode & 0o222:
        raise ValueError(f"{name} must not be writable")


def _is_within(child: str, parent: str) -> bool:
    child_path, parent_path = Path(child), Path(parent)
    return child_path == parent_path or parent_path in child_path.parents


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
) -> PackagedSkillSandboxPolicyV1:
    """构造唯一 strict packaged policy；任一 root identity 不确定即拒绝。"""

    interpreter = _canonical_existing(interpreter_path, "interpreter_path", directory=False)
    if not os.stat(interpreter, follow_symlinks=False).st_mode & 0o111:
        raise ValueError("interpreter_path must be executable")
    runtime = _canonical_roots(runtime_roots, "runtime_roots")
    package = _canonical_existing(package_root, "package_root", directory=True)
    temp = _canonical_existing(temp_root, "temp_root", directory=True)
    system = _canonical_roots(system_runtime_roots, "system_runtime_roots")
    workspace = _canonical_existing(workspace_root, "workspace_root", directory=True)
    home = _canonical_existing(home_root, "home_root", directory=True)
    state = _canonical_existing(state_root, "state_root", directory=True)
    private = _canonical_roots(private_roots, "private_roots") if private_roots else ()
    _require_no_overlap(
        (*runtime, package, temp, *system, workspace, home, state, *private)
    )
    if any(_is_within(package, denied) for denied in (workspace, home, state)):
        raise ValueError("package_root must not be under a denied root")
    if not any(_is_within(interpreter, root) for root in (*runtime, *system)):
        raise ValueError(
            "interpreter_path must be under a qualified runtime/system root"
        )
    if any(_is_within(root, str(_PRODUCT_ROOT)) for root in runtime):
        raise ValueError("runtime_roots must not be under the product tree")
    for root in (*runtime, package):
        _require_read_only(root, "runtime/package root")
    return PackagedSkillSandboxPolicyV1(
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
    )


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

    if not isinstance(policy, PackagedSkillSandboxPolicyV1):
        raise TypeError("packaged policy type is required")
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
        for root in (*policy.runtime_roots, policy.package_root, *policy.system_runtime_roots)
    ]
    clauses.append(f'(allow file-read* (subpath "{escape_seatbelt_path(session)}"))')
    clauses.append(
        f'(allow file-write-data (literal "{escape_seatbelt_path(session)}/result.json"))'
    )
    clauses.append(
        f'(allow file-write-data (literal "{escape_seatbelt_path(session)}/artifact.bin"))'
    )
    return "\n".join(clauses) + "\n"
