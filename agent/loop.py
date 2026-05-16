"""Runtime loop orchestration extracted from `agent.core`.

学习型说明：
`agent.core` 仍是稳定 public API 的承载处，例如 `chat()`；本模块只承载
模型循环的 orchestration。它通过 `LoopDependencies` 接收模型调用、输出分派、
checkpoint 清理和 RuntimeEvent 投影函数，避免 loop 反向 import Memory、UI、
CLI/TUI adapter 或 provider 细节。

这个边界降低 `core.py` 巨石化风险，但不改变状态机语义：checkpoint、tool
execution、request_user_input、memory hook 的行为仍由原 owner 负责。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent.display_events import RuntimeEvent, loop_max_iterations_event
from agent.loop_context import LoopContext
from agent.runtime_observer import log_event as log_runtime_event


@dataclass(frozen=True, slots=True)
class LoopDependencies:
    """主循环依赖集合。

    这里注入的是“怎么做”的函数，而不是 durable state schema。主循环可以
    编排 call_model / dispatch_model_output / checkpoint clear，但不能因此
    理解 Memory 内部字段、UI adapter 或 provider 实现。
    """

    state: Any
    call_model: Callable[[Any, LoopContext], Any]
    dispatch_model_output: Callable[[Any], str | None]
    runtime_loop_fields: Callable[[], dict[str, Any]]
    safe_emit_runtime_event: Callable[[Callable[[RuntimeEvent], None] | None, RuntimeEvent], None]
    clear_checkpoint: Callable[[], None]


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
            return result
