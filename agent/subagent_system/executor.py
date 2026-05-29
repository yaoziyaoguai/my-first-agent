"""L0/L1 bounded local SubAgent executor."""

from __future__ import annotations

import time
from typing import Any

from agent.subagent_system.result import SubAgentAuditRecord, SubAgentResult
from agent.subagent_system.trace import make_trace_event


def execute_local(
    context_package: object, *, delegation_id: str = "delegation-local",
) -> SubAgentResult:
    """Execute deterministic L0 delegation.

    该 executor 不调用 provider、不执行工具、不 spawn 外部进程。它只把 packaged
    context 转换成结构化 SubAgentResult，供 Parent adjudication。
    """

    started = time.monotonic()
    task = getattr(context_package, "task", "")
    max_iterations = int(getattr(context_package, "max_iterations", 1))
    parent_trace_id = getattr(getattr(context_package, "request", None), "parent_trace_id", "")
    subagent_name = getattr(getattr(context_package, "descriptor", None), "name", "unknown")
    execution_mode = getattr(context_package, "execution_mode", "local_fake")

    status, stop_reason, summary, confidence, warnings, clarification = _deterministic_outcome(
        task,
        max_iterations,
    )
    iterations_used = max_iterations if stop_reason == "max_iterations_exceeded" else 1
    trace_events = (
        make_trace_event(
            "result_returned",
            delegation_id=delegation_id,
            parent_trace_id=parent_trace_id,
            data={"status": status, "stop_reason": stop_reason},
        ),
    )
    audit = SubAgentAuditRecord(
        subagent_name=subagent_name,
        delegation_id=delegation_id,
        parent_trace_id=parent_trace_id,
        execution_mode=execution_mode,
        status=status,
        stop_reason=stop_reason,
        iterations_used=iterations_used,
        max_iterations=max_iterations,
        tools_requested=("read_file",) if status == "ok" else (),
        tools_denied=(),
        tools_executed=(),
        memory_proposals_count=0,
        warnings=warnings,
        confidence=confidence,
        elapsed_ms=max(1, int((time.monotonic() - started) * 1000)),
        revision_count=0,
        trace_event_count=len(trace_events),
    )
    return SubAgentResult(
        status=status,
        summary=summary,
        artifacts=(),
        tool_requests=(),
        memory_proposals=(),
        confidence=confidence,
        warnings=warnings,
        audit=audit,
        handoff_back="Parent must adjudicate this L0 result.",
        clarification_question=clarification,
        trace_events=trace_events,
        stop_reason=stop_reason,
    )


def _deterministic_outcome(
    task: str,
    max_iterations: int,
) -> tuple[str, str, str, float, tuple[str, ...], str | None]:
    lowered = task.lower()
    if "loop until max" in lowered:
        return (
            "max_iterations_exceeded",
            "max_iterations_exceeded",
            "Reached max_iterations and returned a best-effort deterministic summary.",
            0.5,
            ("max_iterations reached",),
            None,
        )
    if "needs clarification" in lowered:
        return (
            "needs_clarification",
            "needs_clarification",
            "Task needs clarification before deterministic review can continue.",
            0.3,
            ("task underspecified",),
            "Please clarify the SubAgent task.",
        )
    if "shell" in lowered or "external process" in lowered:
        return (
            "policy_blocked",
            "policy_blocked",
            "Blocked by L0 policy: no shell or external process execution.",
            0.9,
            ("shell/external process is forbidden in L0",),
            None,
        )
    if (
        "nested delegation" in lowered
        or "spawn another subagent" in lowered
        or "delegate to another subagent" in lowered
    ):
        return (
            "policy_blocked",
            "policy_blocked",
            "Blocked by L0 policy: nested SubAgent delegation is disabled.",
            0.9,
            ("nested delegation is forbidden in L0",),
            None,
        )
    return (
        "ok",
        "task_completed",
        f"deterministic L0 summary after 1/{max_iterations} iterations.",
        0.8,
        (),
        None,
    )


def execute_l1(
    context_package: object,
    *,
    delegation_id: str = "delegation-l1",
    provider: Any = None,
    tool_mediator: Any = None,
) -> SubAgentResult:
    """Execute L1 parent-mediated child loop with real provider.

    L1 特征：
    - child 调用真实 provider（继承 parent provider config）
    - child 不直接执行工具 — 所有工具执行通过 parent tool_mediator
    - child 可以做多轮迭代（受 max_iterations 限制）
    - 所有 child action 有 dispatcher evidence

    Args:
        context_package: packaged context from build_context_package()
        delegation_id: unique delegation trace id
        provider: parent provider instance (child inherits this)
        tool_mediator: parent ToolRuntimeMediator for child tool requests
    """
    started = time.monotonic()
    task = getattr(context_package, "task", "")
    max_iterations = int(getattr(context_package, "max_iterations", 1))
    parent_trace_id = getattr(getattr(context_package, "request", None), "parent_trace_id", "")
    subagent_name = getattr(getattr(context_package, "descriptor", None), "name", "unknown")
    execution_mode = getattr(context_package, "execution_mode", "local_fake")
    memory_scope = getattr(getattr(context_package, "request", None), "memory_scope", "none")
    role_prompt = getattr(context_package, "role_prompt", "")
    goal = getattr(context_package, "goal", task)
    constraints = getattr(context_package, "constraints", ())
    allowed_tool_names = [
        getattr(ts, "name", str(ts))
        for ts in getattr(context_package, "allowed_tools", ())
    ]

    # 构建 child system prompt
    system_prompt = _build_child_system_prompt(
        role_prompt=role_prompt,
        goal=goal,
        constraints=constraints,
        allowed_tool_names=allowed_tool_names,
    )

    # 构建 child messages
    child_messages: list[dict[str, Any]] = [
        {"role": "user", "content": task},
    ]

    # 构建 model-visible tools（复用 parent tool metadata）
    child_tools: list[dict[str, Any]] = []
    for ts in getattr(context_package, "allowed_tools", ()):
        if hasattr(ts, "name") and hasattr(ts, "description"):
            child_tools.append({
                "name": getattr(ts, "name", ""),
                "description": getattr(ts, "description", ""),
                "input_schema": {"type": "object", "properties": {}, "required": []},
            })

    iterations_used = 0
    status = "ok"
    stop_reason = "task_completed"
    summary = ""
    confidence = 0.8
    warnings: list[str] = []
    tools_requested: list[str] = []
    tools_denied: list[str] = []
    tools_executed: list[str] = []
    trace_events: list[object] = []

    # ── Child turn loop ──────────────────────────────────────────────────
    for iteration in range(1, max_iterations + 1):
        iterations_used = iteration

        if provider is None:
            status = "error"
            stop_reason = "error"
            summary = "L1 executor: provider is required but was None"
            warnings.append("missing provider")
            break

        try:
            response = provider.create(
                system=system_prompt,
                messages=child_messages,
                tools=child_tools,
            )
        except Exception as exc:
            status = "error"
            stop_reason = "error"
            summary = f"Provider call failed: {exc}"
            warnings.append(f"provider error: {exc}")
            break

        # 解析 response content blocks
        text_blocks: list[str] = []
        tool_use_blocks: list[Any] = []

        for block in response.content:
            if hasattr(block, "type"):
                if block.type == "text":
                    text_blocks.append(getattr(block, "text", ""))
                elif block.type == "tool_use":
                    tool_use_blocks.append(block)

        # 追加 assistant 响应到 child_messages
        serialized_content: list[dict[str, Any]] = []
        for tb in text_blocks:
            if tb:
                serialized_content.append({"type": "text", "text": tb})
        for tu in tool_use_blocks:
            serialized_content.append({
                "type": "tool_use",
                "id": getattr(tu, "id", ""),
                "name": getattr(tu, "name", ""),
                "input": getattr(tu, "input", {}),
            })
        child_messages.append({"role": "assistant", "content": serialized_content})

        # 处理 tool_use blocks
        if tool_use_blocks and response.stop_reason == "tool_use":
            for tu_block in tool_use_blocks:
                tool_name = getattr(tu_block, "name", "")
                tool_input = dict(getattr(tu_block, "input", {}))
                tool_use_id = getattr(tu_block, "id", "")

                tools_requested.append(tool_name)

                if tool_mediator is not None:
                    child_result = tool_mediator.mediate_child_tool_request(
                        tool_name,
                        tool_input,
                        delegation_id=delegation_id,
                        parent_trace_id=parent_trace_id,
                    )
                else:
                    child_result = None

                if child_result == "FORCE_STOP":
                    tools_denied.append(tool_name)
                    child_messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": "[安全策略] 工具被 parent gate 阻断",
                        }],
                    })
                else:
                    tools_executed.append(tool_name)
                    _key = f"child:{delegation_id}:{tool_name}"
                    _tc = getattr(tool_mediator, "_turn_context", {})
                    _real = _tc.get(_key) if tool_mediator is not None else None
                    result_text = _real or f"[L1 child] 工具 {tool_name} 已执行。"
                    child_messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": result_text,
                        }],
                    })
            # 继续下一轮迭代
            continue

        # end_turn 或其他 stop_reason
        summary = " ".join(text_blocks) if text_blocks else ""
        stop_reason = response.stop_reason or "task_completed"
        if stop_reason == "end_turn":
            stop_reason = "task_completed"
        break
    else:
        # max_iterations 耗尽
        stop_reason = "max_iterations_exceeded"
        status = "max_iterations_exceeded"
        warnings.append("max_iterations reached")
        if not summary:
            summary = f"L1 child loop reached max_iterations ({max_iterations})."

    # ── Child memory proposal (Loop 3.2b) ─────────────────────────────────
    # child loop 结束后，如果 memory_scope=propose 且有实质产出，通过 parent
    # tool_mediator 写入 namespaced store（不直接写 store）。
    if memory_scope == "propose" and summary and tool_mediator is not None:
        tool_mediator.mediate_child_memory_request(
            key="child_summary",
            value=summary,
            delegation_id=delegation_id,
            parent_trace_id=parent_trace_id,
            subagent_name=subagent_name,
            memory_scope=memory_scope,
        )

    trace_events = (
        make_trace_event(
            "l1_result_returned",
            delegation_id=delegation_id,
            parent_trace_id=parent_trace_id,
            data={"status": status, "stop_reason": stop_reason, "iterations_used": iterations_used},
        ),
    )

    audit = SubAgentAuditRecord(
        subagent_name=subagent_name,
        delegation_id=delegation_id,
        parent_trace_id=parent_trace_id,
        execution_mode=execution_mode,
        status=status,
        stop_reason=stop_reason,
        iterations_used=iterations_used,
        max_iterations=max_iterations,
        tools_requested=tuple(tools_requested),
        tools_denied=tuple(tools_denied),
        tools_executed=tuple(tools_executed),
        memory_proposals_count=0,
        warnings=tuple(warnings),
        confidence=confidence,
        elapsed_ms=max(1, int((time.monotonic() - started) * 1000)),
        revision_count=0,
        trace_event_count=len(trace_events),
    )
    return SubAgentResult(
        status=status,
        summary=summary,
        artifacts=(),
        tool_requests=(),
        memory_proposals=(),
        confidence=confidence,
        warnings=tuple(warnings),
        audit=audit,
        handoff_back="Parent must adjudicate this L1 result.",
        clarification_question=None,
        trace_events=trace_events,
        stop_reason=stop_reason,
    )


def _build_child_system_prompt(
    *,
    role_prompt: str,
    goal: str,
    constraints: tuple[str, ...],
    allowed_tool_names: list[str],
) -> str:
    """构建 child loop system prompt。"""
    parts: list[str] = []
    if role_prompt:
        parts.append(role_prompt)
    if goal:
        parts.append(f"目标: {goal}")
    if constraints:
        parts.append("约束:")
        for c in constraints:
            parts.append(f"  - {c}")
    if allowed_tool_names:
        parts.append(f"可用工具: {', '.join(allowed_tool_names)}")
    parts.append("请在完成任务后停止（end_turn）。如需使用工具，请通过 tool_use 请求。")
    return "\n".join(parts)
