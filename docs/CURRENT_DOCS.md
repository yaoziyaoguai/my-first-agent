# Current Documentation Map — First Agent

**创建**: 2026-06-02 (docs source-of-truth audit)
**用途**: Coding Agent 的文档导航入口。每次 session 启动后，在所有其他 doc 之前先读 `PROJECT_STATUS.md`，然后按需查阅本文件。

---

## 1. Start Here (必须优先读)

| 优先级 | 文档 | 说明 |
|--------|------|------|
| **P0** | `PROJECT_STATUS.md` | 第一优先。当前状态、能力定义 (REAL-EVIDENCE-001..008)、B1-B8 架构分类账、close-out 声明 |
| **P0** | `PROGRESS_LEDGER.md` | 关键 milestones 历史、commit/date/milestone 映射 |
| **P0** | `handoff/first-agent-current-stage-close-out-2026-06-02.md` | **FROZEN** 阶段交接声明、future debt list、下次 session 启动指令 |
| **P1** | `design/first-agent-tui-visual-target-v1.md` | TUI 22 组件映射、6 区域布局合同、data source policy |
| **P1** | `design/first-agent-tui-design.md` | TUI 设计语言：颜色/token/排版/间距/交互层级 |

---

## 2. Current Implementation (活跃实现文档)

### TUI
| 文档 | 状态 | 说明 |
|------|------|------|
| `plans/first-agent-tui-visual-shell-slice-a-plan.md` | **IMPLEMENTED** | Slice A: static visual shell。代码基准: `088e05b` |
| `plans/first-agent-tui-visual-shell-slice-b-plan.md` | **IMPLEMENTED** (2026-06-02) | Slice B: wire existing safe data into Slice A shell。484/484 TUI tests PASS, tsc clean |
| `design/b8-interaction-first-workbench-sdd.md` | COMPLETED-WITH-CAVEATS | B8 SDD（取代旧 `b8-ts-tui-workbench-sdd.md`） |
| `design/b8-input-readiness-validation.md` | DRAFT | IME/paste/multiline readiness。IME: MANUAL_PENDING |
| `design/runtime-gateway-foundation-sdd.md` | DRAFT | D-04 RuntimeGateway contract + FakeRuntimeAdapter |
| `design/legacy-dashboard-cleanup-plan.md` | DRAFT | Legacy Dashboard/AutoRun/Project Operations 清理方案 |
| `roadmap/b8-tui-workbench-roadmap.md` | CURRENT | B8 roadmap M1-M8 |
| `milestones/b8-interaction-first-workbench-milestones.md` | CURRENT | B8 milestone tracking |
| `proposals/b8-interaction-first-workbench-proposal.md` | CURRENT | B8 方向变更提案 (Accepted) |

### Agent Runtime
| 文档 | 状态 | 说明 |
|------|------|------|
| `design/SKILL_SYSTEM_SDD.md` | CURRENT | Skill System SDD |
| `design/skill-system-architecture.md` | CURRENT | Skill 架构 |
| `design/SUBAGENT_SYSTEM_SDD.md` | CURRENT | SubAgent System SDD |
| `design/subagent-boundary-architecture.md` | CURRENT | SubAgent boundary |
| `design/mcp-architecture.md` | CURRENT | MCP 架构 |
| `design/mcp-real-external-connection-readiness.md` | DRAFT | D-02 MCP external connection (local smoke only) |
| `design/mcp-real-external-flight-contract.md` | DRAFT | Loop 3.3 Real MCP external flight contract |
| `design/unified-project-config-contract.md` | CURRENT | 统一配置合同 (取代旧 provider-profile-config-contract) |
| `design/config-legacy-sunset-contract.md` | CURRENT | Config 遗留 sunset |
| `design/tool-path-unification-l1.3.md` | IMPLEMENTED | Tool 路径统一 (Loop 1.3) |
| `design/runtime-decision-spine.md` | IMPLEMENTED | Runtime Decision Spine |
| `design/advanced-scheduler-contract.md` | DRAFT | Advanced Scheduler SDD |
| `design/batch-b-scheduler-main-path-injection.md` | DRAFT | Scheduler main-path injection |
| `real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md` | ACTIVE | 统一 runtime flow contract |
| `rfc/MEMORY_CANONICAL_RFC.md` | **Canonical** | Memory 权威 RFC |
| `rfc/SKILL_CANONICAL_RFC.md` | **Canonical** | Skill 权威 RFC |
| `rfc/SUBAGENT_CANONICAL_RFC.md` | **Canonical** | SubAgent 权威 RFC |

---

## 3. Evidence / Audit / Debt

| 文档 | 说明 |
|------|------|
| `audit/b1-b8-current-stage-close-out-audit.md` | B1-B8 close-out 审计 (2026-06-02) |
| `debt/first-agent-open-items.md` | **Unresolved open items** — audit result: AGENT_AUTO=zero, P0/P1/P2=no |
| `manual-trials/first-agent-user-trial-guide.md` | **User manual trial guide** — UMT-001~003 step-by-step, result log template |
| `debt/REAL_EVIDENCE_VALIDATION_DEBT.md` | Real evidence validation debt (REAL-EVIDENCE-001..008) |
| `debt/b8-tui-workbench-technical-debt.md` | B8 TUI 技术债务 |
| `debt/b7-pre-sdd-redline-debt.md` | B7 pre-SDD redline (completed) |
| `reviews/b8-tui-workbench-completion-review.md` | B8 completion review (2026-06-01) |
| `reviews/2026-05-29-first-agent-runtime-lab-stage-review.md` | Runtime lab stage review |
| `dogfood/README.md` | Dogfood 报告索引 |
| `dogfood/real-api-full-dogfood-sweep-report-2026-05-27.md` | 最新全量 dogfood sweep |
| `dogfood/GLOBAL_REAL_API_DOGFOOD_REPORT.md` | Global real API dogfood report |

---

## 4. Historical / Superseded (只能作为历史参考)

这些文档**不能**作为当前实现 source of truth：

| 目录/文档 | 原因 | 替代文档 |
|-----------|------|---------|
| `archive/` | 全量历史文档 (15 子目录) | 见各子目录 README |
| `design/b8-ts-tui-workbench-sdd.md` | 旧 B8 SDD (信息展示中心方向) | `design/b8-interaction-first-workbench-sdd.md` |
| `design/provider-profile-config-contract.md` | 已取代 | `design/unified-project-config-contract.md` |
| `audits/` (plural) | 所有 5 个审计已被 close-out 覆盖 | `audit/b1-b8-current-stage-close-out-audit.md` |
| `dogfood/scratch/` | 临时草稿 | — |
| `rfc/archived/` | 已并入 canonical RFC | `rfc/MEMORY_CANONICAL_RFC.md` |
| `00-overview/` `01-getting-started/` `02-architecture/` `05-testing-dogfood/` `06-audit/` | 旧 overlay 结构，仍当前但部分内容可能过期 | 以 `PROJECT_STATUS.md` 为准 |
| `learning/` | 历史 lesson learned | — |

---

## 5. Rules for Coding Agent

当 Coding Agent 读文档时，必须遵守以下规则：

1. **不要重开 current-stage close-out** — `PROJECT_STATUS.md` 标记 FROZEN，不进入 B9
2. **不要把 future debt 当 current blocker** — `debt/REAL_EVIDENCE_VALIDATION_DEBT.md` 是未来债，不是当前 P0
3. **不要把 fake/local 当成 real** — TUI 所有 fake/local 标记不可移除，不能写成 product-ready
4. **不要恢复 Dashboard / AutoRun / Project Operations 为主线** — 这些是 legacy，保留但不在当前入口
5. **不要读 .env / 打印 / 提交 secret** — 安全红线
6. **不要激活 TUI default entry** — `main.tsx` 中 `WorkbenchLayout` 是默认入口，`TuiShell` 是 component-level export only
7. **如果 PROJECT_STATUS.md 与其他 doc 冲突，以 PROJECT_STATUS.md 为准**
8. **archive/ 只能作为历史参考，不能作为当前指令**

---

## 6. 常见任务快速入口

| 任务 | 先读 |
|------|------|
| 实现 TUI 新功能 | `PROJECT_STATUS.md` → `design/first-agent-tui-visual-target-v1.md` → `plans/first-agent-tui-visual-shell-slice-a-plan.md` |
| 修复 TUI bug | `PROJECT_STATUS.md` → 相关 Slice plan → `debt/b8-tui-workbench-technical-debt.md` |
| 新增 runtime capability | `PROJECT_STATUS.md` → 相关 Canonical RFC → 相关 design doc |
| Dogfood 验证 | `dogfood/README.md` → 最新 sweep report → `PROJECT_STATUS.md` REAL-EVIDENCE 表 |
| 架构变更 | `PROJECT_STATUS.md` → 相关 Canonical RFC → `handoff/` close-out doc |
| 文档清理 | 本文件 → `PROJECT_STATUS.md` → `archive/README.md` |
