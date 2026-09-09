"""017 NativeSandboxExecutor：prepared process → confined invocation → runner。

本模块不拥有 timeout/输出 cap/进程组清理（那是 ``agent.process`` 既有
owner 的职责，spec §7）；它只做三件事：spawn 前 revalidate、经 confiner
包装 exact command、把 wrapped invocation 交给 ``run_local_process`` 并
映射为 ``SandboxExecutionDraftV1``。per-invocation temp 环境用后即删。
"""

from __future__ import annotations

import hashlib
import tempfile
from contextlib import suppress

from agent.process.contracts import SAFE_LOCALE, ResourceProfileV1
from agent.process.preparation import (
    closed_process_environment,
    revalidate_process,
)
from agent.process.runner import run_local_process
from agent.runtime.contracts import KnownNotExecuted
from agent.sandbox.contracts import (
    SandboxDraftOutcome,
    SandboxExecutionDraftV1,
    SandboxMode,
    SandboxNetworkMode,
    SandboxPolicyV1,
    StructuredReadbackOutcome,
    StructuredSandboxIoPlanV1,
    StructuredSandboxProcessDraftV1,
    structured_invocation_digest,
)
from agent.sandbox.structured_session import (
    create_structured_session,
    read_structured_session,
)


def _safe_rmtree(path: str) -> None:
    import shutil
    from contextlib import suppress

    with suppress(OSError):
        shutil.rmtree(path, ignore_errors=True)


def _facts_mismatch() -> KnownNotExecuted:
    return KnownNotExecuted(
        code="enforcement_facts_mismatch",
        message="confined invocation facts do not bind the policy",
    )


def _verified_invocation(
    invocation,
    policy: SandboxPolicyV1,
    command,
    expected_environment: dict[str, str],
):  # noqa: ANN001
    """runner 前的 enforcement truth 校验（普通/structured path 复用）。

    - facts 必须精确绑定当前 policy（digest/mode/network）；
    - 仅 danger+full 可为 none/unconfined；其余一律 seatbelt/confined，
      且 facts.profile_digest 必须等于 runner ``-p`` 将使用的 profile；
    - wrapped argv 必须仍是批准的 exact command，environment 不得被
      confiner 扩展。伪造或复用旧 invocation 都在 runner 前拒绝。
    """

    facts = invocation.enforcement
    if (
        facts.policy_digest != policy.policy_digest
        or facts.mode is not policy.mode
        or facts.network is not policy.network
    ):
        return _facts_mismatch()
    unconfined_expected = (
        policy.mode is SandboxMode.DANGER_FULL_ACCESS
        and policy.network is SandboxNetworkMode.FULL
    )
    if unconfined_expected != (facts.backend == "none"):
        return _facts_mismatch()
    resolved = command.executable_identity.resolved_path
    exact_command = (resolved, *command.argv)
    if dict(invocation.environment) != expected_environment:
        return _facts_mismatch()
    if unconfined_expected:
        if (
            invocation.wrapped_executable != resolved
            or invocation.wrapped_argv != exact_command
        ):
            return _facts_mismatch()
    else:
        if invocation.profile is None:
            return _facts_mismatch()
        wrapped = (
            invocation.wrapped_executable,
            "-p",
            invocation.profile,
            *exact_command,
        )
        if invocation.wrapped_argv != wrapped or hashlib.sha256(
            invocation.profile.encode()
        ).hexdigest() != facts.profile_digest:
            return _facts_mismatch()
    return None


class NativeSandboxExecutor:
    def __init__(
        self,
        *,
        confiner,
        runner=None,
    ) -> None:  # noqa: ANN001
        self._confiner = confiner
        self._runner = runner or run_local_process

    def execute(
        self,
        prepared,
        policy: SandboxPolicyV1,
        io_plan: StructuredSandboxIoPlanV1 | None = None,
        resource_override: ResourceProfileV1 | None = None,
    ):  # noqa: ANN001, ANN202
        current = revalidate_process(prepared)
        if isinstance(current, KnownNotExecuted):
            return current
        if io_plan is not None:
            return self._execute_structured(current, policy, io_plan)
        # policy 绑定已批准的 canonical temp parent；每次执行只在该 parent
        # 下创建 ephemeral HOME/TMPDIR，避免 profile 与真实写入根漂移。
        temp_root = tempfile.mkdtemp(prefix="fa-sbx-", dir=policy.temp_root)
        try:
            expected_environment = closed_process_environment(
                temp_root, prepared.child_path
            )
            invocation = self._confiner.confine(
                current.command, policy, dict(expected_environment),
            )
            if isinstance(invocation, KnownNotExecuted):
                return invocation
            # enforcement facts 必须精确绑定当前 policy 与 profile 字节（防
            # confine/结果被篡改或复用旧 invocation）
            mismatch = _verified_invocation(
                invocation, policy, current.command, expected_environment,
            )
            if mismatch is not None:
                return mismatch
            process = self._runner(
                resolved_executable=invocation.wrapped_executable,
                # ``run_local_process`` 自行把 resolved executable 放入 argv[0]；
                # confiner 的 wrapped_argv 是可审计的完整命令，交界处去掉首项。
                argv=invocation.wrapped_argv[1:],
                cwd=current.cwd_path,
                # 内部显式 override（如 shell_exec 的 exact timeout 档位）；
                # 默认仍用 prepared command 自带的 profile。
                profile=(
                    resource_override
                    or ResourceProfileV1.for_profile(current.command.profile)
                ),
                environment=dict(invocation.environment),
            )
            return SandboxExecutionDraftV1.from_process(
                process=process,
                original_command_fingerprint=current.command.command_fingerprint,
                enforcement=invocation.enforcement,
            )
        finally:
            _safe_rmtree(temp_root)

    def _execute_structured(
        self,
        current,
        policy: SandboxPolicyV1,
        io_plan: StructuredSandboxIoPlanV1,
    ):  # noqa: ANN001, ANN202
        """在同一个已重验 invocation 内完成固定文件 session 与 readback。"""

        try:
            session = create_structured_session(policy.temp_root, io_plan)
        except (OSError, ValueError) as error:
            return KnownNotExecuted(
                code="structured_session_setup_failed",
                message=f"structured session setup failed: {error}",
            )
        result = None
        try:
            expected_environment = {
                "HOME": session.root,
                "TMPDIR": session.root,
                "PATH": "",
                "LANG": SAFE_LOCALE,
                "LC_CTYPE": SAFE_LOCALE,
                "TZ": "UTC",
            }
            try:
                invocation = self._confiner.confine(
                    current.command, policy, dict(expected_environment)
                )
            except Exception as error:
                session.close_and_remove()
                return KnownNotExecuted(
                    code="structured_confine_failed",
                    message=f"structured sandbox confine failed: {error}",
                )
            if isinstance(invocation, KnownNotExecuted):
                session.close_and_remove()
                return invocation
            mismatch = _verified_invocation(
                invocation, policy, current.command, expected_environment,
            )
            if mismatch is not None:
                session.close_and_remove()
                return mismatch
            process = self._runner(
                resolved_executable=invocation.wrapped_executable,
                argv=invocation.wrapped_argv[1:],
                cwd=current.cwd_path,
                profile=ResourceProfileV1.for_profile(current.command.profile),
                environment=dict(invocation.environment),
            )
            sandbox_process = SandboxExecutionDraftV1.from_process(
                process=process,
                original_command_fingerprint=current.command.command_fingerprint,
                enforcement=invocation.enforcement,
            )
            outer_digest = structured_invocation_digest(current, policy, io_plan)
            if sandbox_process.outcome is SandboxDraftOutcome.SPAWN_FAILED:
                readback_outcome = StructuredReadbackOutcome.NOT_READ
                result_bytes = b""
                artifact_bytes = None
            else:
                readback = read_structured_session(session, io_plan)
                readback_outcome = readback.outcome
                result_bytes = readback.result_bytes
                artifact_bytes = readback.artifact_bytes
            result = StructuredSandboxProcessDraftV1(
                process=sandbox_process,
                structured_invocation_digest=outer_digest,
                readback_outcome=readback_outcome,
                request_digest=io_plan.request_digest,
                input_digests=tuple(
                    sorted(
                        (item.slot, len(item.content), item.content_digest)
                        for item in io_plan.inputs
                    )
                ),
                result_bytes=result_bytes,
                result_digest=hashlib.sha256(result_bytes).hexdigest(),
                artifact_bytes=artifact_bytes,
                artifact_digest=(
                    hashlib.sha256(artifact_bytes).hexdigest()
                    if artifact_bytes is not None
                    else None
                ),
            )
        except BaseException:
            # runner 抛出时 spawn 是否已发生未知；保留原异常让 Runtime 进入 recovery。
            with suppress(Exception):
                session.close_and_remove()
            raise
        session.close_and_remove()
        return result
