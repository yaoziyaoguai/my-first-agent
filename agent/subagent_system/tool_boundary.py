"""SubAgent ToolRegistry boundary.

该模块只做权限检查和 metadata snapshot。它不执行工具，也不降低 ToolRegistry
风险/确认要求；真正执行必须仍由 Parent Runtime / ToolExecutor 负责。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agent.subagent_system.result import ToolSnapshot


@dataclass(frozen=True)
class ToolCheckResult:
    allowed: bool
    tool_name: str
    risk_level: str = "unknown"
    requires_confirmation: bool = False
    deny_reason: str | None = None


class SubAgentToolBoundary:
    def __init__(self, tool_registry: Mapping[str, Mapping[str, Any]]) -> None:
        self._tool_registry = tool_registry

    def check(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        descriptor: object,
        request: object,
    ) -> ToolCheckResult:
        del arguments  # Phase 6 validates authority, not argument semantics.
        entry = self._tool_registry.get(tool_name)
        if entry is not None and (
            bool(entry.get("meta_tool", False)) or bool(entry.get("is_hidden", False))
        ):
            return ToolCheckResult(False, tool_name, deny_reason="hidden_tool")
        effective = set(getattr(descriptor, "allowed_tools", ())) & set(
            getattr(request, "allowed_tools", ())
        )
        if tool_name not in effective:
            return ToolCheckResult(False, tool_name, deny_reason="tool_not_allowed")
        if entry is None:
            return ToolCheckResult(False, tool_name, deny_reason="unknown_tool")
        confirmation = entry.get("confirmation")
        return ToolCheckResult(
            allowed=True,
            tool_name=tool_name,
            risk_level=str(entry.get("risk_level", "medium")),
            requires_confirmation=confirmation == "always" or callable(confirmation),
        )

    def snapshot(self, descriptor: object, request: object) -> tuple[ToolSnapshot, ...]:
        """Return model-visible tool metadata after hidden and upper-bound filters."""

        snapshots: list[ToolSnapshot] = []
        effective = sorted(
            set(getattr(descriptor, "allowed_tools", ()))
            & set(getattr(request, "allowed_tools", ()))
        )
        for tool_name in effective:
            entry = self._tool_registry.get(tool_name)
            if (
                entry is None
                or bool(entry.get("meta_tool", False))
                or bool(entry.get("is_hidden", False))
            ):
                continue
            confirmation = entry.get("confirmation")
            snapshots.append(
                ToolSnapshot(
                    name=tool_name,
                    description=str(entry.get("description", "")),
                    risk_level=str(entry.get("risk_level", "medium")),
                    requires_confirmation=confirmation == "always" or callable(confirmation),
                    is_hidden=False,
                )
            )
        return tuple(snapshots)
