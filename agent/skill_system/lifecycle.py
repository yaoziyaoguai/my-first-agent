"""Runtime-managed active_skill lifecycle — Plan 3 核心差异化能力。

ActiveSkillLifecycle 提供跨 turn 持久化的 active_skill 状态管理：
- activate/deactivate/switch 语义明确
- 跨 turn 保持（multi-turn until task complete）
- B7 extension point: namespace 参数预留（Phase 7 前默认为 "default"）
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ActiveSkill:
    """当前激活的 Skill 不可变快照。"""

    skill_id: str
    body: str
    allowed_tools: tuple[str, ...]
    activated_at: float  # time.time()
    activated_by: str  # "model_selection" | "keyword_fallback" | "cli_command"


class ActiveSkillLifecycle:
    """Runtime-managed active_skill lifecycle。

    Plan 3 核心——跨 turn 持久化的 active_skill 状态管理。
    每个 core.chat() 实例持有一个 lifecycle，通过 module-level 默认实例
    实现跨 turn 状态保持。

    B7 extension point: namespace 参数预留（Phase 7 前默认为 "default"）。
    """

    def __init__(self, namespace: str = "default") -> None:
        self._active: ActiveSkill | None = None
        self._namespace = namespace

    # ── public API ──────────────────────────────────────────────────────

    def activate(
        self,
        skill_id: str,
        body: str,
        allowed_tools: tuple[str, ...] = (),
        activated_by: str = "model_selection",
    ) -> ActiveSkill:
        """激活一个 Skill，覆盖当前 active_skill。

        deactivate 条件（由调用方负责触发）：
        - task complete
        - 模型选择新 skill（switch）
        - 用户显式取消
        - checkpoint resume 清除
        """
        skill = ActiveSkill(
            skill_id=skill_id,
            body=body,
            allowed_tools=allowed_tools,
            activated_at=time.time(),
            activated_by=activated_by,
        )
        self._active = skill
        return skill

    def deactivate(self) -> None:
        """清除当前 active_skill。"""
        self._active = None

    def switch(
        self,
        skill_id: str,
        body: str,
        allowed_tools: tuple[str, ...] = (),
        activated_by: str = "model_selection",
    ) -> ActiveSkill:
        """切换到新 Skill（deactivate + activate）。"""
        self.deactivate()
        return self.activate(skill_id, body, allowed_tools, activated_by)

    def is_active(self) -> bool:
        """当前是否有激活的 Skill。"""
        return self._active is not None

    def get_active(self) -> ActiveSkill | None:
        """获取当前 active_skill 快照，无则返回 None。"""
        return self._active

    def get_active_skill_id(self) -> str | None:
        """获取当前 skill_id，无则返回 None。"""
        if self._active is not None:
            return self._active.skill_id
        return None

    def get_allowed_tools(self) -> frozenset[str]:
        """获取当前 active_skill 的 allowed_tools。

        无 active_skill 时返回空 frozenset——表示无约束（所有工具可用）。
        """
        if self._active is not None:
            return frozenset(self._active.allowed_tools)
        return frozenset()

    # ── B7 extension point (Phase 7) ────────────────────────────────────

    @property
    def namespace(self) -> str:
        """B7 extension point: 返回当前 namespace。

        Phase 7 前固定为 "default"。B7 实现 multi-instance namespace 后，
        每个 sub-agent instance 可有独立 namespace 的 lifecycle。
        """
        return self._namespace

    def activate_in_namespace(
        self,
        namespace: str,
        skill_id: str,
        body: str,
        allowed_tools: tuple[str, ...] = (),
        activated_by: str = "model_selection",
    ) -> ActiveSkill:
        """B7 extension point: 在指定 namespace 中激活 Skill。

        Phase 7 前 namespace 参数被接受但忽略——始终使用默认 namespace。
        B7 实现后此方法将创建/切换到指定 namespace 的 lifecycle。
        """
        # Phase 7 前忽略 namespace 参数
        _ = namespace
        return self.activate(skill_id, body, allowed_tools, activated_by)

    # ── checkpoint support ──────────────────────────────────────────────

    def to_dict(self) -> dict:
        """序列化为可持久化 dict（checkpoint save 用）。"""
        if self._active is None:
            return {}
        return {
            "skill_id": self._active.skill_id,
            "body": self._active.body[:500],  # checkpoint 截断长 body
            "allowed_tools": list(self._active.allowed_tools),
            "activated_at": self._active.activated_at,
            "activated_by": self._active.activated_by,
            "namespace": self._namespace,
        }

    def restore_from_dict(self, data: dict) -> None:
        """从 checkpoint dict 恢复 active_skill 状态。"""
        if not data or "skill_id" not in data:
            self._active = None
            return
        self._active = ActiveSkill(
            skill_id=data["skill_id"],
            body=data.get("body", ""),
            allowed_tools=tuple(data.get("allowed_tools", ())),
            activated_at=data.get("activated_at", time.time()),
            activated_by=data.get("activated_by", "checkpoint_resume"),
        )


# 模块级默认 lifecycle 实例——跨 turn 状态保持。
# core.py 通过此实例访问 active_skill 状态。
_default_lifecycle = ActiveSkillLifecycle()


def get_default_lifecycle() -> ActiveSkillLifecycle:
    """获取模块级默认 ActiveSkillLifecycle 实例。"""
    return _default_lifecycle


def reset_default_lifecycle() -> None:
    """重置默认 lifecycle（测试用）。"""
    global _default_lifecycle
    _default_lifecycle = ActiveSkillLifecycle()
