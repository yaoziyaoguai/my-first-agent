"""Skill Invocation Result —— 结构化的 Skill 调用输出。

设计原则（来自 RFC/SDD）：
- 结果可审计（含 audit record）
- visible_output 不含 secrets
- errors 是 typed SkillLoadError tuple
- 不直接写 Memory（memory_proposals 回到 governance）
- 不拥有 loop
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.skill_system.errors import SkillLoadError


@dataclass(frozen=True)
class SkillAuditRecord:
    """Redacted 审计记录——不含 secret、不含完整 body/resources。

    字段对应 SDD Sec 3 的 SkillAuditRecord 定义。
    """

    audit_id: str
    skill_name: str
    skill_version: str
    selection_reason: str
    loaded_levels: int
    loaded_resources: tuple[str, ...]
    requested_tools: tuple[str, ...]
    blocked_tools: tuple[str, ...]
    memory_scope: str
    result_status: str
    safe_preview: str


@dataclass(frozen=True)
class SkillInvocationResult:
    """Skill 调用适配器的输出。

    ok=True 表示 Skill 成功执行（body loaded、context prepared）。
    errors 仅在失败时非空。
    memory_proposals 是候选 Memory 条目，需经 governance 批准。
    """

    ok: bool
    skill_name: str
    visible_output: str = ""
    visible_output_preview: str = ""
    requested_tool_names: tuple[str, ...] = ()
    requested_resources: tuple[str, ...] = ()
    memory_proposals: tuple[object, ...] = ()
    audit_record: SkillAuditRecord | None = None
    errors: tuple[SkillLoadError, ...] = ()

    @staticmethod
    def ok_result(
        skill_name: str,
        visible_output: str,
        audit_record: SkillAuditRecord | None = None,
        **kwargs,
    ) -> SkillInvocationResult:
        """便捷构造成功结果。"""
        return SkillInvocationResult(
            ok=True,
            skill_name=skill_name,
            visible_output=visible_output,
            visible_output_preview=visible_output[:200],
            audit_record=audit_record,
            **kwargs,
        )

    @staticmethod
    def error_result(
        skill_name: str,
        errors: tuple[SkillLoadError, ...],
        audit_record: SkillAuditRecord | None = None,
    ) -> SkillInvocationResult:
        """便捷构造失败结果。"""
        return SkillInvocationResult(
            ok=False,
            skill_name=skill_name,
            visible_output="",
            errors=errors,
            audit_record=audit_record,
        )
