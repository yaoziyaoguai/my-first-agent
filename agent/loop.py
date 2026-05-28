"""Runtime loop orchestration extracted from `agent.core`.

学习型说明：
`agent.core` 仍是稳定 public API 的承载处，例如 `chat()`；本模块只承载
模型循环的 orchestration。它通过 `LoopDependencies` 接收模型调用、输出分派、
checkpoint 清理和 RuntimeEvent 投影函数，避免 loop 反向 import Memory、UI、
CLI/TUI adapter 或 provider 细节。

这个边界降低 `core.py` 巨石化风险，但不改变状态机语义：checkpoint、tool
execution、request_user_input、memory hook 的行为仍由原 owner 负责。

Phase 1 hook：``_try_phase1_turn_end_runtime_action`` 在 loop turn-end 时
调用 RuntimeActionDispatcher 的 runtime-loop route，证明 RuntimeAction 确实
由真实 core loop 触发，而非 dogfood harness 直接 dispatcher.route()。这是
classification 从 harness_runtime_e2e 升级到 real_core_loop_runtime_e2e 的
必要条件。
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from agent.display_events import RuntimeEvent, loop_max_iterations_event
from agent.loop_context import LoopContext
from agent.runtime_observer import log_event as log_runtime_event


def _try_trace_event_emission(
    dependencies: Any,
    result_text: str,
    tool_name: str,
    invoke_result: Any = None,
) -> None:
    """在 turn-end hook 末尾发射 TraceEvent（纯观测 side-effect）。

    Trace 是 infrastructure hardening，不参与 tool/memory/checkpoint 决策：
    - 只在 dependencies.on_trace_event sink 存在时发射→默认路径零开销
    - tool_call event：TOOL_INVOKE 完成后发射（包含 tool_output/execution_status）
    - state_transition event：turn-end 标记
    - 任何异常静默吞掉——trace 失败不阻塞 loop
    """
    sink = getattr(dependencies, "on_trace_event", None)
    if sink is None:
        return

    run_id = getattr(dependencies, "trace_run_id", None)
    trace_id = getattr(dependencies, "trace_id", None)

    try:
        # state_transition: 标记 turn-end
        from agent.local_trace import TraceEvent

        transition_event = TraceEvent(
            run_id=run_id or "run:unknown",
            trace_id=trace_id or "trace:unknown",
            span_id=f"turn_end:{hash(result_text) & 0x7FFFFFFF:08x}",
            parent_span_id=None,
            span_type="state_transition",
            name="loop.turn_end",
            status="ok",
            metadata={
                "tool_name": tool_name,
                "result_text_preview": result_text[:200] if result_text else "",
            },
        )
        sink(transition_event)
    except Exception:
        pass

    try:
        # tool_call: TOOL_INVOKE 完成后发射
        if invoke_result is not None:
            invoke_payload = getattr(invoke_result, "payload", {}) or {}
            tool_output = invoke_payload.get("tool_output", "")
            execution_status = invoke_payload.get("execution_status", "unknown")

            # 直接在依赖上构造一个最小 state-like 对象供 emit_tool_result_trace_event 使用
            from agent.local_trace import TraceEvent

            tool_event = TraceEvent(
                run_id=run_id or "run:unknown",
                trace_id=trace_id or "trace:unknown",
                span_id=f"tool_call:{tool_name}:turn_end",
                parent_span_id=f"turn_end:{hash(result_text) & 0x7FFFFFFF:08x}",
                span_type="tool_call",
                name=tool_name,
                status="ok" if execution_status == "success" else "failed",
                metadata={
                    "execution_status": execution_status,
                    "tool_output": tool_output[:500] if tool_output else "",
                },
            )
            sink(tool_event)
    except Exception:
        # Trace 发射异常不阻塞 loop——纯观测 side-effect
        pass


def _dispatch_tool_pipeline(
    dispatcher: Any,
    tool_gate_tool_name: str,
    provider_kind: str,
    provider_external_call: bool,
) -> Any:
    """Tool Pipeline 四阶段 dispatch（Loop 4 提取自 turn-end hook 以精简结构）。

    TOOL_GATE → TOOL_REQUEST → TOOL_INVOKE → TOOL_RESULT。
    各阶段独立 try/except，一个阶段失败不阻断其他阶段。
    返回 invoke_result（供 trace event emission 使用），可能为 None。
    """
    from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType

    route = getattr(dispatcher, "route_from_runtime_loop", None)
    if route is None:
        route = dispatcher.route

    # TOOL_GATE
    gate_result = None
    with contextlib.suppress(Exception):
        gate_result = route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="core_loop",
            parent_trace_id="",
            payload={
                "tool_name": tool_gate_tool_name,
                "tool_args": {},
                "requested_capability": "local_action",
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": provider_kind,
                "provider_external_call": provider_external_call,
                "external_side_effects": False,
            },
        ))

    # TOOL_REQUEST
    with contextlib.suppress(Exception):
        route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_REQUEST,
            source="core_loop",
            parent_trace_id="",
            payload={
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": provider_kind,
                "provider_external_call": provider_external_call,
                "external_side_effects": False,
            },
        ))

    # TOOL_INVOKE（仅在 gate allowed 时）
    invoke_result = None
    if gate_result is not None:
        gate_payload = getattr(gate_result, "payload", {}) or {}
        gate_status = getattr(gate_result, "status", "")
        if gate_status == "success" and gate_payload.get("gate_disposition") == "allowed":
            with contextlib.suppress(Exception):
                invoke_result = route(RuntimeActionRequest(
                    action_type=RuntimeActionType.TOOL_INVOKE,
                    source="core_loop",
                    parent_trace_id="",
                    payload={
                        "tool_name": tool_gate_tool_name,
                        "tool_input": {},
                        "core_loop_invoked": True,
                        "core_entrypoint": "core.chat",
                        "runtime_hook_name": "loop.turn_end",
                        "provider_kind": provider_kind,
                        "provider_external_call": provider_external_call,
                        "external_side_effects": False,
                    },
                ))

    # TOOL_RESULT
    if invoke_result is not None:
        with contextlib.suppress(Exception):
            invoke_payload = getattr(invoke_result, "payload", {}) or {}
            route(RuntimeActionRequest(
                action_type=RuntimeActionType.TOOL_RESULT,
                source="core_loop",
                parent_trace_id="",
                payload={
                    "tool_name": tool_gate_tool_name,
                    "tool_output": invoke_payload.get("tool_output", ""),
                    "execution_status": (
                        invoke_payload.get("execution_status", "success")
                        if getattr(invoke_result, "status", "") == "success"
                        else "error"
                    ),
                    "core_loop_invoked": True,
                    "core_entrypoint": "core.chat",
                    "runtime_hook_name": "loop.turn_end",
                    "provider_kind": provider_kind,
                    "provider_external_call": provider_external_call,
                    "external_side_effects": False,
                },
            ))

    return invoke_result


def _try_phase1_turn_end_runtime_action(
    state: Any,
    result_text: str,
    dispatcher: Any,
    dependencies: Any = None,
) -> None:
    """Phase 1 turn-end RuntimeAction hook。
    memory turn-end proposal + tool pipeline + checkpoint +
    consolidation + recall + skill select + subagent delegate。

    中文学习边界：
    这个函数只在 loop turn-end (result is not None) 时被调用，不参与循环内部
    决策。它构造独立的 RuntimeActionRequest（MEMORY_TURN_END_PROPOSAL、
    TOOL_GATE → TOOL_REQUEST → TOOL_INVOKE → TOOL_RESULT、CHECKPOINT_SAFE_SUMMARY、
    MEMORY_CONSOLIDATE、MEMORY_RECALL、SKILL_SELECT、SUBAGENT_DELEGATE_L0），
    各自通过 dispatcher.route_from_runtime_loop() 获得完整的 evidence chain。

    Tool 是已有介入点，ToolGate / ToolInvoke / ToolResult 不是三个独立子系统，
    而是 Tool lifecycle 的三个 pipeline stages：
      TOOL_GATE (pre-execution gating)
        → TOOL_INVOKE (execution) — 仅当 gate_disposition="allowed"
          → TOOL_RESULT (post-execution feedback)

    为什么各 stage 必须独立 try/except：
    - 每个 stage 在同一 lifecycle 触发，但各自独立
    - 一个 stage 失败不得阻断其他 stage 的 evidence
    - 不允许把多个 stage 包在同一个大 try/except 中
    - TOOL_INVOKE 异常不阻断 TOOL_RESULT（即使 invoke 失败也尝试报告错误）

    为什么 TOOL_GATE 必须显式传 tool_args：
    - _safe_noop 是 zero-arg safe tool，但 tool_args 字段必须显式存在
    - 避免 needs_tool_confirmation() 中的隐式 fallback 链
    - 未来任何带参数工具都必须传真实 tool_args，不得省略

    Hook 参数化（Phase 1 hook param）：
    - provider_kind / provider_external_call 从 dependencies 读取（core.py 预解析）
    - external_side_effects 保持 False——工具/文件/MCP/memory retain 不在本轮范围
    - loop 层不接触 provider 对象、不读 provider_type、不做 white-list 判断
    - 这不是 fake/real 两套路径——是同一条 hook，只是 metadata 值不同

    不负责什么：
    - 不推进 checkpoint state
    - 不影响 loop 返回值和 turn 语义
    - 不读/写真实 memory episodes
    - dispatcher 失败时各自 silent fail，不阻塞 loop 也不阻塞对方
    """
    from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType

    # hook 参数化：从 dependencies 读取 core.py 预解析的 provider metadata
    # 不回退到硬编码——dependencies 为 None 时使用 fail-closed 默认值
    _deps = dependencies
    provider_kind = getattr(_deps, "provider_kind", "unknown") if _deps is not None else "unknown"
    provider_external_call = (
        getattr(_deps, "provider_external_call", False) if _deps is not None else False
    )
    # tool_gate_tool_name 与 provider_kind 同模式：从 dependencies 读取，
    # 默认 _safe_noop 保持向后兼容；传 _confirmable_noop 时覆盖 confirmation_required 路径
    tool_gate_tool_name = (
        getattr(_deps, "tool_gate_tool_name", "_safe_noop") if _deps is not None else "_safe_noop"
    )

    messages = getattr(getattr(state, "conversation", None), "messages", [])
    last_user = ""
    for msg in reversed(messages):
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        if role == "user":
            content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
            if isinstance(content, str):
                last_user = content
                break

    # MEMORY action（独立 try/except——失败不阻断 TOOL_GATE）
    try:
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
            source="core_loop",
            parent_trace_id="",
            payload={
                "user_message": last_user,
                "assistant_response": result_text,
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": provider_kind,
                "provider_external_call": provider_external_call,
                "external_side_effects": False,
            },
        )
        route = getattr(dispatcher, "route_from_runtime_loop", None)
        if route is None:
            route = dispatcher.route
        route(request)
    except Exception:
        # MEMORY proposal 失败不阻塞 loop 也不阻塞 MEMORY_PROPOSE / TOOL_GATE
        pass

    # MEMORY_PROPOSE action（独立 try/except——失败不阻断 TOOL_GATE）
    # 中文学习边界：MEMORY_PROPOSE 是 retain execution 的正式路径，处理用户在 inline
    # confirmation 中确认的 proposal。与 MEMORY_TURN_END_PROPOSAL（proposal generation）
    # 各司其职：
    # - MEMORY_TURN_END_PROPOSAL → stateless proposal generator（evaluation）
    # - MEMORY_PROPOSE → confirmed proposal executor（retain execution）
    #
    # 为什么挂在 turn-end hook 上：
    # - Retain execution 需要 dispatcher evidence chain（RuntimeActionEvent）
    # - 已确认的 proposal 在 state.task.pending_retain_proposals 中跨 turn 排队
    # - turn-end 时 dispatch 确保 store 写入与 proposal generation / recall 在同一生命周期
    try:
        pending = getattr(getattr(state, "task", None), "pending_retain_proposals", None)
        if pending:
            for entry in list(pending):
                try:
                    propose_request = RuntimeActionRequest(
                        action_type=RuntimeActionType.MEMORY_PROPOSE,
                        source="core_loop",
                        parent_trace_id="",
                        payload={
                            "confirmation_result": entry.get("confirmation_result", ""),
                            "proposal_id": entry.get("proposal_id", ""),
                            "candidate": {
                                "proposal_id": entry.get("proposal_id", ""),
                                "content": entry.get("content", ""),
                                "content_hash": entry.get("content_hash", ""),
                                "scope": entry.get("scope", "user"),
                                "sensitivity": entry.get("sensitivity", "low"),
                                "source": entry.get("source", "turn_end_proposal"),
                            },
                            "core_loop_invoked": True,
                            "core_entrypoint": "core.chat",
                            "runtime_hook_name": "loop.turn_end",
                            "provider_kind": provider_kind,
                            "provider_external_call": provider_external_call,
                            "external_side_effects": False,
                        },
                    )
                    route = getattr(dispatcher, "route_from_runtime_loop", None)
                    if route is None:
                        route = dispatcher.route
                    route(propose_request)
                except Exception:
                    # 单个 proposal dispatch 失败不阻塞其他 proposal
                    pass
            # dispatch 后清空队列（即使部分失败也清空——不重复 dispatch）
            pending.clear()
    except Exception:
        # MEMORY_PROPOSE 整体失败不阻塞 loop 也不阻塞 TOOL_GATE
        pass

    # TOOL_GATE → TOOL_REQUEST → TOOL_INVOKE → TOOL_RESULT pipeline
    # Loop 4: 提取为独立 helper _dispatch_tool_pipeline，与 MEMORY/CONSOLE/SKILL 同级
    invoke_result = _dispatch_tool_pipeline(
        dispatcher=dispatcher,
        tool_gate_tool_name=tool_gate_tool_name,
        provider_kind=provider_kind,
        provider_external_call=provider_external_call,
    )

    # CHECKPOINT_SAFE_SUMMARY action（独立 try/except——失败不阻断 MEMORY 和 TOOL_GATE）
    # 中文学习边界：Checkpoint safe summary 是 turn-end hook 上的 branch behavior，
    # 不新增 Anchor、不新增 branch point、不新增 runtime flow。
    # 它只产生 checkpoint boundary evidence（safe_summary / secret_content_detected 等），
    # 不实际调用 save_checkpoint——save 仍由 core.py 在正确时机执行。
    try:
        checkpoint_request = RuntimeActionRequest(
            action_type=RuntimeActionType.CHECKPOINT_SAFE_SUMMARY,
            source="core_loop",
            parent_trace_id="",
            payload={
                "runtime_state_summary": result_text,
                "trigger": "turn_end",
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": provider_kind,
                "provider_external_call": provider_external_call,
                "external_side_effects": False,
            },
        )
        route = getattr(dispatcher, "route_from_runtime_loop", None)
        if route is None:
            route = dispatcher.route
        route(checkpoint_request)
    except Exception:
        # CHECKPOINT_SAFE_SUMMARY 失败不阻塞 loop 也不阻塞其他 dispatch
        pass

    # MEMORY_CONSOLIDATE action（独立 try/except——失败不阻断其他 dispatch）
    # 中文学习边界：Memory Consolidation 是跨回合 episodic → semantic candidate
    # 的只读 batch 分析，挂在 turn-end hook 的最末阶段执行——此时 MEMORY_RECALL
    # 已完成 context injection，store 状态最完整。不写 store（readonly）、不做
    # LLM 增强（除非 opt-in），不自动 adopt candidates（T1 review 是必经路径）。
    #
    # 为什么挂在 turn-end hook 上：
    # - consolidate 分析的是累积 episodic 记录，不是单 turn 内容
    # - 不需要模型实时决策介入——它是后台 batch 分析
    # - 错误时静默降级为 insufficient_evidence / no_candidates，不阻塞主流程
    try:
        consolidate_request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_CONSOLIDATE,
            source="core_loop",
            parent_trace_id="",
            payload={
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": provider_kind,
                "provider_external_call": provider_external_call,
                "external_side_effects": False,
            },
        )
        route = getattr(dispatcher, "route_from_runtime_loop", None)
        if route is None:
            route = dispatcher.route
        route(consolidate_request)
    except Exception:
        # MEMORY_CONSOLIDATE 失败不阻塞 loop 也不阻塞其他 dispatch
        pass

    # Loop 3 (Memory E2E): MEMORY_RECALL 已收敛到 refresh_runtime_system_prompt()
    # 中统一 dispatch，不再在 turn-end hook 中重复调用。recall 发生在每轮开始时
    # （chat() → refresh_runtime_system_prompt(dispatcher=...)），确保 system prompt
    # 通过 dispatcher 生成，fake/real 共享核心路径。

    # SKILL_SELECT action（独立 try/except——失败不阻断其他 dispatch）
    # 中文学习边界：Skill Selection 通过 turn-end hook dispatch 验证 L3 evidence
    # chain 完整。
    #
    # skill_registry 为 None 时（向后兼容）：payload 不含 skill metadata，
    # handler 返回 "no skills available"，L3 evidence 路径保持完整。
    #
    # skill_registry 可用时：从 registry 填充 available_skill_metadata；
    # fake provider 路径额外填充 model_decision_metadata（自动选择第一个可见 skill），
    # 使 handler 能走通 body_load_decision=True 成功路径。
    #
    # 为什么挂在 turn-end hook 上：
    # - 复用已有 branch point，不新增架构元素
    # - L3 evidence 关注「handler 是否从真实 runtime loop dispatch」而非
    #   「handler 是否成功 load 了一个 skill」
    # - rejected/failed disposition 不影响 evidence level
    try:
        # 中文学习注释：build skill metadata from registry（如果可用）
        _skill_registry = getattr(dependencies, "skill_registry", None)
        _skill_payload: dict[str, Any] = {
            "core_loop_invoked": True,
            "core_entrypoint": "core.chat",
            "runtime_hook_name": "loop.turn_end",
            "provider_kind": provider_kind,
            "provider_external_call": provider_external_call,
            "external_side_effects": False,
        }
        if _skill_registry is not None:
            _visible = _skill_registry.list_visible()
            # available_skill_metadata：不含 body/status 字段（handler 校验要求）
            _available_meta: list[dict[str, Any]] = []
            for _desc in _visible:
                _available_meta.append({
                    "skill_id": _desc.name,
                    "description": _desc.description,
                    "risk_level": _desc.risk_level,
                    "tags": list(_desc.tags),
                    "allowed_tools": list(_desc.allowed_tools),
                    "memory_scope": _desc.memory_scope,
                })
            _skill_payload["available_skill_metadata"] = _available_meta
            _skill_payload["task_summary"] = (result_text or "")[:500]

            # fake provider 路径：自动生成 model_decision_metadata，
            # 使 handler 走通 body_load_decision=True 成功路径
            if provider_kind == "fake" and _visible:
                _selected = _visible[0]
                _skill_payload["model_decision_metadata"] = {
                    "selected_skill_id": _selected.name,
                    "selection_reason": (
                        f"fake provider auto-selection: demo skill '{_selected.name}' "
                        f"matched for First Usable Task E2E verification"
                    ),
                    "selection_confidence": "high",
                }
            # 真实 provider 路径：确定性 keyword matching fallback。
            # 中文学习注释 —— 与 fake auto-select 的关键区别：
            # - fake: 无条件选择第一个可见 skill → 仅用于测试 L3 evidence chain
            # - real: 基于 last_user（用户输入）与 skill name/description/tags
            #   的 keyword matching → 没有匹配时不选择，保持 no_suitable_skill
            # - 匹配结果可解释（matched_terms, match_score），方便调试
            # - 确定性：相同输入总是相同输出，不依赖模型行为
            elif _visible and last_user:
                from agent.skill_selection import select_skill_for_real_provider
                _decision = select_skill_for_real_provider(last_user, _visible)
                if _decision is not None:
                    _skill_payload["model_decision_metadata"] = _decision

        skill_request = RuntimeActionRequest(
            action_type=RuntimeActionType.SKILL_SELECT,
            source="core_loop",
            parent_trace_id="",
            payload=_skill_payload,
        )
        route = getattr(dispatcher, "route_from_runtime_loop", None)
        if route is None:
            route = dispatcher.route
        route(skill_request)
    except Exception:
        # SKILL_SELECT 失败不阻塞 loop 也不阻塞其他 dispatch
        pass

    # SUBAGENT_DELEGATE_L0 action（独立 try/except——失败不阻断其他 dispatch）
    # 中文学习边界：SubAgent Delegation 通过 turn-end hook dispatch 验证 L3 evidence
    # chain 完整——handler 使用空 SubAgentRegistry（roots=()），因此总是 rejected
    # （no subagent available）。不影响现有 subagent delegation 行为（模型输出驱动的
    # mid-loop dispatch）。
    #
    # 为什么挂在 turn-end hook 上：
    # - 复用已有 branch point，不新增架构元素
    # - L3 evidence 关注「handler 是否从真实 runtime loop dispatch」而非
    #   「handler 是否成功 delegate 了一个 subagent」
    # - rejected/failed disposition 不影响 evidence level
    try:
        subagent_request = RuntimeActionRequest(
            action_type=RuntimeActionType.SUBAGENT_DELEGATE_L0,
            source="core_loop",
            parent_trace_id="",
            payload={
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": provider_kind,
                "provider_external_call": provider_external_call,
                "external_side_effects": False,
            },
        )
        route = getattr(dispatcher, "route_from_runtime_loop", None)
        if route is None:
            route = dispatcher.route
        route(subagent_request)
    except Exception:
        # SUBAGENT_DELEGATE_L0 失败不阻塞 loop 也不阻塞其他 dispatch
        pass

    # STREAMING_PROVIDER_CALL action（独立 try/except——失败不阻断 trace）
    # 中文学习边界：call_model() 已支持 streaming（model_call.py），事件在 model call
    # 阶段收集并存入 dependencies.streaming_events。turn-end hook 读取并 dispatch。
    # 当 provider 不支持 streaming 时（如 FakeProvider supports_streaming=False），
    # 不 dispatch STREAMING_PROVIDER_CALL——无论 handler 返回什么，not_supported 状态
    # 会污染 action_log 尾事件 evidence 链。
    streaming_supported = bool(getattr(dependencies, "provider_supports_streaming", False))
    if streaming_supported:
        try:
            streaming_events_raw = list(getattr(dependencies, "streaming_events", []) or [])
            serialized_events = []
            for evt in streaming_events_raw:
                serialized_events.append({
                    "event_type": getattr(evt, "event_type", ""),
                    "sequence": getattr(evt, "sequence", 0),
                    "source": getattr(evt, "source", "provider"),
                    "text_delta": getattr(evt, "text_delta", ""),
                    "is_final": getattr(evt, "is_final", False),
                    "error": getattr(evt, "error", None),
                })
            streaming_request = RuntimeActionRequest(
                action_type=RuntimeActionType.STREAMING_PROVIDER_CALL,
                source="core_loop",
                parent_trace_id="",
                payload={
                    "provider_supports_streaming": streaming_supported,
                    "events": serialized_events,
                    "core_loop_invoked": True,
                    "core_entrypoint": "core.chat",
                    "runtime_hook_name": "loop.turn_end",
                    "provider_kind": provider_kind,
                    "provider_external_call": provider_external_call,
                    "external_side_effects": False,
                },
            )
            route = getattr(dispatcher, "route_from_runtime_loop", None)
            if route is None:
                route = dispatcher.route
            route(streaming_request)
            # STREAMING_EVENT：per-event dispatch，为每个 streaming event 收集
            # 独立的 per-event evidence。不与 STREAMING_PROVIDER_CALL 聚合冲突——
            # 前者验证单 event 合法性，后者聚合整轮 streaming response。
            for serialized in serialized_events:
                try:
                    event_request = RuntimeActionRequest(
                        action_type=RuntimeActionType.STREAMING_EVENT,
                        source="core_loop",
                        parent_trace_id="",
                        payload={
                            "event": serialized,
                            "core_loop_invoked": True,
                            "core_entrypoint": "core.chat",
                            "runtime_hook_name": "loop.turn_end",
                        },
                    )
                    route(event_request)
                except Exception:
                    pass
        except Exception:
            pass

    # Trace event emission（独立 try/except——失败不阻断任何 dispatch）
    # 中文学习边界：Trace 是纯观测基础设施，不参与 runtime 决策。
    # 只在调用方显式传入 on_trace_event sink 时触发——默认路径不创建 recorder、
    # 不写 trace、不改变 checkpoint/messages。
    #
    # 为什么不用 dispatcher：
    # - TraceEvent 是事实记录（"工具 X 被调用了，结果是 Y"），不是决策点
    # - dispatcher pattern 用于 decision routing（gate/invoke/result/recall）
    # - trace 不需要证据链 provenance——它自己就是证据
    _try_trace_event_emission(dependencies, result_text, tool_gate_tool_name, invoke_result)


@dataclass(frozen=True, slots=True)
class LoopDependencies:
    """主循环依赖集合。

    这里注入的是"怎么做"的函数，而不是 durable state schema。主循环可以
    编排 call_model / dispatch_model_output / checkpoint clear，但不能因此
    理解 Memory 内部字段、UI adapter 或 provider 实现。

    Phase 1: runtime_action_dispatcher 是可选注入，允许 loop turn-end 触发
    RuntimeAction（如 memory turn-end proposal）而不污染 loop 核心逻辑。
    不传则 loop 行为与 Phase 1 之前完全一致。

    Phase 1 hook 参数化：provider_kind / provider_external_call 在 core.py
    构造点预解析后传入——loop 层不接触 provider 对象，不读取 provider_type，
    不做 white-list 判断。provider_kind 只允许 coarse-grained 三态。
    """

    state: Any
    call_model: Callable[[Any, LoopContext], Any]
    dispatch_model_output: Callable[[Any], str | None]
    runtime_loop_fields: Callable[[], dict[str, Any]]
    safe_emit_runtime_event: Callable[[Callable[[RuntimeEvent], None] | None, RuntimeEvent], None]
    clear_checkpoint: Callable[[], None]
    runtime_action_dispatcher: Any | None = None
    # hook 参数化：预解析的 coarse-grained provider evidence metadata
    # 这些字段在 core.py _run_main_loop 中由 _resolve_provider_evidence_metadata 填充
    # 不在 loop.py 中解析——loop 层保持 provider-agnostic
    provider_kind: str = "unknown"
    provider_external_call: bool = False
    provider_supports_streaming: bool = False
    # streaming_events: call_model() 中收集的流式事件，供 turn-end hook 读取
    streaming_events: list = field(default_factory=list)
    # tool_gate_tool_name 控制 TOOL_GATE action 传递的 tool_name。
    # 默认 "_safe_noop"（confirmation="never" → allowed），
    # 传入 "_confirmable_noop" 时覆盖 confirmation_required branch behavior。
    # 不传则行为与现有完全一致——向后兼容。
    tool_gate_tool_name: str = "_safe_noop"
    # skill_registry: 用于 SKILL_SELECT action 填充 available_skill_metadata。
    # 由 core.py 构造点注入，loop 层不接触 skill 系统实现细节。
    # 默认 None——兼容旧行为（payload 不含 skill metadata，handler 返回
    # "no skills available" 但 L3 evidence 路径保持完整）。
    skill_registry: Any = None
    # Trace event sink（opt-in observability infrastructure）
    # 默认 None——不创建 recorder、不写 trace、零开销。
    on_trace_event: Any = None
    trace_run_id: str | None = None
    trace_id: str | None = None


def _emit_run_summary(
    turn_state: Any,
    loop_ctx: LoopContext,
    dependencies: LoopDependencies,
    *,
    cached_loop_iterations: int | None = None,
    cached_tool_calls: int | None = None,
) -> None:
    """在每次 return 前产出 run.summary RuntimeEvent。

    中文学习边界：
    - 从 RuntimeActionDispatcher.action_log 统计各类 evidence 事件
    - 从 TurnState.task 读取循环计数和工具调用计数
    - 产出结构化摘要文本，经 safe_emit_runtime_event 送达用户
    - 这是 display/observation event，不含 decision 语义
    """
    from agent.display_events import run_summary_event
    from agent.runtime_decision_frame import get_last_decision_frame
    from agent.runtime_integration.schema import classify_action_evidence_kind

    # Loop 1.1: 拉取当前 turn 的 decision frame 摘要，供 evidence 引用
    d_frame = get_last_decision_frame()
    decision_summary: dict[str, Any] | None = None
    if d_frame is not None:
        decision_summary = d_frame.capability_summary()
        decision_summary["provider_mode"] = d_frame.provider_mode
        decision_summary["evidence_level"] = d_frame.evidence_level.value

    dispatcher = getattr(dependencies, "runtime_action_dispatcher", None)
    action_log = getattr(dispatcher, "action_log", ()) if dispatcher is not None else ()

    memory_ops = 0
    subagent_delegations = 0
    tool_names: list[str] = []
    memory_actions: list[str] = []
    subagent_names: list[str] = []
    error_reasons: list[str] = []
    business_events = 0
    probe_events = 0

    # 中文学习说明：turn_end hook 每轮无条件运行 MEMORY_TURN_END_PROPOSAL、
    # MEMORY_CONSOLIDATE、MEMORY_RECALL、SUBAGENT_DELEGATE_L0。它们是 lifecycle
    # check，大多数时候无有效结果（no_action / insufficient_evidence / no_memory /
    # rejected）。run summary 给用户看，必须区分 effective action 和 internal check。
    # 有效 memory disposition：proposed / retain / not_retained / recalled / consolidated
    # 无效 disposition：no_action / should_not_remember / insufficient_evidence /
    #   no_candidates / no_memory / rejected / failed / not_supported
    _effective_memory_dispositions = frozenset({
        "proposed", "retain", "not_retained", "recalled", "consolidated",
    })

    for event in action_log:
        at = str(getattr(event, "action_type", ""))
        status = str(getattr(event, "status", ""))
        evidence = getattr(event, "evidence", None)
        disposition = ""
        if isinstance(evidence, Mapping):
            disposition = str(evidence.get("disposition", ""))

        # 统计 evidence kind（business vs probe）
        ev_kind = classify_action_evidence_kind(at)
        if ev_kind == "business":
            business_events += 1
        else:
            probe_events += 1

        if at.startswith("memory."):
            # 只统计有效操作：status=success 且 disposition 在有效集合中
            if status == "success" and disposition in _effective_memory_dispositions:
                memory_ops += 1
                action_name = at.removeprefix("memory.")
                memory_actions.append(action_name)
        elif at.startswith("subagent."):
            # 只统计真实 delegation（status=success），routing check（rejected）不计入
            if status == "success":
                subagent_delegations += 1
                target = str(getattr(event, "target_identity", ""))
                if target:
                    subagent_names.append(target)
        elif at.startswith("tool."):
            target = str(getattr(event, "target_identity", ""))
            if target:
                tool_names.append(target)

    # 也从 state 中提取本轮工具调用信息（如果 action_log 没有 tool 事件）
    state = dependencies.state
    loop_iterations = (
        cached_loop_iterations
        if cached_loop_iterations is not None
        else getattr(state.task, "loop_iterations", 0)
    )
    tool_calls = (
        cached_tool_calls
        if cached_tool_calls is not None
        else getattr(state.task, "tool_call_count", 0)
    )

    stop_reason = "正常结束"
    if loop_iterations > loop_ctx.max_loop_iterations:
        stop_reason = f"达到最大循环次数 ({loop_ctx.max_loop_iterations})"

    summary_event = run_summary_event(
        loop_iterations=loop_iterations,
        tool_calls=tool_calls,
        memory_operations=memory_ops,
        subagent_delegations=subagent_delegations,
        stop_reason=stop_reason,
        tool_names=tool_names,
        memory_actions=memory_actions,
        subagent_names=subagent_names,
        error_reasons=error_reasons,
        business_events=business_events,
        probe_events=probe_events,
        decision_frame_summary=decision_summary,
    )
    dependencies.safe_emit_runtime_event(turn_state.on_runtime_event, summary_event)


def run_main_loop(
    turn_state: Any,
    loop_ctx: LoopContext,
    dependencies: LoopDependencies,
) -> str:
    """执行模型调用主循环,保持行为中性的 orchestration 层。

    本函数只做:
    - 增加 loop iteration;
    - 调模型;
    - 把模型输出交给 dispatcher;
    - 处理最大循环次数兜底。

    它不解析 Memory, Tool, CLI/TUI 或 confirmation 内部语义;这些语义仍由
    注入的 owner 函数和原有 handler 负责。
    """

    state = dependencies.state
    runtime_loop_fields = dependencies.runtime_loop_fields

    log_runtime_event(
        "loop.start",
        event_source="runtime",
        event_payload=runtime_loop_fields(),
        event_channel="loop",
    )
    while True:
        state.task.loop_iterations += 1
        log_runtime_event(
            "loop.iteration_start",
            event_source="runtime",
            event_payload=runtime_loop_fields(),
            event_channel="loop",
        )
        if state.task.loop_iterations > loop_ctx.max_loop_iterations:
            _guard_loop_iterations = state.task.loop_iterations
            _guard_tool_calls = state.task.tool_call_count
            log_runtime_event(
                "loop.guard_triggered",
                event_source="runtime",
                event_payload={
                    **runtime_loop_fields(),
                    "reason_for_stop": "max_loop_iterations",
                },
                event_channel="loop",
            )
            event = loop_max_iterations_event(loop_ctx.max_loop_iterations)
            dependencies.safe_emit_runtime_event(turn_state.on_runtime_event, event)
            dependencies.clear_checkpoint()
            state.reset_task()
            _emit_run_summary(
                turn_state,
                loop_ctx,
                dependencies,
                cached_loop_iterations=_guard_loop_iterations,
                cached_tool_calls=_guard_tool_calls,
            )
            return "对话循环次数过多，请简化任务或分步执行。"

        response = dependencies.call_model(turn_state, loop_ctx)
        _cached_loop_iterations = state.task.loop_iterations
        _cached_tool_calls = state.task.tool_call_count
        result = dependencies.dispatch_model_output(response)
        if result is not None:
            # Phase 1 turn-end hook: 在真实 core loop 路径中触发 RuntimeAction，
            # 证明 action originate from core.chat/runtime loop 而非 dogfood harness。
            if dependencies.runtime_action_dispatcher is not None:
                _try_phase1_turn_end_runtime_action(
                    dependencies.state, result, dependencies.runtime_action_dispatcher,
                    dependencies=dependencies,
                )
            _emit_run_summary(
                turn_state,
                loop_ctx,
                dependencies,
                cached_loop_iterations=_cached_loop_iterations,
                cached_tool_calls=_cached_tool_calls,
            )
            return result
