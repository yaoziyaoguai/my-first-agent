"""Bounded child runner with call-scoped termination receipt（同步 receipt 路径）。

这是 SubAgent 的 **synchronous receipt** 路径：用于结构化声明 ``deadline_contract``
（``receipt_type="synchronous"``）的 provider——它们的 ``generate`` 保证同步返回、不会
悬挂（例如本地确定性 provider substitute）。production HTTP provider 不满足该合同，必须经
process-isolated 路径（``agent.subagent.process_runner.ChildProcessRunner``）获得真实
hard deadline。

本 runner 构造同一个 ``AgentRuntime``（经 ``build_child_runtime``），提交一次确定性
``SubmitMessage``，先消费 termination receipt 再解释 child ``RunStatus``：``UNCONFIRMED``
总是覆盖 child normalization，使 parent 进入 unknown-outcome recovery。provider call 仍只
发生在 ``agent/runtime/loop.py``；不创建第二套 loop。
"""

from __future__ import annotations

from collections.abc import Callable

from agent.runtime.checkpoint import InMemoryCheckpointStore
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ConversationState,
    LoadedSnapshot,
    RunStatus,
    RuntimeEvent,
    SubmitMessage,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.subagent.contracts import (
    ChildProfile,
    ChildRunResult,
    ProviderDeadlineCapability,
    TerminationReceiptState,
)
from agent.subagent.runtime_factory import (
    child_status_reason,
    compose_child_prompt,
    derive_child_identity,
)

_MAX_MODEL_CALLS = 1


class _NullEventSink:
    """child events 不混入 parent event sequence。"""

    def emit(self, event: RuntimeEvent) -> None:  # noqa: ARG002
        return None


def build_child_runtime(
    provider: object,
    profile: ChildProfile,
    *,
    conversation_id: str,
    invocation_id_factory: Callable[[], str] | None = None,
    strict_control_schema: bool = False,
) -> tuple[AgentRuntime, InMemoryCheckpointStore]:
    """构造与父侧同类、本次调用存活的 child AgentRuntime + 其 in-memory store。

    subagent 包内**唯一**导入 ``agent.runtime.loop`` 的位置（架构 exempt）；同步 runner 与
    进程隔离 child entrypoint 都经此构造同一个 ``AgentRuntime``，不创建第二套 loop。child 固定：
    in-memory store、空 ToolRuntime、无 ContextSource、``max_model_calls=1``。
    """
    store = InMemoryCheckpointStore(ConversationState.new(conversation_id))
    context_manager = KernelContextManager(
        system_policy=(
            "You are an isolated review assistant. You have no tools and one answer. "
            "Return concise final text."
        ),
        limits=ContextLimits(
            max_input_tokens=profile.max_input_tokens,
            output_reserve=min(200, profile.max_output_tokens),
        ),
        sources=(),
        workspace_identity_digest=profile.workspace_scope_digest,
        context_scope_digest=profile.workspace_scope_digest,
        strict_control_schema=strict_control_schema,
    )
    from agent.runtime.tools import KernelToolRuntime

    tool_runtime = KernelToolRuntime(())
    runtime = AgentRuntime(
        provider=provider,  # type: ignore[arg-type]
        context_manager=context_manager,
        tool_runtime=tool_runtime,
        checkpoint_store=store,
        event_sink=_NullEventSink(),
        limits=InvocationLimits(
            max_model_calls=_MAX_MODEL_CALLS,
            max_tool_calls=1,
            max_input_tokens=profile.max_input_tokens,
            max_output_tokens=profile.max_output_tokens,
        ),
        invocation_id_factory=invocation_id_factory or (lambda: "child-invocation"),
    )
    return runtime, store


class UnsupportedProviderError(RuntimeError):
    """provider 不满足 SubAgent structural deadline contract。"""


def build_child_provider(spec) -> object:
    """在 child 进程内按可序列化 ``ChildProviderSpec`` 重建 provider。

    subagent 包内**唯一**导入 ``agent.provider`` 的位置（架构 exempt）：只有 child entrypoint
    经此构造 provider，process runner / tools 不直接依赖 provider 模块。credential 仅 http 路径
    按 ``credential_env_name`` 在子进程内从自身 env 读取（不跨进程序列化 credential 值）。
    """
    from agent.provider.config import AgentProviderConfig
    from agent.provider.factory import build_model_provider
    from agent.runtime.contracts import ModelResponse, ModelTextBlock, ModelToolCall
    from agent.subagent.contracts import ChildProviderSpec

    assert isinstance(spec, ChildProviderSpec)
    kind = spec.kind

    def make_scripted() -> ModelResponse:
        if spec.fake_tool is not None:
            name, arguments = spec.fake_tool
            return ModelResponse((ModelToolCall("child-tool-1", name, arguments),))
        return ModelResponse((ModelTextBlock(spec.fake_text or ""),))

    if kind == "fake":
        return _ScriptedFakeProvider(make_scripted, spec.sleep_seconds, spec.stderr_chars)

    if kind == "http":
        assert spec.provider_type and spec.model and spec.base_url and spec.credential_env_name
        import os

        config = AgentProviderConfig(
            provider_type=spec.provider_type,
            model=spec.model,
            base_url=spec.base_url,
            credential=os.environ.get(spec.credential_env_name),
            timeout=spec.timeout if spec.timeout is not None else 30.0,
            thinking_mode=spec.thinking_mode,
            request_path=spec.request_path,
            strict_tools=spec.strict_tools,
        )
        return build_model_provider(config)

    raise ValueError(f"unsupported child provider spec kind: {kind!r}")


class _ScriptedFakeProvider:
    """子进程内确定性 provider：可选 sleep（用于 deterministic deadline-kill）与可选 stderr
    突发（用于 stderr-drain oracle），再返回脚本结果。

    不声明 ``deadline_contract``——hard deadline 由 parent 进程边界提供，不靠本 provider。
    """

    def __init__(self, factory, sleep_seconds: float, stderr_chars: int = 0) -> None:
        self._factory = factory
        self._sleep_seconds = sleep_seconds
        self._stderr_chars = stderr_chars

    def generate(self, context):  # noqa: ARG002
        if self._stderr_chars > 0:
            import sys

            # 分块写并 flush，模拟 server 在返回前突发大量 stderr（>pipe buffer）。
            sys.stderr.write("SECRET-STDERR-MARKER\n")
            sys.stderr.flush()
            chunk = "S" * 8192
            remaining = self._stderr_chars
            while remaining > 0:
                sys.stderr.write(chunk[:remaining])
                sys.stderr.flush()
                remaining -= len(chunk[:remaining])
        if self._sleep_seconds > 0:
            import time

            time.sleep(self._sleep_seconds)
        return self._factory()


class ChildAgentRunner:
    """production 实现：唯一允许间接触发同一 ``AgentRuntime.run_turn`` 的位置。"""

    def __init__(
        self,
        *,
        provider: object,
        profile: ChildProfile,
        invocation_id_factory: Callable[[], str] | None = None,
    ) -> None:
        cap = ProviderDeadlineCapability.from_provider(provider)
        if cap is None:
            raise UnsupportedProviderError(
                "provider does not expose a structural deadline_contract; "
                "SubAgent requires ProviderDeadlineCapability"
            )
        if cap.hard_deadline_seconds > profile.hard_deadline_seconds:
            raise UnsupportedProviderError(
                "provider hard_deadline exceeds child cap"
            )
        self._provider = provider
        self._profile = profile
        self._invocation_id_factory = invocation_id_factory or (lambda: "child-invocation")

    @property
    def profile(self) -> ChildProfile:
        return self._profile

    def run(
        self,
        *,
        objective: str,
        handoff: str,
        parent_idempotency_key: str,
    ) -> ChildRunResult:
        child_conversation_id, child_run_id = derive_child_identity(parent_idempotency_key)
        runtime, store = build_child_runtime(
            self._provider,
            self._profile,
            conversation_id=child_conversation_id,
            invocation_id_factory=self._invocation_id_factory,
        )
        action = SubmitMessage(
            conversation_id=child_conversation_id,
            action_seq=1,
            expected_revision=0,
            run_id=child_run_id,
            message=compose_child_prompt(objective, handoff),
        )
        snapshot: LoadedSnapshot = store.load()

        receipt = TerminationReceiptState.TERMINATED
        result = None
        try:
            result = runtime.run_turn(action, snapshot)
        except Exception:
            # provider 可能已经发送请求但无法确认终止 → UNCONFIRMED。
            receipt = TerminationReceiptState.UNCONFIRMED

        if receipt is TerminationReceiptState.UNCONFIRMED:
            # UNCONFIRMED 覆盖一切 child normalization。
            return ChildRunResult(
                status=RunStatus.FAILED_FATAL,
                run_id=child_run_id,
                message="",
                reason="unconfirmed_outcome",
                model_calls=0,
                tool_calls=0,
                receipt_state=receipt,
            )

        assert result is not None
        return ChildRunResult(
            status=result.status,
            run_id=child_run_id,
            message=result.message or "",
            reason=child_status_reason(result.status),
            model_calls=_MAX_MODEL_CALLS,
            tool_calls=0,
            receipt_state=receipt,
        )
