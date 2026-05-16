"""Skill Checkpoint/Resume Boundary —— checkpoint 关联与安全检查。

设计原则（来自 RFC Sec 3 / SDD Sec 7）：
- checkpoint 关联 in-flight Skill invocation
- resume 不重放 side effects
- checkpoint 不保存 secrets
- checkpoint 不保存完整大型 Skill body/resources
- interrupted invocation 不能 bypass confirmation
- resume 不重复 high-risk tool execution
- Runtime 拥有 loop
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from agent.skill_system.descriptor import SkillDescriptor

# OpenAI / GitHub / Slack / AWS key patterns
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"ghu_[A-Za-z0-9]{20,}"),
    re.compile(r"ghs_[A-Za-z0-9]{20,}"),
    re.compile(r"ghr_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[bpras]-[A-Za-z0-9-]+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"),
)
_MAX_BODY_SIZE = 50_000


@dataclass(frozen=True)
class SkillCheckpointCorrelation:
    """in-flight Skill invocation 的 checkpoint 关联元数据。

    不含 body、不含 resource 内容、不含 secret。
    """

    skill_name: str
    skill_version: str
    audit_id: str
    loaded_level: int = 0
    loaded_resources: tuple[str, ...] = ()
    pending_confirmation: bool = False
    invocation_status: str = "in_flight"


def build_invocation_checkpoint_note(
    descriptor: SkillDescriptor,
    audit_id: str,
    loaded_level: int,
    invocation_status: str,
) -> str:
    """从 descriptor 和 invocation params 构建 checkpoint note 字符串。"""
    return (
        f"Skill: {descriptor.name} v{descriptor.version} "
        f"audit={audit_id} level={loaded_level} "
        f"status={invocation_status}"
    )


def _contains_secret(data: object) -> bool:
    """递归检查 data 中是否包含疑似 secret 的模式。"""
    if isinstance(data, str):
        for pattern in _SECRET_PATTERNS:
            if pattern.search(data):
                return True
        return False
    if isinstance(data, dict):
        return any(_contains_secret(v) for v in data.values())
    if isinstance(data, (list, tuple)):
        return any(_contains_secret(v) for v in data)
    return False


def _contains_large_body(data: object) -> bool:
    """检查 data 中是否包含超过阈值的 body/resource 内容。"""
    if isinstance(data, str) and len(data) >= _MAX_BODY_SIZE:
        return True
    if isinstance(data, dict):
        return any(_contains_large_body(v) for v in data.values())
    if isinstance(data, (list, tuple)):
        return any(_contains_large_body(v) for v in data)
    return False


def is_checkpoint_safe(data: dict[str, object]) -> bool:
    """检查 checkpoint data 是否安全（不含 secret、不含超大 body）。"""
    if _contains_secret(data):
        return False
    if _contains_large_body(data):
        return False
    return True
