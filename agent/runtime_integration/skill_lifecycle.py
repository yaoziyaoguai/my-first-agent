"""Runtime-owned Skill lifecycle restore and task-boundary helpers."""

from __future__ import annotations

from typing import Any


def _record_skill_evidence(operation: str, safe_summary: str) -> None:
    try:
        from agent.evidence_recorder import record_evidence

        record_evidence(
            subsystem="skill",
            operation=operation,
            phase="end",
            status="ok",
            safe_summary=safe_summary,
        )
    except Exception:
        pass


def _lifecycle_for_state(state: Any, session_id: str = ""):
    from agent.skill_system.lifecycle import get_default_lifecycle

    memory = getattr(state, "memory", None)
    namespace = session_id or str(getattr(memory, "session_id", "") or "default")
    return get_default_lifecycle(namespace)


def build_skill_restore_dependencies():
    """Build the current runtime registry/loader pair used for checkpoint resume."""
    from agent.runtime_integration.phase1_hook import build_skill_registry
    from agent.skill_system.loader import SkillLoader

    registry = build_skill_registry()
    return registry, SkillLoader(registry)


def clear_skill_lifecycle_for_resume(
    state: Any,
    *,
    reason: str,
    source: str,
    session_id: str = "",
):
    """Clear stale active skill state for a resume outcome."""
    lifecycle = _lifecycle_for_state(state, session_id)
    active = lifecycle.get_active()
    lifecycle.deactivate()
    if active is not None:
        _record_skill_evidence(
            "restore_cleared",
            f"skill={active.skill_id} reason={reason} source={source}",
        )
    return lifecycle


def restore_skill_lifecycle_from_checkpoint(
    state: Any,
    checkpoint: dict[str, Any] | None,
    *,
    source: str,
    session_id: str = "",
):
    """Restore or clear active skill from the selected checkpoint."""
    from agent.skill_system.gate import is_s2_skill_enabled

    lifecycle = _lifecycle_for_state(state, session_id)
    if not is_s2_skill_enabled():
        active = lifecycle.get_active()
        lifecycle.deactivate()
        if active is not None:
            _record_skill_evidence(
                "restore_cleared",
                "skill="
                f"{active.skill_id} reason=s2_skill_disabled "
                f"source={source}",
            )
        return "cleared"

    metadata = checkpoint.get("skill") if isinstance(checkpoint, dict) else None
    if not isinstance(metadata, dict) or not metadata:
        active = lifecycle.get_active()
        lifecycle.deactivate()
        if active is not None:
            _record_skill_evidence(
                "restore_cleared",
                "skill="
                f"{active.skill_id} reason=checkpoint_missing_skill_section "
                f"source={source}",
            )
        return "cleared"

    from agent.skill_system.checkpoint_restore import (
        restore_active_skill_from_checkpoint_metadata,
    )

    registry, loader = build_skill_restore_dependencies()
    return restore_active_skill_from_checkpoint_metadata(
        metadata,
        registry=registry,
        loader=loader,
        lifecycle=lifecycle,
        evidence_callback=lambda **kwargs: _record_skill_evidence(
            str(kwargs.get("operation") or "restore"),
            str(kwargs.get("safe_summary") or "skill restore"),
        ),
    )


def deactivate_active_skill_for_task_boundary(
    state: Any,
    *,
    reason: str,
    source: str,
    session_id: str = "",
):
    """Deactivate active skill before task state is cleared or replaced."""
    from agent.skill_system.task_boundary import (
        deactivate_active_skill_for_task_boundary as _deactivate,
    )

    return _deactivate(
        _lifecycle_for_state(state, session_id),
        reason=reason,
        source=source,
        evidence_callback=lambda **kwargs: _record_skill_evidence(
            str(kwargs.get("operation") or "deactivated"),
            str(kwargs.get("safe_summary") or "skill deactivated"),
        ),
    )
