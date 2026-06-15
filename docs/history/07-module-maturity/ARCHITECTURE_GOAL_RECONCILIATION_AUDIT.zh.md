# Architecture Goal Reconciliation Audit

**日期**: 2026-06-15  
**性质**: audit-only 架构目标回溯审计；不是 L3 hardening、Scheduler 实现、Architecture Repair closure 或新的 repair window  
**审计基线**: `1301537` (`docs(maturity): close post-repair L3 hardening pass`)  
**代码与测试改动**: 无  
**最终判定**: **ACCEPT_CURRENT_STOP_WITH_TAXONOMY_RECONCILIATION_REQUIRED**；更精确地说，**ACCEPT_CURRENT_STOP; REJECT_15_MODULE_DENOMINATOR_AS_FUTURE_SCORECARD**

---

## 1. Executive Verdict

1. 项目目标不是普通 chat agent，也不是通用 workflow engine。最准确的分类是 **G：分阶段路线**；当前产品/架构重心是 **D（context-engineering / capability-boundary runtime）+ B（tool-calling）+ C（memory-aware）**，E（workflow/task orchestration）和 F（autonomous long-running）只应作为受证据与 owner decision 约束的后续阶段。
2. North Star 的核心身份仍成立：单进程、单一 runtime spine、安全优先、可审计、可恢复、受治理的 capability extension。它没有要求 15 个同级 runtime 模块，更没有要求所有项同时达到 L3。
3. 当前“15 模块”来自一次合理的 taxonomy 修补，但后续把 **10 个 capability/spine surface + 5 个 cross-cutting concern** 扁平化成 15 个同级 maturity 分母，造成了“模块表完整性”压力。
4. `ActionScheduler` 不是当前 runtime 核心，也不是 background async scheduler。它是一个默认 dormant、可测试注入、同步执行的 action-plan DAG executor。
5. Scheduler 的明确建议是：**SPLIT + REDESIGN + DEFER**。若必须只选一个主标签，选 **REDESIGN**。当前不删除、不接 production routing、不追求 L3；将其移入 future/dormant bucket。
6. `14/15 scoped L3 + Scheduler L2-blocked` 是对现有评分体系的诚实历史快照，但不是未来 architecture scorecard。正确结论是 **ACCEPT_CURRENT_STOP_WITH_TAXONOMY_RECONCILIATION_REQUIRED**，而不是继续追 15 项完整性。

---

## 2. Scope Lock 与方法

本轮严格锁定：

- 不改 `agent/`、`tests/`、North Star、Architecture Repair closure/roadmap；
- 不实现、接线或删除 Scheduler；
- 不创建新的 repair window，不重开 Architecture Repair；
- 不声明所有项同时达到 L3，也不声明更高成熟度等级；
- 不运行真实 provider/MCP/server，不读取 secrets/private data；
- 不提交 Graphify 输出目录，不 push。

证据优先级：

1. runtime source + executable tests：当前事实；
2. `docs/CAPABILITY_BOUNDARIES.md`、closure/retrospective、module maturity docs：治理与历史事实；
3. North Star：目标与原则，不覆盖当前代码事实；
4. Graphify：只做发现，所有 load-bearing 结论回到 source/docs/tests 核验。

---

## 3. Graphify Discovery

Graphify 查询覆盖：North Star、Architecture Repair、runtime、agent loop、dispatcher、tool、memory、provider、policy、capability、state、checkpoint、subagent、MCP、scheduler、async、`ActionScheduler`、`ActionPlan`、`ActionNode`、module maturity、trigger registry、L3 hardening、closure、goal、owner decision。

核心发现：

1. `RuntimeActionDispatcher`、`RuntimeActionRequest/Type`、`ToolRuntimeMediator`、`LoopContext` 构成 runtime 最大连接簇之一，支持 Dispatcher 作为独立 spine，而非 Agent Loop 的附属细节。
2. `ActionScheduler` 与 `RuntimeActionDispatcher` 的 Graphify 路径主要经共享 schema/type 推断；与 `core.py` 的强连接主要来自 scheduler tests，而不是 production composition root。
3. `ActionSchedulerHandler` 被 `build_phase1_dispatcher()` 注册，但注册关系只证明 registered，不证明 routed。
4. maturity/trigger/closure docs 形成高度互联的 governance 文档簇；这能证明记录完整，不自动证明用户路径存在。
5. Graphify 对 scheduler 的宽查询被测试引用放大，因此最终判断必须依赖 AST boundary tests 和真实 source call site。

源码核验后的结论：Graphify 正确提示了 Scheduler 的“有结构、有测试、缺生产消费者”状态，但不能把高连接度或高测试引用误读为 runtime 主链路。

---

## 4. Project Goal Reconstruction

### 4.1 A-G 分类

| 候选 | 判断 | 证据与解释 |
|---|---|---|
| A. 普通 chat agent | 否 | North Star 明确不是 prompt 试验场；chat 是入口，不是架构身份。 |
| B. tool-calling agent | 当前核心之一 | Tool gate、mediator、executor、dispatcher evidence 构成真实主链路。 |
| C. memory-aware agent | 当前受治理能力 | Memory read/write、policy、confirmation、checkpoint 已进入受控路径，但高级 consolidation/emergence 仍 frozen/default-off。 |
| D. context-engineering / capability-boundary agent | **当前最强身份** | 单一 spine、capability registry、policy、安全、evidence、parent control 是 North Star 和 repair 的共同主轴。 |
| E. workflow / task-orchestration agent | 未来可选 | 现有 planning 可处理 plan；`ActionScheduler` 无 production consumer，不能反向定义当前产品。 |
| F. autonomous long-running agent | 远期目标片段 | checkpoint/local resume 存在，但 background execution、cross-host resume、durable human-in-the-loop 均未形成当前产品闭环。 |
| G. 分阶段路线 | **是** | 当前 D+B+C；未来只有在真实 consumer、评测和 owner decision 出现时才扩展到受限 E/F。 |

### 4.2 一句话目标

项目应被定义为：

> 一个单进程、单一 runtime spine、可审计且可恢复的 LLM-driven agent runtime；它以受治理的 tool/capability execution 为核心，以 memory/context 为产品能力，以 policy/security/evidence 为强制边界，并只在真实需求证明后增加 bounded delegation、workflow orchestration 与 long-running autonomy。

该定义比“production-grade 通用 Agent”更可执行，因为它明确了当前核心与未来阶段，避免把所有已存在代码都提升为产品承诺。

---

## 5. 冻结文件如何形成当前结构

### 5.1 推导链

| 层级 | 推导内容 | 形成结果 |
|---|---|---|
| 目标 | 单进程、真实、可审计、可恢复的 agent runtime | 不以 chat UI、provider 或外部 framework 为中心 |
| 架构原则 | One Runtime Spine、deterministic execution、controlled side effects、single owner、governed memory、bounded subagents、stable capability interface | Core/Loop/Dispatcher/Handler/Adapter 分层；policy/evidence/security 横切 |
| 初始模块提案 | 12 项 runtime 组成 | 覆盖 Loop、Tool、MCP、Memory、SubAgent、Skill、Provider、Policy、Scheduler、State、Observability、Docs |
| Taxonomy gate 修补 | 补出 Dispatcher Spine、Security/Privacy、Capability/Config/Registry | 防止关键架构 owner 被藏进其他模块 |
| Option γ | **10 个 capability/spine surface + 5 个 cross-cutting concern** | 原意是区分“模块”与“横切关注” |
| Maturity audit | 将 10+5 扁平列成 15 项并统一使用同一等级阶梯 | 便于盘点，但造成不同性质对象共用同一 maturity ladder |

### 5.2 关键偏差

`AGENT_MODULE_TAXONOMY_DECISION_REQUEST.zh.md` 对 Option γ 的原始定义是“10 能力模块 + 5 横切关注，横切项不计入模块评分”。后续 `AGENT_MODULE_MATURITY_AUDIT.zh.md` 虽保留了“类型”列，却把 15 项统一纳入同一等级总表。

因此，当前 15 项并不是直接由最终目标必然推出的 15 个同级模块，而是：

- 一组 runtime/capability surfaces；
- 一组系统质量与治理维度；
- 一个未来能力（Scheduler）；
- 若干内部仍包含 active/deferred 双子边界的组合项。

冻结文件的形成过程总体合理，但“统一分母”不是目标的必然要求。

---

## 6. Runtime Mainline

当前 production 主链路可概括为：

```text
User/CLI
  -> core.chat()
  -> planning / confirmation / context assembly
  -> loop.run_main_loop()
  -> model decision
  -> RuntimeActionDispatcher / ToolRuntimeMediator
  -> policy gate
  -> tool or bounded capability adapter
  -> result/evidence/state update
  -> loop continuation or completion
  -> turn-end checkpoint/evidence
```

直接位于主链路的核心对象：

- Agent Loop / Core；
- Provider / Model Boundary；
- RuntimeAction / Dispatcher Spine；
- Tool System；
- State transition；
- Policy/Security/Evidence 横切控制。

条件式或受限进入主链路：Memory、Skill、MCP、SubAgent、Checkpoint/Resume。

不在默认 production 主链路：`ActionScheduler`。`core.chat(..., action_scheduler=None)` 默认不注入，`main.py` 不构造也不传入 Scheduler；loop 中只有可选 injection seam。

---

## 7. 15 项目标一致性审计

| # | 项目 | 服务目标 | 当前必要 | Runtime 主链路 | 角色 | 未来必要性 | 建议 |
|---|---|---|---|---|---|---|---|
| 1 | Agent Loop | 是 | **是** | 是 | Runtime kernel | 高 | KEEP；保持核心 |
| 2 | RuntimeAction / Dispatcher Spine | 是 | **是** | 是 | Runtime kernel / boundary | 高 | KEEP；独立 owner 正确 |
| 3 | Tool System | 是 | **是** | 是 | Atomic execution | 高 | KEEP；核心 capability |
| 4 | MCP | 是，作为外部协议适配 | 否 | 默认关闭，opt-in 后经 Tool path | Optional adapter | 中 | KEEP but scoped；不以 test 数量推 production-ready |
| 5 | Memory | 是，属于 context/memory-aware 目标 | 是，但应限于受治理子集 | 条件式 | Product capability | 高 | KEEP；active 与 frozen 子能力继续分开 |
| 6 | SubAgent | 是，属于 bounded delegation | 否 | flag/default/fallback 条件式 | Optional capability | 中 | KEEP but scoped；不是独立 runtime |
| 7 | Skill System | 是，服务 capability discovery/context engineering | 是，若项目坚持 D 身份 | 条件式进入 prompt/tool scope | Product capability | 高 | KEEP；维持 descriptor 边界 |
| 8 | Provider / Model Boundary | 是 | **是** | 是 | Runtime boundary | 高 | KEEP；adapter 而非产品中心 |
| 9 | Policy / Approval | 是 | Policy 是；production approval 否 | 横切 | Guardrail/governance | 高 | KEEP but split sub-boundaries；不同 readiness 不应合并评分 |
| 10 | Scheduler / Async | 只服务未来 E/F | 否 | **否** | Dormant/future capability | 未经 consumer 证明 | SPLIT + REDESIGN + DEFER；移出当前 active 分母 |
| 11 | State / Checkpoint / Resume | 是 | State 是；local checkpoint 对可恢复目标重要；cross-host 否 | State 在主链；resume 条件式 | Runtime infrastructure / recovery | 高 | KEEP；按 state/local recovery/future durable recovery 分层 |
| 12 | Observability / Evidence | 是 | **是**，由项目“可审计”目标直接推出 | 横切 | Evidence/governance | 高 | KEEP；作为 acceptance dimension，不是 peer capability |
| 13 | Security / Privacy | 是 | **是**，由安全优先直接推出 | 横切 | Guardrail/governance | 高 | KEEP；作为强制质量 gate |
| 14 | Capability / Config / Registry Boundary | 是 | Registry/config boundary 是；unified contract 否 | 横切/入口 | Governance/boundary | 高 | KEEP；不应按单一 runtime module 评分 |
| 15 | Docs / Guardrails | 服务 SoT 与工程治理 | 对仓库治理是，对用户 runtime 否 | 否 | Governance/evidence | 高 | KEEP；作为 repository governance scorecard，不计产品模块数 |

### 7.1 推荐的新 taxonomy

1. **Tier 1 — Runtime Kernel**：Agent Loop、Dispatcher Spine、Tool、Provider、State transition。
2. **Tier 2 — Governed Product Capabilities**：Memory、Skill；MCP/SubAgent 作为 optional adapters/capabilities。
3. **Tier 3 — Cross-cutting Acceptance Dimensions**：Policy/Approval、Observability/Evidence、Security/Privacy、Capability/Config/Registry、Docs/SoT guards、Checkpoint/Recovery quality。
4. **Tier 4 — Future/Dormant Capabilities**：Plan orchestration、background async、cross-host durable execution 等；必须有 consumer/benchmark/owner decision 才进入 active maturity。

对应 gate 也应分开：

- Runtime capability：可继续使用现有等级阶梯，但必须证明真实 consumer 与 production routing；
- Cross-cutting dimension：用 `defined -> enforced -> evidenced -> externally validated`；
- Future capability：用 `declared -> decision-ready -> consumer-proven -> activated`，不得用测试数量替代 consumer。

---

## 8. Scheduler / Async 专项判断

### 8.1 当前真实形态

`ActionScheduler`：

- 接受 `ActionPlan` / `ActionNode`；
- 使用 `depends_on` 做拓扑可执行性判断；
- 支持 halt/skip/fallback 条件与 evidence；
- 在同一 `run_main_loop()` 内、model call 之前逐节点同步推进；
- 通过注入的 executor 执行业务动作；
- 不创建 thread/process/`asyncio` task；
- 不是 cron、daemon 或 background scheduler；
- production composition root 不构造、不注入它。

因此它最接近：**graph/DAG task execution，采用同步、顺序推进的运行方式**。

### 8.2 八个问题的明确回答

1. **当前目标的核心模块吗？** 不是。
2. **未来能力吗？** 是，但仅当产品需要可恢复的多步计划执行时。
3. **是否 over-engineering？** 相对于当前零 consumer，是。DAG、condition、fallback、双 plan schema 与大量测试超过了已证明需求。
4. **是否应该删除？** 现在不应直接删除；删除需要独立 cleanup 决策、下游 import 评估和迁移计划。
5. **是否保留但标 dormant？** 是，短期如此；同时移出 active maturity 分母。
6. **是否拆分三类能力？** 是：
   - simple sequential task orchestration；
   - graph/DAG task execution；
   - background async scheduler。
7. **当前实现属于哪类？** 第二类为主，执行方式是同步 sequential；不是第三类。
8. **项目现在需要哪类？** 最多只需要第一类，而且现有 planning/current-plan/loop 已覆盖部分需求；在出现真实 consumer 前，不需要独立 DAG 或 background async。

### 8.3 最小合理形态

若未来保留并激活，最小形态应是 `ActionPlanExecutor`（概念名）：

- 同一 runtime loop 内同步执行；
- 一次只推进一个明确 step；
- 只接受受 schema 验证的 bounded plan；
- 复用 Dispatcher/Tool/Policy/Evidence，不拥有 side effect；
- 支持 cancel、halt、checkpoint handoff；
- 默认不支持后台任务、定时任务、并行 DAG、无限 retry；
- 只有真实用例证明依赖图必要时，才增加 DAG；
- background async 作为独立产品能力重新立项，不复用“Scheduler/Async”模糊名称。

### 8.4 最终建议

**SPLIT + REDESIGN + DEFER**

- **SPLIT**：把 sequential plan execution、DAG execution、background async 分成三个概念；
- **REDESIGN**：将当前 `ActionScheduler` 的目标重新定义为 bounded `ActionPlanExecutor`，避免“Async”误导；
- **DEFER**：在 consumer、benchmark、owner decision 出现前保持 dormant，不追 L3。

不建议：

- `KEEP` 原样并继续计入当前 active 模块分母；
- `DELETE` 作为本轮直接动作；
- 为达到 15/15 造 production consumer；
- 把 `ActionSchedulerHandler` 注册或 95+ tests 当作 production routing。

---

## 9. 当前 14/15 状态是否是正确终态

选择：**E. 需要重新定义 module taxonomy**。

细分判断：

- **作为历史快照**：`14/15 scoped L3 + Scheduler L2, BLOCKED_BY_DECISION/no consumer` 是诚实的，特别是明确写了 not 15/15、not highest-tier maturity。
- **作为当前阶段操作终态**：可以停止继续 hardening，不需要做 Scheduler L3。
- **作为架构目标终态**：不充分。它仍暗示 15 项是同级且 Scheduler 是唯一“未完成模块”，掩盖了 taxonomy 混合与 scoped-L3 语义差异。
- **正确收口方式**：保留 closure 作为历史记录；新 taxonomy 将 active runtime、governance dimensions、optional capabilities、future/dormant capabilities 分开，不再追求 15/15。

---

## 10. 冻结文档有效性

### 10.1 仍然有效

- North Star 的使命核心：单进程、单一 spine、安全优先、可审计、可恢复；
- Core/Loop/Dispatcher/Handler/Adapter 边界；
- controlled side effects、parent control、governed memory、stable capability interface；
- Architecture Repair closure 与 retrospective 作为历史证据；
- `CAPABILITY_BOUNDARIES.md` 对 declared/registered/routed/dormant/deferred 的区分；
- closure 对 no 15/15、no highest-tier maturity、no new repair window 的诚实边界。

### 10.2 需要未来通过新决策澄清，而非本轮修改

- North Star 是 `Draft v0`，其中“agent 调度、子 agent 编排、长任务恢复”的措辞容易被读成当前产品全部必须实现；应在未来决策中增加阶段边界。
- `Scheduler / Async` 命名与真实同步 DAG executor 不一致。
- Option γ 原本区分 10 capability + 5 cross-cutting，maturity audit 后被扁平化。
- 同一个 maturity ladder 不适合同时衡量 runtime capability、docs guard、security quality 与 dormant future capability。
- `runtime_decision_frame.py` 的 scheduler `why_partial` 仍声称缺 contract/core-loop tests，已被后续测试事实反驳；它是静态治理元数据漂移的例子。
- `ActionSchedulerHandler` evidence 写入 `production_capability=True`，与 dormant/not-routed 事实存在语义张力；不能据此声称 production capability。

结论：冻结文档不是失效，而是 **原则有效、历史有效、taxonomy/maturity 解释需要新文档分层**。本轮不修改任何冻结文件。

---

## 11. 两侧风险

### 11.1 删除 Scheduler 的风险

- 丢失已形成的 `ActionPlan`/`ActionNode` schema、依赖排序和 evidence 契约；
- 破坏 tests、planner handoff seam 或潜在下游 import；
- 未来若出现可恢复多步执行需求，需要重新实现 bounded plan executor；
- 可能把“当前无 consumer”误判成“永远无价值”。

风险结论：不足以支持本轮删除，但足以要求将其从 active product taxonomy 降为 dormant/future。

### 11.2 强行做到 L3 的风险

- 为指标制造 consumer，违反目标优先原则；
- 在现有 planning/current-plan/loop 旁形成第二套执行语义；
- 将同步 DAG 错称 async/background，造成 policy、docs 与产品承诺漂移；
- 扩大 retry/idempotency/checkpoint/approval 设计面，重新打开已关闭 repair 边界；
- 高测试数量继续掩盖缺少用户需求、真实调用与 benchmark。

风险结论：显著高于保持 dormant；不得为 15/15 推进。

---

## 12. 是否存在“为了模块表完整而保留无用模块”

存在 **指标层面的倾向**，但尚不足以断言所有相关代码都应删除：

- Scheduler 是最明显案例：代码和测试先于 consumer，且被纳入 15 项 denominator；
- `mcp_tool_orchestrator` 明确是 harness-only，但 MCP 本身仍有 opt-in registration/mediator 路径，不能把整个 MCP 判成 test-only；
- SubAgent、Skill、Memory 的部分高级路径是 default-off/frozen/scoped，不应以模块总名的 L3 覆盖所有子能力；
- Docs/Security/Observability/Capability Boundary 是必要治理维度，但不是用户 runtime 的 peer modules。

因此问题不是“15 项里有 5 个毫无价值”，而是“把不同性质的 15 项放进同一完成度竞赛”。

---

## 13. Architecture Reviewer Findings

**Verdict: ACCEPT_WITH_RECONCILIATION_REQUIRED**

Architecture strategist 的结论与本审计主线一致：当前目标架构整体成立，Architecture Repair 不需要重开，但 taxonomy、maturity 标签和 Scheduler 定位需要文档层面对账。

Findings:

1. North Star / Architecture Repair 的核心原则仍有效：单一 runtime spine、capability boundary、policy/security/evidence、可审计和可恢复，仍是当前架构判断的上位约束。
2. 当前项目不是普通 chat agent，也不是 workflow engine；更准确的描述是分阶段路线，当前阶段聚焦受治理 capability runtime。
3. 当前 active architecture 应聚焦 governed capability runtime + tool-calling + memory-aware context engineering；workflow/task orchestration 和 long-running autonomy 只能作为后续阶段。
4. 15 项扁平 maturity denominator 需要重新解释。原始 Option γ 更接近 10 个 capability/spine surface + 5 个 cross-cutting concern，后续扁平化造成了不必要的 15/15 压力。
5. Scheduler 当前不应激活为 L3，也不应被视为当前 runtime 主链路的一部分。
6. Scheduler 应被移到 future/dormant capability bucket，等待真实 consumer、owner decision 和重新设计。
7. 不需要重开 Architecture Repair；closure 可以保留为历史治理事实。
8. 不需要修改生产代码；本轮处置应保持 docs-only reconciliation。

Disposition: 接受该 reviewer 对 taxonomy reconciliation 的要求。本审计将当前 stop 判定限定为“hardening 可以停止”，同时明确 15-module denominator 不能继续作为未来成熟度指标。

---

## 14. Adversarial Reviewer Findings

**Verdict: REJECT_15_MODULE_MATURITY_AS_FUTURE_ARCHITECTURE_SCORECARD**

**P0: None**

Adversarial reviewer 没有要求重开 Architecture Repair，也没有要求立刻修改生产代码；其主要攻击点集中在“15 模块完整性 / 14/15 scoped L3”不能继续被当成未来架构成熟度结论。

P1 / High-value findings:

1. 不能继续用“15 模块完整性 / 14/15 scoped L3”作为架构成熟度结论；它最多是历史评分快照。
2. Scheduler 不应激活；应移出当前 active module denominator，归入 future/prototype/dormant bucket。
3. `ActionPlan` contract 被 active planner 反向绑定到 `action_scheduler.py`，说明命名和边界需要未来整理；active planning contract 不应长期寄居在 dormant Scheduler 文件里。
4. Scheduler main-path evidence 是 test harness injection，不是 production route。当前 `core.py` / main path 不构造、不注入 `ActionScheduler`。
5. `ActionScheduler` 的 arbitrary callable executor 如果未来激活，可能绕过 One Runtime Spine / Dispatcher / Policy；任何未来 activation 都必须先完成 runtime boundary redesign。
6. 当前 closure 作为历史快照可以保留，但不能作为未来 architecture scorecard。

Disposition:

1. 接受 reviewer 对 15-module denominator 的攻击。
2. 接受 Scheduler 移入 future/dormant bucket。
3. 不在本轮删除或实现 Scheduler，也不接 production routing。
4. 将 `ActionPlan` contract placement 与 callable executor 风险记录为 Module Taxonomy v2 / Scheduler redesign 输入。

---

## 15. Recommended Next Step

下一步不是实现 Scheduler，而是新增一个独立、docs-only、owner-approved 的 **Module Taxonomy v2 Decision**：

1. 锁定四层 taxonomy：Runtime Kernel / Governed Product Capabilities / Cross-cutting Acceptance Dimensions / Future-Dormant Capabilities；
2. 将 Scheduler 从 active module denominator 移到 Future/Dormant；
3. 将 `Scheduler / Async` 拆成 sequential plan execution、DAG execution、background async 三个概念；
4. 为三类对象定义不同 maturity/activation gate；
5. 保留现有 closure 为历史快照，不回写、不重开 Architecture Repair。

只有未来出现真实 consumer、可复现用户场景、benchmark 和 owner activation decision，才启动 Scheduler 设计审查；第一候选是最小同步 `ActionPlanExecutor`，不是 background scheduler。

---

## 16. Final Audit Verdict

**ACCEPT_CURRENT_STOP_WITH_TAXONOMY_RECONCILIATION_REQUIRED**

- 停止 L3 hardening 是正确的；
- Scheduler 保持 L2/dormant 是正确的；
- 15/15 不是目标；
- 14/15 是历史评分结果，不是未来 architecture scorecard；
- 冻结原则继续有效，但 module taxonomy 必须按目标重新分层；
- 本轮不产生任何 runtime、test、Scheduler 或 Architecture Repair 状态变化。
