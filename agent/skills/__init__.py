"""Legacy / experimental Skill prototype package.

本包不是正式 Skill System，也不代表未来稳定 API。正式 Skill System
应以后续 `SKILL_CANONICAL_RFC.md` 为准，当前 `agent.skills` 代码只作为
legacy prototype / 参考基线保留。

冻结边界：
- 默认工具注册路径不应自动启用 Skill lifecycle tools。
- installer 包含真实网络 / git clone / pip install / 文件写入风险，只能在
  explicit opt-in 和用户确认后使用。
- 在正式 RFC / SDD / TDD 完成前，不从本包顶层导出 registry、loader 或
  installer API，避免把 prototype 误当稳定契约。
"""

__all__: list[str] = []
