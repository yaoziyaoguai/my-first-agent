# Dogfood 报告索引 (Dogfood Reports Index)

本目录包含 my-first-agent 的 dogfood（手动验证）报告和相关文档。

**分类规则**：
- **Active（当前）**：manual human dogfood 准备和记录文档
- **Evidence（证据）**：自动化 dogfood/预演报告，保留为证据
- **Historical（历史）**：历史 dogfood 报告，不作为当前状态源

> **关键区分**：agent-driven rehearsal（自动预演）≠ manual human dogfood（人工验证）。自动化证据不能替代人类判断。AutoRun 不执行 dogfood，不重试真实 API。

**当前状态（2026-05-26）**：
- Manual human dogfood **未完成**；需人类按 checklist 执行。
- Agent-driven rehearsal 已完成 fake/local 11/11 PASS，但不是人工 dogfood 的替代品。
- Real provider 路径仍受 401 config/auth concern 阻塞；AutoRun 不重试真实 API。

## Active (当前)

| 文档 | 类型 | 说明 |
|------|------|------|
| [manual-human-dogfood-next-steps.md](manual-human-dogfood-next-steps.md) | **Manual Prep** | 用户准备好时的最短 fake/local 人工 dogfood 路径 |
| [local-manual-dogfood-checklist.md](local-manual-dogfood-checklist.md) | **Manual Checklist** | 本地手动 dogfood 检查清单 — Fake 9/9 PASS |
| [manual-human-dogfood-record-template.md](manual-human-dogfood-record-template.md) | **Record Template** | 人工 dogfood 记录模板；禁止粘贴 secret |

## Evidence (自动化证据)

| 文档 | 类型 | 说明 |
|------|------|------|
| [agent-driven-human-dogfood-rehearsal-report.md](agent-driven-human-dogfood-rehearsal-report.md) | **Auto Rehearsal** | Coding Agent 自动预演报告 — fake/local 11/11 PASS，real provider 401 concern |
| [memory-e2e-report.json](memory-e2e-report.json) | JSON Evidence | Memory E2E 自动化验证结果 |
| [real-provider-e2e-report.json](real-provider-e2e-report.json) | JSON Evidence | Real Provider E2E 自动化验证结果 |

> **注意**：以上自动化证据是 agent-driven，不是 manual human dogfood。不得以此声称人工验证已完成。

## Historical (历史参考)

| 文档 | 类型 | 说明 |
|------|------|------|
| [local-manual-dogfood-report.md](local-manual-dogfood-report.md) | MD Report | 本地手动 dogfood 报告 — FakeProvider baseline |
| [GLOBAL_REAL_API_DOGFOOD_REPORT.md](GLOBAL_REAL_API_DOGFOOD_REPORT.md) | Historical MD Report | 历史真实 API dogfood 报告；当前 real provider 以最新 401 concern 为准 |
| [E2E_RUNTIME_DOGFOOD_REPORT.md](E2E_RUNTIME_DOGFOOD_REPORT.md) | Historical Report | E2E Runtime dogfood 历史报告 |
| [COMPLEX_REAL_API_DOGFOOD_REPORT.md](COMPLEX_REAL_API_DOGFOOD_REPORT.md) | Historical Report | 复杂真实 API dogfood 历史报告 |

## Dogfood Plans (设计阶段文档，保留为参考)

| 文档 | 说明 |
|------|------|
| [SKILL_SYSTEM_DOGFOOD_PLAN.md](SKILL_SYSTEM_DOGFOOD_PLAN.md) | Skill System dogfood 计划 |
| [SUBAGENT_DOGFOOD_PLAN.md](SUBAGENT_DOGFOOD_PLAN.md) | SubAgent dogfood 计划 |

## 读者路径

- **人工 dogfood 最短下一步** → [manual-human-dogfood-next-steps.md](manual-human-dogfood-next-steps.md)
- **手动验证本地功能** → [local-manual-dogfood-checklist.md](local-manual-dogfood-checklist.md)
- **最近自动预演结果** → [agent-driven-human-dogfood-rehearsal-report.md](agent-driven-human-dogfood-rehearsal-report.md)
- **正式记录 Manual Human Dogfood** → 复制 [manual-human-dogfood-record-template.md](manual-human-dogfood-record-template.md) 的结构；不填写 secret
- **历史 dogfood 证据** → Historical 部分，不作为当前状态源
