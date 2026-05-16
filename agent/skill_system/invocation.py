"""Skill Invocation Adapter —— request/result flow，不拥有 loop。

设计原则（来自 RFC Sec 3 / SDD Sec 8）：
- Skill 不拥有 Agent loop
- invocation 是 request/result flow
- Skill 不直接执行工具
- Skill 不直接写 Memory
- InvocationResult 可审计
- failed invocation fail closed
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from agent.skill_system.context import SkillContext
from agent.skill_system.errors import SkillLoadError
from agent.skill_system.loader import SkillLoader
from agent.skill_system.registry import SkillRegistry
from agent.skill_system.result import (
    SkillAuditRecord,
    SkillInvocationResult,
)


@dataclass(frozen=True)
class SkillInvocationRequest:
    """Skill 调用请求——parent Runtime 发起的输入。

    字段对应 SDD Sec 3 的 SkillInvocationRequest 定义。
    """

    skill_name: str
    """目标 Skill name。"""

    user_goal: str = ""
    """用户/调用者的任务目标。"""

    selection_reason: str = ""
    """为什么选中这个 Skill（exact match / keyword / tag）。"""

    requested_resources: tuple[str, ...] = ()
    """显式请求的 Level 3 resource keys（如 "references/guide.md"）。"""


def invoke_skill(
    request: SkillInvocationRequest,
    registry: SkillRegistry,
    loader: SkillLoader,
    audit_id: str | None = None,
) -> SkillInvocationResult:
    """执行一次 Skill 调用（一次性 request/result flow）。

    流程：
    1. 查找 descriptor
    2. 检查 visible
    3. 加载 body（Level 2）
    4. 组装 SkillContext
    5. 构建 audit record
    6. 返回 SkillInvocationResult

    不拥有 loop、不执行 tool、不写 Memory。
    """
    audit_id = audit_id or str(uuid.uuid4())
    errors: list[SkillLoadError] = []

    # Step 1: 查找 descriptor
    descriptor = registry.get_descriptor(request.skill_name)
    if descriptor is None:
        errors.append(SkillLoadError(
            code="SKILL_NOT_FOUND",
            message=f"Skill '{request.skill_name}' 未在 registry 中找到",
            recoverable=False,
            safe_preview=f"Skill '{request.skill_name}' 不存在",
        ))
        audit = SkillAuditRecord(
            audit_id=audit_id,
            skill_name=request.skill_name,
            skill_version="unknown",
            selection_reason=request.selection_reason,
            loaded_levels=0,
            loaded_resources=(),
            requested_tools=(),
            blocked_tools=(),
            memory_scope="none",
            result_status="error",
            safe_preview="skill not found",
        )
        return SkillInvocationResult.error_result(
            request.skill_name,
            errors=tuple(errors),
            audit_record=audit,
        )

    # Step 2: 检查 visible
    if not descriptor.is_visible():
        errors.append(SkillLoadError(
            code="SKILL_HIDDEN",
            message=f"Skill '{request.skill_name}' 状态为 {descriptor.status}，不可调用",
            recoverable=False,
            safe_preview=f"Skill '{request.skill_name}' 不可用",
        ))
        audit = SkillAuditRecord(
            audit_id=audit_id,
            skill_name=request.skill_name,
            skill_version=descriptor.version,
            selection_reason=request.selection_reason,
            loaded_levels=0,
            loaded_resources=(),
            requested_tools=descriptor.allowed_tools,
            blocked_tools=(),
            memory_scope=descriptor.memory_scope,
            result_status="blocked",
            safe_preview=f"skill {request.skill_name} is not visible",
        )
        return SkillInvocationResult.error_result(
            request.skill_name,
            errors=tuple(errors),
            audit_record=audit,
        )

    # Step 3: 加载 body（Level 2）
    try:
        body = loader.load_body(request.skill_name)
    except SkillLoadError as e:
        errors.append(e)
        audit = SkillAuditRecord(
            audit_id=audit_id,
            skill_name=request.skill_name,
            skill_version=descriptor.version,
            selection_reason=request.selection_reason,
            loaded_levels=1,
            loaded_resources=(),
            requested_tools=descriptor.allowed_tools,
            blocked_tools=(),
            memory_scope=descriptor.memory_scope,
            result_status="error",
            safe_preview=f"failed to load body: {e.safe_preview}",
        )
        return SkillInvocationResult.error_result(
            request.skill_name,
            errors=tuple(errors),
            audit_record=audit,
        )

    # Step 4: 组装 SkillContext（供后续阶段扩展使用）
    _ctx = SkillContext(
        descriptor=descriptor,
        body=body,
        task_goal=request.user_goal,
        audit_id=audit_id,
        memory_scope=descriptor.memory_scope,
    )

    # Step 5: 构建输出
    loaded_level = loader.loaded_levels.get(request.skill_name, 2)
    audit_record = loader.get_audit_record(request.skill_name)

    audit = SkillAuditRecord(
        audit_id=audit_id,
        skill_name=request.skill_name,
        skill_version=descriptor.version,
        selection_reason=request.selection_reason,
        loaded_levels=loaded_level,
        loaded_resources=tuple(audit_record.get("loaded_resources", ())),
        requested_tools=descriptor.allowed_tools,
        blocked_tools=(),
        memory_scope=descriptor.memory_scope,
        result_status="ok",
        safe_preview=f"invoked skill '{request.skill_name}' v{descriptor.version}",
    )

    return SkillInvocationResult.ok_result(
        skill_name=request.skill_name,
        visible_output=body,
        audit_record=audit,
    )
