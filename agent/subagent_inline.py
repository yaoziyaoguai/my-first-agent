"""内联 subagent 委托执行（从 agent/core.py _execute_subagent_delegation 提取）。

提供 execute_subagent_delegation()——CLI delegate 和 NL delegation 的共享委托执行路径。
不做检测/解析——只做 registry lookup → SubAgentRequest 构造 →
delegate_once() 执行 → 结果渲染。

中文学习边界：
- 这不是第二条 runtime——所有委托仍通过 delegate_once() + SubAgentRegistry
  执行，不绕过 core.chat() 统一入口
- 进度事件仍通过 on_runtime_event 发射
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.cli_commands import (
    render_delegate_error,
    render_delegate_not_found,
    render_delegate_result,
)
from agent.display_events import (
    subagent_delegated_event,
    subagent_delegating_event,
)
from agent.runtime_event_safety import safe_emit_runtime_event
from agent.subagent_system.delegation import delegate_once
from agent.subagent_system.registry import SubAgentRegistry
from agent.subagent_system.request import SubAgentRequest

# 重新导出以保持向后兼容
__all__ = ["execute_subagent_delegation"]


def execute_subagent_delegation(
    subagent_name: str,
    task: str,
    *,
    delegation_reason: str = "CLI meta-command delegation",
    on_runtime_event: Callable | None = None,
    state: Any = None,
) -> str:
    """执行一次子代理委托并返回渲染后的用户可见结果。

    state（S3-G05 / 审计 H1 修复）：传入 runtime AgentState 时，把成功委派的安全投影
    经 `record_delegation_run` 写入 `state.task.delegation_log`，使 SubAgent
    second-opinion 结果进入 checkpoint/evidence report（`extensions.delegations`）。
    不传则行为同旧版（只渲染、不记录）——既有 CLI/测试调用向后兼容。
    parent-mediated 不变：投影只记录已发生的 parent adjudication，不赋予 child 旁路。
    """
    try:
        registry = SubAgentRegistry(roots=[Path("agent/subagent_system/descriptors")])
    except Exception:
        return render_delegate_error(subagent_name, "无法加载子代理注册表")

    descriptor = registry.get_descriptor(subagent_name)
    if descriptor is None:
        visible_names = [d.name for d in registry.list_visible()]
        return render_delegate_not_found(subagent_name, visible_names)

    try:
        subagent_request = SubAgentRequest(
            task=task,
            role=descriptor.role,
            allowed_tools=descriptor.allowed_tools,
            parent_trace_id=f"delegation-{uuid4().hex[:8]}",
            delegation_reason=delegation_reason,
            max_iterations=descriptor.max_iterations_default,
            execution_mode="local_fake",
            risk_level=descriptor.risk_level,
        )
    except ValueError as exc:
        return f"委托请求无效：{exc}"

    safe_emit_runtime_event(
        on_runtime_event,
        subagent_delegating_event(subagent_name, task),
        fallback_prefix="\n",
    )

    try:
        run = delegate_once(subagent_request, registry)
    except Exception as exc:
        safe_emit_runtime_event(
            on_runtime_event,
            subagent_delegated_event(subagent_name, "error", str(exc)),
            fallback_prefix="\n",
        )
        return render_delegate_error(subagent_name, str(exc))

    # S3-G05 / 审计 H1：成功委派后把安全投影写入 task-state delegation_log，
    # 使 SubAgent second-opinion 进入 checkpoint/evidence report。record_delegation_run
    # 防御性读取 run.result.audit / run.adjudication，只记录已发生的 parent adjudication。
    if state is not None:
        from agent.task_delegation_evidence import record_delegation_run

        record_delegation_run(state, run)

    result = run.result
    status = getattr(result, "status", "unknown") if result else "unknown"
    summary = getattr(result, "summary", "") if result else ""
    stop_reason = getattr(result, "stop_reason", "") if result else ""
    confidence = getattr(result, "confidence", 0.0) if result else 0.0

    safe_emit_runtime_event(
        on_runtime_event,
        subagent_delegated_event(subagent_name, status, summary),
        fallback_prefix="\n",
    )

    return render_delegate_result(subagent_name, status, summary, stop_reason, confidence)
