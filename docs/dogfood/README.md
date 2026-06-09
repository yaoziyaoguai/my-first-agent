# Dogfood Reports Index

Dogfood 报告是证据材料，不是当前能力 source of truth。当前状态以 [PROJECT_STATUS.md](../PROJECT_STATUS.md) 为准。

## 保留入口

| 文档 | 状态 |
|---|---|
| [v1-runtime-first-synthetic-user-dogfood-report.md](v1-runtime-first-synthetic-user-dogfood-report.md) | 历史 synthetic dogfood 证据 |
| [v1-synthetic-user-dogfood-report.md](v1-synthetic-user-dogfood-report.md) | 历史 synthetic dogfood 证据 |
| [GLOBAL_REAL_API_DOGFOOD_REPORT.md](GLOBAL_REAL_API_DOGFOOD_REPORT.md) | 历史 real API dogfood 汇总 |
| [real-api-full-dogfood-sweep-report-2026-05-27.md](real-api-full-dogfood-sweep-report-2026-05-27.md) | 历史 real API smoke |
| [real-api-interactive-dogfood-report-2026-05-27.md](real-api-interactive-dogfood-report-2026-05-27.md) | 历史 interactive smoke |

## 使用规则

- 不把 no-crash / smoke 结果写成 capability complete。
- 不把 fake/local 结果写成 real provider evidence。
- 不把 dogfood report 当成当前 backlog。
- 清理 JSON/report 输出前先做引用检查。
