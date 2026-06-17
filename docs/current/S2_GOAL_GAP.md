# S2 Goal Gap / Release Backlog — Governed Task Agent

> Current authoritative document (`docs/current/`). S2 gap backlog，由
> `S2_BASELINE_STATUS.md`（现状）vs `S2_GOAL.md`（目标）生成。本文是 **backlog**，
> 不是施工结果。本任务只生成 gap，不修 gap、不进入 gap loop。
>
> 规则（见 AGENTS.md goal rules）：不删未完成 gap；完成需证据；不把 S2_GOAL.md 未
> 承诺的能力强行变成 gap；不把所有 TECH_DEBT 塞成 S2 必修。保留 Gap ID 以防引用断裂。
>
> Status ∈ {open, blocked, deferred, satisfied}。
> Blocking ∈ {setup_blocker, must_fix_for_s2, should_fix_for_s2, optional_for_s2,
> s3_or_later}。

## 0. Summary

- **Baseline source**: `docs/current/S2_BASELINE_STATUS.md`（S1 complete；targeted
  acceptance/observability green；full-suite red 仅因 TD-006；ruff red 因 TD-007；
  L1-L4 usable but L4 only minimal multistep；L5 all dormant/boundary-clear）。
- **Goal source**: `docs/current/S2_GOAL.md`（S2 = Governed Task Agent；L2/L3/L4
  协同产品化 + L5 至少一个 selectively-active；AC-1..AC-8 + AC-9/10 optional）。
- **Overall gap verdict**: **S2 是真实大版本**。S1 已交付的 same-spine /
  checkpoint / minimal multistep / evidence baseline 是 must-not-regress 起点，
  但 S2 需要把它升级为「能端到端跑通一个真实受控任务、可恢复、可观测、可审计」。
  核心缺口集中在 L4 task orchestration 正式化、L2 task 级 context/state/checkpoint
  协同、L3 governed tool/evidence 合约，以及至少一个 L5 受控激活。质量债（TD-006/
  007）按对 S2 acceptance 信号的影响进入 P2/P3，**不吞掉产品目标**。
- **How to use this file**: §3 是推荐执行顺序（体现依赖）；§4-§8 按优先级列 gap；
  §9 是完整 ID 索引；§10 是 non-goal guardrails 防越界。每个 gap 的 Status 多为
  `open` 或 `blocked`（blocked = 需用户先解决 S2_GOAL §9 open decision）。

## 1. Priority model

| Priority | 含义 | 典型判据 |
|---|---|---|
| **P0 Setup blocker** | 阻塞 S2 开始执行或会误导后续 agent | S2_GOAL §9 open decisions 未解决时会导致核心 P1 gap 无法精确化；缺 reference task 会使 AC-1/AC-7 无法定义具体验收 |
| **P1 Must fix for S2** | S2 核心产品能力（Governed Task Agent 必达） | L4 task orchestration 正式化；L2 task 级 context/state/checkpoint；L3 governed tool/policy/evidence；reference task 端到端闭环；fake/real 覆盖关键 S2 流程 |
| **P2 Should fix for S2** | 硬化项，建议 S2 内完成 | L5 selectively-active 候选选择与受控接入；acceptance gate 债务分类；task-level evidence 深度；guard cleanup 可控子集 |
| **P3 Optional for S2** | 不影响 S2 核心完成 | ruff/quality gate 策略化处理（不全清零） |
| **P4 S3/Sn / Deferred / Tech debt** | 不属于 S2 核心 | 完整 L5 生态化、durable task ledger、legacy facade/dead-code 大清理、TD 全清零 |

> P0 不滥用：大功能放 P1；只有「阻塞开始 / 误导 agent」才放 P0。

## 2. Status distribution

| Status | Count | Gap IDs |
|---|---|---|
| open | 4 | S2-G09, S2-G11, S2-G12, S2-G13 |
| blocked | 0 | — |
| deferred | 0 | — |
| satisfied | 9 | S2-G01, S2-G02, S2-G03, S2-G04, S2-G05, S2-G06, S2-G07, S2-G08, S2-G10 |

## 3. Recommended execution order

按依赖排序（不严格等于优先级；P0 先行解锁 P1 精确化）：

1. **S2-G01** (P0) — satisfied: reference task & blocking open decisions resolved
2. **S2-G02** (P1) — satisfied: governed task state model defined → S2-G03/G04/G06 解锁
3. **S2-G03** (P1) — satisfied: task orchestration skeleton（依赖 S2-G02）
4. **S2-G04** (P1) — satisfied: task context/memory/state/checkpoint 协同（依赖 S2-G02/G03）
5. **S2-G05** (P1) — satisfied: governed tool/policy/evidence 合约
6. **S2-G06** (P1) — satisfied: task progress + human review/takeover（依赖 S2-G02/G03）
7. **S2-G10** (P2) — satisfied: acceptance gate 债务分类 + guard cleanup 子集（支撑 AC-8）
8. **S2-G07** (P1) — satisfied: fake+real S2 E2E acceptance set（real 为 key-safe opt-in；本地默认 skip）
9. **S2-G08** (P2) — satisfied: Skill selected + same-spine integration plan recorded
10. **S2-G09** (P2) — selected L5 controlled integration（依赖 S2-G08；下一个 eligible gap）
11. **S2-G11** (P2) — task-level evidence depth（依赖 OD-5）
12. **S2-G12** (P3) — ruff/quality gate 策略
13. **S2-G13** (P4) — TECH_DEBT triage into S2/S3/Sn

---

## 4. P0 — Setup blockers

### S2-G01 — Select S2 reference task & resolve blocking open decisions
- **Priority**: P0（setup_blocker）
- **Layer**: Cross-cutting
- **Related S2 Goal**: §3 target state; §5 AC-1/AC-7; §9 OD-1/OD-2/OD-3/OD-5/OD-6
- **Baseline evidence**: S1 只有 minimal multistep（legacy Plan），无 S2 级 reference task；S2_GOAL §9 列出 6 个 open decisions 未决，其中 reference task（OD-1）、L5 选择（OD-2）、full-pytest 政策（OD-3）直接阻塞 P1 gap 的精确化。
- **Gap**: 没有 reference task，AC-1（任务闭环）与 AC-7（fake/real 覆盖）无法定义具体验收；没有 L5 选择，S2-G08/G09 无法启动；没有 full-pytest 政策，AC-8 边界模糊。
- **Needed action**: 用户确认 reference task 场景；确认 L5 先激活哪个；确认 full-pytest 全绿 vs targeted gate；确认 real provider 覆盖深度；确认 memory/evidence 深度（OD-5）；确认 AC-9/AC-10 是否纳入。
- **Resolution decisions（2026-06-17，用户确认）**:
  1. Reference task = **Repo-governed improvement task**：FirstAgent 承接真实项目内任务，从读取 S2 gap / docs / code evidence 开始，制定 plan，执行小范围修复或审计，调用工具，保存 checkpoint，resume，记录 evidence，输出结果/commit；不选纯聊天任务或复杂外部业务任务。
  2. L5 selectively-active = **Skill**：Skill 作为受控任务能力包进入 S2；不得绕过 S1 same-spine runtime、policy/evidence，必须可关闭、可回滚、可验收。MCP/SubAgent/Scheduler 不作为首个 S2 必达激活目标。
  3. Full pytest / ruff policy：S2 不要求 full pytest 和 ruff 全绿作为产品目标；S2 release gate 以 targeted S2 acceptance gate 为准；full pytest / ruff 作为 health/debt signal 分类、记录、逐步治理；TD-006 进入 S2 cleanup，但不得吞掉 S2 产品目标。
  4. Real provider coverage：S2 real provider 覆盖 reference task 的 smoke / E2E 主路径，证明 real provider 能进入 governed task path、产生 evidence、与 fake/local 对齐关键事件链路；不要求覆盖所有分支；必须 key-safe。
  5. Memory / context / evidence depth：S2 做 task-level context / memory / state / checkpoint / evidence；task context 清楚，checkpoint/resume 不丢关键 provider-callable content，tool result 可摘要且可恢复，evidence 能支撑人类复盘任务，memory 读写受控；不做长期人格记忆、复杂 self-evolving memory、多 Agent 共享记忆或大型知识库。
  6. AC-9 / AC-10：纳入 S2 acceptance。AC-9 = human review / takeover；AC-10 = quality/debt governance，必须区分 runtime regression、doc governance debt、ruff/full pytest quality debt。
- **Verification**: satisfied — `S2_GOAL.md` §9 decisions 已由用户答复；reference task 已显式命名为 Repo-governed improvement task；首个 L5 已选 Skill。
- **Dependencies**: 无（这是 S2 的起点）。
- **Non-goal boundary**: 不在本 gap 里实现 reference task，只做选择与确认。
- **Suggested execution order**: P0-1（最先）。
- **Status**: satisfied（用户决策已完成）。
- **Risk if ignored**: 已解除；后续 P1/P2 gap 必须按上述决策收敛，不得重新打开 S2 scope。

---

## 5. P1 — Must fix for S2

### S2-G02 — Define governed task state model
- **Priority**: P1（must_fix_for_s2）
- **Layer**: L4
- **Related S2 Goal**: §4-L4; §5 AC-2
- **Baseline evidence**: S1 legacy Plan `state.py TaskState`（`current_plan`/`current_step_index`/`status`），`mark_step_complete` + `STEP_COMPLETION_THRESHOLD`，`advance_current_step_if_needed`；这是 minimal multistep，不是正式 task orchestration 状态机（无显式 failure/resume/done 语义，无 step-level status）。
- **Gap**: S2 需要正式的 task state model：task state / step state / progress / failure / resume / done 语义明确，可被人观测（AC-2）。
- **Needed action**: 定义 governed task state model（task 级 + step 级状态、转移、失败/恢复/done 语义）；不推翻 legacy Plan，在其上形式化或演进。
- **Verification**: 状态机有文档/契约；task/step/progress/failure/resume/done 可被测试断言。
- **Resolution evidence**:
  - Contract: `docs/current/S2_TASK_STATE_MODEL.md`.
  - Code: `agent/task_state_model.py` defines `GovernedTaskLifecycle`, `GovernedStepStatus`, `GovernedTaskProgress`, `GovernedTaskState`, and `build_governed_task_state(...)`.
  - Tests: `tests/test_s2_task_state_model.py` covers running progress, step completion evidence, blocking reason, failure/done terminal semantics, and checkpoint resume projection.
  - Compatibility: no `TaskState` persistent fields added; no independent durable task ledger; legacy Plan/checkpoint path preserved.
- **Dependencies**: 无（是后续 L4/L2 gap 的基础）。
- **Non-goal boundary**: 不要求独立 durable task ledger（S3+，见 S2-G13）。
- **Suggested execution order**: P1-1。
- **Status**: satisfied。
- **Risk if ignored**: S2 无法 claim「正式 task orchestration」；AC-2 无法验收。

### S2-G03 — Implement task orchestration skeleton
- **Priority**: P1（must_fix_for_s2）
- **Layer**: L4
- **Related S2 Goal**: §3 target state; §4-L4; §5 AC-1
- **Baseline evidence**: legacy Plan 路径 active（plan→advance→resume→done，G-12 已验收）；ActionPlan/Scheduler dormant（G-13 out_of_scope for S1）。
- **Gap**: 把 legacy Plan 最小多步升级为正式 task orchestration skeleton：在同一 runtime spine 上承接 receive task → plan → execute steps → advance → done，并可 checkpoint/resume。
- **Needed action**: 在 S2-G02 状态模型上实现 orchestration skeleton；保持 same-spine；进度可 checkpoint 持久化。
- **Verification**: reference task（S2-G01）能走完 plan→execute→checkpoint→resume→done（fake 确定性）。
- **Resolution evidence**:
  - Code: `agent/task_orchestration.py` adds the S2 orchestration skeleton over existing `transitions`, legacy Plan, `CheckpointAction`, and `build_governed_task_state(...)`.
  - Tests: `tests/test_s2_task_orchestration.py` covers receive task → plan confirmation → checkpoint → resume → execute/advance → checkpoint → resume → done.
  - Boundary: orchestration does not generate plans, execute tools, write checkpoints, activate Scheduler/L5, or introduce a second runtime spine; callers still own model/tool/checkpoint side effects.
- **Dependencies**: S2-G02；S2-G01（reference task）。
- **Non-goal boundary**: 不接入 Scheduler（S3+）；不引入第二主链路。
- **Suggested execution order**: P1-2。
- **Status**: satisfied。
- **Risk if ignored**: S2 没有 task 执行骨架，AC-1 无法达成。

### S2-G04 — Task context / memory / state / checkpoint coordination
- **Priority**: P1（must_fix_for_s2）
- **Layer**: L2
- **Related S2 Goal**: §4-L2; §5 AC-3
- **Baseline evidence**: 压缩配对安全（`memory.py:220 compress_history`，G-07）；checkpoint resume 含大结果已验证（G-07b，summary-only rehydrate 为 provider-callable content）；memory recall/retain usable（G-07）；但无 task 级 context 边界，memory 未 task-scoped，`agent/context.py:36` 是不可达 dead code（TD-003）。
- **Gap**: 明确 task context / memory / state / checkpoint / evidence 职责边界；支持任务级上下文构建；resume 后不丢 provider-callable content（固化 G-07b 到任务级）；memory 写入/读取受控（可被 policy/evidence 观测）。
- **Needed action**: 定义 task 级 context 构建路径；固化 resume 不丢 content 契约；为 memory recall/retain/proposal 加 task-scoped + 受控边界。
- **Verification**: reference task resume 后关键上下文与 provider-callable content 完整；memory 操作有 evidence。
- **Resolution evidence**:
  - Code: `agent/task_context.py` adds `TaskContextPackage`, task-scoped `TaskMemoryBoundary`, provider-callable context checks, and safe memory-boundary evidence recording.
  - Tests: `tests/test_s2_task_context.py` covers task context construction, checkpoint resume of summary-only large `tool_result` into provider-callable content, and safe memory boundary evidence.
  - Boundary: no compression rewrite, no memory store rewrite, no TD-003 dead-code deletion, no raw memory/content persisted by the new evidence hook.
- **Dependencies**: S2-G02, S2-G03。
- **Non-goal boundary**: 不重写压缩主路径；不删除 TD-003 dead code（留 S2-G13）。
- **Suggested execution order**: P1-3。
- **Status**: satisfied。
- **Risk if ignored**: AC-3 无法达成；task resume 可能丢上下文。

### S2-G05 — Governed tool execution / policy / evidence contract
- **Priority**: P1（must_fix_for_s2）
- **Layer**: L3
- **Related S2 Goal**: §4-L3; §5 AC-4/AC-5
- **Baseline evidence**: 工具注册+中介执行 usable（`tool_runtime_mediator.py:186`，`tool_executor.py`，`RuntimeActionDispatcher dispatcher.py:309`）；policy gate usable 且两 provider 一致（`ToolGateHandler tool_gate.py:32`，G-08）；tool result 进 context/state usable（G-09）；evidence 是 skeleton-level（G-10）。
- **Gap**: 把「工具调用走 mediator/dispatcher/policy/evidence」固化为 S2 governed contract；tool result 可摘要/可恢复/可审计；evidence 能支撑人类复盘一次任务（工具、决策、失败、恢复，不止骨架）。
- **Needed action**: 明确 governed tool contract（任何旁路视为缺陷）；定义 task-level evidence 要求；处理 tool result 摘要/恢复（与 S2-G04 协同）。
- **Verification**: reference task 的每次工具调用都经 governed path 且有 evidence；人能从 evidence 复盘工具决策与失败。
- **Resolution evidence**:
  - Code: `agent/task_tool_contract.py` adds task-level governed tool report and safe evidence summary over `tool_execution_log` + S2 task context.
  - Tests: `tests/test_s2_task_tool_contract.py` covers executed/blocked/meta tool decisions, bypass-shaped log violations, and safe summary-only tool evidence.
  - Boundary: no direct tool execution, no dispatcher/mediator rewrite, no model request/response full-body persistence; deeper evidence remains S2-G11/TD-001/TD-004 scope.
- **Dependencies**: 与 S2-G04 协同；深度可能触及 TD-001/TD-004（见 S2-G11/OD-5）。
- **Non-goal boundary**: 不要求 evidence 持久化模型 request/response 全正文（除非 OD-5 确认，见 S2-G11）。
- **Suggested execution order**: P1-4。
- **Status**: satisfied。
- **Risk if ignored**: AC-4/AC-5 无法达成；工具调用可能存在旁路。

### S2-G06 — Task progress exposure & human review/takeover seam
- **Priority**: P1（must_fix_for_s2）
- **Layer**: L4
- **Related S2 Goal**: §3 target state; §4-L4; §5 AC-2/AC-9
- **Baseline evidence**: S1 进度 = checkpoint 快照（无独立 durable ledger，S1 non-goal）；无人可见的 progress/blockage seam。
- **Gap**: 人可看到任务进展（progress + 当前 step + 阻塞点）；提供 human review/takeover seam（AC-9，若 OD-6 确认纳入）。
- **Needed action**: 在 S2-G02/G03 之上暴露 task/step progress 与 blockage；定义 takeover seam（最小：人可审计并在阻塞点介入）。
- **Verification**: reference task 执行中 progress 可观测；阻塞点可被人识别。
- **Resolution evidence**:
  - Code: `agent/task_review.py` adds `TaskProgressReview`, human-visible review text, structured `HumanTakeoverDecision`, and safe progress-review evidence.
  - Tests: `tests/test_s2_task_review.py` covers progress/current-step/blocking visibility, side-effect-free continue/stop/takeover parsing, and safe progress evidence.
  - Boundary: no full UI, no direct task mutation, no checkpoint write, no automatic stop/continue execution; callers remain in control.
- **Dependencies**: S2-G02, S2-G03。
- **Non-goal boundary**: 不做完整 human-in-the-loop UI（可选范围由 OD-6 决定）。
- **Suggested execution order**: P1-5。
- **Status**: satisfied。
- **Risk if ignored**: AC-2/AC-9 无法达成；任务成为黑盒。

### S2-G07 — fake + real S2 E2E acceptance
- **Priority**: P1（must_fix_for_s2）
- **Layer**: L1
- **Related S2 Goal**: §4-L1; §5 AC-1/AC-7
- **Baseline evidence**: S1 acceptance gate green（golden_e2e 15 + smoke 6 + wiring 1）；real smoke opt-in key-safe（G-03 3 passed）；但无 S2 reference-task E2E。
- **Gap**: 建立 S2 reference task 的 E2E acceptance：fake 模式确定性走完任务闭环；real provider 在 key-safe opt-in 下覆盖 reference task 关键路径。
- **Needed action**: 定义 S2 acceptance 集（fake/local 确定性 gate + real key-safe smoke 覆盖）；不把 TD-006 的红混进 runtime 验收信号（与 S2-G10 协同）。
- **Verification**: fake reference-task E2E 确定性通过；real key-smoke 覆盖关键路径；不读取/打印/移动/提交 secret。
- **Resolution evidence**:
  - Code/tests: `tests/test_s2_reference_task_acceptance.py` adds the targeted S2 reference-task acceptance gate.
  - Fake/local E2E: covers governed task receive/plan-confirmation, task context, tool contract summary, progress review, safe evidence hooks, checkpoint save/load/resume, step advance, done projection, and S2 acceptance-gate classification.
  - Real provider: adds `test_s2_reference_task_real_provider_key_safe_context_smoke`, guarded by `MY_FIRST_AGENT_RUN_S2_REAL_PROVIDER_SMOKE=1`; it validates provider-callable S2 task context and then calls the configured real provider only under explicit opt-in.
  - Runbook: `docs/current/S2_REFERENCE_TASK_ACCEPTANCE.md` documents targeted gate, real opt-in command, default skip behavior, and secret/config boundaries.
  - Local verification: `.venv/bin/python -m pytest tests/test_s2_reference_task_acceptance.py -q` -> 1 passed, 1 skipped（real provider 未 opt-in，因此未执行真实 provider 调用）。
- **Dependencies**: S2-G02..S2-G06（reference task 已由 S2-G01 决策为 Repo-governed improvement task）；S2-G10（acceptance gate 分类）。
- **Non-goal boundary**: 不把 full pytest 全绿作为 S2 产品目标（见 S2-G10/G12）。
- **Suggested execution order**: P1-6（S2 验收锚点，最后）。
- **Status**: satisfied。
- **Risk if ignored**: S2 无法判定「完成」；AC-1/AC-7 无验收命令。

---

## 6. P2 — Should fix for S2

### S2-G08 — Selectively-active L5 candidate selection
- **Priority**: P2（should_fix_for_s2）
- **Layer**: L5
- **Related S2 Goal**: §4-L5; §5 AC-6; §9 OD-2
- **Baseline evidence**: 全部 L5 dormant/boundary-clear（G-13/G-14）。graphify 核验：**SubAgent L1 parent-mediated 路径 wiring 最齐**（`delegate_l1`/`execute_l1`/`build_context_package`/`SubAgentRegistry` + `test_subagent_l1_parent_mediated.py` 大量 test）；MCP configurable default-off（`MY_FIRST_AGENT_MCP_ENABLE`）；Skill experimental；Scheduler dormant（main.py 0 refs）。S2-G01 用户决策已选择 **Skill** 作为首个 S2 selectively-active L5。
- **Gap**: 选择**一个** L5 能力进入受控激活；选定后才能做 S2-G09 集成。
- **Needed action**: 在 Skill 已被选定的前提下，补齐 Skill same-spine / policy / evidence / disable boundary 的接入理由与集成计划；未选 MCP/SubAgent/Scheduler 保持 dormant/boundary-clear。
- **Verification**: Skill 有书面理由 + 集成计划；未选项保持 dormant/boundary-clear。
- **Resolution evidence**:
  - Decision/runbook: `docs/current/S2_L5_SKILL_SELECTION.md` records Skill as the selected L5 candidate and defines the same-spine integration plan for S2-G09.
  - Skill evidence: registry/selector are metadata-only (`agent/skill_system/registry.py`, `agent/skill_system/selector.py`); lifecycle/task-boundary/checkpoint seams exist (`agent/skill_system/lifecycle.py`, `agent/skill_system/task_boundary.py`, `agent/runtime_integration/skill_lifecycle.py`); `SKILL_SELECT` is a model-visible tool entry (`agent/skill_system/skill_tool.py`) to be governed in S2-G09.
  - Deferred candidates: MCP/SubAgent/Scheduler are explicitly not selected for the first S2 L5 activation; Scheduler remains dormant, MCP/SubAgent remain later candidates.
- **Dependencies**: S2-G01 satisfied（OD-2 已解决）。
- **Non-goal boundary**: 不全量激活所有 L5；不选超过一个进入 S2 受控激活。
- **Suggested execution order**: P2-1。
- **Status**: satisfied。
- **Risk if ignored**: AC-6 无法达成；S2 缺少 L5 维度。

### S2-G09 — Selected L5 controlled integration
- **Priority**: P2（should_fix_for_s2）
- **Layer**: L5
- **Related S2 Goal**: §4-L5; §5 AC-6
- **Baseline evidence**: 见 S2-G08；所选 L5 当前为 dormant/configurable-default-off。
- **Gap**: 把选定的 L5 能力受控接入主链路：经 dispatcher/mediator（不绕 same-spine）、经 policy/evidence、可禁用/可回滚/可验收；default-off，不激活时行为与 S1 一致。
- **Needed action**: 实现 governed 接入；加 policy gate + evidence；加 disable 开关与回滚路径；写验收测试。
- **Verification**: 激活路径走 same-spine 且有 evidence；disable 后行为与 S1 一致；child/MCP/skill 不绕过主 runtime。
- **Dependencies**: S2-G08（选定项）；S2-G05（governed contract）。
- **Non-goal boundary**: 不做 S3 级生态化；所选 L5 只做受控最小接入。
- **Suggested execution order**: P2-2。
- **Status**: open（S2-G08 已完成；Skill 为选定 L5，S2-G09 可开始受控集成）。
- **Risk if ignored**: AC-6 无法达成；L5 接入可能绕过 policy/evidence。

### S2-G10 — S2 acceptance gate debt classification & guard cleanup subset
- **Priority**: P2（should_fix_for_s2）
- **Layer**: L1 / Cross-cutting
- **Related S2 Goal**: §4-L1; §5 AC-8; §8
- **Baseline evidence**: full-suite red（36 failed, 4747 passed, 13 skipped, 26 xfailed），全部失败是 TD-006 guard/governance 类（`test_docs_source_of_truth.py` 23、`test_v6_drift_addendum_boundary.py` 5、`test_architecture_boundaries.py` 3、taxonomy/diagnostics/contract guards）；当前 S2 acceptance gate 无法把「runtime regression」与「doc governance debt / quality debt」分开。
- **Gap**: 让 S2 acceptance gate 能明确分类 runtime regression / doc governance debt / quality debt（AC-8）；清理 TD-006 中**阻塞 acceptance 信号**的可控子集（不是全量清零）。
- **Needed action**: 定义 acceptance gate 分类口径；清理阻塞信号的 guard 子集，每个 guard 对齐当前 governance docs/contracts（不静默弱化断言）。
- **Verification**: S2 acceptance gate 能输出 runtime-only 信号；被清理的 guard 对齐当前 docs。
- **Resolution evidence**:
  - Contract: `docs/current/S2_ACCEPTANCE_GATE.md`.
  - Code: `agent/acceptance_gate.py` classifies `passed`, `runtime_regression`, `doc_governance_debt`, `quality_debt`, and `unknown_failure`.
  - Tests: `tests/test_s2_acceptance_gate.py` verifies targeted S2 runtime failure is release-blocking, TD-006 guard failures are doc-governance debt, ruff is TD-007 quality debt, and unknown failures remain release-blocking.
  - Boundary: TD-006/TD-007 remain open debt; S2-G10 only separates acceptance signal from health/debt signal.
- **Dependencies**: 无（可与 P1 并行，支撑 S2-G07）。
- **Non-goal boundary**: 不追求 TD-006 全清零作为产品目标；不做大规模 ruff 修复（见 S2-G12）。
- **Suggested execution order**: P2-3（可与 P1 后期并行）。
- **Status**: satisfied。
- **Risk if ignored**: AC-8 无法达成；S2 验收信号被 guard 噪音污染。

### S2-G11 — Task-level evidence depth
- **Priority**: P2（should_fix_for_s2）
- **Layer**: L3
- **Related S2 Goal**: §5 AC-5; §9 OD-5; §8
- **Baseline evidence**: evidence skeleton-level（G-10）；TD-001（无模型 request/response 全正文）、TD-004（pending-tool tool_output 预览可能为空）open。
- **Gap**: 根据 OD-5 决定「任务级 evidence」深度：是否需要触及 TD-001（正文保真）和 TD-004（pending-tool 预览）以支撑人类复盘。
- **Needed action**: OD-5 确认后，按需推进 evidence 深度；若 OD-5 要求复盘级别，则处理 TD-001/TD-004 相关部分。
- **Verification**: reference task evidence 能支撑人类复盘（工具、决策、失败、恢复）。
- **Dependencies**: S2-G01 satisfied（OD-5 已解决）；与 S2-G05 协同。
- **Non-goal boundary**: 不强制全正文保真（除非 OD-5 确认）；未触及的 TD 部分留 S2-G13。
- **Suggested execution order**: P2-4。
- **Status**: open（OD-5 已由 S2-G01 解决；需按 task-level evidence 深度实现）。
- **Risk if ignored**: AC-5 深度不明；可能复盘能力不足或过度投资。

---

## 7. P3 — Optional for S2

### S2-G12 — Quality gate / ruff strategy
- **Priority**: P3（optional_for_s2）
- **Layer**: Cross-cutting
- **Related S2 Goal**: §8
- **Baseline evidence**: TD-007（`ruff check .` red，~451 historical errors，独立于 TD-006）。
- **Gap**: 对 ruff/quality gate 做策略化处理（例如：新代码必须 clean、存量分批、不追求一次性全清零）。
- **Needed action**: 制定 lint 策略；可选分批修复；不与 TD-006 混淆。
- **Verification**: lint 策略成文；新代码 ruff clean。
- **Dependencies**: 无。
- **Non-goal boundary**: 不把 ruff 全清零作为 S2 产品目标。
- **Suggested execution order**: P3-1（随时可做，不阻塞 S2）。
- **Status**: open。
- **Risk if ignored**: lint 健康长期红；不影响 S2 核心能力。

---

## 8. P4 — S3/Sn / Deferred / Tech debt

### S2-G13 — TECH_DEBT triage into S2/S3/Sn
- **Priority**: P4（s3_or_later）
- **Layer**: Cross-cutting
- **Related S2 Goal**: §6 non-goals; §8
- **Baseline evidence**: TD-002（planning/compress legacy `ProviderBackedClient` facade）、TD-003（`agent/context.py` dead code）open；durable task ledger 与完整 L5 生态属 S3+。
- **Gap**: 把剩余 TECH_DEBT 按阶段归位：TD-002/TD-003 的 S2/Sn cleanup 判定；durable task ledger、完整 MCP/Skill/SubAgent/Scheduler 生态化明确留 S3+。
- **Needed action**: 在 S2 推进中持续 triage；把确认 out-of-S2 的债显式标记 deferred。
- **Verification**: 每项债务有阶段归属（S2 cleanup / S3+）；`TECH_DEBT.md` 与本文件一致。
- **Dependencies**: 随 S2 推进更新。
- **Non-goal boundary**: 不在 S2 做大规模清理/重构/生态化。
- **Suggested execution order**: P4-1（贯穿 S2，按需 triage）。
- **Status**: open（持续性 triage）。
- **Risk if ignored**: 债务归属模糊，误导后续 agent。

---

## 9. Original ID index

| ID | Title | Priority | Status | Layer | Related AC |
|---|---|---|---|---|---|
| S2-G01 | Select reference task & resolve blocking open decisions | P0 | satisfied | Cross-cutting | AC-1/7 setup |
| S2-G02 | Define governed task state model | P1 | satisfied | L4 | AC-2 |
| S2-G03 | Implement task orchestration skeleton | P1 | satisfied | L4 | AC-1 |
| S2-G04 | Task context/memory/state/checkpoint coordination | P1 | satisfied | L2 | AC-3 |
| S2-G05 | Governed tool/policy/evidence contract | P1 | satisfied | L3 | AC-4/5 |
| S2-G06 | Task progress & human review/takeover seam | P1 | satisfied | L4 | AC-2/9 |
| S2-G07 | fake + real S2 E2E acceptance | P1 | satisfied | L1 | AC-1/7 |
| S2-G08 | Selectively-active L5 candidate selection | P2 | satisfied | L5 | AC-6 |
| S2-G09 | Selected L5 controlled integration | P2 | open | L5 | AC-6 |
| S2-G10 | Acceptance gate debt classification & guard cleanup subset | P2 | satisfied | L1/Cross | AC-8 |
| S2-G11 | Task-level evidence depth | P2 | open | L3 | AC-5 |
| S2-G12 | Quality gate / ruff strategy | P3 | open | Cross-cutting | §8 |
| S2-G13 | TECH_DEBT triage into S2/S3/Sn | P4 | open | Cross-cutting | §6/§8 |

## 10. Non-goal guardrails

S2 **不做**（防止 agent 越界）：

- 不重写 runtime spine；不引入第二主链路（same-spine 是 must-not-regress）。
- 不做 S3 multi-agent ecosystem；不全量激活所有 L5（只一个受控接入）。
- 不把所有 TECH_DEBT 强行变 S2 必修（TD 按对 S2 acceptance 的影响进入 P2/P3/P4）。
- 不追求全量 ruff/pytest 清零作为产品目标（S2-G10 只清阻塞信号子集；S2-G12 是策略）。
- 不绕过 policy/evidence；任何工具/L5 旁路视为缺陷。
- 不泄露 secret：real provider 仅 key-safe opt-in；不读取/打印/移动/提交 secret；不修改 ignored `config/config.yaml`；不创建 `.env`。
- 不做独立 durable task ledger（S3+）。
- 不删未完成 gap；完成需证据。

## 11. Next step

- S2-G01..S2-G06 and S2-G10 已完成；继续 **S2 gap loop** 时按 §3 执行顺序回到 S2-G07。
- 每个 gap 仍需一轮 focused mini-run、验证、更新本文件与 `WORK_LOG.md`，并按治理规则提交。
