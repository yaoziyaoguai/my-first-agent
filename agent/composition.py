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
from pathlib import Path

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
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import ProviderDescriptor, canonical_json_digest
from agent.runtime.control import ControlInbox
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.ports import CheckpointStore, EventSink, ModelProvider
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
from agent.skill.catalog import SkillLimits, build_skill_catalog
from agent.skill.tools import build_skill_tool_registrations
from agent.tools.file_ops import DEFAULT_PRIVATE_ROOTS, build_file_tool_registrations


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
    workspace_scope_digest: str = "",
    provider_descriptor: ProviderDescriptor | None = None,
    control_inbox: ControlInbox | None = None,
) -> Composition:
    control_inbox = control_inbox or ControlInbox()
    tool_runtime = KernelToolRuntime(tool_registrations)
    definitions = tool_runtime.definitions()
    authority_snapshot = canonical_json_digest(
        {
            "version": "fixed-composition-v1",
            "workspace_identity_digest": workspace_scope_digest,
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
                }
                for definition in definitions
            ],
        }
    )
    context_manager = KernelContextManager(
        system_policy=system_policy,
        limits=context_limits,
        sources=sources,
        workspace_scope_digest=workspace_scope_digest,
        authority_snapshot=authority_snapshot,
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
    import hashlib

    return hashlib.sha256(str(workspace).encode("utf-8")).hexdigest()


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
    if skill_roots:
        catalog = build_skill_catalog(skill_roots, limits=skill_limits)
        registrations.extend(
            build_skill_tool_registrations(
                catalog, max_tool_result_chars=max_tool_result_chars
            )
        )
    return tuple(registrations)
