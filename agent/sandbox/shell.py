"""governed ``shell_exec`` registration（governed-shell-v1）。

Shell 组合（``&&``/pipeline/重定向/expansion）不解析、不黑名单——固定转译为
``/bin/sh -c <exact command>`` 的 exact process command，之后完全复用
sandbox_exec 既有基础设施：``prepare_process`` admission、
``build_sandbox_policy``（所有 mode 固定 network OFF；danger-full-access
仅移除 filesystem 限制）与 ``NativeSandboxExecutor``。
approval/lease 治理由既有 ISOLATED_SANDBOX 语义承担；本模块不做
composition 接线。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent.process.contracts import ResourceProfile, ResourceProfileV1
from agent.process.preparation import prepare_process
from agent.runtime.contracts import (
    ApprovalPolicy,
    EgressClass,
    ExecutionAuthorityClass,
    KnownNotExecuted,
    OutputPolicy,
    SideEffectClass,
    ToolRisk,
    ToolSpec,
)
from agent.sandbox.contracts import SandboxMode, SandboxNetworkMode
from agent.sandbox.executor import NativeSandboxExecutor
from agent.sandbox.policy import build_sandbox_policy
from agent.tools.path_safety import WorkspaceBoundary

SHELL_TOOL_NAME = "shell_exec"
SHELL_TOOL_VERSION = "governed-shell-v1"
SHELL_PATH = "/bin/sh"
SHELL_TRUST_NOTICE_ID = "governed_shell_v1"
# 最小公开合同：command/mode/timeout_seconds；cwd 固定 workspace root，
# profile 由 timeout 档位派生，不暴露任何其他执行参数。
_SHELL_ARGUMENT_KEYS = frozenset({"command", "mode", "timeout_seconds"})
SHELL_TIMEOUT_MIN_SECONDS = 10
SHELL_TIMEOUT_MAX_SECONDS = 900
SHELL_DEFAULT_TIMEOUT_SECONDS = 120
SHELL_TRUST_NOTICE = (
    "Runs one exact command string via /bin/sh -c under macOS Seatbelt with "
    "network denied (deny network*) in every mode, including "
    "danger-full-access, which adds no filesystem isolation. network off "
    "applies only to this command and its ordinary Seatbelt-governed "
    "subprocesses; it does not disconnect the machine and does not block "
    "already-open file descriptors, system services, external applications, "
    "writable files, or other indirect channels outside this policy. Shell "
    "syntax (&&, pipes, redirection, expansion) is not parsed or filtered; "
    "only the literal command string is approved. No TTY, no stdin, closed "
    "environment, one-shot approval only."
)
_TRUST_NOTICE_DIGEST = hashlib.sha256(SHELL_TRUST_NOTICE.encode()).hexdigest()
# command 与转译后 argv item 共用同一 closed byte cap（16 KiB）。
_COMMAND_MAX_BYTES = (
    ResourceProfileV1.for_profile(ResourceProfile.STANDARD).argv_item_max_bytes
)


def shell_exec_tool_spec() -> ToolSpec:
    """governed shell tool 的 closed 静态合同；不暴露 network 参数。"""

    return ToolSpec(
        name=SHELL_TOOL_NAME,
        version=SHELL_TOOL_VERSION,
        description=(
            "Run one exact shell command string via /bin/sh -c under a native "
            "Seatbelt policy with network off in every mode. danger-full-access "
            "adds no filesystem isolation; network stays off. Defaults are "
            "workspace-write mode and a 120 second timeout (10..900)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "mode": {
                    "type": "string",
                    "enum": [
                        "read-only", "workspace-write", "danger-full-access",
                    ],
                },
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": SHELL_TIMEOUT_MIN_SECONDS,
                    "maximum": SHELL_TIMEOUT_MAX_SECONDS,
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.EXTERNAL,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={
            "kind": "shell_exec",
            "shell_path": SHELL_PATH,
            "shell_login": False,
            # 网络语义固定：所有 mode（含 danger-full-access）都 network off。
            "network": SandboxNetworkMode.OFF.value,
            "closed_modes": [mode.value for mode in SandboxMode],
            "timeout_bounds": [
                SHELL_TIMEOUT_MIN_SECONDS,
                SHELL_TIMEOUT_MAX_SECONDS,
            ],
            "command_parsing": False,
        },
        output_limit_chars=64_000,
        egress=EgressClass.GOVERNED_NETWORK,
        execution_authority=ExecutionAuthorityClass.ISOLATED_SANDBOX,
    )


def _parse_shell_arguments(arguments: dict) -> tuple[str, SandboxMode, int]:
    """closed 参数解析：公开合同只有 command/mode/timeout_seconds。"""

    unknown = set(arguments) - _SHELL_ARGUMENT_KEYS
    if unknown:
        raise ValueError(
            f"shell arguments must be closed; unknown keys: {sorted(unknown)}"
        )
    command = arguments.get("command")
    if not isinstance(command, str) or "\x00" in command:
        raise ValueError("command must be a NUL-free string")
    if not command.strip():
        raise ValueError("command must not be empty or whitespace-only")
    if len(command.encode("utf-8")) > _COMMAND_MAX_BYTES:
        raise ValueError(f"command exceeds byte limit: > {_COMMAND_MAX_BYTES} bytes")
    try:
        mode = SandboxMode(arguments.get("mode", SandboxMode.WORKSPACE_WRITE.value))
    except (TypeError, ValueError) as error:
        raise ValueError("mode must be a closed sandbox mode") from error
    timeout = arguments.get("timeout_seconds", SHELL_DEFAULT_TIMEOUT_SECONDS)
    # bool 是 int 子类：必须先拒绝 bool 再验 int/范围。
    if isinstance(timeout, bool) or not isinstance(timeout, int):
        raise ValueError(
            f"timeout_seconds must be an int in "
            f"{SHELL_TIMEOUT_MIN_SECONDS}..{SHELL_TIMEOUT_MAX_SECONDS}"
        )
    if not SHELL_TIMEOUT_MIN_SECONDS <= timeout <= SHELL_TIMEOUT_MAX_SECONDS:
        raise ValueError(
            f"timeout_seconds must be within "
            f"{SHELL_TIMEOUT_MIN_SECONDS}..{SHELL_TIMEOUT_MAX_SECONDS}"
        )
    return command, mode, timeout


def _render_preview(command: str, prepared_command, policy, timeout_seconds: int) -> str:  # noqa: ANN001
    # command 用 JSON quoting 展示 exact 字符串，避免 shell 元字符误导 preview。
    rendered = (
        f"{SHELL_PATH} -c {json.dumps(command, ensure_ascii=False)} "
        f"(cwd={prepared_command.cwd}, profile={prepared_command.profile.value}, "
        f"mode={policy.mode.value}, network={policy.network.value}, "
        f"timeout={timeout_seconds}s)"
    )
    danger = (
        " danger-full-access adds NO filesystem isolation; network stays off."
        if policy.mode is SandboxMode.DANGER_FULL_ACCESS
        else ""
    )
    return f"{rendered}.{danger} {SHELL_TRUST_NOTICE}"


def build_shell_exec_registration(
    *,
    workspace,
    temp_root,
    state_root,
    home,
    captured_path: str,
    confiner,
    private_roots: tuple = (),
    runner=None,
):  # noqa: ANN001, ANN202
    """构造 governed shell registration；不持有 Runtime state/checkpoint。"""

    from agent.runtime.tools import RegisteredTool

    roots = {
        "workspace": Path(workspace).absolute(),
        "temp_root": Path(temp_root).absolute(),
        "state_root": Path(state_root).absolute(),
        "home": Path(home).absolute(),
    }
    boundary = WorkspaceBoundary(roots["workspace"])
    executor = NativeSandboxExecutor(
        confiner=confiner, captured_path=str(captured_path), runner=runner,
    )

    def _admit(arguments: dict):  # noqa: ANN202
        command, mode, timeout = _parse_shell_arguments(arguments)
        # timeout 选最小足够 closed 档位；wall deadline 由 execute 精确覆盖。
        resource = ResourceProfileV1.for_timeout(timeout)
        prepared = prepare_process(
            # 固定转译：不解析 command，argv 恰为 ["-c", exact command]；
            # cwd 固定 workspace root（"."），profile 由 timeout 档位派生。
            {"executable": SHELL_PATH, "argv": ["-c", command],
             "cwd": ".", "profile": resource.profile.value},
            workspace=roots["workspace"],
            captured_path=str(captured_path),
            boundary=boundary,
        )
        if isinstance(prepared, KnownNotExecuted):
            return prepared
        # 网络语义固定：所有 mode（含 danger-full-access）都 network off；
        # danger 只移除 filesystem 隔离（network-only Seatbelt profile）。
        policy = build_sandbox_policy(
            mode=mode,
            network=SandboxNetworkMode.OFF,
            workspace=roots["workspace"],
            temp_root=roots["temp_root"],
            state_root=roots["state_root"],
            home=roots["home"],
            private_roots=private_roots,
        )
        return command, prepared, policy, timeout, resource

    def prepare_binding(arguments: dict) -> dict:
        admitted = _admit(arguments)
        if isinstance(admitted, KnownNotExecuted):
            raise ValueError(f"shell preparation not admitted: {admitted.code}")
        command, prepared, policy, timeout, _resource = admitted
        return {
            # command_fingerprint 绑定 shell path+executable identity、exact
            # command（argv）、cwd descriptor、timeout 档位 profile 与 env
            # policy digest；exact timeout 另行入 binding/preview。
            "command_fingerprint": prepared.command.command_fingerprint,
            "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
            "policy_digest": policy.policy_digest,
            "sandbox_mode": policy.mode.value,
            "sandbox_network": policy.network.value,
            "timeout_seconds": timeout,
            "effect_preview": _render_preview(
                command, prepared.command, policy, timeout,
            ),
            "trust_notice_id": SHELL_TRUST_NOTICE_ID,
            "trust_notice_digest": _TRUST_NOTICE_DIGEST,
        }

    def execute(intent):  # noqa: ANN001, ANN202
        admitted = _admit(intent.arguments)
        if isinstance(admitted, KnownNotExecuted):
            return admitted
        command, prepared, policy, timeout, resource = admitted
        binding = intent.safety_binding
        if (
            prepared.command.command_fingerprint != binding.get("command_fingerprint")
            or hashlib.sha256(command.encode("utf-8")).hexdigest()
            != binding.get("command_sha256")
            or policy.policy_digest != binding.get("policy_digest")
            or timeout != binding.get("timeout_seconds")
        ):
            return KnownNotExecuted(
                code="shell_command_or_policy_changed",
                message="shell command or policy changed after approval",
            )
        # 同一次 executor→runner 调用携带 exact timeout override：wall
        # deadline 精确等于批准值。
        return executor.execute(prepared, policy, resource_override=resource)

    return RegisteredTool(
        spec=shell_exec_tool_spec(),
        func=execute,
        prepare_binding=prepare_binding,
    )
