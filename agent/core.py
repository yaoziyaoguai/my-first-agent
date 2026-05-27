"""Agent 主循环：流程编排 + 模型调用 + stop_reason 分派。"""
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import agent.tools  # noqa: F401  触发所有工具注册
from agent import protocol_debug as _protocol_debug

# ⛔ DEPRECATED: _looks_like_* re-exports 仅为向后兼容保留。
# CLI meta-command 检测/渲染已提取到 agent.cli_commands。
# 测试应直接从 agent.cli_commands import，不要再经由 core.py 的别名。
#
# Why kept: 旧测试和 dogfood scripts 仍通过 core._looks_like_* 引用。
# Removal criteria: 所有外部引用迁移到 agent.cli_commands 直 import 后移除。
# Sunset: v0.4+。不新增引用到此别名。
from agent.cli_commands import (  # noqa: F401  — deprecated backward-compat re-exports
    detect_delegate_to_subagent as _looks_like_delegate_to_subagent,
)
from agent.cli_commands import (
    detect_forget_memory as _looks_like_forget_memory,
)
from agent.cli_commands import (
    detect_nl_delegation as _looks_like_nl_delegation,
)
from agent.cli_commands import (
    detect_show_memories as _looks_like_show_memories,
)
from agent.cli_commands import (
    detect_show_subagents as _looks_like_show_subagents,
)
from agent.cli_commands import (
    render_delegate_error,
    render_delegate_not_found,
    render_delegate_result,
    render_memory_forget_not_found,
    render_memory_forget_result,
    render_memory_list,
    render_subagent_list,
)
from agent.confirm_handlers import (
    ConfirmationContext,
)
from agent.context_builder import (
    build_execution_messages as build_execution_messages_from_state,
)
from agent.context_builder import (
    build_planning_messages as build_planning_messages_from_state,
)
from agent.core_contexts import (
    build_confirmation_context,
    build_loop_context,
)
from agent.display_events import (
    EVENT_ASSISTANT_DELTA,
    DisplayEvent,
    DisplayEventSink,
    RuntimeEvent,
    RuntimeEventSink,
    assistant_delta,
    control_message,
    memory_blocked_event,
    memory_confirmation_requested_event,
    memory_forgotten_event,
    memory_injected_event,
    memory_list_event,
    memory_stored_event,
    plan_confirmation_requested,
    render_runtime_event_for_cli,
    runtime_display_event,
    state_inconsistency_reset_event,
    subagent_delegated_event,
    subagent_delegating_event,
    subagent_list_event,
    tool_requested,
)
from agent.loop import LoopDependencies, run_main_loop
from agent.loop_context import LoopContext
from agent.memory import compress_history
from agent.memory_l2 import L2TriggerGuard as _L2TriggerGuard
from agent.memory_runtime import MemoryEvaluationAction, create_memory_runtime
from agent.model_call import build_default_model_client, call_model
from agent.model_output_dispatch import (
    ModelOutputDispatchDependencies,
    dispatch_model_output,
)
from agent.pending_confirmation_dispatch import dispatch_pending_confirmation
from agent.planner import format_plan_for_display, generate_plan
from agent.prompt_builder import build_system_prompt
from agent.response_handlers import (
    handle_end_turn_response,
    handle_max_tokens_response,
    handle_tool_use_response,
)
from agent.runtime_event_safety import safe_emit_runtime_event as _safe_emit_runtime_event
from agent.runtime_loop_fields import build_runtime_loop_fields
from agent.state import create_agent_state, task_status_requires_plan
from agent.tool_registry import get_model_visible_tools
from config import MAX_CONTINUE_ATTEMPTS, MODEL_NAME

DEBUG_PROTOCOL = False
# MY_FIRST_AGENT_PROTOCOL_DUMP 的实际 guard 在 agent.protocol_debug 中；
# 这里保留兼容锚点，避免外部测试/诊断脚本误判 core 默认会输出协议 dump。
_debug_print_request = _protocol_debug._debug_print_request
_debug_print_response = _protocol_debug._debug_print_response
_protocol_dump_enabled = _protocol_debug._protocol_dump_enabled



# ========== 常量 ==========


MAX_LOOP_ITERATIONS = 50              # 循环总次数兜底（防死循环）；
# v0.4 Phase 2.2-c：本常量保留为**默认值来源**，由 chat() 构造 LoopContext 时
# 引用，运行时实际读取走 loop_ctx.max_loop_iterations。同时兼容现有
# `from agent.core import MAX_LOOP_ITERATIONS` 的测试（test_bug_hunting /
# test_runtime_error_recovery 等）。后续如果引入 env / config 读取，应改为：
#   MAX_LOOP_ITERATIONS = int(os.getenv("MAX_LOOP_ITERATIONS", 50))
# 然后 chat() 仍读这个常量构造 loop_ctx。


# ========== 全局 ==========

_model_provider, client = build_default_model_client()

# Memory Kernel v1 — 模块级 MemoryRuntime 实例。
# 默认使用 InMemoryMemoryStore + 两阶段确认流程。
# store 是 in-memory-only，不进 checkpoint、不进 State、不进文件。
# v1 known limitation：模块级单例在多 session 下可能交叉污染 memory。
# 测试可通过 monkeypatch 替换 _memory_runtime。
_memory_runtime = create_memory_runtime()

# Phase 5b L2 inline extraction trigger guard（session 级）。
# 跟踪 turn count / task boundary / 预算消耗，决定何时触发 L2 extraction。
# 测试可通过 monkeypatch 替换。
_l2_trigger_guard = _L2TriggerGuard()


def get_l2_trigger_guard():
    """返回模块级 L2TriggerGuard 实例（供测试 inspection 用）。"""
    return _l2_trigger_guard


# Phase 5b L2 explicit trigger 短语（RFC §11.3 "用户显式触发"）
_EXPLICIT_L2_TRIGGERS: tuple[str, ...] = (
    "记住这个", "记录一下", "记住这些", "帮我记一下",
    "remember this", "remember these",
)


def _is_explicit_l2_trigger(text: str) -> bool:
    """检测用户输入是否包含 L2 explicit trigger 短语。

    简单关键词匹配，不调用 LLM。
    """
    text_lower = text.strip().lower()
    return any(trigger in text_lower for trigger in _EXPLICIT_L2_TRIGGERS)


# CLI meta-command detection functions (_looks_like_*) 已提取到 agent.cli_commands。
# 这里通过模块顶部的 import 保留向后兼容的模块级别名。
# 新增 CLI 命令的 detect/render 逻辑应直接写入 agent/cli_commands.py。


def _maybe_run_l2_inline(state) -> None:
    """Phase 5b L2 inline extraction thin hook。

    从 state.conversation.messages 中取最近消息，
    调用 run_l2_inline_extraction() 执行 L2 extraction + governance routing。

    不做 governance 决策，不阻塞 conversation flow。
    仅当 L2 trigger guard 判定应触发时才调用。

    当前 L2 extraction 结果未注入 prompt builder ——
    这是 Phase 5b foundation，recall/injection 留待后续。
    """
    try:
        from agent.memory_fs_store import FilesystemMemoryStore
        from agent.memory_l2 import run_l2_inline_extraction

        messages = state.conversation.messages
        # 取最近 20 条消息作为 L2 inline extraction 的 segment
        recent = list(messages[-20:]) if len(messages) > 20 else list(messages)
        if not recent:
            return

        store = FilesystemMemoryStore()
        run_l2_inline_extraction(
            recent,
            store,
            guard=_l2_trigger_guard,
        )
    except Exception:
        # L2 extraction 失败不应影响 conversation flow
        pass

# 统一会话状态：
# 先把 system prompt 放进 runtime，
# conversation / memory / task 先用默认空值初始化。
state = create_agent_state(
    system_prompt="",
    model_name=MODEL_NAME,
    review_enabled=False,
    max_recent_messages=6,
)
def get_state():
    """获取当前会话状态。"""
    return state


# ========== 循环状态 ==========

@dataclass
class TurnState:
    """一次 chat 调用内部的循环状态。

    注意：这里只保留**本次 chat 调用内**确实 ephemeral 的字段。
    所有需要跨多次 chat 调用（例如工具确认来回）累积的计数，
    都放在 state.task 上，由 handlers 直接读写。
    """
    system_prompt: str
    round_tool_traces: list = field(default_factory=list)
    # DisplayEvent 是 Runtime 到 UI 的单向投影出口。它不写入 conversation，也不让
    # tool_executor 反向依赖 TUI；simple backend 没传 sink 时会回退到 stdout。
    on_display_event: DisplayEventSink | None = None
    # RuntimeEvent 是本轮 chat 的用户可见输出总线。它只服务 UI projection，
    # 不能混入 checkpoint、runtime_observer、conversation.messages 或 Anthropic
    # API messages；这些边界仍由各自模块负责。
    on_runtime_event: RuntimeEventSink | None = None
    # TraceEvent 是 opt-in observability sink，不是 Runtime state。默认 None，
    # 不创建 recorder、不写 agent_log/sessions/runs；只有调用方显式传 sink 时才投影。
    on_trace_event: Callable[[Any], None] | None = None
    trace_run_id: str | None = None
    trace_id: str | None = None
    print_assistant_newline: bool = False


def refresh_runtime_system_prompt(dispatcher=None) -> str:
    """重新生成当前运行态实际生效的 system prompt，并写回 state。

    Loop 3 (Memory E2E) 收敛：当 dispatcher 可用时，MEMORY_RECALL 通过
    RuntimeActionDispatcher 统一 dispatch，确保 fake/real 共享核心 recall 路径。
    模块初始化时 dispatcher 为 None，回退到直接路径。
    """
    if dispatcher is not None:
        # 统一路径：通过 dispatcher dispatch MEMORY_RECALL
        from agent.runtime_integration.schema import (
            RuntimeActionRequest,
            RuntimeActionType,
        )

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_RECALL,
            source="core_loop",
            parent_trace_id="",
            payload={},
        )
        route = getattr(dispatcher, "route_from_runtime_loop", dispatcher.route)
        result = route(request)
        memory_section = result.payload.get("prompt_section", "")
        system_prompt = build_system_prompt(memory_section=memory_section)
    else:
        # 回退：模块初始化时 dispatcher 尚不可用
        memory_snapshot = _memory_runtime.snapshot_for_prompt()
        system_prompt = build_system_prompt(memory_snapshot=memory_snapshot)

    state.set_system_prompt(system_prompt)
    return state.get_system_prompt()

refresh_runtime_system_prompt()




# ========== 对外主入口 ==========


def _build_loop_context(
    client_obj,
    *,
    model_name: str = MODEL_NAME,
    max_loop_iterations: int = MAX_LOOP_ITERATIONS,
    provider=None,
    runtime_action_dispatcher=None,
) -> LoopContext:
    """兼容入口：实际 LoopContext 组装在 `agent.core_contexts`。

    provider: 可选的 ModelProvider 实例。传入则注入到 loop context，
              不传则回退到 build_model_provider_from_env()。
    runtime_action_dispatcher: Phase 1 RuntimeActionDispatcher 注入点。
    """

    return build_loop_context(
        client_obj,
        model_name=model_name,
        max_loop_iterations=max_loop_iterations,
        provider=provider,
        runtime_action_dispatcher=runtime_action_dispatcher,
    )


def _build_confirmation_context(
    *,
    state,
    turn_state,
    loop_ctx: LoopContext,
) -> ConfirmationContext:
    """兼容入口：实际 ConfirmationContext 组装在 `agent.core_contexts`。"""

    return build_confirmation_context(
        state=state,
        turn_state=turn_state,
        continue_fn=lambda ts: _run_main_loop(ts, loop_ctx),
        start_planning_fn=lambda inp, ts: _start_planning_for_handler(
            inp, ts, loop_ctx
        ),
        loop_ctx=loop_ctx,
        memory_runtime=_memory_runtime,
    )


def _dispatch_pending_confirmation(
    state,
    user_input: str,
    confirmation_ctx,
) -> str | None:
    """兼容入口：实际分派逻辑在 `agent.pending_confirmation_dispatch`。"""

    return dispatch_pending_confirmation(state, user_input, confirmation_ctx)


def _dispatch_model_output(
    response,
    *,
    turn_state: "TurnState",
) -> str | None:
    """兼容入口：实际分派逻辑在 `agent.model_output_dispatch`。"""

    dependencies = ModelOutputDispatchDependencies(
        state=state,
        handle_max_tokens_response=handle_max_tokens_response,
        handle_end_turn_response=handle_end_turn_response,
        handle_tool_use_response=handle_tool_use_response,
        extract_text=_extract_text,
        runtime_loop_fields=_runtime_loop_fields,
        safe_emit_runtime_event=_safe_emit_runtime_event,
        max_consecutive_max_tokens=MAX_CONTINUE_ATTEMPTS,
    )
    return dispatch_model_output(
        response,
        turn_state=turn_state,
        dependencies=dependencies,
    )


def _execute_subagent_delegation(
    subagent_name: str,
    task: str,
    *,
    delegation_reason: str = "CLI meta-command delegation",
    on_runtime_event: Callable[[RuntimeEvent], None] | None = None,
) -> str:
    """执行一次子代理委托并返回渲染后的用户可见结果。

    这是 CLI delegate 和 NL delegation 的共享委托执行路径。
    不做检测/解析——只做 registry lookup → SubAgentRequest 构造 →
    delegate_once() 执行 → 结果渲染。

    中文学习边界：
    - 这不是第二条 runtime——所有委托仍通过 delegate_once() + SubAgentRegistry
      执行，不绕过 core.chat() 统一入口
    - 进度事件仍通过 on_runtime_event 发射
    """
    from pathlib import Path

    from agent.subagent_system.delegation import delegate_once
    from agent.subagent_system.registry import SubAgentRegistry
    from agent.subagent_system.request import SubAgentRequest

    try:
        # RT-07: 使用 agent/subagent_system/descriptors/ 而非 tests/fixtures/subagents
        # 产品级默认不应依赖测试 fixtures。demo descriptors 显式标注 DEMO-ONLY。
        registry = SubAgentRegistry(roots=[Path("agent/subagent_system/descriptors")])
    except Exception:
        return render_delegate_error(subagent_name, "无法加载子代理注册表")
    descriptor = registry.get_descriptor(subagent_name)
    if descriptor is None:
        visible_names = [d.name for d in registry.list_visible()]
        return render_delegate_not_found(subagent_name, visible_names)
    try:
        subagent_request = SubAgentRequest(
            task=task,
            role=descriptor.role,
            allowed_tools=descriptor.allowed_tools,
            parent_trace_id=f"delegation-{uuid4().hex[:8]}",
            delegation_reason=delegation_reason,
            max_iterations=descriptor.max_iterations_default,
            execution_mode="local_fake",
            risk_level=descriptor.risk_level,
        )
    except ValueError as exc:
        return f"委托请求无效：{exc}"
    _safe_emit_runtime_event(
        on_runtime_event,
        subagent_delegating_event(subagent_name, task),
        fallback_prefix="\n",
    )
    try:
        run = delegate_once(subagent_request, registry)
    except Exception as exc:
        _safe_emit_runtime_event(
            on_runtime_event,
            subagent_delegated_event(subagent_name, "error", str(exc)),
            fallback_prefix="\n",
        )
        return render_delegate_error(subagent_name, str(exc))
    result = run.result
    status = getattr(result, "status", "unknown") if result else "unknown"
    summary = getattr(result, "summary", "") if result else ""
    stop_reason = getattr(result, "stop_reason", "") if result else ""
    confidence = getattr(result, "confidence", 0.0) if result else 0.0
    _safe_emit_runtime_event(
        on_runtime_event,
        subagent_delegated_event(subagent_name, status, summary),
        fallback_prefix="\n",
    )
    return render_delegate_result(subagent_name, status, summary, stop_reason, confidence)


def chat(
    user_input: str,
    *,
    on_output_chunk: Callable[[str], None] | None = None,
    on_display_event: Callable[[DisplayEvent], None] | None = None,
    on_runtime_event: Callable[[RuntimeEvent], None] | None = None,
    on_trace_event: Callable[[Any], None] | None = None,
    provider=None,
    runtime_action_dispatcher=None,
    tool_gate_tool_name: str | None = None,
) -> str:
    """主入口：对话 + 规划 + 工具执行。

    `on_runtime_event` 是 Runtime -> UI 用户可见输出的主路径。`on_output_chunk` 和
    `on_display_event` 只作为 deprecated compatibility bridge 保留，分别兼容旧调用方
    接收 assistant delta 和 DisplayEvent；新调用方不应继续把它们当入口。

    Sunset: on_output_chunk/on_display_event 在 v0.4+ 移除，届时所有调用方必须迁移到
    on_runtime_event。Not default path — 新代码禁止新增 on_output_chunk/on_display_event
    依赖。这个函数只迁移 UI projection，不改变 checkpoint、runtime_observer、
    conversation.messages、Anthropic API messages 或 TaskState 状态机本体。

    `on_trace_event` 是 RFC 0002 的显式 opt-in observability seam：调用方如果需要
    本地 TraceEvent，可以传 sink；默认不创建 recorder，也不把 trace 写入 durable
    Runtime/checkpoint state。

    provider: 可选的 ModelProvider 实例。传入则注入到 loop context 用于 LLM 调用；
              不传则回退到 build_model_provider_from_env()（生产默认路径）。
              这是 E2E / dogfood 测试的显式注入点。

    runtime_action_dispatcher: Phase 1 可选的 RuntimeActionDispatcher 实例。
              传入则直接注入到 loop turn-end hook；不传则在 provider 为 fake 时
              自动构建。dogfood 脚本可传入自建 dispatcher 来在 chat() 返回后
              访问 action_log。
    """

    # 空输入守卫：strip 后为空串的输入直接过滤掉。
    # 这是 chat() 内部的第二层守卫（main.py::main_loop 已有第一层），
    # 目的是让任何直接调 chat() 的前端也不会因空串触发：
    #   - 不必要的 LLM 调用（浪费 token）
    #   - awaiting 分支把空串当 feedback 触发重规划
    if not user_input or not user_input.strip():
        return ""

    # Loop 4: 提前构建 dispatcher，使 CLI READ_ONLY 命令可走统一 dispatcher 路径。
    # 需要 SubAgentRegistry（show subagents）和 _memory_runtime（show memories）。
    from pathlib import Path as _Path

    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher as _build_p1
    from agent.subagent_system.registry import SubAgentRegistry as _SubAgentRegistry

    _p1_dispatcher = _build_p1(
        memory_runtime=_memory_runtime,
        subagent_registry=_SubAgentRegistry(roots=[_Path("agent/subagent_system/descriptors")]),
    )

    # ── CLI meta-command 边界说明 ──────────────────────────────────────────
    # 中文学习边界：CLI meta-command 的检测（detect）和渲染（render）已提取到
    # agent/cli_commands.py。core.chat() 仍然是唯一统一入口，但命令解析和渲染
    # 不再散落在这里。
    #
    # 提取后的职责分工：
    # - agent/cli_commands.py：detect 函数（纯字符串匹配）+ render 函数（纯格式化）
    #   + CommandIntent typed classification（RT-02）
    # - agent/core.py：服务调用（memory_runtime、SubAgentRegistry）+ 渲染委托
    #
    # RT-02 architecture boundary（2026-05-25）:
    # 以下所有 CLI meta-command 快捷路径都是 CLI-ONLY / DEMO-ONLY。
    # 它们通过提前 return 绕过 loop.py/dispatcher/evidence path——
    # 这不是第二条 runtime，但明确不是产品主路径。
    # 当产品需要这些能力时，应通过 typed command/use-case layer 迁入
    # 统一 runtime flow，而不是继续扩展这里的 if/return 块。
    #
    # 这不是第二条 runtime——所有命令仍通过 core.chat() 进入。
    # 后续新增 CLI 命令应在 cli_commands.py 新增 detect/render 函数，
    # 并在 core.chat() 入口处新增薄调用块。
    #
    # ── Memory management CLI commands ──────────────────────────────────────
    # 检测由 agent/cli_commands 完成（纯字符串匹配）；服务调用（memory_runtime）
    # 留在 core.chat 内，不经过 command router。渲染由 cli_commands 的 render 函数完成。
    #
    # CLI-ONLY (CommandCategory.READ_ONLY): show memories
    # Loop 4: 走统一 dispatcher 路径获取 records（替代直接调用 _memory_runtime）
    if _looks_like_show_memories(user_input):
        from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType
        _req = RuntimeActionRequest(
            action_type=RuntimeActionType.CLI_SHOW_MEMORIES,
            source="core.chat",
            parent_trace_id="",
            payload={"user_input": user_input},
        )
        _result = _p1_dispatcher.route(_req)
        records = _result.payload.get("records", ()) if _result else ()
        _safe_emit_runtime_event(
            on_runtime_event,
            memory_list_event(records),
            fallback_prefix="\n",
        )
        return render_memory_list(records)

    # WP-A：forget / 忘记记忆 CLI meta-command。
    # 直接匹配 store 中 record content 并移除，不经过 policy → confirmation 管线。
    #
    # CLI-ONLY (CommandCategory.MUTATING): forget memory — 注意此命令直接操作
    # memory store，绕过 confirmation policy。产品路径下应通过 MEMORY_PROPOSE
    # → confirmation → retain 管线执行，而非此快捷方式。
    forget_keyword = _looks_like_forget_memory(user_input)
    if forget_keyword:
        # 支持按 ID 删除：forget id:<record_id>（精确匹配 + 短 ID 前缀匹配）
        #
        # 为什么显示短 ID 就必须支持短 ID 前缀匹配：
        # - show memories 输出只显示前8位短 ID，用户会自然复制使用
        # - 如果 forget 只支持完整 ID（UUID），用户永远无法用显示出来的 ID 删除
        # - 前缀匹配解决了这个距离问题
        #
        # 为什么前缀冲突必须 ambiguity 而不能误删：
        # - 8 位前缀在理论上可能碰撞（虽然实际中极少见）
        # - 误删是静默数据丢失——这对 memory governance 不可接受
        # - ambiguity 提示要求用户明确指定更多前缀位，保持用户意图为最终仲裁者
        if forget_keyword.lower().startswith("id:"):
            record_id = forget_keyword[3:].strip()
            # Step 1: 尝试精确匹配（完整 ID）
            if _memory_runtime.remove_record(record_id):
                _safe_emit_runtime_event(
                    on_runtime_event,
                    memory_forgotten_event(1, keyword=f"id:{record_id}"),
                    fallback_prefix="\n",
                )
                remaining = _memory_runtime.list_records()
                _safe_emit_runtime_event(
                    on_runtime_event,
                    memory_list_event(remaining),
                    fallback_prefix="\n",
                )
                return f"已移除记忆（ID: {record_id}）。"

            # Step 2: 精确匹配失败 → 尝试前缀匹配（支持短 ID）
            records = _memory_runtime.list_records()
            prefix_matches = [
                r for r in records
                if str(getattr(r, "id", "")).startswith(record_id)
            ]
            if len(prefix_matches) == 1:
                matched_id = prefix_matches[0].id
                if _memory_runtime.remove_record(matched_id):
                    _safe_emit_runtime_event(
                        on_runtime_event,
                        memory_forgotten_event(1, keyword=f"id:{record_id}"),
                        fallback_prefix="\n",
                    )
                    remaining = _memory_runtime.list_records()
                    _safe_emit_runtime_event(
                        on_runtime_event,
                        memory_list_event(remaining),
                        fallback_prefix="\n",
                    )
                    return f"已移除记忆（ID: {record_id} → {matched_id}）。"
                return f"移除记忆失败（ID: {matched_id}）。"
            elif len(prefix_matches) > 1:
                # 前缀匹配到多条记录 → ambiguity，不误删
                matched_ids = [str(getattr(r, "id", "?"))[:12] for r in prefix_matches]
                return (
                    f"前缀「{record_id}」匹配到 {len(prefix_matches)} 条记忆，"
                    f"无法确定要删除哪一条。请使用更长的 ID 前缀重试。\n"
                    f"匹配到的 ID：{', '.join(matched_ids)}"
                )
            # Step 3: 前缀也没有匹配 → not found
            return f"未找到 ID 为「{record_id}」的记忆。"
        # 否则按 content 关键词匹配
        records = _memory_runtime.list_records()
        matched = [
            r for r in records
            if forget_keyword.lower() in getattr(r, "content", "").lower()
        ]
        if not matched:
            return render_memory_forget_not_found(forget_keyword)
        removed_count = 0
        for r in matched:
            if _memory_runtime.remove_record(r.id):
                removed_count += 1
        _safe_emit_runtime_event(
            on_runtime_event,
            memory_forgotten_event(removed_count, keyword=forget_keyword),
            fallback_prefix="\n",
        )
        remaining = _memory_runtime.list_records()
        _safe_emit_runtime_event(
            on_runtime_event,
            memory_list_event(remaining),
            fallback_prefix="\n",
        )
        return render_memory_forget_result(forget_keyword, removed_count)

    # show subagents CLI meta-command：检测 → registry lookup → 渲染。
    # 渲染由 cli_commands.render_subagent_list 完成。
    #
    # CLI-ONLY (CommandCategory.READ_ONLY): show subagents
    # 注意：descriptors 来自 agent/subagent_system/descriptors/——显式 DEMO-ONLY。
    # 产品路径不应依赖 test fixtures（RT-07）。
    # Loop 4: 走统一 dispatcher 路径获取 descriptors（替代直接调用 SubAgentRegistry）
    if _looks_like_show_subagents(user_input):
        from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType
        _req = RuntimeActionRequest(
            action_type=RuntimeActionType.CLI_SHOW_SUBAGENTS,
            source="core.chat",
            parent_trace_id="",
            payload={"user_input": user_input},
        )
        _result = _p1_dispatcher.route(_req)
        descriptors = _result.payload.get("descriptors", ()) if _result else ()
        _safe_emit_runtime_event(
            on_runtime_event,
            subagent_list_event(descriptors),
            fallback_prefix="\n",
        )
        return render_subagent_list(descriptors)

    # delegate to subagent CLI meta-command：检测 → 委托执行 → 渲染。
    # 检测由 cli_commands 完成；_execute_subagent_delegation() 执行委托。
    #
    # CLI-ONLY (CommandCategory.DELEGATING): delegate to subagent
    delegate_match = _looks_like_delegate_to_subagent(user_input)
    if delegate_match:
        subagent_name, task = delegate_match
        delegation_result = _execute_subagent_delegation(
            subagent_name, task,
            delegation_reason="CLI meta-command delegation",
            on_runtime_event=on_runtime_event,
        )
        # 为 CLI delegation 路径 emit run summary（不经过 run_main_loop）
        from agent.display_events import run_summary_event as _run_summary_event
        _safe_emit_runtime_event(
            on_runtime_event,
            _run_summary_event(
                loop_iterations=1, tool_calls=0, memory_operations=0,
                subagent_delegations=1, stop_reason="CLI delegation",
                subagent_names=[subagent_name],
            ),
            fallback_prefix="\n",
        )
        return delegation_result

    # Issue 2: Natural-language SubAgent delegation fixture。
    # 用户无需记忆 CLI 语法即可委托子代理——"帮我统计 demo workspace"
    # 等自然语言触发 demo-stat。这是 deterministic 关键词匹配，不调 LLM。
    #
    # DEMO-ONLY (CommandCategory.DELEGATING): NL delegation fixture
    # 这是 demo fixture，不是产品级 NL 理解。产品路径下 SubAgent delegation
    # 应通过 agent-level planner/confirmation 管线，而非关键词匹配。
    nl_delegation = _looks_like_nl_delegation(user_input)
    if nl_delegation:
        subagent_name, task = nl_delegation
        delegation_result = _execute_subagent_delegation(
            subagent_name, task,
            delegation_reason="NL delegation fixture",
            on_runtime_event=on_runtime_event,
        )
        # 为 NL delegation 路径 emit run summary（不经过 run_main_loop）
        from agent.display_events import run_summary_event as _run_summary_event
        _safe_emit_runtime_event(
            on_runtime_event,
            _run_summary_event(
                loop_iterations=1, tool_calls=0, memory_operations=0,
                subagent_delegations=1, stop_reason="NL delegation",
                subagent_names=[subagent_name],
            ),
            fallback_prefix="\n",
        )
        return delegation_result

    # Memory Kernel v1：评估用户输入是否触发 explicit memory 操作。
    # 这是 core.py 对 Memory 系统的唯一薄调用——不做 policy 判断、不操作 store、
    # 不解析 decision。_memory_runtime 内部处理 policy → confirmation → store 全链路。
    # 当前 on_event 直接复用 on_runtime_event callback（如果调用方传入）。
    result = _memory_runtime.evaluate_user_text(user_input, on_event=on_runtime_event)
    if result.action is MemoryEvaluationAction.STORED:
        _safe_emit_runtime_event(
            on_runtime_event,
            memory_stored_event(result.content_summary),
            fallback_prefix="\n",
        )
    elif result.action is MemoryEvaluationAction.BLOCKED:
        _safe_emit_runtime_event(
            on_runtime_event,
            memory_blocked_event(result.reason),
            fallback_prefix="\n",
        )
    elif result.action is MemoryEvaluationAction.CONFIRMATION_REQUIRED:
        # Memory Interactive Confirmation v1：两阶段交互。
        # evaluate_user_text 已缓存 decision，这里设置 pending_user_input_request
        # 复用 awaiting_user_input 机制等待用户确认。
        confirmation_request = _memory_runtime.get_pending_confirmation(result.candidate_id)
        if confirmation_request is not None:
            from agent.checkpoint import save_checkpoint as _save_ckpt
            from agent.memory_interaction import build_memory_pending_request

            pending = build_memory_pending_request(
                confirmation_request,
                candidate_id=result.candidate_id,
                origin_status=state.task.status,
            )
            state.task.pending_user_input_request = pending
            state.task.status = "awaiting_user_input"
            _save_ckpt(state, source="memory_confirmation")
            _safe_emit_runtime_event(
                on_runtime_event,
                memory_confirmation_requested_event(pending),
                fallback_prefix="\n",
            )
            return ""

    # ── Phase 5b L2 Inline Extraction Trigger ──────────────────────────
    # 每次用户输入后：记录 turn → 检查触发条件 → 触发时执行 L2 extraction。
    # 这是 core.py 对 L2 的唯一薄调用，不做 governance 决策，不阻塞
    # conversation flow。trigger guard 独立在 memory_l2 模块中。
    _l2_trigger_guard.record_turn()
    if _l2_trigger_guard.should_trigger(
        user_input,
        is_explicit_trigger=_is_explicit_l2_trigger(user_input),
    ):
        _maybe_run_l2_inline(state)

    # 状态一致性自愈：是否必须有 current_plan 统一交给 state helper 判断。
    # 这避免 core.py 继续散落硬编码 status tuple；更细的 plan/tool/user-input
    # 维度未来再拆 schema，当前阶段只收口 invariant。
    _inconsistent = (
        task_status_requires_plan(state.task)
        and state.task.current_plan is None
    )
    if _inconsistent:
        # v0.5 第七小步 D · L306 print 迁移到 RuntimeEvent。
        # 优先走调用方传入的 ``on_runtime_event`` callback；callback 缺失时
        # 回退到 stdout，保证 simple CLI 用户仍能看到诊断（characterization
        # baseline 在 tests/test_core_loop_terminal_prints.py 钉死双向行为）。
        # 注意：本处早于 ``_emit_runtime_event`` 闭包定义、早于 ``turn_state``
        # 构造，所以不能复用闭包；只能直接拿 chat() 参数。
        _evt = state_inconsistency_reset_event(state.task.status)
        # v0.5.1 YF1：用 _safe_emit_runtime_event 包住 sink 调用，
        # 防止 callback raise 跳过下面的 state.reset_task()。
        _safe_emit_runtime_event(on_runtime_event, _evt)
        state.reset_task()

    # 注意：不要在这里无条件压缩历史。
    # 当处于 awaiting_tool_confirmation 时，上一条 assistant 里有未闭合的
    # tool_use 块，它必须与稍后的 tool_result 配对。若此刻压缩，可能把该
    # tool_use 丢进摘要，留下悬空 tool_result，下次调用 API 会直接报错。

    # Loop 3 (Memory E2E): 传入 dispatcher 统一 recall 路径
    runtime_system_prompt = refresh_runtime_system_prompt(
        dispatcher=runtime_action_dispatcher
    )

    # Memory Kernel v1：告知用户当前已加载的 memory 条数（仅在有条目时展示）。
    _memory_snapshot = _memory_runtime.snapshot_for_prompt()
    if _memory_snapshot.items:
        _safe_emit_runtime_event(
            on_runtime_event,
            memory_injected_event(len(_memory_snapshot.items)),
            fallback_prefix="\n",
        )

    def _emit_runtime_event(event: RuntimeEvent) -> None:
        """统一投递本轮用户可见输出，并集中兼容旧 callback。

        这是 core.py 内 RuntimeEvent 的唯一投递出口：Runtime 内部先生成
        RuntimeEvent，再由这里决定发给新主路径、deprecated 旧 callback，或无 sink 的
        simple CLI print fallback。旧 `on_output_chunk` / `on_display_event` 的转发必须
        保持集中，不能散落到模型流、工具执行或状态处理里；这个兼容层不能继续扩大成
        新协议，也不能承载 checkpoint、runtime_observer、conversation.messages、
        Anthropic API messages、TaskState 状态机本体、debug print 或 terminal observer
        log。
        """

        if on_runtime_event is not None:
            on_runtime_event(event)
            return

        if event.event_type == EVENT_ASSISTANT_DELTA:
            if on_output_chunk is not None:
                on_output_chunk(event.text)
                return
            print(render_runtime_event_for_cli(event), end="", flush=True)
            return

        if event.display_event is not None:
            if on_display_event is not None:
                on_display_event(event.display_event)
                return
            print(f"\n{render_runtime_event_for_cli(event)}", flush=True)
            return

        rendered = render_runtime_event_for_cli(event)
        if rendered:
            print(f"\n{rendered}", flush=True)

    def _emit_display_event(event: DisplayEvent) -> None:
        """把旧 DisplayEvent sink 收口到 RuntimeEvent，再交给统一投递桥。"""

        _emit_runtime_event(runtime_display_event(event))

    turn_state = TurnState(
        system_prompt=runtime_system_prompt,
        on_display_event=_emit_display_event,
        on_runtime_event=_emit_runtime_event,
        on_trace_event=on_trace_event,
        trace_run_id=(f"run:{uuid4().hex}" if on_trace_event is not None else None),
        trace_id=(f"trace:{uuid4().hex}" if on_trace_event is not None else None),
        print_assistant_newline=(
            on_runtime_event is None and on_output_chunk is None
        ),
    )

    # v0.4 Phase 2.1/2.2-a/2.2-b/2.2-c：构造一次 LoopContext 实例作为运行时
    # 依赖注入锚点，**整个调用链唯一构造点**。
    # - Phase 2.2-a：_run_planning_phase / _start_planning_for_handler 吃；
    # - Phase 2.2-b：_run_main_loop / _call_model 吃；
    # - Phase 2.2-c：_run_main_loop 开始消费 loop_ctx.max_loop_iterations
    #   （client / model_name 仍只在 _call_model 消费）。
    # confirm_handlers / response_handlers 仍走 ConfirmationContext，未迁移
    # （评估属未来切片）。严禁在任何 helper 内重建 LoopContext——SSOT 单源
    # 由 test_chat_remains_unique_loop_context_construction_site_in_core 钉死。
    # 模块级 MAX_LOOP_ITERATIONS 仍保留作为默认值，并兼容现有测试 import。
    #
    # v0.5 Phase 3 第一小步：构造调用走 _build_loop_context() 工厂（行为
    # 中性 helper），让 chat() 主体只剩"拿到运行时依赖"一行。SSOT 测试
    # 用 src.count 在 core.py 全文上检查 LoopContext 字面构造，构造从
    # chat() 移到 helper 后仍恰好 1 次（在 helper 内）。详见
    # _build_loop_context 顶部 docstring。
    #
    # 注意：这里**显式**把 MODEL_NAME / MAX_LOOP_ITERATIONS 作为 kwargs
    # 传入，而不是依赖 helper 的 def-time 默认值——否则
    # monkeypatch.setattr(core, "MAX_LOOP_ITERATIONS", N) 这类测试场景
    # 拿不到运行时被 patch 的值（Python 函数默认参数在 def 时求值，仅一次）。
    # 这一行写法保证 chat() 调用时**重新**读取模块级常量。
    # Phase 1: 构建 RuntimeActionDispatcher 并通过 LoopContext 注入到 loop turn-end hook。
    # 优先使用调用方传入的 dispatcher（dogfood/测试注入点）；否则自动构建默认 dispatcher。
    #
    # 中文学习边界：dispatcher 是 provider-neutral runtime logic——不调用 LLM、
    # 不读 .env、不访问网络。RT-01 修复：所有 provider 类型统一自动构建 dispatcher，
    # 确保 fake/real 共享同一 evidence path，不因 provider type 产生证据路径分歧。
    #
    # 构建本身无副作用：只有 loop turn-end 时 dispatcher.route() 才被调用。
    # Loop 4: _p1_dispatcher 已在函数开头构建（用于 CLI READ_ONLY 命令走统一 dispatcher）。
    # 调用方注入的 runtime_action_dispatcher 优先（dogfood/测试注入点），
    # 否则复用 _p1_dispatcher。
    if runtime_action_dispatcher is not None:
        _phase1_dispatcher = runtime_action_dispatcher
        _skill_registry = None
    else:
        _phase1_dispatcher = _p1_dispatcher
        _skill_registry = None

    _loop_ctx = _build_loop_context(
        client,
        model_name=MODEL_NAME,
        max_loop_iterations=MAX_LOOP_ITERATIONS,
        provider=provider,
        runtime_action_dispatcher=_phase1_dispatcher,
    )

    # v0.5 Phase 3 第二小步：ConfirmationContext 构造走 _build_confirmation_context()
    # 工厂（行为中性 helper），与 _loop_ctx 抽 helper 形成对称结构——chat() 头部
    # 现在是清晰的"两行拿依赖"。client / model_name 来源从 module globals 切到
    # loop_ctx 字段（值等价：loop_ctx 也是由同一组 module globals 构造的）。
    # SSOT 测试 ``test_chat_remains_unique_confirmation_context_construction_site_in_core``
    # 钉死全文 ``ConfirmationContext`` 恰好 1 次。详见 _build_confirmation_context
    # 顶部 docstring。
    confirmation_ctx = _build_confirmation_context(
        state=state,
        turn_state=turn_state,
        loop_ctx=_loop_ctx,
    )

    # v0.5.1 第三小步：5 条 pending confirmation 分支抽进
    # ``_dispatch_pending_confirmation`` helper（纯函数提取，行为与提取前
    # 字面等价）。helper 返回 None 表示 fallthrough 到下方"压缩 + 新任务"
    # 路径；返回 str 表示已被某个 confirmation handler 接管。
    # baseline 由 tests/test_pending_confirmation_dispatch.py 11 条
    # characterization tests 钉死（cdd1427）。详见 helper docstring。
    _dispatched = _dispatch_pending_confirmation(state, user_input, confirmation_ctx)
    if _dispatched is not None:
        return _dispatched

    _compress_history_and_sync_checkpoint(_loop_ctx)

    # 如果当前已有运行中的任务，则默认把这次输入视为"继续当前任务"的反馈。
    if state.task.current_plan and state.task.status == "running":
        state.conversation.messages.append({"role": "user", "content": user_input})
        return _run_main_loop(
            turn_state, _loop_ctx,
            tool_gate_tool_name=tool_gate_tool_name, skill_registry=_skill_registry,
        )

    # 到这里意味着要开启一轮全新的任务。
    # 用 state.reset_task() 一次性清干净 task 层所有字段，避免"单步任务收尾
    # 不触发 done 路径、tool_execution_log / pending_tool 残留到下一个任务"
    # 这种 bug。之前这里只重置 4 个计数字段，其他字段（log/pending/user_goal
    # 等）都有可能带着旧值进新任务。
    state.reset_task()

    plan_result = _run_planning_phase(user_input, turn_state, _loop_ctx)
    return _handle_planning_phase_result(
        plan_result, turn_state, _loop_ctx,
        tool_gate_tool_name=tool_gate_tool_name, skill_registry=_skill_registry,
    )


# ========== 规划阶段 ==========


def _compress_history_and_sync_checkpoint(loop_ctx: LoopContext) -> None:
    """压缩历史并同步 active task checkpoint；不改变 checkpoint schema。"""

    # 到这里才是真正的「新一轮对话」：可以安全做压缩。
    messages = state.conversation.messages
    compressed_messages, new_summary = compress_history(
        messages,
        loop_ctx.client,
        existing_summary=state.memory.working_summary,
        max_recent_messages=state.runtime.max_recent_messages,
    )
    compression_happened = (
        compressed_messages is not messages or new_summary != state.memory.working_summary
    )
    state.conversation.messages = compressed_messages
    state.memory.working_summary = new_summary
    # 压缩真实发生且当前存在运行中任务时，立刻落盘，避免 summary 与 checkpoint 不一致。
    if compression_happened and state.task.current_plan:
        from agent.checkpoint import save_checkpoint as _save_checkpoint

        _save_checkpoint(state)


def _run_planning_phase(
    user_input: str,
    turn_state: TurnState,
    loop_ctx: LoopContext,
) -> str:
    """任务规划阶段；只推进 planning 状态并通过 RuntimeEvent 展示计划。"""
    plan = generate_plan(
        user_input,
        loop_ctx.client,
        loop_ctx.model_name,
        build_planning_messages_from_state(state, user_input),
    )

    # 无论走哪条分支，用户原始输入都必须归档到 conversation.messages。
    # 否则「多步计划 → y 确认 → 执行」路径里，执行阶段模型看不到用户原话，
    # 只能依赖 planner 的二次总结 plan.goal，丢失细节。
    state.conversation.messages.append({"role": "user", "content": user_input})

    if not plan:
        # 这里可能是：planner 判定单步任务，或 planner 自身出错。
        # 单步分支是预期路径；但出错也会走这里，给用户一行轻量提示以便察觉。
        if turn_state.on_runtime_event is not None:
            turn_state.on_runtime_event(control_message("[系统] 未生成多步计划，按单步处理。"))
        return "ok"

    state.task.current_plan = plan.model_dump()
    state.task.user_goal = user_input
    state.task.current_step_index = 0
    state.task.confirm_each_step = any(
        marker in user_input
        for marker in (
            "每步确认",
            "每一步确认",
            "每一步都确认",
            "每步都确认",
            "每一步都让我确认",
            "每步都让我确认",
            "做完一步问我",
            "每做完一步问我",
            "一步一确认",
            "每步推理",
            "每一步推理",
            "逐步推理",
            "一步一步推理",
            "不要自动下一步",
            "不要自动继续",
            "先别自动执行下一步",
        )
    )
    state.task.status = "awaiting_plan_confirmation"

    # 一旦计划生成完毕且状态切到 awaiting_plan_confirmation，必须立刻落盘。
    # 否则用户此时 Ctrl+C，计划会完全丢失、重启后无感。
    from agent.checkpoint import save_checkpoint as _save_checkpoint
    _save_checkpoint(state)

    # 计划展示给用户，但此时还没有正式接受执行。RuntimeEvent 只投影 UI，不改变
    # current_plan / checkpoint / conversation.messages 的业务边界。
    if turn_state.on_runtime_event is not None:
        turn_state.on_runtime_event(
            plan_confirmation_requested(
                f"{format_plan_for_display(plan)}\n按此计划执行吗？(y/n/输入修改意见):",
                metadata={"source": "planning_phase"},
            )
        )
    return "awaiting_plan_confirmation"


def _handle_planning_phase_result(
    plan_result: str,
    turn_state: TurnState,
    loop_ctx: LoopContext,
    *,
    tool_gate_tool_name: str | None = None,
    skill_registry: Any = None,
) -> str:
    """统一处理 planning 的 cancelled / awaiting / ok 三种结果。"""

    if plan_result == "cancelled":
        return "好的，已取消。"
    if plan_result == "awaiting_plan_confirmation":
        return ""
    return _run_main_loop(
        turn_state, loop_ctx,
        tool_gate_tool_name=tool_gate_tool_name, skill_registry=skill_registry,
    )


def _start_planning_for_handler(
    user_input: str,
    turn_state: TurnState,
    loop_ctx: LoopContext,
) -> str:
    """供 confirm_handlers 复用的新任务 planning 出口；只做控制流路由。"""

    plan_result = _run_planning_phase(user_input, turn_state, loop_ctx)
    return _handle_planning_phase_result(plan_result, turn_state, loop_ctx)


# ========== 主循环 ==========


def _resolve_provider_evidence_metadata(provider: Any) -> tuple[str, bool]:
    """预解析 provider 的 coarse-grained runtime evidence metadata。

    中文学习边界——为什么在构造点预解析而非在消费点（loop.py）派生：
    1. core.py 是 provider 信息的「构造点」——LoopDependencies 在这里组装，
       在这里解析 provider metadata 是信息在「最完整的地方」被处理。
    2. loop.py 是「消费点」——它不应知道 provider 的结构、类型体系、白名单。
       LoopDependencies 只接收已解析的 string/bool，保持 loop 的 provider-agnostic。
    3. 如果未来新增 provider 类型，只需更新此处的白名单，loop.py 零改动。

    为什么 provider_kind 只允许 coarse-grained 三态（fake/real/unknown）：
    - raw provider_type（如 "anthropic_native"）是 provider 实现细节，
      不应泄漏到 evidence 的 provider_kind 字段
    - evidence 消费者只需要知道「是否真实 API」这种粗粒度分类
    - 精确的 provider_type 通过 evidence_extra 的 provider_type 字段保留
    - 不回退到 type(provider).__name__：class name 是实现细节

    为什么 provider_external_call 和 external_side_effects 拆开：
    - provider_external_call: provider 本身是否调用了真实外部 API（由 provider 类型决定）
    - external_side_effects: 整个 turn 是否有工具/文件/MCP/memory retain 等副作用
    - 一个 real Anthropic provider 在 real smoke 场景下 provider_external_call=True
      （确实调了 API），但 external_side_effects=False（没有工具/文件/memory retain）
    - 这两个概念正交，不应从 provider 类型推导 external_side_effects

    返回值：
        (provider_kind, provider_external_call)
        - provider_kind: "fake" | "real" | "unknown"
        - provider_external_call: bool

    安全边界：
    - 只读 provider.provider_type 类属性（字符串常量），不读 .env / os.environ
    - 不访问 API key 或任何 secret
    - 未知/缺失 provider_type → fail-closed ("unknown", False)
    """
    if provider is None:
        return ("unknown", False)

    pt = getattr(provider, "provider_type", None)
    if not isinstance(pt, str) or not pt:
        # 空字符串或非字符串 → fail-closed
        return ("unknown", False)

    if pt == "fake":
        return ("fake", False)

    # 白名单归一化：所有已知真实 provider 类型归一化为 "real"
    if pt in (
        "anthropic_native", "anthropic_compatible",
        "openai_native", "openai_compatible",
    ):
        return ("real", True)

    # 未知 provider_type → fail-closed：不 overclaim real
    return ("unknown", False)


def _runtime_loop_fields() -> dict:
    """提取主循环观测字段，只用于日志，不参与业务判断。"""

    return build_runtime_loop_fields(state)

def _run_main_loop(
    turn_state: TurnState,
    loop_ctx: LoopContext,
    *,
    tool_gate_tool_name: str | None = None,
    skill_registry: Any = None,
) -> str:
    """兼容旧测试/调用方的 core-level 主循环入口。

    实际 orchestration 已迁入 `agent.loop.run_main_loop`。这里保留同名 public
    helper，是为了不破坏现有测试和内部调用点；它只组装依赖，不重新承载 loop
    业务逻辑。

    Phase 1 hook 参数化：在构造 LoopDependencies 之前预解析 provider evidence
    metadata，确保 loop.py 不接触 provider 对象，只接收 coarse-grained string/bool。
    """

    from agent.checkpoint import clear_checkpoint as _clear_checkpoint

    # 在构造点预解析 provider metadata，而非在消费点（loop.py）派生
    # 这保证 loop.py 保持 provider-agnostic——只接收已解析的 string/bool
    resolved_kind, resolved_call = _resolve_provider_evidence_metadata(
        loop_ctx.model_provider
    )

    # 共享可变列表：call_model() 通过 _streaming_events_out 填充，
    # turn-end hook 从 dependencies.streaming_events 读取
    _streaming_events: list = []

    # 按位参数构造 LoopDependencies。tool_gate_tool_name 仅在显式传入时覆盖默认值
    # "_safe_noop"，避免 None 覆盖 dataclass 默认值。
    _deps_fields: dict[str, Any] = dict(
        state=state,
        call_model=lambda ts, lc, _out=_streaming_events: _call_model(
            ts, lc, _streaming_events_out=_out
        ),
        dispatch_model_output=lambda response: _dispatch_model_output(
            response,
            turn_state=turn_state,
        ),
        runtime_loop_fields=_runtime_loop_fields,
        safe_emit_runtime_event=lambda sink, event: _safe_emit_runtime_event(
            sink,
            event,
            fallback_prefix="\n",
        ),
        clear_checkpoint=_clear_checkpoint,
        runtime_action_dispatcher=loop_ctx.runtime_action_dispatcher,
        provider_kind=resolved_kind,
        provider_external_call=resolved_call,
        provider_supports_streaming=bool(
            getattr(loop_ctx.model_provider, "supports_streaming", False)
        ),
        streaming_events=_streaming_events,
        # trace infrastructure: 从 TurnState 线程化注入 trace sink 到 LoopDependencies
        on_trace_event=getattr(turn_state, "on_trace_event", None),
        trace_run_id=getattr(turn_state, "trace_run_id", None),
        trace_id=getattr(turn_state, "trace_id", None),
        skill_registry=skill_registry,
    )
    if tool_gate_tool_name is not None:
        _deps_fields["tool_gate_tool_name"] = tool_gate_tool_name
    dependencies = LoopDependencies(**_deps_fields)
    return run_main_loop(turn_state, loop_ctx, dependencies)



def _call_model(
    turn_state: TurnState,
    loop_ctx: LoopContext,
    *,
    _streaming_events_out: list | None = None,
):
    """调用模型并返回 response；provider 依赖只从 LoopContext 读取。"""
    # ===== 协议观察：构造 request payload 并打印 =====
    request_messages = build_execution_messages_from_state(state)
    # _debug_print_request(turn_state.system_prompt, request_messages, get_tool_definitions())

    response = call_model(
        provider=getattr(loop_ctx, "model_provider", None),
        legacy_client=loop_ctx.client,
        model_name=loop_ctx.model_name,
        system_prompt=turn_state.system_prompt,
        messages=request_messages,
        tools=get_model_visible_tools(max_mcp_tools=5),
        emit_text_delta=(
            (lambda text: turn_state.on_runtime_event(assistant_delta(text)))
            if turn_state.on_runtime_event is not None
            else None
        ),
        emit_tool_request=(
            (lambda: turn_state.on_runtime_event(tool_requested()))
            if turn_state.on_runtime_event is not None
            else None
        ),
        print_assistant_newline=turn_state.print_assistant_newline,
        _streaming_events_out=_streaming_events_out,
    )

    # ===== 协议观察：打印返回结构 =====
    # _debug_print_response(response)

    return response




# ========== 辅助 ==========

def _extract_text(content_blocks) -> str:
    parts = [block.text for block in content_blocks if block.type == "text"]
    return "\n".join(p for p in parts if p).strip()
