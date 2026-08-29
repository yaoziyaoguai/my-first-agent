"""017 NativeSandboxExecutor：prepared process → confined invocation → runner。

本模块不拥有 timeout/输出 cap/进程组清理（那是 ``agent.process`` 既有
owner 的职责，spec §7）；它只做三件事：spawn 前 revalidate、经 confiner
包装 exact command、把 wrapped invocation 交给 ``run_local_process`` 并
映射为 ``SandboxExecutionDraftV1``。per-invocation temp 环境用后即删。
"""

from __future__ import annotations

import tempfile

from agent.process.contracts import ResourceProfileV1
from agent.process.preparation import (
    closed_process_environment,
    revalidate_process,
)
from agent.process.runner import run_local_process
from agent.runtime.contracts import KnownNotExecuted
from agent.sandbox.contracts import (
    SandboxExecutionDraftV1,
    SandboxPolicyV1,
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

    def execute(self, prepared, policy: SandboxPolicyV1):  # noqa: ANN001, ANN202
        current = revalidate_process(prepared)
        if isinstance(current, KnownNotExecuted):
            return current
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
