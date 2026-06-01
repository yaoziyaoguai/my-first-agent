"""Small factories for core runtime dependency containers.

学习型说明：
`core.py` 负责决定什么时候创建 runtime context；本模块只负责"如何组装"
这些容器。这样可以降低 core 主入口的阅读负担，同时不把 durable state 写入
LoopContext 或 ConfirmationContext。

provider 注入：
`build_loop_context` 支持可选的 `provider` 参数。传入则直接作为
`LoopContext.model_provider`；不传则回退到 `build_model_provider_from_env()`
（生产默认安全路径）。这使 E2E / dogfood 测试可以显式注入 provider 而不需要
monkeypatch `agent.core_contexts.build_model_provider_from_env`。
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
    provider: Any = None,
    runtime_action_dispatcher: Any = None,
    runtime_identity: Any = None,
) -> LoopContext:
    """构造 runtime-only LoopContext；不包含 checkpoint/durable state。

    Args:
        client_obj: Anthropic SDK client 实例。
        model_name: 模型名称。
        max_loop_iterations: 最大循环迭代次数。
        provider: 可选的 ModelProvider 实例。传入则直接作为 model_provider；
                  不传则回退到 build_model_provider_from_env()（生产默认路径）。
        runtime_action_dispatcher: Phase 1 RuntimeActionDispatcher 注入点。
                                   不传则 loop 行为不变（向后兼容）。
        runtime_identity: B7 RuntimeIdentity 注入点（multi-instance readiness）。
    """

    return LoopContext(
        client=client_obj,
        model_name=model_name,
        max_loop_iterations=max_loop_iterations,
        model_provider=provider if provider is not None else build_model_provider_from_env(),
        runtime_action_dispatcher=runtime_action_dispatcher,
        runtime_identity=runtime_identity,
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
        dispatcher=loop_ctx.runtime_action_dispatcher,
    )
