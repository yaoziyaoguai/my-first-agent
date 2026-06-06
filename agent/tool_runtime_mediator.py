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
from agent.tool_executor import AWAITING_USER, FORCE_STOP, execute_pending_tool, execute_single_tool


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
        store: Any = None,
        identity: Any = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._state = state
        self._turn_state = turn_state
        self._turn_context = turn_context
        self._messages = messages
        self._skill_allowed_tools = skill_allowed_tools
        self._store = store
        self._identity = identity
        self._rejection_counts: dict[str, int] = {}

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
        gate_result = self._route_gate(tool_name, tool_input, tool_use_id)
        gate_disposition = gate_result["gate_disposition"]

        # Step 2: 根据 gate_disposition 分流
        if gate_disposition == "rejected" or gate_disposition is None:
            # 安全失败：blocked / rejected / malformed → 不执行工具
            self._handle_blocked(tool_name, tool_input, tool_use_id, gate_result)
            self._route_result(tool_name, tool_input, tool_use_id, FORCE_STOP)
            return FORCE_STOP

        if gate_disposition == "confirmation_required":
            # 需要用户确认 → 不执行工具，设置 pending_tool
            self._handle_confirmation_required(tool_name, tool_input, tool_use_id)
            self._route_result(tool_name, tool_input, tool_use_id, AWAITING_USER)
            return AWAITING_USER

        # gate_disposition == "allowed"
        # 记录 TOOL_GATE allowed evidence（P2 fix：allowed path 之前缺 gate_decision
        # evidence，导致 tools_attempted=0 但 tools_executed>=1）
        try:
            from agent.evidence_recorder import record_evidence
            path = ""
            if isinstance(tool_input, dict):
                path = str(tool_input.get("path", ""))
            record_evidence(
                subsystem="tool",
                operation="gate_decision",
                phase="decision",
                status="allowed",
                safe_summary=f"tool={tool_name} gate=allowed",
                content_persisted=False,
                sensitive=False,
                metadata={
                    "tool_name": tool_name,
                    "tool_use_id": tool_use_id,
                    "path": path,
                },
            )
        except Exception:
            pass

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

    def mediate_pending(self, pending: dict[str, Any]) -> str:
        """执行已确认的 pending tool，走统一 mediator evidence 链。

        用户已在 pending confirmation UI 中确认（confirmation_already_approved），
        不会重新弹确认。但仍通过 ToolRuntimeMediator 统一路径记录：
        gate_decision → TOOL_INVOKE dispatch → execute_pending_tool → TOOL_RESULT dispatch。

        execute_pending_tool 作为底层 executor 负责实际的工具执行和
        display/audit/messages/checkpoint 等所有 post-execution 能力。
        """
        tool_use_id = pending["tool_use_id"]
        tool_name = pending["tool"]
        tool_input = pending["input"]

        # Step 1: gate_decision evidence（已确认，不重新 gate）
        try:
            from agent.evidence_recorder import record_evidence
            path = ""
            if isinstance(tool_input, dict):
                path = str(tool_input.get("path", ""))
            record_evidence(
                subsystem="tool",
                operation="gate_decision",
                phase="decision",
                status="allowed",
                safe_summary=f"tool={tool_name} gate=allowed (pending confirmed)",
                content_persisted=False,
                sensitive=False,
                metadata={
                    "tool_name": tool_name,
                    "tool_use_id": tool_use_id,
                    "path": path,
                    "from_pending_tool": True,
                    "confirmation_already_approved": True,
                },
            )
        except Exception:
            pass

        # Step 2: TOOL_INVOKE dispatch
        self._route_invoke(tool_name, tool_input, tool_use_id)

        # Step 3: 执行 pending tool（底层 executor 处理全部执行细节）
        result = execute_pending_tool(
            state=self._state,
            turn_state=self._turn_state,
            messages=self._messages,
            pending=pending,
        )

        # Step 4: TOOL_RESULT dispatch
        with contextlib.suppress(Exception):
            result_text = str(self._turn_context.get(tool_use_id, ""))[:500]
            self._dispatcher.route_from_runtime_loop(
                RuntimeActionRequest(
                    action_type=RuntimeActionType.TOOL_RESULT,
                    source="ToolRuntimeMediator",
                    parent_trace_id=tool_use_id,
                    payload={
                        "tool_name": tool_name,
                        "tool_input": dict(tool_input) if tool_input else {},
                        "status": "executed",
                        "tool_output": result_text,
                        "execution_status": "success",
                        "from_pending_tool": True,
                    },
                ),
                core_entrypoint="core.chat",
                runtime_hook_name="handle_tool_use_response",
                identity=self._identity,
            )

        return result

    # ── child tool mediation (Loop 3.2a) ──────────────────────────────────

    def mediate_child_tool_request(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        delegation_id: str = "",
        parent_trace_id: str = "",
    ) -> str | None:
        """Child tool_use → parent TOOL_GATE→TOOL_INVOKE→TOOL_RESULT pipeline.

        child 不直接执行工具 — 所有工具执行通过 parent ToolRuntimeMediator。
        blocked tool 在 TOOL_GATE 被拦截 → 返回 FORCE_STOP。
        Skill allowed_tools enforcement 对 child tool request 同样生效。

        Returns:
            None: 工具已执行
            FORCE_STOP: 被 gate 阻断
            AWAITING_USER: 需要用户确认
        """
        # Step 1: 构建合成 tool_use_id
        tool_use_id = f"child:{delegation_id}:{tool_name}"

        # Step 1.5: Dispatch child tool request evidence (best-effort)
        self._dispatch_child_tool_evidence(
            tool_name, arguments, delegation_id, parent_trace_id,
        )

        # Step 2: TOOL_GATE — 复用 parent gate pipeline
        gate_result = self._route_gate(tool_name, arguments, tool_use_id)
        gate_disposition = gate_result["gate_disposition"]

        if gate_disposition == "rejected" or gate_disposition is None:
            self._handle_blocked(tool_name, arguments, tool_use_id, gate_result)
            self._route_result(tool_name, arguments, tool_use_id, FORCE_STOP)
            return FORCE_STOP

        if gate_disposition == "confirmation_required":
            self._handle_confirmation_required(tool_name, arguments, tool_use_id)
            self._route_result(tool_name, arguments, tool_use_id, AWAITING_USER)
            return AWAITING_USER

        # Step 3: TOOL_INVOKE — 记录 child tool invocation
        self._route_invoke(tool_name, arguments, tool_use_id)

        # Step 4: 执行工具（通过 execute_single_tool）
        # 为 child tool request 构造合成 ToolUseBlock
        synthetic_block = _SyntheticToolUseBlock(
            id=tool_use_id,
            name=tool_name,
            input=arguments,
        )
        result = execute_single_tool(
            synthetic_block,
            state=self._state,
            turn_state=self._turn_state,
            turn_context=self._turn_context,
            messages=self._messages,
        )

        # Step 5: TOOL_RESULT
        self._route_result(tool_name, arguments, tool_use_id, result)

        return result

    # ── child memory mediation (Loop 3.2b) ──────────────────────────────────

    def mediate_child_memory_request(
        self,
        key: str,
        value: str,
        *,
        delegation_id: str = "",
        parent_trace_id: str = "",
        subagent_name: str = "",
        memory_scope: str = "none",
    ) -> str | None:
        """Child memory proposal → parent-mediated store write (Loop 3.2b).

        child 不直接写 store — 所有 memory 操作通过 parent ToolRuntimeMediator。
        memory_scope=none → 不写入；propose → 通过 store.apply_operation_intent() 写入。

        Namespace 隔离：child memory 使用 subagent:<name>: 前缀，防止与 parent
        memory 混淆。

        Returns:
            None: stored successfully
            "rejected": memory_scope disabled the write
            "error": store unavailable or write failed
        """
        # Step 1: Check memory_scope
        if memory_scope == "none":
            self._dispatch_child_memory_evidence(
                key, value, delegation_id, parent_trace_id,
                subagent_name, memory_scope, status="rejected",
            )
            return "rejected"

        if self._store is None:
            self._dispatch_child_memory_evidence(
                key, value, delegation_id, parent_trace_id,
                subagent_name, memory_scope, status="error",
            )
            return "error"

        # Step 2: Build namespaced MemoryOperationIntent
        from agent.memory_confirmation import MemoryConfirmationChoice, MemoryConfirmationStatus
        from agent.memory_contracts import MemoryDecisionType, MemoryScope
        from agent.memory_operations import (
            MemoryOperationIntent,
            MemoryOperationType,
            build_memory_audit_summary,
        )

        source = f"subagent:{subagent_name}:{delegation_id}"
        intent = MemoryOperationIntent(
            operation_type=MemoryOperationType.RETAIN,
            decision_type=MemoryDecisionType.RETAIN,
            confirmation_status=MemoryConfirmationStatus.AUTO_RETAINED,
            user_choice=MemoryConfirmationChoice.ACCEPT,
            content_summary=value,
            source_summary=source,
            scope=MemoryScope.USER,
            safety_summary="child subagent memory proposal, parent-mediated",
            sensitive_redacted=False,
            user_visible_summary=f"SubAgent {subagent_name} 记忆: {value[:80]}",
            memory_type="semantic",
            source_type="agent_suggested",
        )
        audit = build_memory_audit_summary(intent)

        # Step 3: Write to store via parent memory path
        try:
            self._store.apply_operation_intent(intent, audit)
        except Exception:
            self._dispatch_child_memory_evidence(
                key, value, delegation_id, parent_trace_id,
                subagent_name, memory_scope, status="error",
            )
            return "error"

        # Step 4: Dispatch evidence after successful write
        self._dispatch_child_memory_evidence(
            key, value, delegation_id, parent_trace_id,
            subagent_name, memory_scope, status="retained",
        )
        return None

    def _dispatch_child_tool_evidence(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        delegation_id: str,
        parent_trace_id: str,
        *,
        gate_disposition: str | None = None,
    ) -> None:
        """Dispatch SUBAGENT_CHILD_TOOL_REQUEST evidence (best-effort)."""
        with contextlib.suppress(Exception):
            self._dispatcher.route_from_runtime_loop(
                RuntimeActionRequest(
                    action_type=RuntimeActionType.SUBAGENT_CHILD_TOOL_REQUEST,
                    source="ToolRuntimeMediator",
                    parent_trace_id=parent_trace_id or delegation_id,
                    payload={
                        "tool_name": tool_name,
                        "arguments_preview": str(arguments)[:200],
                        "delegation_id": delegation_id,
                        "gate_disposition": gate_disposition,
                    },
                ),
                core_entrypoint="core.chat",
                runtime_hook_name="execute_l1",
                identity=self._identity,
            )

    def _dispatch_child_result_evidence(
        self,
        *,
        delegation_id: str,
        parent_trace_id: str,
        subagent_name: str,
        status: str,
        stop_reason: str,
        summary: str,
        iterations_used: int,
    ) -> None:
        """Dispatch SUBAGENT_CHILD_RESULT evidence (best-effort)."""
        with contextlib.suppress(Exception):
            self._dispatcher.route_from_runtime_loop(
                RuntimeActionRequest(
                    action_type=RuntimeActionType.SUBAGENT_CHILD_RESULT,
                    source="ToolRuntimeMediator",
                    parent_trace_id=parent_trace_id or delegation_id,
                    payload={
                        "subagent_name": subagent_name,
                        "delegation_id": delegation_id,
                        "status": status,
                        "stop_reason": stop_reason,
                        "summary_preview": summary[:200],
                        "iterations_used": iterations_used,
                    },
                ),
                core_entrypoint="core.chat",
                runtime_hook_name="execute_l1",
                identity=self._identity,
            )

    def _dispatch_child_memory_evidence(
        self,
        key: str,
        value: str,
        delegation_id: str,
        parent_trace_id: str,
        subagent_name: str,
        memory_scope: str,
        *,
        status: str,
    ) -> None:
        """Dispatch SUBAGENT_CHILD_MEMORY_REQUEST evidence (best-effort)."""
        with contextlib.suppress(Exception):
            self._dispatcher.route_from_runtime_loop(
                RuntimeActionRequest(
                    action_type=RuntimeActionType.SUBAGENT_CHILD_MEMORY_REQUEST,
                    source="ToolRuntimeMediator",
                    parent_trace_id=parent_trace_id or delegation_id,
                    payload={
                        "key": key,
                        "value_preview": value[:200],
                        "subagent_name": subagent_name,
                        "delegation_id": delegation_id,
                        "memory_scope": memory_scope,
                        "status": status,
                    },
                ),
                core_entrypoint="core.chat",
                runtime_hook_name="execute_l1",
                identity=self._identity,
            )

    # ── gate disposition handlers ─────────────────────────────────────────

    def _handle_blocked(
        self,
        tool_name: str,
        tool_input: Any,
        tool_use_id: str,
        gate_result: dict[str, Any],
    ) -> None:
        """处理 blocked/rejected/malformed gate result：不执行工具。

        F-005: 从 gate_result 中提取 rejection_reason 和 evidence_extra，
        构造有意义的拒绝反馈，帮助模型理解拒绝原因并尝试替代方案。
        """
        gate_disposition = gate_result.get("gate_disposition")
        rejection_reason = gate_result.get("rejection_reason")
        evidence_extra = gate_result.get("evidence_extra") or {}

        # 构建拒绝消息的核心部分
        if rejection_reason:
            reason_text = f"工具被安全策略拒绝：{rejection_reason}"
        elif gate_disposition == "rejected":
            reason_text = "工具被安全策略拒绝"
        else:
            reason_text = "工具门控结果异常，工具执行被安全策略阻止"

        # Evidence recorder: 记录 TOOL_GATE 拒绝 evidence
        try:
            from agent.evidence_recorder import record_evidence
            path = ""
            if isinstance(tool_input, dict):
                path = str(tool_input.get("path", ""))
            record_evidence(
                subsystem="tool",
                operation="gate_decision",
                phase="decision",
                status="blocked",
                reason_code=rejection_reason or "gate_rejected",
                safe_summary=f"tool={tool_name} blocked by gate: {reason_text[:80]}",
                content_persisted=False,
                content_redacted=True,
                sensitive=False,
                metadata={
                    "tool_name": tool_name,
                    "tool_use_id": tool_use_id,
                    "path": path,
                    "gate_disposition": gate_disposition,
                    "rejection_reason": rejection_reason,
                },
            )
        except Exception:
            pass

        # P2-001: 追踪连续重复拒绝，递增反馈强度
        self._rejection_counts[tool_name] = self._rejection_counts.get(tool_name, 0) + 1
        consecutive_count = self._rejection_counts[tool_name]

        # 构建消息部件
        parts: list[str] = [f"[安全策略] {reason_text}：{tool_name}"]

        # P2-001: 根据连续拒绝次数升级反馈强度
        if consecutive_count >= 3:
            parts.append(
                f"⚠️ 此操作已被连续拒绝 {consecutive_count} 次。"
                f"请停止尝试 {tool_name}，改用其他方法完成目标，"
                f"或向用户说明此操作不被允许并建议替代方案。"
            )
        elif consecutive_count >= 2:
            parts.append(
                f"此操作已被重复拒绝。请不要再尝试 {tool_name}，"
                f"换用其他方法或向用户说明限制。"
            )

        # 当拒绝与 skill 工具约束相关时，提供可用替代工具建议
        skill_tools: list[str] | None = evidence_extra.get("skill_allowed_tools")
        if skill_tools:
            tools_str = "、".join(skill_tools[:8])
            parts.append(
                f"当前 skill 允许使用的工具有：{tools_str}。"
                f"请使用这些工具完成目标，或向用户说明当前 skill 不支持 {tool_name}。"
            )
        else:
            parts.append("请尝试其他方法完成目标，或向用户说明此操作不被允许。")

        result_text = "\n".join(parts)
        append_tool_result(self._messages, tool_use_id, result_text)
        self._state.task.tool_execution_log[tool_use_id] = {
            "tool": tool_name,
            "input": dict(tool_input) if tool_input else {},
            "result": result_text,
            "status": "blocked_by_policy",
            "rejection_reason": rejection_reason,
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
    ) -> dict[str, Any]:
        """TOOL_GATE：dispatcher 门控 evidence（execute_single_tool 之前调用）。

        Loop 2.2b: skill_allowed_tools 传入 payload，由 ToolGateHandler 执行
        skill 工具约束检查，非允许工具返回 rejected。

        F-005: 返回完整 gate result（含 rejection_reason / evidence_extra），
        使 _handle_blocked 能构造有意义的拒绝反馈，而非仅写"被安全策略拒绝"。

        Returns:
            dict with keys:
            - gate_disposition: "allowed" / "rejected" / "confirmation_required" / None
            - rejection_reason: str | None
            - evidence_extra: dict | None
        """
        try:
            # USER_RECHECK-P1-001: 部分 provider（如 kimi-k2.5）会剥离工具名的
            # namespace 前缀（demo.echo_task_summary → echo_task_summary），
            # 导致 TOOL_GATE 的 skill_allowed_tools 检查用短名匹配 namespaced 全名
            # 时失败。这里调用 _normalize_tool_name 将短名归一化为注册表全名，
            # 使 skill allowed_tools enforcement 与 execute_tool 走同一归一化路径。
            from agent.tool_registry import _normalize_tool_name
            _normalized = _normalize_tool_name(tool_name)
            _effective_name = _normalized if _normalized is not None else tool_name
            gate_payload: dict[str, Any] = {
                "tool_name": _effective_name,
                "tool_input": dict(tool_input) if tool_input else {},
            }
            # Loop 5 (D05 mediator timing fix): 不依赖 mediator 创建时缓存的
            # _skill_allowed_tools（它在 SKILL_SELECT 之前创建，值为 None），
            # 而是在 gate 时刻动态从 lifecycle 读取当前活跃 skill 的 allowed_tools。
            # 这样同一 turn 内 SKILL_SELECT 先激活 skill 后，后续 tool_use block
            # 的 gate 检查能正确拿到 skill 的工具白名单。
            _live_at = self._skill_allowed_tools
            _active_skill_id: str | None = None
            _session_id = (
                self._identity.session_id if self._identity else "default"
            )
            if _live_at is None:
                try:
                    from agent.skill_system.lifecycle import get_default_lifecycle
                    _lc = get_default_lifecycle(session_id=_session_id)
                    _tools = _lc.get_allowed_tools()
                    _live_at = _tools if _tools else None
                    _active_skill_id = _lc.get_active_skill_id()
                except ImportError:
                    pass
            else:
                try:
                    from agent.skill_system.lifecycle import get_default_lifecycle
                    _lifecycle = get_default_lifecycle(session_id=_session_id)
                    _active_skill_id = _lifecycle.get_active_skill_id()
                except ImportError:
                    pass
            if _live_at is not None:
                gate_payload["skill_allowed_tools"] = sorted(_live_at)
            if _active_skill_id is not None:
                gate_payload["active_skill_id"] = _active_skill_id
            result = self._dispatcher.route_from_runtime_loop(
                RuntimeActionRequest(
                    action_type=RuntimeActionType.TOOL_GATE,
                    source="ToolRuntimeMediator",
                    parent_trace_id=tool_use_id,
                    payload=gate_payload,
                ),
                core_entrypoint="core.chat",
                runtime_hook_name="handle_tool_use_response",
                identity=self._identity,
            )
            return {
                "gate_disposition": result.payload.get("gate_disposition"),
                "rejection_reason": result.payload.get("rejection_reason"),
                "evidence_extra": getattr(result, "evidence_extra", None),
            }
        except Exception:
            return {
                "gate_disposition": None,
                "rejection_reason": None,
                "evidence_extra": None,
            }

    def _route_invoke(
        self, tool_name: str, tool_input: Any, tool_use_id: str
    ) -> None:
        """TOOL_INVOKE evidence 记录（不通过 dispatcher 执行工具）。

        P1-2 冲突复核关键修复：原来的 _route_invoke 通过 dispatcher 路由
        TOOL_INVOKE → ToolInvokeHandler.handle() → invoke_registered_target
        → _tool_invoke_adapter() → execute_tool()，导致工具被 dispatcher
        执行一次，随后 mediate()/mediate_pending() 又调用 execute_single_tool/
        execute_pending_tool 执行第二次。现在改用 record_evidence 直接记录
        evidence，不触发 dispatcher handler 的工具执行路径。
        """
        with contextlib.suppress(Exception):
            from agent.evidence_recorder import record_evidence
            record_evidence(
                subsystem="tool",
                operation="invoke_started",
                phase="execution",
                status="ok",
                safe_summary=f"tool={tool_name} invoke_started",
                content_persisted=False,
                sensitive=False,
                metadata={
                    "tool_name": tool_name,
                    "tool_use_id": tool_use_id,
                },
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

        # Evidence recorder: 记录工具结果 evidence
        try:
            from agent.evidence_recorder import record_evidence
            evidence_status = {
                "executed": "ok",
                "blocked_by_policy": "blocked",
                "awaiting_confirmation": "pending",
                "unknown": "error",
            }.get(status, "error")
            path = ""
            if isinstance(tool_input, dict):
                path = str(tool_input.get("path", ""))
            record_evidence(
                subsystem="tool",
                operation="invoke_result_summary",
                phase="end",
                status=evidence_status,
                safe_summary=f"tool={tool_name} result={status}",
                metadata={
                    "tool_name": tool_name,
                    "tool_use_id": tool_use_id,
                    "path": path,
                    "execution_status": status,
                },
            )
        except Exception:
            pass

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
                        "tool_output": result_text,
                        "execution_status": (
                            "success" if result is None
                            else "blocked" if result == FORCE_STOP
                            else "pending"
                        ),
                    },
                ),
                core_entrypoint="core.chat",
                runtime_hook_name="handle_tool_use_response",
                identity=self._identity,
            )


class _SyntheticToolUseBlock:
    """为 child tool request 构造的合成 ToolUseBlock。

    execute_single_tool 需要 .id / .name / .input / .type 属性，
    这个类提供最小实现，使 child tool request 能走 parent 现有 pipeline。
    """

    __slots__ = ("id", "name", "input")

    def __init__(self, *, id: str, name: str, input: dict[str, Any]) -> None:
        self.id = id
        self.name = name
        self.input = input

    @property
    def type(self) -> str:
        return "tool_use"
