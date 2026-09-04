"""017 native sandbox contracts（frozen spec §3–§5）。

closed 三值 mode/network、policy identity、backend identity、enforcement
facts 与 confined invocation。本模块不认识 Goal/provider/approval；治理
合同在 ``agent.runtime``。Docker/image/snapshot/bundle 词汇不存在于此。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

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

STRUCTURED_REQUEST_MAX_BYTES = 64 * 1024
STRUCTURED_INPUT_MAX_ITEMS = 16
STRUCTURED_INPUT_MAX_BYTES = 32 * 1024 * 1024
STRUCTURED_INPUT_AGGREGATE_MAX_BYTES = 64 * 1024 * 1024
STRUCTURED_RESULT_MAX_BYTES = 64 * 1024 * 1024
STRUCTURED_ARTIFACT_MAX_BYTES = 64 * 1024 * 1024
STRUCTURED_OUTPUT_AGGREGATE_MAX_BYTES = 64 * 1024 * 1024
STRUCTURED_MAGIC_MAX_ITEMS = 16
STRUCTURED_MAGIC_MAX_BYTES = 64


PACKAGED_LIMIT_PROFILE_VALUES = MappingProxyType(
    {
        "skill-standard-v1": MappingProxyType(
            {
                "cpu_seconds": 60,
                "address_space_bytes": 1024 * 1024 * 1024,
                "file_size_bytes": 64 * 1024 * 1024,
                "open_files": 64,
                "core_bytes": 0,
            }
        ),
        "artifact-standard-v1": MappingProxyType(
            {
                "cpu_seconds": 120,
                "address_space_bytes": 2 * 1024 * 1024 * 1024,
                "file_size_bytes": 64 * 1024 * 1024,
                "open_files": 128,
                "core_bytes": 0,
            }
        ),
    }
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


@dataclass(frozen=True, slots=True)
class PackagedSkillResourceLimitsV1:
    """packaged Skill 只能使用冻结的资源档位。"""

    profile: str
    cpu_seconds: int
    address_space_bytes: int
    file_size_bytes: int
    open_files: int
    core_bytes: int
    limits_digest: str = ""

    @classmethod
    def for_profile(cls, profile: str) -> PackagedSkillResourceLimitsV1:
        try:
            values = PACKAGED_LIMIT_PROFILE_VALUES[profile]
        except KeyError as error:
            raise ValueError("packaged resource profile is not closed") from error
        return cls(profile=profile, **values)

    def __post_init__(self) -> None:
        values = {
            "profile": self.profile,
            "cpu_seconds": self.cpu_seconds,
            "address_space_bytes": self.address_space_bytes,
            "file_size_bytes": self.file_size_bytes,
            "open_files": self.open_files,
            "core_bytes": self.core_bytes,
        }
        expected = PACKAGED_LIMIT_PROFILE_VALUES.get(self.profile)
        if expected is None or any(
            not isinstance(getattr(self, name), int)
            or isinstance(getattr(self, name), bool)
            or getattr(self, name) != value
            for name, value in expected.items()
        ):
            raise ValueError("packaged resource limits do not match their closed profile")
        digest = canonical_json_digest(values)
        if self.limits_digest and self.limits_digest != digest:
            raise ValueError("packaged resource limit digest mismatch")
        object.__setattr__(self, "limits_digest", digest)


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
class PackagedSkillSandboxPolicyV1:
    """strict packaged-Skill policy identity；无 full-network 或 danger 分支。"""

    interpreter_path: str
    runtime_roots: tuple[str, ...]
    package_root: str
    temp_root: str
    system_runtime_roots: tuple[str, ...]
    workspace_root: str
    home_root: str
    state_root: str
    private_roots: tuple[str, ...]
    runtime_closure_digest: str
    system_runtime_digest: str
    resource_limits: PackagedSkillResourceLimitsV1
    package_read_paths: tuple[str, ...] = ()
    policy_digest: str = ""
    mode: SandboxMode = field(init=False, default=SandboxMode.READ_ONLY)
    network: SandboxNetworkMode = field(init=False, default=SandboxNetworkMode.OFF)

    def identity_values(self) -> dict[str, object]:
        return {
            "profile": "packaged-skill-v1",
            "interpreter_path": self.interpreter_path,
            "runtime_roots": list(self.runtime_roots),
            "package_root": self.package_root,
            "package_read_paths": list(self.package_read_paths),
            "temp_root": self.temp_root,
            "system_runtime_roots": list(self.system_runtime_roots),
            "workspace_root": self.workspace_root,
            "home_root": self.home_root,
            "state_root": self.state_root,
            "private_roots": list(self.private_roots),
            "runtime_closure_digest": self.runtime_closure_digest,
            "system_runtime_digest": self.system_runtime_digest,
            "resource_limits_digest": self.resource_limits.limits_digest,
            "mode": self.mode.value,
            "network": self.network.value,
        }

    def __post_init__(self) -> None:
        for name in (
            "interpreter_path",
            "package_root",
            "temp_root",
            "workspace_root",
            "home_root",
            "state_root",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.startswith("/"):
                raise ValueError(f"{name} must be an absolute canonical path")
        object.__setattr__(
            self, "runtime_roots", _string_roots(self.runtime_roots, "runtime_roots")
        )
        object.__setattr__(
            self,
            "system_runtime_roots",
            _string_roots(self.system_runtime_roots, "system_runtime_roots"),
        )
        object.__setattr__(
            self, "private_roots", _string_roots(self.private_roots, "private_roots")
        )
        if not isinstance(self.package_read_paths, tuple) or any(
            not isinstance(value, str) for value in self.package_read_paths
        ):
            raise TypeError("package_read_paths must be a tuple of strings")
        if not isinstance(self.resource_limits, PackagedSkillResourceLimitsV1):
            raise TypeError("resource_limits must be a packaged resource profile")
        _require_hex64(self.runtime_closure_digest, "runtime_closure_digest")
        _require_hex64(self.system_runtime_digest, "system_runtime_digest")
        digest = canonical_json_digest(self.identity_values())
        if self.policy_digest and self.policy_digest != digest:
            raise ValueError("packaged sandbox policy digest mismatch")
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


class StructuredResultKind(StrEnum):
    """结构化 sandbox 固定结果协议的闭合集合。"""

    OBSERVATION = "observation"
    ARTIFACT = "artifact"


class StructuredReadbackOutcome(StrEnum):
    """owner-only readback 的闭合分类，不能由 child 自报。"""

    VALID = "valid"
    NOT_READ = "not_read"
    RESULT_MISSING = "result_missing"
    RESULT_REPLACED = "result_replaced"
    RESULT_TOO_LARGE = "result_too_large"
    RESULT_MALFORMED = "result_malformed"
    ARTIFACT_REPLACED = "artifact_replaced"
    ARTIFACT_TOO_LARGE = "artifact_too_large"
    ARTIFACT_UNEXPECTED = "artifact_unexpected"
    ARTIFACT_MISSING = "artifact_missing"
    EXTRA_OUTPUT = "extra_output"


@dataclass(frozen=True, slots=True)
class StructuredSandboxInputV1:
    """单个临时输入；原始 bytes 只允许停留在同次 session。"""

    slot: str
    content: bytes
    content_digest: str
    allowed_magic_hex: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", self.slot) is None:
            raise ValueError("structured input slot has an invalid shape")
        if not isinstance(self.content, bytes):
            raise TypeError("structured input content must be bytes")
        if hashlib.sha256(self.content).hexdigest() != self.content_digest:
            raise ValueError("structured input digest mismatch")
        if not isinstance(self.allowed_magic_hex, tuple) or any(
            not isinstance(value, str) for value in self.allowed_magic_hex
        ):
            raise TypeError("structured input magic must be a tuple of strings")
        magic = tuple(sorted(set(self.allowed_magic_hex)))
        if len(magic) > STRUCTURED_MAGIC_MAX_ITEMS or any(
            re.fullmatch(r"(?:[0-9a-f]{2})+", value) is None
            or len(value) // 2 > STRUCTURED_MAGIC_MAX_BYTES
            for value in magic
        ):
            raise ValueError("structured input magic must be lowercase even-length hex")
        if len(self.content) > STRUCTURED_INPUT_MAX_BYTES:
            raise ValueError("structured input exceeds product maximum")
        object.__setattr__(self, "allowed_magic_hex", magic)


@dataclass(frozen=True, slots=True)
class StructuredSandboxIoPlanV1:
    """单次 structured invocation 的全部 authority-bound I/O 事实。"""

    package_digest: str
    entrypoint_id: str
    entrypoint_digest: str
    request_bytes: bytes
    request_digest: str
    inputs: tuple[StructuredSandboxInputV1, ...]
    result_cap_bytes: int
    artifact_cap_bytes: int
    aggregate_output_cap_bytes: int
    expected_result_kind: StructuredResultKind

    def __post_init__(self) -> None:
        _require_hex64(self.package_digest, "package_digest")
        _require_hex64(self.entrypoint_digest, "entrypoint_digest")
        if not self.entrypoint_id or len(self.entrypoint_id.encode("utf-8")) > 128:
            raise ValueError("entrypoint_id is invalid")
        if not isinstance(self.request_bytes, bytes):
            raise TypeError("structured request must be bytes")
        if hashlib.sha256(self.request_bytes).hexdigest() != self.request_digest:
            raise ValueError("structured request digest mismatch")
        if len(self.request_bytes) > STRUCTURED_REQUEST_MAX_BYTES:
            raise ValueError("structured request exceeds product maximum")
        if not isinstance(self.inputs, tuple) or any(
            not isinstance(item, StructuredSandboxInputV1) for item in self.inputs
        ):
            raise TypeError("structured inputs must be a closed tuple")
        if len(self.inputs) > STRUCTURED_INPUT_MAX_ITEMS:
            raise ValueError("structured input count exceeds product maximum")
        if (
            sum(len(item.content) for item in self.inputs)
            > STRUCTURED_INPUT_AGGREGATE_MAX_BYTES
        ):
            raise ValueError("structured input aggregate exceeds product maximum")
        slots = tuple(item.slot for item in self.inputs)
        if len(set(slots)) != len(slots):
            raise ValueError("structured input slots must be unique")
        for name in (
            "result_cap_bytes",
            "artifact_cap_bytes",
            "aggregate_output_cap_bytes",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be positive")
        if self.result_cap_bytes + self.artifact_cap_bytes < self.aggregate_output_cap_bytes:
            raise ValueError("aggregate output cap exceeds per-file caps")
        if (
            self.result_cap_bytes > STRUCTURED_RESULT_MAX_BYTES
            or self.artifact_cap_bytes > STRUCTURED_ARTIFACT_MAX_BYTES
            or self.aggregate_output_cap_bytes > STRUCTURED_OUTPUT_AGGREGATE_MAX_BYTES
        ):
            raise ValueError("structured output cap exceeds product maximum")
        if not isinstance(self.expected_result_kind, StructuredResultKind):
            raise TypeError("expected result kind must be closed")


def structured_invocation_digest(prepared, policy, plan: StructuredSandboxIoPlanV1) -> str:  # noqa: ANN001
    """session 随机路径之外、并且所有 authority 输入都绑定的稳定 digest。"""

    return canonical_json_digest(
        {
            "domain": "first-agent-structured-invocation-v1",
            "process_command_fingerprint": prepared.command.command_fingerprint,
            "package_digest": plan.package_digest,
            "entrypoint_id": plan.entrypoint_id,
            "entrypoint_digest": plan.entrypoint_digest,
            "request_size": len(plan.request_bytes),
            "request_digest": plan.request_digest,
            "inputs": [
                {
                    "slot": item.slot,
                    "size": len(item.content),
                    "digest": item.content_digest,
                    "allowed_magic_hex": list(item.allowed_magic_hex),
                }
                for item in plan.inputs
            ],
            "policy_digest": policy.policy_digest,
            "temp_parent_digest": canonical_json_digest(
                {"temp_root": policy.temp_root}
            ),
            "result_cap_bytes": plan.result_cap_bytes,
            "artifact_cap_bytes": plan.artifact_cap_bytes,
            "aggregate_output_cap_bytes": plan.aggregate_output_cap_bytes,
            "expected_result_kind": plan.expected_result_kind.value,
        }
    )


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


@dataclass(frozen=True, slots=True)
class StructuredSandboxProcessDraftV1:
    """一次 sandbox process 与 owner-only readback 的瞬时组合草稿。"""

    process: SandboxExecutionDraftV1
    structured_invocation_digest: str
    readback_outcome: StructuredReadbackOutcome
    request_digest: str
    input_digests: tuple[tuple[str, int, str], ...]
    result_bytes: bytes
    result_digest: str
    artifact_bytes: bytes | None
    artifact_digest: str | None
    draft_digest: str = ""

    def identity_values(self) -> dict[str, object]:
        return {
            "process_draft_digest": self.process.draft_digest,
            "structured_invocation_digest": self.structured_invocation_digest,
            "readback_outcome": self.readback_outcome.value,
            "request_digest": self.request_digest,
            "input_digests": [list(item) for item in self.input_digests],
            "result_size": len(self.result_bytes),
            "result_digest": self.result_digest,
            "artifact_size": (
                len(self.artifact_bytes) if self.artifact_bytes is not None else None
            ),
            "artifact_digest": self.artifact_digest,
        }

    def __post_init__(self) -> None:
        if not isinstance(self.process, SandboxExecutionDraftV1):
            raise TypeError("structured draft requires one sandbox process draft")
        _require_hex64(self.structured_invocation_digest, "structured_invocation_digest")
        _require_hex64(self.request_digest, "request_digest")
        if not isinstance(self.readback_outcome, StructuredReadbackOutcome):
            raise TypeError("structured readback outcome must be closed")
        object.__setattr__(self, "input_digests", tuple(self.input_digests))
        if tuple(sorted(self.input_digests)) != self.input_digests:
            raise ValueError("structured input digests must be canonical")
        for slot, size, digest in self.input_digests:
            if re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", slot) is None or size < 0:
                raise ValueError("structured input digest identity is invalid")
            _require_hex64(digest, "structured input digest")
        if not isinstance(self.result_bytes, bytes):
            raise TypeError("structured result must be bytes")
        if hashlib.sha256(self.result_bytes).hexdigest() != self.result_digest:
            raise ValueError("structured result digest mismatch")
        if self.artifact_bytes is not None and not isinstance(self.artifact_bytes, bytes):
            raise TypeError("structured artifact must be bytes")
        expected_artifact = (
            hashlib.sha256(self.artifact_bytes).hexdigest()
            if self.artifact_bytes is not None
            else None
        )
        if expected_artifact != self.artifact_digest:
            raise ValueError("structured artifact digest mismatch")
        if self.readback_outcome is not StructuredReadbackOutcome.VALID and (
            self.result_bytes or self.artifact_bytes not in {None, b""}
        ):
            raise ValueError("invalid readback cannot expose staged bytes")
        spawn_failed = self.process.outcome is SandboxDraftOutcome.SPAWN_FAILED
        not_read = self.readback_outcome is StructuredReadbackOutcome.NOT_READ
        if spawn_failed != not_read:
            raise ValueError("spawn-failed and not-read must occur together")
        expected = canonical_json_digest(self.identity_values())
        if self.draft_digest and self.draft_digest != expected:
            raise ValueError("structured draft digest mismatch")
        object.__setattr__(self, "draft_digest", expected)
