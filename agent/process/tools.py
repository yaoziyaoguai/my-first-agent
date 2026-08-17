"""015 governed ``local_process`` tool definition（KTD1/KTD11）。

只暴露 ToolSpec 静态合同：模型只能提交结构化 ``executable``/``argv``/``cwd``/``profile``。
prepare/invoke/lease-matching/receipt-minting 由 ``KernelToolRuntime``（U6b）在唯一 tool
callable lifecycle 中处理；本模块不拥有 Runtime state 或 checkpoint。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from agent.process import admission
from agent.process.contracts import (
    SAFE_LOCALE,
    SAME_UID_TRUST_NOTICE,
    KnownNotExecuted,
    ProcessCommandV1,
    ResourceProfile,
    ResourceProfileV1,
)
from agent.process.runner import run_local_process
from agent.runtime.contracts import (
    ApprovalPolicy,
    EgressClass,
    ExecutionAuthorityClass,
    OutputPolicy,
    SideEffectClass,
    ToolRisk,
    ToolSpec,
)
from agent.tools.path_safety import WorkspaceBoundary, WorkspaceSecurityError

LOCAL_PROCESS_TOOL_NAME = "local_process"
LOCAL_PROCESS_TOOL_VERSION = "local-process-v1"


def local_process_tool_spec() -> ToolSpec:
    """``local_process`` governed tool 的 closed 静态合同（design §6 / §13）。"""

    return ToolSpec(
        name=LOCAL_PROCESS_TOOL_NAME,
        version=LOCAL_PROCESS_TOOL_VERSION,
        description=(
            "Run one structured, shell-free foreground local process after exact "
            "same-UID approval. Provide executable, argv, workspace-relative cwd, and a "
            "closed resource profile (short/standard/long). No command string, shell, "
            "pipeline, redirection, stdin, env, raw timeout, background or TTY."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "executable": {"type": "string"},
                "argv": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "cwd": {"type": "string"},
                "profile": {
                    "type": "string",
                    "enum": ["short", "standard", "long"],
                },
            },
            "required": ["executable"],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.EXTERNAL,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={
            "execution_authority": ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS.value,
            "same_uid_trust_notice": SAME_UID_TRUST_NOTICE,
            "shell": False,
            "closed_profiles": ["short", "standard", "long"],
        },
        output_limit_chars=64_000,
        egress=EgressClass.NONE,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
    )


def build_local_process_registration(
    *,
    workspace: os.PathLike | str,
    captured_path: str,
    clock: Callable[[], str] | None = None,
    workspace_boundary: WorkspaceBoundary | None = None,
):
    """构造 ``local_process`` 的 RegisteredTool：closed spec + prepare_binding + executor。

    prepare_binding 在 effect 前解析 executable identity、构造 command fingerprint 与
    same-UID preview；executor（func）紧邻 spawn 时重新解析并 revalidate identity、构造
    closed environment + isolated HOME/TMPDIR、运行 runner，返回 ``ProcessExecutionDraftV1``
    或 drift 时的 ``KnownNotExecuted``。KernelToolRuntime 负责 lease 匹配、approval 与
    receipt 铸造（KTD1/KTD3/KTD8）。
    """

    from agent.runtime.tools import RegisteredTool  # 局部导入，避免加载顺序耦合

    workspace_root = str(Path(workspace).absolute())
    boundary = workspace_boundary or WorkspaceBoundary(Path(workspace_root))
    if boundary.root != Path(workspace_root):
        raise ValueError("local_process workspace boundary does not match workspace")
    search_paths, child_path = _sanitize_captured_path(str(captured_path))
    spec = local_process_tool_spec()

    def prepare_binding(arguments: dict) -> dict:
        # F4（review finding / design §6）：closed 4 字段——artifact digest 的
        # authority 是用户（ResolveApproval.confirmed_artifact_*），不进 model binding。
        executable, argv, cwd, profile = _parse_arguments(arguments)
        identity = admission.resolve_executable(
            executable, search_paths=search_paths, workspace_root=workspace_root
        )
        if isinstance(identity, KnownNotExecuted):
            raise ValueError(f"executable not admitted: {identity.code}")
        # F3（review finding 2026-08-16）：cwd 在 approval 前解析并绑定 descriptor
        # identity（st_dev/st_ino）——缺失/越界/非目录的 cwd 是 binding_failure，
        # 不展示幻想 cwd；descriptor 进 fingerprint（同路径替换后的新目录不得
        # 复用旧 lease）。
        cwd_admission = _resolve_workspace_cwd(boundary, cwd)
        if isinstance(cwd_admission, KnownNotExecuted):
            raise ValueError(f"cwd not admitted: {cwd_admission.code}")
        _cwd_path, cwd_descriptor = cwd_admission
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
        binding = {
            "command_fingerprint": command.command_fingerprint,
            "executable_digest": identity.identity_digest,
            "resolved_executable_path": identity.resolved_path,
            "argv_digest": hashlib.sha256(json.dumps(list(argv)).encode("utf-8")).hexdigest(),
            "cwd_digest": hashlib.sha256(cwd.encode("utf-8")).hexdigest(),
            "cwd_descriptor": cwd_descriptor,
            "resource_profile": profile,
            "environment_policy_digest": env_plan.policy_digest,
            "trust_notice_id": "same_uid_process_v1",
            "trust_notice_digest": hashlib.sha256(
                SAME_UID_TRUST_NOTICE.encode("utf-8")
            ).hexdigest(),
            "effect_preview": _render_preview(
                executable, argv, cwd, profile, identity.resolved_path,
            ),
            "process_argv": list(argv),
            "process_cwd": cwd,
            "process_profile": profile,
        }
        return binding

    executor = _make_executor(workspace_root, search_paths, child_path, boundary)
    return RegisteredTool(spec=spec, func=executor, prepare_binding=prepare_binding)


def _make_executor(
    workspace_root: str,
    search_paths: tuple[str, ...],
    captured_path: str,
    boundary: WorkspaceBoundary,
):
    def execute(intent):  # noqa: ANN001
        binding = intent.safety_binding
        executable = intent.arguments.get("executable")
        argv = tuple(binding.get("process_argv", ()))
        cwd = binding.get("process_cwd", ".")
        profile = binding.get("process_profile", "standard")
        identity = admission.resolve_executable(
            executable, search_paths=search_paths, workspace_root=workspace_root
        )
        if isinstance(identity, KnownNotExecuted):
            return KnownNotExecuted(
                code="executable_identity_changed",
                message="executable no longer admitted before spawn",
            )
        if identity.identity_digest != binding["executable_digest"]:
            return KnownNotExecuted(
                code="executable_identity_changed",
                message="executable identity drifted after approval",
            )
        resource = ResourceProfileV1.for_profile(ResourceProfile(profile))
        cwd_admission = _resolve_workspace_cwd(boundary, cwd)
        if isinstance(cwd_admission, KnownNotExecuted):
            return cwd_admission
        cwd_path, cwd_descriptor = cwd_admission
        # F3：紧邻 effect 重验 cwd descriptor——approval 与 spawn 之间同路径替换
        # （rm+mkdir）必须 fail closed，不得在新目录里执行批准的命令。
        if cwd_descriptor != binding.get("cwd_descriptor"):
            return KnownNotExecuted(
                code="cwd_identity_changed",
                message="cwd directory identity drifted after approval",
            )
        home = tempfile.mkdtemp(prefix="fa-process-home-")
        tmp_dir = tempfile.mkdtemp(prefix="fa-process-tmp-")
        environment = {
            "HOME": home,
            "TMPDIR": tmp_dir,
            "PATH": captured_path,
            "LANG": SAFE_LOCALE,
            "LC_CTYPE": SAFE_LOCALE,
            "TZ": "UTC",
        }
        try:
            return run_local_process(
                resolved_executable=identity.resolved_path,
                argv=argv,
                cwd=str(cwd_path),
                profile=resource,
                environment=environment,
            )
        finally:
            _safe_rmtree(home)
            _safe_rmtree(tmp_dir)

    return execute


def _sanitize_captured_path(captured_path: str) -> tuple[tuple[str, ...], str]:
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


def _parse_arguments(arguments: dict) -> tuple[str, list[str], str, str]:
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
    # F1（review finding / design §7.3）：closed Resource Profiles 的 argv 上限
    # （128 items / 16KiB 单项 / 64KiB 总量）必须在 approval 前 fail closed——
    # 此前只有合同定义、零消费。executable token 与 argv item 同界。
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
    # F2（review finding）：cwd 必须是 workspace-relative——绝对路径与 `..` 在
    # approval 前拒绝（此前能进 preview 展示永不执行的 cwd，披露有歧义）。
    if cwd.startswith("/") or ".." in cwd.split("/"):
        raise ValueError("cwd must be workspace-relative (no absolute path, no ..)")
    if profile not in ("short", "standard", "long"):
        raise ValueError("profile must be short/standard/long")
    # F4（review finding）：expected_artifact 不再是 model 参数（schema
    # additionalProperties=False 直接拒绝）；artifact digest 由用户在
    # ResolveApproval.confirmed_artifact_* 确认。
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


def _render_preview(
    executable: str, argv: list[str], cwd: str, profile: str, resolved: str,
) -> str:
    # F3（review finding）：argv 逐 token JSON-quoting——literal 且无歧义（列表边界
    # 可区分、换行/引号被转义、不可伪造披露行）；§12.1 披露项用真实 profile 数值。
    # F2（review finding）：cwd 与 executable token 同标准 JSON-quote——模型可控
    # 字符串一律不得能伪造 `limits:`/`executable:` 披露行。
    resource = ResourceProfileV1.for_profile(ResourceProfile(profile))
    rendered_argv = " ".join(json.dumps(token) for token in argv)
    lines = [
        f"local_process profile={json.dumps(profile)} cwd={json.dumps(cwd)}",
        f"  executable: {json.dumps(executable)} -> {json.dumps(resolved)}",
        f"  argv: {rendered_argv}",
        (
            f"  limits: timeout={resource.wall_deadline_seconds}s, "
            f"stdout cap={resource.stdout_cap_bytes} bytes, "
            f"stderr cap={resource.stderr_cap_bytes} bytes, "
            f"combined cap={resource.combined_cap_bytes} bytes"
        ),
        (
            "  environment: closed allowlist "
            "(HOME/TMPDIR/PATH/LANG/LC_CTYPE/TZ); no env inheritance"
        ),
        (
            "  lease: up to 8 uses, expires 60 minutes after approval, "
            "revocable (RevokeProcessAuthority)"
        ),
    ]
    lines.append(SAME_UID_TRUST_NOTICE)
    return "\n".join(lines)


def _safe_rmtree(path: str) -> None:
    import shutil
    from contextlib import suppress

    with suppress(OSError):
        shutil.rmtree(path, ignore_errors=True)
