# V1 Archive Index

**创建**: 2026-06-03
**用途**: v1 historical / audit / dogfood / plan / review materials 的归档索引。
**规则**: 这些文档保留可追溯性，但**不作为 v2 implementation source-of-truth**。

---

## 1. Archive Purpose

v1 阶段产生了大量过程文档 — 审计、dogfood 报告、plan、review、设计决策记录。这些文档对理解 v1 做了什么是有价值的，但不应在 v2 中作为当前实现指令使用。

本 index 提供分类导航，不移动或删除任何文件。所有 v1 过程文档保持原位，通过本 index 标记为 historical。

---

## 2. Rule for Future Agents

```
Do not use archived v1 docs as v2 implementation source of truth.
Use these instead:
- docs/CURRENT_DOCS.md (文档导航)
- docs/debt/first-agent-v2-priority-backlog.md (v2 优先项)
- docs/releases/v1/first-agent-v1-closeout.md (v1 baseline 声明)
- docs/dev/ENGINEERING_WORKFLOW.md (工程流程)
- docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md (runtime contract)
```

---

## 3. Categories

### 3.1 Handoff / Close-out Docs

| 文档 | 说明 |
|------|------|
| `docs/handoff/first-agent-current-stage-close-out-2026-06-02.md` | FROZEN 阶段交接声明 |
| `docs/handoff/` (other) | 历史 handoff |

### 3.2 Audit / Review Docs

| 文档 | 说明 |
|------|------|
| `docs/audit/b1-b8-current-stage-close-out-audit.md` | B1-B8 close-out 审计 |
| `docs/audits/` (plural, if any) | 历史审计 (已被 close-out 覆盖) |
| `docs/reviews/` | 各类 review 文档 |

### 3.3 Dogfood Evidence Docs

| 文档 | 说明 |
|------|------|
| `docs/dogfood/real-api-full-dogfood-sweep-report-2026-05-27.md` | Historical dogfood sweep |
| `docs/dogfood/real-api-full-dogfood-sweep-report-2026-05-26.md` | 首次 real API dogfood |
| `docs/dogfood/real-api-dogfood-results-*.json` | 结构化 dogfood 结果 |
| `docs/dogfood/GLOBAL_REAL_API_DOGFOOD_REPORT.md` | Global real API dogfood |
| `docs/dogfood/scratch/` | 临时草稿 |

### 3.4 B7/B8 Process Docs

| 文档 | 说明 |
|------|------|
| `docs/design/b7-*` | B7 multi-instance readiness 设计文档 |
| `docs/design/b8-*` | B8 TUI architecture 设计文档 |
| `docs/roadmap/b8-*` | B8 roadmap |
| `docs/milestones/b8-*` | B8 milestone tracking |
| `docs/proposals/b8-*` | B8 方向变更提案 |
| `docs/plans/b7-*` | B7 implementation plans |

### 3.5 Ink / Workbench / Dashboard / AutoRun Historical Docs

| 文档 | 说明 |
|------|------|
| `docs/design/first-agent-tui-visual-target-v1.md` | TUI 22 组件 visual target |
| `docs/design/first-agent-tui-design.md` | TUI 设计语言 |
| `docs/plans/first-agent-tui-visual-shell-slice-a-plan.md` | Slice A plan |
| `docs/plans/first-agent-tui-visual-shell-slice-b-plan.md` | Slice B plan |
| `docs/design/legacy-dashboard-cleanup-plan.md` | Legacy Dashboard cleanup |

### 3.6 Old Remediation / Slice / Closeout Plans

| 文档 | 说明 |
|------|------|
| `docs/plans/` | Implementation plans (Slice A/B, etc.) |
| `docs/debt/first-agent-open-items.md` | v1 unresolved open items |
| `docs/debt/b7-*` `docs/debt/b8-*` | B7/B8 技术债务 |

### 3.7 Historical Architecture Docs

| 文档 | 说明 |
|------|------|
| `docs/design/` (B1-B8 era) | Architecture design docs — B1-B8 时代 |
| `docs/rfc/` | Canonical RFCs (MEMORY, SKILL, SUBAGENT) — still relevant for v2 |
| `docs/design/SKILL_SYSTEM_SDD.md` | Skill System SDD |
| `docs/design/SUBAGENT_SYSTEM_SDD.md` | SubAgent System SDD |
| `docs/design/mcp-architecture.md` | MCP 架构 |

> **Note**: Canonical RFCs (`docs/rfc/`) are still authoritative for their respective subsystems in v2.
> The architecture docs in `docs/design/` contain design intent that may still be relevant, but should be cross-referenced with the current runtime contract.

---

## 4. Archive Banner Template

将以下 banner 添加到任何需要明确标记为 historical 的 v1 文档顶部：

```markdown
> **Status: HISTORICAL / V1 ARCHIVE**
> This document is kept for audit and traceability only.
> Do not use it as the current v2 implementation source of truth.
> Current v2 sources:
> - docs/CURRENT_DOCS.md
> - docs/debt/first-agent-v2-priority-backlog.md
> - docs/releases/v1/first-agent-v1-closeout.md
```

---

## 5. What's NOT Historical

以下文档在 v2 中仍为当前 source-of-truth：

| 文档 | 原因 |
|------|------|
| `docs/PROJECT_STATUS.md` | 当前状态 — 持续更新 |
| `docs/PROGRESS_LEDGER.md` | 进度历史 — 持续更新 |
| `docs/CURRENT_DOCS.md` | 文档导航入口 |
| `docs/releases/v1/first-agent-v1-closeout.md` | v1 baseline 声明 |
| `docs/debt/first-agent-v2-priority-backlog.md` | v2 工作入口 |
| `docs/manual-trials/first-agent-user-trial-guide.md` | 手动试用指南 |
| `docs/dev/ENGINEERING_WORKFLOW.md` | 工程流程 |
| `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md` | Runtime contract |
| `docs/rfc/MEMORY_CANONICAL_RFC.md` | Memory 权威 RFC |
| `docs/rfc/SKILL_CANONICAL_RFC.md` | Skill 权威 RFC |
| `docs/rfc/SUBAGENT_CANONICAL_RFC.md` | SubAgent 权威 RFC |
