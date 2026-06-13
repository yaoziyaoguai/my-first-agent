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
>
> **2026-06-13 Remaining Gap Classification Audit 补注**：本轮在不改 North Star /
> Window plan / Window closure audit / production code / tests 的前提下，新增两节
> 主控视图——`## Repair Remaining Gap Classification`（10 类分类 + 依赖触发表）与
> `## Architecture Repair Mainline Closure Readiness`（主线关闭判断）。本轮经
> Graphify + 源码/测试核验 + 两个 fresh-context reviewer（architecture + adversarial）
> 交叉验证；后续 RED-1 与 GE-1 Phase B/C 均已完成，但 GE-2/GE-3 仍未闭合，故
> `MAINLINE_CLOSE_READY = NO`。原按 Theme 组织的 item 正文保留为详细背书，不删。

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

## 1bis. Git / 文档 Baseline（再次重写时刻）

- branch：`chore/architecture-repair-2026-06`
- HEAD（重写前）：`4ddf3e9`
- North Star sha256（冻结）：`c73c2b3dbe926f30834a5d9ab20155cc947ab27158339a7c8b221d0d80568cde`
- Plan sha256：`docs/plans/2026-06-12-002-feat-subagent-v0-production-routing-plan.md`（见文件 hash）
- 本轮：no push；执行期内 Plan 与 Roadmap 都是 frozen read-only contract（执行 Agent 不得修改）。
- 修订范围：仅修订 SA-1、新增 SA-2、修订 GE-1 Phase A、修订 GE-3、增加 §9.1 decision history。不重写其他主题或优先级。

> 原 v3 重写 baseline（`8fa8ce7` / sha256 `d83bc606…`）见 git 历史；本轮 §1bis 不再冗余保留旧 commit id。

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

### CM-1 — Config 入口 import-boundary spike  ·  P2  ·  `completed`

- **North Star principle**：K（Stable capability interfaces）。
- **Current fact**：`agent/provider/config.py` /
  `agent/provider/simple_config.py` / `agent/provider/profiles.py` /
  `agent/local_config.py` / `agent/mcp_config*.py` 并存；Window 3
  已确认三条 provider config surface 位于 `agent/provider/`，不是 agent 根目录。
- **Target state**：已明确每个 config 入口的 import boundary 与调用面，并区分
  owner / compatibility / wrapper / alternate entry。
- **Gap / failure mode**：Window 3 已关闭：现有入口不是需要本窗口收敛的重复
  provider registry；剩余为低风险呈现/退役决策债。
- **Repair direction**：用可复现命令列出所有 import boundary（spike），再决定；
  不预先重构。
- **Non-goals**：不合并 config 模块、不改 provider 选择逻辑、不动 `.env`。
- **Dependencies**：无。
- **Acceptance evidence**：`docs/06-audit/WINDOW_3_CM1_CONFIG_IMPORT_BOUNDARY_INVENTORY.zh.md`
  + `tests/test_architecture_boundaries.py` 的 W3-T1/W3-T4 inventory/owner
  snapshot 边界测试。
- **Rollback boundary**：spike 产出文档，无代码改动。
- **Owner**：config 维护者（待指派）。
- **Exit condition**：**completed** — inventory 完成；结论为本窗口保留现有
  provider factory / config surfaces，不做 provider registry、不做 CM-2。
- **Window 3 Closure（2026-06-13）**：**completed**。Evidence：
  - CM-1 inventory 记录 provider/config、simple_config、profiles、local_config、
    mcp_config*.py、provider factory/selection；
  - W3-T1/T4 锁定 inventory 与 per-surface owner snapshot；
  - W3-T2/T3 锁定 action_scheduler seam 存在但 production 不默认注入；
  - W3-T5 将 scheduler wording 从不可达式 overclaim 收紧为
    `dormant-by-default / registered-not-routed in production`；
  - CM-2 仍为 `accepted_deferred`，未新增统一 capability contract/status；
  - GE-2 仍是独立后续项，Window 3 未启动。

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

### SA-1 — SubAgent production-path completion (V0 wiring)  ·  P1  ·  `completed`

- **North Star principle**：J（Bounded subagents）、B（One Runtime Spine）。
- **Current fact**：
  - V0 `SubAgentV0Handler` 已 **registered + contract-verified**
    （`phase1_hook.py:179`，dispatcher 12/12 dispatch tests pass），但
    **未 production-routed**。
  - live CLI/NL delegation 通过 pre-loop seam `_dispatch_or_fallback_delegation`
    （`core.py:1973`）短路落地：L1 attempt 是 dead code（`SUBAGENT_DELEGATE_L1`
    未注册），所以 live 路径是无条件 inline-local（`subagent_inline.py:37`，
    `execution_mode=”local_fake”`，evidence-silent）。
  - `core.chat` 始终构建 `_phase1_dispatcher`（`core.py:840`）并注入 loop
    （`core.py:1184`），同一 dispatcher 可用于 pre-loop delegation。
  - `fake_local` V0 success 路径 `observed_call=None`（`subagent_action.py:919`），
    `is_runtime_e2e_evidence=False`，`classify_evidence_level` 真实返回
    `subsystem_integration`（`evidence.py:616-648`）——这是 pre-loop 真实路径
    可达的最高级别。
- **Target state**（用户裁决 #2/#3/#6/#7 + Plan B1-A）：core production caller
  通过 **RuntimeActionDispatcher** 路由到 **V0**（`route_from_runtime_loop`，
  honest pinned `source=”cli_nl_delegation”`）；inline-local 仅作为
  **受控 fallback**（结构性不可用时）；V0 wiring + 继承 + success/error/fallback
  evidence + rollback 全部验证后退出 active。V0 是目标 production SubAgent
  Runtime path（长期 Target 不变）。
- **Gap / failure mode**：生产主路径偏离目标（V0 未路由）；
  Pre-loop 真实路径只能产 `subsystem_integration`（`core_loop` provenance 不可
  伪造，`source` 是 free `str`，且 `fake_local` 路径无 registered-target module
  proof → 无法到 `harness_runtime_e2e`）。
- **Repair direction**（本 Roadmap 只定义迁移，**不实施**；以下为迁移须满足的
  验收契约，不在本轮执行）：
  1. **default-off、flag-on V0 dispatcher routing**：新增 rollout flag
     `SUBAGENT_V0_ROUTING_ENABLED`（默认 off，env-gate，参考
     `memory_runtime_hooks.py:33` 的 `MEMORY_CONSOLIDATION_ENABLED` 模式）。本
     窗口不翻默认值；flipping default 是独立后续工作（见 Non-goals）。
  2. **真实 pre-loop provenance**：`route_from_runtime_loop` 携带 truthful
     `core_entrypoint=”core.chat”`、`runtime_hook_name=”core.delegate”`、
     pinned `source=”cli_nl_delegation”`（B1-A）。禁止伪造 `source=”core_loop”`。
     真实 evidence label 为 `subsystem_integration`，本窗口不要求
     `harness_runtime_e2e` / `core_loop` / L3 / gate=3。
  3. **bounded inheritance**：V0 request 携带 `max_turns=1`、context caps
     （`max_files` / `max_context_chars` / `parent_selected_files`）、permission
     （`capability_flags`，tool/MCP/memory default-deny）、tool subset
     （`allowed_tools`）、parent-built context、trace id。child 不直接执行
     tool/MCP/memory。
  4. **success / error / fallback evidence**：V0 success、error、controlled
     fallback（flag on + V0 结构性不可用）各产一个 dispatcher
     `RuntimeActionEvent`（fallback 通过 `_unsupported_result` 路径，不是手工
     dict，不是新事件类型，不是第二条 emit 路径）。flag-off rollback 保持
     evidence-silent（与现状一致）。
  5. **可回滚**：flag off → 当前 inline-local，行为不变，evidence-silent；
     滚回路径有 focused test 断言（不进入第二 runtime）。
- **Non-goals**：
  - 不删 inline-local（它是受控 fallback，R5/R7）；
  - 本窗口 **不删 L1 attempt**（dead code，R8：保留；
    “无效 L1-attempt 移除” 是后续独立工作，不在 SA-1 exit 范围）；
  - 不翻 rollout 默认值（off→on 是独立后续工作，本窗口 default off）；
  - 不搬迁 lifecycle 进 `run_main_loop`（B1-B / SA-2 单独研究，不在 SA-1
    验收范围）；
  - 不引入第二 runtime；不让 child 直接执行 tool/MCP/memory；
  - 不要求 L3 / `core_loop` provenance / gate=3 / `harness_runtime_e2e`。
- **Dependencies**：OD-1 = **已裁决（V0 为目标）**；`route_from_runtime_loop`
  provenance 机制（已存在）；与 **GE-1 是 co-delivery**（见 GE-1 Dependencies）。
- **Acceptance evidence**（wiring 窗口）：
  - flag-on V0 Golden E2E green（G4）；
  - flag-off inline-local characterization green（G3，rollback 验证）；
  - missing/invalid flag → off（off-cases 测试覆盖）；
  - controlled fallback（flag on + handler 结构性不可用）→ dispatcher
    `not_supported` event + inline-local render（G6）；
  - provenance/evidence 断言：真实 `source=”cli_nl_delegation”` →
    `classify_evidence_level == “subsystem_integration”`；伪造
    `source=”core_loop”` 不改变 label（G7）；
  - 完整 `pytest` 套件（golden_e2e / runtime_integration /
    test_architecture_boundaries）以 flag off / on 两种姿态 green。
- **Rollback boundary**：每 commit 独立可回退（commit matrix 见 Plan）；
  flag off 即时回退到当前 inline-local（行为不变，evidence-silent）；历史
  evidence 在 action log 中保留。
- **Owner**：`core.py` delegation 入口的下一位 owner（实施窗口由 Plan
  指派）。
- **Exit condition**：default-off V0 production routing migration **已实现、
  可观察、可回滚**——本项 **不单独宣称 SubAgent governance=3**。
  gate→3 / `harness_runtime_e2e` 证据的获取由 **SA-2**（lifecycle integration
  / L3 evidence design spike）独立研究后再决定。
- **Window 1 Closure（2026-06-13）**：**completed**。Acceptance evidence：
  - default-off flag（`SUBAGENT_V0_ROUTING_ENABLED`，`subagent_routing_flag.py`，core.py:2001）；
  - flag-on 经 trusted `route_from_runtime_loop` 进入 `SUBAGENT_DELEGATE_V0`；
  - FakeProvider → `fake_local` + V0 success（G4）；
  - missing descriptor → `rejected` / `descriptor_not_found`，不崩溃、不执行 child（F2.1）；
  - handler missing → `not_supported` 后受控 inline-local fallback（G6）；
  - provider/contract business failure → `failed`，不 fallback（F3.1, G7）；
  - RuntimeIdentity/provenance/evidence 正确（G5, G7）；
  - pre-loop seam、L1 attempt、inline-local rollback 均保留；
  - full suite 4686 passed, 0 failed（f5f10df）。

### SA-2 — SubAgent lifecycle integration / L3 evidence design spike  ·  P2  ·  `documented_pending`（`blocked_by_evidence`）

- **North Star principle**：J（Bounded subagents）、B（One Runtime Spine）、
  §20 Acceptance Rubric。
- **Current fact**：SA-1 落地后 live V0 路径真实 evidence label 为
  `subsystem_integration`（pre-loop seam 不可伪造 `core_loop` provenance，
  `fake_local` 路径无 registered-target module proof → 不能到
  `harness_runtime_e2e`）。是否需要搬迁 delegation 进 `run_main_loop` 以取得
  `core_loop` provenance / L3 标签，**未在 SA-1 范围内论证**。
- **Target state**：产出 **design spike 文档**，比较 L3 相对真实
  `subsystem_integration` 的可观察收益，以及搬迁 lifecycle 进 `run_main_loop`
  对以下方面的影响：
  1. pre-loop 早返短路 / 渲染 / 对话状态 / tool 流 / checkpoint / fallback /
     rollback；
  2. parent / child bounded inheritance 是否仍成立（特别是 `max_turns=1`、
     `provider_mode="fake_local"`、child 不直接 tool/MCP/memory 写入）；
  3. 任何会引入 second runtime 风险的耦合。
- **Gap / failure mode**：若不在本项里明确"收益—代价"评估，下游可能为追求
  gate→3 分数而搬迁 lifecycle，破坏 North Star B / §15（single Runtime Spine，
  禁第二 runtime）；或为追求分数伪造 `source="core_loop"` 违反 B1-A。
- **Repair direction**：spike only；明确写出
  "**L3 相对真实 `subsystem_integration` 的可接受收益是什么**" 与
  "**为什么 pre-loop seam 不能作为合法 governed path**"。只有同时满足两点才
  考虑进入 active 实施；任一不满足则保持 `subsystem_integration` 是 final。
  **"无充分收益，不实施"是合法结论**。
- **Non-goals**：
  - **禁止为了评分（gate→3）搬迁 lifecycle**；
  - 不在本项里实施搬迁；不预先承诺产出实施 plan；
  - 不在 SA-2 期间改 SA-1 验收；不伪造 provenance。
- **Dependencies**：SA-1 落地（拿到真实 `subsystem_integration` 证据作为
  baseline）；GE-3 复算结果（如可获取）。
- **Acceptance evidence**：spike 文档包含 (a) 收益表（含可拒绝项）、
  (b) 风险与影响面清单、(c) 明确结论（"应进入 active 实施" /
  "保持 `subsystem_integration` 为 final"）。Spike 通过 `blocked_by_evidence`
  关卡前不算完成。
- **Rollback boundary**：spike 阶段 doc-only；若后续进入 active 实施，须
  独立 plan + 独立 commit matrix，不并入 SA-1。
- **Owner**：架构 owner（待指派）。
- **Exit condition**：spike 完成且结论明确；本项不规定必须实施搬迁。

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

### SPA-1 — Safe metadata ownership  ·  P2  ·  `completed`

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
- **Window 2 Closure（2026-06-13）**：**completed**（Option B 批准）。Evidence：
  - `display_events.py` 确认为 canonical secret-masking owner（`_SECRET_MASK_PATTERNS` + `mask_user_visible_secrets`）；
  - `safe_metadata.py` 确认为 projection wrapper（thin wrapper docstring + import delegation）；
  - `_EXTRA_REDACT_PATTERNS` 定位为 evidence_persistence boundary-local extra redaction；
  - W2-T1/T2：11 tests GREEN（`test_safe_metadata_ownership.py`）；
  - decision doc：`docs/06-audit/SPA1_MASKING_OWNERSHIP_DECISION.zh.md`；
  - 延伸债务 W2-D1（`_EXTRA_REDACT_PATTERNS` 长期归属）deferred，见 §9.4。

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

### CR-1 — action_scheduler governance（dormant-by-default / registered-not-routed）  ·  P2  ·  `completed`

- **North Star principle**：A（Simplicity）、Compatibility lifecycle（§17）。
- **Current fact**：`action_scheduler.py`（731 行）实现 ActionNode/ActionPlan/
  depends_on 拓扑执行器，但 **production 未实例化**：`core.chat` 默认
  `action_scheduler=None`，所有接线被 `if action_scheduler is not None:` 守卫；
  仅测试构造实例。live planning 走 `planner.generate_plan`，非
  `generate_action_plan`。
- **Target state**：显式标注
  `dormant-by-default / registered-not-routed in production`，并有边界证据防止
  无意接入 production 或向框架化漂移；保留测试可手工注入 seam 的事实。
- **Gap / failure mode**：731 行 dormant-by-default 代码若被误称为“不可达”，会掩盖
  `chat(action_scheduler=...)` 可注入 seam；若未标注治理状态，又有 framework-drift
  风险（最接近 LangGraph 式 DAG 词汇的模块）。
- **Repair direction**：顶部加 registered-not-routed 标注；加”无 production
  instantiation”的边界测试或等效证据（参照 V0 治理模式）；Window 3 已补充
  label precision 测试，禁止把 seam 存在的 scheduler 误称为 unreachable。
- **Non-goals**：**不拆、不删、不接 production**（用户裁决 #13），除非未来
  benchmark 证明需要。
- **Dependencies**：无。
- **Acceptance evidence**：边界测试断言 production 不实例化 action_scheduler；
  模块顶部治理标注。
- **Rollback boundary**：加标注 + 加测试，行为中性，可回退。
- **Owner**：action_scheduler 维护者（待指派）。
- **Exit condition**：dormant-by-default 状态被标注且 test-locked。
- **Window 2 Closure（2026-06-13）**：**completed**。Evidence：
  - `agent/action_scheduler.py` 顶部加 CR-1 governance label（8 行中文标注）；
  - `test_cr1_chat_default_action_scheduler_is_none`：AST 验证 `core.chat()` `action_scheduler=None`；
  - `test_cr1_main_py_does_not_pass_action_scheduler_kwarg`：AST 验证 `main.py` 不传 `action_scheduler=`；
  - `test_cr1_action_scheduler_not_routed_in_production`：`main.py` 不 import `agent.action_scheduler`；
  - `test_cr1_action_scheduler_class_exists_and_is_not_wired`：class 存在 + `core.chat` 默认 None；
  - 4 tests GREEN（`tests/test_architecture_boundaries.py`）；
  - compat inventory：`docs/06-audit/WINDOW_2_COMPAT_INVENTORY.zh.md §5`；
  - OD-7（接入生产）仍 deferred，见 §11 OD-7。
- **Window 3 Label Correction（2026-06-13）**：**completed**。Evidence：
  - `agent/action_scheduler.py` docstring 改为
    `dormant-by-default / registered-not-routed in production`；
  - Window 2 closure/compat docs 同步去除 scheduler “不可达” overclaim；
  - W3-T2/T3/T5 验证 main.py/production entrypoint 不注入 scheduler、handler
    仍 registered、测试 seam 仍可手工注入；
  - no scheduler wiring。

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

### GE-1 — Minimal Golden E2E suite（分阶段）  ·  P1  ·  `completed`（Phase A/B/C completed）

- **North Star principle**：L（Evaluation-driven evolution）。
- **定级理由（P1 而非 P2）**：Golden E2E 是 SubAgent critical gate（SA-1）与
  North Star §21 DoD item 4 的验收前提；没有它，SA-1 无法证明 live V0 路径，
  Test/eval 维度与 Subagent 维度都卡在无法到 3。它是 SA-1 的验收基础设施，
  因此与 SA-1 同级 P1。
- **Original fact**：`tests/smoke/` 仅 1 个 e2e 文件
  （`test_first_usable_task_e2e.py`）；无显式 Golden E2E 集合；无 `tests/adversarial/`。
- **Current fact（2026-06-13）**：`tests/golden_e2e/` 已覆盖 Phase A/B/C；
  `tests/adversarial/` 已落最小 safe stub。memory 仍是 frozen/env-gated truth，
  本轮未解冻 memory、未实现 MEM-2。
- **Target state**：最小 Golden E2E 套件，覆盖：simple conversation / tool success /
  tool failure(policy_blocked) / memory truth + checkpoint state / subagent delegation /
  checkpoint-resume / fallback-error / evidence-trace reconstruction。
- **Gap / failure mode**：顶层 e2e 仅 1 个 → 关键路径无回归保护；架构验收无可执行下限。
- **Repair direction（分阶段，最小可行，不一开始建庞大测试平台）**：
  - **Phase A**（路径固定 `tests/golden_e2e/`）：
    - G1 simple conversation；
    - G2 tool success；
    - G3 flag-off inline-local characterization（subagent delegation 的当前
      live 行为取证，flag 显式置 off）；
    - G4 flag-on V0 delegation（live path，`chat()` 驱动，flag 显式置 on）；
    - G5 flag-off rollback（与 G3 行为一致，作为 standing rollback 证明）；
    - G6 V0 unavailable → controlled fallback（flag on + handler 结构性不可用
      → dispatcher `not_supported` event + inline-local render；V0 业务失败
      走 error，不 fallback）；
    - G7 provenance/evidence assertions（`source="cli_nl_delegation"` →
      `classify_evidence_level == "subsystem_integration"`；伪造
      `source="core_loop"` 不改变 label；success/error/controlled-fallback
      各产 dispatcher event）。
    Phase A **不要求 gate=3 / `harness_runtime_e2e`**；其 evidence level 由真实
    路径决定（`subsystem_integration`）。
    subagent-delegation 场景先对当前 live 路径（flag-off inline-local）取证
    （现可 green），SA-1 落地后重指向 V0 断言——借此打破 SA-1↔GE-1 的循环前置
    （见下 Dependencies）。
  - **Phase B**：memory 当前 frozen/env-gated truth + checkpoint/resume local roundtrip。
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
- **Window 1 Closure（2026-06-13）**：**Phase A completed**。Evidence：
  - G1–G2 conversation/tool golden tests green；
  - G3 flag-off inline-local characterization green；
  - G4 flag-on V0 success + structured `provider_mode`/status 断言（F6.1）；
  - G5 flag-off rollback proof green；
  - G6 not_supported 先于 inline-local fallback 的顺序证明（F5.1）；
  - G7 docstring 降级：不再作为真实 failure surface 唯一证据，
    F3.1 通过 real Handler integration tests 覆盖 contract/provider failure；
  - `tests/golden_e2e/` 8 passed。
  - Phase B/C 当时待后续窗口；2026-06-13 已完成（见下方 Closure）。
- **GE-1 Phase B/C Closure（2026-06-13）**：**Phase B/C completed**。Evidence：
  - GE1-B1 memory golden：`test_golden_memory_checkpoint.py` +
    `fixtures/memory_disabled.json` 锁定 consolidation frozen/env-gated、
    emergence disabled-by-env，且默认 gate 不触碰 memory store；
  - GE1-B2 checkpoint golden：`checkpoint_local_roundtrip.json` 锁定
    `checkpoint.v1` local-file / intra-process save-load-restore；
  - GE1-B3 policy golden：`ToolRuntimeMediator` + `ToolGateHandler`
    对不在 active skill allowlist 的工具返回 `__force_stop__`，
    `tool.invoke` count = 0，tool result message 不持久化原始输入 marker；
  - GE1-B4 evidence-trace golden：`dispatcher.flush_to_event_log()`
    输出 `tool.gate` + `tool.result` 两类 `RuntimeActionEvent`，
    关键字段齐备，`claims_real_provider_e2e=false`；
  - GE1-C1 adversarial stub：`tests/adversarial/test_minimal_policy_stub.py`
    用空参数 forbidden tool name `shell` 验证 fail-closed、无危险执行；
  - Verification：`tests/golden_e2e/ tests/adversarial/` 13 passed；
    `tests/runtime_integration/` 1076 passed, 4 skipped, 6 xfailed；
    `tests/` 4730 passed, 12 skipped, 26 xfailed。

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
- **Target state**：SA-1 / GE-1 落地后**按真实 evidence 重新评分**：结果可维持
  2 或达到 3，**由真实证据决定，不预先承诺升分**。Subagent critical gate 是否
  升至 3 由 **SA-2** 单独研究决定（不在 GE-3 评分口径内）。
- **Gap / failure mode**：不复算则 provisional 无法转为可执行验收；
  若为提高分数伪造 provenance / 扩大 scope / 搬迁 lifecycle，会回退到 v2 的
  governance smell（North Star B / §15）。
- **Repair direction**：在 SA-1 与 GE-1 Phase A/B 落地后，按 §20 anchors 逐项
  取证；SA-2（若进入 active 实施）落地后再次复算 Subagent critical gate。
- **Non-goals**：
  - **不得为提高分数伪造 provenance**（B1-A 红线）；
  - **不得为提高分数扩大 scope**（本评分只接受 SA-1/GE-1 真实落地的 evidence）；
  - **不得为提高分数搬迁 lifecycle**（B1-B / SA-2 单独 spike，不在评分诱导下
    实施）；
  - 不平均分抵消 critical failure；不凭文件存在/测试数量评分。
- **Dependencies**：SA-1、GE-1；SA-2 结论（如可获取）。
- **Acceptance evidence**：一份逐维度证据回填的 rubric 复算，**每分附真实
  evidence 引用**（不写无源分数）。
- **Rollback boundary**：doc-only。
- **Owner**：架构审计 owner（待指派）。
- **Exit condition**：rubric 实测回填，critical gates 状态明确（结果 = 2 或
  = 3 均可接受；不得为追求 3 破坏 B1-A / B / §15）。

---

## 9.1. Decision History（SA-1/GE-1/GE-3 acceptance 修订记录）

> 本节只记录本轮对 SA-1、SA-2、GE-1、GE-3 局部验收假设的修订。
> 不重写其他主题或优先级。

| # | 原假设 | 新证据（Plan 阶段核验） | 修订结论 |
|---|---|---|---|
| H-1 | SA-1 Exit 要求 "Subagent gate → 3" 与 "无效 L1-attempt 移除" | delegation 位于 pre-loop seam（`core.py:1973`），不是 `run_main_loop`；`source="core_loop"` 不可伪造（`schema.py:221` 是 free `str`，为 L3 唯一判别）；`fake_local` 路径无 registered-target module proof（`observed_call=None`）→ `classify_evidence_level` 真实返回 `subsystem_integration`（`evidence.py:616-648`） | SA-1 Exit 改为 "default-off V0 production routing migration 已实现、可观察、可回滚"；**不单独宣称 SubAgent governance=3**；L1 attempt 本窗口不删 |
| H-2 | V0 wiring 应迁移进 `run_main_loop` 以取得 `core_loop` / L3 provenance | pre-loop seam 已是合法 governed path（同 `_phase1_dispatcher`）；`core_loop` provenance 在 pre-loop 不可达 | 保持 pre-loop seam（B1-A）；搬迁收益由 **SA-2**（lifecycle integration / L3 evidence design spike）独立 spike 评估，"无充分收益不实施"是合法结论 |
| H-3 | SA-1 Repair direction 强调"必须 `route_from_runtime_loop` + `core_loop` provenance + gate=3" | `route_from_runtime_loop` 已存在；`core_loop` 不可达；gate=3 需要 L3 路径 | Repair direction 改为 default-off、flag-on V0 dispatcher routing、真实 pre-loop provenance、bounded inheritance、success/error/fallback evidence、可回滚 |
| H-4 | evidence label 期待 `harness_runtime_e2e` | `fake_local` V0 success `observed_call=None` → `is_runtime_e2e_evidence=False` → `subsystem_integration` | 当前真实 evidence label 为 `subsystem_integration`；GE-1 Phase A 与 SA-1 接受此为正确结果 |
| H-5 | GE-1 Phase A subagent 场景先对当前路径取证，SA-1 后重指向 V0 | 同 v3 已规划；本轮把路径与 checklist 钉到 `tests/golden_e2e/`：G1 simple conversation / G2 tool success / G3 flag-off inline-local / G4 flag-on V0 / G5 rollback / G6 V0-unavailable fallback / G7 provenance assertions | 维持 co-delivery 形态；GE-1 Phase A 不要求 gate=3 |
| H-6 | GE-3 复算目标 critical gates → 3 | 复算结果由真实 evidence 决定，**不得**为提高分数伪造 provenance / 扩大 scope / 搬迁 lifecycle | 复算结果可维持 2 或达到 3；Subagent critical gate 升分由 SA-2 单独研究决定 |
| H-7 | 实施期由执行 Agent 直接改 Roadmap | 执行期要求 "Plan + Roadmap 都是 frozen read-only contract"；执行 Agent 不得改文档 | 由 docs-only 流程在实施独立审计后单独执行 Roadmap 状态更新；本轮不再让执行 Agent 改 Roadmap |

## 9.2. Window 1 Follow-up Status（2026-06-13）

| ID | 描述 | 状态 | 说明 |
|---|---|---|---|
| F1.1 | budget falsification / V0 single-turn contract propagation | completed | `ecfee47`, `55e5f79`, `d39bca1`; test_f1_1 in test_subagent_v0_audit_v2.py |
| F2.1 | missing descriptor taxonomy (rejected/descriptor_not_found) | completed | `f5f10df`; TestF21MissingDescriptorTaxonomy (6 tests) + five-way discrimination (4 tests) |
| F3.1 | real contract/provider failure evidence | completed | `f5f10df`; TestF31RealContractFailure (4 tests) + TestF31RealProviderFailure (6 tests) + discrimination (2 tests) |
| F4.1 | SUPPORTED_PROVIDER_TYPES safety review | no-change | 复用 SUPPORTED_PROVIDER_TYPES 会扩大 real-opt-in 白名单权限；保持 handler 内独立校验 |
| F5.1 | G6 ordering (not_supported before fallback) | completed | `ecfee47`; test_g6 strict ordering assertions |
| F6.1 | G4 structured assertions (provider_mode/status) | completed | `ecfee47`; test_g4 structured success/provider_mode assertions |

---

## 9.3. Window 1 Deferred Debt

| ID | Debt | Severity | Current impact | Owner | Trigger | Exit condition |
|---|---|---|---|---|---|---|
| W1-D1 | `route_from_runtime_loop` / `runtime_loop_invoked=True` 在 pre-loop seam 的命名语义债 | Low | 不影响运行，provenance 正确但名称暗示 in-loop | SA-2 | lifecycle/L3 spike | 决定保留、重命名或拆分 trusted-route 与 real-loop provenance |
| W1-D2 | `_render_v0_delegate_result` docstring 未覆盖全部 status（仅列 success/failed/not_supported） | Low | 不影响运行，rejected/policy_blocked/skipped 也正确渲染 | Runtime docs | 下次修改该函数或 taxonomy | docstring 与真实 status 集一致 |
| W1-D3 | payload `error` 字段作为 in-band descriptor-missing signal | Low | 安全（仅 core.py B2 设置），但 scale 差 | SubAgent contract | 出现第二种 pre-handler error 或 payload schema versioning | dedicated typed error field/schema |
| W1-D4 | core.py fallback 对 status 使用 negative match（仅 `not_supported` 触发 fallback），而非 exhaustive match | Medium → **test-guarded（Window 2 落地）** | `test_subagent_v0_fallback_dispatch.py` 锁定 guard 语义；新增 status 仍可能 silent fall-through，但 guard 行为已 test-locked | SubAgent routing | 新增 RuntimeAction status 或再次修改 fallback 逻辑 | exhaustive status dispatch + contract tests |
| W1-D5 | provider failure 当前仅有 integration evidence（payload 注入），尚无真实外部 provider E2E | Low/Medium | 证据覆盖 handler 逻辑但非端到端 | GE Phase B | real provider dogfood/CI credentials available | real-provider failure E2E |
| W1-D6 | `parent_stop_condition` 仍是 policy literal（`"max_turns=1"`） | Low | 不影响运行，V0 确实只有 1 turn | SubAgent contract | parent runtime 引入真实 stop policy | 从真实 policy 传递并测试 |
| W1-D7 | `RuntimeIdentity` 默认 `instance_id=session_id` | Low | 不影响运行，单实例场景正确 | Runtime identity | 多实例、跨 run 或独立 instance 需求 | 独立 identity source + tests |

> 所有 debt 均不阻塞 Window 1 关闭。W1-D4 为 Medium 但无当前生产影响（所有现有 status
> 均有正确处理路径）；其余均为 Low。每条都有明确 owner、trigger 和 exit condition。

---

## 9.4. Window 2 Deferred Debt（2026-06-13）

| ID | Debt | Severity | Current impact | Owner | Trigger | Exit condition |
|---|---|---|---|---|---|---|
| W2-D1 | `_EXTRA_REDACT_PATTERNS` 长期归属（safe_metadata vs. display_events） | Low | 当前 boundary-local 定位清晰；仅多了一个"额外脱敏层"管理点 | safe_metadata / display_events 维护者 | trust-boundary contract 演进，或需统一 canonical masking 层时 | 明确迁移到 display_events（Option A 延迟版）或保持 boundary-local + 有 test 锁定 |
| W2-D2 | OD-7：Human approval hook 进生产 | Low | `confirmation_required` 结果态存在且接 AWAITING_USER；强制生产 hook 待需求 | 项目 owner | 出现多用户/生产 approval 需求 | OD-7 裁决后独立窗口 |
| W2-D3 | SPA-2：Permission vs policy staging 口径对齐 | Low | doc-only debt；gate 折叠 permission 无运行风险 | runtime_integration 维护者 | 有人误读 §4.F 5-step 独立 stage | doc-align 窗口 |
| W2-D4 | L1 attempt dead-code removal | Low | L1 dead branch（`core.py:2217` `delegate_l1_called` check）从未执行，handler 未注册 | SubAgent routing | V0 production default-on + 独立 cleanup 窗口 | 独立 cleanup 评估 + 删除 + tests 更新 |

> 所有 W2 debt 均不阻塞 Window 2 关闭。W2-D1/D3/D4 为 Low，W2-D2（OD-7）已在 §11 登记为 Open。每条均有 trigger 和 exit condition。

## 9.5. Window 3 Deferred Debt（2026-06-13）

| ID | Debt | Severity | Current impact | Owner | Trigger | Exit condition |
|---|---|---|---|---|---|---|
| W3-D1 | provider fallback precedence 的用户可见呈现仍分散在 factory/diagnostics/docs | Low | 行为清晰且 test-locked；仅影响排障时的阅读成本 | provider config 维护者 | provider diagnostics 或 config onboarding 再次修改 | 在一个 diagnostics/doc surface 中展示 precedence stack，并保持 factory 行为不变 |
| W3-D2 | profiles/env fallback 是否长期保留未裁决 | Low | compatibility path 继续可用；不会阻塞 config/config.yaml owner | 项目 owner / provider config 维护者 | config/config.yaml 成熟后准备 deprecate legacy fallback | 独立 deprecation/retention 决策 + migration note + focused tests |
| W3-D3 | action_scheduler 是否接入 production 仍 deferred | Low / P3 | 当前 dormant-by-default；无生产行为变化 | action_scheduler 维护者 | OD-7 / CR-2 或明确 multi-turn planning benchmark 需求 | 独立 plan 证明收益、接线、rollback 和 tests；不得在 CM-1 中顺手接入 |

> 所有 W3 debt 均不阻塞 Window 3 关闭。它们分别是可读性/兼容保留/未来接线决策债，
> 不是 CM-1 的失败项；CM-2、provider registry、scheduler wiring 均未启动。

## 9.6. Window 3 Post-Closure Audit Findings（2026-06-13 Gap Classification Audit）

> 本节记录 Gap Classification Audit 经 fresh-context reviewer + 本人源码/测试
> 核验后**新发现**的两项。RED-1 在该审计时是唯一 MUST_FIX_NOW，后续已由
> docs-fix 修复并恢复 full suite green；FOP-1 仍是 default-off 后的 pre-flip 缺陷。

| ID | 发现 | 证据（本人核验） | Severity | 分类 | 阻塞主线关闭? |
|---|---|---|---|---|---|
| RED-1 | full suite 曾 RED：`tests/test_docs_source_of_truth.py::test_active_docs_no_stale_config_env_vars` FAILED——`docs/06-audit/WINDOW_3_CLOSURE_AUDIT.zh.md` 裸列 `MY_FIRST_AGENT_LLM_PROVIDER` / `FIRST_AGENT_PROVIDER_PROFILE` 无 `legacy/deprecated/不推荐` 标记；后续已加 legacy marker 修复 | 当时证据：`pytest …::test_active_docs_no_stale_config_env_vars` → 1 failed；当前证据：full suite 4730 passed, 12 skipped, 26 xfailed | closed | **DONE** | NO |
| FOP-1 | flag-on（`SUBAGENT_V0_ROUTING_ENABLED=on`）+ real provider 时 V0 路由返回 `policy_blocked`：core.py V0 payload 设 `provider_mode='real_opt_in'` 但未设 `provider_mode_allowed`，`v0_contract.py:357` 默认 `fake_only` → `provider_mode_allowed` 拒 real → `policy_blocked`（落入 `_render_v0_delegate_result`，非受控 inline fallback） | `v0_contract.py:357` 默认 `fake_only`；core.py `2090-2210` 仅设 `provider_mode`/`parent_opt_in`，无 `provider_mode_allowed` | Low（默认）/ **P1-on-flip** | **TRACKED_DEBT（pre-flip blocker）** | NO（当前 flag default-off）；**YES 对 default-on flip** |

**RED-1 处置**：已由后续 docs-fix 在 `WINDOW_3_CLOSURE_AUDIT.zh.md` 的 env-var 引用旁
加 `legacy` 标记关闭；当前 full suite green。
**FOP-1 处置**：flag default-off，非当前生产风险；但 SA-1 "off→on 是独立后续工作" 的
表述必须显式携带此 pre-flip blocker：default-on flip 前须修复 `provider_mode_allowed`
传播（core.py V0 payload 注入 `profile_contract.provider_mode_allowed`）并补 real-provider
路径测试。owner = `core.py` delegation 入口维护者；trigger = 准备 default-on flip；
exit = real-provider V0 payload 经 `provider_mode_allowed` 正确放行 + 端到端测试。

> RED-1 是审计 falsifiability 的正例：W3 closure 的 GREEN 自报曾被独立 reviewer + 本人
> pytest 证伪；后续修复关闭了 RED-1，但 `MAINLINE_CLOSE_READY` 仍因 GE-2/GE-3 为 NO。

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
- **P2**：RS-1（topology alignment）、SPA-2（permission staging 口径）、
  MEM-2（memory owner，blocked_by_decision）、GE-2（capability docs）、GE-3（rubric re-score）。
  ~~SPA-1~~（completed Window 2）、~~CR-1~~（completed Window 2）、
  ~~CM-1~~（completed Window 3）。
- **P3**：MEM-1、CM-2、SPR-1、EOE-1、CR-2、CR-3、CR-4（多为 deferred/doc-align）。

## Repair Remaining Gap Classification

> **本节是按修复分类组织的主控视图**（2026-06-13 Gap Classification Audit）。
> 上方按 Theme 组织的 item 正文保留为详细背书；本节把每个 gap 归入下列 10 类，并给出
> 关闭依赖。分类规则、defer/drop/blocked 区别见 §分类方法说明（本节末）。

### 分类方法说明（defer vs drop vs blocked vs tracked debt）

- **DONE**：已实现/已 doc-correct + 有 test/closure evidence；不再是 repair 主线任务。
- **MUST_FIX_NOW**：仍偏离 North Star、真实可执行、不需外部/owner、**不修会阻塞主线关闭**。本类必须极少。
- **FIX_NEXT**：值得修、风险可控、是下一批；可能阻塞 *formal* close（DoD verification/coverage），但不是 runtime risk。
- **DEFERRED**：方向认可、现在不做（缺真实需求/收益不明/时机不成熟）；有 trigger + exit。**defer = 延后，不是忘记，也不是否认问题。**
- **BLOCKED_BY_DECISION**：需 owner/产品/架构裁决，agent 不能自决；贸然实现 = 过度设计。
- **BLOCKED_BY_EXTERNAL**：需 credential/外部 provider/CI secret/稳定外部服务，无法纯本地闭环。
- **DOC_ONLY**：runtime 基本无问题，主要是说明/命名/文档与代码不一致；修复主要是文档。
- **TRACKED_DEBT**：已有 debt id + owner/trigger/exit，不阻塞当前主线，触发时处理。
- **OPTIONAL_OR_FUTURE**：增强项，不属当前 repair 必须完成项。
- **DROP_OR_NOOP**：审计确认原判断是 overclaim / 代码已证明非问题 / 目标不再适用。

**blocked vs deferred**：blocked 有具体外部 gate（决策或 credential）卡住；deferred 是
我们*主动选择*延后（条件未成熟），即使无人阻拦也不现在做。
**deferred vs drop**：deferred 承认问题真实、未来会做；drop 判定原问题不成立 / 不再适用。
**tracked debt 是否阻塞**：不阻塞当前 mainline——它们有治理（owner/trigger/exit），
是"未来触发时处理"，不是"现在必须修"。

### 表 1：总览分类表

| ID | Theme | Original gap / item | Category | Status | Evidence | Why not simply fix in order? | Blocks mainline close? | Next action |
|---|---|---|---|---|---|---|---|---|
| SA-1 | SubAgent | V0 production routing 未接入 | **DONE** | completed (W1) | flag `SUBAGENT_V0_ROUTING_ENABLED`(core.py:1990)；G4 golden；W1 closure | 已修 | no | — |
| GE-1 Phase A | Golden E2E | 无显式 golden 套件 | **DONE** | completed (W1) | `tests/golden_e2e/` 5 文件 G1–G7 green | 已修 | no | — |
| SPA-1 | Safety | masking owner 未锁 | **DONE** | completed (W2) | `test_safe_metadata_ownership.py` 11 green；decision doc | 已修 | no | — |
| CR-1 | Compat | action_scheduler 未治理标注 | **DONE** | completed (W2+W3 label) | 4 `test_cr1_*` green；docstring `dormant-by-default`（W3 收紧 "不可达" overclaim） | 已修，无残留 | no | — |
| CM-1 | Capability | config 入口 import-boundary 未审 | **DONE** | completed (W3) | W3 inventory + W3-T1/T4；结论=保留现有 config，无 duplicate registry | 已修；"无重复→无需收敛"是合法完成 | no | — |
| W1-D4 | SubAgent | fallback negative/非穷举 match | **DONE（test-guarded）** | test-guarded (W2) | `test_subagent_v0_fallback_dispatch.py`；`VALID_RESULT_STATUSES` 闭集在 `schema.py:384` 构造期 raise，未知 status 不可达→不会 silent success | 已中和（闭集）；残留仅 maintainability | no | 收紧 debt 描述（见 §9.3 注） |
| H-1/H-2/H-3 | History | catalog extraction / D1-D3 / SoT 对齐 | **DONE** | move_to_history / protected_pending | `8be4dcb`/`a9b39ab`/`97a7bb3`/`a251306`/`5d1cdcb`；边界测试锁 | 已完成；护栏不回退 | no | 保持边界测试 |
| **RED-1** | Docs SoT | W3 closure 裸列 stale env-var → active guard RED | **DONE** | completed (RED-1) | `WINDOW_3_CLOSURE_AUDIT.zh.md` legacy marker fix；本轮 full suite 4730 passed, 12 skipped, 26 xfailed | 已修；guard 恢复 green | no | — |
| GE-1 Phase B/C | Golden E2E | memory/checkpoint/policy/evidence-trace + adversarial stub 无 golden | **DONE** | completed (GE-1 Phase B/C) | `test_golden_memory_checkpoint.py`、`test_golden_policy_evidence.py`、`test_minimal_policy_stub.py` + 5 fixtures；golden/adversarial 13 passed | 已修；仅新增 tests/fixtures，无 production 行为变化 | no | — |
| GE-3 | Acceptance | §20 rubric 全 `provisional`，未复算 | **FIX_NEXT（closure-blocking）** | documented_pending (P2) | North Star §20 12 维全 provisional；§21 DoD item 8 要求每维 ≥2 *实测* | 复算须在 suite-green + SA-1/GE-1 evidence 后做；红线禁为升分伪造 | **YES（formal close, DoD 8）** | suite-green 后按 §20 anchors 逐维取证 |
| GE-2 | Docs | capability status 四方漂移 | **DOC_ONLY** | documented_pending (P2) | `CURRENT_CAPABILITY_DRIFT.zh.md` / `CAPABILITY_BOUNDARIES.md` 已存在 | doc diff-table；DoD item 5 一致性 | partial（DoD 5） | 产可复现 diff table + terminology align |
| RS-1 | Runtime Spine | North Star §7 topology 文字 vs mediated execution | **DOC_ONLY** | active (P2) | `tool_runtime_mediator.py:228-297` 单一 mediated path；direct-execute 仅 meta/dispatcher=None；boundary tests green | doc topology drift，**非代码缺陷**（两 reviewer 确认非第二 spine） | no | North Star §7 amendment 提案（另案，不本轮改 North Star） |
| SPA-2 | Safety | permission 折叠进 gate 无独立 stage | **DOC_ONLY** | documented_pending (P2) | `tool_gate.py:184` gate_disposition 折叠；North Star §4.F 已降级 Inference | doc-align | no | 说明 gate 折叠 permission |
| MEM-1 | Memory | consolidation/emergence 真实描述 | **DOC_ONLY** | documented_pending (P3) | 两独立 off-by-default gate（`memory_runtime_hooks.py:33/152`）；truth test 锁 | doc-align，不解冻 | no | 引用 truth test 对齐文档 |
| CR-2 | Compat | legacy skill tombstone 措辞 | **DOC_ONLY** | documented_pending (P3) | `agent/skills/__init__.py` tombstone；`legacy_skills/` 不存在 | doc-align | no | 统一 tombstone 措辞 |
| CR-3 | Compat | TUI/local_demo compat label | **DOC_ONLY / OPTIONAL** | documented_pending (P3, do-not-touch) | 生产 spine 不 import tui/local_demo | 最多 1 行 doc label，可选 | no | 可选加 `# compat-path` |
| CR-4 | Compat | stale docs references | **DOC_ONLY** | documented_pending (P3) | `rg legacy_skills docs/` 定位 | doc-only | no | 修正 stale 引用 |
| SA-2 | SubAgent | L3 lifecycle relocation 收益未论证 | **DEFERRED** | documented_pending / blocked_by_evidence (P2) | live V0 真实 label = `subsystem_integration`（`evidence.py:616-648`）；`core_loop` 不可伪造 | spike-only；"无充分收益不实施"是合法结论；无 owner OD 卡 | no | 出现真实 L3/gate→3 需求时做 spike |
| SPR-1 | State | 完整状态机 enum / 跨主机 resume | **DEFERRED** | accepted_deferred (OD-8, P3) | intra-process resume 已接线（`main.py:731`）；仅 cross-host/enum deferred | 无 long-task/HITL 消费者 | no | 真实长任务/HITL 需求出现 |
| EOE-1 | Observability | cost 字段进 observability | **DEFERRED** | accepted_deferred (OD-6, P3) | `latency_ms` 已捕获；cost 非一等字段 | 无评测 harness 消费者 | no | 评测 harness 消费 cost 时 |
| CM-2 | Capability | 统一 Capability Contract | **BLOCKED_BY_DECISION** | accepted_deferred (OD-2, P3) | `idempotency_key/cost_hint/latency_hint` 仅 North Star 文字，无 .py | 无跨三者消费者；建设=投机抽象；红线 #13 禁 | no | OD-2 裁决后 |
| MEM-2 | Memory | memory canonical write owner | **BLOCKED_BY_DECISION** | blocked_by_decision (OD-9, P2) | 职责拆分 memory.py/store/hooks；North Star §4.D 标 Open | 不擅自裁决 owner（裁决 #14） | no | owner 决策 |
| OD-7 | Safety | human approval hook 进生产 | **BLOCKED_BY_DECISION** | accepted_deferred (W2-D2) | `confirmation_required` 已接 AWAITING_USER；debug 路径足够 | 需多用户/生产 approval 需求决策 | no | OD-7 裁决后 |
| W1-D5 | SubAgent | real external provider failure E2E | **BLOCKED_BY_EXTERNAL** | tracked (Low/Medium) | 仅 integration evidence（payload 注入），无真实 provider E2E | 需 credential/CI secret；且须在 GE-1 Phase B infra 之后 | no | owner 提供稳定 test provider / 批准 fake-real adapter |
| FOP-1 | SubAgent | flag-on real-provider V0 → policy_blocked | **TRACKED_DEBT（pre-flip blocker）** | newly found (§9.6) | `v0_contract.py:357` 默认 fake_only；core.py payload 不设 `provider_mode_allowed` | flag default-off，非当前生产风险 | no（default-off）；**YES 对 default-on flip** | default-on flip 前修 `provider_mode_allowed` 传播 + real-provider 测试 |
| W1-D1/D2/D3/D6/D7 | SubAgent | route 命名/docstring/in-band error/stop literal/identity 债 | **TRACKED_DEBT** | tracked (Low) | §9.3 登记 | 均 Low，有 owner/trigger/exit | no | 触发时处理 |
| W2-D1 | Safety | `_EXTRA_REDACT_PATTERNS` 长期归属 | **TRACKED_DEBT** | tracked (Low) | §9.4 登记 | boundary-local 定位清晰 | no | trust-boundary contract 演进 |
| W2-D4 | SubAgent | L1 attempt dead-code removal | **TRACKED_DEBT** | tracked (Low) | dispatcher 无 L1 handler（本人核验 get_handler→None）；branch 不可达 | 删除需独立 cleanup 窗口 | no | V0 default-on + cleanup 窗口 |
| W3-D1/D2/D3 | Capability/Compat | provider precedence 呈现 / fallback 退役 / scheduler wiring 决策 | **TRACKED_DEBT** | tracked (Low/P3) | §9.5 登记 | 可读性/兼容/未来接线债 | no | 各自 trigger |
| S2 / S3 / S4 | (旧) | mediator/core-loop thickness、tests 重组 | **DROP_OR_NOOP** | REMOVE_AS_OBSOLETE (§2) | 无耦合证据，纯 cosmetic；helper 结构已存在 | 审计确认非真实问题 | no | 不做 |
| scheduler "不可达" | Compat | W2 曾称 scheduler `inert/unreachable` | **DROP_OR_NOOP** | corrected (W3) | W3 收紧为 `dormant-by-default`；37 `test_scheduler_main_path` 证 seam 可注入 | 原措辞 overclaim，已修正 | no | — |

### 表 2：依赖与触发表（未 DONE item）

| ID | Depends on | Blocked by | Trigger to revisit | Exit condition | Owner / decision needed | Recommended priority |
|---|---|---|---|---|---|---|
| GE-3 | SA-1 ✓、GE-1 ✓、suite green ✓ | 无（可执行） | 下一 closure step | §20 每维实测回填，每分附 evidence | 架构审计 owner | P2（DoD 8） |
| GE-2 | 与 CR-2/CR-4 协同 | 无 | doc-align 批次 | 四方 diff-table 一致 + 可复现校验 | docs/runtime owner | P2（DoD 5） |
| RS-1 | 无 | North Star amendment 需用户批准 | 评 PR 误判 topology 时 | North Star §7 文字与 mediated execution 一致 | core/mediator owner + 用户 | P2（doc-only） |
| SPA-2 / MEM-1 / CR-2 / CR-3 / CR-4 | 无 | 无 | doc-align 批次 | 文档与代码/测试一致 | 各模块维护者 | P2/P3（doc-only） |
| SA-2 | SA-1 ✓（baseline） | 缺 L3 真实需求（blocked_by_evidence） | 出现 gate→3 / L3 真实需求 | spike 文档结论明确（做 or 保持 subsystem_integration） | 架构 owner | P2（spike） |
| SPR-1 | 无 | OD-8 + 无 long-task 消费者 | 跨主机/长任务/HITL 需求 | OD-8 裁决 + canonical enum | 项目 owner（OD-8/OD-10） | P3 |
| EOE-1 | 无 | OD-6 + 无评测消费者 | 评测 harness 消费 cost | OD-6 裁决 | 项目 owner（OD-6） | P3 |
| CM-2 | 无 | OD-2 + 无跨三者消费者 | 出现跨 Tool/Skill/MCP 消费者 | OD-2 裁决 | 项目 owner（OD-2） | P3 |
| MEM-2 | 无 | OD-9（owner 决策） | owner 决策启动 | canonical owner 裁决 + single-owner test | 项目 owner（OD-9） | P2 |
| OD-7 | 无 | owner/产品决策 | 多用户/生产 approval 需求 | OD-7 裁决 | 项目 owner（OD-7） | P3 |
| W1-D5 | GE-1 Phase B（infra 先行） | 外部 credential/CI secret | Phase B 落地 + credential 可用 | real-provider failure E2E green | SubAgent owner + 外部 | P3 |
| FOP-1 | 无（代码内可修） | 仅在 default-on flip 前必须 | 准备 default-on flip | `provider_mode_allowed` 正确传播 + real-provider V0 测试 | core.py delegation owner | P1-on-flip（当前 P3） |
| W1-D1/D2/D3/D6/D7、W2-D1/D4、W3-D1/D2/D3 | 各自 | 无 | 各自 trigger（§9.3/§9.4/§9.5） | 各自 exit | 各模块维护者 | P3（tracked） |

---

## Architecture Repair Mainline Closure Readiness

> 依据 North Star §21 Definition of Done（逐项 conjunction，不取平均）逐条核验。

1. **P0/P1 open 是否为 0?** —— 是。P0 = 0；P1 = 0。SA-1 与 GE-1 Phase A/B/C 均已 completed。
2. **MUST_FIX_NOW 是否为 0?** —— 是。RED-1 已修复，当前 full suite green。
3. **Blocker / High debt 是否为 0?** —— 是。所有 debt 为 Low（W1-D4 Medium 已 test-guarded）；三窗 review 均 0 Blocker / 0 High。
4. **Window 1/2/3 closure 是否完整?** —— 是，三份 closure audit 存在且有 verdict；RED-1 已由后续 docs-fix 纠正。
5. **Full suite 最近一次是否 green?** —— 是。本轮核验当前 main 为 **4730 passed, 12 skipped, 26 xfailed**。
6. **剩余项是否都属 deferred / blocked / optional / doc-only / tracked debt?** —— **否**。GE-3 仍是 closure-blocking FIX_NEXT（DoD item 8）；GE-2 + doc-align cluster 仍是 DoD item 5。
7. **当前是否可以关闭 architecture repair mainline?** —— 否。
8. **若不能，少数必须修的项：**
   - **GE-3**（DoD item 8）：§20 rubric 逐维实测 ≥2 复算。
   - **GE-2 + doc-align cluster**（DoD item 5）：capability/docs/runtime fact 一致。

> 注：DoD items 1/2/3/6/7/9 已满足（无 Blocker/High、生产路径单 spine、Medium 已治理、
> 扩展点稳定、deferred 无双主路径/双 SoT、Open decisions 均有 owner+exit）。DoD item 4
> 已由 GE-1 Phase B/C golden coverage 补齐；未满足的是 items 5（docs 一致）与
> 8（rubric 实测）。这些都是 **verification / documentation 完成度**，**不是
> runtime/architecture risk**。

**MAINLINE_CLOSE_READY = NO**

Remaining must-fix items:
- GE-3：按 §20 anchors 逐维复算 rubric（DoD item 8）。
- GE-2 + doc-align（RS-1/SPA-2/MEM-1/CR-2/CR-4）：capability/docs/runtime fact 一致（DoD item 5）。

> 这些都是 doc/test 完成项，无 runtime 风险、无外部 credential（除 W1-D5/real-provider）、
> 无 owner 决策门槛（GE-3/GE-2 均 agent 可执行）。
> 一旦 GE-2 完成 + GE-3 复算确认每维 ≥2，主线即可关闭。

---

## 14. 下一批推荐主线

1. **SA-1 + GE-1 Phase A** 同窗口 co-delivery：V0 wiring 迁移定义 + 最小 Golden E2E。
   GE-1 的 conversation+tool 场景独立可 green；subagent 场景先验当前 inline-local，
   SA-1 落地后重指向 V0——非循环前置，是唯一能推动 critical gate 向 3 的组合。
   **（Window 1 已 completed，Window 2 继续推进 SA-2 spike）**
2. ~~SPA-1（completed Window 2）+ CR-1（completed Window 2）~~
3. ~~CM-1（completed Window 3）~~
4. **GE-2**（capability docs diff-table）：清 Documentation critical 维度。
5. **SA-2**（SubAgent lifecycle / L3 evidence design spike）：评估搬迁收益与风险。
6. **RS-1**（tool mediated-execution topology alignment）：核验 gate/result/evidence 统一治理。

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
