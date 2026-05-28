"""CheckpointSave RuntimeAction handler — dispatcher-mediated checkpoint persistence.

Loop 2.3: 将 save_checkpoint() 从 direct call 迁入 dispatcher，
产生 RuntimeAction evidence，使 checkpoint save 接入统一 main runtime path。
"""

from __future__ import annotations

from agent.runtime_integration.dispatcher import RuntimeActionContext
from agent.runtime_integration.schema import RuntimeActionRequest


class CheckpointSaveHandler:
    """checkpoint 保存通过 dispatcher 中介，产生 RuntimeAction evidence。

    不重写 save_checkpoint 逻辑，只在其外围包裹 dispatcher evidence lifecycle。
    """

    def handle(self, request: RuntimeActionRequest, context: RuntimeActionContext):
        from agent.checkpoint import save_checkpoint as _save_checkpoint

        payload = dict(request.payload)
        state = payload.get("_state")
        source = str(payload.get("source") or "dispatcher")
        task_status = str(payload.get("task_status") or "unknown")
        step_index = payload.get("current_step_index")
        pending_tool_name = None
        pending_input_kind = None
        if isinstance(payload.get("pending_tool"), dict):
            pending_tool_name = payload["pending_tool"].get("tool")
        if isinstance(payload.get("pending_user_input_request"), dict):
            pending_input_kind = payload["pending_user_input_request"].get(
                "awaiting_kind"
            )

        observed = context.invoke_registered_target(
            target_module="CheckpointSave",
            operation="persist",
            payload={
                "task_status": task_status,
                "current_step_index": step_index,
                "has_pending_tool": pending_tool_name is not None,
                "has_pending_input": pending_input_kind is not None,
            },
        )

        save_ok = False
        if state is not None:
            try:
                _save_checkpoint(state, source=source)
                save_ok = True
            except Exception:
                save_ok = False

        evidence_extra = {
            "task_status": task_status,
            "current_step_index": step_index,
            "pending_tool_name": pending_tool_name,
            "pending_input_kind": pending_input_kind,
            "save_succeeded": save_ok,
            "checkpoint_mediated": True,
            "capability_type": "checkpoint_persistence",
            "production_capability": True,
        }

        if not save_ok:
            return context.failed(
                handler_name=type(self).__name__,
                target_module="CheckpointSave",
                payload={
                    "save_succeeded": False,
                    "task_status": task_status,
                },
                observed_call=observed,
                evidence_extra=evidence_extra,
                error_safe_preview="checkpoint save failed",
            )

        return context.success(
            handler_name=type(self).__name__,
            target_module="CheckpointSave",
            payload={
                "save_succeeded": True,
                "task_status": task_status,
                "current_step_index": step_index,
            },
            observed_call=observed,
            evidence_extra=evidence_extra,
        )
