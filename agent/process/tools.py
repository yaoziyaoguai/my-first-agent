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

from agent.process.contracts import (
    SAME_UID_TRUST_NOTICE,
    KnownNotExecuted,
    ResourceProfile,
    ResourceProfileV1,
)
from agent.process.preparation import (
    SessionPathAdmissions,
    closed_process_environment,
    prepare_process,
    revalidate_process,
)
from agent.process.runner import run_local_process
from agent.runtime.contracts import (
    ApprovalPolicy,
    EgressClass,
    ExecutionAuthorityClass,
    OutputPolicy,
    ResultSourceKind,
    SideEffectClass,
    ToolRisk,
    ToolSpec,
)
from agent.tools.path_safety import WorkspaceBoundary

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
            "pipeline, redirection, stdin, env, raw timeout, background or TTY. When this "
            "process validates a Goal artifact, materialize and read it back before "
            "requesting this process because approval can require its current digest. "
            "For an existing project test or validator, use read-only workspace tools to "
            "find its direct workspace executable and invoke that path with only its real "
            "arguments: never use list/find/cat as a process discovery command, and never "
            "wrap it with sh/bash/python/env. A rejected unrelated candidate is not proof "
            "that the requested validator cannot run; inspect the workspace result and "
            "propose the direct executable instead."
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
    path_admissions: SessionPathAdmissions | None = None,
):
    """构造 ``local_process`` 的 RegisteredTool：closed spec + prepare_binding + executor。

    prepare_binding 在 effect 前解析 executable identity、构造 command fingerprint 与
    same-UID preview；executor（func）紧邻 spawn 时重新解析并 revalidate identity、构造
    closed environment + isolated HOME/TMPDIR、运行 runner，返回 ``ProcessExecutionDraftV1``
    或 drift 时的 ``KnownNotExecuted``。KernelToolRuntime 负责 lease 匹配、approval 与
    receipt 铸造（KTD1/KTD3/KTD8）。注入 ``path_admissions`` 后，prepare 与 spawn 各自
    取当时的 effective PATH（会话内 /env-path 准入动态生效）；``None`` 时全链行为与
    启动期冻结 PATH 逐字节一致。
    """

    from agent.runtime.tools import RegisteredTool  # 局部导入，避免加载顺序耦合

    workspace_root = str(Path(workspace).absolute())
    boundary = workspace_boundary or WorkspaceBoundary(Path(workspace_root))
    if boundary.root != Path(workspace_root):
        raise ValueError("local_process workspace boundary does not match workspace")
    spec = local_process_tool_spec()

    def _effective_captured_path() -> str:
        if path_admissions is None:
            return str(captured_path)
        return path_admissions.effective_captured_path(str(captured_path))

    def prepare_binding(arguments: dict) -> dict:
        # F4：closed 4 字段——artifact digest 的 authority 是用户，不进 model
        # binding。exact admission 走共享 seam（017 Task 3）。PATH 取当前
        # effective 值（会话内准入在每次 prepare 时生效）。
        prepared = prepare_process(
            arguments,
            workspace=workspace,
            captured_path=_effective_captured_path(),
            boundary=boundary,
        )
        if isinstance(prepared, KnownNotExecuted):
            raise ValueError(f"preparation not admitted: {prepared.code}")
        command = prepared.command
        identity = command.executable_identity
        env_plan = command.environment_policy
        assert identity is not None and env_plan is not None
        executable = command.executable_token
        argv = list(command.argv)
        cwd = command.cwd
        profile = command.profile.value
        binding = {
            "command_fingerprint": command.command_fingerprint,
            # 2026-10-26（用户裁决：命令输出复用）：proof 的稳定目标。label 用
            # 短指纹便于阅读，digest 用完整 fingerprint（已绑定 executable/
            # argv/cwd 三者 digest），不因截断降低绑定强度。
            "consent_target": f"command:{command.command_fingerprint[:16]}",
            "target_digest": command.command_fingerprint,
            "executable_digest": identity.identity_digest,
            "resolved_executable_path": identity.resolved_path,
            "argv_digest": hashlib.sha256(json.dumps(list(argv)).encode("utf-8")).hexdigest(),
            "cwd_digest": hashlib.sha256(cwd.encode("utf-8")).hexdigest(),
            "cwd_descriptor": command.cwd_descriptor,
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

    executor = _make_executor(workspace_root, boundary, path_admissions, str(captured_path))
    return RegisteredTool(
        spec=spec,
        func=executor,
        prepare_binding=prepare_binding,
        # 2026-10-26（用户裁决：命令输出复用）：成功 stdout 铸 command_output
        # proof；会话许可按类覆盖，仍受 TTL/次数/撤销与 goal 绑定约束。
        result_source_kind=ResultSourceKind.WORKSPACE_COMMAND,
    )


def _make_executor(
    workspace_root: str,
    boundary: WorkspaceBoundary,
    path_admissions: SessionPathAdmissions | None,
    captured_path: str,
):
    def execute(intent):  # noqa: ANN001
        # 每次 invoke 取当前 effective PATH：approval 与 spawn 之间 /env-path
        # 准入可能已变化，同一次调用内 prepare 与 closed environment 必须一致。
        effective_captured_path = (
            str(captured_path)
            if path_admissions is None
            else path_admissions.effective_captured_path(str(captured_path))
        )
        binding = intent.safety_binding
        # 与 approval 签名对比：重新走共享 seam，再逐项核对已批准 digest/
        # descriptor（executable 内容漂移 → executable_identity_changed；
        # cwd 同路径替换 → cwd_identity_changed，F3 语义不变）。
        prepared = prepare_process(
            intent.arguments,
            workspace=workspace_root,
            captured_path=effective_captured_path,
            boundary=boundary,
        )
        if isinstance(prepared, KnownNotExecuted):
            return prepared
        revalidated = revalidate_process(prepared)
        if isinstance(revalidated, KnownNotExecuted):
            return revalidated
        # 与已批准 binding 的粒度对比：executable 内容漂移与 cwd 同路径替换
        # 分别报 closed code（F3 语义不变）。
        approved_identity = prepared.command.executable_identity
        if (
            approved_identity is None
            or approved_identity.identity_digest != binding.get("executable_digest")
        ):
            return KnownNotExecuted(
                code="executable_identity_changed",
                message="executable identity drifted after approval",
            )
        if prepared.command.cwd_descriptor != binding.get("cwd_descriptor"):
            return KnownNotExecuted(
                code="cwd_identity_changed",
                message="cwd directory identity drifted after approval",
            )
        # 冻结 PATH 下这是恒真式；动态 /env-path 准入下它是 approval→spawn 的
        # 环境策略不变式：同 digest 的可执行文件不得带变更后的 PATH 落地。
        if (
            prepared.command.environment_policy.policy_digest
            != binding.get("environment_policy_digest")
        ):
            return KnownNotExecuted(
                code="environment_policy_changed",
                message="prepared environment changed; prepare and review the command again",
            )
        resource = ResourceProfileV1.for_profile(prepared.command.profile)
        temp_root = tempfile.mkdtemp(prefix="fa-process-")
        # 子进程 PATH 用 effective 值经共享 seam 清洗后的 child_path（admitted
        # 前缀 + 启动期 base 同一规则去相对/去重）：与 binding 的
        # environment_policy 同源，且 admissions=None 时与冻结 PATH 行为一致。
        environment = closed_process_environment(temp_root, prepared.child_path)
        try:
            return run_local_process(
                resolved_executable=revalidated.command.executable_identity.resolved_path,
                argv=revalidated.command.argv,
                cwd=revalidated.cwd_path,
                profile=resource,
                environment=environment,
            )
        finally:
            _safe_rmtree(temp_root)

    return execute


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
