"""015 process admission 的 closed 合同（KTD5/KTD7）。

这些是 process-package 内部合同：command identity、resource profile、environment
policy、executable identity。durable authority 合同（lease/candidate/receipt）仍在
``agent.runtime.contracts``，因为 checkpoint 要 round-trip 它们。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

# F4（review finding 2026-08-16）：``KnownNotExecuted`` 只有一个 closed 类型，由
# ``agent.runtime.contracts`` 拥有（KernelToolRuntime.invoke 的 isinstance 分支消费）。
# process 包 re-export 同一类——admission/executor 的 drift/denial 返回值必须能进入
# ``ToolResult(executed=False)``，而不是因类型分裂退化为 TypeError→假 unknown。
from agent.runtime.contracts import KnownNotExecuted  # noqa: F401  re-export

# same-UID trust boundary 的准确措辞（design §3.2 / §12.1）。approval preview、README、
# UI 都引用同一文本，确保不宣称 OS sandbox / filesystem confinement / network denial。
SAME_UID_TRUST_NOTICE = (
    "Same-UID operator-trusted process: the approved command runs as your OS user. "
    "cwd is only the starting directory and does not confine filesystem access; the "
    "child can read or write other same-UID files, open network connections, and spawn "
    "further processes that may leave the observed process group. This is not an OS "
    "sandbox, not a filesystem confinement, and not a network denial."
)


class ResourceProfile(StrEnum):
    """模型唯一可选的 closed resource profile（§7.3）。"""

    SHORT = "short"
    STANDARD = "standard"
    LONG = "long"


@dataclass(frozen=True, slots=True)
class ResourceProfileV1:
    """单个 closed profile 的固定 wall deadline / grace / output caps / argv 上限。"""

    profile: ResourceProfile
    wall_deadline_seconds: int
    term_grace_seconds: int
    kill_grace_seconds: int
    stdout_cap_bytes: int
    stderr_cap_bytes: int
    combined_cap_bytes: int
    rendered_chars: int
    argv_max_items: int
    argv_item_max_bytes: int
    argv_total_max_bytes: int
    executable_hash_max_bytes: int

    @classmethod
    def for_profile(cls, profile: ResourceProfile) -> ResourceProfileV1:
        # 固定 v1 合同（plan §Closed Resource Profiles），不做可配置 framework。
        if profile is ResourceProfile.SHORT:
            return cls(
                profile=profile,
                wall_deadline_seconds=10,
                term_grace_seconds=1,
                kill_grace_seconds=1,
                stdout_cap_bytes=256 * 1024,
                stderr_cap_bytes=256 * 1024,
                combined_cap_bytes=512 * 1024,
                rendered_chars=16_000,
                argv_max_items=128,
                argv_item_max_bytes=16 * 1024,
                argv_total_max_bytes=64 * 1024,
                executable_hash_max_bytes=256 * 1024 * 1024,
            )
        if profile is ResourceProfile.STANDARD:
            return cls(
                profile=profile,
                wall_deadline_seconds=120,
                term_grace_seconds=2,
                kill_grace_seconds=2,
                stdout_cap_bytes=1024 * 1024,
                stderr_cap_bytes=1024 * 1024,
                combined_cap_bytes=2 * 1024 * 1024,
                rendered_chars=32_000,
                argv_max_items=128,
                argv_item_max_bytes=16 * 1024,
                argv_total_max_bytes=64 * 1024,
                executable_hash_max_bytes=256 * 1024 * 1024,
            )
        return cls(
            profile=ResourceProfile.LONG,
            wall_deadline_seconds=900,
            term_grace_seconds=5,
            kill_grace_seconds=5,
            stdout_cap_bytes=2 * 1024 * 1024,
            stderr_cap_bytes=2 * 1024 * 1024,
            combined_cap_bytes=4 * 1024 * 1024,
            rendered_chars=64_000,
            argv_max_items=128,
            argv_item_max_bytes=16 * 1024,
            argv_total_max_bytes=64 * 1024,
            executable_hash_max_bytes=256 * 1024 * 1024,
        )


# closed environment allowlist：child 只允许出现这些名称（runner 在 EXECUTING 时填值）。
# 不含任何 provider/proxy/ambient key（R14）。PATH 由 composition 捕获；HOME/TMPDIR 指向
# product-owned isolated 目录；locale 为 closed safe subset。
ENVIRONMENT_ALLOWLIST: tuple[str, ...] = (
    "HOME",
    "TMPDIR",
    "PATH",
    "LANG",
    "LC_CTYPE",
    "TZ",
)

# closed safe locale fallback（host locale 不可安全采用时使用）。
SAFE_LOCALE = "C.UTF-8"


@dataclass(frozen=True, slots=True)
class EnvironmentProfileV1:
    """admission 构造的 immutable environment plan（不创建任何目录）。

    只描述 policy identity（allowlist + locale + 捕获 PATH 的 digest），不保存 raw PATH
    value；实际 child environment 由 runner 在 EXECUTING checkpoint 后构造。
    """

    allowlist: tuple[str, ...]
    locale: str
    path_digest: str
    policy_digest: str

    @classmethod
    def build(cls, *, captured_path: str) -> EnvironmentProfileV1:
        path_digest = hashlib.sha256(captured_path.encode("utf-8")).hexdigest()
        policy_digest = _canonical_digest(
            {
                "allowlist": list(ENVIRONMENT_ALLOWLIST),
                "locale": SAFE_LOCALE,
                "path_digest": path_digest,
            }
        )
        return cls(
            allowlist=ENVIRONMENT_ALLOWLIST,
            locale=SAFE_LOCALE,
            path_digest=path_digest,
            policy_digest=policy_digest,
        )


@dataclass(frozen=True, slots=True)
class ExecutableIdentityV1:
    """resolved executable identity（KTD5）：canonical path + symlink chain + stat + digest。

    admission 绑定 identity，invoke 紧邻 spawn 时 revalidate；drift 返回
    ``KnownNotExecuted(code="executable_identity_changed")``。该机制缩小 race，不宣称
    消除 kernel-level TOCTOU。
    """

    token: str
    resolved_path: str
    symlink_chain: tuple[dict, ...]
    st_dev: int
    st_ino: int
    file_type: str
    mode: int
    size: int
    mtime_ns: int
    content_digest: str
    is_regular_executable: bool
    identity_digest: str


@dataclass(frozen=True, slots=True)
class ProcessCommandV1:
    """canonical command identity（§5.1）。模型工具参数只暴露 token/argv/cwd/profile。"""

    executable_token: str
    argv: tuple[str, ...]
    cwd: str
    profile: ResourceProfile
    executable_identity: ExecutableIdentityV1 | None = None
    environment_policy: EnvironmentProfileV1 | None = None
    expected_artifact_digest: str | None = None
    # F3（review finding 2026-08-16）：cwd 绑定 descriptor identity（st_dev/st_ino）
    # ——path string digest 不能区分同路径 rm+mkdir 替换后的新目录。
    cwd_descriptor: str | None = None
    command_fingerprint: str = ""

    def __post_init__(self) -> None:
        if "\x00" in self.executable_token or any("\x00" in item for item in self.argv):
            raise ValueError("executable/argv must not contain NUL")
        object.__setattr__(self, "argv", tuple(self.argv))
        payload = {
            "executable_token": self.executable_token,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "profile": self.profile.value,
            "executable_identity_digest": (
                self.executable_identity.identity_digest
                if self.executable_identity is not None
                else None
            ),
            "environment_policy_digest": (
                self.environment_policy.policy_digest
                if self.environment_policy is not None
                else None
            ),
            "expected_artifact_digest": self.expected_artifact_digest,
            "cwd_descriptor": self.cwd_descriptor,
        }
        object.__setattr__(self, "command_fingerprint", _canonical_digest(payload))


class ProcessDraftOutcome(StrEnum):
    """runner 一次 bounded lifecycle 的 closed outcome（§5.5 / §10）。

    ``SPAWN_FAILED`` 表示 spawn 前/时证明未执行；spawn 后无法确认的失败由调用方
    （Runtime）映射到既有 unknown-outcome recovery，不在这里伪造 receipt。
    """

    EXITED = "exited"
    SIGNALED = "signaled"
    TIMED_OUT_REAPED = "timed_out_reaped"
    SPAWN_FAILED = "spawn_failed"


@dataclass(frozen=True, slots=True)
class ProcessExecutionDraftV1:
    """runner 唯一返回的 closed draft（KTD8）。Kernel 校验 bounds 后才铸造 receipt。

    draft 不是 receipt：普通 callable 返回 draft 仍被拒绝。只携带 closed 字段，无自由
    metadata map。stdout/stderr 是 bounded untrusted bytes + digest + deterministic
    replacement projection + truncation flag。
    """

    outcome: ProcessDraftOutcome
    pid: int | None
    process_group_id: int | None
    exit_code: int | None
    signal: str | None
    started_at_monotonic: float
    ended_at_monotonic: float
    duration_seconds: float
    stdout_bytes: int
    stderr_bytes: int
    stdout_digest: str
    stderr_digest: str
    stdout_projection: str
    stderr_projection: str
    stdout_truncated: bool
    stderr_truncated: bool
    group_reaped: bool
    term_sent: bool
    kill_sent: bool
    error_code: str | None = None


# --------------------------------------------------------------------------- #
# digest helpers（避免与 runtime contracts 的 canonical_json_digest 形成跨包依赖）。
# --------------------------------------------------------------------------- #


def _canonical_digest(value: object) -> str:
    import json

    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
