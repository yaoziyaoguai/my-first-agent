"""ToolRuntimeMediator — dispatcher-mediated tool execution bridge.

Loop 1.3 方案 2：dispatcher 中介层，坐在 model tool_use 和 tool executor 之间。

职责：
- 对每个业务 tool_use block，通过 dispatcher 提供 TOOL_GATE → TOOL_INVOKE →
  execute_single_tool → TOOL_RESULT 的完整 lifecycle evidence
- execute_single_tool 作为底层 executor 被复用（拥有 confirmation/policy/audit/
  display/checkpoint/messages 等所有能力）
- handle_tool_use_response 通过 mediator 调用，不再裸调 execute_single_tool

防呆：
- 不得在 execute_single_tool 之后补 evidence（方案 3）
- TOOL_GATE 必须在 execute_single_tool 之前调用
- TOOL_INVOKE 必须包住 execute_single_tool
"""

from __future__ import annotations

import contextlib
from typing import Any

from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType
from agent.tool_executor import AWAITING_USER, FORCE_STOP, execute_single_tool


class ToolRuntimeMediator:
    """Dispatcher-mediated tool execution 中介层。

    dispatcher 提供 TOOL_GATE / TOOL_INVOKE / TOOL_RESULT evidence lifecycle；
    execute_single_tool 提供 confirmation / policy / audit / display / checkpoint /
    messages 等所有执行能力。mediator 协调两者，不替代任何一方。
    """

    def __init__(
        self,
        dispatcher: Any,
        *,
        state: Any,
        turn_state: Any,
        turn_context: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> None:
        self._dispatcher = dispatcher
        self._state = state
        self._turn_state = turn_state
        self._turn_context = turn_context
        self._messages = messages

    def mediate(self, block: Any) -> str | None:
        """对单个业务 tool_use block 执行 dispatcher-mediated execution。

        Returns:
            None: 正常执行完成
            AWAITING_USER: 需要用户确认（由 execute_single_tool 设置 pending_tool）
            FORCE_STOP: 被安全策略阻断
        """
        tool_name = block.name
        tool_input = block.input
        tool_use_id = block.id

        # Step 1: TOOL_GATE — dispatcher 门控（参与真实执行生命周期）
        self._route_gate(tool_name, tool_input, tool_use_id)

        # Step 2: TOOL_INVOKE — dispatcher 记录工具调用
        self._route_invoke(tool_name, tool_input, tool_use_id)

        # Step 3: 真实执行 — execute_single_tool 作为底层 executor
        # 拥有 confirmation / policy / audit / display / checkpoint / messages 全部能力
        result = execute_single_tool(
            block,
            state=self._state,
            turn_state=self._turn_state,
            turn_context=self._turn_context,
            messages=self._messages,
        )

        # Step 4: TOOL_RESULT — dispatcher 记录执行结果
        self._route_result(tool_name, tool_input, tool_use_id, result)

        return result

    # ── private helpers ────────────────────────────────────────────────────

    def _route_gate(
        self, tool_name: str, tool_input: Any, tool_use_id: str
    ) -> None:
        """TOOL_GATE：dispatcher 门控 evidence（execute_single_tool 之前调用）。"""
        with contextlib.suppress(Exception):
            self._dispatcher.route_from_runtime_loop(
                RuntimeActionRequest(
                    action_type=RuntimeActionType.TOOL_GATE,
                    source="ToolRuntimeMediator",
                    parent_trace_id=tool_use_id,
                    payload={
                        "tool_name": tool_name,
                        "tool_input": dict(tool_input) if tool_input else {},
                    },
                ),
                core_entrypoint="core.chat",
                runtime_hook_name="handle_tool_use_response",
            )

    def _route_invoke(
        self, tool_name: str, tool_input: Any, tool_use_id: str
    ) -> None:
        """TOOL_INVOKE：dispatcher 记录工具调用（execute_single_tool 之前调用）。"""
        with contextlib.suppress(Exception):
            self._dispatcher.route_from_runtime_loop(
                RuntimeActionRequest(
                    action_type=RuntimeActionType.TOOL_INVOKE,
                    source="ToolRuntimeMediator",
                    parent_trace_id=tool_use_id,
                    payload={
                        "tool_name": tool_name,
                        "tool_input": dict(tool_input) if tool_input else {},
                    },
                ),
                core_entrypoint="core.chat",
                runtime_hook_name="handle_tool_use_response",
            )

    def _route_result(
        self,
        tool_name: str,
        tool_input: Any,
        tool_use_id: str,
        result: str | None,
    ) -> None:
        """TOOL_RESULT：dispatcher 记录执行结果（execute_single_tool 之后调用）。

        result 为 None → success；FORCE_STOP → blocked；AWAITING_USER → pending。
        """
        result_text = str(self._turn_context.get(tool_use_id, ""))[:500]
        if result is None:
            status = "executed"
        elif result == FORCE_STOP:
            status = "blocked_by_policy"
        elif result == AWAITING_USER:
            status = "awaiting_confirmation"
        else:
            status = "unknown"

        with contextlib.suppress(Exception):
            self._dispatcher.route_from_runtime_loop(
                RuntimeActionRequest(
                    action_type=RuntimeActionType.TOOL_RESULT,
                    source="ToolRuntimeMediator",
                    parent_trace_id=tool_use_id,
                    payload={
                        "tool_name": tool_name,
                        "tool_input": dict(tool_input) if tool_input else {},
                        "status": status,
                        "result_summary": result_text,
                    },
                ),
                core_entrypoint="core.chat",
                runtime_hook_name="handle_tool_use_response",
            )
