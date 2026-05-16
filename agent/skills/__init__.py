"""Removed Skill prototype tombstone.

本包只保留历史 import path 的空壳，避免旧 `agent.skills` prototype 继续被
误认为正式 Skill System。正式实现必须使用 `agent/skill_system/`，不能从这里
导入 registry、loader、installer 或 local MVP helper。

旧实现已经隔离到 `agent/legacy_skills/`，仅作历史参考和显式迁移材料；默认
工具注册、prompt 构造和正式 Skill 实现都不得依赖它。
"""

__all__: list[str] = []
