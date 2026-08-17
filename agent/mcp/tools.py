"""MCP governed tool registrations。

把每个 catalog descriptor 映射为 HIGH + EXTERNAL + ALWAYS_APPROVAL 的 governed tool。
intent-aware executor 提交一次有限时 stdio session coroutine 到 bridge，并把
``McpBridgeOutcome`` 映射为：EXECUTED → 文本结果；NOT_EXECUTED → ``KnownNotExecuted``；
UNKNOWN → 抛出（交由 Runtime recovery）。bridge 自身的 thread/loop 在 coroutine 正常返回时
是健康的——只有 total_timeout（coroutine 仍在跑、无法证明 cleanup）才 quarantine 共享
bridge；clean UNKNOWN 不 quarantine，避免单个 server 的不确定 outcome 永久误伤同
composition 的无关 MCP server，durable 安全由 per-binding latch（保持 ARMED）保证。
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.mcp.bridge import (
    BridgeClosedError,
    BridgeQuarantinedError,
    BridgeTimeoutError,
    McpAsyncBridge,
    SessionTimeouts,
    run_stdio_session,
)
from agent.mcp.catalog import McpCatalog, McpServerConfig, McpToolDescriptor
from agent.mcp.contracts import McpOutcomeClassification
from agent.mcp.safety import LatchBinding, McpSafetyLatch, SafetyLatchError
from agent.runtime.contracts import (
    ApprovalPolicy,
    ExecutionAuthorityClass,
    KnownExecutedError,
    KnownNotExecuted,
    OutputPolicy,
    PolicyDecision,
    SideEffectClass,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.tools import RegisteredTool

MCP_TOOL_POLICY_VERSION = "mcp-tool-v1"
PREVIEW_ARG_CAP = 2_000


class McpUnknownOutcomeError(RuntimeError):
    """MCP call 可能已发生但结果未知；交由 Runtime unknown-outcome recovery。"""


class _McpToolPolicy:
    identity = MCP_TOOL_POLICY_VERSION

    def evaluate(self, spec, arguments, binding):  # noqa: ARG002
        # 所有 v1 MCP tool 统一 ALWAYS_APPROVAL；remote annotation 不能降低。
        return PolicyDecision.REQUIRE_APPROVAL


@dataclass(frozen=True, slots=True)
class McpExecutorConfig:
    bridge: McpAsyncBridge
    latch: McpSafetyLatch
    composition_epoch: str
    timeouts: SessionTimeouts
    env_provider: object  # Callable[[tuple[str, ...]], dict[str, str]]


def build_mcp_tool_registrations(
    catalog: McpCatalog,
    *,
    executor_config: McpExecutorConfig,
) -> tuple[RegisteredTool, ...]:
    registrations: list[RegisteredTool] = []
    servers = {server.server_id: server for server in catalog.servers}
    for descriptor in catalog.tools:
        server = servers[descriptor.server_id]
        registrations.append(
            RegisteredTool(
                spec=_build_spec(descriptor, server, executor_config.composition_epoch),
                func=_make_executor(descriptor, server, executor_config),
                prepare_binding=_make_binding(
                    descriptor, server, executor_config.composition_epoch
                ),
                policy=_McpToolPolicy(),
            )
        )
    return tuple(registrations)


def _build_spec(
    descriptor: McpToolDescriptor,
    server: McpServerConfig,
    composition_epoch: str,
) -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name=descriptor.local_name,
        version="1",
        description=descriptor.description,
        input_schema=dict(descriptor.input_schema),
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.EXTERNAL,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={
            "kind": "mcp_tool",
            "server_id": server.server_id,
            "config_digest": server.config_digest,
            "descriptor_digest": descriptor.descriptor_digest,
            "credential_profile": server.credential_profile,
            "safety_generation": server.safety_generation,
            "composition_epoch": composition_epoch,
            "policy_version": MCP_TOOL_POLICY_VERSION,
        },
        output_limit_chars=descriptor.output_limit_chars,
    )


def _make_binding(descriptor, server, composition_epoch):
    def prepare(arguments):
        canonical = _canonical_arguments(arguments)
        if len(canonical) > PREVIEW_ARG_CAP:
            raise ValueError("canonical arguments exceed the preview cap")
        return {
            "effect_preview": _preview(descriptor, server, composition_epoch, canonical),
            "target_digest": server.config_digest,
            "arguments_digest": _arguments_digest(canonical),
        }

    return prepare


def _canonical_arguments(arguments) -> str:
    import json

    return json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)


def _arguments_digest(canonical: str) -> str:
    import hashlib

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _preview(descriptor, server, composition_epoch, canonical_args: str) -> str:
    executable = str(server.command)
    cwd = server.cwd or "<workspace>"
    return (
        f"mcp server={server.server_id} tool={descriptor.remote_name} "
        f"profile={server.credential_profile} generation={server.safety_generation} "
        f"epoch={composition_epoch} executable={executable} cwd={cwd} "
        f"arguments={canonical_args}"
    )


def _make_executor(descriptor, server, config: McpExecutorConfig):
    def execute(intent):
        binding = LatchBinding(
            server_id=server.server_id,
            config_digest=server.config_digest,
            credential_profile=server.credential_profile,
            safety_generation=server.safety_generation,
            intent_digest=intent.intent_digest,
        )
        snapshot = config.latch.snapshot()
        expected_clear_revision = snapshot.revision if snapshot is not None else 0
        try:
            outcome = config.bridge.submit(
                lambda: run_stdio_session(
                    command=server.command,
                    args=server.args,
                    cwd=server.cwd,
                    env=config.env_provider(server.env_names),
                    remote_name=descriptor.remote_name,
                    arguments=dict(intent.arguments),
                    input_schema=descriptor.input_schema,
                    descriptor_digest=descriptor.descriptor_digest,
                    latch=config.latch,
                    binding=binding,
                    expected_clear_revision=expected_clear_revision,
                    timeouts=config.timeouts,
                    spawn_identity=server.spawn_identity,
                )
            )
        except BridgeTimeoutError:
            # bridge 总 timeout 发生在 coroutine 运行中；无法证明
            # call bytes 未写出，必须按 UNKNOWN 处理（quarantine + recovery）。
            config.bridge.quarantine(reason="bridge total timeout")
            raise McpUnknownOutcomeError(
                "MCP bridge total timeout; call outcome unknown"
            ) from None
        except (
            BridgeQuarantinedError,
            BridgeClosedError,
            SafetyLatchError,
        ):
            return KnownNotExecuted(
                code="mcp_unavailable",
                message="MCP bridge or latch is unavailable; rebuild configuration",
            )
        if outcome.classification is McpOutcomeClassification.EXECUTED:
            if outcome.error_code:
                # remote ``isError`` 或 unsupported content：call 已发生（bytes 已发、响应已收），
                # 但 server 报告业务错误或返回了无法呈现的内容。必须作为 known-executed error
                # 返回（is_error=True/executed=True），不能当作普通成功字符串误导模型。
                # server 的 error text 仍带给模型，使其能修正参数重试。
                return KnownExecutedError(
                    code=outcome.error_code,
                    message=outcome.result_text
                    or outcome.error_message
                    or "remote tool reported an error",
                )
            return outcome.result_text
        if outcome.classification is McpOutcomeClassification.NOT_EXECUTED:
            return KnownNotExecuted(
                code=outcome.error_code or "not_executed",
                message=outcome.error_message,
            )
        # UNKNOWN：effect 可能已发生，抛给 Runtime recovery。bridge 的 thread/loop 在
        # coroutine 正常返回时健康（只有 total_timeout 才不可信——见 except BridgeTimeoutError），
        # 故不 quarantine 共享 bridge，避免单个 server 的不确定 outcome 永久误伤同 composition
        # 的无关 MCP server。durable 安全由 per-binding latch 保持 ARMED（operator-only
        # recovery）保证：同 binding 重试会撞已 ARMED latch → KnownNotExecuted。
        raise McpUnknownOutcomeError(outcome.error_message or "unknown mcp outcome")

    return execute
