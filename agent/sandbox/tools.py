"""017 单一 native ``sandbox_exec`` governed tool registration。"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

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

SANDBOX_TOOL_NAME = "sandbox_exec"
SANDBOX_TOOL_VERSION = "native-sandbox-v1"
SANDBOX_TRUST_NOTICE_ID = "native_sandbox_v1"
SANDBOX_TRUST_NOTICE = (
    "Confined modes use macOS Seatbelt and do not provide a host shell interface. "
    "danger-full-access is an unconfined exact-command bypass. Every mode is "
    "shell-free, foreground-only, and requires exact one-shot approval; there is "
    "no TTY, background process, sudo, or implicit credential access."
)
_TRUST_NOTICE_DIGEST = hashlib.sha256(SANDBOX_TRUST_NOTICE.encode()).hexdigest()


def sandbox_exec_tool_spec() -> ToolSpec:
    """唯一产品 sandbox tool 的 closed 静态合同。"""

    return ToolSpec(
        name=SANDBOX_TOOL_NAME,
        version=SANDBOX_TOOL_VERSION,
        description=(
            "Run one structured, shell-free foreground command under the selected "
            "native sandbox policy. Defaults are workspace-write and network off."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "executable": {"type": "string"},
                "argv": {"type": "array", "items": {"type": "string"}},
                "cwd": {"type": "string"},
                "profile": {
                    "type": "string",
                    "enum": ["short", "standard", "long"],
                },
                "mode": {
                    "type": "string",
                    "enum": [
                        "read-only",
                        "workspace-write",
                        "danger-full-access",
                    ],
                },
                "network": {"type": "string", "enum": ["off", "full"]},
            },
            "required": ["executable"],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.EXTERNAL,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={
            "kind": "sandbox_exec",
            "shell": False,
            "background": False,
            "closed_modes": [
                "read-only",
                "workspace-write",
                "danger-full-access",
            ],
            "closed_network": ["off", "full"],
        },
        output_limit_chars=64_000,
        egress=EgressClass.GOVERNED_NETWORK,
        execution_authority=ExecutionAuthorityClass.ISOLATED_SANDBOX,
    )


def _closed_policy(arguments: dict, *, roots: dict, private_roots: tuple):
    mode_raw = arguments.get("mode", SandboxMode.WORKSPACE_WRITE.value)
    network_raw = arguments.get("network", SandboxNetworkMode.OFF.value)
    try:
        mode = SandboxMode(mode_raw)
        network = SandboxNetworkMode(network_raw)
    except (TypeError, ValueError) as error:
        raise ValueError("sandbox mode/network must be closed values") from error
    return build_sandbox_policy(
        mode=mode,
        network=network,
        workspace=roots["workspace"],
        temp_root=roots["temp_root"],
        state_root=roots["state_root"],
        home=roots["home"],
        private_roots=private_roots,
    )


def _render_preview(command, policy) -> str:  # noqa: ANN001
    argv = " ".join(command.argv)
    rendered = command.executable_token + (f" {argv}" if argv else "")
    return (
        f"{rendered} (cwd={command.cwd}, profile={command.profile.value}, "
        f"mode={policy.mode.value}, network={policy.network.value}). "
        f"{SANDBOX_TRUST_NOTICE}"
    )


def build_sandbox_exec_registration(
    *,
    workspace,
    temp_root,
    state_root,
    home,
    captured_path: str,
    confiner,
    private_roots: tuple = (),
    runner=None,
    policy_builder=None,
    authority_policy_digest: str | None = None,
):  # noqa: ANN001, ANN202
    """构造单一 native registration；不持有 Runtime state/checkpoint。"""

    from agent.runtime.tools import RegisteredTool

    roots = {
        "workspace": Path(workspace).absolute(),
        "temp_root": Path(temp_root).absolute(),
        "state_root": Path(state_root).absolute(),
        "home": Path(home).absolute(),
    }
    boundary = WorkspaceBoundary(roots["workspace"])
    executor = NativeSandboxExecutor(
        confiner=confiner,
        captured_path=str(captured_path),
        runner=runner,
    )
    resolved_policy_builder = policy_builder or (
        lambda arguments, bound_roots, bound_private_roots: _closed_policy(
            arguments,
            roots=bound_roots,
            private_roots=bound_private_roots,
        )
    )
    if authority_policy_digest is not None and not re.fullmatch(
        r"[0-9a-f]{64}", authority_policy_digest
    ):
        raise ValueError("authority_policy_digest must be bare hex64")

    def prepare_binding(arguments: dict) -> dict:
        prepared = prepare_process(
            arguments,
            workspace=roots["workspace"],
            captured_path=str(captured_path),
            boundary=boundary,
        )
        if isinstance(prepared, KnownNotExecuted):
            raise ValueError(f"sandbox preparation not admitted: {prepared.code}")
        policy = resolved_policy_builder(arguments, roots, private_roots)
        command = prepared.command
        binding = {
            "command_fingerprint": command.command_fingerprint,
            "policy_digest": authority_policy_digest or policy.policy_digest,
            "sandbox_mode": policy.mode.value,
            "sandbox_network": policy.network.value,
            "effect_preview": _render_preview(command, policy),
            "trust_notice_id": SANDBOX_TRUST_NOTICE_ID,
            "trust_notice_digest": _TRUST_NOTICE_DIGEST,
        }
        if authority_policy_digest is not None:
            binding["policy_instance_digest"] = policy.policy_digest
        return binding

    def execute(intent):  # noqa: ANN001, ANN202
        prepared = prepare_process(
            intent.arguments,
            workspace=roots["workspace"],
            captured_path=str(captured_path),
            boundary=boundary,
        )
        if isinstance(prepared, KnownNotExecuted):
            return prepared
        policy = resolved_policy_builder(intent.arguments, roots, private_roots)
        if (
            prepared.command.command_fingerprint
            != intent.safety_binding.get("command_fingerprint")
            or (authority_policy_digest or policy.policy_digest)
            != intent.safety_binding.get("policy_digest")
            or (
                authority_policy_digest is not None
                and policy.policy_digest
                != intent.safety_binding.get("policy_instance_digest")
            )
        ):
            return KnownNotExecuted(
                code="sandbox_policy_or_command_changed",
                message="sandbox command or policy changed after approval",
            )
        return executor.execute(prepared, policy)

    return RegisteredTool(
        spec=sandbox_exec_tool_spec(),
        func=execute,
        prepare_binding=prepare_binding,
    )
