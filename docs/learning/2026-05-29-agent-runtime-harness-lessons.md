# Agent Runtime / Harness Engineering — Lessons Learned

**日期**: 2026-05-29
**项目**: First Agent (my-first-agent)
**阶段**: evidence-hardening 阶段性收口
**当前基线**: 3.7/5（保守），3 credible + 4 partial-credible + 1 questionable

本文档沉淀 First Agent 项目在 agent runtime / harness 工程化过程中的关键判断和可复用经验。不是项目状态报告，不是为了展示功能完成度，而是后续做类似项目时可以参考的方法论笔记。

---

## 1. 为什么做这个项目

First Agent 不是 Claude Code 或 Codex 的竞品。它不追求产品化的用户体验、多实例部署、TUI 界面。

它是一个 **Agent Runtime Lab**——一个刻意保持最小的实验环境，用来拆解和验证以下问题：

- 一个 agent runtime 应该拥有什么样的 decision vocabulary？
- Tool / Memory / Skill / MCP / SubAgent / Scheduler / Checkpoint 这些子系统如何进入统一 runtime path？
- 如何区分"代码存在"和"能力就绪"？
- 如何防止 AI agent 在自举开发中自我催眠——写上代码、跑通测试、就声称能力完成？

项目的核心产出不是某个 feature，而是：
- **RuntimeDecisionFrame**：14 个 branch point 的诚实注册表，0 READY
- **Evidence classification 体系**：区分 credible / partial-credible / questionable
- **统一 Tool runtime path**：ToolRuntimeMediator → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT
- **一套验证方法论**：fake ≠ real，direct-call ≠ main-path，no-crash ≠ capability

---

## 2. 核心架构判断

### 2.1 一条统一 main runtime path

每个子系统（Tool、Memory、Skill、MCP、SubAgent、Scheduler、Checkpoint）都应该通过**同一条 dispatcher-mediated pipeline** 进入 runtime。不能让 Tool 有一条路径、Memory 有另一条路径、Skill 再有一条路径。

具体实现：
- `ToolRuntimeMediator` 是模型 tool_use 的唯一入口
- 所有 runtime action 通过 `RuntimeActionDispatcher` 分发
- Evidence 在 dispatcher 层面统一收集，而不是在各个 handler 里各自埋点

### 2.2 子系统是有限的 branch point / intervention point

不是每个子系统都要成为一个独立的 runtime。RuntimeDecisionFrame 的核心设计原则：**frame 描述状态，不执行逻辑**。14 个 branch point 各自回答一个具体问题（"MCP bridge 是否就绪"、"Skill 是否激活"），但 frame 本身不做任何决策。

### 2.3 不能每个能力做成第二 runtime

这是最容易踩的坑。Scheduler 是最典型的案例：
- 有 ActionScheduler 类和 handler
- 有 46 个 contract tests
- 有手动 harness 证明"可以跑"
- 但 `core.chat()` 默认路径不注入 ActionScheduler → scheduler preprocessing block 是 dead code

教训：如果一个能力有自己的执行路径、自己的状态管理、自己的 evidence 收集方式，它就变成了第二 runtime。Scheduler 的设计边界（AD-3）明确写了：**Scheduler 是 orchestration layer，不直接执行 Tool/Memory/MCP/SubAgent**。

### 2.4 fake / real 只能是 provider / adapter / config 差异

FakeProvider 和 RealProvider 的差异只能在 provider 层——不能因为用了 FakeProvider 就走不同的 tool execution path、不同的 memory write path、不同的 dispatcher evidence chain。这是本项目反复出现的问题：
- Tool path 一度有真实执行路径和 RuntimeAction evidence 路径两个分支
- Memory recall 一度有 dispatcher path 和 direct store call 两个分支

解决方式：**统一 path，差异只在最外层注入点**。FakeProvider 只是换了一个 provider 实例，其余 pipeline 完全一致。

### 2.5 SubAgent child 必须 parent-mediated

Child loop 不能绕过 parent 直接调工具、直接写 memory、直接产生 user-visible output。所有 child action 必须通过 parent 的 ToolRuntimeMediator、parent 的 memory store、parent 的 dispatcher 中介。理由：
- 安全：parent 可以 gate child 的工具调用
- 可观测：parent dispatcher 能看到所有 child evidence
- 一致：不存在"child 做了但 parent 不知道"的状态

---

## 3. 证据判断力

这是整个项目最重要的方法论收获。

### 3.1 五个不等式

| 不等式 | 说明 | 本项目中的案例 |
|--------|------|---------------|
| **fake ≠ 真实能力** | FakeProvider 通过的测试不能证明真实 provider 下行为一致 | 003 Skill allowed_tools：FakeProvider 验证了 blocking 逻辑，但 real provider dogfood 因 confirmation='always' 无法自动验证 |
| **direct-call ≠ main-path** | 直接 `dispatcher.route()` 或 `execute_tool()` 不能证明默认 `core.chat()` 路径中有同样行为 | 008 Scheduler：手动构造 ActionScheduler + hardcoded ActionPlan → 不是 main-path evidence |
| **no-crash ≠ capability** | 不 crash 是最低标准，不是能力完成 | Dogfood harness 曾把 no-crash 标为 PASS，后修正为 SMOKE_PASS |
| **expected event 出现 ≠ 能力完成** | dispatcher evidence 中有某个 event type 不等于该能力就绪 | 原始 redteam 77% overclaim 的核心机制 |
| **code path complete ≠ real validation complete** | 代码路径存在 + contract tests 通过 ≠ 真实 E2E 验证完成 | 006 SubAgent：42 contract tests pass 但 real provider E2E 被 MODEL_BEHAVIOR_CONCERN 阻止 |

### 3.2 credible / partial-credible / questionable

这是本项目的证据可信度三级分类：

- **credible**：真实 provider/main-path 验证通过，positive assertions 充分，非 no-crash PASS。例：001 Memory（13/13 PASS + shared store consistency）、004 Checkpoint（Batch A hardened，direct-save fallback removed）、005 MCP bridge（real StdioMCPClient subprocess JSON-RPC，12/12 PASS）
- **partial-credible**：部分验证通过，但有关键 caveat。例：003（FakeProvider，非 real model SKILL_SELECT）、006（code path fixed 但缺 real provider child tool_use E2E）、007（TOOL_GATE entry proven 但 TOOL_INVOKE/call_tool/result 未验证）、008（code-path injection credible 但缺 full core.chat() E2E + model-generated ActionPlan）
- **questionable**：只有 contract/design 级别证据，没有 real main-path 验证。例：002（deterministic keyword fallback，不是 model-owned skill selection）

**关键规则：partial-credible 不能通过"文档措辞调整"升级为 credible。** 如果 caveat 是真实存在的，它就是 partial-credible。只有补齐了 caveat 对应的验证（如 real provider E2E），才能重新评估。

### 3.3 为什么要有 REAL-EVIDENCE debt

REAL-EVIDENCE debt 是一份集中登记的"真实验证债务"清单。它的作用：
- 防止每个 loop 被手工 dogfood 打断节奏
- 防止把"contract tests 通过"当作"能力就绪"
- 给后续验证收敛提供一个明确的 checklist
- 在 PROJECT_STATUS 中引用 debt ID，防止 overclaim

登记原则：
- 新的 capability loop 完成后，如果缺真实 dogfood，登记到 debt
- 不要把它写成 loop 本身的 blocker
- 最后集中处理（validation convergence loop），而非零散逐个验证

### 3.4 为什么独立审计能防止自我催眠

同一 agent 先实现再审计自己的实现，与独立 agent 只读审计已有代码和证据——两者输出有系统性偏差。

本项目的实际经历：
- 实现 agent 声称 8/8 REAL-EVIDENCE CLOSED
- 独立复审降到 2/8 credible、6/8 questionable
- 后续 Batch A+B 将 004/007/008 推到 credible/partial-credible

这不是"实现 agent 在骗人"——而是实现 agent 对整个代码库的投入感、对 contract tests 的熟悉度、对"代码存在=能力存在"的默认假设，会让它在评估时系统性地低估证据缺口。独立审计 agent 没有这些负担，它只看"证据链是否真的闭合"。

**建议**：每个重要阶段收口前，必须由独立 agent 做只读审计。这不是不信任实现 agent，而是认识到单一 agent 的认知盲区。

---

## 4. Harness 工作流经验

### 4.1 推荐工作流

```
redteam audit → plan → implementation → independent review → status update
```

每个阶段的职责边界：

| 阶段 | 做什么 | 不做什么 |
|------|--------|---------|
| redteam audit | 只读审计现有代码/测试/文档，按 strict standard 评估 evidence | 不改代码，不修问题 |
| plan | 基于审计 findings，做分类（evidence-only / code-path / defer），定义 scope boundary | 不实现，不在 plan 里写实现代码 |
| implementation | 按 plan 的 scope 和 batch 顺序执行 | 不超出 scope，不边修边发散 |
| independent review | 独立 agent 只读审计 implementation 产出 | 不实现，不与实现 agent 共享 context |
| status update | 更新 PROJECT_STATUS / PROGRESS_LEDGER / debt | 不 overclaim，不为好看而调高分数 |

### 4.2 evidence-only hardening 和 code-path hardening 必须分开

- **Evidence-only hardening**：只改验证脚本，不改生产代码。加固断言、移除 fallback、重新验证。风险低，回滚简单。
- **Code-path hardening**：改生产代码（如 `core.chat()` 签名、依赖注入）。需要 SDD + TDD，风险中高。

两类工作**不能混在同一 commit**：
- 混在一起 reviewer 无法判断生产代码是否被意外修改
- 回滚粒度太粗——evidence script 修坏了不应该回滚 production code
- commit message 无法准确描述变更性质

### 4.3 plan 要先 review，不能边修边发散

这是本项目最重要的流程教训。多次出现"在修 003 的过程中顺手修了 006"、"做 Batch A 的时候开始改 production code"的情况。

规则：
- Plan 里写了什么 scope，就做什么 scope
- 如果发现了 plan scope 外的缺口，记下来，放入 next loop candidates
- 不要"顺便修一下"——这会破坏 scope boundary、让 review 无法判断完成度、让 plan 变成废纸

### 4.4 每次修完要更新 PROJECT_STATUS / PROGRESS_LEDGER / debt

不是可选的。不是"等所有 loop 修完再统一更新"。每个 loop 完成后立即更新：
- PROJECT_STATUS：分数、credibility matrix、loop 状态
- PROGRESS_LEDGER：milestone + commit hash + 简述
- REAL_EVIDENCE_VALIDATION_DEBT：相关 item 的证据和状态

这三个文档是后续独立审计的入口。如果它们过时，审计 agent 拿到的就是错误的基线。

### 4.5 什么时候要停止，什么时候可以继续

**必须停止的情况**（hard stop）：
- Secret 泄漏风险（真实 API key 即将被 commit）
- 需要读取/覆盖用户真实 config/config.yaml
- 需要读取真实 .env / sessions / runs / episodes
- 危险操作（rm -rf / force push main / 删库）
- 引入第二条 runtime flow / fake-real split
- 重大架构分支点改变（需用户确认）
- P0/P1 连续修复失败 >= 2 次

**不是停止条件的情况**：
- Loop 成功完成 → 自动继续下一个 pending loop
- commit/push 完成 → 自动继续
- review 完成 → review 后如有 next loop 且无 hard stop，继续
- "next recommended loop" 输出 → 判断并继续

**递减收益信号**——应该考虑阶段性收口而不是继续修：
- 剩余 items 都是结构性工作（需要 SDD+TDD），不是"小补证据"
- 继续修的边际收益递减（从 3.2→3.5 容易，从 3.5→4.0 需要跨越 real provider/model E2E）
- evidence-hardening 和 code-path hardening 的边界开始模糊

---

## 5. 代码风格和架构风格经验

### 5.1 模块边界

- `core.py`：只做 orchestration——串联 provider、dispatcher、loop、handlers
- `loop.py`：只做 turn loop——不持有业务逻辑，不直接操作 Tool/Memory store
- `ToolRuntimeMediator`：模型 tool_use 的唯一入口，gate → invoke → result
- `RuntimeActionDispatcher`：runtime evidence 的唯一分发点
- Handler（`*Handler`）：接收 dispatcher 分发的 action，执行业务逻辑，返回 result
- Provider：模型调用的抽象层——FakeProvider 和 RealProvider 共享同一接口
- Store：持久化抽象层——不直接操作文件/数据库

**关键边界**：
- Handler 不能绕过 dispatcher 直接产生 evidence
- core.py 不能直接调 store.write()——必须通过 dispatcher
- loop.py 不能直接调 execute_single_tool()——必须通过 ToolRuntimeMediator

### 5.2 依赖注入

关键接缝必须用依赖注入，不能硬编码：

**做对了的例子**：
- `core.chat(action_scheduler=...)`——scheduler 通过参数注入
- `LoopDependencies`——把 dispatcher/store/scheduler/provider 打包注入 loop
- `l1_handler.set_provider(provider, tool_mediator)`——provider 和 mediator 在 delegation 点注入

**做错了的例子**：
- `core.py:1301` 曾硬编码 `tool_mediator=None`——导致 child tool mediation 在 production path 不可用（TOOL_MEDIATOR_GAP）
- executor.py 曾硬编码占位符字符串 `f"[L1 child] 工具 {tool_name} 已执行。"`——而非真实 tool result

### 5.3 状态和 evidence 要显式

- 不要藏在 prompt 叙事里：`system_prompt += "[Active Skill: demo-note-maker]"` 是 prompt engineering，不是 runtime state
- 用 dispatcher evidence 显式记录：SKILL_SELECT、TOOL_GATE、TOOL_INVOKE、TOOL_RESULT
- RuntimeDecisionFrame 是代码级可查询的状态注册表——不是文档里的自然语言描述

### 5.4 文件组织

- 高内聚、低耦合：一个 handler 文件只处理一种 RuntimeActionType
- 不机械拆文件：200-400 行是合理范围，不要为了"每个文件 <100 行"而拆出贫血抽象
- core.py 会膨胀——800 行以内可以接受，超过就要考虑拆出 helper module
- 测试文件按 subsystem 组织，不要一个 test 文件覆盖所有 handler

---

## 6. 这次踩过的坑

### 6.1 Tool path 的真实执行路径和 evidence 路径分裂

**问题**：`handle_tool_use_response()` 一度直接调 `execute_single_tool()` 执行工具，同时 `ToolRuntimeMediator` 产生 TOOL_GATE/TOOL_INVOKE/TOOL_RESULT evidence——但两者是分离的两条路径。Tool 实际上被执行了，但 evidence 上说它走了 mediator pipeline。

**修法**：ToolRuntimeMediator 成为 model tool_use 的唯一入口。`execute_single_tool()` 只在 mediator 内部调用。

### 6.2 Skill selection 的 model-owned vs deterministic fallback 混淆

**问题**：项目最初声称 Skill 能力就绪，但实际上 skill selection 走的是 keyword matching fallback（`select_skill_for_real_provider()`），不是模型自主调用 SKILL_SELECT tool。

**为什么没修**：这是明确的设计选择——真实模型的 tool_use 行为不可控，keyword matching 提供了可解释、可验证的 fallback。但它不是 model-owned skill selection。两者是不同的能力等级。

### 6.3 Checkpoint save/load 被误认为 true resume

**问题**：checkpoint 验证脚本有 `save_checkpoint()` direct fallback——当 dispatcher 不可用时静默 fallback 到直接文件写入。这让验证结果看起来是"dispatcher-mediated checkpoint save"，但实际上可能是 direct-call。

**修法**：移除 direct fallback，dispatcher 不可用时标 CONCERN 而非静默 fallback。只检查 dispatcher handler 实际写入的文件。

### 6.4 MCP bridge readiness 和 MCP external invocation 混淆

**问题**：`run_mcp_bridge()` 注册 MCP tools 到 TOOL_REGISTRY = bridge readiness。模型通过 `core.chat()` 选择并调用 MCP tool → TOOL_GATE→TOOL_INVOKE→call_tool→TOOL_RESULT = external invocation。这两个是不同层级的能力。Bridge readiness 可以用 fake client + contract tests 验证；external invocation 需要真实 MCP server + real provider + confirmation policy 允许。

当前状态：bridge readiness = credible (005)；external invocation = partial-credible (007)，TOOL_INVOKE / call_tool / result / feedback 未验证。

### 6.5 SubAgent child tool mediation 代码路径有 gap

**问题**：`core.py` 中 `l1_handler.set_provider(provider, None)` 传入 `tool_mediator=None`。child loop 中模型调用的工具无法通过 parent 的 ToolRuntimeMediator 执行，只能返回硬编码占位符。

**修法**：`_dispatch_or_fallback_delegation()` 内部构造 ToolRuntimeMediator，注入 provider。但 real provider E2E 受模型行为限制（模型偏好直接工具调用而非 delegation），仍为 partial-credible。

### 6.6 Scheduler 手动 harness 被误当成 main path

**问题**：Scheduler 有 46 个 contract tests + 手动 harness → 被标为 REAL-EVIDENCE-008 CLOSED。但 `core.chat()` 默认路径不注入 ActionScheduler → scheduler preprocessing block 是 dead code。手动 harness 不是 main-path evidence。

**修法**：Batch B 注入了 scheduler 到 `core.chat()` 主路径（7 行改动）。但缺 full core.chat() E2E + model-generated ActionPlan，仍然是 partial-credible。

### 6.7 文档里的 CLOSED / validated 容易写得过满

**问题**：实现 agent 在项目状态文档中写了大量 "VALIDATED"、"ALL REAL-EVIDENCE CLOSED"、"8/8" 等措辞。独立复审发现其中 6/8 是 questionable。

**根因**：实现 agent 对代码的投入感让它把"代码存在 + contract tests 通过"等同于"能力就绪"。这不是故意的欺骗，而是认知偏差。

**防护**：
- `evaluation_honesty.py` 硬编码 `can_no_crash_be_capability=False`
- RuntimeDecisionFrame 的 `is_capability_complete()` 要求 status==READY AND evidence_level >= FAKE_LOCAL_USER_PATH
- 独立审计作为阶段收口前的最后一道 check

### 6.8 真实 API dogfood 容易被环境、confirmation policy、模型行为影响

具体表现：
- confirmation='always' 策略阻止了所有 tool execution（003、007 受影响）
- 模型行为不可控：选择直接调用工具而非委托给 subagent（006 MODEL_BEHAVIOR_CONCERN）
- checkpoint save 触发条件依赖 tool execution（004 Part B CONCERN）
- 结果字段不匹配导致 result_size=0（007 W6 CONCERN）

这些都不是代码缺陷，而是真实环境中的约束。在做 evidence hardening 时必须如实记录，不能为了"PASS"而绕过它们。

---

## 7. 后续迁移价值

### 7.1 迁移到 MindForge

MindForge 如果要做一个 agent runtime harness，可以从本项目直接迁移：
- **RuntimeDecisionFrame** 模式：定义 MindForge 自己的 branch points，诚实注册状态
- **Evidence classification** 体系：区分 credible / partial-credible / questionable
- **统一 Tool path**：ToolRuntimeMediator → gate → invoke → result 的 pipeline 设计
- **REAL-EVIDENCE debt** 登记机制：在开发过程中持续记录验证缺口

### 7.2 迁移到 Web Data Copilot / DataOps Copilot

这些项目涉及 Tools 和外部 API 调用：
- **confirmation policy** 的设计经验：什么时候 always、什么时候 never、什么时候 ask
- **Tool gate** 的 policy enforcement 模式：server_allowlist、destructive tool patterns、skill_allowed_tools
- **SubAgent parent-mediation** 模式：child 不能绕过 parent 直接调外部 API

### 7.3 迁移到车载语音助手 Agent 观测 / 记忆评测

- **Memory main-path** 模式：retain → confirmation → propose → store → recall → forget 的统一 pipeline
- **Checkpoint true resume** 验证方法：不是 save/load file smoke，而是跨保存/恢复的 dispatcher evidence chain 连续性
- **Evidence 显式化**：Memory 的 provenance（谁写入的、什么时候、通过哪个 dispatcher path）必须在 evidence 中可追溯

### 7.4 用这套方法审 Claude Code / Codex / Harness Agent 的输出

- 问：这个声称的能力，有没有经过独立 agent 的只读审计？
- 问：验证用的是 fake provider 还是真实 provider？
- 问：验证走的是默认 main path 还是 direct-call / manual harness？
- 问：验证的断言是 positive assertions 还是 no-crash / expected_events？
- 问：如果有 CONCERN，是否被诚实地记录和分类？

---

## 8. 以后继续开发 First Agent 的原则

如果后续要继续开发 First Agent，以下原则必须遵守：

1. **不要从当前阶段继续乱补**。3.7/5 是阶段性收口基线。不要在"evidence-hardening"这个 umbrella 下混入结构性代码变更。

2. **新阶段必须先写 stage plan**。每个后续方向（006 real provider E2E、007 real MCP invocation、008 scheduler full E2E、B7 multi-instance、B8 TUI）都需要独立的 SDD、scope boundary、success criteria。

3. **每个阶段先 SDD/TDD，再 implementation，再独立审计**。不能跳过任何一个环节。

4. **不允许把 partial-credible 直接升级成 credible**。升级必须通过补齐 caveat 对应的真实验证——不是文档措辞调整。

5. **不允许因为想提高分数而包装证据**。3.7/5 就是 3.7/5。如果真实能力只有 3.7，就不要标 4.0。

6. **006 / 007 / 008 / B7 / B8 都必须单独开阶段**：
   - 006 real provider E2E：需要模型行为配合，非纯代码修复
   - 007 real MCP invocation：需要解决 confirmation policy + mediator field mismatch + model-selected invocation
   - 008 scheduler full E2E：需要 planner bridge + model-generated ActionPlan + full core.chat() E2E
   - B7 multi-instance：需要消除模块级单例
   - B8 TUI：需要 TUI framework decision

7. **每次 stage 完成后必须由独立 agent 审计**。不接受实现 agent 自我审计的结果。

8. **保持 RuntimeDecisionFrame 的诚实性**。当前 0 READY branch point 不是耻辱——它是诚实的。如果后续把某个 branch point 推到 READY，必须有对应的 real main-path E2E evidence。

---

## 附录：关键文档索引

这些是后续继续开发时必须先读的文档：

| # | 文档 | 用途 |
|---|------|------|
| 1 | `docs/PROJECT_STATUS.md` | 当前状态、分数、credibility matrix |
| 2 | `docs/PROGRESS_LEDGER.md` | 完整进度历史 |
| 3 | `docs/debt/REAL_EVIDENCE_VALIDATION_DEBT.md` | 每个 REAL-EVIDENCE 的详细证据和 caveat |
| 4 | `docs/reviews/2026-05-29-first-agent-runtime-lab-stage-review.md` | 阶段性架构复盘 |
| 5 | `docs/plans/2026-05-29-evidence-hardening-plan.md` | Batch A/B 的范围定义和分类逻辑 |
| 6 | `docs/design/runtime-decision-spine.md` | Decision frame 设计原则 |
| 7 | `docs/design/batch-b-scheduler-main-path-injection.md` | Batch B SDD |
| 8 | `docs/design/advanced-scheduler-contract.md` | Scheduler 架构决策 |
| 9 | `docs/design/mcp-real-external-flight-contract.md` | MCP external flight 设计 |
