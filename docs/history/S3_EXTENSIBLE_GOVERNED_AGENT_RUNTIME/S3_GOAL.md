# S3 Goal — Extensible Governed Agent Runtime

> Current document (`docs/current/`). **状态：CONFIRMED / FROZEN for S3 execution**
> （用户于 2026-06-19 确认 §8 Resolved decisions 并冻结本 goal）。本文由
> `S_ROADMAP.md`（五层主线）、`S3_BASELINE_STATUS.md`（S3 起点现状）、S2 归档与当前
> `TECH_DEBT.md` 推导而来；方向对比见 `_tmp_s3_goal_draft/direction_review.md`。
>
> 冻结含义（`AGENTS.md` goal rules）：goal 已冻结，不得因实现困难而改、不得静默收窄或
> 扩张；只有用户能批准 goal 变更。**下一步是生成 `docs/current/S3_GOAL_GAP.md`（本任务
> 不生成、不进入 gap loop）。**

## 0. Executive summary

S3 = **Extensible Governed Agent Runtime / 可扩展的受控 Agent Runtime**。核心是
**L5 Extension Boundary Maturation**：在**不推翻 S1/S2 same-spine runtime** 的前提下，
把 extension boundary 从 boundary-clear/未激活推进到更成熟的 **governed-active** 状态。

- S3 **继承** S2 的 Governed Task Agent（governed task path / state / progress /
  context-memory-checkpoint / tool-policy-evidence / Skill governed-active /
  acceptance gate），并把它们作为 must-not-regress 起点。
- S3 **不推翻** S1/S2 same-spine runtime，不引入第二条主链路。
- S3 **不**进入完整多 Agent / 完整 MCP 生态化（见 §7 Non-goals）。

**S3 selected L5 scope（已确认冻结）—— 必达 = MCP + SubAgent：**

- **MCP（必达）**：只做**受控 MCP tool source**（把 MCP 作为受控的工具来源接入 governed
  tool path），**不做完整 MCP 生态**。
- **SubAgent（必达）**：只做 **read-only / audit-first / parent-mediated** 委派；
  **不允许绕过主 Agent 执行 tool / provider / memory**。
- **Skill**：保持 S2 的 governed-active，作为 **capability contract 参考**，不作为 S3
  主新增目标。
- **Scheduler**：**defer 到 S4/Sn**，S3 只保留 boundary，不作为 S3 目标。

**S3 reference task（已确认）**：**Extension-assisted repo governance task** —— 主 Agent
承接 repo governance / code-review / gap audit 任务；过程中使用受控 MCP tool source 获取
上下文或工具能力，调用 read-only SubAgent 做 second opinion，最终由主 Agent 汇总
evidence、决策、执行或产出报告。

**TD policy（已确认）**：TD-006 进入 S3 release gate（release 前必须清到 full pytest 不
再出现 governance guard failure）；TD-007/ruff 不作为 S3 release blocker（仅 quality
debt / strategy）；不把清债当 S3 产品主目标。

**Real provider（已确认）**：覆盖 S3 reference task 的关键 path smoke（key-safe opt-in）。

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
- **S3 goal 是本阶段基于 baseline 的选择**，不是 roadmap 预设；它从五层主线（重点 L5，
  受 L1-L4 约束）+ S3 baseline 推导，且不越出"不推翻 S1/S2 主链路"的边界。

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
- **Skill governed-active（L5）** —— governed default-off gate
  `MY_FIRST_AGENT_S2_SKILL_ENABLE`；discovery allowed / activation default-off /
  execution gated；关闭时行为同 S1。S3 以此为 capability contract 参考。
- **Real provider governed smoke** —— opt-in、key-safe、走 production path。
- **Acceptance gate（L1）** —— 区分 runtime_regression / doc_governance_debt /
  quality_debt / unknown_failure。
- **Carry-forward debt** —— TD-006（full-suite 33 guard 红）、TD-007（ruff ~451）、
  TD-001/002/003/004；均 open。S3 对它们的政策见 §0 / §7 / AC-9。
- **L5 extension 当前成熟度（S3 起点，graphify 核验）**：Skill = governed-active；
  SubAgent = parent-mediated / side-effect-free / 未激活（`agent/subagent_system/*`，
  wiring 最齐）；MCP = configurable default-off（`agent/runtime_integration/
  mcp_bridge_lifecycle.py`、`mcp_tool_orchestrator.py`）；Scheduler = 已有
  `ActionScheduler`/`ActionPlan` + handler + tests，但未在默认 loop 激活。

## 3. Candidate S3 directions（决策记录 / historical rationale）

> 方向已选定（Option A，见 §4），本节保留候选对比作为决策依据。完整对比见
> `_tmp_s3_goal_draft/direction_review.md`。

### Option A — L5 Extension Boundary Maturation（**SELECTED**）
- **Description**：把 S2 在 Skill 上验证的受控激活模式抽象为统一 extension 接入契约，
  并选定 L5 能力进入 governed-active，受 L1-L4 约束。
- **Why it fits roadmap**：直接落在 `S_ROADMAP.md §4` 五层主线的 L5 与 `§5` 举例的
  "扩展能力逐级成熟"上；复用而非推翻 S2。
- **Pros**：roadmap 契合度最高；复用 S2 acceptance/evidence 框架；增量、可禁用、可
  回滚；验收边界清晰。
- **Risks 与对策**：若选太多 L5 会滑向"全做" → §0/§8 已把 scope 锁定为 **MCP + SubAgent**
  两项，Skill 维持、Scheduler defer；extension 旁路 → §5/§7 强制经 policy/evidence。
- **Selected**：是。

### Option B — Full-suite Governance（测试/文档/lint 治理收敛）
- **Description**：清 TD-006 guard + 批量 TD-007 lint，让 full-suite 可作 release gate。
- **Why not selected as mainline**：把清债当产品主线违反 `S_ROADMAP §5` 与 S2 non-goal，
  会让 S3 沦为 S2 cleanup。**处置（已消解，见 §8-5）**：TD-006 **进入 S3 release gate
  hygiene**（AC-9），但不是 S3 产品主目标；TD-007 不作 release blocker。

### Option C — Task Intelligence（更强任务执行智能）
- **Description**：增强 plan 生成 / re-plan / 失败自恢复 / evidence 驱动决策（L4 深化）。
- **Why not selected as mainline**：易滑向"完整自主 / AutoGPT 式"（超出"受控"）。
  **处置**：作为 Option A 的**配套**（reference task 组合 extension 时顺带验证编排质量），
  不作独立主线。

## 4. Selected S3 direction

**Selected & frozen：Option A — Extensible Governed Agent Runtime。**

核心范围（scope，已冻结）：

1. **Extension boundary maturation** —— 把"受控激活"从 Skill 单点扩展为可复用的
   extension 接入契约（capability contract）。
2. **Capability governance lifecycle** —— extension 的 discovery / selection /
   enablement / governance / evidence / disable 路径统一、可观测、可回滚。
3. **selected L5 scope = MCP + SubAgent（必达）**：
   - **MCP** 进入 governed-active，仅作**受控 MCP tool source**（非完整 MCP 生态）。
   - **SubAgent** 进入 governed-active，仅 **read-only / audit-first / parent-mediated**
     （不绕过主 Agent 执行 tool/provider/memory）。
   - **Skill** 维持 governed-active（contract 参考，不新增主目标）。
   - **Scheduler** defer S4/Sn（只保留 boundary，不激活）。
4. **保持边界** —— same-spine / task-state / policy / evidence / checkpoint 全部
   must-not-regress；任何 extension 旁路视为缺陷。

## 5. Layer goals

> 这些是 S3 在五层主线上的层目标，约束 selected direction；不是施工步骤。

- **L1 — Runtime Spine**：**不重写** spine（must-not-regress）。只**硬化 extension
  接入契约**：MCP tool source 与 SubAgent 委派的激活必须经 dispatcher/mediator 进入
  同一 runtime，fake/real 边界仍只停在 factory/config 层；不新增第二条主链路。
- **L2 — Context / Memory / State / Checkpoint**：当 MCP/SubAgent 参与任务时，任务
  上下文/状态/进度仍能**保存、恢复、审计**；extension 产生的中间结果（MCP tool 结果、
  SubAgent second-opinion 输出）纳入既有 checkpoint/resume 边界，不丢 provider-callable
  content。SubAgent 为 parent-mediated，不持有独立 memory 旁路。
- **L3 — Tools / Policy / Evidence**：MCP tool source 的每次调用与 SubAgent 的每次委派
  **必须经过 policy gate 与 evidence**；可被 allow/reject、可被记录、可被复盘；任何绕过
  policy/evidence 的 extension 路径视为缺陷。
- **L4 — Task Orchestration**：S3 reference task（Extension-assisted repo governance
  task）能在 governed task path 内**组合调用 MCP tool source + read-only SubAgent**
  完成受控闭环；编排仍走 S2 的 state model（不退化）。
- **L5 — Skill / MCP / SubAgent / Scheduler（选择性推进）**：
  - **MCP**：从 configurable default-off 推进到 governed-active 的受控 tool source；
    具备 metadata / enable-disable / risk / verification / evidence。
  - **SubAgent**：从 parent-mediated/未激活 推进到 governed-active 的 read-only/
    audit-first 委派；同样具备 metadata / enable-disable / risk / verification / evidence。
  - **Skill**：维持 S2 governed-active，不退化、不作为主新增目标。
  - **Scheduler**：保持当前 boundary（已实现未激活），**S3 不激活**，defer S4/Sn。

## 6. Acceptance criteria

> 冻结口径。具体阈值、reference-task 细节、清理范围在 `S3_GOAL_GAP.md` gap 阶段细化，
> 但不得削弱本节承诺。

1. **AC-1（S2 不回归）**：S2 governed task path（state/orchestration/context/tool/
   evidence/progress/Skill governed-active）在 fake 确定性下不回归；targeted S2 gate
   仍通过。
2. **AC-2（MCP governed tool source 接入）**：MCP 作为**受控 tool source** 进入
   governed-active，经 dispatcher/mediator + policy/evidence，不绕过 same-spine；
   default 行为可控、可禁用；**非完整 MCP 生态**。
3. **AC-3（SubAgent read-only/audit-first parent-mediated 接入）**：SubAgent 进入
   governed-active 的 read-only / audit-first / parent-mediated 委派；**不绕过主 Agent
   执行 tool/provider/memory**；委派经 policy/evidence。
4. **AC-4（extension capability 契约）**：每个进入 governed-active 的 extension
   （MCP、SubAgent）具备 metadata、enable/disable 开关、risk 说明、verification、
   evidence。
5. **AC-5（reference task 闭环）**：S3 reference task（Extension-assisted repo
   governance task）能在受控路径内**使用 MCP + SubAgent** 完成 plan→execute→checkpoint
   →resume→done 的受控闭环（fake 确定性）。
6. **AC-6（real provider 覆盖）**：real provider 在 key-safe opt-in 下覆盖关键 S3 path
   —— 能进入 extension-assisted governed path、能看到 extension evidence、与 fake/local
   关键事件链路对齐；不要求覆盖所有 MCP/SubAgent 分支。
7. **AC-7（acceptance gate 可分类）**：acceptance gate 能区分 **extension regression /
   runtime regression / known debt(TD-006/TD-007) / unknown failure**，extension 引入的
   失败不被混入或被掩盖。
8. **AC-8（阶段治理不回退）**：`docs/current` / `docs/history` / `TECH_DEBT.md` 的阶段
   治理边界不回退（S2 归档不动、carry-forward 债不被静默关闭、S3 文档在 current 区）。
9. **AC-9（TD-006 release hygiene）**：S3 release 前 TD-006 清理到 **full pytest 不再
   出现 governance/guard failure**（即 full-suite 的 release 判断不再被 TD-006 污染）；
   清理对齐当前 governance docs/contracts，不靠静默弱化断言。TD-007 不在本 AC 内。

## 7. Non-goals

S3 明确**不**做：

- 不重写 S1/S2 runtime spine，不引入第二条主链路。
- 不做完整 AutoGPT 式自主代理（不追求无人监督的自主目标分解执行）。
- **不做完整多 Agent 生态**（多 Agent 协作/编排留 S4/Sn）。
- **不做完整 MCP 生态**（S3 的 MCP 仅受控 tool source）。
- **不全量激活 Skill / MCP / SubAgent / Scheduler**（S3 只把 MCP + SubAgent 推进到
  governed-active；Skill 维持；Scheduler defer）。
- **不让 MCP / SubAgent 绕过 policy / evidence / checkpoint / task-state / same-spine**；
  SubAgent 不绕过主 Agent 执行 tool/provider/memory。
- 不把清债当 S3 产品主目标；**TD-006 是 release gate hygiene（AC-9），TD-007 全清不作
  为 S3 release blocker**（仅 quality debt / strategy，除非用户另行决定）。
- 不做独立 durable task ledger（S3+ 候选，非 S3 必达）。
- **不开始 S4/Sn**，不在本 goal 里规划后续阶段。

## 8. Resolved decisions

> 这些条目在草案(draft)阶段曾是 open decisions，现已由用户于 2026-06-19 **确认并冻结
> （resolved）**。后续 gap/实现以此为准，不得重新打开 S3 scope。

1. **S3 selected direction（resolved）**：S3 = Extensible Governed Agent Runtime；核心
   = L5 Extension Boundary Maturation，在不推翻 S1/S2 same-spine 前提下让 extension
   boundary 进入更成熟的 governed-active。
2. **S3 selected L5 scope（resolved）**：必达 = **MCP + SubAgent**。
   - MCP：必达，仅受控 MCP tool source，不做完整 MCP 生态。
   - SubAgent：必达，仅 read-only / audit-first / parent-mediated，不绕过主 Agent 执行
     tool/provider/memory。
   - Skill：维持 S2 governed-active，作为 capability contract 参考，不作主新增目标。
   - Scheduler：defer S4/Sn，只保留 boundary。
3. **TD policy（resolved）**：TD-006 进入 S3 release gate（清到 full pytest 不出现
   governance guard failure，见 AC-9）；TD-007/ruff 不作 S3 release blocker，仅 quality
   debt / strategy；不把清债当 S3 产品主目标。
4. **S3 reference task（resolved）**：Extension-assisted repo governance task（主 Agent
   承接 repo governance / code-review / gap audit；用受控 MCP tool source 取上下文/工具
   能力；调 read-only SubAgent 做 second opinion；主 Agent 汇总 evidence、决策、执行或
   产出报告）。
5. **Real provider coverage（resolved）**：覆盖 S3 reference task 的关键 path smoke ——
   证明 real provider 能进入 extension-assisted governed path、能看到 extension
   evidence、fake/local 与 real 关键事件链路对齐、key-safe；不要求覆盖所有
   MCP/SubAgent 分支。
6. **Non-goal boundaries（resolved）**：见 §7（不做完整 AutoGPT/多 Agent/MCP 生态、不
   全量激活 L5、不让 MCP/SubAgent 绕过 policy/evidence/checkpoint/task-state、TD-007
   全清不作 release blocker、不开始 S4/Sn）。

### Future deferred decisions（S4/Sn only，不属于 S3）

- Scheduler 进入 governed-active / 接入主 loop。
- 完整 MCP 生态（多 server 编排、动态发现生态化等）。
- 完整多 Agent 生态（多 Agent 协作/编排、可写 SubAgent 委派的扩展）。
- 独立 durable task ledger。
- TD-007 全量 ruff 清理（除非用户另行决定提前）。

## 9. Next step

- 本 `S3_GOAL.md` 已**冻结**（confirmed for S3 execution）。
- 下一步：**生成 `docs/current/S3_GOAL_GAP.md`**（由 `S3_BASELINE_STATUS.md` vs 本冻结
  goal 推导），随后进入 gap loop。
- **本任务只冻结 goal，不生成 S3_GOAL_GAP.md、不进入 gap loop、不修改代码/tests、
  不 push。**
