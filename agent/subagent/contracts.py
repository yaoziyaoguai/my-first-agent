"""SubAgent child 合同：structural provider deadline + termination receipt."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agent.runtime.contracts import RunStatus


class TerminationReceiptState(StrEnum):
    """call-scoped single-use receipt proving whether the provider call terminated."""

    TERMINATED = "terminated"
    UNCONFIRMED = "unconfirmed"


@dataclass(frozen=True, slots=True)
class ProviderDeadlineCapability:
    """Structural contract a provider must expose to qualify for SubAgent v1.

    Checked by attribute presence (``deadline_contract``), NOT by class name.
    Providers that don't expose this attribute are unsupported.
    """

    hard_deadline_seconds: float
    receipt_type: str  # "synchronous" | "native_timeout" | etc.

    attr_name = "deadline_contract"

    @classmethod
    def from_provider(cls, provider: object) -> ProviderDeadlineCapability | None:
        cap = getattr(provider, cls.attr_name, None)
        if not isinstance(cap, cls):
            return None
        return cap


@dataclass(frozen=True, slots=True)
class ChildProfile:
    """child 隔离 profile 的非秘密 identity 与边界。"""

    runner_version: str
    provider_profile_id: str
    provider_destination: str
    workspace_scope_digest: str
    max_input_tokens: int
    max_output_tokens: int
    limits_digest: str
    hard_deadline_seconds: float


@dataclass(frozen=True, slots=True)
class ChildProviderSpec:
    """process-isolated child 在子进程内重建 provider 所需的可序列化、非秘密描述。

    - ``kind="fake"``：子进程构造确定性 ``FakeProvider``。``fake_text`` 为返回文本；
      ``fake_tool``（``(name, arguments)``）使子进程返回一次 tool call（用于 nonterminal
      E2）。``sleep_seconds`` 让子进程的 generate 阻塞（用于 deterministic deadline-kill）。
    - ``kind="http"``：子进程用 ``build_model_provider`` 构造真实 HTTP adapter；
      credential 只按 ``credential_env_name`` 在子进程内从自身 env 读取（不跨进程序列化
      credential 值），其余为非秘密 config。

    无论哪种 kind，spec 本身都不含 credential 值；它不进入 parent checkpoint/event/manifest。
    """

    kind: str
    fake_text: str | None = None
    fake_tool: tuple[str, dict] | None = None
    sleep_seconds: float = 0.0
    stderr_chars: int = 0
    provider_type: str | None = None
    model: str | None = None
    base_url: str | None = None
    credential_env_name: str | None = None
    timeout: float | None = None
    thinking_mode: str | None = None


@dataclass(frozen=True, slots=True)
class ChildRunResult:
    """runner 返回的 bounded child 结果。不含 raw prompt/response/credential。"""

    status: RunStatus
    run_id: str
    message: str
    reason: str
    model_calls: int
    tool_calls: int
    receipt_state: TerminationReceiptState
