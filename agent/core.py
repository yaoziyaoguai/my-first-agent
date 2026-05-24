"""Agent 主循环：流程编排 + 模型调用 + stop_reason 分派。"""
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4
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
    memory_injected_event,
    memory_list_event,
    memory_stored_event,
    subagent_list_event,
    plan_confirmation_requested,
    render_runtime_event_for_cli,
    runtime_display_event,
    state_inconsistency_reset_event,
    tool_requested,
)
from agent.core_contexts import (
    build_confirmation_context,
    build_loop_context,
)
from agent.loop import LoopDependencies, run_main_loop
from agent.model_output_dispatch import (
    ModelOutputDispatchDependencies,
    dispatch_model_output,
)
from agent.pending_confirmation_dispatch import dispatch_pending_confirmation
from agent.model_call import build_default_model_client, call_model
from agent import protocol_debug as _protocol_debug
from agent.runtime_event_safety import safe_emit_runtime_event as _safe_emit_runtime_event
from agent.runtime_loop_fields import build_runtime_loop_fields
from agent.prompt_builder import build_system_prompt
from agent.state import create_agent_state, task_status_requires_plan
import agent.tools  # noqa: F401  触发所有工具注册
from agent.memory_l2 import L2TriggerGuard as _L2TriggerGuard



from config import MODEL_NAME, MAX_CONTINUE_ATTEMPTS
from agent.memory import compress_history
from agent.planner import generate_plan, format_plan_for_display
from agent.tool_registry import get_model_visible_tools
from agent.context_builder import (
    build_planning_messages as build_planning_messages_from_state,
    build_execution_messages as build_execution_messages_from_state,
)


from agent.confirm_handlers import (
    ConfirmationContext,
)

from agent.response_handlers import (
    handle_end_turn_response,
    handle_max_tokens_response,
    handle_tool_use_response,
)
from agent.loop_context import LoopContext
from agent.memory_runtime import MemoryEvaluationAction, create_memory_runtime

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


def _looks_like_show_memories(text: str) -> bool:
    """检测用户输入是否为"查看记忆"CLI 命令。

    中文学习边界：这是 deterministic CLI meta-command 检测，
    不是 memory operation。它不进入 policy → confirmation → store pipeline，
    只读取当前 store 中的 records 并展示给用户。

    支持的触发词（中英文）：
    - show memories / list memories / show my memories
    - 显示记忆 / 列出记忆 / 查看记忆 / 我的记忆 / 已保存的记忆
    """
    text_lower = text.strip().lower()
    show_triggers = (
        "show memories", "list memories", "show my memories",
        "显示记忆", "列出记忆", "查看记忆", "我的记忆", "已保存的记忆",
        "记忆列表", "查看已保存",
    )
    return any(trigger in text_lower for trigger in show_triggers)


def _looks_like_forget_memory(text: str) -> str | None:
    """检测用户输入是否为"忘记记忆"CLI 命令，返回待匹配的内容关键词。

    WP-A：deteministic CLI meta-command——不经过 policy → confirmation 管线，
    直接操作 store 移除匹配 record。返回 None 表示不是 forget 命令。

    支持的触发模式（中英文）：
    - forget <content keyword>
    - 忘记 <content keyword>
    - remove memory <content keyword>
    - 删除记忆 <content keyword>
    """
    import re

    text_stripped = text.strip()
    text_lower = text_stripped.lower()
    forget_prefixes = (
        "forget ", "忘记", "remove memory ", "remove memories ",
        "删除记忆", "删掉记忆", "清除记忆",
    )
    for prefix in forget_prefixes:
        if text_lower.startswith(prefix):
            remainder = text_stripped[len(prefix):].strip()
            if remainder:
                return remainder
            return None
    # 也支持 "请忘记 X" 等中间形式
    m = re.match(r".*?(?:forget|忘记|删除记忆|删掉记忆)\s+(.+)", text_lower)
    if m:
        return text_stripped[m.start(1):].strip() or None
    return None


def _looks_like_show_subagents(text: str) -> bool:
    """检测用户输入是否为"查看子代理"CLI 命令。

    中文学习边界：这是 deterministic CLI meta-command 检测，
    不触发 delegation、不执行 subagent、不写 store。

    支持的触发词（中英文）：
    - show subagents / list subagents / show agents
    - 显示子代理 / 列出子代理 / 查看子代理 / 子代理列表
    """
    text_lower = text.strip().lower()
    show_triggers = (
        "show subagents", "list subagents", "show agents",
        "显示子代理", "列出子代理", "查看子代理", "子代理列表",
    )
    return any(trigger in text_lower for trigger in show_triggers)


def _looks_like_delegate_to_subagent(text: str) -> tuple[str, str] | None:
    """检测用户输入是否为"委托子代理"CLI 命令，返回 (subagent_name, task)。

    中文学习边界：这是 deterministic CLI meta-command 检测，
    不调用 LLM、不经过 tool pipeline、不写 store。
    实际 delegation 执行走 agent.subagent_system.delegation.delegate_once()，
    复用 SubAgentRegistry + SubAgentRequest + execute_local 的已有基础设施。

    支持的触发模式：
    - delegate to <name>: <task>
    - 委托 <name>: <task> / 委托 <name>：<task>
    - delegate <task> to <name>
    """
    import re

    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    # Pattern 1: "delegate to <name>: <task>"
    m = re.match(r"delegate\s+to\s+(\S+)\s*:\s*(.+)", text_lower)
    if m:
        return (m.group(1), text_stripped[m.start(2):].strip())

    # Pattern 2: "委托 <name>: <task>" (支持中英文冒号)
    m = re.match(r"委托\s+(\S+)\s*[:：]\s*(.+)", text_stripped)
    if m:
        return (m.group(1), m.group(2).strip())

    # Pattern 3: "delegate <task> to <name>"
    m = re.match(r"delegate\s+(.+)\s+to\s+(\S+)", text_lower)
    if m:
        return (m.group(2), text_stripped[m.start(1):m.end(1)].strip())

    return None


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
        from agent.memory_l2 import run_l2_inline_extraction
        from agent.memory_fs_store import FilesystemMemoryStore

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


def refresh_runtime_system_prompt() -> str:
    """
    重新生成当前运行态实际生效的 system prompt，并写回 state。

    注意：
    - 当前阶段仍然沿用 build_system_prompt() 作为 system prompt 的生成器
    - 但最终真正生效的结果，以 state.runtime.system_prompt 为准
    - Memory Kernel v1：从 _memory_runtime 获取 MemorySnapshot 并传入
      build_system_prompt；无已批准 memory 时 snapshot 为空，不影响 prompt。
    """
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
    接收 assistant delta 和 DisplayEvent；新调用方不应继续把它们当入口。这个函数
    只迁移 UI projection，不改变 checkpoint、runtime_observer、conversation.messages、
    Anthropic API messages 或 TaskState 状态机本体。

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

    # ── Memory management CLI commands ──────────────────────────────────────
    # 中文学习边界：show memories / 显示记忆 是 CLI meta-command，不是 memory
    # 操作。它不经过 policy → confirmation → store pipeline，只是读取当前 store
    # 中的 records 并展示给用户。这是 core.chat 中的 "外层读"，不改变 unified
    # runtime flow。
    if _looks_like_show_memories(user_input):
        records = _memory_runtime.list_records()
        _safe_emit_runtime_event(
            on_runtime_event,
            memory_list_event(records),
            fallback_prefix="\n",
        )
        return "\n".join(
            [getattr(r, "content", str(r))[:120] for r in records]
        ) if records else "暂无已保存的记忆。"

    # WP-A：forget / 忘记记忆 CLI meta-command。
    # 直接匹配 store 中 record content 并移除，不经过 policy → confirmation 管线。
    forget_keyword = _looks_like_forget_memory(user_input)
    if forget_keyword:
        records = _memory_runtime.list_records()
        matched = [r for r in records if forget_keyword.lower() in getattr(r, "content", "").lower()]
        if not matched:
            return f"未找到匹配「{forget_keyword}」的记忆。"
        removed_count = 0
        for r in matched:
            if _memory_runtime.remove_record(r.id):
                removed_count += 1
        # 通知 RuntimeEvent 监听者 memory 已变更
        remaining = _memory_runtime.list_records()
        _safe_emit_runtime_event(
            on_runtime_event,
            memory_list_event(remaining),
            fallback_prefix="\n",
        )
        return f"已移除 {removed_count} 条记忆（匹配「{forget_keyword}」）。"

    # 中文学习边界：show subagents / 显示子代理 是 CLI meta-command，
    # 不触发 delegation、不执行 subagent、不写 store。
    if _looks_like_show_subagents(user_input):
        from pathlib import Path
        from agent.subagent_system.registry import SubAgentRegistry

        try:
            registry = SubAgentRegistry(roots=[Path("tests/fixtures/subagents")])
            descriptors = registry.list_visible()
        except Exception:
            descriptors = ()

        _safe_emit_runtime_event(
            on_runtime_event,
            subagent_list_event(descriptors),
            fallback_prefix="\n",
        )
        if descriptors:
            lines = [f"已注册的子代理（共 {len(descriptors)} 个）："]
            for i, d in enumerate(descriptors, 1):
                name = getattr(d, "name", str(d))
                role = getattr(d, "role", "")
                desc = getattr(d, "description", "")[:80]
                lines.append(f"  {i}. {name} [{role}] — {desc}")
            return "\n".join(lines)
        return "暂无已注册的子代理。"

    # 中文学习边界：delegate to <name>: <task> / 委托 <name>: <task> 是 CLI
    # meta-command。不经过 tool pipeline、不调用 LLM、不修改 state。
    # 实际 delegation 执行走 agent.subagent_system.delegation.delegate_once()，
    # 复用已有 SubAgentRegistry + SubAgentRequest + execute_local 基础设施，
    # 不与 unified runtime flow 形成第二条路径。
    delegate_match = _looks_like_delegate_to_subagent(user_input)
    if delegate_match:
        from pathlib import Path
        from agent.subagent_system.delegation import delegate_once
        from agent.subagent_system.registry import SubAgentRegistry
        from agent.subagent_system.request import SubAgentRequest

        subagent_name, task = delegate_match
        try:
            registry = SubAgentRegistry(roots=[Path("tests/fixtures/subagents")])
        except Exception:
            return f"无法加载子代理注册表。「{subagent_name}」不可用。"
        descriptor = registry.get_descriptor(subagent_name)
        if descriptor is None:
            visible_names = [d.name for d in registry.list_visible()]
            hint = f"可用子代理：{', '.join(visible_names)}" if visible_names else "暂无已注册的子代理"
            return f"未找到子代理「{subagent_name}」。{hint}。"
        try:
            subagent_request = SubAgentRequest(
                task=task,
                role=descriptor.role,
                allowed_tools=descriptor.allowed_tools,
                parent_trace_id=f"cli-delegation-{uuid4().hex[:8]}",
                delegation_reason="CLI meta-command delegation",
                max_iterations=descriptor.max_iterations_default,
                execution_mode="local_fake",
                risk_level=descriptor.risk_level,
            )
        except ValueError as exc:
            return f"委托请求无效：{exc}"
        try:
            run = delegate_once(subagent_request, registry)
        except Exception as exc:
            return f"子代理执行失败：{exc}"
        result = run.result
        status = getattr(result, "status", "unknown") if result else "unknown"
        summary = getattr(result, "summary", "") if result else ""
        stop_reason = getattr(result, "stop_reason", "") if result else ""
        confidence = getattr(result, "confidence", 0.0) if result else 0.0
        parts = [
            f"[SubAgent: {subagent_name}]",
            f"状态: {status}",
        ]
        if stop_reason:
            parts.append(f"停止原因: {stop_reason}")
        if summary:
            parts.append(f"摘要: {summary}")
        if confidence > 0:
            parts.append(f"置信度: {confidence:.0%}")
        return "\n".join(parts)

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
            from agent.memory_interaction import build_memory_pending_request
            from agent.checkpoint import save_checkpoint as _save_ckpt

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

    runtime_system_prompt = refresh_runtime_system_prompt()

    # Memory Kernel v1：告知用户当前已加载的 memory 条数（仅在有条目时展示）。
    # 这里再次调用 snapshot_for_prompt() 以获取条数——与 refresh_runtime_system_prompt
    # 内部的调用是重复的，但 _noop_event_logger 下不产生副作用，且避免改函数签名。
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
    # 优先使用调用方传入的 dispatcher（dogfood/测试注入点）；其次在 provider 为 fake 时自动构建。
    # 构建本身无副作用：只有 loop turn-end 时 dispatcher.route() 才被调用。
    if runtime_action_dispatcher is not None:
        _phase1_dispatcher = runtime_action_dispatcher
        _skill_registry = None
    elif getattr(provider, "provider_type", None) == "fake":
        from agent.runtime_integration.phase1_hook import build_phase1_dispatcher, build_skill_registry

        _phase1_dispatcher = build_phase1_dispatcher()
        _skill_registry = build_skill_registry()
    else:
        _phase1_dispatcher = None
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
        return _run_main_loop(turn_state, _loop_ctx, tool_gate_tool_name=tool_gate_tool_name, skill_registry=_skill_registry)

    # 到这里意味着要开启一轮全新的任务。
    # 用 state.reset_task() 一次性清干净 task 层所有字段，避免"单步任务收尾
    # 不触发 done 路径、tool_execution_log / pending_tool 残留到下一个任务"
    # 这种 bug。之前这里只重置 4 个计数字段，其他字段（log/pending/user_goal
    # 等）都有可能带着旧值进新任务。
    state.reset_task()

    plan_result = _run_planning_phase(user_input, turn_state, _loop_ctx)
    return _handle_planning_phase_result(plan_result, turn_state, _loop_ctx, tool_gate_tool_name=tool_gate_tool_name, skill_registry=_skill_registry)


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
    return _run_main_loop(turn_state, loop_ctx, tool_gate_tool_name=tool_gate_tool_name, skill_registry=skill_registry)


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
        provider_supports_streaming=bool(getattr(loop_ctx.model_provider, "supports_streaming", False)),
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
