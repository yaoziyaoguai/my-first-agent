# Dogfood 报告索引 (Dogfood Reports Index)

本目录包含 my-first-agent 的 dogfood 报告和结果数据。

## 当前报告 (Active)

| 文档 | 日期 | 说明 |
|------|------|------|
| [AGENT_DOGFOOD_AUTO Suite](../PROJECT_STATUS.md) | 2026-06-03 | **最新** v1 release-readiness agent dogfood：873 tests PASS, 0 AGENT_FIX_AUTO, 7 xfailed known/expected |
| [GLOBAL_REAL_API_DOGFOOD_REPORT.md](GLOBAL_REAL_API_DOGFOOD_REPORT.md) | 2026-06-02 | Global real API dogfood report |
| [real-api-full-dogfood-sweep-report-2026-05-27.md](real-api-full-dogfood-sweep-report-2026-05-27.md) | 2026-05-27 | Real API dogfood smoke：20 cases, 19 non-failing / 1 CONCERN |
| [real-api-full-dogfood-sweep-report-2026-05-26.md](real-api-full-dogfood-sweep-report-2026-05-26.md) | 2026-05-26 | 首次 real API 全能力 dogfood：18 PASS / 2 CONCERN / 0 FAIL |

**Evidence 限制**：当前 dogfood 多数是 direct provider smoke，不是完整 agent runtime E2E。交互式 confirmation、resume、interrupt、tool/memory confirmation、streaming/progress 尚未真实覆盖。Evidence level: REAL_DOGFOOD_SMOKE。AGENT_DOGFOOD_AUTO (2026-06-03) 为当前最高覆盖面 agent-driven suite。

## 结果数据 (Active)

| 文档 | 说明 |
|------|------|
| [real-api-dogfood-results-2026-05-27.json](real-api-dogfood-results-2026-05-27.json) | 最新 dogfood 结构化结果 |
| [real-api-dogfood-results-2026-05-26.json](real-api-dogfood-results-2026-05-26.json) | 首次 dogfood 结构化结果 |
| [memory-e2e-report.json](memory-e2e-report.json) | Memory E2E 自动化验证结果 |
| [real-provider-e2e-report.json](real-provider-e2e-report.json) | Real Provider E2E 自动化验证结果 |

## Archive

历史 dogfood 报告（fake/local、manual、rehearsal 等）已归档至 [archive/2026-05-27-cleanup/dogfood/](../archive/2026-05-27-cleanup/dogfood/)。
