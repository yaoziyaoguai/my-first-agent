# S-Series Product Roadmap

> 权威文档（docs/current/）。本文只定义 S 系列的版本语义与高层方向，不写未来 S2/S3/Sn 的硬性实施计划，不复活 docs/history/ 中的旧 roadmap。

## 1. 什么是 S 系列

S 系列是 FirstAgent **重新开始之后的产品版本序列**：S1、S2、S3 …… Sn。

- **S 命名 ≠ 代码里的 v1/v2/v3。** 代码中存在 `v0.x`、`Phase N`、`Loop N`、`B7`、`L0/L1/L2` 等历史命名，它们是实现演进留下的内部标签。S 系列是**产品版本**层面的重新编号。
- 使用 S 命名的唯一目的，是**避免 coding agent 把产品版本目标和代码里的旧版本标签混淆**。任何 S 文档都不得用代码 `v1/v2/v3` 当作 S 目标，也不得把 S 当作代码版本号。

## 2. S1 是什么

- **S1 = 第一个「基本可用产品版 / Baseline Usable Product」。**
- S1 不是 demo，不是 MVP 小试，不是一个小 sprint，也不是纯审计/纯治理阶段。
- S1 的任务是把**当前已经存在的 FirstAgent 能力**，收敛为一个可以真实使用、可以解释、可以验收、可以继续增强的产品基线。
- S1 的详细目标见 `docs/history/S1_BASELINE_USABLE_PRODUCT/S1_GOAL.md`（S1 已完成并归档；用户批准后冻结）。

## 3. S2 / S3 / Sn 是什么

- S2/S3/Sn 是**在 S1 基线之上**围绕五层能力的**持续补强版本**。
- 约束：后续版本必须在**不推翻 S1 架构主链路**的前提下增强能力。
- 本文**不**把 S2/S3/Sn 写成硬性实施计划，也不为它们承诺范围或时间。它们的具体目标在各自进入时再定义。

## 4. 五层能力主线（贯穿 S 系列）

S 系列围绕同一条五层能力主线演进。各层在不同 S 版本的成熟度不同，但层的划分稳定：

- **L1 — Agent Loop / Runtime Spine**：统一入口、runtime loop、provider 边界与 same-spine。
- **L2 — Context / Memory / State / Checkpoint**：上下文构建与压缩、memory、任务状态、checkpoint/resume。
- **L3 — Tools / Policy / Evidence**：工具注册与中介执行、policy/approval gate、evidence/log/trace。
- **L4 — Task Orchestration / State Machine / Progress Tracking**：多步任务状态机、步骤推进、进度跟踪。
- **L5 — Skill / MCP / SubAgent / Scheduler Extension Boundary**：扩展能力边界——Skill、MCP、SubAgent、Scheduler 的接入边界与激活策略。

> 说明：这里的 L1–L5 是**能力分层标签**，不是成熟度等级评分，也不对应代码里的 `L0/L1/L2` 历史标签。

## 5. 高层方向（非实施计划）

- **S1**：把五层能力收敛为「基本可用或边界清楚」的产品基线。每层只要求 basic-usable / boundary-clear，不要求最终成熟。
- **S2 及以后**：在 S1 基线上，按届时确定的优先级，对某些层做深度补强（例如扩展能力从 boundary-clear 走向 selectively-active）。具体不在本文展开。

## 6. 文档与治理

- `docs/current/` 是当前权威文档区；`docs/history/` 是历史证据区（非 routing authority）。
- 历史文档（含旧 roadmap、Window/Theme 计划、模块成熟度表）只能作为背景证据，不得作为当前 S 系列路线来源。
- S 系列治理规则见 `AGENTS.md` 的 **S1 Development Governance**。
