# Dogfood 报告索引 (Dogfood Reports Index)

本目录包含 my-first-agent 的 dogfood（手动验证）报告和相关文档。

## 读者路径

- **想手动验证本地功能** → [local-manual-dogfood-checklist.md](local-manual-dogfood-checklist.md)
- **想看最近的完整 dogfood 结果** → [local-manual-dogfood-report.md](local-manual-dogfood-report.md)（本地 FakeProvider）和 [GLOBAL_REAL_API_DOGFOOD_REPORT.md](GLOBAL_REAL_API_DOGFOOD_REPORT.md)（真实 API）
- **想看 JSON 证据** → JSON evidence reports

## Active Dogfood Documents

| 文档 | 类型 | 说明 |
|------|------|------|
| [local-manual-dogfood-checklist.md](local-manual-dogfood-checklist.md) | **Manual Checklist** | 本地手动 dogfood 检查清单 — Fake 9/9 PASS |
| [local-manual-dogfood-report.md](local-manual-dogfood-report.md) | **MD Report** | 本地手动 dogfood 报告 — FakeProvider baseline |
| [GLOBAL_REAL_API_DOGFOOD_REPORT.md](GLOBAL_REAL_API_DOGFOOD_REPORT.md) | **MD Report** | 全局真实 API dogfood 报告 — Real provider 5/6 PASS |

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
