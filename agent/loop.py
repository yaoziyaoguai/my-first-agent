"""Runtime loop orchestration extracted from `agent.core`.

学习型说明：
`agent.core` 仍是稳定 public API 的承载处，例如 `chat()`；本模块只承载
模型循环的 orchestration。它通过 `LoopDependencies` 接收模型调用、输出分派、
checkpoint 清理和 RuntimeEvent 投影函数，避免 loop 反向 import Memory、UI、
CLI/TUI adapter 或 provider 细节。

这个边界降低 `core.py` 巨石化风险，但不改变状态机语义：checkpoint、tool
execution、request_user_input、memory hook 的行为仍由原 owner 负责。

Phase 1 hook：``_try_phase1_turn_end_runtime_action`` 在 loop turn-end 时
调用 RuntimeActionDispatcher，证明 RuntimeAction 确实由真实 core loop 触发，
而非 dogfood harness 直接 dispatcher.route()。这是 classification 从
harness_runtime_e2e 升级到 real_core_loop_runtime_e2e 的必要条件。
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
    """Phase 1 turn-end RuntimeAction hook：memory turn-end proposal + tool gate。

    中文学习边界：
    这个函数只在 loop turn-end (result is not None) 时被调用，不参与循环内部
    决策。它构造两个独立的 RuntimeActionRequest（MEMORY_TURN_END_PROPOSAL 和
    TOOL_GATE），各自通过 dispatcher.route() 获得完整的 evidence chain。

    为什么 MEMORY 和 TOOL_GATE 必须独立 try/except：
    - 两个 action 在同一 lifecycle 触发，但各自独立
    - MEMORY 失败不得阻断 TOOL_GATE evidence（反之亦然）
    - 不允许把两个 action 包在同一个大 try/except 中——一个 action 的异常
      不能导致另一个 action 消失

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
        dispatcher.route(request)
    except Exception:
        # MEMORY action 失败不阻塞 loop 也不阻塞 TOOL_GATE
        pass

    # TOOL_GATE action（独立 try/except——失败不阻断 MEMORY）
    try:
        tool_gate_request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="core_loop",
            parent_trace_id="",
            payload={
                "tool_name": "_safe_noop",
                # 显式传 tool_args——_safe_noop 是 zero-arg safe tool，
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
        dispatcher.route(tool_gate_request)
    except Exception:
        # TOOL_GATE action 失败不阻塞 loop 也不阻塞 MEMORY
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
