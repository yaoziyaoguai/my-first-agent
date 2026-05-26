# 审计文档索引 (Audit Documentation Index)

本目录包含 my-first-agent 的独立审计文档。

**分类规则**：
- **Active（当前）**：最新全量审计，覆盖当前 main 分支状态，用于指导下一步行动
- **Historical（历史）**：过去特定阶段/系统的审计，保留为历史证据，不作为当前行动源

> **AutoRun 规则**：只以 Active 审计为执行依据。Historical audits 是实现证据，不是当前 backlog。Archived audits（`docs/archive/`）不参与 AutoRun discovery。

## Active Audits

| 文档 | 日期 | 范围 | 用途 |
|------|------|------|------|
| [global-red-team-product-architecture-audit-2026-05-25.md](global-red-team-product-architecture-audit-2026-05-25.md) | 2026-05-25 | **全仓库 Red-Team** — 架构、代码质量、UX、安全、冗余 | **当前唯一权威行动源** |
| [capability-gap-audit-low-complexity-2026-05-25.md](capability-gap-audit-low-complexity-2026-05-25.md) | 2026-05-25 | Low-complexity capability gap 审计 | Low-complexity remediation 选择依据（已完成） |
| [big-loop-independent-audit-2026-05-25.md](big-loop-independent-audit-2026-05-25.md) | 2026-05-25 | 多轮 Big Loop 后的子系统审计 | Big Loop issue sweep 审计，Issue 1-5 已随 Loop 解决 |

## Historical Audits (已完成或已过期的审计，保留为证据)

| 文档 | 日期 | 范围 | 状态 |
|------|------|------|------|
| [global-agent-capability-architecture-audit-2026-05-25.md](global-agent-capability-architecture-audit-2026-05-25.md) | 2026-05-25 | 全仓库能力/架构审计 | Historical — 已被 red-team audit 取代为权威行动源 |
| [MEMORY_RFC_AUDIT_2026-05-16.md](MEMORY_RFC_AUDIT_2026-05-16.md) | 2026-05-16 | Memory RFC 审计 | Historical — Memory 主线已完成 |
| [SKILL_SYSTEM_AUDIT_CHECKLIST.md](SKILL_SYSTEM_AUDIT_CHECKLIST.md) | — | Skill System 审计清单 | Historical — Skill System 主线已完成 |
| [SKILL_SYSTEM_IMPLEMENTATION_AUDIT_PACKET.md](SKILL_SYSTEM_IMPLEMENTATION_AUDIT_PACKET.md) | — | Skill System 实现审计包 | Historical |
| [SUBAGENT_AUDIT_CHECKLIST.md](SUBAGENT_AUDIT_CHECKLIST.md) | — | SubAgent 审计清单 | Historical — SubAgent L0 主线已完成 |
| [SUBAGENT_IMPLEMENTATION_AUDIT_PACKET.md](SUBAGENT_IMPLEMENTATION_AUDIT_PACKET.md) | — | SubAgent 实现审计包 | Historical |

## 读者路径

- **当前审计状态** → [CURRENT_AUDIT_STATUS.zh.md](../06-audit/CURRENT_AUDIT_STATUS.zh.md)
- **当前能力状态** → [CURRENT_CAPABILITY_STATUS.zh.md](../00-overview/CURRENT_CAPABILITY_STATUS.zh.md)
- **下一步行动** → [final-cleanup-readiness-summary-2026-05-25.md](../plans/final-cleanup-readiness-summary-2026-05-25.md) — cleanup 已完成，manual human dogfood 是下一步
- **Red-Team 审计原文** → [global-red-team-product-architecture-audit-2026-05-25.md](global-red-team-product-architecture-audit-2026-05-25.md)
- **历史审计证据** → Historical 部分，保留为实现证据链，不作为行动源
