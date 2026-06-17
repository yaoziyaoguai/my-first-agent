"""S2 Skill activation gate.

Skill is the selected S2 L5 candidate, but activation must stay explicit and
reversible. This module centralizes the default-off switch so prompt exposure,
tool registration, and direct runtime actions share the same decision.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

S2_SKILL_ENABLE_ENV = "MY_FIRST_AGENT_S2_SKILL_ENABLE"
_ENABLED_VALUES = frozenset({"1", "true", "yes", "on"})


def is_s2_skill_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Return whether S2 Skill activation is explicitly enabled."""

    source = os.environ if env is None else env
    return str(source.get(S2_SKILL_ENABLE_ENV, "")).strip().lower() in _ENABLED_VALUES


def disabled_reason() -> str:
    return f"{S2_SKILL_ENABLE_ENV} is not enabled"
