# Current Architecture Repair Roadmap (v3 — theme-organized Current→Target migration)

> 状态：active — 按架构主题组织的 Current→Target 迁移路线图
> 重写日期：2026-06-11
> 上位依据（本轮冻结，不修改）：`docs/architecture/ARCHITECTURE_NORTH_STAR.zh.md`
>   sha256 `c73c2b3dbe926f30834a5d9ab20155cc947ab27158339a7c8b221d0d80568cde`
> 权威分轴：North Star = Target / Principle authority；production code + 可执行测试
>   = Current Runtime Fact authority。二者冲突时写成 Current→Target gap，
>   不得改 North Star 迁就代码，也不得把 Target 伪装成 Current。
> 本轮性质：**只重写本 Roadmap**。未改 North Star、production code、tests、
>   audit delta、capability/status docs、现有 plans、AGENTS.md；未 add/commit/push。
> 本文件不是 implementation plan，不含代码 diff，不生成 goal 命令。

---

## 0. 阅读说明：内容分类

每个 item 显式归入下列状态，并区分七类内容（Current Fact / Target / Active
Migration / Accepted Deferred / Open Decision / Non-goal / Completed History）：

| Status | 含义 |
|---|---|
| `completed` | 已完成，证据齐全 → 移入 §10 History |
| `active` | 当前在做或下一批主线 |
| `protected_pending` | 已落地、靠测试保护、边界不得回退 |
| `documented_pending` | 仅需文档/口径对齐，不动代码逻辑 |
| `accepted_deferred` | 已治理的延期；无当前消费者，不建设 |
| `blocked_by_decision` | 等用户/owner 决策，不擅自裁决 |
| `move_to_history` | 完成项归档 |

优先级：**P0** 安全/数据丢失/核心路径不可运行/未治理第二 Runtime/权限或证据边界失效；
**P1** North Star critical gate 低于目标/生产主路径明显偏离/双主路径或关键迁移未完成；
**P2** supporting 维度缺口/SoT ownership/Golden E2E/文档一致性/扩展成本/迁移债；
**P3** 已治理兼容/frozen/future capability/低风险文档修正。

> 每个 active item 绑定 North Star principle，并含 Current / Target / Gap /
> Repair / Non-goal / Dependencies / Acceptance / Rollback / Owner / Exit。

---

## 1bis. Git / 文档 Baseline（重写时刻）

- branch：`chore/architecture-repair-2026-06`
- HEAD：`8fa8ce7`
- dirty tracked：`AGENTS.md`（pre-existing，本轮不碰）
- untracked：`.claude/settings.json`、`docs/architecture/ARCHITECTURE_NORTH_STAR.zh.md`、
  `docs/plans/2026-06-12-001-...md`
- North Star sha256（冻结）：`c73c2b3dbe926f30834a5d9ab20155cc947ab27158339a7c8b221d0d80568cde`
- Roadmap sha256（重写前）：`d83bc60639364f0ba94f3d8dcaf030f5b98edc8842bbdbf87996f74b5ff5d82a`
- 本轮：no git add / no commit / no push。

---

## 2. old(v2)→new(v3) 处置矩阵

| 旧项 | 处置 | 新 ID | 说明 |
|---|---|---|---|
| V1 safe metadata 扫描迁移 | REWRITE → ownership 问题 | **SPA-1** | D1/D2/D3 边界已迁移；下一问题是 masking owner，不是继续机械扫 call site |
| V2 evidence/TargetCatalog extraction | **MOVE_TO_HISTORY** | **H-1** | 已完成（`8be4dcb`）+ extraction 测试锁；保留证据 |
| V3 SubAgent 多路径 | REWRITE + 合并 | **SA-1** | 升级为 V0 production-path completion |
| V4 capability docs drift | REWRITE → Documentation/Acceptance | **GE-2** | 产出可复现 diff table，code/test 决定 Current |
| V5 legacy skill tombstone wording | MERGE → Compatibility | **CR-2** | P3 doc-align |
| V6 memory consolidation/emergence | MERGE → Memory Governance | **MEM-1** | P3，保持 frozen/env-gated 真实描述 |
| V7 TUI/local_demo | MERGE → Compatibility（do-not-touch） | **CR-3** | 仅可选 1 行 compat label |
| S1 config 入口 | KEEP → P2 design spike | **CM-1** | import-boundary inventory |
| S2 mediator thickness | **REMOVE_AS_OBSOLETE** | — | 无耦合证据，纯 cosmetic；do-not-split |
| S3 core/loop thickness | **REMOVE_AS_OBSOLETE** | — | helper 结构已存在；do-not-split |
| S4 tests 重组/规模 | **REMOVE_AS_OBSOLETE** → Golden E2E 取代 | **GE-1** | 重组是 churn；真实缺口是 Golden E2E |
| S5 stale docs refs | MERGE → Documentation/Compatibility | **CR-4** | P3 doc-only |

> 新增（无对应旧项）：**RS-1**（tool mediated-execution topology alignment）、
> **CM-2**（unified Capability Contract，deferred）、**CR-1**（action_scheduler governance）、
> **SPR-1**（state/resume deferred）、**EOE-1**（cost field deferred）、**GE-3**（rubric re-score）。

---

## Theme 1 — Runtime Spine

### RS-1 — Tool mediated-execution topology alignment  ·  P2  ·  `active`

- **North Star principle**：B（One Runtime Spine）、F（Controlled side effects）。
- **Current fact**：业务 tool 的 TOOL_GATE / TOOL_RESULT 经
  `tool_runtime_mediator.py:_route_gate(1105)` / `_route_result(1214)` 走
  `dispatcher.route_from_runtime_loop`；真实执行在 `execute_single_tool`
  (`tool_executor.py`)，由 mediator 在 gate 之后调用；TOOL_INVOKE 故意
  evidence-only（`tool_invoke.py:14-15`，`_route_invoke` 用 record_evidence
  防双重执行）。即 **gate/result/evidence 在 spine 上，execution 是 mediated**。
  live `core.chat` 始终构建 `_phase1_dispatcher`（`core.py:840`）并注入 loop
  （`core.py:1184`）；`response_handlers.py:418` 的 direct-execute 仅 meta-tool
  或 dispatcher=None（测试）可达，非业务主路径第二条线。
- **Target state**：North Star §5/§7 的 topology 文字与“mediated execution 是
  受统一 Runtime 治理的合法拓扑”一致；mediated execution 被显式承认，而不是
  被描述成“execute 必经 Handler/Adapter”。
- **Gap / failure mode**：North Star §7 layer 表把 Tool side effect 归到
  Handler/Adapter，与真实 mediated 执行不符；读者据 §7 评 PR 会误判 mediator
  “越层”。这是 **doc topology drift**，非代码缺陷。
- **Repair direction**：(1) 核验 gate/result/evidence/provenance 是否统一治理
  （已有 31 个 boundary tests 通过 + `test_mediator_route_invoke_*`）；
  (2) 若需修正 North Star topology 文字，**另行提交 North Star amendment 提案**，
  本轮不改 North Star。
- **Non-goals**：不把 `execute_single_tool` 搬进 dispatcher handler（会复活
  双重执行）；不写第二条 tool execution path；不动 mediator 行为。
- **Dependencies**：无（核验先行）。amendment 需用户批准。
- **Acceptance evidence**：boundary tests 持续 green；一份 “mediated-execution
  是 governed topology” 的说明 + （若采纳）North Star amendment 记录。
- **Rollback boundary**：纯文档/核验，无代码改动可回滚。
- **Owner**：`core.py`/`tool_runtime_mediator.py` 维护者（待指派）。
- **Exit condition**：North Star topology 文字与真实 mediated execution 一致，
  且 boundary tests 锁定 gate/result/evidence 统一治理。

> RS 主线后续（V0 路由对 spine 的影响）见 **SA-1**。

---

## Theme 2 — Capability Model: Tool / Skill / MCP

### CM-1 — Config 入口 import-boundary spike  ·  P2  ·  `active`

- **North Star principle**：K（Stable capability interfaces）。
- **Current fact**：`config.py` / `simple_config.py` / `profiles.py` /
  `local_config.py` / `mcp_config*.py` 并存（均实测存在）。
- **Target state**：明确每个 config 入口的 import boundary 与调用面，判断是否
  真有分散调用需收敛，或仅需文档说明边界。
- **Gap / failure mode**：入口数量与“是否应收敛”未定；可能存在隐性多入口耦合。
- **Repair direction**：用可复现命令列出所有 import boundary（spike），再决定；
  不预先重构。
- **Non-goals**：不合并 config 模块、不改 provider 选择逻辑、不动 `.env`。
- **Dependencies**：无。
- **Acceptance evidence**：一张 config import-boundary inventory 表 + 收敛/保留结论。
- **Rollback boundary**：spike 产出文档，无代码改动。
- **Owner**：config 维护者（待指派）。
- **Exit condition**：inventory 完成且“收敛 or 保留”有结论。

### CM-2 — Unified Capability Contract  ·  P3  ·  `accepted_deferred`（Open OD-2）

- **North Star principle**：K。
- **Current fact**：Tool（`tool_registry.py` ToolRegistryEntry）、Skill
  （`skill_system/`，入口 tombstone `skills/__init__.py`）、MCP
  （`mcp_tool_orchestrator.py` 包装为 tool）各自 schema；`idempotency_key` /
  `cost_hint` / `latency_hint` 仅存在于 North Star 文字，无任何 .py 实现。
- **Target state**：见 North Star §9 / OD-2——三者是否共享统一 Capability
  Contract，**待用户决定**。
- **Gap / failure mode**：无当前跨三者的消费者；现在建设属投机抽象。
- **Repair direction**：保持 Open；出现真实跨 Tool/Skill/MCP 消费者后再设计。
- **Non-goals**：不为“像某框架”引入统一 Contract；不加无消费者的 schema 字段。
- **Dependencies**：OD-2 决策。
- **Acceptance evidence**：n/a until decided。
- **Rollback boundary**：n/a。
- **Owner**：项目 owner（决策）。
- **Exit condition**：OD-2 被裁决。

---

## Theme 3 — SubAgent Governance

### SA-1 — SubAgent production-path completion (V0 wiring)  ·  P1  ·  `active`

- **North Star principle**：J（Bounded subagents）、B（One Runtime Spine）。
- **Current fact**：
  - V0 `SubAgentV0Handler` 已 **registered + contract-verified**
    （`phase1_hook.py:179`，dispatcher 12/12 dispatch tests pass），但
    **未 production-routed**。
  - live CLI/NL delegation = **L1-attempt → direct inline-local fallback
    (local_fake)**（`core.py:2015` 尝试 L1 handler，`subagent_inline.py:37`
    `execute_subagent_delegation` 以 `execution_mode="local_fake"` 落地）。
  - registered **L0 handler** 与 **direct inline-local fallback** 是两条
    *不同* 路径（用户裁决 #5）。
  - L1-attempt 当前用 `dispatcher.route()`（direct provenance），**不是**
    `route_from_runtime_loop()`（`core.py:2029`），缺 runtime-loop provenance。
- **Target state**（用户裁决 #2/#3/#6/#7）：core production caller 路由到 **V0**；
  inline-local 仅作为 **受控 fallback**；V0 wiring + fallback + observability +
  rollback 全部验证后，再退出无效 L1-attempt。V0 是目标 production SubAgent
  Runtime path。
- **Gap / failure mode**：生产主路径偏离目标（V0 未路由）；Subagent critical
  gate 无法到 3；L1 dispatcher 路径缺 runtime-loop provenance。
- **Repair direction**（本 Roadmap 只定义迁移，**不实施**；以下为迁移须满足的
  验收契约，不在本轮执行）：
  1. live V0 boundary/integration test 作为验收契约——
     `tests/runtime_integration/test_subagent_v0_runtime_boundary.py` **已存在**；
     本轮仅确认其定义 live-path 覆盖契约，**不在本轮跑通/实现**，留待 wiring 窗口。
  2. policy / tool / context / trace 继承经 V0 验证——验收须含一个断言
     “child 继承 parent budget/permission/tool subset/trace id” 的 focused test
     （契约定义，不在本轮实现）。
  3. fallback behavior 明确（inline-local 何时、如何作为受控 fallback）；
  4. evidence provenance（V0 路径经 `route_from_runtime_loop` 取得 runtime 证据）；
  5. rollback plan（V0→inline-local 回退路径与开关），回退 test 须断言回退后
     仍产出 evidence 且不进入第二 runtime（非“调用一次不抛错”即可）。
- **Non-goals**：本轮不写 V0 wiring 代码；不删 inline-local（它是受控 fallback）；
  不引入第二 runtime；不让 child 直接执行 tool/MCP/memory。
- **Dependencies**：OD-1 = **已裁决（V0 为目标）**；`route_from_runtime_loop`
  provenance 机制（已存在）；与 **GE-1 是 co-delivery**（见 GE-1 Dependencies）：
  GE-1 的 subagent-delegation 场景先对 *当前* inline-local 路径取证，SA-1 落地后
  *重指向* V0 断言——因此二者不构成循环前置，而是同窗口联合交付。
- **Acceptance evidence**：live V0 boundary/integration test green（wiring 窗口）；
  继承 focused test green；trace 显示 V0 路径 runtime provenance；fallback 与
  rollback 各有 focused test（含上述 rollback 断言）。
- **Rollback boundary**：迁移须可回退到当前 L1-attempt→inline-local；回退不丢
  evidence；回退路径本身有 test。
- **Owner**：`core.py` delegation 入口的下一位 owner（`V0_WIRING_DECISION.zh.md`
  指 U7/U8 窗口）。
- **Exit condition**：core 路由到 V0；inline-local 退为受控 fallback；
  无效 L1-attempt 在 V0+fallback+observability+rollback 全部验证后移除；
  Subagent gate 具备到 3 的证据。

---

## Theme 4 — Memory / Context Governance

### MEM-1 — Memory consolidation / emergence 真实描述对齐  ·  P3  ·  `documented_pending`

- **North Star principle**：I（Governed memory）。
- **Current fact**：consolidation pipeline FROZEN（2026-05-25,
  `memory_consolidation_pipeline.py:7`），由 `MEMORY_CONSOLIDATION_ENABLED`
  默认关闭门控（`memory_runtime_hooks.py:33`）；emergence 由
  `MEMORY_EMERGENCE_ENABLED` 默认关闭门控（`:152`）——**两个独立 off-by-default
  gate**。两者 runtime-reachable，`test_memory_consolidation_truth.py` 锁状态。
  持久化在 `memory_store.py` / `memory_fs_store.py`（`apply_operation_intent` /
  `store_retained_record`）；写入 gate `DeterministicMemoryPolicy`
  （`memory_policy.py:86`，reject 非 silent-retain）。
- **Target state**：文档/口径与上述真实状态一致（frozen + env-gated + reachable +
  policy-gated + 两独立 gate）；保持 frozen-by-evidence 模式。
- **Gap / failure mode**：旧文档可能把 frozen 写成 active 或漏掉双 gate。
- **Repair direction**：doc-align only，引用已存在的 truth test。
- **Non-goals**：不解冻 consolidation、不新增 raw write/auto-adoption/真实 LLM
  consolidation、不重构 memory。
- **Dependencies**：无。
- **Acceptance evidence**：docs 与 `test_memory_consolidation_truth.py` 一致。
- **Rollback boundary**：doc-only。
- **Owner**：memory 维护者（待指派）。
- **Exit condition**：所有 memory 状态描述与代码/测试一致。

### MEM-2 — Memory canonical write owner  ·  P2  ·  `blocked_by_decision`（Open）

- **North Star principle**：I、D（Single owner）。
- **Current fact**：职责拆分——`memory.py` 压缩/抽取/部分协调；
  `memory_store.py`/`memory_fs_store.py` 持久化；`memory_runtime_hooks.py` +
  `memory_policy.py` 触发与治理。North Star §4.D / §10.1 已把 canonical owner
  标为 `Open:`。
- **Target state**：选定唯一 canonical write owner（North Star 未预选）。
- **Gap / failure mode**：owner 未定 → SoT 维度无法到 3。
- **Repair direction**：先做 ownership decision spike（候选 owner + 迁移代价），
  **不擅自裁决**（用户裁决 #14）。
- **Non-goals**：本轮不选 owner、不移动持久化实现、不动 provenance 格式。
- **Dependencies**：用户/owner 决策。
- **Acceptance evidence**：decision spike 文档 + 决策记录；选定后 single-owner test。
- **Rollback boundary**：spike 阶段 doc-only。
- **Owner**：项目 owner（决策）。
- **Exit condition**：canonical owner 被裁决并 test-locked。

> provenance 格式 / deletion 流程 / 跨 session conflict / lifecycle 见 North Star
> §10.2，统一作为 **decision spike**（`accepted_deferred`），不自动重构。

---

## Theme 5 — State / Persistence / Recovery

### SPR-1 — 完整全局状态机 / 跨主机 resume  ·  P3  ·  `accepted_deferred`（Open OD-8）

- **North Star principle**：E（Explicit state machine）、H（Durable/recoverable）。
- **Current fact**：dispatcher result 7 值枚举已实现且强制
  （`schema.py:145-153,384`）；task.status 字面量分布于 `state.py` + `transitions.py`；
  save/load/resume **已接线**（`checkpoint.py:370/466`，`main.py:731`
  `try_resume_from_checkpoint`，`awaiting_resume_choice` 处理 `main.py:352`）。
- **Target state**：完整 global state machine enum 与跨主机/跨进程 resume 协议
  保持 Open（North Star §12 / OD-8）；intra-process resume 为隐含默认。
- **Gap / failure mode**：无统一 global state-machine 对象（候选态分布存在）；
  resume 协议（replay/cross-host）未定义——但均正确 deferred。
- **Repair direction**：保持 deferred；仅在真实长任务/HITL 需求 + 评测出现后升级。
- **Non-goals**：不实施完整状态机 enum（用户裁决 #11/#14）；不建跨主机 resume；
  不擅自裁决 canonical enum。
- **Dependencies**：真实长任务/HITL 需求；OD-8 决策。
- **Acceptance evidence**：n/a until triggered。
- **Rollback boundary**：n/a。
- **Owner**：项目 owner（决策）。
- **Exit condition**：出现真实需求后重新进入 active。

---

## Theme 6 — Evidence / Observability / Evaluation

### EOE-1 — Cost field 进入 observability  ·  P3  ·  `accepted_deferred`（Open OD-6）

- **North Star principle**：G（First-class observability）。
- **Current fact**：`runtime_observer.py:131 log_event` → `agent_log.jsonl`；
  `evidence_recorder.record_evidence`；`latency_ms` 已捕获（`dispatcher.py:425`）；
  dispatcher 反伪造 provenance（`route_from_runtime_loop` 铸 runtime 证据，
  handler 不能自签，`dispatcher.py:546-555`）。**cost 非一等字段**。
- **Target state**：cost / latency 是否成为 observability 必填，见 North Star
  §14 / OD-6，待决定。
- **Gap / failure mode**：无评测 harness 消费 cost；现在强制属投机。
- **Repair direction**：保持 best-effort；出现评测消费者后再升级。
- **Non-goals**：不强制 cost 字段（用户裁决 #11）。
- **Dependencies**：OD-6 决策 + 评测 harness。
- **Acceptance evidence**：n/a until decided。
- **Rollback boundary**：n/a。
- **Owner**：项目 owner。
- **Exit condition**：OD-6 裁决。

> observability 的 *evaluation* 侧（Golden E2E）见 Theme 9。

---

## Theme 7 — Safety / Policy / Approval

### SPA-1 — Safe metadata ownership  ·  P2  ·  `active`

- **North Star principle**：D（Single owner）、Guardrail（§13）。
- **Current fact**：projector `safe_metadata.py` 已覆盖 D1/D2/D3 trust boundary
  （`a9b39ab`/`97a7bb3`/`a251306`），但底层 `mask_user_visible_secrets` 仍
  owned by `display_events.py`；projector 当前是 **import-surface shim**
  （`safe_metadata.py:23` 注明 regex 在 display_events，projector 只加 import 面）。
- **Target state**：唯一 canonical masking owner；projector 负责 trust-boundary
  projection / truncation / schema filtering，而非二次拥有 masking 逻辑。
- **Gap / failure mode**：masking 逻辑两处（display_events 实现 + safe_metadata
  shim）→ SoT 维度无法到 3；North Star §4.D 的 owner 主张与现状不符。
- **Repair direction**：先做 ownership design spike（移动实现到 projector，或
  明确 display_events 为 owner 并让 projector 仅做投影），再决定。
- **Non-goals**：**不机械全仓替换所有 masker call site**（用户裁决 #10）；
  不改 masking 正则行为。
- **Dependencies**：无（spike 先行）。
- **Acceptance evidence**：ownership 决策文档 + 一个 single masking-owner test。
- **Rollback boundary**：spike 阶段 doc-only；若移动实现，须 behavior-neutral +
  可回退。
- **Owner**：safe_metadata / display_events 维护者（待指派）。
- **Exit condition**：单一 canonical masking owner，test-locked；projector 职责
  收敛为 projection。

### SPA-2 — Permission vs policy staging 口径  ·  P2  ·  `documented_pending`

- **North Star principle**：F（Controlled side effects）。
- **Current fact**：gate（`tool_gate.py:184`）把 skill-allowlist + confirmation +
  block 折叠为单一 `gate_disposition`；**permission 无独立 named stage**。
  North Star §4.F 已诚实降级为 `Inference:`。
- **Target state**：文档清楚说明 5 步治理次序中 permission 实际折叠进 gate，
  避免读者期待一个不存在的独立 stage。
- **Gap / failure mode**：把 §4.F 当 5 个独立 call site 会误判缺失。
- **Repair direction**：doc-align（保持 §4.F 的 `Inference:` 标注）；若未来要拆出
  独立 permission stage，需另案。
- **Non-goals**：不为凑 5 步而制造 permission stage。
- **Dependencies**：无。
- **Acceptance evidence**：文档对 gate 折叠 permission 的说明与代码一致。
- **Rollback boundary**：doc-only。
- **Owner**：runtime_integration 维护者（待指派）。
- **Exit condition**：staging 口径与代码一致。

> Human approval hook（OD-7）= `accepted_deferred`：`confirmation_required`
> 结果态已存在并接 AWAITING_USER；production 强制 approval hook 待 OD-7 裁决，
> 当前 debug 路径足够，不建设。

---

## Theme 8 — Compatibility Retirement

### CR-1 — action_scheduler governance（registered-not-routed）  ·  P2  ·  `active`

- **North Star principle**：A（Simplicity）、Compatibility lifecycle（§17）。
- **Current fact**：`action_scheduler.py`（731 行）实现 ActionNode/ActionPlan/
  depends_on 拓扑执行器，但 **production 未实例化**：`core.chat` 默认
  `action_scheduler=None`，所有接线被 `if action_scheduler is not None:` 守卫；
  仅测试构造实例。live planning 走 `planner.generate_plan`，非
  `generate_action_plan`。
- **Target state**：显式标注 `registered-not-routed / inert`，并有边界证据防止
  无意接入 production 或向框架化漂移。
- **Gap / failure mode**：731 行 inert 代码未标注治理状态 → framework-drift 风险
  （最接近 LangGraph 式 DAG 词汇的模块）。
- **Repair direction**：顶部加 registered-not-routed 标注；加“无 production
  instantiation”的边界测试或等效证据（参照 V0 治理模式）。
- **Non-goals**：**不拆、不删、不接 production**（用户裁决 #13），除非未来
  benchmark 证明需要。
- **Dependencies**：无。
- **Acceptance evidence**：边界测试断言 production 不实例化 action_scheduler；
  模块顶部治理标注。
- **Rollback boundary**：加标注 + 加测试，行为中性，可回退。
- **Owner**：action_scheduler 维护者（待指派）。
- **Exit condition**：inert 状态被标注且 test-locked。

### CR-2 — Legacy skill tombstone wording  ·  P3  ·  `documented_pending`

- **North Star principle**：K。
- **Current fact**：`agent/skills/__init__.py` 是 active fail-closed tombstone；
  历史隔离目标 `agent/legacy_skills/` **不存在**；真实实现在 `agent/skill_system/`。
- **Target state**：文档/注释/测试口径统一为 “tombstone with stale historical
  target”，不写成 healthy_current。
- **Gap / failure mode**：旧表述把 tombstone 误述为现状能力。
- **Repair direction**：doc-align（含 `docs/design/skill-system-architecture.md` 等）。
- **Non-goals**：不恢复 `agent/legacy_skills/` 或 `agent/skills/` 原型。
- **Dependencies**：无。
- **Acceptance evidence**：相关文档措辞统一；tombstone 行为测试保持。
- **Rollback boundary**：doc-only。
- **Owner**：skill_system 维护者（待指派）。
- **Exit condition**：所有引用处口径一致。

### CR-3 — TUI / local_demo compat labeling  ·  P3  ·  `documented_pending`（do-not-touch）

- **North Star principle**：A、K。
- **Current fact**：`tui/`（根目录）+ `agent/local_demo.py` + `agent/local_trace.py`
  + `agent/local_artifacts.py`；`local_trace` 已被 `loop.py` import（在生产 loop 内），
  其余为 demo/test 可达路径，未显式标注 compat path。
- **Target state**：必要时加 1 行 `# compat-path` 标注即可。
- **Gap / failure mode**：缺 compat 标注可能引起误读，但生产 spine 不 import 它们，
  风险低。
- **Repair direction**：最多 1 行 doc-only 标注。
- **Non-goals**：**不把 TUI/local_demo 当主线迁移**（用户裁决 #12 精神 + 红线）；
  不改其行为；不进入近期重构。
- **Dependencies**：无。
- **Acceptance evidence**：（可选）compat 标注存在。
- **Rollback boundary**：doc-only。
- **Owner**：TUI/local 维护者（待指派）。
- **Exit condition**：标注完成或显式判定无需标注。

### CR-4 — Stale docs references  ·  P3  ·  `documented_pending`

- **North Star principle**：Documentation accuracy（§18）。
- **Current fact**：`docs/design/*` 可能引用已删除文件（如 `legacy_skills`）。
- **Target state**：文档引用与真实文件一致。
- **Gap / failure mode**：stale 引用误导读者。
- **Repair direction**：用可复现命令（如 `rg "legacy_skills" docs/`）定位并修正引用。
- **Non-goals**：不删除历史文档至不可追溯；不改设计结论。
- **Dependencies**：与 CR-2 口径一致。
- **Acceptance evidence**：`rg` 检查无 stale 引用。
- **Rollback boundary**：doc-only。
- **Owner**：docs 维护者（待指派）。
- **Exit condition**：stale 引用清零。

---

## Theme 9 — Golden E2E / Architecture Acceptance

### GE-1 — Minimal Golden E2E suite（分阶段）  ·  P1  ·  `active`

- **North Star principle**：L（Evaluation-driven evolution）。
- **定级理由（P1 而非 P2）**：Golden E2E 是 SubAgent critical gate（SA-1）与
  North Star §21 DoD item 4 的验收前提；没有它，SA-1 无法证明 live V0 路径，
  Test/eval 维度与 Subagent 维度都卡在无法到 3。它是 SA-1 的验收基础设施，
  因此与 SA-1 同级 P1。
- **Current fact**：`tests/smoke/` 仅 1 个 e2e 文件
  （`test_first_usable_task_e2e.py`）；无显式 Golden E2E 集合；无 `tests/adversarial/`。
- **Target state**：最小 Golden E2E 套件，覆盖：simple conversation / tool success /
  tool failure(policy_blocked) / memory read-write / subagent delegation /
  checkpoint-resume / fallback-error / evidence-trace reconstruction。
- **Gap / failure mode**：顶层 e2e 仅 1 个 → 关键路径无回归保护；架构验收无可执行下限。
- **Repair direction（分阶段，最小可行，不一开始建庞大测试平台）**：
  - **Phase A**：simple conversation + tool success + subagent delegation。
    subagent-delegation 场景先对 **当前 live 路径（L1-attempt→inline-local）**
    取证（这是 live 路径，现在即可 green），SA-1 落地后 **重指向 V0 断言**——
    借此打破 SA-1↔GE-1 的循环前置（见下 Dependencies）。
  - **Phase B**：memory read/write + checkpoint/resume。
  - **Phase C**：policy_blocked + evidence-trace reconstruction，**外加一个最小
    `tests/adversarial/` stub**（单个注入用例，复用既有 D2 leak-gate 参数化模式）。
    Phase C 是**最小覆盖**，不是 adversarial 平台；`tests/adversarial/` 仅落 1 个
    stub 用例，后续扩充须由独立、单独定级的新 item 驱动，不在本套件内增生。
- **Non-goals**：不建大型测试平台；Phase C 不扩成 adversarial 子平台；不用 mock
  替代真实路径；不重组现有 tests 目录（取代 S4）。
- **Dependencies**：与 SA-1 **co-delivery，非循环前置**——GE-1 Phase A 的
  conversation + tool 场景独立于 SA-1 即可 green；subagent 场景先验当前 inline-local，
  SA-1 wiring 落地后再把该场景断言重指向 V0。两者在同一窗口联合交付，各自有独立
  可 green 的子集。
- **Acceptance evidence**：每 Phase 的 Golden E2E green；§20 rubric Test/eval 维度
  具备到 3 的证据。
- **Rollback boundary**：纯新增测试，可独立回退；不改 production 行为。
- **Owner**：测试 owner（待指派）。
- **Exit condition**：三个 Phase 套件齐备且 green；OD-5 最小定义被锁定。

### GE-2 — Capability documentation alignment  ·  P2  ·  `documented_pending`

- **North Star principle**：Documentation accuracy（§18）、K。
- **Current fact**：`RuntimeDecisionFrame` / `PROJECT_STATUS` /
  `CURRENT_CAPABILITY_STATUS` / `runtime-decision-spine` 之间 capability status
  口径漂移（旧 V4）。
- **Target state**：四方做可复现 diff table；code/test 决定 Current Fact；
  docs/status 与结构化 SoT 一致；不手工维护多份互相重复的状态。
- **Gap / failure mode**：多份状态文档互相漂移 → Documentation critical 维度卡在 2。
- **Repair direction**：先产出可复现 diff table，再做 terminology alignment；
  不改代码逻辑。
- **Non-goals**：不手工维护重复状态；不改 capability 行为。
- **Dependencies**：与 CR-2/CR-4 口径协同。
- **Acceptance evidence**：diff table + docs/status 与结构化 SoT 一致的断言。
- **Rollback boundary**：doc-only。
- **Owner**：docs/runtime 维护者（待指派）。
- **Exit condition**：四方口径一致且可复现校验通过。

### GE-3 — Rubric re-score（架构验收复算）  ·  P2  ·  `documented_pending`

- **North Star principle**：§20 Acceptance Rubric、§21 DoD。
- **Current fact**：§20 全 12 维度当前为 `provisional`；本轮 Gap Audit 给出
  逐维度证据，critical gates 均 = 2（基本成型，未 Done）。
- **Target state**：SA-1 / GE-1 落地后重跑 rubric，回填实测分；目标 critical
  gates → 3。
- **Gap / failure mode**：不复算则 provisional 无法转为可执行验收。
- **Repair direction**：在 SA-1 与 GE-1 Phase A/B 落地后，按 §20 anchors 逐项取证。
- **Non-goals**：不平均分抵消 critical failure；不凭文件存在/测试数量评分。
- **Dependencies**：SA-1、GE-1。
- **Acceptance evidence**：一份逐维度证据回填的 rubric 复算。
- **Rollback boundary**：doc-only。
- **Owner**：架构审计 owner（待指派）。
- **Exit condition**：rubric 实测回填，critical gates 状态明确。

---

## Theme 10 — History / Completed Work

> 保留完成证据与测试，记录“为什么不再是 active work”，不删至不可追溯。

### H-1 — evidence.py / RuntimeActionTargetCatalog extraction  ·  `move_to_history`

- **North Star principle**：D（Single owner）。
- **完成内容**：`RuntimeActionTargetCatalog` 从 `evidence.py` 提取到
  `target_catalog.py`（catalog 单一 owner）；`evidence.py` 保留 back-compat
  re-export；生产行为未变。
- **commit/test evidence**：commit `8be4dcb`（2026-06-12）；
  `tests/runtime_integration/test_target_catalog_extraction.py` 锁边界；
  `docs/06-audit/TARGET_CATALOG_REEXPORT_AUDIT.zh.md`（U4 审计）。
- **为何不再 active**：extraction 已完成且 test-locked；属红线“不移出生产路径”。
- **后续护栏**：保持 re-export 边界测试不回退。

### H-2 — Safe metadata D1/D2/D3 trust-boundary migration  ·  `protected_pending`

- **North Star principle**：D、Guardrail（§13）。
- **完成内容**：三个独立 trust boundary 经 projector：D1 runtime_observer、
  D2 evidence_persistence（leak-gate + projector-level redactors，16 参数化
  AWS/GitHub/GCP/Slack/JWT/Bearer 等）、D3 memory_hook。每 commit 一边界。
- **commit/test evidence**：`a9b39ab`（D1）、`97a7bb3`（D2）、`a251306`（D3）。
- **为何仍 protected_pending 而非纯 history**：边界不得回退；**剩余 ownership
  问题转入 SPA-1**（projector 仍是 shim，masking owner 仍在 display_events）。

### H-3 — SubAgent SoT runtime-truth 对齐  ·  `protected_pending`

- **North Star principle**：J。
- **完成内容**：`runtime_decision_frame.py` 中 V0/L1 状态与 runtime 一致
  （V0 registered-not-routed；L1 frozen；live = L1-attempt→inline-local）。
- **commit/test evidence**：`5d1cdcb`/`4d0d8e5`；
  `test_subagent_runtime_truth.py`、`test_subagent_inline_local_live.py`、
  `test_subagent_l2_contract.py`。
- **为何仍 protected_pending**：SoT 已修正且 test-locked，但 **production wiring
  仍未完成 → 转入 SA-1（active P1）**。

---

## 11. Open Decisions 寄存器（不在本轮裁决）

| OD | 主题 | 状态 | 关联 item | 何时裁决 |
|---|---|---|---|---|
| OD-1 | V0 production SubAgent 主路径 | **已裁决=V0 为目标** | SA-1 | 已决；wiring 待实施窗口 |
| OD-2 | 统一 Capability Contract | Open | CM-2 | 出现跨 Tool/Skill/MCP 消费者时 |
| OD-3 | HTTP/RPC 远程 client | Open（non-goal 倾向） | — | 维持进程内；非目标 |
| OD-4 | Consolidation 默认 production | Open | MEM-1 | 出现真实 long-term 需求时 |
| OD-5 | Golden E2E 最小定义 | **进入 active=GE-1** | GE-1 | 本批锁定 |
| OD-6 | Cost/Latency 必填 | Open | EOE-1 | 出现评测消费者时 |
| OD-7 | Human approval hook 进生产 | Open | SPA-2 注 | 出现多用户/生产需求时 |
| OD-8 | Checkpoint 兼容/resume 协议 | Open（intra-process 默认） | SPR-1 | 出现跨主机/长任务需求时 |
| — (OD-9) | Memory canonical write owner | Open | MEM-2 | owner 决策 |
| — (OD-10) | 全局状态机 canonical enum | Open | SPR-1 | 真实需求出现时 |

> OD-9/OD-10 为本 Roadmap 本地编号（North Star §23 仅列 OD-1..OD-8）；North Star
> §4.D/§10.1/§12 已把这两项标为 Open，此处仅给本地交叉引用号，不改 North Star。

---

## 12. Do-not-touch（红线，继承 v2 并对齐用户裁决）

1. 不 push；不改 remote；不 commit（除非用户明确授权）。
2. 不读 `.env` / `agent_log.jsonl` / `sessions/` / `workspace/` 真实内容。
3. 不真实调用 LLM / MCP / external server。
4. 不恢复 legacy L1/L2 production route；不复活 `agent/legacy_skills/` / `agent/skills/` 原型。
5. 不新增第二 runtime；不绕过 `core.py`/`loop.py` 主线。
6. 不绕过 `ToolRuntimeMediator`；不写第二条 tool execution path。
7. 不让 child 直接执行 tool/MCP/memory 写入。
8. 不新增 Memory raw write / auto-adoption / 真实 LLM consolidation；不动 frozen consolidation。
9. 不先大拆 `core.py`/`loop.py`/`mediator`；不重组 tests 目录（S2/S3/S4 已 obsolete）。
10. 不削弱 `tests/test_architecture_boundaries.py`；不移出 `RuntimeActionTargetCatalog` 生产路径。
11. 不把 TUI/local_demo 当主线迁移。
12. 不机械全仓替换 masker call site（SPA-1 走 ownership，不走扫描）。
13. 不实施完整状态机 / 跨主机 checkpoint / RPC / 统一 Capability Contract / HITL UI /
    强制 cost 字段等无当前消费者的能力。
14. 不擅自裁决 Memory canonical owner 与完整状态机 enum。
15. 本文件不写成 implementation plan、不含代码 diff、不生成 goal 命令。

---

## 13. P0/P1/P2/P3 清单（active + pending）

- **P0**：无（无安全/数据/核心不可运行/未治理第二 Runtime/权限或证据边界失效项）。
- **P1**：**SA-1**（V0 production-path completion）、**GE-1**（minimal Golden E2E）。
- **P2**：RS-1（topology alignment）、CM-1（config spike）、SPA-1（safe-metadata ownership）、
  SPA-2（permission staging 口径）、CR-1（action_scheduler governance）、
  MEM-2（memory owner，blocked_by_decision）、GE-2（capability docs）、GE-3（rubric re-score）。
- **P3**：MEM-1、CM-2、SPR-1、EOE-1、CR-2、CR-3、CR-4（多为 deferred/doc-align）。

## 14. 下一批推荐主线

1. **SA-1 + GE-1 Phase A** 同窗口 co-delivery：V0 wiring 迁移定义 + 最小 Golden E2E。
   GE-1 的 conversation+tool 场景独立可 green；subagent 场景先验当前 inline-local，
   SA-1 落地后重指向 V0——非循环前置，是唯一能推动 critical gate 向 3 的组合。
2. **SPA-1**（safe-metadata ownership spike）+ **CR-1**（action_scheduler 标注）：
   清 SoT 与 framework-drift，低风险。
3. **GE-2**（capability docs diff-table）：清 Documentation critical 维度。

## 15. Final Verdict

- Roadmap 已从历史发现编号（V1–V7/S1–S5）升级为按架构主题（Theme 1–10）组织的
  Current→Target 迁移路线。
- 每个 active item 绑定 North Star principle，并含 Current/Target/Gap/Repair/
  Non-goal/Dependencies/Acceptance/Rollback/Owner/Exit。
- completed 项（V2/D1-D3/SoT 对齐）移入 §10 History；obsolete/cosmetic（S2/S3/S4）
  不再占 active 优先级。
- V0 wiring（SA-1）与 Golden E2E（GE-1）成为下一阶段明确主线。
- deferred 项均已治理，不制造双主路径或双 SoT。
- 本 Roadmap 可按主题逐段生成 ce-plan，而无需现场重做架构决策。
- 本文件仍是 draft，等待 human review；非 source-of-truth，不替代 North Star。
