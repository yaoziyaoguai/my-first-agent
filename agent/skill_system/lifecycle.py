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
        # B7: per-session model_selected flag，替代 core._skill_selected_by_model 模块单例。
        self._model_selected: bool = False

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

    # ── B7 model_selected flag ───────────────────────────────────────────

    def set_model_selected(self) -> None:
        """标记本轮模型已通过 tool_use 选择 Skill。"""
        self._model_selected = True

    def was_model_selected(self) -> bool:
        """检查本轮模型是否已通过 tool_use 选择 Skill 并消费该标记。"""
        return self._model_selected

    def consume_model_selected(self) -> bool:
        """检查并重置 model_selected 标记（turn-end hook 消费）。"""
        was = self._model_selected
        self._model_selected = False
        return was

    # ── checkpoint support ──────────────────────────────────────────────

    def to_checkpoint_metadata(self) -> dict:
        """返回 checkpoint-safe active skill metadata（不含 body/raw 内容）。

        checkpoint 路径必须使用此 API；不得使用 to_dict() 作为 checkpoint contract。
        返回字段仅包含：skill_id、allowed_tools、activated_by、activated_at、namespace。
        """
        if self._active is None:
            return {}
        return {
            "skill_id": self._active.skill_id,
            "allowed_tools": list(self._active.allowed_tools),
            "activated_by": self._active.activated_by,
            "activated_at": self._active.activated_at,
            "namespace": self._namespace,
        }

    def restore_from_checkpoint_metadata(
        self,
        skill_id: str,
        body: str,
        allowed_tools: tuple[str, ...],
        activated_at: float | None = None,
        activated_by: str = "checkpoint_resume",
    ) -> ActiveSkill:
        """apply-only restore：使用已 validate/load 的 body 和当前 manifest allowed_tools。

        调用方必须先通过 SkillLoader.load_body() 加载完整 body，
        并从当前 descriptor/manifest 获取 allowed_tools（不盲信 checkpoint 旧值）。
        本方法只做 activate，不做 validate/load/fallback。
        """
        skill = ActiveSkill(
            skill_id=skill_id,
            body=body,
            allowed_tools=allowed_tools,
            activated_at=activated_at if activated_at is not None else time.time(),
            activated_by=activated_by,
        )
        self._active = skill
        return skill

    # to_dict() / restore_from_dict() 保留用于向后兼容和测试，
    # 不作为 checkpoint contract。checkpoint 路径必须使用
    # to_checkpoint_metadata() / restore_from_checkpoint_metadata()。
    def to_dict(self) -> dict:
        """序列化为 dict（向后兼容/测试用；不作为 checkpoint contract）。"""
        if self._active is None:
            return {}
        return {
            "skill_id": self._active.skill_id,
            "body": self._active.body[:500],  # 截断长 body（仅供测试/兼容）
            "allowed_tools": list(self._active.allowed_tools),
            "activated_at": self._active.activated_at,
            "activated_by": self._active.activated_by,
            "namespace": self._namespace,
        }

    def restore_from_dict(self, data: dict) -> None:
        """从 dict 恢复 active_skill 状态（向后兼容/测试用；不作为 checkpoint contract）。"""
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
# B7: _lifecycle_registry 提供 per-session namespace 隔离。
_lifecycle_registry: dict[str, ActiveSkillLifecycle] = {}
_default_lifecycle = ActiveSkillLifecycle()
# 向后兼容：_default_lifecycle 仍可被无参 get_default_lifecycle() 访问，
# 对应 "default" namespace。


def get_default_lifecycle(session_id: str = "default") -> ActiveSkillLifecycle:
    """获取指定 session 的 ActiveSkillLifecycle 实例。

    B7: 支持 per-session namespace 隔离。
    - session_id="default"（默认）→ 返回模块级 _default_lifecycle（向后兼容）
    - session_id 非 "default" → 从 _lifecycle_registry 查找/创建独立 lifecycle
    """
    if session_id == "default":
        return _default_lifecycle
    if session_id not in _lifecycle_registry:
        _lifecycle_registry[session_id] = ActiveSkillLifecycle(namespace=session_id)
    return _lifecycle_registry[session_id]


def reset_default_lifecycle() -> None:
    """重置默认 lifecycle 和所有 per-session lifecycle（测试用）。"""
    global _default_lifecycle
    _default_lifecycle = ActiveSkillLifecycle()
    _lifecycle_registry.clear()
