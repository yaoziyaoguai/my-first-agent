"""Small factories for core runtime dependency containers.

学习型说明：
`core.py` 负责决定什么时候创建 runtime context；本模块只负责“如何组装”
这些容器。这样可以降低 core 主入口的阅读负担，同时不把 durable state 写入
LoopContext 或 ConfirmationContext。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent.confirm_handlers import ConfirmationContext
from agent.loop_context import LoopContext
from agent.provider.factory import build_model_provider_from_env


def build_loop_context(
    client_obj: Any,
    *,
    model_name: str,
    max_loop_iterations: int,
) -> LoopContext:
    """构造 runtime-only LoopContext；不包含 checkpoint/durable state。"""

    return LoopContext(
        client=client_obj,
        model_name=model_name,
        max_loop_iterations=max_loop_iterations,
        model_provider=build_model_provider_from_env(),
    )


def build_confirmation_context(
    *,
    state: Any,
    turn_state: Any,
    loop_ctx: LoopContext,
    continue_fn: Callable[[Any], str],
    start_planning_fn: Callable[[str, Any], str],
    memory_runtime: Any,
) -> ConfirmationContext:
    """构造 handler dependency bundle；函数引用不进 checkpoint/schema。"""

    return ConfirmationContext(
        state=state,
        turn_state=turn_state,
        client=loop_ctx.client,
        model_name=loop_ctx.model_name,
        continue_fn=continue_fn,
        start_planning_fn=start_planning_fn,
        memory_runtime=memory_runtime,
    )
