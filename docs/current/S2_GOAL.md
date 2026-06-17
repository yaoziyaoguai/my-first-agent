# S2 Goal — Governed Task Agent

> Current authoritative document (`docs/current/`). S2 目标定义。本文为**草案，
> 待用户确认后冻结**（见 AGENTS.md goal rules：goal 不得因实现困难而改、不得被
> 静默收窄或扩张）。本文不展开实施步骤；可验收的差距清单见 `S2_GOAL_GAP.md`
> （待用户确认本 goal 后再生成）。S2 起点现状见 `S2_BASELINE_STATUS.md`。

## 0. Executive summary

S1（Baseline Usable Product）已完成，S2 继承 S1 baseline 起步。**S2 是大版本，不是
S1 cleanup、不是纯测试治理、不是文档重排。** S2 的目标是 **Governed Task Agent /
受控任务型 Agent**：把 FirstAgent 从 S1 的「可以聊天、调用工具、checkpoint」升级为
一个**可执行、可恢复、可观测、可审计的受控多步任务 Agent** —— 以同一 runtime spine
承接一个真实多步任务：构建上下文、形成计划、推进步骤、调用工具、保存状态、恢复执行、
输出证据，并让人类可以审计和接管。S2 主战场是 L2/L3/L4 的协同与产品化，并让 L5 中
**至少一个**扩展能力进入受控激活路径，但只做受控接入，**不做 S3 级生态化**。

## 1. Positioning

- S2 是 S 系列中 S1 之后的**第一个大版本**：S1 证明「能作为 baseline usable product
  运行」，S2 回答「能否可靠地执行受控的多步工作」。
- **S1 → S2 的跃迁**：从「单链路能力各自可用 + L5 仅边界清楚」，走向「同一条链路把
  一个真实任务从接收到交付端到端跑通，并让人能审计/接管」。
- **S2 与 S3 的边界**：S2 只让**一个** L5 能力受控激活；S3 才是多 Agent / Skill-MCP
  生态化。S2 不做 S3。
- **S2 不是**：旧 `v1/v2/v3`、`Phase N`、`Loop N` 等代码标签的延续，也不是 demo /
  sprint / 小阶段。S 系列与代码内旧版本标签无对应关系（见 `S_ROADMAP.md §1`）。

一句话定位：

> S1 solved "can the agent run as a baseline usable product?"
> S2 answers "can the agent reliably execute governed multi-step work?"

## 2. Inherited baseline

S2 起点能力来自 `S2_BASELINE_STATUS.md`（摘要，不复制长篇证据）：

- **Same-spine runtime（L1）**：单一入口 + runtime loop；fake/real 共享同一 spine
  （仅 factory/config 层不同）。
- **Fake/local 确定性验收**：`tests/golden_e2e` 等为 fake 确定性基线（S1 AC-1 green）。
- **Real provider smoke（L1）**：opt-in、key-safe，S1 G-03 已通过。
- **Checkpoint/resume（L2）**：含大结果摘要 resume 形态已验证（G-07b）。
- **最小多步任务（L4）**：legacy Plan 路径 plan→advance→resume→done 已验收（G-12）。
- **Evidence baseline（L3）**：per-session `events.jsonl` 路径骨架可观测（G-10）。
- **Config 卫生**：`config/config.yaml` untracked + gitignored，真实 key 仅在本地
  ignored 文件，模板 `config.example.yaml` 在仓库（G-15）。
- **Dormant L5 boundaries**：Scheduler dormant；MCP/SubAgent V0 configurable
  default-off；Skill experimental —— 边界清楚，激活留 S2（G-13/G-14）。
- **已知 caveat**：full-suite 因 TD-006 guard 测试红；`ruff` 因 TD-007 红均非 runtime
  回归，不阻塞 S2 起步。

继承基线是 must-not-regress：S2 的任何增强都不得回退上述 S1 已满足的能力。

## 3. S2 target state

S2 完成后，FirstAgent 能以同一 runtime spine 承接一个真实任务，端到端：

1. **receive task** —— 接收一个有明确目标的任务（reference task 待 §9-1 确认）。
2. **construct task context** —— 构建任务级上下文（与闲聊上下文区分）。
3. **propose / maintain plan** —— 形成并维护计划与步骤。
4. **execute steps** —— 在 runtime loop 内推进步骤。
5. **call tools through governed path** —— 工具调用统一走 mediator/dispatcher/
   policy/evidence，不绕过主链路。
6. **persist checkpoint/state** —— 任务状态与进度可持久化。
7. **resume after interruption** —— 中断后可恢复，且 resume 不丢 provider-callable
   content 与关键上下文。
8. **record evidence** —— 每一步的决策、工具调用、失败、恢复都可观测。
9. **expose progress and result** —— 人可看到任务进展与阻塞点。
10. **allow human review / takeover** —— 人可以审计一次任务并在需要时接管。

这个状态是「受控」的：每一步都经过 governed path、可被 policy 约束、可被 evidence
记录、可被禁用/回滚。

## 4. Layer goals

### L1 — Runtime Spine hardening

- **不重写 runtime spine**。S1 same-spine 是 must-not-regress。
- **强化 fake/real parity**：让 S2 acceptance 能区分 runtime regression / doc
  governance debt / quality debt，不再把 TD-006 的红混进 runtime 验收信号。
- **入口与 provider boundary 更稳定**：fake/real 边界继续只停在 factory/config 层。
- 不引入第二条主链路（见 Non-goals §6）。

### L2 — Context / Memory / State / Checkpoint

- **明确 task context / memory / state / checkpoint / evidence 的职责边界**，避免
 互相串用。
- 支持**任务级上下文构建**（区别于单轮闲聊）。
- **resume 后不丢 provider-callable content**（继承并固化 S1 G-07b 结论）。
- 大结果摘要可恢复（不把 raw 大结果塞进 checkpoint，但 resume 形态可用）。
- **memory 写入/读取需要受控**：recall/retain/proposal 走显式路径，可被 policy/
  evidence 观测。

### L3 — Tools / Policy / Evidence

- **工具调用统一走 mediator / dispatcher / policy / evidence**；任何旁路都视为缺陷。
- **tool result 可摘要、可恢复、可审计**。
- **policy gate 清晰**：两 provider 模式下 gate 行为一致，决策可被 evidence 解释。
- **evidence 能支撑人类复盘一次任务**：包括工具、决策、失败、恢复（不止路径骨架）。

### L4 — Task Orchestration / State Machine / Progress Tracking

- 从 S1 的 **legacy Plan 最小多步**升级为正式的 **task orchestration**：明确 task
  state / step state / progress / failure / resume / done。
- 任务状态机可被 checkpoint 持久化并可恢复。
- **人可以看到任务进展和阻塞点**（progress + 当前 step + 阻塞原因）。
- 不要求独立 durable task ledger 作为 S2 硬目标（可保留为 S3+，见 §6/§8）。

### L5 — Skill / MCP / SubAgent / Scheduler selectively-active

- **至少选择一个 L5 能力进入受控激活路径**（具体哪个由 §9-2 决定）。
- 激活**不绕过 S1 same-spine runtime**：必须经 dispatcher/mediator，不能另起一条
  agent 主链路。
- 必须经过 **policy / evidence**：委派/调用可被 gate 约束、可被 evidence 记录。
- 必须**可禁用、可回滚、可验收**：default-off，不激活时行为与 S1 一致。
- **不做全量生态化**：不一次性生产化所有 L5；不做 S3 级多 Agent / Skill-MCP 生态。

## 5. Acceptance criteria

S2 视为达成，当且仅当（草案口径，待用户确认）：

1. **AC-1 任务闭环**：存在一个真实多步任务 reference task，能在 fake 模式确定性走完
   `start → plan → execute → checkpoint → resume → done`。
2. **AC-2 task state / progress / step status**：任务有明确的 task state / step
   state / progress / failure / resume / done，且人可观测当前进展与阻塞点。
3. **AC-3 context/memory/checkpoint/evidence 边界**：四者职责边界清楚；resume 后不丢
   provider-callable content 与关键上下文；memory 写入/读取受控。
4. **AC-4 governed tool path**：所有工具调用统一走 mediator/dispatcher/policy/
   evidence，不绕过主链路；tool result 可摘要/可恢复/可审计。
5. **AC-5 任务级 evidence**：evidence 能支撑人类复盘一次任务，覆盖工具、决策、失败、
   恢复（不止路径骨架）。
6. **AC-6 L5 selectively-active**：至少一个 L5 能力受控激活，并有 policy/evidence/
   disable boundary；不激活时行为与 S1 一致；激活不绕过 same-spine。
7. **AC-7 fake/real 覆盖**：fake/local 覆盖全部关键 S2 流程（确定性）；real provider
   在 key-safe opt-in 下覆盖 reference task 的关键路径。
8. **AC-8 acceptance gate 分类**：S2 acceptance gate 能明确区分 runtime regression /
   doc governance debt / quality debt，不把 TD-006/TD-007 的红混进 runtime 验收信号。

已由用户确认纳入 S2 acceptance：

9. **AC-9 human review / takeover**：人可在任务执行中看到任务进度、证据、失败
   原因，并可在阻塞点接管、停止或继续。
10. **AC-10 quality / debt governance**：S2 必须能区分 runtime regression、doc
    governance debt、ruff/full pytest quality debt，不能把所有红点混成一个不可判断的失败。

## 6. Non-goals

S2 明确**不**做：

- 不推翻 S1 runtime，不引入第二条主链路。
- 不让 SubAgent/MCP/Skill/Scheduler 绕过主 runtime。
- 不一次性生产化所有 L5（只激活一个，受控接入）。
- 不把 full ruff/pytest 全清零作为 S2 **产品目标**（见 §8；债务可与 S2 并行清理但不
  等同于产品目标）。
- 不把 S2 做成纯测试治理或文档重排。
- 不做独立 durable task ledger 作为 S2 硬目标（可留 S3+）。
- 不做 S3 级多 Agent / Skill-MCP 生态。

## 7. Boundaries and constraints

- `docs/current/` 是 S2 current context；S1 已归档至
  `docs/history/S1_BASELINE_USABLE_PRODUCT/`，仅作 evidence，非 routing authority。
- `TECH_DEBT.md` 是债务入口；**S2 gap 由 baseline vs 本 goal 生成**（在 `S2_GOAL_GAP.md`
  ，本任务不生成）。
- `S2_GOAL_GAP.md` 是 S2 backlog；gap 状态只能按 baseline、本文目标与用户决策更新。
- **real provider 可用于验收，但必须 key-safe**：opt-in、不读取/打印/复制/移动/提交
  secret、不修改 ignored `config/config.yaml`、不创建 `.env`。
- **config/secret 不得泄露**：延续 S1 G-15 边界。
- S2 与代码内 `v1/v2/v3`、`Phase N`、`Loop N` 等标签无对应关系。

## 8. Relation to technical debt

- **TD-006（guard/governance 红）/ TD-007（ruff 红）是 S2 baseline 的质量债**，不等同
  于 S2 产品目标。它们可作为 S2 并行的 cleanup gap，但不应让 S2 沦为「只清债」。
- 某些债**可以**成为 S2 gap（例如：AC-8 要求 acceptance gate 能分类债务，这隐含需要
  清理 TD-006 中阻塞信号的部分）。
- 某些债**应留到 S2/Sn cleanup**（例如 TD-007 ruff 全清、TD-003 dead-code 删除）。
- TD-001（evidence 正文保真）/TD-004（pending-tool 预览）是否进 S2 取决于 AC-5 对
  「任务级 evidence」的要求深度（§9-5 open decision）。
- **不要把所有技术债都塞进 S2 goal。** 债务分配在 gap 阶段按 baseline vs goal 决定。

## 9. Resolved decisions

以下 S2-G01 open decisions 已由用户在 2026-06-17 确认，后续 gap loop 以此为准：

1. **Reference task**：采用 **Repo-governed improvement task**。FirstAgent 应能承接真实项目内任务，从读取 S2 gap / docs / code evidence 开始，制定 plan，执行小范围修复或审计，调用工具，保存 checkpoint，resume，记录 evidence，输出结果/commit；不选择纯聊天任务或复杂外部业务任务。
2. **L5 selectively-active 选择**：首个 S2 L5 选择 **Skill**。Skill 作为受控任务能力包进入 S2；不得绕过 S1 same-spine runtime、policy/evidence，必须可关闭、可回滚、可验收。MCP/SubAgent/Scheduler 不作为首个 S2 必达激活目标。
3. **Full pytest / ruff policy**：S2 不要求 full pytest 和 ruff 全绿作为产品目标。S2 release gate 以 targeted S2 acceptance gate 为准；full pytest / ruff 作为 health/debt signal 分类、记录、逐步治理；TD-006 进入 S2 cleanup，但不得吞掉 S2 产品目标。
4. **Real provider coverage**：real provider 覆盖 reference task 的 smoke / E2E 主路径，证明 real provider 能进入 governed task path、产生 evidence、与 fake/local 对齐关键事件链路；不要求所有分支、所有测试都用 real provider 覆盖；必须 key-safe。
5. **Memory / context / evidence depth**：S2 做 task-level context / memory / state / checkpoint / evidence；task context 清楚，checkpoint/resume 不丢关键 provider-callable content，tool result 可摘要且可恢复，evidence 能支撑人类复盘任务，memory 读写受控；不做长期人格记忆、复杂 self-evolving memory、多 Agent 共享记忆或大型知识库。
6. **AC-9 / AC-10**：纳入 S2 acceptance。AC-9 为 human review / takeover；AC-10 为 quality/debt governance。

## 10. Next step

- S2-G01 已解锁；后续按 `S2_GOAL_GAP.md` 推荐顺序进入 gap loop。
- 不得借本决策扩大 S2：首个 L5 仅 Skill；MCP/SubAgent/Scheduler 保持后续候选。
- 每个 gap 仍需 focused mini-run、验证、更新 backlog/work log，并独立提交。
