"""U3: checkpoint skill restore helper。

从 checkpoint 顶层 "skill" metadata 恢复 active skill。
validate/load 成功后一次性 apply；失败时 clear 并记录 reason。
不盲信 checkpoint 中旧 allowed_tools —— 必须使用当前 manifest/descriptor 值。
"""

from __future__ import annotations

import enum
from collections.abc import Callable


class RestoreResult(enum.Enum):
    RESTORED = "restored"
    CLEARED = "cleared"


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


def _clear_with_reason(
    lifecycle,
    evidence_callback: Callable | None,
    *,
    skill_id: str,
    reason: str,
) -> RestoreResult:
    lifecycle.deactivate()
    _safe_evidence(
        evidence_callback,
        subsystem="skill",
        operation="restore_cleared",
        safe_summary=f"skill={skill_id or '<unknown>'} reason={reason}",
    )
    return RestoreResult.CLEARED


def restore_active_skill_from_checkpoint_metadata(
    metadata: dict,
    registry,
    loader,
    lifecycle,
    *,
    evidence_callback: Callable | None = None,
) -> RestoreResult:
    """从 checkpoint metadata 恢复 active skill。

    顺序固定不可调整：
    1. 解析 metadata
    2. validate skill_id
    3. 查询 registry
    4. 确认 skill 存在、visible、enabled、manifest valid
    5. 用 loader.load_body(skill_id) 加载 body
    6. 使用当前 descriptor 的 allowed_tools（不盲信 checkpoint 旧值）
    7. 全部成功后一次性 restore_from_checkpoint_metadata()
    8. 失败时 deactivate()，返回 CLEARED + reason
    """
    if not isinstance(metadata, dict) or "skill_id" not in metadata:
        return _clear_with_reason(
            lifecycle,
            evidence_callback,
            skill_id="",
            reason="invalid_metadata",
        )

    skill_id = str(metadata["skill_id"])
    if not skill_id:
        return _clear_with_reason(
            lifecycle,
            evidence_callback,
            skill_id="",
            reason="invalid_metadata",
        )

    # Step 2-4: validate skill exists + visible + enabled
    descriptor = registry.get_descriptor(skill_id)
    if descriptor is None:
        return _clear_with_reason(
            lifecycle,
            evidence_callback,
            skill_id=skill_id,
            reason="skill_missing",
        )

    if not descriptor.is_visible():
        return _clear_with_reason(
            lifecycle,
            evidence_callback,
            skill_id=skill_id,
            reason=f"skill_hidden_or_disabled status={descriptor.status}",
        )

    # Step 5: load body
    try:
        body = loader.load_body(skill_id)
    except Exception:
        return _clear_with_reason(
            lifecycle,
            evidence_callback,
            skill_id=skill_id,
            reason="body_load_failed",
        )

    if not body:
        return _clear_with_reason(
            lifecycle,
            evidence_callback,
            skill_id=skill_id,
            reason="empty_body",
        )

    # Step 6: 使用当前 descriptor 的 allowed_tools，不盲信 checkpoint 旧值
    current_allowed_tools = descriptor.allowed_tools

    # Step 7: 一次性 apply
    lifecycle.restore_from_checkpoint_metadata(
        skill_id=skill_id,
        body=body,
        allowed_tools=current_allowed_tools,
        activated_at=metadata.get("activated_at"),
        activated_by="checkpoint_resume",
    )

    _safe_evidence(
        evidence_callback,
        subsystem="skill",
        operation="restored",
        safe_summary=f"skill={skill_id} allowed_tools_count={len(current_allowed_tools)}",
    )
    return RestoreResult.RESTORED
