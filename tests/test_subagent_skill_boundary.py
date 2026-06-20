"""SubAgent Phase 7: Skill Boundary tests."""

from __future__ import annotations

from dataclasses import dataclass

from agent.subagent_system.descriptor import SubAgentDescriptor
from agent.subagent_system.skill_boundary import SubAgentSkillBoundary


@dataclass(frozen=True)
class _SkillDescriptor:
    name: str
    description: str
    tags: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    memory_scope: str = "none"


class _SkillSystem:
    def __init__(self) -> None:
        self._items = {
            "review-skill": _SkillDescriptor(
                "review-skill", "Review safely", ("review",), ("read_file",)
            ),
        }

    def get_descriptor(self, name: str) -> _SkillDescriptor | None:
        return self._items.get(name)


def test_skill_boundary_returns_l1_metadata_only_for_allowed_skill() -> None:
    """SubAgent 只能得到 Skill L1 metadata；full body loading 仍由 Skill System 管。"""

    descriptor = SubAgentDescriptor(
        name="reviewer",
        description="Review",
        role="reviewer",
        allowed_skills=("review-skill",),
    )
    boundary = SubAgentSkillBoundary(_SkillSystem())

    result = boundary.check("review-skill", descriptor)

    assert result.allowed is True
    assert result.l1_metadata is not None
    assert result.l1_metadata.name == "review-skill"
    assert not hasattr(result.l1_metadata, "body")


def test_skill_boundary_blocks_skill_outside_upper_bound() -> None:
    """allowed_skills 是上限，SubAgent 不能临时选择未授权 Skill。"""

    descriptor = SubAgentDescriptor(name="reviewer", description="Review", role="reviewer")
    boundary = SubAgentSkillBoundary(_SkillSystem())

    result = boundary.check("review-skill", descriptor)

    assert result.allowed is False
    assert result.deny_reason == "skill_not_allowed"

