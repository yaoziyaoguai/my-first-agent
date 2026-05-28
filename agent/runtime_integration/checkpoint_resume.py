"""CheckpointResume RuntimeAction handler — dispatcher-mediated checkpoint restoration.

Loop 2.3: 将 load_checkpoint_to_state() 纳入 dispatcher evidence lifecycle，
使 checkpoint resume 接入统一 main runtime path，产生可追溯的 evidence chain。
"""

from __future__ import annotations

from agent.runtime_integration.dispatcher import RuntimeActionContext
from agent.runtime_integration.schema import RuntimeActionRequest


class CheckpointResumeHandler:
    """checkpoint 恢复通过 dispatcher 中介，产生 RuntimeAction evidence。

    不重写 load_checkpoint_to_state 逻辑，只在其外围包裹 dispatcher evidence。
    """

    def handle(self, request: RuntimeActionRequest, context: RuntimeActionContext):
        from agent.checkpoint import load_checkpoint_to_state as _load

        payload = dict(request.payload)
        state = payload.get("_state")
        resume_mode = str(payload.get("resume_mode") or "interactive")
        already_loaded = bool(payload.get("_already_loaded"))

        observed = context.invoke_registered_target(
            target_module="CheckpointResume",
            operation="restore",
            payload={
                "resume_mode": resume_mode,
                "already_loaded": already_loaded,
            },
        )

        restored = False
        restored_status = None
        restored_step_index = None
        restored_has_pending_tool = False
        restored_has_pending_input = False

        if state is not None:
            try:
                # session.py 已执行 load_checkpoint_to_state 时跳过重复 load，只记录 evidence。
                restored = True if already_loaded else _load(state)
                if restored:
                    restored_status = getattr(state.task, "status", None)
                    restored_step_index = getattr(
                        state.task, "current_step_index", None
                    )
                    restored_has_pending_tool = (
                        getattr(state.task, "pending_tool", None) is not None
                    )
                    restored_has_pending_input = (
                        getattr(state.task, "pending_user_input_request", None)
                        is not None
                    )
            except Exception:
                restored = False

        evidence_extra = {
            "resume_mode": resume_mode,
            "restore_succeeded": restored,
            "restored_task_status": restored_status,
            "restored_step_index": restored_step_index,
            "restored_has_pending_tool": restored_has_pending_tool,
            "restored_has_pending_input": restored_has_pending_input,
            "checkpoint_mediated": True,
            "capability_type": "checkpoint_restoration",
            "production_capability": True,
        }

        if not restored:
            return context.failed(
                handler_name=type(self).__name__,
                target_module="CheckpointResume",
                payload={
                    "restore_succeeded": False,
                    "resume_mode": resume_mode,
                },
                observed_call=observed,
                evidence_extra=evidence_extra,
                error_safe_preview="checkpoint resume failed or no checkpoint found",
            )

        return context.success(
            handler_name=type(self).__name__,
            target_module="CheckpointResume",
            payload={
                "restore_succeeded": True,
                "restored_task_status": restored_status,
                "restored_step_index": restored_step_index,
            },
            observed_call=observed,
            evidence_extra=evidence_extra,
        )
