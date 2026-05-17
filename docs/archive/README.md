# Archive Policy

这篇文档解决什么问题：说明哪些文档属于历史记录，以及为什么本轮没有机械搬运所有旧文档。

不解决什么问题：不列出每个历史 commit，也不删除旧文档。

推荐读者：维护者、文档审计者、准备清理历史文档的 Coding Agent。

## Policy

本轮不大规模移动旧文档，原因是很多旧报告仍被 release notes、审计证据或代码注释引用。为避免破坏引用，采用两层策略：

1. 新入口统一放在 `docs/README.zh.md`、`docs/00-overview/`、`docs/01-getting-started/`、`docs/05-testing-dogfood/`、`docs/06-audit/`。
2. 历史长文保留原路径，但不再作为用户入口；必要时在文档顶部标注 superseded 状态。

## Historical by default

以下类别默认视为历史证据，不作为当前入口：

- `docs/V0_*`
- `docs/*_SMOKE_*`
- `docs/*_TRIAL_*`
- `docs/*_RELEASE_*`
- `docs/ROADMAP_LEGACY.md`
- `docs/review/*`
- 根目录 `RELEASE_NOTES_*.md`

## Canonical, do not archive casually

- `docs/rfc/MEMORY_CANONICAL_RFC.md`
- `docs/rfc/SKILL_CANONICAL_RFC.md`
- `docs/rfc/SUBAGENT_CANONICAL_RFC.md`
- `docs/design/SKILL_SYSTEM_SDD.md`
- `docs/design/SUBAGENT_SYSTEM_SDD.md`
- `docs/testing/SKILL_SYSTEM_TDD.md`
- `docs/testing/SUBAGENT_SYSTEM_TDD.md`
- `docs/roadmap/SKILL_SYSTEM_IMPLEMENTATION_LOOP.md`
- `docs/roadmap/SUBAGENT_IMPLEMENTATION_LOOP.md`
- `docs/audit/SKILL_SYSTEM_AUDIT_CHECKLIST.md`
- `docs/audit/SUBAGENT_AUDIT_CHECKLIST.md`
