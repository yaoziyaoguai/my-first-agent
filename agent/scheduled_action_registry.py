"""G-044a: Safety-gated scheduled-action visibility + NO-OP/report-only.

学习型说明：
这是一个 **可视化 + 报告层**，不是自动执行器。它只允许：
- 创建 NO-OP/report-only scheduled action（描述 + 类型，不绑定任何危险回调）
- 列出/查询/取消 scheduled action（operator 可见性）
- 触发 NO-OP/report-only fire（记录 evidence，不执行任何 tool/memory/subagent）

明确不允许：
- 定时执行 tool/memory/subagent（future autonomy，需 safety gate G-031）
- 自动重复/递归 fire
- 任何网络/文件/shell 副作用

这是 FirstAgent Scheduler 产品化的第一步：operator 可见 "什么被调度了"，
但不给 agent 自主执行能力。scheduling ≠ workflows ≠ approval。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class ScheduledAction:
    """一个 scheduled action 记录（NO-OP/report-only only）。"""

    action_id: str
    description: str
    action_type: str  # "no_op" | "report"
    status: str  # "pending" | "fired" | "cancelled"
    created_at: float
    fired_at: float | None = None
    cancelled_at: float | None = None


class ScheduledActionRegistry:
    """In-memory scheduled-action registry (visibility + NO-OP, no execution)."""

    def __init__(self) -> None:
        self._actions: dict[str, ScheduledAction] = {}

    def create(
        self, description: str, *, action_type: str = "no_op"
    ) -> ScheduledAction:
        """Create a NO-OP/report-only scheduled action (no execution binding)."""
        if action_type not in ("no_op", "report"):
            raise ValueError(
                f"action_type must be 'no_op' or 'report' (safety: no execution); "
                f"got {action_type!r}"
            )
        action = ScheduledAction(
            action_id=uuid4().hex[:12],
            description=description,
            action_type=action_type,
            status="pending",
            created_at=time.time(),
        )
        self._actions[action.action_id] = action
        return action

    def list_actions(self) -> tuple[ScheduledAction, ...]:
        """List all scheduled actions (operator visibility)."""
        return tuple(self._actions.values())

    def get(self, action_id: str) -> ScheduledAction | None:
        """Get a scheduled action by id."""
        return self._actions.get(action_id)

    def cancel(self, action_id: str) -> bool:
        """Cancel a pending scheduled action (graceful cancel, not terminate)."""
        action = self._actions.get(action_id)
        if action is None or action.status != "pending":
            return False
        self._actions[action_id] = ScheduledAction(
            action_id=action.action_id,
            description=action.description,
            action_type=action.action_type,
            status="cancelled",
            created_at=action.created_at,
            cancelled_at=time.time(),
        )
        return True

    def fire_noop(self, action_id: str) -> str:
        """Fire a NO-OP/report-only action: records evidence, executes NOTHING.

        Returns a human-readable result string. Never executes tools/memory/
        subagent. This is the safety-gated "fire" — it proves the action lifecycle
        (create -> pending -> fire -> evidence) without any side effects.
        """
        action = self._actions.get(action_id)
        if action is None:
            return f"[scheduled] not found: {action_id}"
        if action.status != "pending":
            return f"[scheduled] cannot fire (status={action.status}): {action_id}"
        self._actions[action_id] = ScheduledAction(
            action_id=action.action_id,
            description=action.description,
            action_type=action.action_type,
            status="fired",
            created_at=action.created_at,
            fired_at=time.time(),
        )
        return (
            f"[scheduled] NO-OP fired: {action.action_id} "
            f"(type={action.action_type}, desc={action.description[:60]}) "
            f"— no tool/memory/subagent executed."
        )


# Module-level singleton for the CLI surface (tests can create their own).
_registry = ScheduledActionRegistry()


def get_registry() -> ScheduledActionRegistry:
    """Get the module-level registry singleton."""
    return _registry


def format_action_list(actions: tuple[ScheduledAction, ...]) -> str:
    """Format scheduled actions for operator display."""
    if not actions:
        return "No scheduled actions.\n"
    lines = [
        f"{'ID':<14} {'Type':<8} {'Status':<10} {'Description'}",
        "-" * 60,
    ]
    for a in actions:
        lines.append(
            f"{a.action_id:<14} {a.action_type:<8} {a.status:<10} {a.description[:40]}"
        )
    return "\n".join(lines) + "\n"
