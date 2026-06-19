"""S3-G05: 把 SubAgent 委派结果接入 task evidence / checkpoint / task-state 边界。

SubAgent 委派（`delegate_once` / `delegate_l1` / `delegate_l2`）返回的 `SubAgentRun`
默认是瞬态的——其 `SubAgentAuditRecord` / `ParentAdjudicationResult` 随返回值出作用域即丢，
不会进 task-state，因此 checkpoint→resume 后无法复盘（graphify + 代码核验，2026-06-20）。

本模块提供安全投影写入 `state.task.delegation_log`（TaskState 字段，自动进 checkpoint，
经 checkpoint._copy_state_dict 持久化 + _filter_to_declared_fields 恢复）：

- 只存 JSON-safe 安全投影（不存 raw payload / arguments / secrets），与 evidence_recorder
  的 safe-summary 纪律一致（非逐字保真 = TD-001 deferred）。
- parent-mediated 不变：投影只是「记录已发生的 parent adjudication」，不赋予 child 任何
  tool/provider/memory 旁路能力。

MCP tool 结果无需经此模块——它们经共享 tool 路径（execute_single_tool）落入
`tool_execution_log`，已是 TaskState 字段，自动跨 resume 保真。
"""
from __future__ import annotations

from typing import Any


def record_delegation_run(state: Any, run: Any) -> dict[str, Any]:
    """把一次 SubAgent 委派（`SubAgentRun`）的安全投影追加到 `state.task.delegation_log`。

    返回写入的投影 dict（便于调用方同时 record_evidence 到事件日志）。防御性读取
    run.result.audit / run.adjudication，避免部分构造的 run 导致崩溃。
    """

    audit = getattr(getattr(run, "result", None), "audit", None)
    adjudication = getattr(run, "adjudication", None)
    projection: dict[str, Any] = {
        "delegation_id": getattr(run, "delegation_id", ""),
        "subagent_name": getattr(audit, "subagent_name", "") if audit else "",
        "status": getattr(audit, "status", "") if audit else "",
        "stop_reason": getattr(audit, "stop_reason", "") if audit else "",
        "execution_mode": getattr(audit, "execution_mode", "") if audit else "",
        "adjudication_action": getattr(adjudication, "action", "") if adjudication else "",
        "confidence": getattr(audit, "confidence", 0.0) if audit else 0.0,
        "tools_executed": list(getattr(audit, "tools_executed", ()) or ()),
        "tools_denied": list(getattr(audit, "tools_denied", ()) or ()),
    }
    state.task.delegation_log.append(projection)
    return projection
