# S1 Goal — Baseline Usable Product

> 权威文档（docs/current/）。S1 目标定义。经用户批准后**冻结**（见 AGENTS.md：S1_GOAL.md frozen after user approval）。本文不是 Phase Plan，不展开实施步骤；可验收的差距清单见 `S1_GOAL_GAP.md`。

## 0. 一句话目标

把当前 FirstAgent 收敛为「基本可用产品版」。S1 不是 demo，也不是小阶段，而是 S 系列中的第一个正式产品基线版本。S1 必须在统一 Agent Runtime 主链路之上，具备基本可用的上下文/状态管理、受控工具执行、可追踪 evidence、最小多步任务状态能力和安全配置基线；同时明确 Skill、MCP、SubAgent、Scheduler 等扩展能力的边界，保证后续 S2/S3/Sn 可以在不推翻 S1 架构的前提下继续补强。

## 1. S1 的定位

1. S1 是 FirstAgent 的 **Baseline Usable Product / 基本可用产品版**。
2. S1 **不是 demo**。当前项目（统一 `core.chat()` 入口、显式 runtime loop、provider 协议、dispatcher/mediator、policy gate、checkpoint/resume、双层 evidence）早已越过 demo 级别。
3. S1 **不是**小阶段、纯治理、纯审计，也不是只证明 runtime spine 能跑。
4. S1 的目标是让现有能力**可以真实使用、可以解释、可以验收、可以继续增强**。
5. S1 **必须基于当前代码现实**（见 `S1_CURRENT_CODE_ARCHITECTURE_AUDIT.zh.md`），不得凭空定义不存在的能力。
6. S1 **必须覆盖五层能力**，但每层要求是「基本可用 or 边界清楚」，不是最终成熟。

## 2. 五层能力的 S1 要求

- **L1 Runtime Spine**：单一入口与 runtime loop 可用；fake/real 共享同一 spine（仅 factory/config 层不同）。
- **L2 Context/Memory/State/Checkpoint**：上下文压缩配对安全、memory recall/retain 可用、任务状态机可用、checkpoint save/resume 可用。
- **L3 Tools/Policy/Evidence**：工具注册+中介执行可用、policy/confirmation gate 在两种 provider 模式一致、evidence 至少能证明一次 run 的路径骨架。
- **L4 Task Orchestration**：存在**最小**多步任务状态与步骤推进，进度可在 checkpoint 中持久化。
- **L5 Extension Boundary**：Skill / MCP / SubAgent / Scheduler 的**边界清楚**（active / configurable / dormant / demo-only 明确），不要求在 S1 默认激活。

## 3. 必须具备的能力（S1 must-have）

1. 单一可运行入口 + 统一 runtime loop。
2. FakeProvider 可作为确定性回归基线；RealProvider 可作为真实 smoke 路径。
3. fake/real 进入 core 后共享同一 action parsing / dispatcher / tool mediator / policy / checkpoint / evidence。
4. 上下文压缩不破坏 tool_use/tool_result 配对。
5. 受控工具执行：tool result 可靠回到 context 与 task state。
6. 最小多步任务状态：计划→步骤推进→完成/失败，且可 checkpoint/resume。
7. evidence 能证明一次 run 的路径骨架（provider 类型、工具 gate/invoke/result、memory、checkpoint）。
8. 安全配置基线：仓库不得提交真实 provider 密钥。

## 4. 不承诺的能力（S1 explicitly NOT promised）

1. Scheduler 接入主链路（当前 dormant；S1 保持 dormant，不接入也不删除）。
2. MCP / SubAgent / Skill 的全量生产激活（S1 只要求边界清楚；默认 configurable/dormant 可接受）。
3. evidence 持久化模型 request/response 正文（S1 仅要求路径骨架级可观测）。
4. 独立 durable task ledger（S1 用 checkpoint 快照作为进度记录即可）。
5. 任何超出当前代码现实的新能力。

## 5. Release blockers（必须先解决才能宣布 S1 可用）

- **RB-1**：`config/config.yaml` 被 git 跟踪且含真实 provider 密钥。产品基线不得在仓库中暴露密钥。（对应 gap G-15。本轮按指令不处理密钥，仅登记为 release blocker。）
- **RB-2**：面向使用者的运行说明可用。README 的文档导航当前指向已迁移到 `docs/history/` 的路径、并自述「不是面向普通用户的产品」，与「基本可用产品版」不一致。（对应 gap G-16。本轮禁改 README，仅登记。）

## 6. Acceptance criteria（S1 验收口径）

S1 视为达成，当且仅当：

1. **AC-1 主链路**：存在一条被指定的主链路验收命令/测试集（候选 `tests/golden_e2e/*`），fake 模式下确定性通过。
2. **AC-2 same-spine**：能用一次 fake run 与一次 real run 的 `sessions/<id>/events.jsonl` 对照，证明二者经过同一组事件（tool gate/invoke/result、checkpoint、memory），仅 `provider_type` 不同。
3. **AC-3 real smoke**：存在一个 key-safe 的 real provider smoke 步骤（用 gitignored `config/config.local.yaml`），产出可证明真实模型调用的 events。
4. **AC-4 工具结果完整性**：tool result 可靠进入 context 与 task state，压缩不破坏配对。
5. **AC-5 多步任务**：一个最小多步任务能计划、推进、完成，并能 checkpoint/resume。
6. **AC-6 安全基线**：仓库中不存在被跟踪的真实密钥（RB-1 已解决）。
7. **AC-7 可用说明**：使用者能按 README/quickstart 跑起来，文档导航指向有效路径（RB-2 已解决）。

> 上述验收口径的逐条差距与状态见 `S1_GOAL_GAP.md`。

## 7. 不可触碰的产品原则（Provider Rules）

- **FakeProvider 与 RealProvider 不能成为两套 agent。**
- RealProvider **不能绕过 runtime spine**。
- FakeProvider **不是产品能力上限**，只是确定性测试/CI/运行契约适配器。
- 历史 docs 只是证据，**不是当前路线**；`docs/current/` 是当前权威文档区。
- 若某任务有把 fake/real 拆成两条路径的风险，必须记入 `S1_GOAL_GAP.md` 或 `TECH_DEBT.md`。

## 8. 与代码版本命名的关系

S1 与代码里的 `v1/v2/v3`、`Phase N`、`Loop N` 等标签**无对应关系**。S1 是产品基线版本，不得被旧实现标签牵引。
