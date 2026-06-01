"""程序入口：输入循环 + 调用 session 模块。"""
import contextlib
import io
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.checkpoint import load_checkpoint
from agent.cli.commands import dispatch_maintenance_command
from agent.cli.display import (
    _forward_runtime_event_to_legacy_callbacks,
    _merge_chat_outputs,
    _render_runtime_event_for_simple_cli,
    _textual_stdout_fallback_output,
)
from agent.cli.input_backends import (
    INPUT_BACKEND_ENV,  # noqa: F401 - 保持 main.INPUT_BACKEND_ENV 兼容测试/旧入口
    _selected_input_backend,
    read_user_input,  # noqa: F401 - main.read_user_input 是既有 public seam
    read_user_input_event,
)
from agent.cli_renderer import render_onboarding, render_provider_mode_banner, render_status_line
from agent.core import chat, get_state
from agent.display_events import (
    EVENT_ASSISTANT_DELTA,
    DisplayEvent,
    RuntimeEvent,
    render_runtime_event_for_cli,
)
from agent.event_log import EventLogWriter
from agent.input_intents import classify_user_input
from agent.memory_review import run_pending_review_cli
from agent.session import (
    finalize_session,
    handle_double_interrupt,
    handle_interrupt_choice,
    handle_interrupt_with_checkpoint,
    handle_interrupt_without_checkpoint,
    handle_resume_choice,
    init_session,
    summarize_session_status,
    try_resume_from_checkpoint,
)
from config import load_legacy_dotenv_config

CTRL_C_DOUBLE_PRESS_WINDOW = 1.0  # 秒


def _run_textual_runtime_turn(
    user_input: str,
    *,
    on_output_chunk: Callable[[str], None] | None = None,
    on_display_event: Callable[[DisplayEvent], None] | None = None,
    on_runtime_event: Callable[[RuntimeEvent], None] | None = None,
    event_log_writer: Any = None,
) -> tuple[str, str]:
    """执行一轮 Textual 产品主路径，并返回 latest_output fallback。

    这是 TUI-first 第一刀的边界函数：Textual 是正式产品交互路径，必须优先消费
    RuntimeEvent，而不是把旧 CLI 的 print/stdout 当主语义。本阶段进一步收窄旧
    callback 补丁：这里总是以 `on_runtime_event` 调用 core.chat，再把事件集中转发给
    deprecated callback；不再把 `on_output_chunk` / `on_display_event` 直接作为
    Textual 调 Runtime 的入口。stdout capture 仍保留，是为了兼容未迁移的 print-era
    输出与旧测试；它不能继续扩大，也不能承载 RuntimeEvent 以外的输入协议、checkpoint、
    runtime_observer、conversation.messages、Anthropic API messages、TaskState 状态机、
    debug print、terminal observer log 或 simple CLI fallback 语义。

    关键边界：streaming chunk 已经进入 TUI 后，final return / stdout capture
    不能再作为第二条 Assistant 正文追加，否则长任务结束时会重复显示最后一条
    assistant 消息。这里切断的是输出写入路径，不改变 Runtime 状态推进。
    """

    captured = io.StringIO()
    runtime_event_outputs: list[str] = []
    emitted_runtime_event = False
    streamed_any_chunk = False

    def forward_runtime_event(event: RuntimeEvent) -> None:
        """记录并转发 RuntimeEvent，替代 stdout-era 输出猜测。

        main.py 只做 I/O 适配：它不解释 Runtime 状态，不写 checkpoint，也不把
        runtime_observer debug event 混进 TUI。这里保留旧 callback 转发，是为了
        让未迁移的调用方继续工作；新 Textual Shell 会直接传 on_runtime_event，
        simple CLI 也使用 RuntimeEvent renderer。旧 callback 在这里是 deprecated
        compatibility bridge，不能继续成为新功能入口。
        本阶段删除了 Textual 直接把旧 callback 传给 core.chat 的分支：core 只看见
        RuntimeEvent sink，旧 callback 只在 main.py 这一层兼容转发。删除条件是旧
        callback 调用方和 stdout fallback 都迁移到 RuntimeEvent iterator。
        一旦本轮已经有 RuntimeEvent，stdout capture 就只能作为无事件旧路径的
        兜底，不能再把同一条用户可见语义作为 completion 返回给 Textual。
        """

        nonlocal emitted_runtime_event, streamed_any_chunk
        emitted_runtime_event = True
        if on_runtime_event is not None:
            on_runtime_event(event)
            return

        streamed_any_chunk = (
            _forward_runtime_event_to_legacy_callbacks(
                event,
                on_output_chunk=on_output_chunk,
                on_display_event=on_display_event,
            )
            or streamed_any_chunk
        )

        if on_output_chunk is None and on_display_event is None:
            rendered = render_runtime_event_for_cli(event)
            if rendered:
                runtime_event_outputs.append(rendered)

    with contextlib.redirect_stdout(captured):
        reply = chat(
            user_input,
            on_runtime_event=forward_runtime_event,
            event_log_writer=event_log_writer,
        )
    if emitted_runtime_event and runtime_event_outputs:
        latest_output = _merge_chat_outputs(
            reply,
            "".join(runtime_event_outputs),
        )
        return reply, latest_output
    if emitted_runtime_event and on_runtime_event is not None:
        # Textual 主路径已经通过 on_runtime_event 实时追加了用户可见内容。这里不再
        # 合并 captured stdout，避免旧 print-era 文案把同一语义作为 final reply
        # 再盖到 Assistant 占位上。若本轮完全没有 RuntimeEvent，后面的 stdout
        # fallback 仍会兜住尚未迁移的 session/异常旧输出。
        return reply, reply.strip()
    if streamed_any_chunk:
        # 已经通过 output.chunk 进入 conversation view，stdout capture 只保留
        # 非 assistant 的控制型返回；避免同一 assistant 文本再走 completion。
        return reply, reply.strip()
    latest_output = _textual_stdout_fallback_output(reply, captured.getvalue())
    return reply, latest_output


def _run_simple_cli_runtime_turn(
    user_input: str, *, event_log_writer: Any = None
) -> tuple[str, str]:
    """执行一轮 simple CLI fallback adapter。

    simple CLI 现在也通过 RuntimeEvent renderer 接收用户可见输出，但它不是产品能力
    的源头，也不能反过来决定 Textual TUI 的输入/确认/取消语义。这里保留 direct
    print 是终端 adapter 的渲染行为；它不写 checkpoint、runtime_observer、
    conversation.messages、Anthropic API messages 或 TaskState，也不把 simple CLI 的
    `/multi`、EOF、KeyboardInterrupt 等输入协议混进 RuntimeEvent 输出边界。
    """

    simple_streamed_any_chunk = False
    simple_assistant_parts: list[str] = []

    def forward_simple_runtime_event(event: RuntimeEvent) -> None:
        """simple CLI 主输出桥，避免 RuntimeEvent 又回落到 core.py print fallback。

        这是第四阶段的收口点：simple CLI 与 Textual 一样消费 RuntimeEvent，只是渲染
        目标不同。这里记录 assistant.delta 是为了防止 final return 又把已经流式输出
        的正文打印一遍；这是兼容旧 return-value 语义的防重复保护，不应继续扩展成
        新状态机，也不能塞入 checkpoint、runtime_observer、conversation.messages、
        Anthropic API messages 或 TaskState 本体。
        """

        nonlocal simple_streamed_any_chunk
        if event.event_type == EVENT_ASSISTANT_DELTA:
            simple_assistant_parts.append(event.text)
        simple_streamed_any_chunk = (
            _render_runtime_event_for_simple_cli(event)
            or simple_streamed_any_chunk
        )

    reply = chat(
        user_input,
        on_runtime_event=forward_simple_runtime_event,
        event_log_writer=event_log_writer,
    )
    if simple_streamed_any_chunk:
        # core.py 在无 sink 时代负责补这个换行；simple CLI 接管 RuntimeEvent 后，
        # 换行也必须留在 I/O adapter。这里不是业务输出，不能变成 RuntimeEvent。
        print()

    reply_text = reply.strip()
    streamed_text = "".join(simple_assistant_parts).strip()
    if simple_streamed_any_chunk and reply_text and reply_text == streamed_text:
        return "", streamed_text
    return reply, reply_text or streamed_text


def _run_chat_for_backend(
    user_input: str,
    *,
    backend: str,
    on_output_chunk: Callable[[str], None] | None = None,
    on_display_event: Callable[[DisplayEvent], None] | None = None,
    on_runtime_event: Callable[[RuntimeEvent], None] | None = None,
    event_log_writer: Any = None,
) -> tuple[str, str]:
    """按 UI adapter 分派一轮 Runtime 调用。

    这是为了兼容现有测试和调用方保留的薄 dispatcher，不再承载具体交互语义。
    Textual 产品路径和 simple CLI fallback 已拆到独立函数，避免 main.py 继续把
    terminal input()/print 时代的行为当成 TUI 主路径。这里不能新增 RuntimeEvent 类型、
    InputIntent、checkpoint 写入、状态机判断或新的 stdout 字符串过滤。
    """

    if backend == "textual":
        return _run_textual_runtime_turn(
            user_input,
            on_output_chunk=on_output_chunk,
            on_display_event=on_display_event,
            on_runtime_event=on_runtime_event,
            event_log_writer=event_log_writer,
        )

    return _run_simple_cli_runtime_turn(user_input, event_log_writer=event_log_writer)


def _handle_textual_shell_input(
    user_input: str,
    on_output_chunk: Callable[[str], None] | None = None,
    on_display_event: Callable[[DisplayEvent], None] | None = None,
    on_runtime_event: Callable[[RuntimeEvent], None] | None = None,
    *,
    event_log_writer: Any = None,
) -> str:
    """处理常驻 Textual Shell 提交的文本，并返回用户可见输出。

    这里是 main.py 的 I/O 桥接层：TUI 不 import Runtime state，也不
    save_checkpoint；main 负责复用现有 chat 流程，再把可展示文本交还给
    conversation view。stdout capture 仍保留，是为了兜住尚未迁移的 print-era
    session/异常/旧调用方文案；已经事件化的 assistant.delta、plan confirmation、
    request_user_input、DisplayEvent 和工具 lifecycle 不应再依赖这层 capture。

    本轮（slash command 整体下线）：以 `/` 起头的输入不再走 CommandRegistry/
    handle_slash_command 分流，而是按普通自然语言输入交给 chat()。后续如要
    补回类似能力，应通过自然语言归一 InputIntent + 明确 RuntimeEvent 用户确认
    流来表达，不再恢复 `/xxx` 字符串协议。
    """

    intent = classify_user_input(
        user_input,
        source="tui",
        state=get_state(),
    )
    # InputIntent 是 TUI adapter 进入 Runtime 前的只读分类：这里只用它集中
    # empty/exit 这类 UI 控制输入，confirmation/request_user_input 仍交给
    # core.chat() 按 TaskState 分派。不要把 intent 写进 checkpoint、messages、
    # RuntimeEvent 或 Anthropic API messages，也不要把它扩展成状态机本体。
    text = intent.normalized_text
    if intent.kind == "empty":
        return ""

    if intent.kind == "exit":
        return "[系统] 常驻 TUI 请按 Ctrl+Q 退出并保存会话。"

    _reply, latest_output = _run_chat_for_backend(
        text,
        backend="textual",
        on_output_chunk=on_output_chunk,
        on_display_event=on_display_event,
        on_runtime_event=on_runtime_event,
        event_log_writer=event_log_writer,
    )
    return latest_output


def run_textual_main_loop(event_log_writer: Any = None) -> None:
    """运行常驻 Textual backend。

    one-shot TUI 的闪退闪回来自”提交即 app.exit，再由 main 重建 App”。这里改成
    一个常驻 I/O Shell：Textual 只显示/收集 I/O，Runtime 仍通过 main 调用
    chat()，checkpoint 仍由既有 Runtime/session 逻辑负责。
    """

    from functools import partial

    from agent.input_backends.textual import run_textual_io_shell

    handler = partial(_handle_textual_shell_input, event_log_writer=event_log_writer)
    run_textual_io_shell(chat_handler=handler)
    finalize_session()


def main_loop(event_log_writer: Any = None):
    last_interrupt_time = 0
    latest_output = ""
    last_status_line = ""

    while True:
        try:
            backend = _selected_input_backend()
            if backend in ("", "simple"):
                status_line = render_status_line(summarize_session_status(get_state()))
                if status_line != last_status_line:
                    print(f"\n{status_line}")
                    last_status_line = status_line

            # P2 修复：resume / interrupt 选择不再在 session.py 里裸调 input()，
            # 改为由 main_loop 通过正常输入后端收口读取。
            state = get_state()
            if state.task.status == "awaiting_resume_choice":
                event = read_user_input_event(
                    prompt_text="要继续这个任务吗？(y/n): ",
                    latest_output="",
                )
                if event.envelope is not None:
                    handle_resume_choice(event.envelope.raw_text)
                continue

            if state.task.status == "awaiting_interrupt_choice":
                # 菜单已由 handle_interrupt_with_checkpoint 打印。
                event = read_user_input_event(
                    prompt_text="请选择 (1/2/3): ",
                    latest_output="",
                )
                if event.envelope is not None:
                    should_exit = handle_interrupt_choice(event.envelope.raw_text)
                    if should_exit:
                        break
                continue

            event = read_user_input_event(latest_output=latest_output)
            intent = classify_user_input(
                event.envelope.raw_text if event.envelope is not None else None,
                source=event.event_source,
                state=get_state(),
                event_type=event.event_type,
            )
            # main_loop 是 simple CLI fallback 和 legacy one-shot textual backend 的调度层。
            # InputIntent 只帮助这里统一 cancel/eof/empty/exit 的输入边界；
            # plan/tool/request_user_input 等 Runtime 语义仍由 chat() 的 TaskState 分派处理。
            # 不能把 intent 持久化，也不能把它混进 RuntimeEvent 输出边界。

            # cancelled 复用现有 Ctrl+C interrupt 流程；它不是空输入。
            if intent.kind == "cancel":
                raise KeyboardInterrupt

            # closed 表示输入会话结束/EOF，不进入 chat，也不触发 empty guard。
            if intent.kind == "eof":
                finalize_session()
                break

            if event.envelope is None:
                continue

            user_input = intent.normalized_text

            # 空输入过滤
            if intent.kind == "empty":
                continue

            if intent.kind == "exit":
                finalize_session()
                break

            # Phase 5a T1 pending review CLI trigger（RFC §11.4 / §15.2）
            # slash command 已整体下线，这里用普通文本触发 review。
            # 这不是通用 command registry，只是 Phase 5a 的最小可用入口。
            if user_input.strip().lower() in (
                "review memory", "查看待确认记忆", "memory review", "review pending",
            ):
                print()
                run_pending_review_cli()
                continue

            # WP3 onboarding：用户输入 help/帮助/onboarding 时展示能力与限制。
            if user_input.strip().lower() in ("help", "帮助", "onboarding", "?"):
                print()
                print(render_onboarding())
                continue

            reply, new_latest_output = _run_chat_for_backend(
                user_input,
                backend=backend,
                event_log_writer=event_log_writer,
            )
            if new_latest_output:
                latest_output = new_latest_output
            if reply:
                print(reply)
            if backend in ("", "simple"):
                status_line = render_status_line(summarize_session_status(get_state()))
                if status_line != last_status_line:
                    print(f"\n{status_line}")
                    last_status_line = status_line

        except KeyboardInterrupt:
            now = time.time()

            if now - last_interrupt_time < CTRL_C_DOUBLE_PRESS_WINDOW:
                handle_double_interrupt()
                break

            last_interrupt_time = now

            if load_checkpoint():
                should_exit = handle_interrupt_with_checkpoint()
            else:
                should_exit = handle_interrupt_without_checkpoint()

            if should_exit:
                break


def _try_dispatch_mcp_bridge_lifecycle(report, mode: str, dry_run: bool) -> None:
    """通过 disposable dispatcher 记录 MCP bridge lifecycle evidence。

    模式与 session.py _try_dispatch_checkpoint_resume() 一致：
    dispatcher 按需构建，仅用于 evidence recording。构建失败时静默跳过。
    """
    try:
        from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
        from agent.runtime_integration.schema import (
            RuntimeActionRequest,
            RuntimeActionType,
        )

        dispatcher = build_phase1_dispatcher()
        dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.MCP_BRIDGE_LIFECYCLE,
            source="main.mcp_bridge",
            parent_trace_id="",
            payload={
                "mode": mode,
                "dry_run": dry_run,
                "servers_configured": report.servers_configured,
                "servers_evaluated": report.servers_evaluated,
                "tools_discovered": report.tools_discovered,
                "tools_registered": report.tools_registered,
                "overall_decision": report.overall_decision,
                "errors": report.errors,
            },
        ))
    except Exception:
        pass


def _init_mcp_bridge_if_enabled() -> None:
    """MCP bridge thin wrapper：只在 MY_FIRST_AGENT_MCP_ENABLE=1 时运行。

    不修改 core.py、不绕过 policy gate、默认 disabled。
    bridge 在 init_session 之前运行，将 MCP tools 注册到 TOOL_REGISTRY。
    Loop 2.4: bridge report 生成后通过 disposable dispatcher 记录
    MCP_BRIDGE_LIFECYCLE evidence。
    Loop 3.3: 支持 server_allowlist / config_path 显式传入；
    bridge 成功后通过 set_mcp_bridge_result() 更新决策脊柱 mcp_available。
    """
    import os

    enabled = os.getenv("MY_FIRST_AGENT_MCP_ENABLE", "").strip().lower()
    if enabled not in ("1", "true", "yes", "on"):
        return

    mode = os.getenv("MY_FIRST_AGENT_MCP_MODE", "registration").strip().lower()
    dry_run = os.getenv("MY_FIRST_AGENT_MCP_DRY_RUN", "1").strip().lower() in (
        "1", "true", "yes",
    )

    # Loop 3.3: server_allowlist 从 env var 显式传入
    raw_allowlist = os.getenv("MY_FIRST_AGENT_MCP_SERVER_ALLOWLIST", "").strip()
    server_allowlist: frozenset[str] | None = None
    if raw_allowlist:
        server_allowlist = frozenset(
            name.strip() for name in raw_allowlist.split(",") if name.strip()
        )

    # Loop 3.3: config_path 从 env var 显式传入（而非仅在 _load_mcp_config 内部读取）
    config_path = os.getenv("MY_FIRST_AGENT_MCP_CONFIG", "") or None

    try:
        from agent.mcp_bridge import run_mcp_bridge, set_mcp_bridge_result

        report = run_mcp_bridge(
            mode=mode,  # type: ignore[arg-type]
            config_path=config_path,
            server_allowlist=server_allowlist,
            dry_run=dry_run,
        )
        # Loop 3.3: 更新决策脊柱 mcp_available 状态
        set_mcp_bridge_result(report.tools_registered)

        # Loop 2.4: 通过 disposable dispatcher 记录 MCP_BRIDGE_LIFECYCLE evidence
        _try_dispatch_mcp_bridge_lifecycle(report, mode, dry_run)
        # bridge report 只打印短摘要，不打印 raw descriptor / raw result
        print(
            f"\n[MCP Bridge] mode={report.mode} "
            f"servers={report.servers_evaluated}/{report.servers_configured} "
            f"tools_discovered={report.tools_discovered} "
            f"tools_blocked={report.tools_blocked} "
            f"tools_registered={report.tools_registered} "
            f"decision={report.overall_decision}"
        )
        if report.errors:
            for err in report.errors:
                print(f"  [MCP Bridge error] {err}")
    except Exception as e:
        print(f"[MCP Bridge] 初始化异常（已跳过）: {e}")


def main(argv: list[str] | None = None) -> int:
    # legacy CLI 入口显式 opt-in 读取项目 .env；普通 import config 不再产生
    # os.environ 副作用，provider/dogfood 路径继续走 scoped loader。
    load_legacy_dotenv_config(project_root=Path(__file__).resolve().parent)

    # PF-01: 启动时输出 provider mode 横幅，让用户明确当前是 fake/local 还是 real provider。
    # manual human dogfood 第一 blocker——用户必须知道当前模式。
    print(render_provider_mode_banner(), file=sys.stderr)

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"--shell", "shell"}:
        argv = argv[1:]

    if argv and argv[0] in {"--help", "-h", "help"}:
        print(render_onboarding())
        return 0

    command_result = dispatch_maintenance_command(
        argv,
        project_root=Path(__file__).resolve().parent,
    )
    if command_result is not None:
        return command_result

    # MCP bridge：受控 readiness 层，默认 disabled。
    # 设置 MY_FIRST_AGENT_MCP_ENABLE=1 后才在 session 初始化前运行。
    # bridge 不进入 core loop、不改 checkpoint、不绕过 policy gate。
    _init_mcp_bridge_if_enabled()

    # B7: session_id 在 main() startup 时生成（非 import-time）
    _session_id = str(uuid4())
    init_session(session_id=_session_id)
    try_resume_from_checkpoint()

    # B7 Slice 4: per-session event log writer
    _project_dir = Path(__file__).resolve().parent
    _event_log_writer = EventLogWriter(session_dir=_project_dir / "sessions" / _session_id)

    # P2 修复：try_resume_from_checkpoint 可能将 status 设为
    # awaiting_resume_choice。进入 main_loop / textual shell 前必须先解析。
    state = get_state()
    if state.task.status == "awaiting_resume_choice":
        if _selected_input_backend() == "textual":
            # Textual 后端尚未初始化，用 raw input() 做一次性解析。
            # Textual 是 TTY-only，不存在管道 stdin 抢占问题。
            choice = input("要继续这个任务吗？(y/n): ").strip().lower()
            handle_resume_choice(choice)
        else:
            # simple 后端：交给 main_loop 通过正常输入后端收口。
            pass

    if _selected_input_backend() == "textual":
        run_textual_main_loop(event_log_writer=_event_log_writer)
    else:
        main_loop(event_log_writer=_event_log_writer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
