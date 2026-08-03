"""`first-agent` 的最小组合根；业务语义全部由 Runtime Kernel 拥有。"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from agent.cli.app import run_repl
from agent.cli.render import TerminalRenderer
from agent.composition import (
    build_composition,
    build_mcp_resources,
    build_memory_resources,
    build_owner_preference_resources,
    build_tool_registrations,
    load_mcp_catalog_file,
    provider_trust_profile,
    workspace_scope_digest_for,
)
from agent.continuity.restart import project_restart
from agent.continuity.sessions import StartupDisposition, open_workspace_session
from agent.mcp.catalog import McpCatalogError
from agent.memory.store import MemoryStore, MemoryStoreError
from agent.provider.config import AgentProviderConfig
from agent.provider.factory import build_model_provider
from agent.provider.fake_provider import FakeProvider
from agent.provider.protocol import ProviderError
from agent.runtime.checkpoint import CheckpointError
from agent.runtime.context import ContextLimits
from agent.runtime.loop import InvocationLimits
from agent.scheduler.caller import ScheduledOccurrenceCaller, create_or_load_occurrence_store
from agent.scheduler.contracts import ScheduledOccurrence, SchedulerError
from agent.skill.catalog import SkillCatalogError
from agent.subagent.contracts import ChildProfile
from agent.subagent.runner import ChildAgentRunner
from agent.subagent.tools import build_subagent_tool_registrations
from agent.tools.file_ops import DEFAULT_PRIVATE_ROOTS
from agent.tui.adapter import QueueingEventSink


def build_parser() -> argparse.ArgumentParser:
    # allow_abbrev=False：--state/--resume 已按 012 合同移除；禁止 argparse 前缀缩写
    # 把 --state 静默复活为 --state-root 的兼容别名。
    parser = argparse.ArgumentParser(prog="first-agent", allow_abbrev=False)
    parser.add_argument(
        "--state-root",
        type=Path,
        help="override the owner-only product state root",
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument(
        "--provider",
        choices=("fake", "anthropic_compatible", "openai_compatible"),
        default="fake",
    )
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--credential-env", default="FIRST_AGENT_API_KEY")
    parser.add_argument(
        "--thinking-mode",
        choices=("disabled",),
        help="explicitly disable provider-specific opaque thinking continuity",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--skill-root",
        action="append",
        default=[],
        type=Path,
        help="explicit trusted Skill root directory (repeatable)",
    )
    parser.add_argument(
        "--mcp-catalog",
        type=Path,
        help="explicit operator-approved MCP stdio catalog JSON",
    )
    parser.add_argument(
        "--mcp-safety-state",
        type=Path,
        help="owner-only durable MCP safety latch state path",
    )
    memory = parser.add_mutually_exclusive_group()
    memory.add_argument(
        "--memory-create",
        type=Path,
        help="exclusively create a new workspace Memory store",
    )
    memory.add_argument(
        "--memory-store",
        type=Path,
        help="load an existing workspace Memory store",
    )
    parser.add_argument(
        "--memory-profile",
        default="default",
        help="non-secret provider trust profile id bound to the Memory store",
    )
    parser.add_argument(
        "--subagent",
        action="store_true",
        help="enable the bounded subagent__delegate tool using the same provider",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="launch the optional Textual TUI instead of the plain REPL",
    )
    return parser


def _build_child_profile(args, workspace_scope_digest: str) -> ChildProfile:
    import hashlib

    max_input = 4_000
    max_output = 1_000
    # child hard deadline：一次有限时 provider call（≤ args.timeout）加有界本地处理余量。
    # 进程隔离路径以此为 wall-clock cap；同步路径用它校验 provider deadline 不超 child cap。
    hard_deadline_seconds = args.timeout + 10.0
    limits_digest = hashlib.sha256(
        f"{max_input}:{max_output}:{hard_deadline_seconds}".encode()
    ).hexdigest()
    return ChildProfile(
        runner_version="subagent-v1",
        provider_profile_id=args.memory_profile,
        provider_destination=args.base_url or "local",
        workspace_scope_digest=workspace_scope_digest,
        max_input_tokens=max_input,
        max_output_tokens=max_output,
        limits_digest=limits_digest,
        hard_deadline_seconds=hard_deadline_seconds,
    )


def _open_memory_store(args, workspace):
    scope = workspace_scope_digest_for(workspace)
    destination = args.base_url or "local"
    profile = provider_trust_profile(
        profile_id=args.memory_profile,
        provider_family=args.provider,
        destination=destination,
    )
    selected = args.memory_create or args.memory_store
    if selected is None:
        return None, scope
    resolved = selected.resolve(strict=False)
    if resolved == workspace or resolved.is_relative_to(workspace):
        raise ValueError("memory store must remain outside the tool workspace")
    if args.memory_create is not None:
        return (
            MemoryStore.create(resolved, workspace_scope_digest=scope, profile=profile),
            scope,
        )
    return (
        MemoryStore.load(resolved, workspace_scope_digest=scope, profile=profile),
        scope,
    )


def _mcp_env_provider(forwarded):
    # catalog 的 env_names 就是 operator 批准的转发 allowlist；只转发存在的项。
    return {name: os.environ[name] for name in forwarded if name in os.environ}


def _build_provider(args: argparse.Namespace):
    if args.provider == "fake":
        return FakeProvider()
    if not args.model or not args.base_url:
        raise ValueError("real HTTP providers require --model and --base-url")
    credential = os.environ.get(args.credential_env)
    if not credential:
        raise ValueError(f"credential environment variable is not set: {args.credential_env}")
    return build_model_provider(
        AgentProviderConfig(
            provider_type=args.provider,
            model=args.model,
            base_url=args.base_url,
            credential=credential,
            timeout=args.timeout,
            thinking_mode=args.thinking_mode,
        )
    )


def _build_provider_descriptor(args: argparse.Namespace):
    if args.provider == "fake":
        return AgentProviderConfig(provider_type="fake").descriptor()
    if not args.model or not args.base_url:
        raise ValueError("real HTTP providers require --model and --base-url")
    return AgentProviderConfig(
        provider_type=args.provider,
        model=args.model,
        base_url=args.base_url,
        timeout=args.timeout,
    ).descriptor()


def main(
    argv: Sequence[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    write_fn: Callable[[str], None] = print,
) -> int:
    args = build_parser().parse_args(argv)
    # 唯一 close-stack owner：stdlib ExitStack。所有退出路径（正常、startup 失败、
    # optional-dependency 失败、runtime 异常）都按注册逆序各关闭一次。
    with contextlib.ExitStack() as close_stack:
        try:
            workspace = args.workspace.resolve(strict=True)
            if not workspace.is_dir():
                raise ValueError("workspace must be a directory")
            session = open_workspace_session(
                workspace,
                state_root=args.state_root,
            )
            projection = project_restart(session)
            if session.disposition is StartupDisposition.SELECT_REQUIRED:
                for candidate in session.candidates:
                    write_fn(
                        "Goal candidate: "
                        f"{candidate.goal_id or '(conversation)'} "
                        f"[{candidate.conversation_id}]"
                    )
                write_fn("Startup requires an exact SelectGoal action.")
                return 2
            if session.disposition is StartupDisposition.NEEDS_AUTHORITY:
                write_fn("Startup stopped: workspace or authority binding drifted.")
                return 2
            if session.store is None or session.checkpoint_path is None:
                raise ValueError("startup did not select a checkpoint")
            store = session.store
            protected_paths = (session.checkpoint_path,)
            if projection.goal_id is not None:
                write_fn(
                    f"Goal {projection.goal_id} [{projection.goal_status.value}]: "
                    f"{projection.user_outcome}"
                )
            if session.disposition is StartupDisposition.RECOVERY_REQUIRED:
                write_fn("Recovery required before the previous effect can continue.")
            skill_roots = tuple(
                root.resolve(strict=True) for root in (args.skill_root or ())
            )
            renderer = TerminalRenderer(write_fn)
            context_limits = ContextLimits(max_input_tokens=100_000, output_reserve=8_000)
            registrations = list(
                build_tool_registrations(
                    workspace=workspace,
                    skill_roots=skill_roots,
                    protected_paths=protected_paths,
                    private_roots=DEFAULT_PRIVATE_ROOTS,
                    max_tool_result_chars=context_limits.max_tool_result_chars,
                )
            )
            closeables: list[Callable[[], None]] = []
            sources: list = []
            workspace_scope_digest = workspace_scope_digest_for(workspace)
            provider_descriptor = _build_provider_descriptor(args)
            preference_resources = build_owner_preference_resources(
                session.state_root / "owner-preferences.json",
                provider_trust_digest=provider_descriptor.identity_digest,
            )
            registrations.extend(preference_resources.registrations)
            sources.append(preference_resources.source)
            if (args.mcp_catalog is None) != (args.mcp_safety_state is None):
                raise ValueError("--mcp-catalog and --mcp-safety-state must be used together")
            if args.mcp_catalog is not None:
                mcp_resources = build_mcp_resources(
                    load_mcp_catalog_file(args.mcp_catalog.resolve(strict=True)),
                    # safety latch 由首次 invocation 惰性创建（文件缺失即 clear），
                    # 不得要求 composition 时已存在——与 memory store 一样用 strict=False。
                    args.mcp_safety_state.resolve(strict=False),
                    env_provider=_mcp_env_provider,
                )
                registrations.extend(mcp_resources.registrations)
                closeables.extend(mcp_resources.closeables)
                # 立即注册进 close-stack：即使后续 startup 步骤失败也会逆序关闭。
                for closeable in mcp_resources.closeables:
                    close_stack.callback(closeable)
            memory_store, memory_scope = _open_memory_store(args, workspace)
            if memory_store is not None:
                workspace_scope_digest = memory_scope
                memory_resources = build_memory_resources(
                    memory_store, workspace_scope_digest=workspace_scope_digest
                )
                registrations.extend(memory_resources.registrations)
                sources.append(memory_resources.source)
            provider = _build_provider(args)
            if args.subagent:
                from agent.subagent.contracts import (
                    ChildProviderSpec,
                    ProviderDeadlineCapability,
                )

                cap = ProviderDeadlineCapability.from_provider(provider)
                if cap is not None and cap.receipt_type == "synchronous":
                    # provider 结构化保证 generate 同步返回（如本地确定性 provider）→
                    # in-process runner，synchronous receipt。
                    runner = ChildAgentRunner(
                        provider=provider,
                        profile=_build_child_profile(args, workspace_scope_digest),
                    )
                else:
                    # production HTTP provider 无 synchronous deadline_contract；socket
                    # timeout 不能证明 provider 已终止，故走进程隔离 hard-deadline 路径：
                    # child 在独立进程运行同一个 AgentRuntime，parent 拥有 process group 并
                    # 在 hard_deadline 后 killpg + 确认退出。credential 仅按 env name 在子进程
                    # 内读取，不跨进程序列化。
                    from agent.subagent.process_runner import ChildProcessRunner

                    if args.provider != "fake" and (not args.model or not args.base_url):
                        raise ValueError(
                            "SubAgent over HTTP requires --model and --base-url"
                        )
                    spec = ChildProviderSpec(
                        kind="http",
                        provider_type=args.provider,
                        model=args.model or "fake",
                        base_url=args.base_url,
                        credential_env_name=args.credential_env,
                        timeout=args.timeout,
                        thinking_mode=args.thinking_mode,
                    )
                    runner = ChildProcessRunner(
                        provider_spec=spec,
                        profile=_build_child_profile(args, workspace_scope_digest),
                    )
                registrations.extend(build_subagent_tool_registrations(runner))
            # TUI 与 Runtime 共享同一个 QueueingEventSink；terminal renderer 不作
            # runtime sink，故 model/tool progress 不写入 terminal writer。
            event_sink = QueueingEventSink() if args.tui else renderer
            composition = build_composition(
                provider=provider,
                provider_descriptor=provider_descriptor,
                checkpoint_store=store,
                tool_registrations=tuple(registrations),
                event_sink=event_sink,
                system_policy=(
                    "You are a local task agent. Use only supplied tools, obey tool policy, "
                    "and return concise final text. File-tool paths are relative to the "
                    "selected workspace; '.' means its root. Use list_files on '.' when "
                    "resource discovery is needed. Policy-hidden paths are unavailable. "
                    "FIRST_AGENT_TRUSTED_CONTROL_CONTEXT is Runtime-generated authority: "
                    "when proposing a Goal, copy its source_fact_id, "
                    "workspace_identity_digest, and authority_snapshot exactly; propose "
                    "criteria but leave admitted_criteria empty."
                ),
                context_limits=context_limits,
                invocation_limits=InvocationLimits(),
                closeables=tuple(closeables),
                sources=tuple(sources),
                workspace_scope_digest=session.workspace_identity.identity_digest,
            )
            runtime = composition.runtime
        except (
            CheckpointError,
            OSError,
            ProviderError,
            ValueError,
            SkillCatalogError,
            McpCatalogError,
            MemoryStoreError,
        ) as error:
            write_fn(f"Startup failed: {type(error).__name__}: {error}")
            return 2

        if args.tui:
            from agent.cli.actions import run_id_factory
            from agent.tui.adapter import TuiAdapter
            from agent.tui.app import TextualNotInstalledError, run_tui

            adapter = TuiAdapter(
                runtime,
                store,
                event_sink=event_sink,
                control_inbox=composition.control_inbox,
            )
            try:
                return run_tui(adapter, run_id_factory=run_id_factory("tui-run"))
            except TextualNotInstalledError as error:
                write_fn(str(error))
                return 2
        try:
            return run_repl(
                runtime,
                store,
                input_fn=input_fn,
                write_fn=write_fn,
                renderer=renderer,
            )
        except (CheckpointError, OSError) as error:
            write_fn(f"Runtime state failed: {type(error).__name__}")
            return 2


def build_schedule_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="first-agent-schedule")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument(
        "--state-root",
        type=Path,
        required=True,
        help="scheduler state root outside workspace",
    )
    parser.add_argument("--schedule-id", required=True)
    parser.add_argument("--occurrence-id", required=True)
    parser.add_argument("--scheduled-for", required=True, help="canonical UTC time ...Z")
    parser.add_argument("--message", required=True)
    parser.add_argument(
        "--provider",
        choices=("fake", "anthropic_compatible", "openai_compatible"),
        default="fake",
    )
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--credential-env", default="FIRST_AGENT_API_KEY")
    parser.add_argument(
        "--thinking-mode",
        choices=("disabled",),
        help="explicitly disable provider-specific opaque thinking continuity",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def run_schedule(
    argv: Sequence[str] | None = None,
    *,
    write_fn: Callable[[str], None] = print,
) -> int:
    args = build_schedule_parser().parse_args(argv)
    # 唯一 close-stack owner：与 main() 同一模式，逆序关闭一次。
    with contextlib.ExitStack() as close_stack:
        try:
            workspace = args.workspace.resolve(strict=True)
            if not workspace.is_dir():
                raise ValueError("workspace must be a directory")
            # state-root 在首次触发时可能尚不存在；由 checkpoint
            # store 在 initialize 时创建并锁定为 0700 owner-only。overlap guard 必须在任何
            # 创建之前用非严格 resolve 完成：一个尚不存在但词法上落在 workspace 内的路径
            # 也要被拒绝，不能等到创建后才发现。已存在的目录仍须自身是 0700 owner 目录，
            # 否则 store fail closed。
            state_root = args.state_root.resolve(strict=False)
            if state_root == workspace or state_root.is_relative_to(workspace):
                raise ValueError("scheduler state root must remain outside the tool workspace")
            occurrence = ScheduledOccurrence(
                schedule_id=args.schedule_id,
                occurrence_id=args.occurrence_id,
                scheduled_for_utc=args.scheduled_for,
                message=args.message,
                workspace_scope_digest=workspace_scope_digest_for(workspace),
            )
            store, snapshot = create_or_load_occurrence_store(occurrence, state_root=state_root)
            context_limits = ContextLimits(max_input_tokens=100_000, output_reserve=8_000)
            composition = build_composition(
                provider=_build_provider(args),
                provider_descriptor=_build_provider_descriptor(args),
                checkpoint_store=store,
                tool_registrations=build_tool_registrations(
                    workspace=workspace,
                    protected_paths=(),
                    private_roots=DEFAULT_PRIVATE_ROOTS,
                    max_tool_result_chars=context_limits.max_tool_result_chars,
                ),
                event_sink=TerminalRenderer(write_fn),
                system_policy="You are a scheduled task agent. Return concise final text.",
                context_limits=context_limits,
                invocation_limits=InvocationLimits(),
                workspace_scope_digest=occurrence.workspace_scope_digest,
            )
            for closeable in reversed(composition.close_stack):
                close_stack.callback(closeable)
            report = ScheduledOccurrenceCaller(
                composition.runtime, store, snapshot, occurrence
            ).run_once()
        except (CheckpointError, OSError, ProviderError, ValueError, SchedulerError) as error:
            write_fn(f"Schedule failed: {type(error).__name__}: {error}")
            return 2
        write_fn(report.to_json())
        if report.occurrence_status == "completed":
            return 0
        if report.occurrence_status == "needs_human":
            return 1
        return 2


if __name__ == "__main__":
    sys.exit(main())
