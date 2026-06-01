"""Skill 运行时状态——打破 agent.core ↔ agent.loop/agent.skill_system.skill_tool 双向依赖。

提取前，loop 和 skill_tool 都必须 local import agent.core 访问
`_skill_selected_by_model` 和 `_active_skill`，形成两对直接模块循环。
提取后，三者共享 import 本模块，无循环依赖。

Warning:
    本模块是 minimal extraction——只承载被多模块共享的 flag/state。
    不要在这里加 business logic、dispatcher、tool registry 或 lifecycle。
    如果未来需要更复杂的 skill state management，应迁移到 skill_system/ 下。
"""

from __future__ import annotations

# REAL-EVIDENCE-002: 模型自主选择 Skill 标志。
# - True: 模型在本 turn 通过 tool_use("SKILL_SELECT", ...) 选择了 skill，
#   turn-end hook 检查此 flag 跳过 keyword fallback
# - False: 初始状态 / 关键字 fallback 已执行 / turn-end 已消费
_skill_selected_by_model: bool = False

# 向后兼容 dict——写入 lifecycle 后同步到此 dict。
# 新增代码应使用 agent.skill_system.lifecycle.ActiveSkillLifecycle。
_active_skill: dict[str, str] = {}


def get_skill_selected_by_model() -> bool:
    """返回 _skill_selected_by_model flag（供 loop turn-end hook 读取）。"""
    return _skill_selected_by_model


def set_skill_selected_by_model(value: bool) -> None:
    """设置 _skill_selected_by_model flag（供 skill_tool / keyword fallback 写入）。"""
    global _skill_selected_by_model
    _skill_selected_by_model = value


def get_active_skill() -> dict[str, str]:
    """返回向后兼容的 _active_skill dict（供 skill_tool 写入、外部读取）。"""
    return _active_skill


def set_active_skill(skill: dict[str, str]) -> None:
    """替换 _active_skill dict 内容（供 _update_active_skill_from_dispatcher 写入）。

    通过 clear + update 而非直接赋值，保证已有引用（如 core.py 的模块级别名）
    仍指向正确的 dict 对象。
    """
    _active_skill.clear()
    _active_skill.update(skill)
