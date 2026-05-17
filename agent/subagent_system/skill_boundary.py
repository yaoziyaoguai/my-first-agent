"""SubAgent Skill boundary."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillL1Metadata:
    """SubAgent-visible Skill metadata; deliberately excludes body/resources."""

    name: str
    description: str
    tags: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    memory_scope: str = "none"


@dataclass(frozen=True)
class SkillCheckResult:
    allowed: bool
    skill_name: str
    l1_metadata: SkillL1Metadata | None = None
    deny_reason: str | None = None


class SubAgentSkillBoundary:
    """Delegates Skill lookup to Skill System without loading full bodies."""

    def __init__(self, skill_system: object) -> None:
        self._skill_system = skill_system

    def check(self, skill_name: str, descriptor: object) -> SkillCheckResult:
        if skill_name not in getattr(descriptor, "allowed_skills", ()):
            return SkillCheckResult(False, skill_name, deny_reason="skill_not_allowed")
        get_descriptor = getattr(self._skill_system, "get_descriptor", None)
        skill_descriptor = get_descriptor(skill_name) if callable(get_descriptor) else None
        if skill_descriptor is None:
            return SkillCheckResult(False, skill_name, deny_reason="skill_not_found")
        return SkillCheckResult(
            True,
            skill_name,
            l1_metadata=SkillL1Metadata(
                name=getattr(skill_descriptor, "name"),
                description=getattr(skill_descriptor, "description"),
                tags=tuple(getattr(skill_descriptor, "tags", ())),
                allowed_tools=tuple(getattr(skill_descriptor, "allowed_tools", ())),
                memory_scope=getattr(skill_descriptor, "memory_scope", "none"),
            ),
        )

