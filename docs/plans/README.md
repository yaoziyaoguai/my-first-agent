# 计划文档索引 (Plans Index)

本目录包含 my-first-agent 的计划文档。计划类型分两种：
- **Active（当前执行中）**：最新计划，覆盖当前阶段行动
- **Historical（历史）**：过去特定能力的实现计划，保留为历史证据

## Active Plans

| 文档 | 日期 | 范围 | 用途 |
|------|------|------|------|
| [post-red-team-cleanup-remediation-plan-2026-05-25.md](post-red-team-cleanup-remediation-plan-2026-05-25.md) | 2026-05-25 | PF-01 到 PF-15 cleanup 修复 | **当前执行中** — Cleanup-Only Remediation Big Loop |
| [global-red-team-remediation-plan-2026-05-25.md](global-red-team-remediation-plan-2026-05-25.md) | 2026-05-25 | RT-01 到 RT-18 全量修复 | **已完成** — 第一轮 6 phases committed，RT-01/RT-12/RT-16 resolved |
| [first-agent-subsystem-integration-roadmap.md](first-agent-subsystem-integration-roadmap.md) | — | 子系统集成 roadmap | AutoRun queue 定义（当前仅 cleanup/slimming 模式） |

## Historical Plans (已完成或已冻结)

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

- **当前该做什么**：读 [post-red-team-cleanup-remediation-plan-2026-05-25.md](post-red-team-cleanup-remediation-plan-2026-05-25.md) — cleanup-only remediation 进行中
- **第一轮 remediation 历史**：读 [global-red-team-remediation-plan-2026-05-25.md](global-red-team-remediation-plan-2026-05-25.md) — 已完成，作为证据保留
- **AutoRun queue 定义**：读 [first-agent-subsystem-integration-roadmap.md](first-agent-subsystem-integration-roadmap.md)
- **历史实现证据**：Historical 部分保留为实现证据链，不需要作为行动源
