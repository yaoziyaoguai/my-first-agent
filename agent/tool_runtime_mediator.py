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
import hashlib
from typing import Any

from agent.conversation_events import append_tool_result
from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType
from agent.tool_executor import (
    AWAITING_USER,
    FORCE_STOP,
    TRANSITION_DENIED,
    execute_pending_tool,
    execute_single_tool,
)
from agent.transitions import (
    CheckpointAction,
    TaskTransitionRequest,
    TaskTransitionResult,
    TransitionEvent,
    apply_task_transition,
    validate_task_transition,
)

_MEMORY_MODEL_VISIBLE_TOOLS = frozenset({
    "MEMORY_REMEMBER_REQUEST",
    "MEMORY_LIST",
    "MEMORY_FORGET_REQUEST",
})


def _tool_input_path_metadata(tool_input: Any) -> dict[str, Any]:
    if not isinstance(tool_input, dict) or "path" not in tool_input:
        return {}
    from agent.evidence_recorder import build_safe_path_metadata

    return build_safe_path_metadata(tool_input.get("path", ""))


def _hash_memory_tool_value(value: Any, *, prefix: str) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _memory_tool_input_metadata(tool_name: str, tool_input: Any) -> dict[str, Any]:
    """把 model-visible memory tool input 收口成 evidence-safe 摘要。"""

    if tool_name not in _MEMORY_MODEL_VISIBLE_TOOLS:
        return {}
    payload = dict(tool_input or {}) if isinstance(tool_input, dict) else {}
    operation = _memory_tool_operation(tool_name)
    metadata: dict[str, Any] = {
        "memory_tool_input_redacted": True,
        "operation": operation,
        "redacted": True,
        "source_type": "model_visible_tool",
        "policy_path": "memory_tool_input_redaction",
    }
    if tool_name == "MEMORY_REMEMBER_REQUEST":
        content = str(payload.get("content") or "")
        metadata["content_length"] = len(content)
        metadata["content_hash"] = _hash_memory_tool_value(
            content, prefix="mempayload"
        )
        return metadata
    if tool_name == "MEMORY_FORGET_REQUEST":
        record_id = str(payload.get("record_id") or payload.get("memory_id") or "")
        metadata["memory_id_hash"] = _hash_memory_tool_value(record_id, prefix="memid")
        metadata["record_id_hash"] = metadata["memory_id_hash"]
        metadata["count"] = 1 if record_id else 0
        return metadata
    query = str(payload.get("query") or "")
    metadata["query_length"] = len(query)
    metadata["query_hash"] = _hash_memory_tool_value(query, prefix="memquery")
    metadata["count"] = 1 if query else 0
    return metadata


def _safe_tool_input_metadata(tool_name: str, tool_input: Any) -> dict[str, Any]:
    metadata = {
        **_memory_tool_input_metadata(tool_name, tool_input),
        **_tool_input_path_metadata(tool_input),
    }
    return {key: value for key, value in metadata.items() if value not in ("", None)}


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
        memory_runtime: Any = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._state = state
        self._turn_state = turn_state
        self._turn_context = turn_context
        self._messages = messages
        self._skill_allowed_tools = skill_allowed_tools
        self._store = store
        self._identity = identity
        self._memory_runtime = memory_runtime
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
            transition = self._handle_confirmation_required(
                tool_name,
                tool_input,
                tool_use_id,
            )
            if not transition.allowed:
                return TRANSITION_DENIED
            self._route_result(tool_name, tool_input, tool_use_id, AWAITING_USER)
            assert transition.checkpoint_action is CheckpointAction.SAVE
            from agent.runtime_integration.checkpoint_save import save_runtime_checkpoint

            save_runtime_checkpoint(self._state)
            return AWAITING_USER

        # gate_disposition == "allowed"
        # 记录 TOOL_GATE allowed evidence（P2 fix：allowed path 之前缺 gate_decision
        # evidence，导致 tools_attempted=0 但 tools_executed>=1）
        try:
            from agent.evidence_recorder import record_evidence
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
                    **_tool_input_path_metadata(tool_input),
                },
            )
        except Exception:
            pass

        # Step 3: TOOL_INVOKE — dispatcher 记录工具调用
        self._route_invoke(tool_name, tool_input, tool_use_id)

        if tool_name in _MEMORY_MODEL_VISIBLE_TOOLS:
            result = self._mediate_memory_tool_request(
                tool_name, tool_input, tool_use_id
            )
            self._route_result(tool_name, tool_input, tool_use_id, result)
            return result

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

    def _mediate_memory_tool_request(
        self,
        tool_name: str,
        tool_input: Any,
        tool_use_id: str,
    ) -> str | None:
        """处理 Memory v0 request-only model-visible tools。

        工具调用已经经过 TOOL_GATE / TOOL_INVOKE evidence；这里仅创建用户确认
        或读取用户可见 records，不直接 commit/delete/update MemoryStore。
        """
        from agent.conversation_events import append_tool_result

        if tool_name == "MEMORY_LIST":
            records = ()
            if self._memory_runtime is not None:
                records = self._memory_runtime.list_records()
            lines = ["Memory records:"]
            if not records:
                lines.append("- none")
            else:
                for record in records:
                    record_id = str(getattr(record, "id", ""))
                    content = str(getattr(record, "content", ""))
                    lines.append(f"- {record_id[:8]}: {content}")
            result_text = "\n".join(lines)
            append_tool_result(self._messages, tool_use_id, result_text)
            self._turn_context[tool_use_id] = result_text
            self._set_safe_tool_result_context(
                tool_use_id,
                operation="list",
                count=len(records),
                record_ids=[str(getattr(record, "id", "")) for record in records],
            )
            return None

        if self._memory_runtime is None:
            result_text = "Memory request deferred: memory runtime unavailable."
            append_tool_result(self._messages, tool_use_id, result_text)
            self._turn_context[tool_use_id] = result_text
            self._set_safe_tool_result_context(
                tool_use_id,
                operation=_memory_tool_operation(tool_name),
                count=0,
                reason="memory_runtime_unavailable",
            )
            return FORCE_STOP

        if tool_name == "MEMORY_REMEMBER_REQUEST":
            content = str(dict(tool_input or {}).get("content") or "")
            from agent.memory_runtime import MemoryEvaluationAction

            result = self._memory_runtime.evaluate_user_text(
                f"remember that {content}",
                on_event=None,
            )
            if result.action is not MemoryEvaluationAction.CONFIRMATION_REQUIRED:
                result_text = "Memory remember request did not create a pending confirmation."
                append_tool_result(self._messages, tool_use_id, result_text)
                self._turn_context[tool_use_id] = result_text
                self._set_safe_tool_result_context(
                    tool_use_id,
                    operation="remember_request",
                    count=0,
                    reason="no_pending_confirmation",
                )
                return FORCE_STOP
            transition = self._set_memory_confirmation_pending(
                result.candidate_id,
                owner="tool_runtime_mediator.memory_remember_request",
            )
            if not transition.allowed:
                result_text = "Memory remember request could not enter confirmation state."
                append_tool_result(self._messages, tool_use_id, result_text)
                self._turn_context[tool_use_id] = result_text
                self._set_safe_tool_result_context(
                    tool_use_id,
                    operation="remember_request",
                    count=0,
                    reason="confirmation_transition_denied",
                )
                return TRANSITION_DENIED
            result_text = "Memory remember request is waiting for user confirmation."
            append_tool_result(self._messages, tool_use_id, result_text)
            self._turn_context[tool_use_id] = result_text
            self._set_safe_tool_result_context(
                tool_use_id,
                operation="remember_request",
                count=0,
                reason="awaiting_user_confirmation",
            )
            return AWAITING_USER

        if tool_name == "MEMORY_FORGET_REQUEST":
            record_id = str(dict(tool_input or {}).get("record_id") or "")
            transition = self._set_memory_forget_pending(record_id)
            if not transition.allowed:
                result_text = "Memory forget request could not enter confirmation state."
                append_tool_result(self._messages, tool_use_id, result_text)
                self._turn_context[tool_use_id] = result_text
                self._set_safe_tool_result_context(
                    tool_use_id,
                    operation="forget_request",
                    count=1 if record_id else 0,
                    record_ids=[record_id],
                    reason="confirmation_transition_denied",
                )
                return TRANSITION_DENIED
            result_text = "Memory forget request is waiting for user confirmation."
            append_tool_result(self._messages, tool_use_id, result_text)
            self._turn_context[tool_use_id] = result_text
            self._set_safe_tool_result_context(
                tool_use_id,
                operation="forget_request",
                count=1 if record_id else 0,
                record_ids=[record_id],
                reason="awaiting_user_confirmation",
            )
            return AWAITING_USER

        return FORCE_STOP

    def _set_safe_tool_result_context(
        self,
        tool_use_id: str,
        *,
        operation: str,
        count: int,
        record_ids: list[str] | tuple[str, ...] = (),
        reason: str = "",
    ) -> None:
        from agent.evidence_recorder import hash_memory_identifier

        record_id_hashes = tuple(
            hash_memory_identifier(record_id)
            for record_id in record_ids
            if str(record_id or "")
        )
        safe_output = (
            "Memory tool result redacted: "
            f"operation={operation} count={int(count)}"
        )
        if reason:
            safe_output += f" reason={reason}"
        metadata = {
            "memory_tool_result_redacted": True,
            "operation": operation,
            "count": int(count),
            "record_id_hashes": record_id_hashes,
            "memory_id_hashes": record_id_hashes,
            "redacted": True,
            "source_type": "model_visible_tool",
            "policy_path": "memory_tool_result_redaction",
        }
        if reason:
            metadata["reason"] = reason
        self._turn_context[f"_safe_tool_result:{tool_use_id}"] = {
            "tool_output": safe_output,
            "metadata": metadata,
        }

    def _set_memory_confirmation_pending(
        self,
        candidate_id: str | None,
        *,
        owner: str,
    ) -> TaskTransitionResult:
        confirmation_request = self._memory_runtime.get_pending_confirmation(candidate_id)
        if confirmation_request is None:
            return self._denied_task_transition(
                reason="missing memory confirmation",
                event=TransitionEvent.MEMORY_CONFIRMATION_REQUIRED,
                owner=owner,
            )
        from agent.memory_interaction import build_memory_pending_request

        origin_status = self._state.task.status
        pending = build_memory_pending_request(
            confirmation_request,
            candidate_id=candidate_id,
            origin_status=origin_status,
        )
        request = TaskTransitionRequest(
            event=TransitionEvent.MEMORY_CONFIRMATION_REQUIRED,
            owner=owner,
            expected_from_status=origin_status,
        )
        preflight = validate_task_transition(self._state, request)
        if not preflight.allowed:
            return preflight
        transition = apply_task_transition(self._state, request, preflight=preflight)
        if transition.allowed:
            self._state.task.pending_user_input_request = pending
            with contextlib.suppress(Exception):
                from agent.display_events import memory_confirmation_requested_event
                emit = getattr(self._turn_state, "on_runtime_event", None)
                if emit is not None:
                    emit(memory_confirmation_requested_event(pending))
            with contextlib.suppress(Exception):
                from agent.runtime_integration.checkpoint_save import save_runtime_checkpoint
                save_runtime_checkpoint(
                    self._state,
                    source="tool_runtime_mediator.memory_remember_request",
                )
        return transition

    def _set_memory_forget_pending(self, record_id: str) -> TaskTransitionResult:
        origin_status = self._state.task.status
        pending = {
            "awaiting_kind": "memory_forget_confirmation",
            "question": "确认删除这条记忆？",
            "why_needed": "模型只能请求删除，最终删除必须由用户确认。",
            "options": ["1. 删除", "2. 取消"],
            "context": "",
            "tool_use_id": "",
            "step_index": None,
            "_record_id": record_id,
            "_origin_status": origin_status,
        }
        request = TaskTransitionRequest(
            event=TransitionEvent.MEMORY_CONFIRMATION_REQUIRED,
            owner="tool_runtime_mediator.memory_forget_request",
            expected_from_status=origin_status,
        )
        preflight = validate_task_transition(self._state, request)
        if not preflight.allowed:
            return preflight
        transition = apply_task_transition(self._state, request, preflight=preflight)
        if transition.allowed:
            self._state.task.pending_user_input_request = pending
            with contextlib.suppress(Exception):
                from agent.runtime_integration.checkpoint_save import save_runtime_checkpoint
                save_runtime_checkpoint(
                    self._state,
                    source="tool_runtime_mediator.memory_forget_request",
                )
        return transition

    def _denied_task_transition(
        self,
        *,
        reason: str,
        event: TransitionEvent,
        owner: str,
    ) -> TaskTransitionResult:
        return TaskTransitionResult(
            allowed=False,
            reason=reason,
            previous_status=getattr(self._state.task, "status", ""),
            next_status=None,
            event=event,
            owner=owner,
            checkpoint_action=CheckpointAction.NONE,
        )

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
                    **_tool_input_path_metadata(tool_input),
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
            safe_input_metadata = _safe_tool_input_metadata(tool_name, tool_input)
            self._dispatcher.route_from_runtime_loop(
                RuntimeActionRequest(
                    action_type=RuntimeActionType.TOOL_RESULT,
                    source="ToolRuntimeMediator",
                    parent_trace_id=tool_use_id,
                    payload={
                        "tool_name": tool_name,
                        "safe_tool_input": safe_input_metadata,
                        "status": "executed",
                        "tool_output": result_text,
                        "execution_status": "success",
                        **safe_input_metadata,
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
        """Child memory request → v0 rejected/deferred evidence-only lockdown.

        Memory v0 不允许 child/sub-agent 直接写长期 MemoryStore。历史路径曾在
        non-none scope 下构造 MemoryOperationIntent 并 AUTO_RETAINED+ACCEPT 写入；
        v0 将该能力锁为 evidence-only，未来如需 proposal-only 必须单独走
        parent/user confirmation 设计。

        Returns:
            "rejected": memory_scope=none disabled the request
            "deferred": non-none scope is deferred to a future governed phase
        """
        # Step 1: Always record the received request with safe hashes only.
        self._record_child_memory_lifecycle_evidence(
            event_type="memory.child_request_received",
            key=key,
            value=value,
            memory_scope=memory_scope,
            decision="received",
            reason="child_memory_request_received",
        )

        # Step 2: Reject/defer without touching MemoryStore.
        if memory_scope == "none":
            self._dispatch_child_memory_evidence(
                key, value, delegation_id, parent_trace_id,
                subagent_name, memory_scope, status="rejected",
            )
            self._record_child_memory_lifecycle_evidence(
                event_type="memory.child_request_rejected",
                key=key,
                value=value,
                memory_scope=memory_scope,
                decision="blocked",
                reason="child_memory_scope_none",
            )
            return "rejected"

        self._dispatch_child_memory_evidence(
            key, value, delegation_id, parent_trace_id,
            subagent_name, memory_scope, status="deferred",
        )
        self._record_child_memory_lifecycle_evidence(
            event_type="memory.child_request_deferred",
            key=key,
            value=value,
            memory_scope=memory_scope,
            decision="deferred",
            reason="child_memory_direct_write_disabled",
        )
        return "deferred"

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
        """Dispatch SUBAGENT_CHILD_MEMORY_REQUEST evidence with safe fields only."""
        with contextlib.suppress(Exception):
            from agent.evidence_recorder import build_memory_evidence_metadata

            metadata = build_memory_evidence_metadata(
                event_type="memory.child_request_received",
                source_type="child_agent",
                operation="propose",
                policy_path="child_memory_v0_lockdown",
                decision=status,
                reason=(
                    "child_memory_scope_none"
                    if status == "rejected"
                    else "child_memory_direct_write_disabled"
                ),
                count=1,
                redacted=True,
                child_payload=value,
                child_key=key,
                raw_fields={"key": key, "value_preview": value},
            )
            self._dispatcher.route_from_runtime_loop(
                RuntimeActionRequest(
                    action_type=RuntimeActionType.SUBAGENT_CHILD_MEMORY_REQUEST,
                    source="ToolRuntimeMediator",
                    parent_trace_id=parent_trace_id or delegation_id,
                    payload={
                        "delegation_id": delegation_id,
                        "status": status,
                        "child_payload_hash": metadata.get("child_payload_hash", ""),
                        "key_hash": metadata.get("key_hash", ""),
                        "redacted": True,
                        "count": 1,
                        "source_type": "child_agent",
                        "policy_path": "child_memory_v0_lockdown",
                        "decision": status,
                        "reason": metadata.get("reason", ""),
                    },
                ),
                core_entrypoint="core.chat",
                runtime_hook_name="execute_l1",
                identity=self._identity,
            )

    def _record_child_memory_lifecycle_evidence(
        self,
        *,
        event_type: str,
        key: str,
        value: str,
        memory_scope: str,
        decision: str,
        reason: str,
    ) -> None:
        """Record Memory v0 child request lifecycle evidence through built-in recorder."""
        with contextlib.suppress(Exception):
            from agent.evidence_recorder import record_memory_evidence

            record_memory_evidence(
                event_type=event_type,
                operation="propose",
                phase="decision" if event_type != "memory.child_request_received" else "start",
                status="blocked" if decision in {"blocked", "deferred"} else "success",
                source_type="child_agent",
                decision=decision,
                policy_path="child_memory_v0_lockdown",
                reason=reason,
                count=1,
                child_payload=value,
                child_key=key,
                raw_fields={
                    "key": key,
                    "value_preview": value,
                    "memory_scope": memory_scope,
                },
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
                    **_tool_input_path_metadata(tool_input),
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
    ) -> TaskTransitionResult:
        """先迁移状态，再提交 pending_tool；checkpoint 由 mediate() 持有。"""
        pending_tool = {
            "tool_use_id": tool_use_id,
            "tool": tool_name,
            "input": dict(tool_input) if tool_input else {},
        }
        request = TaskTransitionRequest(
            event=TransitionEvent.TOOL_CONFIRMATION_REQUIRED,
            owner="tool_runtime_mediator.handle_confirmation_required",
            expected_from_status=(
                "idle" if self._state.task.status == "idle" else "running"
            ),
        )
        preflight = validate_task_transition(self._state, request)
        if not preflight.allowed:
            return preflight
        transition = apply_task_transition(
            self._state,
            request,
            preflight=preflight,
        )
        if transition.allowed:
            self._state.task.pending_tool = pending_tool
        return transition

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
                "tool_args": dict(tool_input) if tool_input else {},
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
        safe_context = self._turn_context.get(f"_safe_tool_result:{tool_use_id}")
        safe_tool_metadata: dict[str, Any] = {}
        if isinstance(safe_context, dict):
            result_text = str(safe_context.get("tool_output") or "")[:500]
            metadata = safe_context.get("metadata") or {}
            if isinstance(metadata, dict):
                safe_tool_metadata = dict(metadata)
        else:
            result_text = str(self._turn_context.get(tool_use_id, ""))[:500]
        if result is None:
            status = "executed"
        elif result == FORCE_STOP:
            status = "blocked_by_policy"
        elif result == AWAITING_USER:
            status = "awaiting_confirmation"
        else:
            status = "unknown"
        path_metadata = _tool_input_path_metadata(tool_input)
        safe_input_metadata = _safe_tool_input_metadata(tool_name, tool_input)

        # Evidence recorder: 记录工具结果 evidence
        try:
            from agent.evidence_recorder import record_evidence
            evidence_status = {
                "executed": "ok",
                "blocked_by_policy": "blocked",
                "awaiting_confirmation": "pending",
                "unknown": "error",
            }.get(status, "error")
            record_evidence(
                subsystem="tool",
                operation="invoke_result_summary",
                phase="end",
                status=evidence_status,
                safe_summary=f"tool={tool_name} result={status}",
                metadata={
                    "tool_name": tool_name,
                    "tool_use_id": tool_use_id,
                    **path_metadata,
                    **safe_input_metadata,
                    **safe_tool_metadata,
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
                        "safe_tool_input": safe_input_metadata,
                        "status": status,
                        "tool_output": result_text,
                        **safe_input_metadata,
                        **safe_tool_metadata,
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


def _memory_tool_operation(tool_name: str) -> str:
    if tool_name == "MEMORY_LIST":
        return "list"
    if tool_name == "MEMORY_FORGET_REQUEST":
        return "forget_request"
    if tool_name == "MEMORY_REMEMBER_REQUEST":
        return "remember_request"
    return "memory_request"


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
