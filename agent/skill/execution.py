"""声明式 Skill entrypoint 到既有 structured sandbox 的窄适配。"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from agent.process.preparation import PreparedProcessV1
from agent.runtime.contracts import KnownNotExecuted, canonical_json_digest
from agent.sandbox.contracts import (
    PackagedSkillResourceLimitsV1,
    PackagedSkillSandboxPolicyV1,
    StructuredResultKind,
    StructuredSandboxIoPlanV1,
    structured_invocation_digest,
)
from agent.sandbox.executor import NativeSandboxExecutor
from agent.sandbox.hermetic_runtime import (
    TrustedApplicationRuntime,
    prepare_trusted_skill_process,
)
from agent.sandbox.packaged_policy import build_packaged_skill_policy
from agent.skill.catalog import (
    SkillCatalog,
    SkillCatalogError,
    SkillDescriptor,
    SkillEntrypointDescriptor,
)

SKILL_EXECUTION_TRUST_NOTICE_ID = "governed_skill_entrypoint_v1"
SKILL_EXECUTION_TRUST_NOTICE = (
    "Runs one declared Python entrypoint in the read-only packaged Skill sandbox. "
    "The fixed runner has no network, shell, workspace access, or ambient credentials."
)
_TRUST_NOTICE_DIGEST = hashlib.sha256(
    SKILL_EXECUTION_TRUST_NOTICE.encode("utf-8")
).hexdigest()
_RESULT_CAP_BYTES = 64 * 1024
_ARTIFACT_CAP_BYTES = 1


@dataclass(frozen=True, slots=True)
class SkillExecutionConfig:
    """composition root 注入的单一执行配置；不拥有 Skill 生命周期。"""

    runtime: TrustedApplicationRuntime
    workspace_root: Path
    temp_root: Path
    state_root: Path
    home_root: Path
    system_runtime_roots: tuple[Path, ...]
    system_runtime_digest: str
    private_roots: tuple[Path, ...]
    executor: NativeSandboxExecutor


@dataclass(frozen=True, slots=True)
class PreparedSkillExecution:
    prepared: PreparedProcessV1
    policy: PackagedSkillSandboxPolicyV1
    io_plan: StructuredSandboxIoPlanV1
    binding: dict


@dataclass(frozen=True, slots=True)
class PreparedSkillBase:
    """registration 时冻结的 process/policy；每次调用只追加 bounded request。"""

    prepared: PreparedProcessV1
    policy: PackagedSkillSandboxPolicyV1


def skill_resource_limits() -> PackagedSkillResourceLimitsV1:
    """按平台选择 closed limits profile；darwin 只声明可执行的限额。"""

    profile = (
        "skill-standard-darwin-v1" if sys.platform == "darwin" else "skill-standard-v1"
    )
    return PackagedSkillResourceLimitsV1.for_profile(profile)


def prepare_skill_base(
    catalog: SkillCatalog,
    descriptor: SkillDescriptor,
    entrypoint: SkillEntrypointDescriptor,
    config: SkillExecutionConfig,
) -> PreparedSkillBase:
    """重验 Skill identity，并冻结固定 runner 与 sandbox policy。"""

    package_root, current = catalog.resolve_entrypoint_target(
        descriptor.name, entrypoint.id
    )
    if current != entrypoint:
        raise ValueError("skill entrypoint identity changed")
    limits = skill_resource_limits()
    prepared = prepare_trusted_skill_process(
        config.runtime,
        package_root=package_root,
        package_digest=descriptor.identity_digest,
        entrypoint_id=entrypoint.id,
    )
    if isinstance(prepared, KnownNotExecuted):
        raise ValueError("skill process could not be prepared")
    policy = build_packaged_skill_policy(
        interpreter_path=config.runtime.interpreter_path,
        runtime_roots=config.runtime.readable_roots,
        package_root=package_root,
        temp_root=config.temp_root,
        system_runtime_roots=config.system_runtime_roots,
        workspace_root=config.workspace_root,
        home_root=config.home_root,
        state_root=config.state_root,
        private_roots=config.private_roots,
        runtime_closure_digest=config.runtime.identity_digest,
        system_runtime_digest=config.system_runtime_digest,
        resource_limits=limits,
        package_read_paths=(entrypoint.relative_path,),
    )
    return PreparedSkillBase(prepared=prepared, policy=policy)


def bind_skill_execution(
    base: PreparedSkillBase,
    descriptor: SkillDescriptor,
    entrypoint: SkillEntrypointDescriptor,
    arguments: dict,
) -> PreparedSkillExecution:
    """把一次 JSON arguments 绑定到已冻结的 Skill process/policy。"""

    limits = base.policy.resource_limits
    request = {
        "protocol": "first-agent-skill-request-v1",
        "package_digest": descriptor.identity_digest,
        "entrypoint_id": entrypoint.id,
        "entrypoint_script": {
            "path": entrypoint.relative_path,
            "size": entrypoint.size,
            "sha256": entrypoint.digest,
        },
        "arguments": arguments,
        "inputs": [],
        "expected_result_kind": StructuredResultKind.OBSERVATION.value,
        "resource_limits_digest": limits.limits_digest,
    }
    request_bytes = json.dumps(
        request,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    request_digest = hashlib.sha256(request_bytes).hexdigest()
    entrypoint_digest = canonical_json_digest(
        {
            "id": entrypoint.id,
            "path": entrypoint.relative_path,
            "size": entrypoint.size,
            "sha256": entrypoint.digest,
        }
    )
    io_plan = StructuredSandboxIoPlanV1(
        package_digest=descriptor.identity_digest,
        entrypoint_id=entrypoint.id,
        entrypoint_digest=entrypoint_digest,
        request_bytes=request_bytes,
        request_digest=request_digest,
        inputs=(),
        result_cap_bytes=_RESULT_CAP_BYTES,
        artifact_cap_bytes=_ARTIFACT_CAP_BYTES,
        aggregate_output_cap_bytes=_RESULT_CAP_BYTES + _ARTIFACT_CAP_BYTES,
        expected_result_kind=StructuredResultKind.OBSERVATION,
    )
    outer_digest = structured_invocation_digest(base.prepared, base.policy, io_plan)
    binding = {
        "command_fingerprint": base.prepared.command.command_fingerprint,
        "policy_digest": base.policy.policy_digest,
        "sandbox_mode": base.policy.mode.value,
        "sandbox_network": base.policy.network.value,
        "effect_preview": (
            f"Run Skill '{descriptor.name}' entrypoint '{entrypoint.id}' in a "
            "read-only sandbox with network off."
        ),
        "trust_notice_id": SKILL_EXECUTION_TRUST_NOTICE_ID,
        "trust_notice_digest": _TRUST_NOTICE_DIGEST,
        "skill_identity": descriptor.identity_digest,
        "entrypoint_digest": entrypoint_digest,
        "arguments_digest": canonical_json_digest(arguments),
        "request_digest": request_digest,
        "resource_limits_digest": limits.limits_digest,
        "structured_invocation_digest": outer_digest,
    }
    return PreparedSkillExecution(base.prepared, base.policy, io_plan, binding)


def prepare_skill_execution(
    catalog: SkillCatalog,
    descriptor: SkillDescriptor,
    entrypoint: SkillEntrypointDescriptor,
    arguments: dict,
    config: SkillExecutionConfig,
) -> PreparedSkillExecution:
    """执行前重验 package，再重建与 approval 全等的 invocation。"""

    base = prepare_skill_base(catalog, descriptor, entrypoint, config)
    return bind_skill_execution(base, descriptor, entrypoint, arguments)


def execute_skill_entrypoint(
    *,
    catalog: SkillCatalog,
    descriptor: SkillDescriptor,
    entrypoint: SkillEntrypointDescriptor,
    config: SkillExecutionConfig,
    intent,
):  # noqa: ANN001, ANN202
    """spawn 前再次重验完整 binding；catalog drift 时不调用 executor。"""

    try:
        execution = prepare_skill_execution(
            catalog,
            descriptor,
            entrypoint,
            intent.arguments["arguments"],
            config,
        )
    except SkillCatalogError:
        return KnownNotExecuted(
            code="skill_entrypoint_drift",
            message="skill entrypoint drifted; rebuild the catalog",
        )
    except (KeyError, TypeError, ValueError, OSError):
        return KnownNotExecuted(
            code="skill_execution_unavailable",
            message="skill entrypoint execution is unavailable",
        )
    if execution.binding != intent.safety_binding:
        return KnownNotExecuted(
            code="skill_execution_binding_changed",
            message="skill execution binding changed after approval",
        )
    return config.executor.execute(
        execution.prepared,
        execution.policy,
        io_plan=execution.io_plan,
    )
