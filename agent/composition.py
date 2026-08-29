"""显式静态组合根。

只构造一个 `KernelToolRuntime`、一个 `KernelContextManager` 与一个 `AgentRuntime`。
不提供 global getter 或动态 registry。`ContextSource` tuple 与 ordered closeable
stack 是 composition root 已有的显式静态组合点：sources 由 composition root 注入
`KernelContextManager`，source 的调用、排序、预算与投影仅由后者拥有；closeables
仅由 lifecycle owner 在 teardown 时按逆序关闭。二者都不是 capability 可在运行时
查询、调用或绕过既有 owner 的 registry。任何阶段都不得演变成 service locator、动态
capability registry 或第二套 Runtime。
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

from agent.browser.playwright_adapter import SocketAddressResolver
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
    BackgroundExecutionAuthorityV1,
    BrowserTakeoverRequestV1,
    ConversationWorkspaceBindingV1,
    ProviderDescriptor,
    canonical_json_digest,
)
from agent.runtime.control import ControlInbox
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.ports import (
    BackgroundClaimVerifier,
    CheckpointStore,
    EventSink,
    ModelProvider,
)
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

class SandboxReadiness(StrEnum):
    """native sandbox backend 的本地就绪度（只读 qualification 探测）。"""

    UNSUPPORTED = "unsupported"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class SandboxResources:
    """native sandbox composition 的副产品：唯一 registration + 就绪度。

    无 closeables/receipt book——native 执行没有长生命周期 session，清理由
    executor 的 per-invocation temp 与既有 process owner 拥有；receipt 由
    Runtime 在 invoke 内铸造（不经 composition 的旁路 book）。
    """

    registrations: tuple[RegisteredTool, ...]
    readiness: SandboxReadiness
    reason_code: str | None = None


def build_sandbox_resources(
    workspace,
    state_root,
    captured_path: str,
    *,
    confiner=None,
):  # noqa: ANN001, ANN202
    """native sandbox 的静态组合：自动 qualification + 唯一 sandbox_exec。

    无论 backend 是否可用都注册同一个 ``sandbox_exec``——danger-full-access
    是不依赖 backend 的显式 unconfined bypass；confined 命令在 confine 处
    fail closed（spec §2/§4）。没有 local_process fallback、没有 Docker
    vocabulary。per-invocation temp/home 基座放在系统 temp 下的 session
    专属目录（policy 冻结四 root 两两不交，temp/home 不得位于 state_root
    的 unreadable carveout 内）。
    """

    import hashlib
    import tempfile as _tempfile

    from agent.sandbox.seatbelt import SeatbeltConfiner
    from agent.sandbox.tools import build_sandbox_exec_registration

    resolved_confiner = confiner or SeatbeltConfiner()
    report = resolved_confiner.qualify()
    state_root_path = Path(state_root)
    base = (
        Path(_tempfile.gettempdir())
        / (
            "first-agent-sbx-"
            + hashlib.sha256(str(state_root_path).encode()).hexdigest()[:12]
        )
    )
    temp_root = base / "temp"
    home_root = base / "home"
    temp_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    home_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    registration = build_sandbox_exec_registration(
        workspace=workspace,
        temp_root=temp_root,
        state_root=state_root_path,
        home=home_root,
        captured_path=captured_path,
        confiner=resolved_confiner,
    )
    if report.reason_code == "unsupported_platform":
        readiness = SandboxReadiness.UNSUPPORTED
    elif report.available:
        readiness = SandboxReadiness.READY
    else:
        readiness = SandboxReadiness.TEMPORARILY_UNAVAILABLE
    return SandboxResources(
        registrations=(registration,),
        readiness=readiness,
        reason_code=None if report.available else report.reason_code,
    )


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
    sandbox_receipt_book=None,
    browser_takeover_complete: Callable[[object], int] | None = None,
    background_claim_verifier: BackgroundClaimVerifier | None = None,
    background_execution_authority: BackgroundExecutionAuthorityV1 | None = None,
    tool_clock: Callable[[], str] | None = None,
) -> Composition:
    if workspace_binding is not None and (
        workspace_binding.workspace_identity_digest != workspace_identity_digest
        or workspace_binding.workspace_scope_digest != context_scope_digest
    ):
        raise ValueError("composition workspace binding does not match its identity inputs")
    control_inbox = control_inbox or ControlInbox()
    tool_runtime = KernelToolRuntime(
        tool_registrations,
        clock=tool_clock,
        sandbox_receipt_book=sandbox_receipt_book,
        background_claim_verifier=background_claim_verifier,
    )
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
        browser_takeover_complete=browser_takeover_complete,
        background_execution_authority=background_execution_authority,
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


# --------------------------------------------------------------------------- #
# 018 governed browser tasks：optional composition（spec §11）
# --------------------------------------------------------------------------- #


class BrowserReadiness(StrEnum):
    """browser 资源的 closed 就绪度；不可用只给一条 reason。"""

    NOT_ENABLED = "not_enabled"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class BrowserResources:
    """browser composition 的副产品：registrations + 有序 closeables。

    closeables 按构造逆序关闭（后构造先关）；不可用时 registrations 为空，
    绝不 fallback 到系统 Chrome/Safari/CDP。只额外暴露一个 Runtime 注入的
    typed takeover completion port，不暴露 environment/store owner。
    """

    registrations: tuple[RegisteredTool, ...]
    closeables: tuple[Callable[[], None], ...]
    readiness: BrowserReadiness
    reason_code: str | None = None
    complete_takeover: Callable[[BrowserTakeoverRequestV1], int] | None = None


def browser_identity_digest_for_state_root(state_root: Path) -> str:
    """专属 browser installation identity；profile 创建与 composition 必须同源。"""

    import hashlib

    return hashlib.sha256(
        f"first-agent-browser:{Path(state_root)}".encode()
    ).hexdigest()


def _default_browser_binary_available() -> bool:
    """production read-only binary qualification：不启动 browser、不下载。

    Playwright 的 driver lifecycle 隔离在短子进程中，避免仅查询
    ``executable_path`` 时的异步收尾噪声污染产品进程；任何缺失、超时或
    非零退出都视为不可用（fail closed，无 fallback）。
    """

    import subprocess as _subprocess
    import sys as _sys

    try:
        probe = _subprocess.run(
            [
                _sys.executable,
                "-c",
                (
                    "from playwright.sync_api import sync_playwright; "
                    "p=sync_playwright().start(); "
                    "print(p.chromium.executable_path); p.stop()"
                ),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, _subprocess.SubprocessError):
        return False
    if probe.returncode != 0:
        return False
    import os as _os

    executable = probe.stdout.strip()
    return bool(executable) and _os.path.exists(executable)


def _default_browser_egress_ready(resolver: object) -> bool:
    """production read-only egress qualification：构造 guard 即 ready。

    guard 无 permissive 开关；resolver 构造成功（无异常）即代表 DNS 解析
    通道可用。不发起任何网络请求。
    """

    return resolver is not None


def _browser_qualification_reasons(
    *,
    playwright_factory: object | None,
    profile_root: Path,
    binary_available: bool,
    egress_ok: bool,
) -> str | None:
    """read-only closed qualification：按优先级返回唯一 reason 或 None。

    顺序：package → profile permissions → bundled binary → egress。
    绝不启动或下载 browser，绝不 fallback。
    """

    import os as _os
    import stat as _stat

    if playwright_factory is None:
        try:
            import playwright.sync_api  # noqa: F401  lazy，base 启动不加载
        except ImportError:
            return "browser_package_missing"
    try:
        info = _os.lstat(profile_root)
    except FileNotFoundError:
        info = None
    if info is not None:
        if _stat.S_ISLNK(info.st_mode) or not _stat.S_ISDIR(info.st_mode):
            return "browser_profile_permissions"
        if info.st_mode & 0o077:
            # owner-only 合同被破坏且非我们创建的 root：read-only 检查不改
            # 权限，直接 fail closed（我们自己创建的 0700 root 不受影响）。
            return "browser_profile_permissions"
    if not binary_available:
        return "browser_binary_missing"
    if not egress_ok:
        return "browser_egress_unavailable"
    return None


# 模块级私有 qualification seam：production 默认为真实只读探测；测试经
# monkeypatch 注入确定布尔。不在公开签名暴露任何测试旋钮。
def _browser_binary_available_for_factory() -> bool:
    """注入 playwright_factory 的调用也走同一 binary 判据。

    默认真实只读探测（本机无 playwright 包时返回 False）；测试 monkeypatch
    本函数注入确定布尔，不改变 production qualification 语义。
    """

    return _default_browser_binary_available()


_BROWSER_EGRESS_SEAM: Callable[[object], bool] = _default_browser_egress_ready


def build_browser_resources(
    workspace: Path,
    state_root: Path,
    *,
    enabled: bool,
    resolver: object | None = None,
    playwright_factory: object | None = None,
) -> BrowserResources:
    """browser 静态组合：read-only qualification 后构造唯一 adapter 拥有的资源。

    production 调用不传 resolver/playwright_factory（使用真实 DNS 与 lazy
    Playwright）；测试只能经这两个 constructor seam 注入 fake。签名不含
    allow_private/disable_guard/binary/egress 测试旋钮——binary/egress
    qualification 是真实只读探测，注入只经模块级私有 seam
    （``_BROWSER_BINARY_SEAM``/``_BROWSER_EGRESS_SEAM``，测试 monkeypatch）。
    """

    if not enabled:
        return BrowserResources(
            registrations=(),
            closeables=(),
            readiness=BrowserReadiness.NOT_ENABLED,
            reason_code=None,
            complete_takeover=None,
        )
    profile_root = Path(state_root) / "browser" / "profiles"
    session_root = Path(state_root) / "browser" / "sessions"
    resolved_resolver = (
        resolver
        if resolver is not None
        else SocketAddressResolver()
    )
    binary_available = (
        _browser_binary_available_for_factory()
        if playwright_factory is not None
        else _default_browser_binary_available()
    )
    egress_ok = _BROWSER_EGRESS_SEAM(resolved_resolver)
    reason = _browser_qualification_reasons(
        playwright_factory=playwright_factory,
        profile_root=profile_root,
        binary_available=binary_available,
        egress_ok=egress_ok,
    )
    if reason is not None:
        return BrowserResources(
            registrations=(),
            closeables=(),
            readiness=BrowserReadiness.TEMPORARILY_UNAVAILABLE,
            reason_code=reason,
            complete_takeover=None,
        )
    import time as _time

    from agent.browser.playwright_adapter import (
        PlaywrightBrowserEnvironment,
    )
    from agent.browser.profile_store import BrowserProfileStore
    from agent.browser.quarantine import BrowserQuarantine
    from agent.browser.session_store import BrowserSessionStore
    from agent.browser.takeover import complete_browser_takeover_profile
    from agent.browser.tools import build_browser_tool_registrations

    profile_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    session_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    browser_identity_digest = browser_identity_digest_for_state_root(Path(state_root))
    quarantine_root = Path(state_root) / "browser" / "quarantine"
    quarantine = BrowserQuarantine(root=quarantine_root)
    environment = PlaywrightBrowserEnvironment(
        playwright_factory=playwright_factory,  # type: ignore[arg-type]
        resolver=resolved_resolver,
        browser_identity_digest=browser_identity_digest,
        profile_root=profile_root,
        quarantine=quarantine,
    )
    profile_store = BrowserProfileStore(root=profile_root)
    registrations = build_browser_tool_registrations(
        environment=environment,
        profile_store=profile_store,
        session_store=BrowserSessionStore(root=session_root),
        browser_identity_digest=browser_identity_digest,
        clock=lambda: datetime.now(UTC).isoformat(),
        monotonic_clock=_time.monotonic,
        workspace=Path(workspace),
        quarantine=quarantine,
    )
    closeables: tuple[Callable[[], None], ...] = (environment.shutdown,)
    return BrowserResources(
        registrations=registrations,
        closeables=closeables,
        readiness=BrowserReadiness.READY,
        reason_code=None,
        complete_takeover=lambda request: complete_browser_takeover_profile(
            request,
            profile_store,
            browser_identity_digest=browser_identity_digest,
            session_is_active=environment.takeover_session_active,
        ),
    )
