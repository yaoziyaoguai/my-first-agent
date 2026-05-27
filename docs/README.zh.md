# First Agent 文档入口

本文档为新开发者、架构审计者和 Coding Agent 提供稳定的阅读入口。

---

## 从这里开始（必读）

1. **[PROJECT_STATUS.md](PROJECT_STATUS.md)** — 当前项目状态：capability 状态、已知 issues、活跃约束、config 规则、推荐下一步
2. **[PROGRESS_LEDGER.md](PROGRESS_LEDGER.md)** — 进度账本：关键 milestones、已修复 bugs、P3 积压
3. **[dev/AUTO_RUN_WORKFLOW.md](dev/AUTO_RUN_WORKFLOW.md)** — 工程流程、loop 入口点、deferred/stop 条件

Coding Agent 每次启动必须先读上述三个文件。

---

## 当前 Dogfood

| 文档 | 说明 |
|------|------|
| [dogfood/real-api-full-dogfood-sweep-report-2026-05-27.md](dogfood/real-api-full-dogfood-sweep-report-2026-05-27.md) | 最新 real API dogfood 报告（19 PASS / 1 CONCERN / 0 FAIL） |
| [plans/real-api-full-dogfood-remediation-plan-2026-05-26.md](plans/real-api-full-dogfood-remediation-plan-2026-05-26.md) | ISSUE-001/002 修复记录 |

---

## 运行时宪法

| 文档 | 说明 |
|------|------|
| [real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md](real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md) | 统一 runtime flow 契约、branch points、classification rules |

---

## Config

| 文件 | 说明 |
|------|------|
| `config/config.yaml` | 当前推荐配置入口（本地可含 API key，不可 commit） |
| `config/config.example.yaml` | 配置参考（fake 安全默认） |
| `config/examples/` | Kimi/GLM/fake 等 provider 示例 |

**Legacy 路径（不推荐）**：`FIRST_AGENT_PROVIDER_PROFILE`、`MY_FIRST_AGENT_LLM_PROVIDER`、`config/provider_profiles.yaml`。

---

## Canonical Specs

| 文档 | 领域 |
|------|------|
| [rfc/MEMORY_CANONICAL_RFC.md](rfc/MEMORY_CANONICAL_RFC.md) | Memory 系统 |
| [rfc/SKILL_CANONICAL_RFC.md](rfc/SKILL_CANONICAL_RFC.md) | Skill 系统 |
| [rfc/SUBAGENT_CANONICAL_RFC.md](rfc/SUBAGENT_CANONICAL_RFC.md) | SubAgent 系统 |

---

## 设计契约

| 文档 | 说明 |
|------|------|
| [design/fake-provider-scripted-scenario-contract.md](design/fake-provider-scripted-scenario-contract.md) | FakeProvider 脚本化场景契约 |
| [design/config-legacy-sunset-contract.md](design/config-legacy-sunset-contract.md) | Legacy 配置路径 sunset 时间线 |
| [design/dogfood-harness-contract.md](design/dogfood-harness-contract.md) | Dogfood harness 契约 |
| [design/run-summary-compact-report.md](design/run-summary-compact-report.md) | Run summary 报告 |

---

## 工程文档

| 文档 | 说明 |
|------|------|
| [dev/AUTO_RUN_WORKFLOW.md](dev/AUTO_RUN_WORKFLOW.md) | Auto-run workflow 定义 |
| [dev/ENGINEERING_WORKFLOW.md](dev/ENGINEERING_WORKFLOW.md) | 工程流程纪律（SDD→TDD→Impl→Review→Debug） |

---

## 审计和计划

审计和计划文档数量较多，状态各异。以以下索引为准：

- [audit/README.md](audit/README.md) — 审计文档 active vs historical 分类
- [plans/README.md](plans/README.md) — 计划文档 active vs historical 分类
- [dogfood/README.md](dogfood/README.md) — Dogfood 报告 active vs historical 分类

---

## Archive

历史文档统一放在 [archive/](archive/) 下，包括：

- `archive/design/` — 历史架构设计
- `archive/implementation-notes/` — 历史实现笔记
- `archive/specs/` — 历史 SPEC/TDD
- `archive/root-stale/` — 根目录移动过来的过期文档
- `archive/v0.x/` — V0.x 版本记录
- `archive/refactor/` — 重构历史
- `archive/llm-provider/` — LLM provider legacy 文档
- `archive/mcp/` — MCP 历史

**Archive 中的文档不作为当前状态参考。**

---

## 术语约定

| 中文 | English | 含义 |
|---|---|---|
| 主代理运行时 | Parent Agent Runtime | 拥有主 loop、状态、模型调用和分派 |
| 工具注册中心 | ToolRegistry | 工具 authority，决定工具定义、风险、confirmation |
| 检查点 | Checkpoint | 安全恢复边界 |
| 人工确认 | Confirmation | 高风险动作的人类控制边界 |
