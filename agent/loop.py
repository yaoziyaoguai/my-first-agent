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

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent.display_events import RuntimeEvent, loop_max_iterations_event
from agent.loop_context import LoopContext
from agent.runtime_observer import log_event as log_runtime_event


def _try_phase1_turn_end_runtime_action(
    state: Any,
    result_text: str,
    dispatcher: Any,
    dependencies: Any = None,
) -> None:
    """Phase 1 turn-end RuntimeAction hook：memory turn-end proposal + tool pipeline + checkpoint + consolidation + recall。

    中文学习边界：
    这个函数只在 loop turn-end (result is not None) 时被调用，不参与循环内部
    决策。它构造独立的 RuntimeActionRequest（MEMORY_TURN_END_PROPOSAL、
    TOOL_GATE → TOOL_INVOKE → TOOL_RESULT、CHECKPOINT_SAFE_SUMMARY、
    MEMORY_CONSOLIDATE、MEMORY_RECALL），各自通过
    dispatcher.route_from_runtime_loop() 获得完整的 evidence chain。

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
    provider_kind = getattr(dependencies, "provider_kind", "unknown") if dependencies is not None else "unknown"
    provider_external_call = getattr(dependencies, "provider_external_call", False) if dependencies is not None else False
    # tool_gate_tool_name 与 provider_kind 同模式：从 dependencies 读取，
    # 默认 _safe_noop 保持向后兼容；传 _confirmable_noop 时覆盖 confirmation_required 路径
    tool_gate_tool_name = getattr(dependencies, "tool_gate_tool_name", "_safe_noop") if dependencies is not None else "_safe_noop"

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
        route = getattr(dispatcher, "route_from_runtime_loop", dispatcher.route)
        route(request)
    except Exception:
        # MEMORY action 失败不阻塞 loop 也不阻塞 TOOL_GATE
        pass

    # TOOL_GATE action（独立 try/except——失败不阻断 MEMORY）
    # 捕获 gate_result 以判断是否允许调用工具（gate_disposition）
    gate_result = None
    try:
        tool_gate_request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="core_loop",
            parent_trace_id="",
            payload={
                "tool_name": tool_gate_tool_name,
                # 显式传 tool_args——_safe_noop/_confirmable_noop 是 zero-arg safe tool，
                # 但避免 needs_tool_confirmation() 中的隐式 fallback 链。
                # 未来任何带参数工具都必须传真实 tool_args，不得省略。
                "tool_args": {},
                "requested_capability": "local_action",
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": provider_kind,
                "provider_external_call": provider_external_call,
                "external_side_effects": False,
            },
        )
        route = getattr(dispatcher, "route_from_runtime_loop", dispatcher.route)
        gate_result = route(tool_gate_request)
    except Exception:
        # TOOL_GATE action 失败不阻塞 loop 也不阻塞 MEMORY
        pass

    # TOOL_INVOKE action（独立 try/except——gate allowed 后调用工具）
    # ToolGate / ToolInvoke / ToolResult 是 Tool lifecycle 的三个 pipeline stages，
    # 不是三个独立子系统。它们共享同一个 ToolRegistry、同一个 dispatcher、
    # 同一个 unified runtime flow 入口。
    invoke_result = None
    if gate_result is not None:
        gate_payload = getattr(gate_result, "payload", {}) or {}
        gate_status = getattr(gate_result, "status", "")
        if gate_status == "success" and gate_payload.get("gate_disposition") == "allowed":
            try:
                invoke_request = RuntimeActionRequest(
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
                )
                route = getattr(dispatcher, "route_from_runtime_loop", dispatcher.route)
                invoke_result = route(invoke_request)
            except Exception:
                # TOOL_INVOKE 失败不阻塞 loop 也不阻断 TOOL_RESULT
                pass

    # TOOL_RESULT action（独立 try/except——即使 TOOL_INVOKE 抛异常也尝试构造）
    # 仅当 invoke_result 非 None 时构造（invoke 异常时有 invoke_result=None，
    # 无法提取 tool_output/execution_status，跳过 TOOL_RESULT）。
    # execution_status 现在根据 invoke_result.status 判定：
    #   - invoke_result.status == "success" → 使用 payload 中的 execution_status
    #   - invoke_result.status != "success" → execution_status = "error"
    # 此前版本无条件默认 "success"，现已修复（P2 focused remediation）。
    if invoke_result is not None:
        try:
            invoke_payload = getattr(invoke_result, "payload", {}) or {}
            result_request = RuntimeActionRequest(
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
            )
            route = getattr(dispatcher, "route_from_runtime_loop", dispatcher.route)
            route(result_request)
        except Exception:
            # TOOL_RESULT 失败不阻塞 loop
            pass

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
        route = getattr(dispatcher, "route_from_runtime_loop", dispatcher.route)
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
        route = getattr(dispatcher, "route_from_runtime_loop", dispatcher.route)
        route(consolidate_request)
    except Exception:
        # MEMORY_CONSOLIDATE 失败不阻塞 loop 也不阻塞其他 dispatch
        pass

    # MEMORY_RECALL action（独立 try/except——失败不阻断其他 dispatch）
    # 中文学习边界：Memory Recall 是跨回合只读 snapshot 生成，挂在 turn-end hook
    # 的最末阶段执行——此时 MEMORY_CONSOLIDATE 已完成，store 状态最完整。
    # 只读操作（不写 store），生成 governed MemorySnapshot 用于下一轮 context injection。
    #
    # 为什么挂在 turn-end hook 上：
    # - recall 读取的是累积 store 状态，不依赖当前 turn 的模型输出
    # - turn-end 时 store 状态最完整（retain + consolidate 均已完成）
    # - 错误时静默降级为 no_memory，不影响主流程
    try:
        recall_request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_RECALL,
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
        route = getattr(dispatcher, "route_from_runtime_loop", dispatcher.route)
        route(recall_request)
    except Exception:
        # MEMORY_RECALL 失败不阻塞 loop 也不阻塞其他 dispatch
        pass


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
    # 这两个字段在 core.py _run_main_loop 中由 _resolve_provider_evidence_metadata 填充
    # 不在 loop.py 中解析——loop 层保持 provider-agnostic
    provider_kind: str = "unknown"
    provider_external_call: bool = False
    # tool_gate_tool_name 控制 TOOL_GATE action 传递的 tool_name。
    # 默认 "_safe_noop"（confirmation="never" → allowed），
    # 传入 "_confirmable_noop" 时覆盖 confirmation_required branch behavior。
    # 不传则行为与现有完全一致——向后兼容。
    tool_gate_tool_name: str = "_safe_noop"


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
            return "对话循环次数过多，请简化任务或分步执行。"

        response = dependencies.call_model(turn_state, loop_ctx)
        result = dependencies.dispatch_model_output(response)
        if result is not None:
            # Phase 1 turn-end hook: 在真实 core loop 路径中触发 RuntimeAction，
            # 证明 action originate from core.chat/runtime loop 而非 dogfood harness。
            if dependencies.runtime_action_dispatcher is not None:
                _try_phase1_turn_end_runtime_action(
                    dependencies.state, result, dependencies.runtime_action_dispatcher,
                    dependencies=dependencies,
                )
            return result
