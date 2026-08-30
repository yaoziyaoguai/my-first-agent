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


class NativeSandboxExecutor:
    def __init__(
        self,
        *,
        confiner,
        captured_path: str,
        runner=None,
    ) -> None:  # noqa: ANN001
        self._confiner = confiner
        self._captured_path = captured_path
        self._runner = runner or run_local_process

    def execute(
        self,
        prepared,
        policy: SandboxPolicyV1,
        io_plan: StructuredSandboxIoPlanV1 | None = None,
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
            environment = closed_process_environment(
                temp_root, self._captured_path,
            )
            invocation = self._confiner.confine(
                current.command, policy, environment,
            )
            if isinstance(invocation, KnownNotExecuted):
                return invocation
            # enforcement facts 必须精确绑定当前 policy（防 confine/结果被篡改
            # 或复用旧 invocation）
            if (
                invocation.enforcement.policy_digest != policy.policy_digest
                or invocation.enforcement.mode is not policy.mode
                or invocation.enforcement.network is not policy.network
            ):
                return KnownNotExecuted(
                    code="enforcement_facts_mismatch",
                    message="confined invocation facts do not bind the policy",
                )
            process = self._runner(
                resolved_executable=invocation.wrapped_executable,
                # ``run_local_process`` 自行把 resolved executable 放入 argv[0]；
                # confiner 的 wrapped_argv 是可审计的完整命令，交界处去掉首项。
                argv=invocation.wrapped_argv[1:],
                cwd=current.cwd_path,
                profile=ResourceProfileV1.for_profile(current.command.profile),
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
            environment = {
                "HOME": session.root,
                "TMPDIR": session.root,
                "PATH": "",
                "LANG": SAFE_LOCALE,
                "LC_CTYPE": SAFE_LOCALE,
                "TZ": "UTC",
            }
            try:
                invocation = self._confiner.confine(
                    current.command, policy, environment
                )
            except (OSError, ValueError) as error:
                session.close_and_remove()
                return KnownNotExecuted(
                    code="structured_confine_failed",
                    message=f"structured sandbox confine failed: {error}",
                )
            if isinstance(invocation, KnownNotExecuted):
                result = invocation
            elif (
                invocation.enforcement.policy_digest != policy.policy_digest
                or invocation.enforcement.mode is not policy.mode
                or invocation.enforcement.network is not policy.network
            ):
                result = KnownNotExecuted(
                    code="enforcement_facts_mismatch",
                    message="confined invocation facts do not bind the policy",
                )
            else:
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
