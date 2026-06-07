"""CheckpointSave RuntimeAction handler — dispatcher-mediated checkpoint persistence.

Loop 2.3: 将 save_checkpoint() 从 direct call 迁入 dispatcher，
产生 RuntimeAction evidence，使 checkpoint save 接入统一 main runtime path。
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from agent.runtime_integration.dispatcher import RuntimeActionContext
from agent.runtime_integration.schema import RuntimeActionRequest


class CheckpointSkillMetadataError(RuntimeError):
    """Raised when an active skill cannot produce checkpoint-safe metadata."""


def _runtime_session_id(state: Any, explicit_session_id: str = "") -> str:
    if explicit_session_id:
        return explicit_session_id
    memory = getattr(state, "memory", None)
    return str(getattr(memory, "session_id", "") or "default")


def _active_skill_extra_sections(
    state: Any,
    *,
    session_id: str = "",
) -> dict[str, Any] | None:
    """Collect checkpoint-safe active skill metadata at the write boundary."""
    from agent.skill_system.lifecycle import get_default_lifecycle

    lifecycle = get_default_lifecycle(_runtime_session_id(state, session_id))
    active = lifecycle.get_active()
    if active is None:
        return None

    metadata = lifecycle.to_checkpoint_metadata()
    if not metadata:
        raise CheckpointSkillMetadataError(
            "active skill checkpoint metadata is empty"
        )
    return {"skill": metadata}


def save_runtime_checkpoint(
    state: Any,
    source: str | None = None,
    *,
    path: Path | None = None,
    session_id: str = "",
    run_id: str = "",
    extra_sections: dict[str, Any] | None = None,
) -> None:
    """Save a recoverable checkpoint through the runtime-owned gateway.

    Skill lifecycle metadata is collected at the final write boundary so every
    production owner gets a fresh, checkpoint-safe top-level ``skill`` section.
    """
    from agent.checkpoint import save_checkpoint as _save_checkpoint

    runtime_extra_sections = dict(extra_sections or {})
    skill_extra_sections = _active_skill_extra_sections(state, session_id=session_id)
    if skill_extra_sections:
        runtime_extra_sections.update(skill_extra_sections)
    checkpoint_kwargs: dict[str, Any] = {}
    if path is not None:
        checkpoint_kwargs["path"] = path
    if session_id:
        checkpoint_kwargs["session_id"] = session_id
    if run_id:
        checkpoint_kwargs["run_id"] = run_id
    if runtime_extra_sections:
        checkpoint_kwargs["extra_sections"] = runtime_extra_sections
    try:
        signature = inspect.signature(_save_checkpoint)
    except (TypeError, ValueError):
        accepted_kwargs = dict(checkpoint_kwargs)
        accepted_kwargs["source"] = source
    else:
        parameters = signature.parameters
        accepts_var_kwargs = any(
            param.kind is inspect.Parameter.VAR_KEYWORD
            for param in parameters.values()
        )
        accepted_kwargs = (
            dict(checkpoint_kwargs)
            if accepts_var_kwargs
            else {
                key: value
                for key, value in checkpoint_kwargs.items()
                if key in parameters
            }
        )
        if accepts_var_kwargs or "source" in parameters:
            accepted_kwargs["source"] = source
    _save_checkpoint(state, **accepted_kwargs)


class CheckpointSaveHandler:
    """checkpoint 保存通过 dispatcher 中介，产生 RuntimeAction evidence。

    不重写 save_checkpoint 逻辑，只在其外围包裹 dispatcher evidence lifecycle。
    """

    def handle(self, request: RuntimeActionRequest, context: RuntimeActionContext):
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

        # B7: 从 context.identity 提取 session_id/run_id 写 v2 per-run 路径
        _identity = getattr(context, "identity", None)
        _session_id = getattr(_identity, "session_id", "") or ""
        _run_id = getattr(_identity, "run_id", "") or ""

        save_ok = False
        if state is not None:
            try:
                save_runtime_checkpoint(
                    state, source=source,
                    session_id=_session_id, run_id=_run_id,
                )
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
