"""Agent 主循环：流程编排 + 模型调用 + stop_reason 分派。"""
import contextlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import agent.tools  # noqa: F401  触发所有工具注册

# ⛔ DEPRECATED: _looks_like_* re-exports 仅为向后兼容保留。
# CLI meta-command 检测/渲染已提取到 agent.cli_commands。
# 测试应直接从 agent.cli_commands import，不要再经由 core.py 的别名。
#
# Why kept: 旧测试和 dogfood scripts 仍通过 core._looks_like_* 引用。
# Removal criteria: 所有外部引用迁移到 agent.cli_commands 直 import 后移除。
# Sunset: v0.4+。不新增引用到此别名。
from agent import cli_commands as _cli_commands
from agent import protocol_debug as _protocol_debug

# B7: skill_state 提取 _skill_selected_by_model / _active_skill 到独立模块，
# 打破 agent.core ↔ agent.loop 和 agent.core ↔ agent.skill_system.skill_tool
# 两对直接模块循环。core/loop/skill_tool 现在共享 import 本模块，无循环。
from agent import skill_state as _skill_state
from agent.cli_commands import (
    detect_delegate_to_subagent as _looks_like_delegate_to_subagent,
)
from agent.cli_commands import (
    detect_nl_delegation as _looks_like_nl_delegation,
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
    memory_injected_event,
    memory_stored_event,
    plan_confirmation_requested,
    render_runtime_event_for_cli,
    runtime_display_event,
    state_inconsistency_reset_event,
    tool_requested,
)
from agent.logger import log_event
from agent.loop import LoopDependencies, run_main_loop
from agent.loop_context import LoopContext
from agent.memory import compress_history, set_working_summary_scratchpad
from agent.memory_l2 import L2TriggerGuard as _L2TriggerGuard
from agent.memory_runtime import MemoryEvaluationAction, create_memory_runtime
from agent.model_call import build_default_model_client, call_model
from agent.model_output_dispatch import (
    ModelOutputDispatchDependencies,
    dispatch_model_output,
)
from agent.pending_confirmation_dispatch import dispatch_pending_confirmation
from agent.planner import (
    ACTION_PLAN_PROMPT,
    SCHEMA_REPAIR_PROMPT,
    format_action_plan_for_display,
    format_plan_for_display,  # ⛔ LEGACY: Sunset v0.5+
    validate_action_plan_raw,
)
from agent.prompt_builder import build_system_prompt
from agent.provider.protocol import (
    ProviderError,
    ProviderResponse,
)
from agent.provider_evidence import (
    resolve_provider_evidence_metadata as _resolve_provider_evidence_metadata,
)
from agent.response_handlers import (
    handle_end_turn_response,
    handle_max_tokens_response,
    handle_tool_use_response,
)
from agent.runtime_decision_frame import (
    build_decision_frame_from_chat_params as _build_decision_frame,
)
from agent.runtime_decision_frame import (
    set_last_decision_frame as _set_last_decision_frame,
)
from agent.runtime_event_safety import safe_emit_runtime_event as _safe_emit_runtime_event
from agent.runtime_loop_fields import build_runtime_loop_fields
from agent.skill_system.lifecycle import get_default_lifecycle as _get_lifecycle
from agent.skill_system.prompt_section import build_skill_selection_section
from agent.skill_system.retriever import SkillCandidateRetriever
from agent.state import create_agent_state, task_status_requires_plan
from agent.subagent_inline import execute_subagent_delegation as _execute_subagent_delegation
from agent.tool_registry import TOOL_REGISTRY, get_model_visible_tools
from agent.transitions import (
    CheckpointAction,
    TaskTransitionRequest,
    TransitionEvent,
    apply_task_transition,
    validate_task_transition,
)
from config import MAX_CONTINUE_ATTEMPTS, MODEL_NAME

_looks_like_show_memories = _cli_commands.detect_show_memories
_looks_like_forget_memory = _cli_commands.detect_forget_memory
_looks_like_show_subagents = _cli_commands.detect_show_subagents


def _record_core_evidence(
    operation: str,
    status: str,
    safe_summary: str,
    *,
    metadata: dict | None = None,
) -> None:
    """core Runtime branch point 统一 evidence 接入。

    保留 legacy log_event 作为 compatibility，但 Runtime 事实源必须是
    record_evidence。此 helper 避免在多个调用点重复 try/except/import。
    """
    try:
        from agent.evidence_recorder import record_evidence
        record_evidence(
            subsystem="core",
            operation=operation,
            phase="end" if status in ("ok", "skipped") else "error",
            status=status,
            safe_summary=safe_summary,
            metadata=metadata or {},
        )
    except Exception:
        pass

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

# Memory Kernel v1 — per-session MemoryRuntime registry。
# 默认使用 InMemoryMemoryStore + 两阶段确认流程。
# store 是 in-memory-only，不进 checkpoint、不进 State、不进文件。
# B7: per-session 隔离——非默认 session_id 拥有独立 MemoryRuntime 实例，
# 避免多 session 交叉污染 memory。
# 测试可通过 monkeypatch 替换 _default_memory_runtime 或 _memory_runtime_registry。
_default_memory_runtime = create_memory_runtime()
_memory_runtime_registry: dict[str, Any] = {}


def get_memory_runtime(session_id: str = "") -> Any:
    """获取指定 session 的 MemoryRuntime 实例。

    B7: per-session namespace 隔离。
    - session_id 为空或 "default" → 返回 _memory_runtime（向后兼容别名，支持 monkeypatch）
    - session_id 非默认 → 从 _memory_runtime_registry 查找/创建独立实例
    """
    if not session_id or session_id == "default":
        return _memory_runtime
    if session_id not in _memory_runtime_registry:
        _memory_runtime_registry[session_id] = create_memory_runtime()
    return _memory_runtime_registry[session_id]


# 向后兼容别名 —— 无参代码仍可用 _memory_runtime 访问默认实例。
_memory_runtime = _default_memory_runtime

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


def _maybe_run_l2_inline(state) -> dict | None:
    """Phase 5b L2 inline extraction thin hook。

    从 state.conversation.messages 中取最近消息，
    调用 run_l2_inline_extraction() 执行 L2 extraction + governance routing。

    不做 governance 决策，不阻塞 conversation flow。
    仅当 L2 trigger guard 判定应触发时才调用。

    当前 L2 extraction 结果未注入 prompt builder ——
    这是 Phase 5b foundation，recall/injection 留待后续。
    """
    from agent.memory_l2 import maybe_run_l2_inline

    messages = state.conversation.messages
    recent = list(messages[-20:]) if len(messages) > 20 else list(messages)
    if not recent:
        return None
    return maybe_run_l2_inline(
        recent,
        guard=_l2_trigger_guard,
    )

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


# ⛔ DEPRECATED: _active_skill dict 的 canonical source 在 agent.skill_state。
# 保留此模块级引用指向同一 dict 对象以维持向后兼容。
# 写入应通过 skill_state.set_active_skill()，保证引用一致性。
_active_skill = _skill_state.get_active_skill()
"""向后兼容——写入 lifecycle 后同步到此 dict。新增代码应使用 _get_lifecycle()。"""


def _active_skill_section(*, lifecycle=None) -> str:
    """从 lifecycle 获取当前 active_skill body，用于 prompt 注入。

    B7: 接受可选的 lifecycle 参数用于 per-session 隔离。
    """
    _lc = lifecycle if lifecycle is not None else _get_lifecycle()
    active = _lc.get_active()
    if active is not None:
        return active.body
    return ""


def _active_skill_memory_scope(*, lifecycle=None, skill_registry=None) -> str:
    """返回当前 active Skill 的 memory_scope，无法确认时 fail-closed 为 none。"""
    _lc = lifecycle if lifecycle is not None else _get_lifecycle()
    active = _lc.get_active()
    if active is None:
        return ""
    descriptor = None
    if skill_registry is not None:
        with contextlib.suppress(Exception):
            descriptor = skill_registry.get_descriptor(active.skill_id)
    if descriptor is None:
        return "none"
    return str(getattr(descriptor, "memory_scope", "none") or "none")


def _memory_recall_policy_payload(*, memory_scope: str) -> dict[str, Any]:
    if memory_scope != "none":
        return {}
    return {
        "policy_path": "skill.memory_scope",
        "decision": "blocked",
        "reason": "skill_memory_scope_none",
        "source_type": "skill",
    }


def _record_direct_skill_memory_recall_blocked() -> None:
    """dispatcher 不可用时也记录 Skill memory_scope recall block evidence。"""
    with contextlib.suppress(Exception):
        from agent.evidence_recorder import record_memory_evidence

        record_memory_evidence(
            event_type="memory.policy_blocked",
            operation="recall",
            phase="decision",
            status="blocked",
            source_type="skill",
            decision="blocked",
            policy_path="skill.memory_scope",
            reason="skill_memory_scope_none",
            count=0,
        )
        record_memory_evidence(
            event_type="memory.recall.skipped",
            operation="recall",
            phase="decision",
            status="blocked",
            source_type="skill",
            decision="skipped",
            policy_path="skill.memory_scope",
            reason="skill_memory_scope_none",
            count=0,
        )


def _record_direct_memory_recall_skipped_no_dispatcher() -> None:
    """dispatcher=None 时禁止无 evidence 的 prompt-affecting recall。"""
    with contextlib.suppress(Exception):
        from agent.evidence_recorder import record_memory_evidence

        record_memory_evidence(
            event_type="memory.recall.skipped",
            operation="recall",
            phase="decision",
            status="blocked",
            source_type="system",
            decision="skipped",
            policy_path="memory.recall.dispatcher_required",
            reason="no_dispatcher_fallback",
            count=0,
        )


# _skill_selected_by_model flag 已提取到 agent.skill_state——见 import _skill_state。
# 历史注释保留以供上下文：
# - True: 模型在本 turn 通过 tool_use("SKILL_SELECT", ...) 选择了 skill
# - False: 初始状态 / 关键字 fallback 已执行 / turn-end 已消费


def _update_active_skill_from_dispatcher(dispatcher, *, session_id: str = "") -> None:
    """从 dispatcher action_log 提取最近一次 SKILL_SELECT 成功结果。

    RuntimeActionEvent 扁平化存储 status/evidence/action_type——不使用嵌套的
    result.payload 格式。evidence 中包含了 handler 返回的证据字段（含
    body_load_decision、selected_skill_id 等），而 loaded_body_preview 和
    allowed_tools_after_selection 仅存在于 RuntimeActionResult.payload 中，
    不会进入 event。因此需要从 SkillRegistry 重新加载 body 和 allowed_tools。

    Phase 4 (Plan 3): 使用 ActiveSkillLifecycle 管理状态，同时更新向后兼容 dict。
    B7: session_id 用于 per-session lifecycle 隔离。
    """
    lifecycle = _get_lifecycle(session_id)
    for event in reversed(getattr(dispatcher, "action_log", [])):
        if getattr(event, "action_type", None) is None:
            continue
        if getattr(event.action_type, "value", "") == "skill.select":
            evidence = dict(getattr(event, "evidence", {}) or {})
            if evidence.get("body_load_decision"):
                skill_id = str(evidence.get("selected_skill_id") or "")
                if not skill_id:
                    continue
                body = ""
                allowed_tools: frozenset[str] = frozenset()
                try:
                    from agent.skill_system.loader import SkillLoader  # noqa: I001
                    from agent.skill_system.registry import SkillRegistry  # noqa: I001
                    from pathlib import Path  # noqa: I001

                    _registry = SkillRegistry(roots=[Path("skills")])
                    _descriptor = _registry.get_descriptor(skill_id)
                    if _descriptor is not None:
                        allowed_tools = frozenset(_descriptor.allowed_tools)
                        _loader = SkillLoader(_registry)
                        _body = _loader.load_body(skill_id)
                        body = str(_body)[:2000] if _body else ""
                except Exception:
                    body = ""
                    allowed_tools = frozenset()
                if skill_id and body:
                    # Phase 4: 通过 lifecycle 管理状态
                    lifecycle.activate(
                        skill_id=skill_id,
                        body=body,
                        allowed_tools=tuple(allowed_tools),
                        activated_by="model_selection",
                    )
                    # 向后兼容：同步到 skill_state（clear + update 保持引用一致性）
                    _skill_state.set_active_skill({
                        "skill_id": skill_id,
                        "body": body,
                        "allowed_tools": allowed_tools,
                    })
                return


def _dispatch_checkpoint_save(dispatcher, state, source="core.chat", *, identity=None):
    """通过 dispatcher 中介 checkpoint 保存，产生 RuntimeAction evidence。

    dispatcher 为 None 时回退到 runtime checkpoint gateway。
    B7: identity 用于 per-run checkpoint v2 路径。
    """
    if dispatcher is None:
        from agent.runtime_integration.checkpoint_save import save_runtime_checkpoint

        _sid = getattr(identity, "session_id", "") or "" if identity is not None else ""
        _rid = getattr(identity, "run_id", "") or "" if identity is not None else ""
        save_runtime_checkpoint(state, source=source, session_id=_sid, run_id=_rid)
        return

    from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType

    pending_tool = getattr(state.task, "pending_tool", None)
    pending_ui = getattr(state.task, "pending_user_input_request", None)
    route = getattr(dispatcher, "route_from_runtime_loop", None)
    if route is None:
        route = dispatcher.route
    route(
        RuntimeActionRequest(
            action_type=RuntimeActionType.CHECKPOINT_SAVE,
            source="core_loop",
            parent_trace_id="",
            payload={
                "_state": state,
                "source": source,
                "task_status": getattr(state.task, "status", None),
                "current_step_index": getattr(state.task, "current_step_index", None),
                "pending_tool": pending_tool,
                "pending_user_input_request": pending_ui,
            },
        ),
        core_entrypoint="core.chat",
        runtime_hook_name="save_checkpoint",
        identity=identity,
    )


def refresh_runtime_system_prompt(
    dispatcher=None, *, skill_registry=None, user_input: str = "",
    identity=None, namespace_key: str = "",
):
    """重新生成当前运行态实际生效的 system prompt，并写回 state。

    Loop 3 (Memory E2E) 收敛：当 dispatcher 可用时，MEMORY_RECALL 通过
    RuntimeActionDispatcher 统一 dispatch，确保 fake/real 共享核心 recall 路径。
        dispatcher 为 None 时不执行 prompt-affecting recall，避免无 evidence 的
        MemoryStore 内容影响 system prompt。

    Loop 2.2: skill_registry 用于生成可用技能列表 prompt section；
    注入激活 Skill body（上一轮 SKILL_SELECT 成功加载的 body）。

    Phase 3: 当 user_input 非空且有 skill_registry 时，执行 turn-start
    structured skill selection：
    - dispatch skill.selection.entered evidence
    - SkillCandidateRetriever.retrieve(user_input, skill_registry)
    - dispatch skill.candidates.built evidence（含候选数量和名称）
    - build_skill_selection_section(candidates) → 注入 selection_section
    返回 (system_prompt, snapshot_item_count)，调用方由此获得 memory 条数，
    无需再直接调用 _memory_runtime.snapshot_for_prompt()。

    B7: identity 参数用于 evidence 链，namespace_key 用于 per-session lifecycle 和 memory 隔离。
    """
    # B7: namespace_key 用于 per-session 隔离（空字符串 → 默认实例）
    _ns = namespace_key or ""
    _lifecycle = _get_lifecycle(_ns)
    _mem_rt = get_memory_runtime(_ns)
    _skill_memory_scope = _active_skill_memory_scope(
        lifecycle=_lifecycle,
        skill_registry=skill_registry,
    )

    # Phase 3: turn-start skill candidate retrieval
    selection_section = ""
    if user_input and skill_registry is not None:
        # 记录 selection phase 进入 evidence
        if dispatcher is not None:
            _dispatch_skill_selection_entered(dispatcher, user_input, identity=identity)
        # 检索候选 skill
        retriever = SkillCandidateRetriever()
        candidates = retriever.retrieve(user_input, skill_registry)
        # 记录候选构建 evidence
        if dispatcher is not None:
            _dispatch_skill_candidates_built(dispatcher, candidates, identity=identity)
        # 生成 selection prompt section
        selection_section = build_skill_selection_section(candidates)

    if dispatcher is not None:
        from agent.runtime_integration.schema import (
            RuntimeActionRequest,
            RuntimeActionType,
        )

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_RECALL,
            source="core_loop",
            parent_trace_id="",
            payload=_memory_recall_policy_payload(
                memory_scope=_skill_memory_scope,
            ),
        )
        route = getattr(dispatcher, "route_from_runtime_loop", None)
        if route is not None:
            result = route(request, identity=identity)
        else:
            result = dispatcher.route(request)
        memory_section = result.payload.get("prompt_section", "")
        snapshot_item_count = int(result.payload.get("snapshot_item_count") or 0)
        system_prompt = build_system_prompt(
            memory_section=memory_section,
            skill_registry=skill_registry,
            active_skill_section=_active_skill_section(lifecycle=_lifecycle),
            selection_section=selection_section,
        )
    else:
        if _skill_memory_scope == "none":
            memory_snapshot = None
            _record_direct_skill_memory_recall_blocked()
        else:
            memory_snapshot = None
            _record_direct_memory_recall_skipped_no_dispatcher()
        snapshot_item_count = 0
        system_prompt = build_system_prompt(
            memory_snapshot=memory_snapshot,
            skill_registry=skill_registry,
            active_skill_section=_active_skill_section(lifecycle=_lifecycle),
            selection_section=selection_section,
        )

    state.set_system_prompt(system_prompt)
    return state.get_system_prompt(), snapshot_item_count


def _dispatch_skill_selection_entered(dispatcher, user_input: str, *, identity=None) -> None:
    """Phase 3: 记录 turn-start skill selection phase 进入 evidence。

    这是每 turn 的 probe event——每次 model call 前无条件执行，
    大多数情况下无有效候选时返回 noop。

    B7: identity 参数传入 dispatcher，使 SKILL_SELECTION_ENTERED event 携带
    session_id/run_id/instance_id。
    """
    from agent.runtime_integration.schema import (
        RuntimeActionRequest,
        RuntimeActionType,
    )

    try:
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.SKILL_SELECTION_ENTERED,
            source="core_loop",
            parent_trace_id="",
            payload={"user_input_length": len(user_input)},
        )
        route = getattr(dispatcher, "route_from_runtime_loop", None)
        if route is not None:
            route(request, identity=identity)
        else:
            dispatcher.route(request)
    except Exception:
        # evidence dispatch 失败不阻塞 main loop
        pass


def _dispatch_skill_candidates_built(
    dispatcher, candidates: list, *, identity=None,
) -> None:
    """Phase 3: 记录 skill candidates 构建 evidence。

    在 SkillCandidateRetriever.retrieve() 返回后 dispatch，
    payload 包含候选数量和名称列表，用于验证 selection phase 产出。

    B7: identity 参数传入 dispatcher，使 SKILL_CANDIDATES_BUILT event 携带
    session_id/run_id/instance_id。
    """
    from agent.runtime_integration.schema import (
        RuntimeActionRequest,
        RuntimeActionType,
    )

    try:
        candidate_names = [c.skill_name for c in candidates]
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.SKILL_CANDIDATES_BUILT,
            source="core_loop",
            parent_trace_id="",
            payload={
                "candidate_count": len(candidates),
                "candidate_names": candidate_names,
            },
        )
        route = getattr(dispatcher, "route_from_runtime_loop", None)
        if route is not None:
            route(request, identity=identity)
        else:
            dispatcher.route(request)
    except Exception:
        # evidence dispatch 失败不阻塞 main loop
        pass


refresh_runtime_system_prompt()




# ========== 对外主入口 ==========


def _build_loop_context(
    client_obj,
    *,
    model_name: str = MODEL_NAME,
    max_loop_iterations: int = MAX_LOOP_ITERATIONS,
    provider=None,
    runtime_action_dispatcher=None,
    runtime_identity=None,
    event_log_writer=None,
) -> LoopContext:
    """兼容入口：实际 LoopContext 组装在 `agent.core_contexts`。

    provider: 可选的 ModelProvider 实例。传入则注入到 loop context，
              不传则回退到 build_model_provider_from_env()。
    runtime_action_dispatcher: Phase 1 RuntimeActionDispatcher 注入点。
    runtime_identity: B7 RuntimeIdentity 注入点。
    event_log_writer: B7 EventLogWriter 注入点（per-session event log）。
    """

    return build_loop_context(
        client_obj,
        model_name=model_name,
        max_loop_iterations=max_loop_iterations,
        provider=provider,
        runtime_action_dispatcher=runtime_action_dispatcher,
        runtime_identity=runtime_identity,
        event_log_writer=event_log_writer,
    )


def _build_confirmation_context(
    *,
    state,
    turn_state,
    loop_ctx: LoopContext,
    action_scheduler: Any = None,
) -> ConfirmationContext:
    """兼容入口：实际 ConfirmationContext 组装在 `agent.core_contexts`。"""

    # B7: 从 loop_ctx 提取 session_id 获取 per-session MemoryRuntime。
    _rt_id = getattr(loop_ctx, "runtime_identity", None)
    _sid = getattr(_rt_id, "session_id", "") or "" if _rt_id is not None else ""
    _mem_rt = get_memory_runtime(_sid)

    return build_confirmation_context(
        state=state,
        turn_state=turn_state,
        # 在闭包中捕获 action_scheduler，保证 plan confirmation 后的
        # continue_fn → _run_main_loop 路径不丢失 scheduler 注入。
        continue_fn=lambda ts, _as=action_scheduler: _run_main_loop(
            ts, loop_ctx, action_scheduler=_as
        ),
        start_planning_fn=lambda inp, ts: _start_planning_for_handler(
            inp, ts, loop_ctx
        ),
        loop_ctx=loop_ctx,
        memory_runtime=_mem_rt,
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
    runtime_action_dispatcher=None,
    runtime_identity=None,
) -> str | None:
    """兼容入口：实际分派逻辑在 `agent.model_output_dispatch`。"""

    _sid = getattr(runtime_identity, "session_id", "") or "" if runtime_identity is not None else ""
    dependencies = ModelOutputDispatchDependencies(
        state=state,
        handle_max_tokens_response=handle_max_tokens_response,
        handle_end_turn_response=handle_end_turn_response,
        handle_tool_use_response=handle_tool_use_response,
        extract_text=_extract_text,
        runtime_loop_fields=_runtime_loop_fields,
        safe_emit_runtime_event=_safe_emit_runtime_event,
        max_consecutive_max_tokens=MAX_CONTINUE_ATTEMPTS,
        runtime_action_dispatcher=runtime_action_dispatcher,
        runtime_identity=runtime_identity,
        memory_runtime=get_memory_runtime(_sid),
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
    action_scheduler=None,
    tool_gate_tool_name: str | None = None,
    checkpoint_save_on_turn_end: bool = False,
    session_id: str = "",
    event_log_writer=None,
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

    # B7: 提前计算 session_id / RuntimeIdentity。
    # _sid 用于 identity tracking（无显式 session_id 时生成 UUID）。
    # _ns_key 用于 memory/lifecycle namespace 隔离（无显式 session_id 时为空 → 默认实例）。
    _sid = session_id or str(uuid4())
    _ns_key = session_id or ""  # empty → default lifecycle/memory（向后兼容 monkeypatch）
    _mem_rt = get_memory_runtime(_ns_key)

    # B7: 设置 skill_tool 的活跃 session namespace key——
    # _skill_select_tool_func 通过此值获取 per-session lifecycle，
    # 避免依赖 logger.get_runtime_session_id() 的 import-time SESSION_ID fallback。
    # 实际 set 推迟到工具执行路径入口处以配合 try/finally cleanup。
    from agent.runtime_identity import RuntimeIdentity as _RuntimeIdentity
    from agent.skill_system.skill_tool import set_active_session_ns as _set_skill_ns
    _chat_identity = _RuntimeIdentity(
        session_id=_sid,
        run_id=str(uuid4()),
        instance_id=_sid,
    )

    # Loop 4: 提前构建 dispatcher，使 CLI READ_ONLY 命令可走统一 dispatcher 路径。
    # 需要 SubAgentRegistry（show subagents）和 _memory_runtime（show memories）。
    from pathlib import Path as _Path

    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher as _build_p1
    from agent.runtime_integration.phase1_hook import build_skill_registry as _build_skill_registry
    from agent.subagent_system.registry import SubAgentRegistry as _SubAgentRegistry

    # Loop 2.2: 构建 skill_registry 一次，同时传给 dispatcher builder 和主路径。
    _skill_registry = _build_skill_registry()
    _p1_dispatcher = _build_p1(
        memory_runtime=_mem_rt,
        subagent_registry=_SubAgentRegistry(roots=[_Path("agent/subagent_system/descriptors")]),
        skill_registry=_skill_registry,
    )

    # 调用方注入的 runtime_action_dispatcher 优先（dogfood/测试注入点），必须先于
    # CLI meta-command 赋值，使 delegation 证据落入调用方指定的 dispatcher。
    _phase1_dispatcher = (
        runtime_action_dispatcher if runtime_action_dispatcher is not None else _p1_dispatcher
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
    # ── CLI meta-command thin dispatch ──────────────────────────────────────
    # U4 hardening: core.py 只保留一次薄调用。真实存在的 show memories /
    # forget memory / show subagents 逻辑由 runtime_integration.cli_handlers
    # 承载；不新增 update/correction CLI。
    from agent.runtime_integration.cli_handlers import handle_cli_meta_command

    cli_result = handle_cli_meta_command(
        user_input,
        read_only_dispatcher=_p1_dispatcher,
        mutating_dispatcher=_phase1_dispatcher,
        memory_runtime=_mem_rt,
        on_runtime_event=on_runtime_event,
    )
    if cli_result is not None:
        return cli_result

    # delegate to subagent CLI meta-command：检测 → dispatcher-mediated 委托 → 渲染。
    # Loop 3.2a: delegation 走统一 dispatcher 路径（SUBAGENT_DELEGATE_L1），
    # 不再绕过 dispatcher 直接调 _execute_subagent_delegation()。
    # 如果 dispatcher L1 handler 没有 provider（默认 CLI 路径），回退 L0 inline。
    #
    # CLI-ONLY (CommandCategory.DELEGATING): delegate to subagent
    delegate_match = _looks_like_delegate_to_subagent(user_input)
    if delegate_match:
        subagent_name, task = delegate_match
        delegation_result = _dispatch_or_fallback_delegation(
            subagent_name, task,
            delegation_reason="CLI meta-command delegation",
            on_runtime_event=on_runtime_event,
            dispatcher=_phase1_dispatcher,
            provider=provider,
            user_input=user_input,
            session_id=_sid,
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
        delegation_result = _dispatch_or_fallback_delegation(
            subagent_name, task,
            delegation_reason="NL delegation fixture",
            on_runtime_event=on_runtime_event,
            dispatcher=_phase1_dispatcher,
            provider=provider,
            user_input=user_input,
            session_id=_sid,
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
    # 不解析 decision。MemoryRuntime 内部处理 policy → confirmation → store 全链路。
    # 当前 on_event 直接复用 on_runtime_event callback（如果调用方传入）。
    # B7: 使用 per-session MemoryRuntime 实例隔离多 session memory。
    # confirmation-required event 必须等 transition 成功后再发出；evaluate 阶段
    # 只允许 MemoryRuntime 计算本地结果，不能提前产生 UI side effect。
    result = _mem_rt.evaluate_user_text(user_input, on_event=None)
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
        confirmation_request = _mem_rt.get_pending_confirmation(result.candidate_id)
        if confirmation_request is not None:
            from agent.memory_interaction import build_memory_pending_request

            origin_status = state.task.status
            pending = build_memory_pending_request(
                confirmation_request,
                candidate_id=result.candidate_id,
                origin_status=origin_status,
            )
            transition_request = TaskTransitionRequest(
                event=TransitionEvent.MEMORY_CONFIRMATION_REQUIRED,
                owner="core.chat.memory_confirmation",
                expected_from_status=origin_status,
            )
            preflight = validate_task_transition(state, transition_request)
            if not preflight.allowed:
                return ""
            transition = apply_task_transition(
                state,
                transition_request,
                preflight=preflight,
            )
            if not transition.allowed:
                return ""
            assert transition.checkpoint_action is CheckpointAction.SAVE
            state.task.pending_user_input_request = pending
            _dispatch_checkpoint_save(
                _p1_dispatcher, state, source="memory_confirmation",
                identity=_chat_identity,
            )
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
        from agent.runtime_integration.skill_lifecycle import (
            deactivate_active_skill_for_task_boundary,
        )

        deactivate_active_skill_for_task_boundary(
            state,
            reason="state_inconsistency_reset",
            source="core.state_inconsistency_reset",
            session_id=_sid,
        )
        state.reset_task()

    # 注意：不要在这里无条件压缩历史。
    # 当处于 awaiting_tool_confirmation 时，上一条 assistant 里有未闭合的
    # tool_use 块，它必须与稍后的 tool_result 配对。若此刻压缩，可能把该
    # tool_use 丢进摘要，留下悬空 tool_result，下次调用 API 会直接报错。

    # Loop 3 (Memory E2E): 传入 dispatcher 统一 recall 路径
    # Loop 2.2: 传入 skill_registry 生成 Skill 可用列表 prompt section
    # Phase 3: 传入 user_input — turn-start skill candidate retrieval + selection section
    runtime_system_prompt, snapshot_item_count = refresh_runtime_system_prompt(
        dispatcher=_phase1_dispatcher,
        skill_registry=_skill_registry,
        user_input=user_input,
        identity=_chat_identity,
        namespace_key=_ns_key,
    )

    # Memory Kernel v1：告知用户当前已加载的 memory 条数（仅在有条目时展示）。
    if snapshot_item_count > 0:
        _safe_emit_runtime_event(
            on_runtime_event,
            memory_injected_event(snapshot_item_count),
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
    # Loop 4: _phase1_dispatcher 已在函数开头与 _p1_dispatcher 一同设置。

    # ── Loop 1.1: Runtime Decision Spine ──────────────────────────────────────
    # 在入口处构建统一 decision frame，描述当前 turn 所有子系统分支点状态。
    # 这不是新 runtime，不改变任何执行路径——只是诚实地标记各子系统是 READY/
    # PARTIAL/DEFERRED/FAKE_DEMO/STUB，防止 silent pass 和 overclaim。
    _turn_decision_frame = _build_decision_frame(
        user_input=user_input,
        provider=provider,
        skill_registry=_skill_registry,
        runtime_action_dispatcher=_phase1_dispatcher,
        tool_gate_tool_name=tool_gate_tool_name,
        session_id=_sid,
    )
    _set_last_decision_frame(_turn_decision_frame)

    # B7: RuntimeIdentity 已在函数头部提前构造，此处复用。
    # _chat_identity 和 _sid 由函数头部统一管理。

    _loop_ctx = _build_loop_context(
        client,
        model_name=MODEL_NAME,
        max_loop_iterations=MAX_LOOP_ITERATIONS,
        provider=provider,
        runtime_action_dispatcher=_phase1_dispatcher,
        runtime_identity=_chat_identity,
        event_log_writer=event_log_writer,
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
        action_scheduler=action_scheduler,
    )

    # v0.5.1 第三小步：5 条 pending confirmation 分支抽进
    # ``_dispatch_pending_confirmation`` helper（纯函数提取，行为与提取前
    # 字面等价）。helper 返回 None 表示 fallthrough 到下方"压缩 + 新任务"
    # 路径；返回 str 表示已被某个 confirmation handler 接管。
    # baseline 由 tests/test_pending_confirmation_dispatch.py 11 条
    # characterization tests 钉死（cdd1427）。详见 helper docstring。
    # B7: 工具执行路径入口处设置 session namespace 并用 try/finally 确保 cleanup。
    # D-09 fix: 使用 _sid (UUID) 而非 _ns_key (empty string fallback)，
    # 使 skill_tool lifecycle 与 turn-end hook lifecycle 共享同一 namespace，
    # 确保 model_selected flag 和 active_skill 可被 turn-end hook 正确读取。
    _set_skill_ns(_sid)
    try:
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
                action_scheduler=action_scheduler,
                checkpoint_save_on_turn_end=checkpoint_save_on_turn_end,
            )

        # 到这里意味着要开启一轮全新的任务。
        # 用 state.reset_task() 一次性清干净 task 层所有字段，避免"单步任务收尾
        # 不触发 done 路径、tool_execution_log / pending_tool 残留到下一个任务"
        # 这种 bug。之前这里只重置 4 个计数字段，其他字段（log/pending/user_goal
        # 等）都有可能带着旧值进新任务。
        from agent.runtime_integration.skill_lifecycle import (
            deactivate_active_skill_for_task_boundary,
        )
        deactivate_active_skill_for_task_boundary(
            state,
            reason="new_task",
            source="core.new_task_boundary",
            session_id=_sid,
        )
        state.reset_task()

        plan_result = _run_planning_phase(
            user_input, turn_state, _loop_ctx,
            action_scheduler=action_scheduler,
        )
        return _handle_planning_phase_result(
            plan_result, turn_state, _loop_ctx,
            tool_gate_tool_name=tool_gate_tool_name, skill_registry=_skill_registry,
            action_scheduler=action_scheduler,
            checkpoint_save_on_turn_end=checkpoint_save_on_turn_end,
        )
    finally:
        from agent.skill_system.skill_tool import clear_active_session_ns as _clear_skill_ns
        _clear_skill_ns()


# ========== 规划阶段 ==========


def _action_plan_to_dict(action_plan) -> dict[str, Any]:
    """将 ActionPlan 序列化为 JSON-safe dict（用于 state.task.current_plan 持久化）。

    ActionPlan 是 frozen dataclass，不可直接 JSON 序列化。
    此 helper 递归展开 nodes/tuple/dataclass → dict/list，保证 checkpoint
    序列化兼容。
    """
    nodes = []
    for node in action_plan.nodes:
        nodes.append({
            "node_id": node.node_id,
            "action_type": node.action_type,
            "target": node.target,
            "params": dict(node.params),
            "depends_on": list(node.depends_on),
            "recovery": {
                "max_retries": node.recovery.max_retries,
                "fallback_node_id": node.recovery.fallback_node_id,
                "on_failure": node.recovery.on_failure,
            },
            "condition": node.condition,
            "description": node.description,
        })
    return {
        "plan_id": action_plan.plan_id,
        "nodes": nodes,
        "entry_node_id": action_plan.entry_node_id,
        "status": action_plan.status,
        "description": action_plan.description,
    }


def _compress_history_and_sync_checkpoint(loop_ctx: LoopContext) -> None:
    """压缩历史并同步 active task checkpoint；不改变 checkpoint schema。"""

    # 到这里才是真正的「新一轮对话」：可以安全做压缩。
    messages = state.conversation.messages
    previous_summary = state.memory.working_summary
    compressed_messages, new_summary = compress_history(
        messages,
        loop_ctx.client,
        existing_summary=state.memory.working_summary,
        max_recent_messages=state.runtime.max_recent_messages,
    )
    safe_summary = set_working_summary_scratchpad(
        state,
        new_summary,
        reason="history_compression",
    )
    compression_happened = (
        compressed_messages is not messages or safe_summary != previous_summary
    )
    state.conversation.messages = compressed_messages
    # 压缩真实发生且当前存在运行中任务时，立刻落盘，避免 summary 与 checkpoint 不一致。
    if compression_happened and state.task.current_plan:
        _dispatch_checkpoint_save(
            loop_ctx.runtime_action_dispatcher, state,
            identity=loop_ctx.runtime_identity,
        )


def _run_planning_phase(
    user_input: str,
    turn_state: TurnState,
    loop_ctx: LoopContext,
    *,
    action_scheduler: Any = None,
) -> str:
    """任务规划阶段：单次 API 调用 + 双解析路径（ActionPlan → legacy Plan fallback）。

    ActionPlan 是 planner ↔ scheduler 之间唯一正式机器执行契约。
    generate_action_plan() 是 ActionPlan 解析的唯一正式入口——
    _run_planning_phase() 只负责 API 调用和结果编排，不内联解析逻辑。

    解析策略（仅一次 API 调用）：
    1. 使用 ACTION_PLAN_PROMPT 调用模型
    2. 委托 planner.generate_action_plan(clean_text=...) 解析 ActionPlan
    3. 失败时回退 legacy Plan/PlanStep 解析 + plan_to_action_plan() 桥接

    关键架构边界：
    - core.py 只做 orchestration（API 调用 + 结果路由）
    - planner.py 拥有 ActionPlan 解析逻辑（generate_action_plan）
    - core.py 不再内联 markdown 剥离/JSON 解析/build_action_plan_from_model_output

    注意：state 引用模块级全局 AgentState（非 turn_state 形参）。
    build_planning_messages_from_state / state.conversation / state.task
    均操作模块级 state；仅 on_runtime_event 使用 turn_state。
    """
    from agent.planner import generate_action_plan

    # ── 单次 API 调用 + schema validation + 最多一次 repair retry ──
    planning_messages = build_planning_messages_from_state(state, user_input)
    clean_text = None
    raw = None
    schema_retry_used = False

    # 内联 helper: 调用模型获取 planning 结果
    # 返回 (clean_text, raw_json_dict_or_None)
    # clean_text 永远返回模型原始输出文本（用于诊断），
    # raw 为 None 时表示 JSON 提取全部失败。
    def _call_planning_model(_system: str, _messages: list[dict]) -> tuple[str | None, dict | None]:
        try:
            response = loop_ctx.client.messages.create(
                max_tokens=4096,
                system=_system,
                messages=_messages,
            )
            result_text = ""
            for block in response.content:
                if block.type == "text":
                    result_text = block.text
                    break

            if not result_text.strip():
                # 模型返回空文本时记录 stop_reason + 内容块类型分布，
                # 用于诊断 thinking/max_tokens 等导致的空响应。
                _block_types = [getattr(b, "type", "?") for b in response.content]
                _sr = getattr(response, "stop_reason", None)
                log_event("planning_model_empty_text", {
                    "stop_reason": _sr,
                    "block_types": _block_types,
                    "content_block_count": len(response.content),
                })
                _record_core_evidence(
                    "planning_model", "error", "planning model returned empty text")
                return "", None

            _raw_text = result_text.strip()
            # 从模型输出中提取 JSON：先尝试直接 parse，失败则从 markdown
            # fence 或大括号对中提取。
            try:
                _raw = json.loads(_raw_text)
                return _raw_text, _raw
            except json.JSONDecodeError:
                pass

            # 尝试从 ```json / ``` fence 中提取
            fence_match = re.search(
                r'```(?:json)?\s*\n(.*?)\n\s*```', _raw_text, re.DOTALL
            )
            if fence_match:
                try:
                    _raw = json.loads(fence_match.group(1).strip())
                    return _raw_text, _raw
                except json.JSONDecodeError:
                    pass

            # 最后尝试从 { ... } 对中提取（处理模型在 JSON 前后加文本的情况）
            brace_match = re.search(r'\{[\s\S]*\}', _raw_text)
            if brace_match:
                try:
                    _raw = json.loads(brace_match.group(0))
                    return _raw_text, _raw
                except json.JSONDecodeError:
                    pass

            # 所有提取失败——返回原始文本用于诊断
            return _raw_text, None
        except Exception as _exc:
            _record_core_evidence(
                "planning_model", "error",
                f"planning model call error: {type(_exc).__name__}")
            log_event("planning_model_call_error", {
                "error_type": type(_exc).__name__,
                "error_msg": str(_exc)[:300],
                "phase": "model_api_call",
                "model_name": str(loop_ctx.model_name)[:100],
                "system_len": len(_system or ""),
                "message_count": len(_messages or []),
            })
            return None, None

    clean_text, raw = _call_planning_model(ACTION_PLAN_PROMPT, planning_messages)
    _record_core_evidence("planning_entered", "ok", "planning mode entered")
    log_event("planning_mode_entered", {
        "action_plan_prompt_used": True,
        "phase": "_run_planning_phase",
        "raw_parsed": raw is not None,
        "clean_text_len": len(clean_text or ""),
    })

    # ── schema validation + repair retry ──
    # 当 action_scheduler 传入时（scheduler 模式），强制 ActionPlan schema——
    # 不允许模型输出 steps/tool 等旧格式后静默回退 legacy。
    # raw is None（JSON 提取完全失败）时也尝试 repair retry。
    if action_scheduler is not None:
        if raw is not None:
            is_valid, reason = validate_action_plan_raw(raw)
        else:
            is_valid = False
            reason = "模型输出不是合法 JSON（无法提取 JSON 对象）"

        if not is_valid:
            _record_core_evidence(
                "schema_validation", "error",
                f"action plan schema invalid: {reason[:100]}",
                metadata={"reason": reason})
            log_event("action_plan_schema_invalid", {
                "reason": reason,
                "phase": "schema_validation",
                "raw_was_none": raw is None,
            })
            # 一次 repair retry（需要 clean_text 非空才可重试）
            if clean_text:
                schema_retry_used = True
                repair_content = SCHEMA_REPAIR_PROMPT.format(wrong_patterns=reason)
                repair_messages = list(planning_messages) + [
                    {"role": "assistant", "content": clean_text},
                    {"role": "user", "content": repair_content},
                ]
                clean_text, raw = _call_planning_model(
                    ACTION_PLAN_PROMPT, repair_messages
                )
                if raw is not None:
                    is_valid2, reason2 = validate_action_plan_raw(raw)
                    if is_valid2:
                        is_valid = True
                        _record_core_evidence(
                            "schema_validation", "ok",
                            "action plan schema validated after retry",
                            metadata={"after_retry": True})
                        log_event("action_plan_schema_validated", {
                            "after_retry": True,
                            "phase": "schema_repair_retry_success",
                        })
                    else:
                        _record_core_evidence(
                            "planning_failed", "error",
                            f"planning failed after retry: {reason2[:100]}",
                            metadata={"reason": reason2, "retry_used": True})
                        log_event("planning_failed", {
                            "reason": reason2,
                            "retry_used": True,
                            "phase": "schema_repair_retry_failed",
                        })
                        raw = None
                        clean_text = None
                else:
                    _record_core_evidence(
                        "planning_failed", "error", "planning failed: retry parse error",
                        metadata={"retry_used": True})
                    log_event("planning_failed", {
                        "reason": "retry parse failed",
                        "retry_used": True,
                        "phase": "schema_repair_retry_parse_error",
                    })
                    clean_text = None
            else:
                _record_core_evidence(
                    "planning_failed", "error",
                    f"planning failed: {reason[:100]}",
                    metadata={"reason": reason, "retry_used": False})
                log_event("planning_failed", {
                    "reason": reason,
                    "retry_used": False,
                    "phase": "schema_validation_no_text_for_retry",
                })
    elif raw is not None and action_scheduler is None:
        is_valid, reason = validate_action_plan_raw(raw)
        if is_valid:
            log_event("action_plan_schema_validated", {"after_retry": False})
            _record_core_evidence("schema_validation", "ok", "action plan schema validated")
        # 无 scheduler 时不强制 schema——允许 legacy fallback
        _record_core_evidence(
            "model_plan_received", "ok",
            f"model plan received schema_valid={is_valid}",
            metadata={"schema_valid": is_valid})
        log_event("model_plan_received", {
            "schema_valid": is_valid,
            "has_scheduler": False,
        })

    # ── 解析路径 1：通过 planner.generate_action_plan() 解析 ActionPlan ──
    # 这是 ActionPlan 解析的唯一正式入口。core.py 不再直接调用
    # build_action_plan_from_model_output()——所有解析逻辑由 planner 拥有。
    action_plan = None
    if clean_text is not None and raw is not None:
        steps_estimate = raw.get("steps_estimate", 0)
        node_count = len(raw.get("nodes") or [])
        multi_step = (
            isinstance(steps_estimate, (int, float)) and int(steps_estimate) > 1
        )
        if multi_step or node_count > 1:
            action_plan = generate_action_plan(
                user_input, loop_ctx.client, loop_ctx.model_name,
                messages=planning_messages,
                clean_text=clean_text,
            )

    # ── 解析路径 2：legacy Plan/PlanStep schema（回退桥接）──
    # ⚠️ scheduler 模式下（action_scheduler set），schema 验证失败后不启用
    # legacy fallback——模型必须输出正确 ActionPlan schema。
    legacy_plan = None
    if action_plan is None and raw is not None and action_scheduler is None:
        try:
            steps_estimate = raw.get("steps_estimate", 0)
            if isinstance(steps_estimate, (int, float)) and int(steps_estimate) <= 1:
                pass  # 单步任务
            else:
                from agent.plan_schema import Plan, PlannerOutput

                decision = PlannerOutput.model_validate(raw)
                if decision.goal and decision.steps:
                    legacy_plan = Plan(
                        goal=decision.goal,
                        thinking=decision.thinking,
                        steps=decision.steps,
                        needs_confirmation=decision.needs_confirmation,
                    )
        except Exception:
            legacy_plan = None

    # ── 统一处理结果 ──
    if action_plan is not None:
        plan_payload = _action_plan_to_dict(action_plan)
        user_message = {"role": "user", "content": user_input}
        request = TaskTransitionRequest(
            event=TransitionEvent.PLAN_GENERATED,
            owner="core.run_planning_phase.action_plan",
            expected_from_status="idle",
        )
        preflight = validate_task_transition(state, request)
        if not preflight.allowed:
            return "planning_transition_denied"
        transition = apply_task_transition(state, request, preflight=preflight)
        if not transition.allowed:
            return "planning_transition_denied"

        state.task.current_plan = plan_payload
        state.task.user_goal = user_input
        state.task.current_step_index = 0
        state.conversation.messages.append(user_message)

        if action_scheduler is not None:
            try:
                action_scheduler.load_plan(action_plan)
            except Exception:
                _record_core_evidence(
                    "scheduler_load", "error",
                    "planning handoff: scheduler.load_plan() failed")
                log_event("planning_handoff_failure", {
                    "error": "action_scheduler.load_plan() failed",
                    "plan_id": action_plan.plan_id,
                    "phase": "ActionPlan handoff",
                })
                # transition 已生效但 scheduler 未接管时，显式回到 factory idle；
                # 不保存 awaiting 状态，也不展示伪成功 confirmation。
                from agent.runtime_integration.skill_lifecycle import (
                    deactivate_active_skill_for_task_boundary,
                )

                _rt_id = getattr(loop_ctx, "runtime_identity", None)
                _sid = (
                    getattr(_rt_id, "session_id", "") or ""
                    if _rt_id is not None else ""
                )
                deactivate_active_skill_for_task_boundary(
                    state,
                    reason="planning_handoff_failed",
                    source="core.run_planning_phase.action_plan_handoff_failed",
                    session_id=_sid,
                )
                state.reset_task()
                return "planning_handoff_failed"
            _record_core_evidence(
                "scheduler_load", "ok",
                f"scheduler load success plan_id={action_plan.plan_id}")
            log_event("scheduler_load_success", {
                "plan_id": action_plan.plan_id,
                "nodes": len(action_plan.nodes),
                "schema_retry_used": schema_retry_used,
            })

        assert transition.checkpoint_action is CheckpointAction.SAVE
        _dispatch_checkpoint_save(
            loop_ctx.runtime_action_dispatcher, state,
            identity=loop_ctx.runtime_identity,
        )

        if turn_state.on_runtime_event is not None:
            turn_state.on_runtime_event(
                plan_confirmation_requested(
                    f"{format_action_plan_for_display(action_plan)}\n按此计划执行吗？(y/n/输入修改意见):",
                    metadata={"source": "planning_phase", "schema": "ActionPlan"},
                )
            )
        return "awaiting_plan_confirmation"

    if legacy_plan is not None:
        plan_payload = legacy_plan.model_dump()
        confirm_each_step = any(
            marker in user_input
            for marker in (
                "每步确认", "每一步确认", "每一步都确认", "每步都确认",
                "每一步都让我确认", "每步都让我确认", "做完一步问我",
                "每做完一步问我", "一步一确认", "每步推理",
                "每一步推理", "逐步推理", "一步一步推理",
                "不要自动下一步", "不要自动继续", "先别自动执行下一步",
            )
        )
        user_message = {"role": "user", "content": user_input}
        request = TaskTransitionRequest(
            event=TransitionEvent.PLAN_GENERATED,
            owner="core.run_planning_phase.legacy_plan",
            expected_from_status="idle",
        )
        preflight = validate_task_transition(state, request)
        if not preflight.allowed:
            return "planning_transition_denied"
        transition = apply_task_transition(state, request, preflight=preflight)
        if not transition.allowed:
            return "planning_transition_denied"

        state.task.current_plan = plan_payload
        state.task.user_goal = user_input
        state.task.current_step_index = 0
        state.task.confirm_each_step = confirm_each_step
        state.conversation.messages.append(user_message)

        # ⛔ LEGACY bridge: 旧 Plan → ActionPlan → scheduler
        if action_scheduler is not None:
            try:
                from agent.action_scheduler import plan_to_action_plan as _legacy_bridge
                legacy_action_plan = _legacy_bridge(
                    legacy_plan, plan_id=f"legacy-{legacy_plan.goal[:40]}"
                )
                action_scheduler.load_plan(legacy_action_plan)
            except Exception as exc:
                _record_core_evidence(
                    "scheduler_load", "error",
                    f"legacy bridge failed: {type(exc).__name__}")
                log_event("planning_handoff_failure", {
                    "error": f"legacy bridge failed: {type(exc).__name__}: {exc}",
                    "plan_id": f"legacy-{legacy_plan.goal[:40]}",
                    "phase": "Legacy Plan→ActionPlan handoff",
                })
                state.reset_task()
                return "planning_handoff_failed"

        assert transition.checkpoint_action is CheckpointAction.SAVE
        _dispatch_checkpoint_save(
            loop_ctx.runtime_action_dispatcher, state,
            identity=loop_ctx.runtime_identity,
        )

        if turn_state.on_runtime_event is not None:
            turn_state.on_runtime_event(
                plan_confirmation_requested(
                    f"{format_plan_for_display(legacy_plan)}\n按此计划执行吗？(y/n/输入修改意见):",
                    metadata={"source": "planning_phase", "schema": "Plan (legacy)"},
                )
            )
        return "awaiting_plan_confirmation"

    # 单步任务或规划失败
    state.conversation.messages.append({"role": "user", "content": user_input})
    if turn_state.on_runtime_event is not None:
        turn_state.on_runtime_event(control_message("[系统] 未生成多步计划，按单步处理。"))
    return "ok"


def _handle_planning_phase_result(
    plan_result: str,
    turn_state: TurnState,
    loop_ctx: LoopContext,
    *,
    tool_gate_tool_name: str | None = None,
    skill_registry: Any = None,
    action_scheduler: Any = None,
    checkpoint_save_on_turn_end: bool = False,
) -> str:
    """统一处理 planning 的 cancelled / awaiting / ok 三种结果。"""

    if plan_result == "cancelled":
        return "好的，已取消。"
    if plan_result == "awaiting_plan_confirmation":
        return ""
    if plan_result == "planning_transition_denied":
        return "[系统] planning 状态迁移失败，未修改当前任务。"
    if plan_result == "planning_handoff_failed":
        return "[系统] 计划未能交给调度器，任务已安全重置。"
    return _run_main_loop(
        turn_state, loop_ctx,
        tool_gate_tool_name=tool_gate_tool_name, skill_registry=skill_registry,
        action_scheduler=action_scheduler,
        checkpoint_save_on_turn_end=checkpoint_save_on_turn_end,
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




def _runtime_loop_fields() -> dict:
    """提取主循环观测字段，只用于日志，不参与业务判断。"""

    return build_runtime_loop_fields(state)

def _run_main_loop(
    turn_state: TurnState,
    loop_ctx: LoopContext,
    *,
    tool_gate_tool_name: str | None = None,
    skill_registry: Any = None,
    action_scheduler: Any = None,
    checkpoint_save_on_turn_end: bool = False,
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
    # B7: 从 identity 提取 session_id，用于 task-boundary cleanup 和
    # turn-end active skill 更新。必须在 LoopDependencies callback 捕获前计算。
    _rt_id = getattr(loop_ctx, "runtime_identity", None)
    _sid = getattr(_rt_id, "session_id", "") or "" if _rt_id is not None else ""

    def _deactivate_task_boundary(
        _state,
        *,
        reason: str,
        source: str,
        session_id: str = "",
    ) -> None:
        from agent.runtime_integration.skill_lifecycle import (
            deactivate_active_skill_for_task_boundary,
        )

        deactivate_active_skill_for_task_boundary(
            _state,
            reason=reason,
            source=source,
            session_id=session_id,
        )

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
            runtime_action_dispatcher=loop_ctx.runtime_action_dispatcher,
            runtime_identity=loop_ctx.runtime_identity,
        ),
        runtime_loop_fields=_runtime_loop_fields,
        safe_emit_runtime_event=lambda sink, event: _safe_emit_runtime_event(
            sink,
            event,
            fallback_prefix="\n",
        ),
        clear_checkpoint=_clear_checkpoint,
        task_boundary_callback=lambda reason, source: _deactivate_task_boundary(
            state,
            reason=reason,
            source=source,
            session_id=_sid,
        ),
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
        action_scheduler=action_scheduler,
        checkpoint_save_on_turn_end=checkpoint_save_on_turn_end,
        runtime_identity=loop_ctx.runtime_identity,
    )
    if tool_gate_tool_name is not None:
        _deps_fields["tool_gate_tool_name"] = tool_gate_tool_name
    dependencies = LoopDependencies(**_deps_fields)
    result = run_main_loop(turn_state, loop_ctx, dependencies)
    # Loop 2.2: 主循环完成后，从 dispatcher action_log 提取 SKILL_SELECT 结果，
    # 更新跨 turn active skill 状态。
    _update_active_skill_from_dispatcher(
        dependencies.runtime_action_dispatcher, session_id=_sid,
    )
    return result
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

    try:
        # REAL-EVIDENCE-002: 确保 SKILL_SELECT 在 TOOL_REGISTRY 中注册（幂等）。
        from agent.skill_system.skill_tool import _ensure_skill_select_registered
        _ensure_skill_select_registered()

        # UMT-P1-002: 活跃 skill 时限制模型可见工具范围。
        # 不限制时模型看到所有工具但只能用 skill.allowed_tools 中的工具，
        # 导致模型尝试调用其他工具时被 TOOL_GATE 拒绝（"overblocking"）。
        # 修复：活跃 skill 时通过 explicit_allowlist 将模型可见工具
        # 收窄为 skill.allowed_tools + 元工具 + SKILL_SELECT。
        _skill_visible_allowlist: frozenset[str] | None = None
        try:
            from agent.skill_system.lifecycle import get_default_lifecycle
            _rt_id = getattr(loop_ctx, "runtime_identity", None)
            _sid = getattr(_rt_id, "session_id", "default") if _rt_id is not None else "default"
            _lc = get_default_lifecycle(session_id=_sid)
            _active_tools = _lc.get_allowed_tools()
            if _active_tools:
                # 技能工具 + 元工具 + SKILL_SELECT（用于切换/退出技能）
                _meta_tool_names = frozenset({
                    name for name, info in TOOL_REGISTRY.items()
                    if info.get("meta_tool")
                })
                # v1.1 skill tool-scope fix: Skill 激活后 visible_tools =
                # BASE_TOOLS + skill_allowed_tools + meta_tools + SKILL_SELECT，
                # 不剥夺 Agent 基础只读/控制能力。
                from agent.tool_scope import BASE_TOOLS
                _skill_visible_allowlist = (
                    frozenset(_active_tools)
                    | _meta_tool_names
                    | {"SKILL_SELECT"}
                    | BASE_TOOLS
                )
        except ImportError:
            pass

        response = call_model(
            provider=getattr(loop_ctx, "model_provider", None),
            legacy_client=loop_ctx.client,
            model_name=loop_ctx.model_name,
            system_prompt=turn_state.system_prompt,
            messages=request_messages,
            tools=get_model_visible_tools(
                max_mcp_tools=5, explicit_allowlist=_skill_visible_allowlist
            ),
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
    except ProviderError as exc:
        # Loop 4.2: 将 provider 异常转为用户可见的 RuntimeEvent，避免 traceback 崩溃。
        error_msg = str(exc)
        if turn_state.on_runtime_event is not None:
            turn_state.on_runtime_event(
                control_message(f"[Provider 错误] 模型调用失败：{error_msg}")
            )
        return ProviderResponse(content=[], stop_reason="end_turn")

    # ===== 协议观察：打印返回结构 =====
    # _debug_print_response(response)

    return response




# ========== 辅助 ==========

def _extract_text(content_blocks) -> str:
    parts = [block.text for block in content_blocks if block.type == "text"]
    return "\n".join(p for p in parts if p).strip()


def _dispatch_or_fallback_delegation(
    subagent_name: str,
    task: str,
    *,
    delegation_reason: str,
    on_runtime_event,
    dispatcher,
    provider,
    user_input: str,
    session_id: str = "",
) -> str:
    """Loop 3.2a: dispatcher-mediated L1 delegation，不存在则回退 L0 inline。

    优先走 dispatcher (SUBAGENT_DELEGATE_L1)：
    1. 从 dispatcher 获取 L1 handler
    2. 注入 provider（如果有）
    3. 构建 RuntimeActionRequest → route
    4. 成功则返回 delegation result

    如果 dispatcher 中没有 L1 handler 或 provider 未设置 → 回退 L0 inline path
    （_execute_subagent_delegation）。
    """
    from types import SimpleNamespace as _SimpleNamespace

    from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType

    # 006 TOOL_MEDIATOR_GAP: 为 L1 delegation 构造 ToolRuntimeMediator。
    # 复用 response_handlers.py:230-247 的构造模式，使用 SimpleNamespace
    # 作为最小 turn_state（delegation call sites 在 TurnState 创建之前）。
    _tool_mediator = None
    if dispatcher is not None:
        from agent.tool_runtime_mediator import ToolRuntimeMediator as _Tmr
        _skill_at = _get_lifecycle(session_id).get_allowed_tools() or None
        _tool_mediator = _Tmr(
            dispatcher,
            state=state,
            turn_state=_SimpleNamespace(on_display_event=None, round_tool_traces=[]),
            turn_context={},
            messages=state.conversation.messages,
            skill_allowed_tools=_skill_at,
        )

    l1_handler = dispatcher.get_handler(RuntimeActionType.SUBAGENT_DELEGATE_L1)
    if l1_handler is not None and provider is not None:
        l1_handler.set_provider(provider, _tool_mediator)
        # 通过 dispatcher 路由 delegation
        req = RuntimeActionRequest(
            action_type=RuntimeActionType.SUBAGENT_DELEGATE_L1,
            source="core.chat",
            parent_trace_id="",
            payload={
                "subagent_name": subagent_name,
                "delegation_goal": task,
                "delegation_reason": delegation_reason,
            },
        )
        result = dispatcher.route(req)
        payload = dict(result.payload)
        if payload.get("delegate_l1_called"):
            # L1 delegation 成功 → 渲染结果
            from agent.cli_commands import render_delegate_result
            return render_delegate_result(
                subagent_name,
                payload.get("status", "unknown"),
                payload.get("execution_result", ""),
                payload.get("stop_reason", ""),
            )

    # 回退 L0 inline path
    return _execute_subagent_delegation(
        subagent_name, task,
        delegation_reason=delegation_reason,
        on_runtime_event=on_runtime_event,
    )
