---
created: 2026-05-29
status: completed
source: Independent re-audit after evidence closure (docs/audits/2026-05-28-full-subsystem-capability-completion-audit-redteam-addendum.md)
final_score: 3.7/5 (保守基线，不再上调)
deepened: none
---

# Evidence Hardening Plan — Narrow Pass

> **Post-completion note (2026-05-29)**: Batch A (004 checkpoint + 007 MCP bridge evidence-only) 和 Batch B (008 scheduler code-path injection) 均已完成。独立 combined review 保守结论：**3.7/5**。Credibility: 3 credible (001/004/005) + 4 partial-credible (003/006/007/008) + 1 questionable (002)。003/006/007 均为 partial-credible，不标 fully validated。006 real provider E2E 和 007 real MCP invocation 须作为单独新阶段处理。B7/B8 排除。当前阶段建议阶段性收口。

## 1. Problem Frame

独立复审结论：当前 REAL-EVIDENCE closure credibility = **2/8 credible, 6/8 questionable**。项目得分 3.2/5，比原始 red-team 推断 1.4/5 明显改善，但不能严谨称为 "fully validated"。

目标：在不进入 B7/B8、不大范围重构的前提下，通过窄范围 evidence hardening 把可信度从 3.2/5 推到 3.7-4.0/5。

## 2. Scope Boundaries

### In Scope
- Evidence-only hardening：加固验证脚本，不改变生产代码行为
  - REAL-EVIDENCE-004 — Checkpoint true resume
  - REAL-EVIDENCE-007 — MCP runtime-mediated invocation
  - REAL-EVIDENCE-001 — Memory recall provenance（可选）
- Code-path hardening（单独批次，不改生产代码则不混入）
  - REAL-EVIDENCE-008 — Scheduler main-path injection

### Out of Scope
- B7 Multi-instance readiness
- B8 TUI architecture
- 大范围重构
- 新增架构决策
- 把全部 questionable 一口气修完
- 006 TOOL_MEDIATOR_GAP 的生产代码修复（defer）
- 003 Skill allowed_tools claim downgrade（暂保持现状，后续单独做 scripted dogfood）
- 关闭 evidence 除非验证真的补足 main runtime path

## 3. Item Classification

| ID | Capability | Category | Rationale |
|----|-----------|----------|-----------|
| 001 | Memory recall provenance | evidence-only（可选） | 行为闭环已验证（13/13 PASS），部分路径使用 direct dispatcher route() 而非 route_from_runtime_loop()；加固脚本即可，收益较小 |
| 003 | Skill allowed_tools | **later optional** | 暂保持现状，不先降级 claim；后续如需补，单独做 scripted dogfood 诱导 disallowed tool 场景 |
| 004 | Checkpoint true resume | evidence-only（Batch A） | Handler path 存在；validation script 有 direct-save fallback；需要修复脚本重新验证 |
| 006 | SubAgent TOOL_MEDIATOR_GAP | **defer** | 真正的代码缺口：core.py 传入 tool_mediator=None，child tool mediation 无法在 production path 触发；修复需要 tool_mediator 依赖注入（非 trivial，触及 state/messages/turn_context） |
| 007 | MCP runtime-mediated invocation | evidence-only（Batch A） | Code path 完整（MCP 工具走统一 Tool pipeline）；当前证据是 direct execute_tool()；需要 model-selected MCP tool invocation 证据 |
| 008 | Scheduler main-path injection | code-path（Batch B，单独处理） | 真正的代码缺口：ActionScheduler 不在默认 core.chat() 路径中；需要 SDD/TDD，不与 Batch A 混在同一批 |

## 4. Item-by-Item Judgment

### 4.1 REAL-EVIDENCE-001 — Memory Recall Provenance

**当前状态**: credible（独立复审认可行为闭环）

**问题**: 部分 evidence 使用 `dispatcher.route()` 而非 `dispatcher.route_from_runtime_loop()`。行为正确但 provenance 标记不够精确。

**判断**: evidence-only hardening。加固 `scripts/real_evidence_001_memory.py` 中 recall 的 provenance 检查——验证 MEMORY_RECALL 走的是 `route_from_runtime_loop()` 而非 generic `route()`。不需要改生产代码。

**不做什么**: 不改 memory recall 主路径代码；不重跑全部 13 个 case。

### 4.2 REAL-EVIDENCE-003 — Skill allowed_tools

**当前状态**: questionable（独立复审认为 same-turn real blocking 未证实）

**问题**: Contract tests 验证了 disallowed-tool blocking 逻辑，但 real dogfood 中：
- confirmation='always' 策略阻止所有 tool 执行（TOOL_GATE: 0 accepted, 2 rejected）
- 模型遵循 skill 指令，不会尝试调用 disallowed tool
- 因此无法在真实路径中证明 "模型尝试调 disallowed tool → 被 blocked"

**判断**: **暂保持现状，不进 Batch A**。
- 不先降级 claim——当前 CLOSED 状态虽然独立复审判定 questionable，但 contract tests 层面的验证充分，closure claim 有合理依据
- 不放入 Batch A 作为第一项
- 后续如需补证据：单独做 scripted dogfood，用 scripted scenario 诱导模型调用 disallowed tool（而非依赖模型自主决策），验证 blocking 行为
- 这不是设计缺陷——confirmation='always' 是安全特性，不是代码缺口

**不做什么**: 不降级 claim；不把 confirmation 改为 'never' 来让测试通过；不新增 hack 绕过安全策略。

**独立复审 caveat（2026-05-29）**: 003 暂保持现状，但独立复审认为仍有 caveat——same-turn real disallowed-tool blocking 未在真实路径验证，confirmation='always' 策略会阻止 tool execution 从而阻止 disallowed-tool blocking 场景的触发。本次 Batch A 不处理 003，不修改 debt 状态。

### 4.3 REAL-EVIDENCE-004 — Checkpoint True Resume

**当前状态**: questionable（script 有 direct-save fallback，real provider 部分有 concern）

**问题**: `scripts/real_evidence_004_checkpoint.py` 中当 dispatcher 不可用时 fallback 到 `save_checkpoint()` direct call。这削弱了 "dispatcher-mediated" 声称。

**判断**: evidence-only hardening。修复 validation script：
1. 移除 direct-save fallback——当 dispatcher 不可用时标 CONCERN 而非静默 fallback
2. 加强 real provider 部分的 checkpoint 触发条件（不依赖 tool execution 触发 save）
3. 重新验证

**不做什么**: 不改 checkpoint save/resume handler 生产代码（handler path 已正确）；不改变 checkpoint 存储格式。

### 4.4 REAL-EVIDENCE-006 — SubAgent TOOL_MEDIATOR_GAP

**当前状态**: questionable（child tool mediation 未在 core delegation path 证实）

**问题**: `agent/core.py:1301` — `l1_handler.set_provider(provider, None)` 传入 `tool_mediator=None`。这是真正的代码缺口：child 无法在 production delegation path 中通过 parent mediator 调用工具。

**风险单独说明**:
- **风险等级**: 中高
- **原因**: tool_mediator 的构造依赖 state、messages、turn_context、dispatcher 等依赖，这些在 delegation 点未必全部可用
- **如果修**: 需要仔细设计 tool_mediator 的依赖注入方式，可能触及 `_dispatch_or_fallback_delegation()` 的函数签名和 L1 handler 的初始化流程
- **如果不修**: child tool mediation 只能通过 contract tests 验证，production path 无法触发——这是一个已知限制，但 L1 child loop/result/adjudication 的基本能力不受影响
- **推荐**: **本阶段不修**。31 个 contract tests 已充分验证 tool mediation 逻辑。在文档中明确标注为 known limitation。

**不做什么**: 不修改 tool_mediator 依赖注入；不改变 delegation path 架构。

### 4.5 REAL-EVIDENCE-007 — MCP Runtime-Mediated Invocation

**当前状态**: questionable（direct execute_tool()，不是 model-selected）

**问题**: MCP 工具已注册在 TOOL_REGISTRY 中，可通过 `tool_registry.execute_tool()` direct call 调用。但缺少 model-selected MCP tool invocation 证据（模型看到 MCP tool → 选择调用 → 通过统一 Tool pipeline 执行 → 结果进入上下文）。

**判断**: evidence-only hardening。MCP 工具已经走统一 Tool pipeline（TOOL_GATE→TOOL_INVOKE→TOOL_RESULT），只需要创建脚本通过 `core.chat()` 验证模型能选择并调用 MCP 工具。需要：
- 真实 provider
- `scripts/fixtures/mcp_echo_server.py`（已存在）
- `MY_FIRST_AGENT_MCP_ENABLE=1` + MCP config

**不做什么**: 不改 MCP bridge/tool pipeline 生产代码；不需要新增 MCP server fixture。

### 4.6 REAL-EVIDENCE-008 — Scheduler Main-Path Injection

**当前状态**: questionable（手动 harness，默认 chat() 无 scheduler）

**问题**: `ActionScheduler` 类、handler、contract tests (46 pass)、手动 harness 都存在，但默认 `core.chat()` 不注入 `ActionScheduler`。`loop.py:run_main_loop()` 中 scheduler 集成点在 `call_model()` 之前，但 `core.chat()` 创建 `LoopDependencies` 时未包含 scheduler。

**判断**: **code-path hardening（Batch B）**。需要在 `core.chat()` 中注入 `ActionScheduler`，使 scheduler 在默认 main path 中可用。这是本计划中唯一需要改生产代码的项。

## 5. Batch Definitions

### Batch A: Evidence-Only Hardening（推荐先做）

**目标**: 把 004 和 007 从 questionable 推进到 credible，不改变生产代码行为。

**包含**:
- A1: REAL-EVIDENCE-004 — Checkpoint script 加固（移除 direct-save fallback + 重验证）
- A2: REAL-EVIDENCE-007 — MCP model-selected invocation 脚本 + 验证
- A3: REAL-EVIDENCE-001 — Memory recall provenance 加固（可选，收益小）

**明确不包含**:
- REAL-EVIDENCE-003 — 暂保持现状，不降级 claim，后续单独做 scripted dogfood

**不做什么**:
- 不改任何 `agent/` 下的生产代码
- 不改 checkpoint handler / MCP bridge / memory recall 逻辑
- 不新增 MCP server fixture
- 不做 claim downgrade

**需要改的文件类别**:
- `scripts/real_evidence_004_checkpoint.py` — 修复
- `scripts/real_evidence_007_mcp_invoke.py` — 新建
- `scripts/real_evidence_001_memory.py` — 可选小修
- `docs/debt/REAL_EVIDENCE_VALIDATION_DEBT.md` — 更新 004/007 状态
- `docs/PROJECT_STATUS.md` — 更新分数和状态
- `docs/PROGRESS_LEDGER.md` — 记录 batch 完成

**需要真实 provider**: 是（004 重新验证、007 MCP invocation）
**需要真实 MCP server**: 是（007 需要 `scripts/fixtures/mcp_echo_server.py`，已存在）
**需要改 production code**: 否
**成功标准**:
- 004: checkpoint script 不再有 direct-save fallback，real provider 部分 PASS（非 CONCERN）
- 007: `core.chat()` 中模型选择并调用 MCP tool → 通过 TOOL_GATE→TOOL_INVOKE→TOOL_RESULT → 结果进入上下文
- REAL-EVIDENCE credibility: 2/8 → 3-4/8 credible
**停止条件**:
- 007: 如果模型在真实对话中不选择 MCP tool（模型自主决策），不以 hack 方式强制调用——标为 PARTIAL 并注明原因
- 004: 如果 real provider 下仍然无法触发 checkpoint save（不依赖 tool execution），保留 CONCERN 并注明约束
**失败归因**:
- 脚本设计问题 → 修脚本
- 模型行为问题（不选 MCP tool、不触发 checkpoint）→ 标为模型自主决策约束，非代码缺陷
- 环境/网络问题 → 保持 pending
**预计分数提升**: 3.2 → 3.4-3.5

### Batch B: Code-Path Hardening（单独处理，不混入 Batch A）

**目标**: 把 REAL-EVIDENCE-008 (Scheduler) 推进到 main-path credible。这是 code-path hardening，需要 SDD/TDD。

**包含**:
- 单独的 SDD/TDD loop，不改 evidence scripts
- `core.chat()` 中注入 `ActionScheduler`（或新增 `chat_with_scheduler()` 入口）
- 新建 `scripts/real_evidence_008_scheduler_main_path.py` 验证默认路径
- 更新 RuntimeDecisionFrame scheduler branch points

**为什么单独处理**:
- 这是本计划中唯一需要改生产代码的项
- 需要 SDD（设计 scheduler 注入方式）和 TDD（先写 failing test）
- 不应和 evidence-only script hardening 混在同一 commit

**不做什么**:
- 不重写 scheduler 逻辑
- 不改变 scheduler handler/contract
- 不新增 scheduler node type
- 不让 scheduler 替代现有的 plan mode 流程

**需要改的文件类别**:
- `agent/core.py` — chat() 中注入 ActionScheduler
- `agent/loop.py` — 可能需要调整 scheduler 集成点
- `scripts/real_evidence_008_scheduler_main_path.py` — 新建
- `agent/runtime_decision_frame.py` — 更新 scheduler branch point 状态
- `tests/unit/test_runtime_decision_frame.py` — 更新 branch point status 断言
- `docs/debt/REAL_EVIDENCE_VALIDATION_DEBT.md` — 更新 008
- `docs/PROJECT_STATUS.md` — 更新
- `docs/PROGRESS_LEDGER.md` — 记录

**需要真实 provider**: 是（验证 scheduler 在主路径中工作）
**需要真实 MCP server**: 否
**需要改 production code**: 是
**成功标准**:
- 默认 `core.chat()` 路径下 scheduler 可用并产生 ACTION_PLAN_START/NODE_ENTER/NODE_EXIT/ACTION_PLAN_COMPLETE evidence
- 不是手动构造 ActionPlan 再调度——由真实 planner.generate_plan() 触发
- RuntimeDecisionFrame scheduler branch points 标 CODE_PATH_COMPLETE 或以上
**停止条件**:
- 如果 scheduler 注入破坏了现有 plan mode 流程 → 回退，改用 opt-in `chat_with_scheduler()` 变体
- 如果 scheduler 注入需要大幅改动 core.py 架构 → 标为 deferred，不改
**失败归因**:
- scheduler 注入位置不正确 → 调整集成点
- scheduler 与 plan mode 冲突 → 可能需要分离二者或标 deferred
- 模型不生成多步 plan → 模型行为约束，非代码问题
**预计分数提升**: 在 Batch A 基础上 3.4-3.5 → 3.7-4.0

## 6. Items Not in Current Pass (Post-Completion Status)

| Item | Disposition | Current Status |
|------|------------|----------------|
| 006 TOOL_MEDIATOR_GAP | 已实现 (_dispatch_or_fallback_delegation 内部构造 ToolRuntimeMediator) | **partial-credible** — 42 contract tests pass，缺 real provider child structured tool_use E2E。后续须作为单独新阶段 |
| 003 Skill allowed_tools | 已硬化 (FakeProvider + main runtime path) | **partial-credible** — 5/5 PASS，缺 real provider same-turn disallowed-tool dogfood。不建议继续投入 |
| 007 MCP invocation | Batch A 已硬化 (TOOL_GATE entry proven) | **partial-credible** — TOOL_INVOKE / call_tool / result / feedback 未验证。后续须作为单独新阶段 |
| B7 Multi-instance | **excluded** | 用户明确排除 |
| B8 TUI | **excluded** | 用户明确排除 |
| 002 Skill selection | **not in scope** | questionable — deterministic keyword fallback，不是 model-owned skill selection |

## 7. Recommendation

### 推荐先做 Batch A

理由：
1. 不改变生产代码，风险最低
2. 004 和 007 是当前最突出的 credible gap（独立复审明确指出 script fallback 和 direct execution 问题）
3. 预计能把 credibility 从 2/8 推到 3-4/8，分数从 3.2 推到 3.4-3.5
4. Batch A 完成后可以独立 re-audit 确认效果，再决定是否进入 Batch B

### 第一批具体包含

按优先级：
1. **A1 (004 checkpoint)** — 修复已有脚本（移除 direct-save fallback），重验证
2. **A2 (007 MCP invocation)** — 新建脚本，需要真实 provider + MCP fixture，验证 model-selected MCP tool invocation
3. **A3 (001 provenance)** — 可选，收益小，如果 004+007 已经足够推到目标分数可跳过

### 003 为什么不先做

- 当前 CLOSED 状态有合理依据（contract tests + evidence chain）
- 降级 claim 不能替代真实验证——如果后续要补，应做 scripted dogfood 而非文档修正
- 没有紧迫性——不阻塞 004/007/008 的硬化

### 008 为什么单独处理

- 需要改生产代码（`core.chat()` 注入 scheduler），与 evidence-only 的 004/007 性质不同
- 需要 SDD（决定 opt-in `chat_with_scheduler()` vs 默认注入）+ TDD（先写 failing test）
- 不应和 evidence script hardening 混在同一 commit
- Batch A 完成后的 re-audit 可以更好判断 Batch B 的必要性和范围

### 是否建议先交给独立审计 agent review 这个 plan

建议。这个 plan 做了明确的分类决策（哪些 evidence-only、哪些 defer、哪些 later optional），独立审计可以验证分类合理性以及成功标准是否足够严格。

### 是否建议完成 Batch A 后再 re-audit

是。Batch A 完成后应该做一次 mini re-audit，验证：
- credibility count 是否真的从 2/8 提升
- 新的 evidence 是否满足 strict standard
- 是否有新的 overclaim 引入
- Batch B 是否仍然必要

## 8. Draft Implementation Prompt — Batch A

```
请执行 Evidence Hardening Plan Batch A（docs/plans/2026-05-29-evidence-hardening-plan.md）。

安全约束：
- 不要读取 .env 文件内容
- 不要打印 API key / token / secret
- 不要提交任何 secret
- 只使用当前 shell 已配置的 provider 环境

执行顺序：

### A1: REAL-EVIDENCE-004 — Checkpoint Script 加固

1. 修改 scripts/real_evidence_004_checkpoint.py：
   - 移除 direct save_checkpoint() fallback
   - 当 dispatcher 不可用时标 CONCERN 而非静默 fallback
   - 加强 real provider checkpoint 触发条件（不依赖 tool execution 触发 save）
2. 重新运行验证脚本
3. 更新 REAL_EVIDENCE_VALIDATION_DEBT.md 中 004 状态

### A2: REAL-EVIDENCE-007 — MCP Runtime-Mediated Invocation

1. 新建 scripts/real_evidence_007_mcp_invoke.py：
   - 使用真实 provider + core.chat()
   - 启用 MCP bridge（MY_FIRST_AGENT_MCP_ENABLE=1, dry_run=0）
   - 配置指向 scripts/fixtures/mcp_echo_server.py
   - 验证 MCP tools 在 model-visible tools 中
   - 通过对话让模型选择并调用 MCP echo tool
   - 验证 TOOL_GATE→TOOL_INVOKE→TOOL_RESULT evidence chain
   - 验证 MCP tool result 进入模型上下文
   - stop condition: 如果模型不主动选择 MCP tool，不以 hack 强制——记录为模型自主决策约束
2. 运行验证脚本
3. 更新 REAL_EVIDENCE_VALIDATION_DEBT.md 中 007 状态

### A3: REAL-EVIDENCE-001 — Memory Provenance（可选，收益小）

1. 修改 scripts/real_evidence_001_memory.py 的 recall 部分：
   - 验证 MEMORY_RECALL 走 route_from_runtime_loop() 而非 generic route()
2. 如果改动小，重跑验证

### 收尾

1. 更新 docs/PROJECT_STATUS.md Section 0 分数和 credibility count
2. 更新 docs/PROGRESS_LEDGER.md
3. 运行 affected tests: pytest tests/runtime_integration/ -x -q
4. ruff check 所有修改的脚本
5. 如果所有 REAL-EVIDENCE 状态变化收敛，commit 并 push

不要进入 Batch B，不要改 production code，不要碰 003 Skill allowed_tools。
```
