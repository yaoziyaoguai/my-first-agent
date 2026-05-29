# First Agent Runtime Lab — Stage Architecture Review

**日期**: 2026-05-29
**类型**: 阶段性架构复盘
**范围**: evidence-hardening 阶段（原始 redteam → 当前 3.7/5 保守基线）
**审计算子**: 独立架构复盘 agent，非实现 agent
**代码变更**: 无

---

## 1. Executive Summary

First Agent 是一个 **Agent Runtime Lab / Evidence-driven runtime prototype**，不是 Claude Code 或 Codex 的竞品。它的核心实验问题是：一个 agent runtime 应该在多大程度上拥有自己的 decision vocabulary、evidence chain 和 capability classification，才能诚实地回答"我现在能做什么"。

当前阶段从原始 redteam 审计的推断基线 **1.4/5** 提升到 **3.7/5**（保守基线）。提升主要来自两项工作：

- **Batch A**（evidence-only hardening）：加固了 Checkpoint（004）和 MCP bridge（007）的验证脚本和证据链，未修改生产代码。
- **Batch B**（code-path hardening）：将 ActionScheduler 注入到 `core.chat()` 主路径中，使 scheduler preprocessing block 从 dead code 变为可触发路径。

**当前可以阶段性收口**。理由：
- evidence-hardening 已进入递减收益区间；
- 继续修 003/006/B7/B8 都是结构性工作，不是"小补证据"；
- 3.6/5 已经足够支撑阶段性的架构总结；
- 后续如果继续，应单独开下一阶段，不与当前证据硬化混在同一批次。

**B7（Multi-instance readiness）和 B8（TUI architecture）不进入当前阶段**。它们是后续大型架构/产品化决策，独立的复审已将其明确排除在当前 score 计算之外。

---

## 2. What Changed Since Original Redteam Audit

原始 redteam 审计（2026-05-28 addendum）的结论：名义完成率 77%（90/117），严格校正后 23.1%（27/117）。根因是将 registry/descriptor/docs/guard-test 存在、no-crash dogfood、以及 direct subsystem call 混在一起计为 COMPLETE。

以下子系统在 evidence-hardening 阶段发生了实质性变化：

### 2.1 RuntimeDecisionFrame

**文件**: `agent/runtime_decision_frame.py`（609 lines）

建立了 14 个预定义 branch point 的诚实注册表（0 READY / 8 PARTIAL / 1 NOT_READY / 2 DEFERRED / 1 FAKE_DEMO / 1 STUB），每个 branch point 绑定 evidence_level。核心规则：`is_capability_complete()` 要求 status==READY AND evidence_level >= FAKE_LOCAL_USER_PATH。禁止 overclaim 的组合在 guard tests 中强制执行（35 tests）。

**价值**: 把"这个子系统当前能做什么"从分散的文档声称收敛到一个代码级、可测试的单一事实源。

### 2.2 Evidence Classification

**文件**: `agent/runtime_integration/evidence.py`、`agent/evaluation_honesty.py`

实现了两层分类：
- `is_business_capability_evidence()` — 区分 business disposition（allowed/recalled/retain/executed/...）和 probe disposition（noop/no_action/rejected），禁止 routing evidence（`real_core_loop_runtime_e2e` alone）等同于业务能力证明。
- `classify_evaluation()` — 4 级枚举（CAPABILITY_PASS/REAL_VALIDATION_PENDING/CAPABILITY_FAIL/SMOKE_PASS），硬编码 `can_no_crash_be_capability=False`、`can_fake_harness_close_debt=False`。

**价值**: 从机制上阻止 future audits 重复 77% overclaim。

### 2.3 Tool Path Unification

**文件**: `agent/tool_runtime_mediator.py`

模型 `tool_use` 路径现在通过 `ToolRuntimeMediator` 进入 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT evidence chain，不再裸调 `execute_single_tool`。gate_disposition 驱动执行流：allowed → execute；rejected/None → FORCE_STOP（安全失败）。

**价值**: 消除了"Tool 有两条分离路径"的架构分裂。

### 2.4 Memory Main Path

**文件**: `agent/core.py`、`agent/loop.py`

Memory recall 统一走 dispatcher path（`refresh_runtime_system_prompt(dispatcher=...)`），不再直接调 `_memory_runtime.snapshot_for_prompt()`。retain/recall/forget 使用共享 store，confirmation-to-store evidence chain 闭合。真实 provider dogfood 验证了 retain/recall/forget 的行为闭环（REAL-EVIDENCE-001: 13/13 PASS）。

### 2.5 Skill Activation / allowed_tools

**文件**: `agent/skill_selection.py`、`agent/response_handlers.py`

实现了确定性 keyword matching skill selection（`select_skill_for_real_provider()`），body load 和 active skill prompt injection 已连接。allowed_tools contract path 有效：`ToolRuntimeMediator` 检查 `skill_allowed_tools`，disallowed tool → rejected → FORCE_STOP。

**已知限制**: selection 是 deterministic fallback，不是 model-owned skill tool selection（REAL-EVIDENCE-002 questionable）；same-turn disallowed-tool blocking 已通过 main runtime path (core.chat → ToolRuntimeMediator → TOOL_GATE) 验证，但 production dogfood 因 confirmation='always' 策略阻止了 tool execution（REAL-EVIDENCE-003 partial-credible）。

### 2.6 Checkpoint True Resume Evidence Hardening

**Batch A 硬化**: 移除了验证脚本中的 direct `save_checkpoint()` fallback（Guardrail 2: dispatcher 不可用时标 CONCERN 而非静默 fallback）；CHECKPOINT_PATH 重定向确保 dispatcher handler 写入正确 temp path。Part A 10/10 PASS；Part B 2 CONCERN（tools executing but no checkpoint save point reached）。

### 2.7 MCP Bridge / External Flight

**Batch A 硬化**: 新建 `scripts/real_evidence_007_mcp_invoke.py`，验证 real StdioMCPClient bridge → TOOL_REGISTRY（W1/W2: 2 tools registered PASS）。不再使用 direct `execute_tool()` 作为 MCP invocation 证据。W3-W6 CONCERN — 模型未选择 MCP tool（Guardrail 1: 不 hack model behavior）。

### 2.8 SubAgent L1

**文件**: `agent/core.py`（`execute_l1()`、`delegate_l1()`、`_dispatch_or_fallback_delegation()`）

L1 child provider loop 已实现：child 调真实 provider → 返回结果 → parent adjudication。Real provider dogfood 验证了 delegate → child_result → parent_adjudication evidence chain（15 PASS / 0 FAIL / 1 CONCERN）。

**已知限制**: TOOL_MEDIATOR_GAP 已修复（ToolRuntimeMediator 在 `_dispatch_or_fallback_delegation()` 中构造并 set_provider()）；42 contract tests 验证 child tool mediation 逻辑；real provider child structured tool_use E2E 未实现（MODEL_BEHAVIOR_CONCERN），SimpleNamespace turn_state / _turn_context caveat 存在（REAL-EVIDENCE-006 partial-credible）。后续须作为单独新阶段处理。

### 2.9 Advanced Scheduler

**Batch B 硬化**: `core.chat()` 接受 `action_scheduler` 参数 → `_run_main_loop()` → `LoopDependencies` 注入 → `run_main_loop()` scheduler preprocessing block 实际触发（不再 dead code）。20 个 new contract tests 验证注入契约 + 主路径 evidence + 边界防护；66/66 scheduler tests pass。设计边界明确：Scheduler 是 orchestration layer，不是第二 runtime，不直接执行 Tool/Memory/MCP/SubAgent。

**已知限制**: 缺 full `core.chat(..., action_scheduler=scheduler)` E2E 测试；ActionPlan 仍是 hand-built fixture，不是 real model-generated plan。

### 2.10 Dogfood / Evaluation Harness Honesty

`agent/evaluation_honesty.py`（~220 lines）实现了 SMOKE_PASS ≠ CAPABILITY_PASS 的硬编码分类。41 个 guard tests 验证 fake/local/no-crash/expected_events 不能关闭 REAL-EVIDENCE debt。CaseEvaluator 已修复 expected_events 从死字段升级为 CONCERN 判定条件。

### 2.11 UX / Error Recovery / Storage Hygiene

Provider error → RuntimeEvent fallback（不 crash）；scheduler node failure → 用户可见通知；checkpoint resume → `[系统] 正在恢复上次对话状态...`；log hygiene（50MB rotation + sanitization）；storage hygiene（`.gitignore` 添加 `state.json`/`runs/`）。

---

## 3. Current Evidence Baseline

以下基线反映 **2026-05-29 独立审计复核后的保守口径**。使用 strict main-path evidence standard（`core.chat()` 默认路径、非 direct-call、非 manual harness）。

### 3.1 Overall Score

**3.7 / 5**（保守基线，不再上调）

比原始 redteam inferred 1.4/5 明显改善；不敢标 4.0+，因为仍有多项 partial-credible 和 questionable 未闭合。

### 3.2 Credible（3/8）

| ID | Capability | 硬化后状态 | 关键证据 |
|----|-----------|----------|---------|
| REAL-EVIDENCE-001 | Memory retain/recall/forget | credible | 真实 provider dogfood: 13/13 PASS，shared store 一致性确认，12 positive assertions，非 no-crash PASS |
| REAL-EVIDENCE-004 | Checkpoint save/resume | **credible** (hardened) | Batch A: direct-save fallback removed, Part A 10/10 PASS；Part B 2 CONCERN 归因修正（checkpoint save trigger condition not met） |
| REAL-EVIDENCE-005 | MCP bridge readiness | credible | 真实 StdioMCPClient subprocess JSON-RPC: 12/12 PASS，tools_discovered=2, tools_registered=2, allowlist 生效 |

### 3.3 Partial-Credible（4/8）

| ID | Capability | 硬化后状态 | 关键证据 | Caveats |
|----|-----------|----------|---------|---------|
| REAL-EVIDENCE-003 | Skill allowed_tools | **partial-credible** | Contract tests + main runtime path (core.chat → ToolRuntimeMediator → TOOL_GATE) 验证 disallowed-tool blocking | FakeProvider + scripted skill activation，非 real model SKILL_SELECT；production dogfood 因 confirmation='always' 无法自动验证 same-turn blocking |
| REAL-EVIDENCE-006 | SubAgent L1 | **partial-credible** | Code path complete: execute_l1() + delegate_l1() + ToolRuntimeMediator injection；42 contract tests pass | 缺 real provider child structured tool_use E2E；SimpleNamespace turn_state / _turn_context caveat 存在；后续须作为单独新阶段处理 |
| REAL-EVIDENCE-007 | MCP external flight | **partial-credible** | MCP pipeline entry (TOOL_GATE) 通过 FakeProvider + main runtime path 验证；bridge registration 通过 real StdioMCPClient | TOOL_INVOKE / StdioMCPClient.call_tool / real MCP result / conversation feedback 未验证；后续须作为单独新阶段处理 |
| REAL-EVIDENCE-008 | Advanced scheduler | **partial-credible** (code-path injection credible) | Batch B: core.chat() 注入 chain 结构正确，20 contract tests + 66/66 pass | 缺 full core.chat() E2E；ActionPlan 为 hand-built fixture；无 real model-generated plan |

### 3.4 Questionable（1/8）

| ID | Capability | 状态 | 为什么 questionable |
|----|-----------|------|-------------------|
| REAL-EVIDENCE-002 | Skill selection | questionable | 确定性 keyword fallback，不是 model-owned skill tool selection |

### 3.5 Deferred / Optional

| Item | Disposition | Reason |
|------|------------|--------|
| 003 Skill allowed_tools | 不建议继续投入 | confirmation='always' 是安全特性；contract tests + main-path evidence 验证充分（partial-credible）；same-turn blocking 验证需要绕过安全策略的 scripted dogfood |
| 006 real provider E2E | 后续单独新阶段 | 42 contract tests 已充分验证逻辑；real provider child structured tool_use E2E 需要模型行为配合，非 trivial change |
| 007 real MCP invocation | 后续单独新阶段 | TOOL_INVOKE / call_tool / result / feedback 未验证；confirmation='always' 在 production 中阻止 TOOL_INVOKE |
| B7 Multi-instance | 后续大型架构决策 | 需要消除模块级单例；不是当前阶段范围 |
| B8 TUI | 后续产品化决策 | 需要 TUI framework decision；不是当前阶段范围 |

---

## 4. What We Learned

### 4.1 Fake / Direct-Call / No-Crash 不能算 Capability

原始 redteam 77% overclaim 的核心机制：no-crash dogfood → PASS、expected_events 存在 → PASS、fake provider smoke → capability complete。Evaluation honesty guard 现在硬编码了 `can_no_crash_be_capability=False`、`can_fake_harness_close_debt=False`。但这仍然是需要持续警觉的点——只要 review 不独立、audit standard 不 strict，同类 overclaim 就会复发。

### 4.2 Code Path Complete ≠ Real Validation Complete

Loop 3.4 Scheduler 是最典型案例：554 lines of scheduler code + 46 contract tests + manual harness → 被标为 REAL-EVIDENCE-008 CLOSED。但 `core.chat()` 不注入 ActionScheduler → scheduler preprocessing block 是 dead code。Code path 存在不等于能力已接入主路径。Batch B 正是针对这个缺口做了 code-path injection。

### 4.3 Evidence-Only Hardening 和 Code-Path Hardening 必须分开

Batch A（004/007 evidence-only）不改生产代码，只加固验证脚本和证据链。Batch B（008 code-path）需要改 `core.chat()` 签名和 `LoopDependencies`，走 SDD+TDD。两类工作的风险剖面、review 策略、回滚路径完全不同。混在一起会导致 reviewer 无法判断生产代码是否被意外修改。

### 4.4 Scheduler 不能成为第二 Runtime

Batch B SDD 的设计边界（AD-3）明确：Scheduler 是 orchestration layer，不直接执行 Tool/Memory/MCP/SubAgent。实际执行仍复用已有 RuntimeAction / dispatcher / mediator / handler。如果 scheduler 开始拥有自己的 tool execution path、自己的 memory write path，就会退化为原始 redteam 指出的"两个能力平面"问题——只是换了名字。

### 4.5 SubAgent Parent/Child Mediation 是深水区

TOOL_MEDIATOR_GAP（006）暴露了 SubAgent 架构的核心张力：child tool mediation 需要 tool_mediator，而 tool_mediator 的构造依赖 state、messages、turn_context、dispatcher。这些依赖在 delegation 点未必全部可用。不是简单的"加个参数"，而是一个需要独立 SDD 的架构决策。31 contract tests 验证了逻辑正确性，但 production path 的打通不是 trivial change。

### 4.6 RuntimeDecisionFrame 对防 Overclaim 有价值

14 个 branch point 的诚实注册表，0 READY，8 PARTIAL，全部绑定 evidence_level。`is_capability_complete()` 和 `should_not_silent_pass()` 提供了代码级 overclaim 防护。但它不是银弹——如果 registry 本身不更新（batch point status 滞后于代码实现），它也会变成 stale documentation。当前 registry 仍全是 PARTIAL，没有 READY branch point，这本身是一个需要持续维护的信号。

### 4.7 Independent Audit 对避免自我催眠有价值

原始 closure 声称 8/8 REAL-EVIDENCE CLOSED。独立复审将可信度降到 2/8 credible、6/8 questionable。后续 Batch A+B 将 004/007/008 推到了 credible/partial-credible。但整个过程说明：同一 agent 先实现再审计自己的实现，与独立 agent 只读审计已有代码和证据，两者输出有系统性偏差。独立审计作为阶段收口前的最后一道 check 是低成本、高收益的。

---

## 5. Remaining Risks

| Risk | Severity | Detail |
|------|---------|--------|
| 002 Skill model-owned selection | P2 | 当前 deterministic keyword fallback 是明确设计选择，不是缺失。但如果在后续阶段声称 Skill 就绪，必须先解决 model-owned selection |
| 003 Skill allowed_tools real blocking | P2 | 不建议继续投入。confirmation='always' 是安全特性，contract tests + main-path evidence 验证充分（partial-credible） |
| 006 SubAgent real provider E2E | P2 | **后续单独新阶段**。42 contract tests 已充分验证逻辑，缺 real provider child structured tool_use E2E。SimpleNamespace caveat 存在 |
| 007 MCP real invocation | P2 | **后续单独新阶段**。TOOL_INVOKE / call_tool / result / feedback 未验证；confirmation='always' 在 production 中阻止 TOOL_INVOKE |
| 008 Scheduler full E2E | P2 | 缺 full core.chat() E2E + real model-generated ActionPlan。code-path injection 已验证，但完整闭环需要 planner bridge + E2E test |
| B7/B8 | deferred | 后续大型架构/产品化决策，不进入当前阶段 |

---

## 6. Why Stop Here

### 6.1 Evidence-Hardening 已进入递减收益

Batch A（004+007 evidence-only）将 credibility 从 2/8 推到 3/8；Batch B（008 code-path injection）推到 3 credible + 1 partial-credible。独立 combined review 保守结论：3 credible (001/004/005) + 4 partial-credible (003/006/007/008) + 1 questionable (002)。剩余的 partial-credible items（003/006/007/008）和 questionable item（002）都不再是"加固验证脚本"能解决的——它们要么是设计选择（002 确定性 fallback）、要么是安全特性的必然结果（003 confirmation='always'）、要么需要 real provider/model E2E（006/007/008）。

### 6.2 006/007/B7/B8 都不是"小补证据"

- **006**: real provider child structured tool_use E2E 需要模型行为配合（MODEL_BEHAVIOR_CONCERN），非代码修复能解决；SimpleNamespace caveat 仍需处理
- **007**: TOOL_INVOKE / call_tool / result / feedback 未验证，confirmation='always' 在 production 中阻止 TOOL_INVOKE
- **B7**: 需要消除模块级单例，是全局架构变更
- **B8**: 需要 TUI framework decision，是产品化决策

这几项都不是当前阶段 batch 的合理延续——它们是各自独立的下一阶段。

### 6.3 3.7/5 已经足够支撑阶段性架构总结

从 1.4/5 → 3.7/5（保守基线）的提升代表了：移除了 direct-save fallback、消除了 Scheduler dead code、建立了 evidence classification 体系、建立了 RuntimeDecisionFrame、完成了 8 个 REAL-EVIDENCE 的硬化（3 credible + 4 partial-credible + 1 questionable）。这是一个有意义的阶段性里程碑。

### 6.4 后续如果继续，应单独开下一阶段

不应继续在"evidence-hardening"这个 umbrella 下混入结构性代码变更。每个后续方向（006 hardening / scheduler full E2E / B7 / B8）都值得自己的 SDD、自己的 scope boundary、自己的 success criteria。

---

## 7. Next-Stage Options

以下选项**只列不启动**。每个选项都需要独立的 scope definition、SDD 和 reviewer approval 才能进入。

- **Option A**: 停止当前阶段，做学习总结。直接收口，把 3.7/5 作为阶段性基线记录，转向学习总结或新实验方向。
- **Option B**: 单独开 006 real provider E2E hardening。real provider child structured tool_use E2E + SimpleNamespace caveat 修复。风险中高，需要模型行为配合。
- **Option C**: 单独开 B7 Multi-instance readiness。消除模块级单例，使 runtime 支持多实例。大型架构变更。
- **Option D**: 单独开 B8 TUI architecture。TUI framework selection + implementation。产品化决策。
- **Option E**: 继续完善 scheduler full core.chat() E2E / model-generated plan bridge。将 008 从 partial-credible 推到 credible。

---

## 8. Source of Truth

后续继续时必须先读以下文档，按优先级排列：

| # | 文档 | 用途 |
|---|------|------|
| 1 | `docs/PROJECT_STATUS.md` | 当前状态、分数、credibility 矩阵、Section 0 独立复审 override |
| 2 | `docs/PROGRESS_LEDGER.md` | 完整进度历史、每个 milestone 的 commit 和简述 |
| 3 | `docs/debt/REAL_EVIDENCE_VALIDATION_DEBT.md` | 每个 REAL-EVIDENCE item 的详细证据、验证步骤、已知限制 |
| 4 | `docs/plans/2026-05-29-evidence-hardening-plan.md` | Batch A/B 的范围定义、分类逻辑、成功/停止条件 |
| 5 | `docs/audits/2026-05-28-full-subsystem-capability-completion-audit-redteam-addendum.md` | 原始 strict standard、27/117 校正完成率、full gap matrix |
| 6 | `docs/design/runtime-decision-spine.md` | Decision frame 设计原则、与 runtime 的边界、overclaim 防护规则 |
| 7 | `docs/design/batch-b-scheduler-main-path-injection.md` | Batch B SDD、scheduler 注入设计、scope boundaries |

---

## Appendix A: Score Progression

| Date | Event | Score | Credibility |
|------|-------|------:|------------|
| 2026-05-28 | Original redteam addendum | 1.4/5 (inferred) | — |
| 2026-05-29 | Initial REAL-EVIDENCE closure (overclaimed) | claimed "8/8 CLOSED" | overclaim |
| 2026-05-29 | Independent re-audit after closure | 3.2/5 | 2/8 credible, 6/8 questionable |
| 2026-05-29 | Batch A complete (004+007 evidence-only) | 3.5/5 | 3-4/8 credible |
| 2026-05-29 | Batch B complete (008 code-path injection) | 3.6/5 | 3 credible, 1 partial-credible, 4 questionable |
| 2026-05-29 | 保守证据可信度基线（独立 combined review） | 3.7/5 | 3 credible (001/004/005), 4 partial-credible (003/006/007/008), 1 questionable (002) |

## Appendix B: Key Architecture Decisions Preserved

以下架构决策在 evidence-hardening 阶段被确认和记录（非新建）：

1. **Scheduler 不是第二 runtime**（AD-3 from `advanced-scheduler-contract.md`）
2. **Decision frame 描述不执行**（`runtime-decision-spine.md` Section 3）
3. **Fake/real 共享主路径，不共享证据等级**（`evaluation_honesty.py`）
4. **Evidence-only hardening 和 code-path hardening 分批次**（`evidence-hardening-plan.md` Section 5）
5. **TOOL_MEDIATOR_GAP 是已知限制，不阻塞 CLOSED**（`REAL_EVIDENCE_VALIDATION_DEBT.md` 006）

## Appendix C: Test Baseline

| Category | Count | Status |
|----------|------:|--------|
| Total regression tests | 574 | 568 pass / 6 pre-existing failures |
| Scheduler contract tests | 66 | 66/66 pass |
| Decision frame guard tests | 35 | 35/35 pass |
| Evaluation honesty guard tests | 41 | 41/41 pass |
| Evidence taxonomy guard tests | 24 | 24/24 pass |
| Scheduler main-path contract tests | 20 | 20/20 pass (Batch B new) |
| Log hygiene tests | 21 | 21/21 pass |
| Config safety guard tests | 8 | 8/8 pass |
