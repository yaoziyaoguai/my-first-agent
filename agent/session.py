"""Session 生命周期管理：启动、恢复、退出、中断。

把原来散在 main.py 里的 session 相关逻辑集中到这里。
"""

import inspect
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import agent.checkpoint as _cp
from agent.checkpoint import (
    checkpoint_path,
    clear_checkpoint,
    load_checkpoint,
    load_checkpoint_to_state,
)
from agent.cli_renderer import (
    STAGE_LABEL,
    render_resume_status,
    render_session_header,
    summarize_health,
)
from agent.display_events import (
    build_tool_awaiting_confirmation_event,
    render_display_event,
)
from agent.health_check import run_health_check
from agent.logger import (
    get_runtime_session_id,
    log_event,
    save_session_snapshot,
    set_runtime_session_id,
)
from agent.memory import (
    _format_extraction_summary,
    cleanup_old_episodes,
    extract_memories_from_session,
    init_memory,
)
from agent.memory_review import count_pending_proposals
from agent.runtime_integration.checkpoint_save import save_runtime_checkpoint
from agent.runtime_integration.skill_lifecycle import (
    clear_skill_lifecycle_for_resume,
    restore_skill_lifecycle_from_checkpoint,
)
from config import MODEL_NAME, SYSTEM_PROMPT

# ========== checkpoint 路径辅助 ==========

def _resolve_session_id() -> str:
    """返回当前 runtime session_id，无则返回空字符串。"""
    try:
        return get_runtime_session_id() or ""
    except Exception:
        return ""


def save_checkpoint(state: Any, source: str | None = None, **kwargs: Any) -> None:
    """Compatibility patch symbol; session saves still use runtime gateway."""
    kwargs.setdefault("session_id", _resolve_session_id())
    try:
        signature = inspect.signature(save_runtime_checkpoint)
    except (TypeError, ValueError):
        save_runtime_checkpoint(state, source=source, **kwargs)
        return

    parameters = signature.parameters
    accepts_var_kwargs = any(
        param.kind is inspect.Parameter.VAR_KEYWORD
        for param in parameters.values()
    )
    accepted_kwargs = (
        dict(kwargs)
        if accepts_var_kwargs
        else {key: value for key, value in kwargs.items() if key in parameters}
    )
    if accepts_var_kwargs or "source" in parameters:
        accepted_kwargs["source"] = source
    save_runtime_checkpoint(state, **accepted_kwargs)


def _single_file_checkpoint_ok(single_cp, current_sid: str) -> bool:
    """检查 single-file checkpoint (formerly v1) 是否属于当前 session。

    - 无 session_id metadata：legacy 兼容，允许加载
    - 有 session_id 且匹配当前 session：允许加载
    - 有 session_id 且不匹配：拒绝（cross-session contamination guard）
    """
    if single_cp is None:
        return False
    _meta = single_cp.get("meta", {}) or {}
    _sid = _meta.get("session_id", "")
    if not _sid:
        return True   # legacy: no session_id → allow
    return _sid == current_sid


def _load_checkpoint_best_effort():
    """加载最新 checkpoint，按 mtime 选择（single-file vs session-scoped）。

    Single-file checkpoint (formerly "v1"): memory/checkpoint.json
    Session-scoped checkpoint (formerly "v2"): memory/checkpoints/{sid}/*.json

    Gap 4 fix: 不再无条件优先 session-scoped。当两者同时存在时按 mtime
    选择最新的；拒绝跨 session 的 single-file checkpoint (P2-1)；
    legacy single-file 无 session_id 时保留向后兼容。
    """
    _sid = _resolve_session_id()

    # 收集最佳 session-scoped candidate（当前 session 下 mtime 最新的）
    _best_session = None
    _best_session_mtime = 0.0
    if _sid:
        _session_dir = checkpoint_path(_sid, "_").parent
        if _session_dir.exists():
            for _rf in _session_dir.glob("*.json"):
                _candidate = load_checkpoint(path=_rf)
                if _candidate is not None:
                    _mt = _rf.stat().st_mtime
                    if _mt > _best_session_mtime:
                        _best_session = _candidate
                        _best_session_mtime = _mt

    # single-file candidate (formerly v1)
    _single_cp = load_checkpoint()
    _single_mtime = _cp.CHECKPOINT_PATH.stat().st_mtime if _cp.CHECKPOINT_PATH.exists() else 0.0
    _single_ok = _single_file_checkpoint_ok(_single_cp, _sid)

    # 两者都有：按 mtime 选最新，兼顾 session 匹配
    if _best_session is not None and _single_ok:
        if _single_mtime > _best_session_mtime:
            return _single_cp
        else:
            return _best_session

    if _best_session is not None:
        return _best_session
    if _single_ok:
        return _single_cp
    return None


@dataclass(frozen=True)
class SelectedCheckpointRestoreResult:
    success: bool
    checkpoint: dict[str, Any] | None = None
    path: Path | None = None

    def __bool__(self) -> bool:
        return self.success


def _load_selected_checkpoint_to_state_best_effort(
    state,
) -> SelectedCheckpointRestoreResult:
    """恢复到 state：按 mtime 选最新 checkpoint（single-file vs session-scoped）。

    Single-file checkpoint (formerly "v1"): memory/checkpoint.json
    Session-scoped checkpoint (formerly "v2"): memory/checkpoints/{sid}/*.json

    策略：
    1. 按 mtime 从新到旧尝试 session-scoped checkpoints，跳过损坏的 (P2-2)
    2. 若所有 session-scoped 均失败，fallback 到 single-file（需 session 匹配
       或 legacy 兼容，P2-1）
    3. 在两者间按 mtime 选择最新的
    4. 返回实际选中的 checkpoint/path，供 session resume 成功后同步恢复 skill
    """
    _sid = _resolve_session_id()

    # P2-2: 按 mtime 从新到旧找第一个可解析的 session-scoped checkpoint
    _best_session_mtime = 0.0
    _best_session_path = None
    if _sid:
        _session_dir = checkpoint_path(_sid, "_").parent
        if _session_dir.exists():
            _session_paths = sorted(
                _session_dir.glob("*.json"),
                key=lambda p: p.stat().st_mtime, reverse=True,
            )
            for _sp in _session_paths:
                # 用 load_checkpoint 验证文件可解析（跳过损坏的）
                if load_checkpoint(path=_sp) is not None:
                    _best_session_path = _sp
                    _best_session_mtime = _sp.stat().st_mtime
                    break

    # single-file candidate (formerly v1)
    _single_mtime = _cp.CHECKPOINT_PATH.stat().st_mtime if _cp.CHECKPOINT_PATH.exists() else 0.0
    _single_cp = load_checkpoint() if _cp.CHECKPOINT_PATH.exists() else None
    _single_ok = _single_file_checkpoint_ok(_single_cp, _sid)

    # 决定加载哪个（按 mtime 选最新，session-scoped 优先于平局）
    _pick_single = False
    if _best_session_path is not None and _single_ok:
        if _single_mtime > _best_session_mtime:
            _pick_single = True
    elif _best_session_path is None and _single_ok:
        _pick_single = True

    _chosen_cp = None
    _chosen_path: Path | None = None
    if _pick_single:
        _chosen_cp = _single_cp
        _chosen_path = _cp.CHECKPOINT_PATH
    elif _best_session_path is not None:
        _chosen_path = _best_session_path

    if _pick_single:
        restored = load_checkpoint_to_state(state)
        if restored and _chosen_path is not None:
            _chosen_cp = load_checkpoint(path=_chosen_path)
        return SelectedCheckpointRestoreResult(
            bool(restored and _chosen_cp is not None),
            checkpoint=_chosen_cp if restored else None,
            path=_chosen_path if restored else None,
        )

    if _best_session_path is not None:
        restored = load_checkpoint_to_state(state, path=_best_session_path)
        if restored:
            _chosen_cp = load_checkpoint(path=_best_session_path)
        return SelectedCheckpointRestoreResult(
            bool(restored and _chosen_cp is not None),
            checkpoint=_chosen_cp if restored else None,
            path=_chosen_path if restored else None,
        )

    return SelectedCheckpointRestoreResult(False)


def _load_checkpoint_to_state_best_effort(state):
    """Backward-compatible bool wrapper for older callers/tests."""
    return _load_selected_checkpoint_to_state_best_effort(state).success


def _detect_provider_info() -> dict[str, str]:
    """在 session 启动时检测 provider_type 和 model，不输出 secret。

    Evidence readiness (2026-06-05): session_start 必须携带 provider/entry 信息，
    否则无法从 996 个 historical sessions 中区分 fake vs real、--plain vs --tui。
    复用 cli_renderer.render_provider_mode_banner 的检测路径，保持一致性。
    """
    try:
        from agent.provider.simple_config import load_unified_provider_config
        unified = load_unified_provider_config()
        return {
            "provider_type": unified.config.provider_type,
            "model": unified.config.model or "unspecified",
            "config_source": str(unified.source),
        }
    except Exception:
        pass
    # fallback: legacy env
    import os as _os
    provider_env = _os.getenv("MY_FIRST_AGENT_LLM_PROVIDER", "fake")
    model_env = (
        _os.getenv("MY_FIRST_AGENT_LLM_MODEL")
        or _os.getenv("ANTHROPIC_MODEL")
        or _os.getenv("OPENAI_MODEL")
        or "unspecified"
    )
    return {
        "provider_type": provider_env.strip().lower() or "fake",
        "model": model_env or "unspecified",
        "config_source": "legacy_env",
    }


# ========== 启动 ==========

def init_session(*, session_id: str | None = None, entry: str = ""):
    """启动时调用：初始化记忆 + 健康检查 + 渲染 session header。

    B7: 接受可选的 session_id 参数。传入时设置 runtime session_id 并使用它；
    不传时回退到 import-time SESSION_ID（向后兼容）。

    Evidence readiness (2026-06-05): 接受 entry 参数（--plain/--tui/--textual），
    写入 session_start 事件，使后续 golden E2E 复测可区分入口路径。

    v0.3 M1 升级：用 cli_renderer.render_session_header 替代旧的两行
    print，把阶段标签 / cwd / 健康摘要一次性结构化显示，并把 health_check
    切成 verbose=False 模式避免刷屏（详情仍可用 `python main.py health` 查看）。
    """
    if session_id is not None:
        set_runtime_session_id(session_id)

    _sid = get_runtime_session_id()
    init_memory()
    cleanup_old_episodes()

    _provider_info = _detect_provider_info()
    log_event("session_start", {
        "system_prompt_length": len(SYSTEM_PROMPT),
        "provider_type": _provider_info["provider_type"],
        "model": _provider_info["model"],
        "config_source": _provider_info["config_source"],
        "entry": entry or "plain",
    })
    # Evidence recorder: session.start 是核心 Runtime branch point，
    # 必须进入统一 evidence，后续排查靠它关联 provider/entry/session_id。
    try:
        from agent.evidence_recorder import record_evidence
        record_evidence(
            subsystem="session",
            operation="start",
            phase="start",
            status="ok",
            safe_summary=f"session_start provider={_provider_info['provider_type']}"
                        f" model={_provider_info['model']}"
                        f" entry={entry or 'plain'}",
            metadata={
                "provider_type": _provider_info["provider_type"],
                "provider_model": _provider_info["model"],
                "config_source": _provider_info["config_source"],
                "entry": entry or "plain",
            },
        )
    except Exception:
        pass

    health_results = run_health_check(verbose=False)

    # Phase 5a T1 pending review: 通知用户有未处理的 pending proposals
    _pending_count = count_pending_proposals()
    if _pending_count > 0:
        print(f"\n[记忆] 有 {_pending_count} 条待确认的记忆提案。输入 'review memory' 查看并处理。")

    print(
        render_session_header(
            session_id=_sid,
            cwd=os.getcwd(),
            stage_label=STAGE_LABEL,
            health_summary=summarize_health(health_results),
        )
    )


def _checkpoint_has_actionable_resume(task_data: dict, conv_data: dict) -> bool:
    """判断 checkpoint 是否值得提示用户「要不要继续」。

    真实 M7-C 痛点：旧实现只要 checkpoint 文件存在就 prompt，
    哪怕 task.status='idle' + 0 条消息 + 无 pending_tool，
    用户会看到「📌 发现未完成的任务：（未命名任务） 已有 0 条对话历史」
    然后被强迫 y/n，体验上既无信息也无意义。

    actionable 条件（任一满足即提示）：
    - status 处于明确等待用户的状态（awaiting_*）
    - 存在 pending_tool 或 pending_user_input_request
    - 有进行中的 plan（current_plan + current_step_index > 0）
    - 有非空对话历史 + 非 idle 状态（说明上一轮没正常收尾）
    """
    status = task_data.get("status") or "idle"
    if status.startswith("awaiting_"):
        return True
    if task_data.get("pending_tool"):
        return True
    if task_data.get("pending_user_input_request"):
        return True
    if task_data.get("current_plan") and (task_data.get("current_step_index") or 0) > 0:
        return True
    msg_count = len(conv_data.get("messages", []))
    return bool(msg_count > 0 and status != "idle")


def _try_dispatch_checkpoint_resume(state, resume_mode="interactive"):
    """尝试通过 dispatcher 记录 CHECKPOINT_RESUME evidence。

    session.py 在 chat() 之前运行，dispatcher 尚未构建。这里按需构建一个
    dispatcher 实例仅用于 evidence recording——load_checkpoint_to_state 已在
    调用方执行完毕，handler 通过 _already_loaded 跳过重复 load。
    构建失败时静默跳过（resume 本身已完成，仅缺少 dispatcher evidence）。
    """
    try:
        from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
        from agent.runtime_integration.schema import (
            RuntimeActionRequest,
            RuntimeActionType,
        )

        dispatcher = build_phase1_dispatcher()
        route = getattr(dispatcher, "route_from_runtime_loop", None)
        if route is None:
            route = dispatcher.route
        route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.CHECKPOINT_RESUME,
                source="session.resume",
                parent_trace_id="",
                payload={
                    "_state": state,
                    "resume_mode": resume_mode,
                    "_already_loaded": True,
                },
            ),
            core_entrypoint="session.resume",
            runtime_hook_name="resume_checkpoint",
        )
    except Exception:
        pass


def try_resume_from_checkpoint():
    """检查有没有未完成的任务，有就问用户是否恢复。

    M7-C 修复：不再无条件 prompt；只有 checkpoint 真的处于「等待用户输入」
    或「执行中断」状态时才提示。idle + 空消息的 checkpoint 视作历史残留，
    静默清掉，避免干扰用户开始新对话。

    P2 修复：不再在此函数内直接调用 input()。管道 stdin 下，这里的 input()
    会抢跑管道内容，导致确认不可靠。改为：
    - 管道模式（stdin 非 TTY）：自动恢复，不弹交互提示。
    - TTY 模式：设 state.task.status = "awaiting_resume_choice"，
      由 main_loop 通过正常输入后端收口读取用户选择。
    """
    # 延迟 import，避免循环依赖
    from agent.core import get_state

    checkpoint = _load_checkpoint_best_effort()
    # B2 契约：普通 CLI 下不能裸 print 整段 checkpoint dict（含 conversation messages）。
    # 这里只在 MY_FIRST_AGENT_DEBUG=1 时才打印调试信息，且打印的是 keys 而非 values，
    # 避免把会话历史泄到终端。详见 docs/CLI_OUTPUT_CONTRACT.md "禁止项"。
    from agent.checkpoint import _debug_stdout_enabled
    if checkpoint is not None and _debug_stdout_enabled():
        print(f"[CHECKPOINT] loaded keys={list(checkpoint.keys())}")
    if not checkpoint:
        # v0.3 M1：让「无 checkpoint」也有一行可读的状态行，不沉默退出。
        print(render_resume_status(None))
        return

    task_data = checkpoint.get("task", {})
    conv_data = checkpoint.get("conversation", {})

    if not _checkpoint_has_actionable_resume(task_data, conv_data):
        # 静默清理历史残留，避免误导用户「有未完成的任务」。
        clear_checkpoint()
        clear_skill_lifecycle_for_resume(
            get_state(),
            reason="no_actionable_resume",
            source="session.try_resume_from_checkpoint",
        )
        # v0.3 M1：把「静默清理」也变成一行可见提示，方便用户确认 resume 行为。
        print(render_resume_status({"actionable": False}))
        return

    summary = _build_checkpoint_resume_summary(task_data, conv_data)
    print(render_resume_status(summary))

    # 管道模式：不弹交互提示，自动恢复最近任务。
    if not sys.stdin.isatty():
        print("[系统] 检测到管道输入，自动恢复最近任务。")
        restore_result = _load_selected_checkpoint_to_state_best_effort(get_state())
        if restore_result.success:
            restore_skill_lifecycle_from_checkpoint(
                get_state(),
                restore_result.checkpoint,
                source="session.try_resume_from_checkpoint",
            )
            _try_dispatch_checkpoint_resume(get_state())
            _replay_awaiting_prompt(get_state())
        else:
            clear_skill_lifecycle_for_resume(
                get_state(),
                reason="state_restore_failed",
                source="session.try_resume_from_checkpoint",
            )
        return

    # TTY 模式：交给 main_loop 通过正常输入后端收口读取用户选择。
    get_state().task.status = "awaiting_resume_choice"


def _build_checkpoint_resume_summary(task_data: dict, conv_data: dict) -> dict:
    """从 checkpoint 的 task / conversation 字段抽出渲染用的脱敏摘要。

    刻意只抽 cli_renderer.render_resume_status 真正需要的字段，
    避免把整段 messages / system prompt / api 配置 print 到终端。
    """
    pending_tool = task_data.get("pending_tool") or {}
    return {
        "actionable": True,
        "user_goal": task_data.get("user_goal"),
        "status": task_data.get("status"),
        "current_step_index": task_data.get("current_step_index", 0),
        "message_count": len(conv_data.get("messages", [])),
        "pending_tool_name": pending_tool.get("tool")
        if isinstance(pending_tool, dict)
        else None,
    }


def summarize_session_status(state) -> dict:
    """v0.3 M1：把 AgentState 压缩成渲染层可用的脱敏摘要。

    渲染层（cli_renderer）只读 dict、不持有 state 引用，可以避免：
    - 把 raw conversation messages / api_key / base_url / headers 误打到终端
    - 渲染逻辑反向修改 Runtime / messages / checkpoint

    入参 state 是 AgentState；这里只抽取 task 区里**对人工可读、且不敏感**的字段。
    """
    if state is None or getattr(state, "task", None) is None:
        return {
            "actionable": False,
            "user_goal": None,
            "status": "idle",
            "current_step_index": 0,
            "message_count": 0,
            "pending_tool_name": None,
            "plan_total_steps": None,
        }

    task = state.task
    conv = getattr(state, "conversation", None)
    plan = task.current_plan if isinstance(task.current_plan, dict) else None
    plan_steps = plan.get("steps") if isinstance(plan, dict) else None
    plan_total = len(plan_steps) if isinstance(plan_steps, list) else None
    current_step_title = None
    if isinstance(plan_steps, list) and 0 <= task.current_step_index < len(plan_steps):
        step = plan_steps[task.current_step_index]
        if isinstance(step, dict):
            current_step_title = (
                step.get("title")
                or step.get("name")
                or step.get("description")
                or step.get("action")
            )
    pending = task.pending_tool if isinstance(task.pending_tool, dict) else None
    return {
        "actionable": task.status != "idle"
        or bool(pending)
        or bool(task.pending_user_input_request),
        "user_goal": task.user_goal,
        "status": task.status,
        "current_step_index": task.current_step_index,
        "message_count": len(conv.messages) if conv is not None else 0,
        "pending_tool_name": pending.get("tool") if pending else None,
        "plan_total_steps": plan_total,
        "current_step_title": current_step_title,
    }


def _replay_awaiting_prompt(state):
    """按恢复后的 task.status 重新打印对应的询问提示。

    目的：checkpoint 存的是一个「等待用户某种输入」的断点，恢复后用户
    如果不知道当前处于哪个 awaiting 状态，就不知道该输入 y/n。
    """
    from agent.planner import Plan, format_plan_for_display

    status = state.task.status
    plan_dict = state.task.current_plan

    if status == "awaiting_plan_confirmation" and plan_dict:
        try:
            plan = Plan.model_validate(plan_dict)
            print(format_plan_for_display(plan))
        except Exception:
            pass
        print("按此计划执行吗？(y/n/输入修改意见): ", end="", flush=True)
        return

    if status == "awaiting_step_confirmation":
        print("\n上一步已完成。回复 y 继续下一步，回复 n 停止任务。")
        return

    if status == "awaiting_user_input":
        # 区分两种来源：
        # - 执行期求助（pending_user_input_request 非 None）：回放当时的问题/原因/选项
        # - collect_input/clarify 收尾：保留旧文案
        pending = getattr(state.task, "pending_user_input_request", None)
        if pending:
            print("\n上一轮需要你补充信息后才能继续：")
            if pending.get("question"):
                print(f"  问题：{pending['question']}")
            if pending.get("why_needed"):
                print(f"  原因：{pending['why_needed']}")
            options = pending.get("options") or []
            if options:
                print("  可选项：")
                for o in options:
                    print(f"    - {o}")
            print("  请直接回复你的答复。")
        else:
            print("\n上一步需要补充信息，请直接回复。")
        return

    if status == "awaiting_tool_confirmation" and state.task.pending_tool:
        pending = state.task.pending_tool
        event = build_tool_awaiting_confirmation_event(
            tool_name=pending.get("tool", "unknown"),
            tool_input=pending.get("input") or {},
        )
        print("\n" + render_display_event(event))
        return

    print(f"\n[系统] 已恢复断点（状态：{status}）。\n")


# ========== 退出 ==========

def _run_session_end_memory_extraction(messages, client, model_name) -> dict:
    """Session-end memory extraction 的 thin orchestration helper。

    职责：
    - 调用 extract_memories_from_session() 触发 extraction → governance → persistence
    - 通过 _format_extraction_summary() 展示结果

    不参与 T1/T2/T3 routing 决策，不直接操作 store 文件结构。

    被 finalize_session() 和 handle_double_interrupt() 共用，
    确保正常退出和 Ctrl+C×2 退出都执行 session-end extraction。
    """
    print("\n[系统] 正在提取本次对话的记忆...")
    extraction_summary = extract_memories_from_session(messages, client, model_name)
    print(_format_extraction_summary(extraction_summary))
    return extraction_summary


def _record_session_end(status: str = "ok", reason: str = "") -> None:
    """记录 session.end evidence，使 session 生命周期完整闭环。

    session.start / session.end 配对是 logs --summary 可信排查的基础。
    """
    try:
        from agent.evidence_recorder import record_evidence
        record_evidence(
            subsystem="session",
            operation="end",
            phase="end",
            status=status,
            reason_code=reason,
            safe_summary=f"session_end status={status}" + (f" reason={reason}" if reason else ""),
        )
    except Exception:
        pass


def finalize_session():
    """正常退出（quit 或双 Ctrl+C）：提取记忆 + 保存快照 + 保存 state 断点。

    session.py 只做 thin runtime orchestration。
    """
    from agent.core import client, get_state

    state = get_state()
    messages = state.conversation.messages

    _run_session_end_memory_extraction(messages, client, MODEL_NAME)
    save_session_snapshot(messages)

    if state.task.current_plan:
        save_checkpoint(state)
        print("[系统] 未完成的任务断点已保存，下次启动可继续。")

    _record_session_end(status="ok")
    print("会话已保存，再见！")


# ========== 中断处理 ==========

def handle_interrupt_with_checkpoint() -> bool:
    """单次 Ctrl+C + 有 checkpoint：弹菜单。

    P2 修复：不再在此函数内直接调用 input()，改为设
    state.task.status = "awaiting_interrupt_choice"，
    由 main_loop 通过正常输入后端收口读取用户选择。
    返回 True 表示要退出程序。
    """
    from agent.core import get_state

    state = get_state()
    save_checkpoint(state)

    print("\n\n[系统] 当前任务已暂停，断点已保存。")
    print("  1. 继续当前任务")
    print("  2. 放弃任务，回到对话模式")
    print("  3. 退出程序")

    state.task.status = "awaiting_interrupt_choice"
    return False


def handle_resume_choice(choice: str) -> None:
    """处理 await_resume_choice 状态的用户输入。

    由 main_loop 在读取到用户输入后调用。
    """
    from agent.core import get_state

    choice = choice.strip().lower()
    if choice != "y":
        clear_checkpoint()
        clear_skill_lifecycle_for_resume(
            get_state(),
            reason="resume_declined",
            source="session.handle_resume_choice",
        )
        print("\n[系统] 已清除断点，回到对话模式，可以直接输入新任务。\n")
        get_state().task.status = "idle"
        return

    restore_result = _load_selected_checkpoint_to_state_best_effort(get_state())
    if restore_result.success:
        restore_skill_lifecycle_from_checkpoint(
            get_state(),
            restore_result.checkpoint,
            source="session.handle_resume_choice",
        )
        _try_dispatch_checkpoint_resume(get_state())
        _replay_awaiting_prompt(get_state())
    else:
        clear_skill_lifecycle_for_resume(
            get_state(),
            reason="state_restore_failed",
            source="session.handle_resume_choice",
        )
        print(
            "\n[系统] 恢复断点失败——checkpoint 数据可能已损坏或与当前版本不兼容。"
            "已清除断点，回到对话模式。可直接输入新任务。\n"
        )
        get_state().task.status = "idle"


def handle_interrupt_choice(choice: str) -> bool:
    """处理 awaiting_interrupt_choice 状态的用户输入。

    由 main_loop 在读取到用户输入后调用。
    返回 True 表示要退出程序。
    """
    from agent.core import get_state

    state = get_state()
    choice = choice.strip()

    if choice == "1":
        print("[系统] 已保留当前任务状态，继续对话。\n")
        state.task.status = "running"
        return False

    if choice == "2":
        from agent.runtime_integration.skill_lifecycle import (
            deactivate_active_skill_for_task_boundary,
        )

        deactivate_active_skill_for_task_boundary(
            state,
            reason="user_abandon",
            source="session.user_abandon",
        )
        clear_checkpoint()
        state.reset_task()
        print("[系统] 任务已放弃，回到对话模式。\n")
        return False

    if choice == "3":
        save_session_snapshot(state.conversation.messages)
        _record_session_end(status="ok", reason="menu_exit")
        print("[系统] 再见！")
        return True

    print("[系统] 回到对话模式。\n")
    state.task.status = "idle"
    return False


def handle_interrupt_without_checkpoint() -> bool:
    """单次 Ctrl+C + 无 checkpoint：提示再按一次退出。返回 False（不退出）"""
    from agent.core import get_state

    messages = get_state().conversation.messages

    print("\n\n[系统] 再按一次 Ctrl+C 退出程序，或继续输入。")
    save_session_snapshot(messages)
    return False


def handle_double_interrupt():
    """连续两次 Ctrl+C：extraction + 保存并退出。

    Slice 1 P1-2 修复：复用 _run_session_end_memory_extraction()，
    确保 Ctrl+C×2 退出路径与正常 quit 路径一样执行 session-end extraction。
    """
    from agent.core import client, get_state

    print("\n\n[系统] 检测到连续中断，正在保存...")

    state = get_state()
    messages = state.conversation.messages

    # session-end memory extraction（与 finalize_session 共用同一 helper）
    _run_session_end_memory_extraction(messages, client, MODEL_NAME)

    save_session_snapshot(messages)

    if state.task.current_plan:
        save_checkpoint(state)
        print("[系统] 任务断点已更新。")

    _record_session_end(status="ok", reason="double_interrupt")
    print("[系统] 下次启动可继续未完成的任务。再见！")
