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
) -> None:
    """Phase 1 turn-end RuntimeAction hook：memory turn-end proposal。

    中文学习边界：
    这个函数只在 loop turn-end (result is not None) 时被调用，不参与循环内部
    决策。它构造一个 memory.turn_end_proposal RuntimeActionRequest，通过
    dispatcher.route() 获得完整的 evidence chain（route/result/proof）。
    因为调用发生在真实 core loop 路径中，evidence 中的 core_loop_invoked=true
    字段允许 classifier 把这次 action 标为 real_core_loop_runtime_e2e。

    为什么选择 memory turn-end proposal：
    - 语义最干净：turn-end 是自然边界，不需要额外条件判断
    - pending_review only：不自动批准，不写真实 memory episodes
    - handler 已存在（MemoryTurnEndProposalHandler），不需新建
    - deterministic policy 确保无副作用

    不负责什么：
    - 不推进 checkpoint state
    - 不影响 loop 返回值和 turn 语义
    - 不读/写真实 memory episodes
    - dispatcher 失败时 silent fail，不阻塞 loop
    """
    try:
        from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType

        messages = getattr(getattr(state, "conversation", None), "messages", [])
        last_user = ""
        for msg in reversed(messages):
            role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
            if role == "user":
                content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
                if isinstance(content, str):
                    last_user = content
                    break

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
                "provider_kind": "fake",
                "external_side_effects": False,
            },
        )
        dispatcher.route(request)
    except Exception:
        # Phase 1 hook 必须 silent fail：不阻塞 loop、不改变 turn 语义
        pass


@dataclass(frozen=True, slots=True)
class LoopDependencies:
    """主循环依赖集合。

    这里注入的是”怎么做”的函数，而不是 durable state schema。主循环可以
    编排 call_model / dispatch_model_output / checkpoint clear，但不能因此
    理解 Memory 内部字段、UI adapter 或 provider 实现。

    Phase 1: runtime_action_dispatcher 是可选注入，允许 loop turn-end 触发
    RuntimeAction（如 memory turn-end proposal）而不污染 loop 核心逻辑。
    不传则 loop 行为与 Phase 1 之前完全一致。
    """

    state: Any
    call_model: Callable[[Any, LoopContext], Any]
    dispatch_model_output: Callable[[Any], str | None]
    runtime_loop_fields: Callable[[], dict[str, Any]]
    safe_emit_runtime_event: Callable[[Callable[[RuntimeEvent], None] | None, RuntimeEvent], None]
    clear_checkpoint: Callable[[], None]
    runtime_action_dispatcher: Any | None = None


def run_main_loop(
    turn_state: Any,
    loop_ctx: LoopContext,
    dependencies: LoopDependencies,
) -> str:
    """执行模型调用主循环，保持行为中性的 orchestration 层。

    本函数只做：
    - 增加 loop iteration；
    - 调模型；
    - 把模型输出交给 dispatcher；
    - 处理最大循环次数兜底。

    它不解析 Memory、Tool、CLI/TUI 或 confirmation 内部语义；这些语义仍由
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
                )
            return result
