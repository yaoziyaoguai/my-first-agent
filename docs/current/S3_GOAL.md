# S3 Goal — Extensible Governed Agent Runtime

> Current document (`docs/current/`). S3 目标**草案**，供用户审阅。本文由
> `S_ROADMAP.md`（五层主线）、`S3_BASELINE_STATUS.md`（S3 起点现状）、S2 归档与当前
> `TECH_DEBT.md` 推导而来；方向对比见 `_tmp_s3_goal_draft/direction_review.md`。
>
> 状态：**未冻结**。按 `AGENTS.md` goal rules，goal 经用户批准后才冻结，冻结后不得因
> 实现困难而改、不得静默收窄/扩张。本文**不生成 S3 gap**；gap 在用户批准本 goal 后才
> 由 `S3_GOAL_GAP.md` 承接。

## 0. Executive summary

S3 = **Extensible Governed Agent Runtime / 可扩展的受控 Agent Runtime**。

- S3 **继承** S2 的 Governed Task Agent（governed task path / state / progress /
  context-memory-checkpoint / tool-policy-evidence / Skill governed-active /
  acceptance gate），并把它们作为 must-not-regress 起点。
- S3 **不推翻** S1/S2 same-spine runtime，不引入第二条主链路。
- S3 **不**直接进入完整多 Agent / 完整 MCP 生态化（见 §7 Non-goals）。
- S3 的目标是让 **L5 extension boundary 更成熟、更可治理**：把 S2 在 Skill 上验证过的
  受控激活模式（discovery → select → enable → govern → evidence → disable）抽象为
  **统一的 extension 接入契约**，并把 **1-2 个** L5 扩展能力从 boundary-clear/未激活
  推进到 **governed-active**，全程受 L1-L4 约束。
- **具体激活哪些 L5 能力（Skill 之外的哪 1-2 个：SubAgent / MCP / Scheduler）属于 S3
  scope decision，必须由用户在 §8 open decisions 中明确，不在本草案里默认全做。**

一句话定位：

> S2 answered "can the agent reliably execute governed multi-step work?"
> S3 answers "can the agent reliably **extend** that governed work through more
> capabilities — without losing same-spine, policy, evidence, or checkpoint control?"

## 1. Roadmap constraints

- **S 系列 ≠ 代码 v1/v2/v3。** S1/S2/S3/Sn 是**产品阶段**版本，与代码内
  `v0.x`/`Phase N`/`Loop N`/`L0-L2` 历史标签无对应（`S_ROADMAP.md §1`）。
- **S3 必须继承 S1/S2 主链路。** 后续版本只能在**不推翻 S1 架构主链路**的前提下增强
  （`S_ROADMAP.md §3`）。same-spine（fake/real 仅 factory/config 层不同）是 must-not-
  regress（`AGENTS.md` Provider Rules）。
- **Roadmap 只定义五层主线，不提前承诺 S3 具体范围。** `S_ROADMAP.md §3` 明确不把
  S2/S3/Sn 写成硬性实施计划；`§5` 仅举例"扩展能力从 boundary-clear 走向 selectively-
  active"作为 S2+ 的演进方向。
- **S3 goal 是本阶段基于 baseline 的选择**，不是 roadmap 预设；它必须能从五层主线 +
  S3 baseline 推导出来，且不得越出"不推翻 S1/S2 主链路"的边界。

## 2. Inherited S3 baseline

摘要自 `S3_BASELINE_STATUS.md`（详证据见该文件，不在此复制长篇）：

- **S2 completed / archived** —— `docs/history/S2_GOVERNED_TASK_AGENT/`，release 记录
  `S2_RELEASE_SUMMARY.md`，S2-G01..G13 全 satisfied。
- **Governed task path（L4）** —— receive→plan→execute→advance→checkpoint→resume→done。
- **Task orchestration / state / progress（L4）** —— task/step status、progress %、
  当前 step、阻塞原因、side-effect-free human review/takeover seam。
- **Context / memory / checkpoint（L2）** —— task-scoped context、memory boundary、
  resume 不丢 provider-callable content、大结果摘要可恢复。
- **Tool / policy / evidence（L3）** —— 统一 mediator/dispatcher/policy 路径、
  governed tool report（allowed/rejected/failed/control + bypass detection）、
  结构化 task evidence（replay metadata，非逐字）。
- **Skill selectively-active（L5）** —— governed default-off gate
  `MY_FIRST_AGENT_S2_SKILL_ENABLE`；discovery allowed / activation default-off /
  execution gated；关闭时行为同 S1。
- **Real provider governed smoke（AC-7）** —— opt-in、key-safe、走 production path。
- **Acceptance gate（L1）** —— 区分 runtime_regression / doc_governance_debt /
  quality_debt / unknown_failure。
- **Carry-forward debt** —— TD-006（full-suite 33 guard 红）、TD-007（ruff ~451）、
  TD-001/002/003/004；均 open，约束 S3 的 release 信号策略与 evidence 深度，但**不**
  定义 S3 产品方向。
- **L5 extension 当前成熟度（S3 起点）**：Skill = governed-active；SubAgent =
  parent-mediated / side-effect-free / 未激活（wiring 最齐）；MCP = configurable
  default-off / 未默认激活；Scheduler = 已有 `ActionScheduler`/`ActionPlan` + handler
  + tests，但未在默认 loop 激活。

## 3. Candidate S3 directions

完整对比见 `_tmp_s3_goal_draft/direction_review.md`。摘要：

### Option A — L5 Extension Boundary Maturation（**selected**，见 §4）
- **Description**：把 S2 在 Skill 上验证的受控激活模式抽象为统一 extension 接入契约，
  并选 1-2 个 L5 能力进入 governed-active，受 L1-L4 约束。
- **Why it fits roadmap**：直接落在 `S_ROADMAP.md §4` 五层主线的 L5 与 `§5` 举例的
  "扩展能力逐级成熟"上；复用而非推翻 S2。
- **Pros**：roadmap 契合度最高；复用 S2 acceptance/evidence 框架；增量、可禁用、可
  回滚；验收边界清晰。
- **Risks**：若选太多 L5 会滑向"全做"（§7 non-goal）；extension 激活若绕过
  policy/evidence 会破坏 governance —— 用 §6 AC 与 §7 non-goal 约束。
- **Selected**：是（§4）。

### Option B — Full-suite Governance（测试/文档/lint 治理收敛）
- **Description**：清 TD-006 guard + 批量 TD-007 lint，让 full-suite 可作 release gate。
- **Why/Pros**：release 信号更强；长期健康。
- **Risks**：把清债当产品主线**违反** `S_ROADMAP §5` 与 S2 non-goal（S2_GOAL §8 /
  S2-G10 已定 TD-006/007 为 health/debt 信号而非产品目标），会让 S3 沦为 S2 cleanup。
- **Why not selected**：不作为 S3 产品主线；降级为 S3 内的 supporting concern /
  open decision（§8-5：TD-006 是否进 S3 release gate）。

### Option C — Task Intelligence（更强任务执行智能）
- **Description**：增强 plan 生成 / re-plan / 失败自恢复 / evidence 驱动决策（L4 深化）。
- **Why/Pros**：直接提升任务完成质量。
- **Risks**：易滑向"完整自主 / AutoGPT 式"（超出"受控"）；与 §5 点名的"扩展能力成熟"
  不如 A 直接对应；验收更难。
- **Why not selected**：不作独立主线；作为 Option A 的**配套**（reference task 组合
  extension 时顺带验证编排质量）。

## 4. Selected S3 direction

**Selected：Option A — Extensible Governed Agent Runtime。**

核心范围（scope）：

1. **Extension boundary maturation** —— 把"受控激活"从 Skill 单点扩展为可复用的
   extension 接入契约。
2. **Capability governance lifecycle** —— extension 的 discovery / selection /
   enablement / governance / evidence / disable 路径统一、可观测、可回滚。
3. **选择 1-2 个 L5 能力进入 governed-active** —— 具体是哪 1-2 个（SubAgent / MCP /
   Scheduler 的子集）由 §8 open decisions 决定；**本草案不默认全选**。
4. **保持边界** —— same-spine / task-state / policy / evidence / checkpoint 全部
   must-not-regress；任何 extension 旁路视为缺陷。

明确**不**写死：不预设"Skill 之外再加哪些"，不预设 MCP/SubAgent/Scheduler 全部进入，
不预设 S3 = 多 Agent 生态。这些是 §8 待决项。

## 5. Layer goals

> 这些是 S3 在五层主线上的层目标，约束 selected direction；不是施工步骤。

- **L1 — Runtime Spine**：**不重写** spine（must-not-regress）。只**硬化 extension
  接入契约**：extension 激活必须经 dispatcher/mediator 进入同一 runtime，fake/real
  边界仍只停在 factory/config 层；不新增第二条主链路。
- **L2 — Context / Memory / State / Checkpoint**：当 extension 参与任务时，任务上下文/
  状态/进度仍能**保存、恢复、审计**；extension 产生的中间结果纳入既有 checkpoint/
  resume 边界，不丢 provider-callable content。
- **L3 — Tools / Policy / Evidence**：extension 的能力调用**必须经过 policy gate 与
  evidence**；可被 allow/reject、可被记录、可被复盘；任何绕过 policy/evidence 的
  extension 路径视为缺陷。
- **L4 — Task Orchestration**：S3 reference task 能在 governed task path 内**组合调用
  选定的 extension 能力**完成受控闭环；编排仍走 S2 的 state model（不退化）。
- **L5 — Skill / MCP / SubAgent / Scheduler**：**选择性推进**，不全量生产化。Skill 维持
  governed-active；选定的 1-2 个能力从 boundary-clear/未激活推进到 governed-active，
  具备 metadata / enable-disable / risk / verification；未选项保持当前 boundary-clear/
  configurable/未激活状态，不退化也不强行激活。

## 6. Acceptance criteria

> 草案口径，待用户确认；刻意不过度承诺。具体阈值与 reference task 在 gap 阶段细化。

1. **AC-1（S2 不回归）**：S2 governed task path（state/orchestration/context/tool/
   evidence/progress/Skill governed-active）在 fake 确定性下不回归；targeted S2 gate
   仍通过。
2. **AC-2（至少一个新 extension 成熟）**：至少**一个** Skill 之外的 L5 extension
   boundary 从 boundary-clear/未激活推进到 **governed-active**（受控激活、可禁用、
   关闭时行为不变）。
3. **AC-3（统一接入）**：若 S3 选定多个 extension，它们必须**统一**接入 policy /
   evidence / checkpoint / task-state，而不是各自另起路径。
4. **AC-4（capability 契约）**：每个进入 governed-active 的 extension 具备
   metadata、enable/disable 开关、risk 说明、verification（测试/证据）。
5. **AC-5（reference task 闭环）**：存在一个 S3 reference task，能在受控路径内**使用
   选定的 extension** 完成 plan→execute→checkpoint→resume→done 的闭环（fake 确定性）。
6. **AC-6（real provider 覆盖）**：real provider 在 key-safe opt-in 下覆盖 S3 关键
   path（extension 参与的 governed task 主路径），与 fake/local 关键事件链路对齐。
7. **AC-7（acceptance gate 可分类）**：acceptance gate 能区分 **extension regression /
   runtime regression / known debt(TD-006/007) / unknown failure**，extension 引入的
   失败不被混入或被掩盖。
8. **AC-8（阶段治理不回退）**：`docs/current` / `docs/history` / `TECH_DEBT.md` 的阶段
   治理边界不回退（S2 归档不动、carry-forward 债不被静默关闭、S3 文档在 current 区）。

## 7. Non-goals

S3 明确**不**做：

- 不重写 S1/S2 runtime spine，不引入第二条主链路。
- 不做完整 AutoGPT 式自主代理（不追求无人监督的自主目标分解执行）。
- **不做完整多 Agent 生态**（多 Agent 协作/编排留 S4/Sn）。
- **不"Skill+MCP+SubAgent 全做"**：不一次性把所有 L5 扩展全量激活/生产化；S3 只选
  1-2 个进入 governed-active。
- 不让任何 extension 绕过 policy / evidence / same-spine / checkpoint。
- **不把 TD-006/TD-007 清理当作 S3 产品主目标**（它们是 health/debt 信号；是否进
  release gate 见 §8 open decision）。
- 不做独立 durable task ledger（S3+ 候选，非 S3 必达）。
- 不直接开始 S4/Sn，不在本 goal 里规划后续阶段。

## 8. Open decisions

以下必须由用户决定，**未决前不得在 gap 阶段当成已承诺目标**：

1. **S3 选哪 1-2 个 L5 extension 进入 governed-active？**（候选：SubAgent / MCP /
   Scheduler。baseline 事实参考：SubAgent wiring 最齐且 side-effect-free，MCP
   configurable default-off，Scheduler 有实现+handler+tests 但未在默认 loop 激活。）
2. **是否把 MCP 作为 S3 必达**，还是留作候选？
3. **SubAgent 若入选，是否只做 read-only / audit 委派**（不写文件、不改仓库），还是
   允许更宽的受控委派？
4. **Scheduler 是否 defer 到 S4/Sn**（即使它已有实现）？
5. **TD-006 是否进入 S3 release gate**（S3 是否要求 full-suite 绿，还是继续以 targeted
   gate 为产品信号）？
6. **S3 reference task 选什么**（建议延续 S2 的 repo-governed improvement 风格，但具体
   场景由用户定）？
7. **real provider 覆盖深度到哪里**（延续 key-safe opt-in；覆盖广度/分支待定）？

## 9. Next step

- **用户审阅本 `S3_GOAL.md` 草案**，确认方向（Option A）、selected scope 与 §8 open
  decisions。
- 用户批准并冻结 goal 后，**再生成 `docs/current/S3_GOAL_GAP.md`**（由 S3 baseline vs
  本 goal 推导），进入 gap loop。
- **本任务不生成 S3 gap、不进入 gap loop、不修改代码/tests、不 push。** 在 §8 未决前，
  不得把任何具体 L5 选择当作已承诺目标推进。
