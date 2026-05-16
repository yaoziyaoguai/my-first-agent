"""Quarantined legacy / experimental Skill prototype package.

本包不是正式 Skill System，也不代表未来稳定 API。正式 Skill System 使用
`agent/skill_system/`，当前 `agent.legacy_skills` 代码只作为历史参考和显式
迁移材料保留。

隔离边界：
- 默认工具注册路径不应自动启用 Skill lifecycle tools。
- installer 包含真实网络 / git clone / pip install / 文件写入风险，只能在
  explicit opt-in 和用户确认后使用。
- 正式 `agent/skill_system/` 不得 import 本包；未来迁移必须有单独批准的
  migration phase。
"""

__all__: list[str] = []
