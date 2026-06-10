"""Removed Skill prototype tombstone.

本包只保留历史 import path 的空壳，避免旧 `agent.skills` prototype 继续被
误认为正式 Skill System。正式实现必须使用 `agent/skill_system/`，不能从这里
导入 registry、loader、installer 或 local MVP helper。

历史隔离目标 `agent/legacy_skills/` **当前不存在**——tombstone 只保留
"stale historical target"的指代，不对应任何活跃代码路径。任何 `import
agent.legacy_skills` 都会 ImportError，符合 quarantine 的语义。
"""

__all__: list[str] = []
