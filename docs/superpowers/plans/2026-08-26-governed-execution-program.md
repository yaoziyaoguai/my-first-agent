# 017–019 Governed Execution Program Plan Index

> **For agentic workers:** Execute the milestone plans in order. Do not start the next milestone until the current milestone has a sealed real E3 receipt and fresh independent PASS.

**Goal:** 连续交付 sandbox 命令/代码任务、专用浏览器网页任务和有界后台调度，同时保持 First Agent 唯一 Runtime/ToolRuntime owner。

**Spec:** `docs/superpowers/specs/2026-08-26-governed-execution-program-design.md`

## Execution order

1. `docs/superpowers/plans/2026-08-26-017-sandboxed-workspace-execution.md`
2. `docs/superpowers/plans/2026-08-26-018-governed-browser-tasks.md`
3. `docs/superpowers/plans/2026-08-26-019-durable-background-runs.md`

## Promotion rule

每个 milestone 都必须独立完成 U0 frozen contracts、U1 deterministic gates、U2 sealed materialized real E3 三连和 U3 fresh review。旧 milestone 的 Green 不能替代新 milestone 的 receipt；后续 milestone 的存在也不能让前一阶段提前宣称完成。

## Executor rule

Claude Code GLM 5.3 `effort=max` 是主实现者；Codex 负责计划、审计和配额 handoff。明确 429 后 Codex 才接手；恢复时在原子边界交还 Claude。两者不得并发写同一工作树。按项目规则，本计划不要求 commit/push。

## Plan self-review

| Approved spec requirement | Owning tasks |
| --- | --- |
| 唯一 Runtime/ToolRuntime、状态面分离、state≠authority | 017 T4/T6/T8，018 T2/T5/T6/T8，019 T2/T4/T5/T7 |
| Sandbox snapshot、真实隔离、network policy、ChangeBundle | 017 T2–T7 |
| Browser dedicated profile、两种 navigation policy、takeover、commit approval | 018 T1–T8 |
| Download quarantine / sandbox integration | 018 T7 |
| launchd one-shot worker、UTC occurrence、replay、bounded job | 019 T1–T7 |
| 后台只读/compute envelope、human wait/restart | 019 T4/T6/T7 |
| Unknown outcome 不自动重放 | 017 T4/T7，018 T4/T8，019 T3/T5/T7 |
| Credential/private data absence | 三份计划的 Global Constraints、focused mutation tests 和 T10 |
| focused→single source full→materialized real E3→fresh review | 每份计划 T9/T10 |
| Claude quota handoff、不并发写、不改配置 | 本索引 Executor rule 与 approved spec §10 |

自审后已统一 adapter draft 与 Runtime durable receipt 的命名，补齐 SandboxStore/BrowserSessionStore，补齐 browser profile CRUD，并删除了不可靠的 launchd calendar encoding：019 只用 60 秒外部 wake，纯 UTC resolver 决定是否产生 occurrence，not-due 路径在 composition 前退出。
