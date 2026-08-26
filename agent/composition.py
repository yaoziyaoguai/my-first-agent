"""显式静态组合根。

只构造一个 `KernelToolRuntime`、一个 `KernelContextManager` 与一个 `AgentRuntime`。
不提供 global getter、动态 registry、ContextSource tuple 或 closeable stack：
这些分别留给真实消费者引入（Memory 定义 ContextSource、MCP 出现首个 closeable 时
扩展为 ordered close stack）。任何阶段都不得演变成 service locator 或第二套 Runtime。
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import httpx

from agent.history.catalog import HistoryCatalog
from agent.history.tools import build_history_tool_registrations
from agent.mcp.bridge import McpAsyncBridge, SessionTimeouts
from agent.mcp.catalog import McpCatalogError, build_mcp_catalog
from agent.mcp.safety import McpSafetyLatch
from agent.mcp.tools import McpExecutorConfig, build_mcp_tool_registrations
from agent.memory.contracts import ProviderTrustProfile
from agent.memory.preferences import (
    OwnerPreferenceSource,
    OwnerPreferenceStore,
    build_owner_preference_tool_registrations,
)
from agent.memory.source import MemoryContextSource
from agent.memory.store import MemoryStore
from agent.memory.tools import build_memory_tool_registrations
from agent.process.tools import build_local_process_registration
from agent.research.tools import build_research_tool_registrations
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ConversationWorkspaceBindingV1,
    ProviderDescriptor,
    canonical_json_digest,
)
from agent.runtime.control import ControlInbox
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.ports import CheckpointStore, EventSink, ModelProvider
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
from agent.skill.catalog import SkillLimits, build_skill_catalog
from agent.skill.tools import build_skill_tool_registrations
from agent.tools.file_ops import DEFAULT_PRIVATE_ROOTS, build_file_tool_registrations
from agent.tools.path_safety import WorkspaceBoundary
from agent.transport_audit import TransportAttemptRecorder
from agent.web.client import TavilyClient
from agent.web.profile import WebProfileV1
from agent.web.tools import build_web_tool_registrations


@dataclass(frozen=True, slots=True)
class Composition:
    """组合根的静态结果：三个唯一 owner。

    它是 composition root 的返回值，不进入 Runtime state、checkpoint、context 或 event。
    ``close_stack`` 是首个真实 closeable（MCP bridge）引入的有序关闭栈；teardown 时
    按倒序关闭。Order 0 之前为空。
    """

    runtime: AgentRuntime
    tool_runtime: KernelToolRuntime
    context_manager: KernelContextManager
    control_inbox: ControlInbox
    close_stack: tuple[Callable[[], None], ...] = ()
    sources: tuple = ()


@dataclass(frozen=True, slots=True)
class McpResources:
    """MCP composition 的副产品：registrations + 有序 closeables。"""

    registrations: tuple[RegisteredTool, ...]
    closeables: tuple[Callable[[], None], ...]
    latch: McpSafetyLatch


@dataclass(frozen=True, slots=True)
class MemoryResources:
    """Memory composition 的副产品：source + registrations。"""

    source: object
    registrations: tuple[RegisteredTool, ...]


@dataclass(frozen=True, slots=True)
class WebResources:
    """固定 Tavily client 的 registrations 与有序 closeables。"""

    registrations: tuple[RegisteredTool, ...]
    closeables: tuple[Callable[[], None], ...]
    readiness: WebReadiness
    credential_env: str | None = None


class WebReadiness(StrEnum):
    """只描述本地配置就绪度；启动时不做网络健康检查。"""

    NOT_ENABLED = "not_enabled"
    READY = "ready"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"


def build_web_resources(
    profile: WebProfileV1 | None,
    *,
    credential: str | None,
    http_client: httpx.Client | None = None,
    clock: Callable[[], str] | None = None,
    attempt_recorder: TransportAttemptRecorder | None = None,
) -> WebResources:
    """未配置时显式关闭；配置后 key 只进入 client 内存。"""
    if profile is None:
        if credential is not None:
            raise ValueError("Web credential cannot be supplied without a profile")
        return WebResources((), (), WebReadiness.NOT_ENABLED)
    if not credential:
        return WebResources(
            (),
            (),
            WebReadiness.TEMPORARILY_UNAVAILABLE,
            credential_env=profile.credential_env,
        )
    client = TavilyClient(
        profile,
        api_key=credential,
        http_client=http_client,
        attempt_recorder=attempt_recorder,
    )
    observed_at = clock or (
        lambda: datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    return WebResources(
        registrations=build_web_tool_registrations(
            client,
            profile,
            clock=observed_at,
        ),
        closeables=(client.close,) if client.owns_client else (),
        readiness=WebReadiness.READY,
        credential_env=profile.credential_env,
    )


def build_mcp_resources(
    catalog_config: dict[str, object],
    safety_state: Path,
    *,
    env_provider: Callable[[tuple[str, ...]], dict[str, str]],
    composition_epoch: str | None = None,
    timeouts: SessionTimeouts | None = None,
) -> McpResources:
    """构建 MCP registrations + bridge/latch。latch 若处于 unresolved ARMED，fail closed。"""
    latch = McpSafetyLatch(safety_state)
    latch.require_clear_for_composition()
    catalog = build_mcp_catalog(catalog_config)
    bridge = McpAsyncBridge(total_timeout_seconds=60.0)
    config = McpExecutorConfig(
        bridge=bridge,
        latch=latch,
        composition_epoch=composition_epoch or secrets.token_hex(8),
        timeouts=timeouts or SessionTimeouts(),
        env_provider=env_provider,
    )
    registrations = build_mcp_tool_registrations(catalog, executor_config=config)
    return McpResources(
        registrations=registrations,
        closeables=(bridge.close,),
        latch=latch,
    )


def load_mcp_catalog_file(path: Path) -> dict[str, object]:
    """读取显式 MCP catalog JSON。credential value 不会进入运行时；错误不泄露路径。"""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        raw = b""
        while True:
            chunk = os.read(fd, 65_536)
            if not chunk:
                break
            raw += chunk
            if len(raw) > 1_000_000:
                raise McpCatalogError("mcp catalog exceeds the size limit")
    finally:
        os.close(fd)
    try:
        config = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise McpCatalogError("mcp catalog must be valid JSON") from error
    if not isinstance(config, dict):
        raise McpCatalogError("mcp catalog must be a JSON object")
    return config


def build_composition(
    *,
    provider: ModelProvider,
    checkpoint_store: CheckpointStore,
    tool_registrations: tuple[RegisteredTool, ...],
    event_sink: EventSink,
    system_policy: str,
    context_limits: ContextLimits,
    invocation_limits: InvocationLimits,
    closeables: tuple[Callable[[], None], ...] = (),
    sources: tuple = (),
    workspace_identity_digest: str = "",
    context_scope_digest: str = "",
    provider_descriptor: ProviderDescriptor | None = None,
    control_inbox: ControlInbox | None = None,
    strict_control_schema: bool = False,
    workspace_binding: ConversationWorkspaceBindingV1 | None = None,
) -> Composition:
    if workspace_binding is not None and (
        workspace_binding.workspace_identity_digest != workspace_identity_digest
        or workspace_binding.workspace_scope_digest != context_scope_digest
    ):
        raise ValueError("composition workspace binding does not match its identity inputs")
    control_inbox = control_inbox or ControlInbox()
    tool_runtime = KernelToolRuntime(tool_registrations)
    definitions = tool_runtime.definitions()
    authority_snapshot = canonical_json_digest(
        {
            "version": "fixed-composition-v1",
            "workspace_identity_digest": workspace_identity_digest,
            "provider_descriptor_digest": (
                provider_descriptor.identity_digest
                if provider_descriptor is not None
                else "local-unbound"
            ),
            "tools": [
                {
                    "name": definition.name,
                    "input_schema": definition.input_schema,
                    "side_effect": definition.side_effect.value,
                    "egress": definition.egress.value,
                    "execution_authority": definition.execution_authority.value,
                }
                for definition in definitions
            ],
        }
    )
    context_manager = KernelContextManager(
        system_policy=system_policy,
        limits=context_limits,
        sources=sources,
        workspace_identity_digest=workspace_identity_digest,
        context_scope_digest=context_scope_digest,
        authority_snapshot=authority_snapshot,
        strict_control_schema=strict_control_schema,
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=context_manager,
        tool_runtime=tool_runtime,
        checkpoint_store=checkpoint_store,
        event_sink=event_sink,
        limits=invocation_limits,
        provider_descriptor=provider_descriptor,
        control_inbox=control_inbox,
        workspace_binding=workspace_binding,
    )
    return Composition(
        runtime=runtime,
        tool_runtime=tool_runtime,
        context_manager=context_manager,
        control_inbox=control_inbox,
        close_stack=closeables,
        sources=sources,
    )


def build_memory_resources(
    store: MemoryStore,
    *,
    workspace_scope_digest: str,
) -> MemoryResources:
    """从已 create/load 的 store 构建 Memory source + governed tool registrations。"""
    source = MemoryContextSource(store)
    registrations = build_memory_tool_registrations(
        store, workspace_scope_digest=workspace_scope_digest
    )
    return MemoryResources(source=source, registrations=registrations)


def build_owner_preference_resources(
    path: Path,
    *,
    provider_trust_digest: str,
) -> MemoryResources:
    """打开固定 owner store；profile 漂移必须 fail closed，不能另建旁路 store。"""

    if path.exists():
        store = OwnerPreferenceStore.load(
            path,
            provider_trust_digest=provider_trust_digest,
        )
    else:
        store = OwnerPreferenceStore.create(
            path,
            provider_trust_digest=provider_trust_digest,
        )
    return MemoryResources(
        source=OwnerPreferenceSource(store),
        registrations=build_owner_preference_tool_registrations(store),
    )


def workspace_scope_digest_for(workspace: Path) -> str:
    from agent.continuity.identity import WorkspaceIdentityV1

    return WorkspaceIdentityV1.resolve(workspace).scope_digest


def provider_trust_profile(
    *, profile_id: str, provider_family: str, destination: str
) -> ProviderTrustProfile:
    return ProviderTrustProfile(profile_id, provider_family, destination)


def build_tool_registrations(
    *,
    workspace: Path,
    skill_roots: Sequence[Path] = (),
    protected_paths: tuple[Path, ...] = (),
    private_roots: tuple[str, ...] = DEFAULT_PRIVATE_ROOTS,
    max_tool_result_chars: int,
    skill_limits: SkillLimits | None = None,
    history_catalog: HistoryCatalog | None = None,
    captured_path: str | None = None,
) -> tuple[RegisteredTool, ...]:
    """显式拼接当前真实消费者需要的 tool registrations。

    没配置 skill root 时只返回文件工具；配置了才构建 catalog（懒加载 PyYAML），
    并把 skill activation/resource registrations 拼到同一 tuple。最终由
    ``build_composition`` 装进唯一 ``KernelToolRuntime``。
    """
    if max_tool_result_chars < 1:
        raise ValueError("max_tool_result_chars must be positive")
    registrations: list[RegisteredTool] = list(
        build_file_tool_registrations(
            workspace,
            protected_paths=protected_paths,
            private_roots=private_roots,
        )
    )
    registrations.extend(build_research_tool_registrations())
    if history_catalog is not None:
        registrations.extend(build_history_tool_registrations(history_catalog))
    if skill_roots:
        catalog = build_skill_catalog(skill_roots, limits=skill_limits)
        registrations.extend(
            build_skill_tool_registrations(
                catalog, max_tool_result_chars=max_tool_result_chars
            )
        )
    # 015 governed local action：仅在支持 POSIX process lifecycle 的平台静态注册
    # local_process（默认可发现、默认无执行权）。未支持平台不注册，不 shell fallback。
    if _posix_process_lifecycle_available():
        process_boundary = WorkspaceBoundary(
            workspace,
            protected_paths=protected_paths,
            private_roots=private_roots,
        )
        registrations.append(
            build_local_process_registration(
                workspace=workspace,
                captured_path=captured_path or os.environ.get("PATH", ""),
                workspace_boundary=process_boundary,
            )
        )
    return tuple(registrations)


def _posix_process_lifecycle_available() -> bool:
    """仅当平台提供 bounded POSIX process-group lifecycle（killpg/setsid/no-follow）时注册。"""

    return all(hasattr(os, attr) for attr in ("killpg", "setsid", "O_NOFOLLOW"))
