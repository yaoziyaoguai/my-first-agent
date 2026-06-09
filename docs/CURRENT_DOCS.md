# Current Documentation Map

**最后更新**: 2026-06-10
**用途**: 给人类维护者和 Coding Agent 一个短的当前文档地图。

## Start Here

| 文档 | 状态 | 用途 |
|---|---|---|
| [PROJECT_STATUS.md](PROJECT_STATUS.md) | current source of truth | 当前实现地图、边界、授权状态 |
| [00-overview/CURRENT_CAPABILITY_STATUS.zh.md](00-overview/CURRENT_CAPABILITY_STATUS.zh.md) | current summary | 当前能做什么、不能做什么 |
| [06-audit/CURRENT_AUDIT_STATUS.zh.md](06-audit/CURRENT_AUDIT_STATUS.zh.md) | current audit entry | 审计口径和冻结项 |
| [dev/AUTO_RUN_WORKFLOW.md](dev/AUTO_RUN_WORKFLOW.md) | workflow | 自动化工程流程 |
| [PROGRESS_LEDGER.md](PROGRESS_LEDGER.md) | historical ledger | 历史里程碑追溯 |

## Current Implementation Docs

| 领域 | 当前参考 |
|---|---|
| Runtime flow | [real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md](real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md) |
| Memory | [rfc/MEMORY_CANONICAL_RFC.md](rfc/MEMORY_CANONICAL_RFC.md) |
| Skill | [rfc/SKILL_CANONICAL_RFC.md](rfc/SKILL_CANONICAL_RFC.md), [design/skill-system-architecture.md](design/skill-system-architecture.md) |
| SubAgent | [rfc/SUBAGENT_CANONICAL_RFC.md](rfc/SUBAGENT_CANONICAL_RFC.md), [design/subagent-boundary-architecture.md](design/subagent-boundary-architecture.md) |
| MCP | [design/mcp-architecture.md](design/mcp-architecture.md) |
| Config | [design/config-legacy-sunset-contract.md](design/config-legacy-sunset-contract.md), [design/unified-project-config-contract.md](design/unified-project-config-contract.md) |
| FakeProvider | [design/fake-provider-scripted-scenario-contract.md](design/fake-provider-scripted-scenario-contract.md) |

## Historical Areas

这些目录保留历史证据或旧计划，不能作为当前执行依据：

- [archive/README.md](archive/README.md)
- [audits/](audits/)
- [releases/](releases/)
- [reviews/](reviews/)
- [handoff/](handoff/)
- 旧 TUI/B7/B8 计划和 closeout 文档

## Agent Rules

- 如果 `PROJECT_STATUS.md` 与其他文档冲突，以 `PROJECT_STATUS.md` 为准。
- 不把 dogfood、旧 closeout 或 archive 文档当成当前 backlog。
- 不恢复旧 L1/L2 production route。
- 不恢复 direct tool/MCP execution。
- 不新增 raw memory write、auto-adoption 或第二 runtime。
- 文档清理时优先删除旧上下文；代码删除必须先做引用和测试证明。
