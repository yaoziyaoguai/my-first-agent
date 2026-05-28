"""ToolRuntimeMediator — dispatcher-mediated tool execution bridge.

Loop 1.3 方案 2：dispatcher 中介层，坐在 model tool_use 和 tool executor 之间。

职责：
- 对每个业务 tool_use block，通过 dispatcher 提供 TOOL_GATE → TOOL_INVOKE →
  execute_single_tool → TOOL_RESULT 的完整 lifecycle evidence
- execute_single_tool 作为底层 executor 被复用（拥有 confirmation/policy/audit/
  display/checkpoint/messages 等所有能力）
- handle_tool_use_response 通过 mediator 调用，不再裸调 execute_single_tool

Loop 1.3b：gate_disposition 驱动执行流
- TOOL_GATE 返回 gate_disposition：allowed / rejected / confirmation_required / None
- allowed → 继续 TOOL_INVOKE → execute_single_tool → TOOL_RESULT
- rejected / None → 不执行工具，返回 FORCE_STOP（安全失败）
- confirmation_required → 不执行工具，设置 pending_tool，返回 AWAITING_USER

防呆：
- 不得在 execute_single_tool 之后补 evidence（方案 3）
- TOOL_GATE 必须在 execute_single_tool 之前调用
- TOOL_INVOKE 必须包住 execute_single_tool
- blocked / rejected / confirmation_required / malformed 不得进入 execute_single_tool
"""

from __future__ import annotations

import contextlib
from typing import Any

from agent.conversation_events import append_tool_result
from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType
from agent.tool_executor import AWAITING_USER, FORCE_STOP, execute_single_tool


class ToolRuntimeMediator:
    """Dispatcher-mediated tool execution 中介层。

    dispatcher 提供 TOOL_GATE / TOOL_INVOKE / TOOL_RESULT evidence lifecycle；
    execute_single_tool 提供 confirmation / policy / audit / display / checkpoint /
    messages 等所有执行能力。mediator 协调两者，不替代任何一方。

    Loop 1.3b：gate_disposition 控制执行流，blocked/rejected/confirmation_required
    不会进入 execute_single_tool。
    """

    def __init__(
        self,
        dispatcher: Any,
        *,
        state: Any,
        turn_state: Any,
        turn_context: dict[str, Any],
        messages: list[dict[str, Any]],
        skill_allowed_tools: frozenset[str] | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._state = state
        self._turn_state = turn_state
        self._turn_context = turn_context
        self._messages = messages
        self._skill_allowed_tools = skill_allowed_tools

    # ── public ────────────────────────────────────────────────────────────

    def mediate(self, block: Any) -> str | None:
        """对单个业务 tool_use block 执行 dispatcher-mediated execution。

        Loop 1.3b：gate_disposition 驱动执行流：
        - allowed → TOOL_INVOKE → execute_single_tool → TOOL_RESULT
        - rejected / None → FORCE_STOP（安全失败，不执行工具）
        - confirmation_required → AWAITING_USER（等待用户确认，不执行工具）

        Returns:
            None: 正常执行完成
            AWAITING_USER: 需要用户确认（由 gate_disposition="confirmation_required" 触发）
            FORCE_STOP: 被 gate 阻断（由 gate_disposition="rejected"/None 触发）
        """
        tool_name = block.name
        tool_input = block.input
        tool_use_id = block.id

        # Step 1: TOOL_GATE — dispatcher 门控（参与真实执行生命周期）
        gate_disposition = self._route_gate(tool_name, tool_input, tool_use_id)

        # Step 2: 根据 gate_disposition 分流
        if gate_disposition == "rejected" or gate_disposition is None:
            # 安全失败：blocked / rejected / malformed → 不执行工具
            self._handle_blocked(tool_name, tool_input, tool_use_id, gate_disposition)
            self._route_result(tool_name, tool_input, tool_use_id, FORCE_STOP)
            return FORCE_STOP

        if gate_disposition == "confirmation_required":
            # 需要用户确认 → 不执行工具，设置 pending_tool
            self._handle_confirmation_required(tool_name, tool_input, tool_use_id)
            self._route_result(tool_name, tool_input, tool_use_id, AWAITING_USER)
            return AWAITING_USER

        # gate_disposition == "allowed"
        # Step 3: TOOL_INVOKE — dispatcher 记录工具调用
        self._route_invoke(tool_name, tool_input, tool_use_id)

        # Step 4: 真实执行 — execute_single_tool 作为底层 executor
        result = execute_single_tool(
            block,
            state=self._state,
            turn_state=self._turn_state,
            turn_context=self._turn_context,
            messages=self._messages,
        )

        # Step 5: TOOL_RESULT — dispatcher 记录执行结果
        self._route_result(tool_name, tool_input, tool_use_id, result)

        return result

    # ── gate disposition handlers ─────────────────────────────────────────

    def _handle_blocked(
        self,
        tool_name: str,
        tool_input: Any,
        tool_use_id: str,
        gate_disposition: str | None,
    ) -> None:
        """处理 blocked/rejected/malformed gate result：不执行工具。"""
        reason = (
            "工具被安全策略拒绝"
            if gate_disposition == "rejected"
            else "工具门控结果异常，安全失败"
        )
        result_text = f"[安全策略] {reason}：{tool_name}"
        append_tool_result(self._messages, tool_use_id, result_text)
        self._state.task.tool_execution_log[tool_use_id] = {
            "tool": tool_name,
            "input": dict(tool_input) if tool_input else {},
            "result": result_text,
            "status": "blocked_by_policy",
            "step_index": self._state.task.current_step_index,
        }

    def _handle_confirmation_required(
        self,
        tool_name: str,
        tool_input: Any,
        tool_use_id: str,
    ) -> None:
        """处理 confirmation_required gate result：设置 pending_tool。"""
        from agent.checkpoint import save_checkpoint

        self._state.task.pending_tool = {
            "tool_use_id": tool_use_id,
            "tool": tool_name,
            "input": dict(tool_input) if tool_input else {},
        }
        self._state.task.status = "awaiting_tool_confirmation"
        save_checkpoint(self._state)

    # ── private helpers ────────────────────────────────────────────────────

    def _route_gate(
        self, tool_name: str, tool_input: Any, tool_use_id: str
    ) -> str | None:
        """TOOL_GATE：dispatcher 门控 evidence（execute_single_tool 之前调用）。

        Loop 2.2b: skill_allowed_tools 传入 payload，由 ToolGateHandler 执行
        skill 工具约束检查，非允许工具返回 rejected。

        Returns:
            gate_disposition: "allowed" / "rejected" / "confirmation_required" / None
        """
        try:
            gate_payload: dict[str, Any] = {
                "tool_name": tool_name,
                "tool_input": dict(tool_input) if tool_input else {},
            }
            if self._skill_allowed_tools is not None:
                gate_payload["skill_allowed_tools"] = sorted(self._skill_allowed_tools)
            result = self._dispatcher.route_from_runtime_loop(
                RuntimeActionRequest(
                    action_type=RuntimeActionType.TOOL_GATE,
                    source="ToolRuntimeMediator",
                    parent_trace_id=tool_use_id,
                    payload=gate_payload,
                ),
                core_entrypoint="core.chat",
                runtime_hook_name="handle_tool_use_response",
            )
            return result.payload.get("gate_disposition")
        except Exception:
            return None

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
