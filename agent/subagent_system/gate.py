"""S3 SubAgent governed-active default-off gate（S3-G04）。

SubAgent 的 **read-only / audit-first / parent-mediated** 委派是 S3 推进的
governed-active capability。激活必须**显式 opt-in（default-off）**，与 Skill gate
（`agent/skill_system/gate.py`，`MY_FIRST_AGENT_S2_SKILL_ENABLE`）和 MCP gate
（`MY_FIRST_AGENT_MCP_ENABLE`）同一语义：默认关闭、可禁用、opt-in 值一致（1/true/yes/on）。

被 `select_execution_mode`（governed-active 模式）与统一 capability 契约
（`agent.subagent_capability.SUBAGENT_CAPABILITY` → `evaluate_activation`）共同消费。
"""
from __future__ import annotations

import os
from collections.abc import Mapping

SUBAGENT_ENABLE_ENV = "MY_FIRST_AGENT_S3_SUBAGENT_ENABLE"
_ENABLED_VALUES = frozenset({"1", "true", "yes", "on"})


def is_subagent_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Return whether S3 SubAgent governed-active activation is explicitly enabled."""

    source = os.environ if env is None else env
    return str(source.get(SUBAGENT_ENABLE_ENV, "")).strip().lower() in _ENABLED_VALUES


def disabled_reason() -> str:
    return f"{SUBAGENT_ENABLE_ENV} is not enabled"
