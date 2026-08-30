"""``SeatbeltConfiner``：macOS Seatbelt 的 ``SandboxConfiner`` 实现。

qualify = 一次 bounded 只读 functional probe（缓存于实例）；confine = pure
wrapping（绝不 spawn）——把 exact command 编译为 ``sandbox-exec -p <profile>
<command>`` 并返回 enforcement facts。danger-full-access 是 unconfined
bypass，不探测 backend（spec §2–§4）。
"""

from __future__ import annotations

import hashlib
import platform as platform_module
from collections.abc import Callable, Mapping
from pathlib import Path

from agent.process.contracts import ProcessCommandV1
from agent.runtime.contracts import KnownNotExecuted, canonical_json_digest
from agent.sandbox.contracts import (
    ConfinedInvocationV1,
    PackagedSkillSandboxPolicyV1,
    SandboxBackendIdentityV1,
    SandboxEnforcementFactsV1,
    SandboxMode,
    SandboxPolicyV1,
    SandboxQualificationV1,
)
from agent.sandbox.packaged_policy import (
    compile_packaged_skill_profile,
    validate_packaged_skill_policy,
)
from agent.sandbox.policy import compile_seatbelt_profile
from agent.sandbox.qualification import (
    MINIMAL_PROBE_PROFILE,
    PROBE_OUTPUT_CAP_BYTES,
    PROBE_TARGET,
    PROBE_TIMEOUT_SECONDS,
    SeatbeltCommandRunner,
)


class SeatbeltConfiner:
    def __init__(
        self,
        *,
        binary: str = "/usr/bin/sandbox-exec",
        runner: SeatbeltCommandRunner | None = None,
        platform_system: str | None = None,
        platform_release: str | None = None,
        profile_compiler: Callable[[object], str] = compile_seatbelt_profile,
        legacy_policy_type: type = SandboxPolicyV1,
    ) -> None:
        self._binary = binary
        self._runner = runner
        self._platform_system = platform_system or platform_module.system()
        self._platform_release = platform_release or platform_module.release()
        self._profile_compiler = profile_compiler
        self._legacy_policy_type = legacy_policy_type
        self._qualification: SandboxQualificationV1 | None = None

    # ------------------------------------------------------------------ #

    def qualify(self) -> SandboxQualificationV1:
        """只读探测（每实例缓存一次）：platform → binary 存在 → functional
        probe。任何失败都 fail closed，绝不安装/启动/登录/降级。"""

        if self._qualification is not None:
            return self._qualification
        self._qualification = self._qualify_once()
        return self._qualification

    def _qualify_once(self) -> SandboxQualificationV1:
        if self._platform_system != "Darwin":
            return SandboxQualificationV1(False, "unsupported_platform")
        binary_path = Path(self._binary)
        if not binary_path.is_file():
            return SandboxQualificationV1(False, "sandbox_exec_missing")
        runner = self._runner or SeatbeltCommandRunner()
        argv = (self._binary, "-p", MINIMAL_PROBE_PROFILE, PROBE_TARGET)
        result = runner.run(
            argv, cwd=None, env={}, timeout=PROBE_TIMEOUT_SECONDS,
        )
        if (
            result.timed_out
            or result.returncode is None
            or result.returncode < 0
            or len(result.stdout) > PROBE_OUTPUT_CAP_BYTES
            or len(result.stderr) > PROBE_OUTPUT_CAP_BYTES
        ):
            return SandboxQualificationV1(False, "functional_probe_failed")
        if result.returncode != 0:
            return SandboxQualificationV1(False, "seatbelt_profile_refused")
        identity = SandboxBackendIdentityV1(
            executable_path=self._binary,
            platform_system=self._platform_system,
            platform_release=self._platform_release,
            functional_probe_digest=canonical_json_digest(
                {
                    "argv": list(argv),
                    "returncode": result.returncode,
                    "stdout_digest": hashlib.sha256(result.stdout).hexdigest(),
                    "stderr_digest": hashlib.sha256(result.stderr).hexdigest(),
                    "timed_out": result.timed_out,
                },
            ),
            probe_profile_digest=hashlib.sha256(
                MINIMAL_PROBE_PROFILE.encode(),
            ).hexdigest(),
        )
        return SandboxQualificationV1(True, "qualified", backend_identity=identity)

    # ------------------------------------------------------------------ #

    def confine(
        self,
        command: ProcessCommandV1,
        policy: SandboxPolicyV1 | PackagedSkillSandboxPolicyV1,
        environment: Mapping[str, str],
    ) -> ConfinedInvocationV1 | KnownNotExecuted:
        """pure wrapping：confined 编译 profile；danger 直接 bypass。"""

        if type(policy) not in (
            PackagedSkillSandboxPolicyV1,
            self._legacy_policy_type,
        ):
            return KnownNotExecuted(
                code="sandbox_policy_type_unknown",
                message="sandbox policy type is not admitted",
            )
        if type(policy) is PackagedSkillSandboxPolicyV1:
            try:
                validate_packaged_skill_policy(policy)
            except ValueError:
                return KnownNotExecuted(
                    code="sandbox_policy_type_unknown",
                    message="packaged sandbox policy is not admitted",
                )
        if command.executable_identity is None:
            return KnownNotExecuted(
                code="executable_identity_missing",
                message="exact command carries no resolved executable identity",
            )
        resolved = command.executable_identity.resolved_path
        if (
            type(policy) is SandboxPolicyV1
            and policy.mode is SandboxMode.DANGER_FULL_ACCESS
        ):
            # bypass 不依赖 backend qualification（spec §2/§4）
            return ConfinedInvocationV1(
                wrapped_executable=resolved,
                wrapped_argv=(resolved, *command.argv),
                profile=None,
                environment=dict(environment),
                enforcement=SandboxEnforcementFactsV1(
                    backend="none",
                    enforcement="unconfined",
                    mode=policy.mode,
                    network=policy.network,
                    policy_digest=policy.policy_digest,
                ),
            )
        qualification = self.qualify()
        if not qualification.available:
            return KnownNotExecuted(
                code=qualification.reason_code,
                message=(
                    "sandbox backend unavailable; confined command not executed"
                ),
            )
        if type(policy) is PackagedSkillSandboxPolicyV1:
            profile = compile_packaged_skill_profile(policy, environment)
        else:
            profile = self._profile_compiler(policy)
        return ConfinedInvocationV1(
            wrapped_executable=self._binary,
            wrapped_argv=(self._binary, "-p", profile, resolved, *command.argv),
            profile=profile,
            environment=dict(environment),
            enforcement=SandboxEnforcementFactsV1(
                backend="seatbelt",
                enforcement="confined",
                mode=policy.mode,
                network=policy.network,
                policy_digest=policy.policy_digest,
                profile_digest=hashlib.sha256(profile.encode()).hexdigest(),
            ),
        )
