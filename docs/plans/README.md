# 计划文档索引 (Plans Index)

本目录包含 my-first-agent 的计划文档。

**分类规则**：
- **Active（当前）**：当前阶段唯一行动入口
- **Completed（已完成）**：已执行完毕的计划，保留为证据
- **Historical（历史）**：过去特定能力的实现计划，保留为历史证据

> **AutoRun 规则**：只以 Active 计划为当前行动入口。Completed/Historical plans 是实现证据，不驱动新能力建设。Archived plans（`docs/archive/`）不参与 AutoRun discovery。当前 AutoRun 模式为 cleanup/source-of-truth only，不新增 capability。

## Active Plan (当前唯一行动入口)

| 文档 | 日期 | 范围 | 用途 |
|------|------|------|------|
| [final-cleanup-readiness-summary-2026-05-25.md](final-cleanup-readiness-summary-2026-05-25.md) | 2026-05-25 | 最终收口 readiness 总结 | **当前权威行动入口** — manual human dogfood 是最优先下一步；能力建设暂停 |

## Completed Plans (已执行完毕)

| 文档 | 日期 | 范围 | 状态 |
|------|------|------|------|
| [low-complexity-capability-remediation-summary-2026-05-25.md](low-complexity-capability-remediation-summary-2026-05-25.md) | 2026-05-25 | Capability Gap Audit 后的 low-complexity 补齐总结 | **已完成** — 6 项 safe-to-auto-run 补齐 |
| [post-red-team-cleanup-remediation-plan-2026-05-25.md](post-red-team-cleanup-remediation-plan-2026-05-25.md) | 2026-05-25 | PF-01 到 PF-15 cleanup 修复 | **已完成** — cleanup-only remediation |
| [global-red-team-remediation-plan-2026-05-25.md](global-red-team-remediation-plan-2026-05-25.md) | 2026-05-25 | RT-01 到 RT-18 全量修复 | **已完成** — 第一轮 6 phases committed |

## Reference (参考文档，非执行计划)

| 文档 | 日期 | 范围 | 用途 |
|------|------|------|------|
| [first-agent-subsystem-integration-roadmap.md](first-agent-subsystem-integration-roadmap.md) | — | 子系统集成 roadmap | AutoRun queue 定义（当前仅 cleanup/slimming 模式） |
| [documentation-source-of-truth-reset-2026-05-26.md](documentation-source-of-truth-reset-2026-05-26.md) | 2026-05-26 | 文档 source-of-truth reset 盘点 | 归档操作参考（已完成） |

## Historical Plans (已完成或已冻结，保留为证据)

| 文档 | 日期 | 范围 | 状态 |
|------|------|------|------|
| [user-usable-agent-runtime-issue-sweep.md](user-usable-agent-runtime-issue-sweep.md) | — | 用户可用性 issue sweep | Historical — 已由 Big Loop 审计覆盖 |
| [user-usable-agent-runtime-mvp-plan.md](user-usable-agent-runtime-mvp-plan.md) | — | MVP 计划 | Historical — MVP 能力已交付 |
| [2026-05-21-001-feat-memory-anchor-fake-plan.md](2026-05-21-001-feat-memory-anchor-fake-plan.md) | 2026-05-21 | Memory Anchor (Fake) | Historical — Memory 主线已完成 |
| [2026-05-21-002-feat-memory-anchor-hook-param-plan.md](2026-05-21-002-feat-memory-anchor-hook-param-plan.md) | 2026-05-21 | Memory Anchor Hook Param | Historical |
| [2026-05-22-001-feat-memory-anchor-real-smoke-plan.md](2026-05-22-001-feat-memory-anchor-real-smoke-plan.md) | 2026-05-22 | Memory Anchor Real Smoke | Historical |
| [2026-05-22-002-feat-tool-confirmation-anchor-plan.md](2026-05-22-002-feat-tool-confirmation-anchor-plan.md) | 2026-05-22 | Tool Confirmation Anchor | Historical |
| [2026-05-22-003-global-runtime-flow-remediation-plan.md](2026-05-22-003-global-runtime-flow-remediation-plan.md) | 2026-05-22 | Global Runtime Flow Remediation | Historical — 已由统一 runtime flow 取代 |

## 读者路径

- **当前该做什么** → [final-cleanup-readiness-summary-2026-05-25.md](final-cleanup-readiness-summary-2026-05-25.md) — manual human dogfood 是最优先下一步
- **当前能力状态** → [CURRENT_CAPABILITY_STATUS.zh.md](../00-overview/CURRENT_CAPABILITY_STATUS.zh.md)
- **当前审计状态** → [CURRENT_AUDIT_STATUS.zh.md](../06-audit/CURRENT_AUDIT_STATUS.zh.md)
- **低复杂度补齐结果** → [low-complexity-capability-remediation-summary-2026-05-25.md](low-complexity-capability-remediation-summary-2026-05-25.md)（已完成）
- **第一轮 remediation 历史** → [global-red-team-remediation-plan-2026-05-25.md](global-red-team-remediation-plan-2026-05-25.md)（已完成，证据保留）
- **AutoRun queue 定义** → [first-agent-subsystem-integration-roadmap.md](first-agent-subsystem-integration-roadmap.md)
- **历史实现证据** → Historical 部分，保留为实现证据链，不作为行动源
