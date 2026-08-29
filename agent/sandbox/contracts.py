"""017 native sandbox contracts（frozen spec §3–§5）。

closed 三值 mode/network、policy identity、backend identity、enforcement
facts 与 confined invocation。本模块不认识 Goal/provider/approval；治理
合同在 ``agent.runtime``。Docker/image/snapshot/bundle 词汇不存在于此。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from agent.runtime.contracts import KnownNotExecuted, canonical_json_digest  # noqa: F401  re-export

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SANDBOX_BACKENDS = frozenset({"seatbelt", "none"})
_SANDBOX_ENFORCEMENTS = frozenset({"confined", "unconfined"})
SANDBOX_QUALIFICATION_REASONS = frozenset(
    {
        "qualified",
        "unsupported_platform",
        "sandbox_exec_missing",
        "seatbelt_profile_refused",
        "functional_probe_failed",
    },
)


class SandboxMode(StrEnum):
    """closed 三值 policy mode（spec §4）。"""

    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    DANGER_FULL_ACCESS = "danger-full-access"


class SandboxNetworkMode(StrEnum):
    """closed 二值 network policy（spec §8，独立于 filesystem seam）。"""

    OFF = "off"
    FULL = "full"


def _require_hex64(value: object, name: str) -> str:
    if not isinstance(value, str) or not _HEX64.match(value):
        raise ValueError(f"{name} must be bare hex64")
    return value


def _string_roots(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{name} must be a tuple of canonical roots")
    for item in value:
        if not isinstance(item, str) or not item.startswith("/"):
            raise ValueError(f"{name} must contain absolute path strings")
    return value


@dataclass(frozen=True, slots=True)
class SandboxPolicyV1:
    """immutable policy identity：digest 绑定全部成员（spec §5）。

    canonical 路径与 overlap 校验的唯一 admission 点是
    ``agent.sandbox.policy.build_sandbox_policy``；本 dataclass 只做类型/
    形状校验与 digest 重算。
    """

    mode: SandboxMode
    network: SandboxNetworkMode
    workspace_root: str
    temp_root: str
    state_root: str
    home_root: str
    writable_roots: tuple[str, ...] = ()
    git_metadata_roots: tuple[str, ...] = ()
    unreadable_roots: tuple[str, ...] = ()
    policy_digest: str = ""

    def identity_values(self) -> dict:
        return {
            "mode": self.mode.value,
            "network": self.network.value,
            "workspace_root": self.workspace_root,
            "temp_root": self.temp_root,
            "state_root": self.state_root,
            "home_root": self.home_root,
            "writable_roots": list(self.writable_roots),
            "git_metadata_roots": list(self.git_metadata_roots),
            "unreadable_roots": list(self.unreadable_roots),
        }

    def __post_init__(self) -> None:
        if not isinstance(self.mode, SandboxMode):
            raise ValueError("mode must be a closed SandboxMode")
        if not isinstance(self.network, SandboxNetworkMode):
            raise ValueError("network must be a closed SandboxNetworkMode")
        for name in ("workspace_root", "temp_root", "state_root", "home_root"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.startswith("/"):
                raise ValueError(f"{name} must be an absolute path string")
        object.__setattr__(
            self, "writable_roots", _string_roots(self.writable_roots, "writable_roots"),
        )
        object.__setattr__(
            self,
            "git_metadata_roots",
            _string_roots(self.git_metadata_roots, "git_metadata_roots"),
        )
        object.__setattr__(
            self,
            "unreadable_roots",
            _string_roots(self.unreadable_roots, "unreadable_roots"),
        )
        digest = canonical_json_digest(self.identity_values())
        if self.policy_digest and self.policy_digest != digest:
            raise ValueError("sandbox policy digest mismatch")
        object.__setattr__(self, "policy_digest", digest)


@dataclass(frozen=True, slots=True)
class SandboxBackendIdentityV1:
    """backend identity = canonical executable path + platform/build facts +
    functional probe result + probe profile digest（spec §12：不承诺版本事实）。"""

    executable_path: str
    platform_system: str
    platform_release: str
    functional_probe_digest: str
    probe_profile_digest: str
    backend_identity_digest: str = ""

    def identity_values(self) -> dict:
        return {
            "executable_path": self.executable_path,
            "platform_system": self.platform_system,
            "platform_release": self.platform_release,
            "functional_probe_digest": self.functional_probe_digest,
            "probe_profile_digest": self.probe_profile_digest,
        }

    def __post_init__(self) -> None:
        for name in (
            "executable_path", "platform_system", "platform_release",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} must be a non-empty string")
        _require_hex64(self.functional_probe_digest, "functional_probe_digest")
        _require_hex64(self.probe_profile_digest, "probe_profile_digest")
        digest = canonical_json_digest(self.identity_values())
        if self.backend_identity_digest and self.backend_identity_digest != digest:
            raise ValueError("backend identity digest mismatch")
        object.__setattr__(self, "backend_identity_digest", digest)


@dataclass(frozen=True, slots=True)
class SandboxQualificationV1:
    """只读 qualification 报告：closed reason；available ⇔ qualified。"""

    available: bool
    reason_code: str
    backend_identity: SandboxBackendIdentityV1 | None = None

    def __post_init__(self) -> None:
        if self.reason_code not in SANDBOX_QUALIFICATION_REASONS:
            raise ValueError("qualification reason_code must be closed")
        if self.available != (self.reason_code == "qualified"):
            raise ValueError("available must match reason_code")
        if self.available and not isinstance(self.backend_identity, SandboxBackendIdentityV1):
            raise ValueError("qualified report must carry backend identity")
        if not self.available and self.backend_identity is not None:
            raise ValueError("unavailable report carries no backend identity")


@dataclass(frozen=True, slots=True)
class SandboxEnforcementFactsV1:
    """enforcement facts：backend=none ⇔ unconfined（bypass）；seatbelt ⇒
    confined 且 profile digest 为 hex64（spec §4）。"""

    backend: str
    enforcement: str
    mode: SandboxMode
    network: SandboxNetworkMode
    policy_digest: str
    profile_digest: str = ""

    def __post_init__(self) -> None:
        if self.backend not in _SANDBOX_BACKENDS:
            raise ValueError("backend must be a closed value")
        if self.enforcement not in _SANDBOX_ENFORCEMENTS:
            raise ValueError("enforcement must be a closed value")
        if not isinstance(self.mode, SandboxMode) or not isinstance(
            self.network, SandboxNetworkMode,
        ):
            raise ValueError("mode/network must be closed enums")
        _require_hex64(self.policy_digest, "policy_digest")
        if self.backend == "none":
            if self.enforcement != "unconfined":
                raise ValueError("backend=none must record unconfined")
            if self.profile_digest:
                raise ValueError("unconfined facts carry no profile digest")
        else:
            if self.enforcement != "confined":
                raise ValueError("seatbelt facts must record confined")
            _require_hex64(self.profile_digest, "profile_digest")


@dataclass(frozen=True, slots=True)
class ConfinedInvocationV1:
    """confine(argv, policy) 的结果：exact wrapped argv + profile + facts。
    adapter 从不 spawn——执行由既有 process runner 完成（spec §3）。"""

    wrapped_executable: str
    wrapped_argv: tuple[str, ...]
    profile: str | None
    environment: dict[str, str]
    enforcement: SandboxEnforcementFactsV1

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "wrapped_argv", tuple(str(item) for item in self.wrapped_argv),
        )
        if not isinstance(self.wrapped_executable, str) or not self.wrapped_executable:
            raise ValueError("wrapped_executable must be a non-empty string")
        if (self.enforcement.backend == "seatbelt") != (self.profile is not None):
            raise ValueError("profile presence must match backend")
        if not isinstance(self.environment, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in self.environment.items()
        ):
            raise ValueError("environment must be a str->str mapping")


class SandboxDraftOutcome(StrEnum):
    """confined 执行的 closed 结果集（镜像 ``ProcessDraftOutcome``）。"""

    EXITED = "exited"
    SIGNALED = "signaled"
    TIMED_OUT_REAPED = "timed_out_reaped"
    SPAWN_FAILED = "spawn_failed"


@dataclass(frozen=True, slots=True)
class SandboxExecutionDraftV1:
    """confined 执行的 durable draft：绑定 original command fingerprint 与
    enforcement facts；completion 需要 receipt + host read-back（spec §9）。"""

    outcome: SandboxDraftOutcome
    exit_code: int | None
    signal: str | None
    duration_seconds: float
    stdout_bytes: int
    stderr_bytes: int
    stdout_digest: str
    stderr_digest: str
    stdout_projection: str
    stderr_projection: str
    stdout_truncated: bool
    stderr_truncated: bool
    original_command_fingerprint: str
    enforcement: SandboxEnforcementFactsV1
    draft_digest: str = ""

    @classmethod
    def from_process(
        cls,
        *,
        process,
        original_command_fingerprint: str,
        enforcement: SandboxEnforcementFactsV1,
    ):  # noqa: ANN001, ANN202
        """既有 ``run_local_process`` draft → sandbox draft（outcome 镜像映射）。"""
        return cls(
            outcome=SandboxDraftOutcome(process.outcome.value),
            exit_code=process.exit_code,
            signal=process.signal,
            duration_seconds=process.duration_seconds,
            stdout_bytes=process.stdout_bytes,
            stderr_bytes=process.stderr_bytes,
            stdout_digest=process.stdout_digest,
            stderr_digest=process.stderr_digest,
            stdout_projection=process.stdout_projection,
            stderr_projection=process.stderr_projection,
            stdout_truncated=process.stdout_truncated,
            stderr_truncated=process.stderr_truncated,
            original_command_fingerprint=original_command_fingerprint,
            enforcement=enforcement,
        )

    def identity_values(self) -> dict:
        return {
            "outcome": self.outcome.value,
            "exit_code": self.exit_code,
            "signal": self.signal,
            "duration_seconds": self.duration_seconds,
            "stdout_bytes": self.stdout_bytes,
            "stderr_bytes": self.stderr_bytes,
            "stdout_digest": self.stdout_digest,
            "stderr_digest": self.stderr_digest,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "original_command_fingerprint": self.original_command_fingerprint,
            "policy_digest": self.enforcement.policy_digest,
            "profile_digest": self.enforcement.profile_digest,
            "backend": self.enforcement.backend,
            "enforcement": self.enforcement.enforcement,
        }

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, SandboxDraftOutcome):
            raise ValueError("outcome must be a closed SandboxDraftOutcome")
        _require_hex64(self.stdout_digest, "stdout_digest")
        _require_hex64(self.stderr_digest, "stderr_digest")
        _require_hex64(
            self.original_command_fingerprint, "original_command_fingerprint",
        )
        digest = canonical_json_digest(self.identity_values())
        if self.draft_digest and self.draft_digest != digest:
            raise ValueError("sandbox draft digest mismatch")
        object.__setattr__(self, "draft_digest", digest)
