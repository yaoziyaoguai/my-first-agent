"""ActionScheduler RuntimeAction handler — dispatcher-mediated scheduler evidence.

Loop 3.4: Advanced Scheduler 的 5 个 RuntimeActionType（ACTION_PLAN_START /
NODE_ENTER / NODE_EXIT / NODE_FAILURE / ACTION_PLAN_COMPLETE）通过此 handler
在 dispatcher 中注册，使 scheduler 的 orchestration decision 产生
RuntimeAction evidence。

中文学习说明：
Scheduler 本身通过 dispatcher.route_from_runtime_loop() 产生 evidence。
此 handler 不重写 scheduler 逻辑——只负责验证 payload 结构并通过
context.invoke_registered_target() 建立 evidence chain。
Scheduler 是 orchestrator（决定何时、以什么顺序执行），不是 executor
（不直接调用 tool/memory/skill/subagent）。执行委托给注入的 ActionExecutor。
"""

from __future__ import annotations

from typing import Any

from agent.runtime_integration.dispatcher import RuntimeActionContext
from agent.runtime_integration.schema import RuntimeActionRequest


class ActionSchedulerHandler:
    """Advanced Scheduler 的 dispatcher evidence handler。

    5 个 action type 共用此 handler——每种 type 的 payload 结构不同，
    但 handler 的职责相同：验证 payload → invoke_registered_target → 返回 success。
    """

    # 每个 action type 需要的 payload key
    _REQUIRED_KEYS: dict[str, frozenset[str]] = {
        "scheduler.action_plan_start": frozenset({
            "plan_id", "total_nodes", "node_ids", "entry_node_id",
        }),
        "scheduler.node_enter": frozenset({
            "node_id", "action_type", "target", "plan_id",
        }),
        "scheduler.node_exit": frozenset({
            "node_id", "action_type", "target", "disposition", "success",
        }),
        "scheduler.node_failure": frozenset({
            "node_id", "action_type", "target", "error", "recovery_on_failure",
        }),
        "scheduler.action_plan_complete": frozenset({
            "plan_id", "disposition", "completed_nodes", "total_nodes",
        }),
    }

    def handle(self, request: RuntimeActionRequest, context: RuntimeActionContext):
        """验证 scheduler evidence payload 并返回 success。

        中文学习说明：
        Scheduler 不直接调用 tool/memory/skill 子系统——它只是 orchestration
        layer。此 handler 验证 payload 结构完整性，但不执行任何业务逻辑。
        真正执行业务逻辑的是注入 ActionScheduler 的 ActionExecutor。
        """
        payload = dict(request.payload)
        action_type = str(request.action_type)

        # 提取通用字段
        plan_id = str(payload.get("plan_id") or "")
        node_id = str(payload.get("node_id") or "")
        node_action_type = str(payload.get("action_type") or "")
        target = str(payload.get("target") or "")
        disposition = str(payload.get("disposition") or "")
        error_msg = str(payload.get("error") or "")
        success_flag = payload.get("success")

        # 验证必填 key
        required = self._REQUIRED_KEYS.get(action_type)
        missing = []
        if required is not None:
            missing = [k for k in required if k not in payload]
        if missing:
            return context.failed(
                handler_name=type(self).__name__,
                target_module="ActionScheduler",
                payload={"missing_keys": missing, "action_type": action_type},
                error_safe_preview=f"Missing required keys: {missing}",
            )

        # 通过 catalog-owned adapter 建立 evidence chain
        observed = context.invoke_registered_target(
            target_module="ActionScheduler",
            operation=action_type.replace("scheduler.", ""),
            payload={
                "plan_id": plan_id,
                "node_id": node_id,
                "action_type": node_action_type,
                "target": target,
                "disposition": disposition,
            },
        )

        evidence_extra: dict[str, Any] = {
            "scheduler_mediated": True,
            "plan_id": plan_id,
            "node_id": node_id,
            "disposition": disposition,
            "capability_type": "advanced_scheduler",
            "production_capability": True,
        }
        if error_msg:
            evidence_extra["error"] = error_msg
            evidence_extra["failure_count"] = payload.get("failure_count", 0)
            evidence_extra["recovery_on_failure"] = str(
                payload.get("recovery_on_failure") or ""
            )
        if success_flag is not None:
            evidence_extra["success"] = bool(success_flag)

        return context.success(
            handler_name=type(self).__name__,
            target_module="ActionScheduler",
            payload={
                "action_type": action_type,
                "plan_id": plan_id,
                "node_id": node_id,
                "disposition": disposition,
                "validated": True,
            },
            observed_call=observed,
            evidence_extra=evidence_extra,
        )
