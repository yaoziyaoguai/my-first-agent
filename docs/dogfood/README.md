# Dogfood 报告索引 (Dogfood Reports Index)

本目录包含 my-first-agent 的 dogfood（手动验证）报告和相关文档。

**当前状态（2026-05-25）**：

- Manual human dogfood **未完成**；用户暂时不需要今晚执行。
- Agent-driven rehearsal 已完成 fake/local 11/11 PASS，但它是自动预演，不是人工 dogfood 的替代品。
- Real provider 路径仍受 401 config/auth concern 阻塞；不要在 AutoRun 中重试真实 API。
- 用户准备好时，按 [manual-human-dogfood-next-steps.md](manual-human-dogfood-next-steps.md) 走最短 fake/local 路径即可。

## 读者路径

- **只想知道人工 dogfood 最短下一步** → [manual-human-dogfood-next-steps.md](manual-human-dogfood-next-steps.md)
- **想手动验证本地功能** → [local-manual-dogfood-checklist.md](local-manual-dogfood-checklist.md)
- **想看最近的自动预演结果** → [agent-driven-human-dogfood-rehearsal-report.md](agent-driven-human-dogfood-rehearsal-report.md)
- **想看历史 dogfood 结果** → [local-manual-dogfood-report.md](local-manual-dogfood-report.md)（本地 FakeProvider）和 [GLOBAL_REAL_API_DOGFOOD_REPORT.md](GLOBAL_REAL_API_DOGFOOD_REPORT.md)（历史真实 API）
- **想看 JSON 证据** → JSON evidence reports
- **想正式记录 Manual Human Dogfood** → 复制 [manual-human-dogfood-record-template.md](manual-human-dogfood-record-template.md) 的结构，记录所有发现；不要填写 secret

## Active Dogfood Documents

| 文档 | 类型 | 说明 |
|------|------|------|
| [manual-human-dogfood-next-steps.md](manual-human-dogfood-next-steps.md) | **Manual Prep** | 用户准备好时的最短 fake/local 人工 dogfood 路径 |
| [local-manual-dogfood-checklist.md](local-manual-dogfood-checklist.md) | **Manual Checklist** | 本地手动 dogfood 检查清单 — Fake 9/9 PASS |
| [manual-human-dogfood-record-template.md](manual-human-dogfood-record-template.md) | **Record Template** | 人工 dogfood 记录模板；禁止粘贴 secret |
| [agent-driven-human-dogfood-rehearsal-report.md](agent-driven-human-dogfood-rehearsal-report.md) | **Auto Rehearsal** | Coding Agent 自动预演报告 — fake/local 11/11 PASS，real provider 401 concern |
| [local-manual-dogfood-report.md](local-manual-dogfood-report.md) | **MD Report** | 本地手动 dogfood 报告 — FakeProvider baseline |
| [GLOBAL_REAL_API_DOGFOOD_REPORT.md](GLOBAL_REAL_API_DOGFOOD_REPORT.md) | **Historical MD Report** | 历史真实 API dogfood 报告；当前 real provider 以最新 401 concern 为准 |

## Dogfood Plans (设计阶段文档)

| 文档 | 说明 |
|------|------|
| [SKILL_SYSTEM_DOGFOOD_PLAN.md](SKILL_SYSTEM_DOGFOOD_PLAN.md) | Skill System dogfood 计划 |
| [SUBAGENT_DOGFOOD_PLAN.md](SUBAGENT_DOGFOOD_PLAN.md) | SubAgent dogfood 计划 |

## Historical Dogfood Reports (历史参考，不作为当前状态源)

| 文档 | 类型 | 说明 |
|------|------|------|
| [E2E_RUNTIME_DOGFOOD_REPORT.md](E2E_RUNTIME_DOGFOOD_REPORT.md) | Historical Report | E2E Runtime dogfood 历史报告 |
| [COMPLEX_REAL_API_DOGFOOD_REPORT.md](COMPLEX_REAL_API_DOGFOOD_REPORT.md) | Historical Report | 复杂真实 API dogfood 历史报告 |

## JSON Evidence Reports (自动化证据，保留为原始数据)

| 文档 | 类型 | 说明 |
|------|------|------|
| [memory-e2e-report.json](memory-e2e-report.json) | JSON Evidence | Memory E2E 自动化验证结果 |
| [real-provider-e2e-report.json](real-provider-e2e-report.json) | JSON Evidence | Real Provider E2E 自动化验证结果 |
