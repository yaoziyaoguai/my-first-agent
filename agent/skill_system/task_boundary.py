"""U4: task boundary active skill deactivation helper。

Task complete / reset / cancel / new task boundary 时清除 active skill。
Helper 幂等；caller 负责注入并记录 evidence。
"""

from __future__ import annotations

import enum
from collections.abc import Callable


class DeactivateResult(enum.Enum):
    DEACTIVATED = "deactivated"
    NO_ACTIVE_SKILL = "no_active_skill"


def _safe_evidence(
    evidence_callback: Callable | None,
    subsystem: str,
    operation: str,
    safe_summary: str,
    phase: str = "end",
    status: str = "ok",
) -> None:
    """安全调用 evidence callback，失败不抛异常。"""
    if evidence_callback is None:
        return
    try:  # noqa: SIM105
        evidence_callback(
            subsystem=subsystem,
            operation=operation,
            safe_summary=safe_summary,
            phase=phase,
            status=status,
        )
    except Exception:
        pass


def deactivate_active_skill_for_task_boundary(
    lifecycle,
    *,
    reason: str,
    source: str,
    evidence_callback: Callable | None = None,
) -> DeactivateResult:
    """Task boundary 时清除 active skill，确保下一 task 不受旧 skill 约束。

    幂等：无 active skill 时 no-op，不记录 evidence。
    evidence_callback 签名需兼容:
    record_evidence(subsystem=, operation=, safe_summary=, phase=, status=)。
    """
    active = lifecycle.get_active()
    if active is None:
        return DeactivateResult.NO_ACTIVE_SKILL

    skill_id = active.skill_id
    lifecycle.deactivate()

    _safe_evidence(
        evidence_callback,
        subsystem="skill",
        operation="deactivated",
        safe_summary=f"skill={skill_id} reason={reason} source={source}",
    )
    return DeactivateResult.DEACTIVATED
