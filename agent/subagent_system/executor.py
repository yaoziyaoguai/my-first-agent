"""L0/L1/L2 bounded local SubAgent executor."""

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
    # 收集 child 可用工具名：优先从 context_package.allowed_tools 取 object，
    # 再合并 context_package.request.allowed_tools（descriptor 中的字符串名）。
    _cp_tool_names: set[str] = set()
    for ts in getattr(context_package, "allowed_tools", ()):
        name = getattr(ts, "name", None)
        if isinstance(name, str) and name:
            _cp_tool_names.add(name)
    _req = getattr(context_package, "request", None)
    _req_tool_names = [
        str(t) for t in getattr(_req, "allowed_tools", ()) or ()
    ]
    allowed_tool_names = sorted(_cp_tool_names | set(_req_tool_names))

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

    # 构建 model-visible tools — 从 TOOL_REGISTRY 查找真实 tool schema
    from agent.tool_registry import TOOL_REGISTRY as _TR

    child_tools: list[dict[str, Any]] = []
    for name in allowed_tool_names:
        entry = _TR.get(name)
        if entry is not None:
            child_tools.append({
                "name": entry["name"],
                "description": entry["description"],
                "input_schema": entry.get("parameters", {
                    "type": "object", "properties": {}, "required": [],
                }),
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


def _build_l2_child_system_prompt(
    *,
    role_prompt: str,
    goal: str,
    constraints: tuple[str, ...],
    allowed_tool_names: list[str],
) -> str:
    """构建 L2 child loop system prompt（含独立停止条件规则）。"""
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
    parts.append(
        "你可以自主决定何时完成任务并停止（end_turn）。"
        "以下情况应该停止："
        "  (1) 任务已完成且有最终摘要"
        "  (2) 需要 parent 澄清（设置 clarification_question）"
        "  (3) 可用工具已耗尽"
        "以下情况不应停止："
        "  (1) 还在等待下一轮工具结果"
        "  (2) 任务部分完成且工具仍可用"
    )
    parts.append(
        "如需提交多个 memory proposal，"
        "请在最终回复中以 JSON block 格式输出 batch_memory: "
        '{"batch_memory": [{"key": "...", "value": "...", "scope": "..."}]}'
    )
    return "\n".join(parts)


def execute_l2(
    context_package: object,
    *,
    delegation_id: str = "delegation-l2",
    provider: Any = None,
    tool_mediator: Any = None,
) -> SubAgentResult:
    """Execute L2 native-loop delegation with independent stop condition.

    L2 在 L1 基础上增加：
    - child 可自主发出 stop_signal（end_turn）而不依赖 max_iterations
    - child 可批量提交 memory proposals（batch_memory）
    - child 可访问 deepened 工具集（read_file + grep + glob）
    - child 可请求 parent revision（clarification_question）

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
    execution_mode = getattr(context_package, "execution_mode", "real_llm_tool_requesting")
    memory_scope = getattr(getattr(context_package, "request", None), "memory_scope", "none")
    role_prompt = getattr(context_package, "role_prompt", "")
    goal = getattr(context_package, "goal", task)
    constraints = getattr(context_package, "constraints", ())

    # L2 deepened tool set — read_file + grep + glob
    _cp_tool_names: set[str] = set()
    for ts in getattr(context_package, "allowed_tools", ()):
        name = getattr(ts, "name", None)
        if isinstance(name, str) and name:
            _cp_tool_names.add(name)
    _req = getattr(context_package, "request", None)
    _req_tool_names = [
        str(t) for t in getattr(_req, "allowed_tools", ()) or ()
    ]
    base_tool_names = sorted(_cp_tool_names | set(_req_tool_names))
    # L2: always add grep + glob if not already present
    for _extra in ("grep", "glob"):
        if _extra not in base_tool_names:
            base_tool_names.append(_extra)
    allowed_tool_names = base_tool_names

    system_prompt = _build_l2_child_system_prompt(
        role_prompt=role_prompt,
        goal=goal,
        constraints=constraints,
        allowed_tool_names=allowed_tool_names,
    )

    child_messages: list[dict[str, Any]] = [
        {"role": "user", "content": task},
    ]

    from agent.tool_registry import TOOL_REGISTRY as _TR

    child_tools: list[dict[str, Any]] = []
    for name in allowed_tool_names:
        entry = _TR.get(name)
        if entry is not None:
            child_tools.append({
                "name": entry["name"],
                "description": entry["description"],
                "input_schema": entry.get("parameters", {
                    "type": "object", "properties": {}, "required": [],
                }),
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
    batch_memory_proposals: list[object] = []
    clarification_question: str | None = None

    for iteration in range(1, max_iterations + 1):
        iterations_used = iteration

        if provider is None:
            status = "error"
            stop_reason = "error"
            summary = "L2 executor: provider is required but was None"
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

        text_blocks: list[str] = []
        tool_use_blocks: list[Any] = []

        for block in response.content:
            if hasattr(block, "type"):
                if block.type == "text":
                    text_blocks.append(getattr(block, "text", ""))
                elif block.type == "tool_use":
                    tool_use_blocks.append(block)

        combined_text = " ".join(text_blocks) if text_blocks else ""
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

        # Parse batch_memory from response text
        if combined_text:
            _parsed = _parse_batch_memory(combined_text)
            if _parsed:
                batch_memory_proposals.extend(_parsed)

        # Parse clarification request
        _resp_stop = response.stop_reason if hasattr(response, "stop_reason") else ""
        if _resp_stop == "end_turn" and ("clarif" in combined_text.lower()
                                          or "question" in combined_text.lower()
                                          or "revision" in combined_text.lower()):
            clarification_question = combined_text.strip()[:500]

        # Tool use — same parent-mediated path as L1
        if tool_use_blocks and getattr(response, "stop_reason", "") == "tool_use":
            for tu_block in tool_use_blocks:
                tool_name = getattr(tu_block, "name", "")
                tool_input = dict(getattr(tu_block, "input", {}))
                tool_use_id = getattr(tu_block, "id", "")
                tools_requested.append(tool_name)

                if tool_mediator is not None:
                    child_result = tool_mediator.mediate_child_tool_request(
                        tool_name, tool_input,
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
                    result_text = _real or f"[L2 child] 工具 {tool_name} 已执行。"
                    child_messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": result_text,
                        }],
                    })
            continue

        # end_turn — child explicitly decided to stop
        summary = combined_text
        if getattr(response, "stop_reason", "") == "end_turn":
            stop_reason = "task_completed_by_child"
        else:
            _rs = getattr(response, "stop_reason", None)
            stop_reason = _rs if _rs else "task_completed"
        break
    else:
        stop_reason = "max_iterations_exceeded"
        status = "max_iterations_exceeded"
        warnings.append("max_iterations reached")
        if not summary:
            summary = f"L2 child loop reached max_iterations ({max_iterations})."

    # Batch memory proposal through parent
    if memory_scope == "propose" and batch_memory_proposals and tool_mediator is not None:
        for _bp in batch_memory_proposals:
            _bk = str(getattr(_bp, "key", "") or _bp.get("key", ""))
            _bv = str(getattr(_bp, "value", "") or _bp.get("value", ""))
            if _bk and _bv:
                tool_mediator.mediate_child_memory_request(
                    key=_bk, value=_bv,
                    delegation_id=delegation_id,
                    parent_trace_id=parent_trace_id,
                    subagent_name=subagent_name,
                    memory_scope=memory_scope,
                )
    elif memory_scope == "propose" and summary and tool_mediator is not None:
        tool_mediator.mediate_child_memory_request(
            key="child_summary", value=summary,
            delegation_id=delegation_id,
            parent_trace_id=parent_trace_id,
            subagent_name=subagent_name,
            memory_scope=memory_scope,
        )

    trace_events = (
        make_trace_event(
            "l2_result_returned",
            delegation_id=delegation_id,
            parent_trace_id=parent_trace_id,
            data={
                "status": status,
                "stop_reason": stop_reason,
                "iterations_used": iterations_used,
                "batch_memory_count": len(batch_memory_proposals),
                "level": "L2",
            },
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
        memory_proposals_count=len(batch_memory_proposals),
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
        handoff_back="Parent must adjudicate this L2 result.",
        clarification_question=clarification_question,
        trace_events=trace_events,
        stop_reason=stop_reason,
        batch_memory_proposals=tuple(batch_memory_proposals),
    )


def _parse_batch_memory(text: str) -> list[object] | None:
    """Parse batch_memory JSON block from child response text.

    返回 None 表示未找到合法 batch_memory block；返回 list 表示解析成功。
    格式: {"batch_memory": [{"key": "...", "value": "...", "scope": "..."}]}
    """
    import json as _json

    # 定位 "batch_memory" 关键字
    _idx = text.find('"batch_memory"')
    if _idx == -1:
        return None

    # 从 batch_memory 往前找最近的 '{'（JSON 对象的开始）
    _brace_start = text.rfind('{', 0, _idx)
    if _brace_start == -1:
        return None

    # bracket-counting: 从 _brace_start 开始计数，找到匹配的 '}'
    _depth = 0
    _brace_end = -1
    for _i in range(_brace_start, len(text)):
        _ch = text[_i]
        if _ch == '{':
            _depth += 1
        elif _ch == '}':
            _depth -= 1
            if _depth == 0:
                _brace_end = _i
                break

    if _brace_end == -1:
        return None

    _candidate = text[_brace_start:_brace_end + 1]
    try:
        data = _json.loads(_candidate)
    except (_json.JSONDecodeError, ValueError):
        return None

    proposals = data.get("batch_memory", [])
    if isinstance(proposals, list) and len(proposals) > 0:
        result: list[object] = []
        for item in proposals:
            if isinstance(item, dict) and "key" in item and "value" in item:
                result.append(item)
        return result if result else None
    return None
