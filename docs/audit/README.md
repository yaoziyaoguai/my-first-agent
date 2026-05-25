# 审计文档索引 (Audit Documentation Index)

本目录包含 my-first-agent 的独立审计文档。审计类型分两种：
- **Active（当前）**：最新全量审计，覆盖当前 main 分支状态，用于指导下一步行动
- **Historical（历史）**：过去特定阶段/系统的审计，保留为历史证据

## Active Audits

| 文档 | 日期 | 范围 | 用途 |
|------|------|------|------|
| [global-red-team-product-architecture-audit-2026-05-25.md](global-red-team-product-architecture-audit-2026-05-25.md) | 2026-05-25 | **全仓库 Red-Team** — 架构、代码质量、UX、安全、冗余 | **当前权威源** — Global Audit Remediation Big Loop 的唯一执行依据 |
| [global-agent-capability-architecture-audit-2026-05-25.md](global-agent-capability-architecture-audit-2026-05-25.md) | 2026-05-25 | 全仓库 — 代码、测试、文档、工程契约、dogfood | 全局能力/架构审计（已被 red-team audit 取代为权威行动源） |
| [big-loop-independent-audit-2026-05-25.md](big-loop-independent-audit-2026-05-25.md) | 2026-05-25 | 多轮 Big Loop 后的子系统审计 | Big Loop issue sweep 审计，Issue 1-5 已随 Loop 解决 |

## Historical Audits (当前阶段已完成或已过期的审计)

| 文档 | 日期 | 范围 | 状态 |
|------|------|------|------|
| [MEMORY_RFC_AUDIT_2026-05-16.md](MEMORY_RFC_AUDIT_2026-05-16.md) | 2026-05-16 | Memory RFC 审计 | Historical — Memory 主线已完成 |
| [SKILL_SYSTEM_AUDIT_CHECKLIST.md](SKILL_SYSTEM_AUDIT_CHECKLIST.md) | — | Skill System 审计清单 | Historical — Skill System 主线已完成 |
| [SKILL_SYSTEM_IMPLEMENTATION_AUDIT_PACKET.md](SKILL_SYSTEM_IMPLEMENTATION_AUDIT_PACKET.md) | — | Skill System 实现审计包 | Historical |
| [SUBAGENT_AUDIT_CHECKLIST.md](SUBAGENT_AUDIT_CHECKLIST.md) | — | SubAgent 审计清单 | Historical — SubAgent L0 主线已完成 |
| [SUBAGENT_IMPLEMENTATION_AUDIT_PACKET.md](SUBAGENT_IMPLEMENTATION_AUDIT_PACKET.md) | — | SubAgent 实现审计包 | Historical |

## 读者路径

- **下一步行动（当前）**：直接读 [global-red-team-product-architecture-audit-2026-05-25.md](global-red-team-product-architecture-audit-2026-05-25.md)，特别是 Section J (Top Findings) 和 Section K (Recommended Next Big Loops)
- **Red-Team Remediation Plan**：[global-red-team-remediation-plan-2026-05-25.md](../plans/global-red-team-remediation-plan-2026-05-25.md) — RT-01 到 RT-18 的完整修复执行计划
- **最近 Big Loop 成果**：读 [big-loop-independent-audit-2026-05-25.md](big-loop-independent-audit-2026-05-25.md)，了解最近完成的 issue sweep
- **历史审计证据**：Historical 部分保留为实现证据链，不需要作为行动源
