# S3 Goal Gap / Release Backlog — Extensible Governed Agent Runtime

> Current document (`docs/current/`). S3 gap backlog，由 `S3_BASELINE_STATUS.md`
> （现状）vs 已冻结的 `S3_GOAL.md`（目标）生成。本文是 **backlog**，不是施工结果。
> 本任务**只生成 gap，不修 gap、不进入 gap loop**。
>
> 规则（见 `AGENTS.md` goal rules）：不删未完成 gap；完成需证据（commit/test/log/
> trace/audit/source ref）；不把 `S3_GOAL.md` 未承诺的能力强行变成 gap；不把所有
> `TECH_DEBT` 塞成 S3 必修。保留 Gap ID 以防引用断裂。
>
> Status ∈ {open, blocked, deferred, satisfied}。
> Priority ∈ {P0 setup/release blocker, P1 must_fix_for_s3, P2 should_fix_for_s3,
> P3 optional_for_s3, P4 s4_or_later/deferred}。

## 0. Summary

- **Baseline source**: `docs/current/S3_BASELINE_STATUS.md`（S2 completed/archived；
  governed task path + Skill governed-active 可用；MCP plumbing 丰富但 runtime
  orchestrator HARNESS-ONLY、default-off；SubAgent parent-mediated/side-effect-free
  但未激活；Scheduler 已实现未激活；full-suite 因 TD-006 红、ruff 因 TD-007 红）。
- **Goal source**: 已冻结 `docs/current/S3_GOAL.md`（S3 = Extensible Governed Agent
  Runtime；必达 = MCP governed tool source + SubAgent read-only/audit-first
  parent-mediated；Skill 维持 contract 参考；Scheduler defer；reference task =
  Extension-assisted repo governance task；TD-006 进 release gate；TD-007 非 blocker；
  AC-1..AC-9）。
- **Overall gap verdict**: **S3 是 L5 extension boundary maturation 版本，不是新 runtime
  也不是 cleanup。** 核心缺口集中在：(a) 把 Skill 的受控激活模式抽象为**统一 extension
  capability contract**；(b) 把已有 MCP plumbing 从 HARNESS-ONLY/default-off 接成**生产
  governed tool source**；(c) 把成熟的 SubAgent parent-mediated 结构推进到**受控
  read-only/audit-first 激活**；(d) 让 extension 的 evidence/checkpoint/task-state 与
  S2 spine 对齐；(e) 一个组合 MCP+SubAgent 的 **Extension-assisted repo governance**
  E2E reference task + real provider key-path smoke。质量债中**只有 TD-006** 因进入
  release gate 而成为 S3 P2 gap；TD-007 与其余 TD 不进 S3 核心。
- **How to use this file**: §3 是推荐执行顺序（体现依赖）；§4-§8 按优先级列 gap；
  §9 是完整 ID 索引；§10 是 non-goal guardrails 防越界；§11 是 next step。所有 gap 当前
  Status 为 `open`（或 P4 `deferred`），因为本任务只生成不执行。

## 1. Priority model

| Priority | 含义 | 典型判据 |
|---|---|---|
| **P0 Setup/release blocker** | 阻塞 S3 gap loop 或 release 判断的前置问题 | reference task 未落地为可执行口径，会使 AC-5/AC-6 无法精确验收 |
| **P1 Must fix for S3** | S3 必达产品能力（Extensible Governed Agent Runtime 必达） | unified extension contract；MCP governed tool source；SubAgent read-only/audit parent-mediated；extension evidence/checkpoint/task-state；reference task E2E；real provider key path |
| **P2 Should fix for S3** | 硬化/治理项，建议 S3 内完成 | acceptance gate extension-regression 分类；TD-006 release-gate 清理；docs/current+history governance；Skill non-regress guard |
| **P3 Optional for S3** | 不影响 S3 核心完成 | 额外 extension metadata / reports / provider checks |
| **P4 S4/Sn / Deferred** | 不属于 S3 核心 | Scheduler 生产化、完整 MCP 生态、完整 multi-agent 生态、durable task ledger、TD-007 全量 ruff、TD-002/003 cleanup |

> P0 不滥用：大功能放 P1；只有「阻塞开始 / 误导 agent」才放 P0。

## 2. Status distribution

| Status | Count | Gap IDs |
|---|---|---|
| open | 3 | S3-G09, S3-G11, S3-G12 |
| blocked | 0 | —（S3 open decisions 已在冻结 goal 中全部 resolved） |
| deferred | 1 | S3-G13 |
| satisfied | 9 | G01-G08；S3-G10（docs/current+history governance） |

## 3. Recommended execution order

按依赖排序（不严格等于优先级；P0 先行解锁 P1 精确化）：

1. **S3-G01** (P0) — define S3 reference task precisely（解锁 G06/G07 精确验收）
2. **S3-G02** (P1) — unified extension capability contract（解锁 G03/G04 统一接入）
3. **S3-G03** (P1) — MCP governed tool source（依赖 G02 契约）
4. **S3-G04** (P1) — SubAgent read-only/audit-first parent-mediated（依赖 G02 契约）
5. **S3-G05** (P1) — extension evidence/checkpoint/task-state integration（依赖 G03/G04）
6. **S3-G06** (P1) — extension-assisted repo governance E2E reference task（依赖 G01/G03/G04/G05）
7. **S3-G07** (P1) — real provider S3 governed extension key-path smoke（依赖 G06）
8. **S3-G08** (P2) — acceptance gate extension-regression classification（支撑 AC-7，可与 G06 并行）
9. **S3-G09** (P2) — TD-006 release-gate cleanup（release 前 hygiene，可与 P1 后期并行）
10. **S3-G10** (P2) — docs/current+history governance for S3（贯穿，close-out 前必查）
11. **S3-G11** (P2) — Skill contract remains governed-active & non-regressed（贯穿 regression guard）
12. **S3-G12** (P3) — optional extension hardening（随时可做，不阻塞）
13. **S3-G13** (P4) — deferred to S4/Sn + TECH_DEBT triage（贯穿登记，不执行）

---

## 4. P0 — Setup / release blockers

### S3-G01 — Define S3 reference task precisely
- **Priority**: P0（setup_blocker）
- **Layer**: Cross-cutting (L4-anchored)
- **Related S3 Goal**: §0 reference task; §6 AC-5/AC-6; §8 Resolved decision 4
- **Baseline evidence**: 冻结 goal 已命名 reference task = **Extension-assisted repo
  governance task**，但仅有概念口径，无可执行规格（具体 repo-governance 场景、用哪些
  MCP tool source、调用哪个 read-only SubAgent 做 second opinion、主 Agent 汇总/产出
  形态、成功判据）。S2 的 `tests/test_s2_reference_task_acceptance.py` 是可参照模板。
- **Gap**: 没有可执行 reference task 规格，AC-5（闭环）与 AC-6（real key path）无法定义
  具体验收命令与断言。
- **Needed action**: 把 reference task 落地为可执行规格：输入（一个真实 repo governance
  / code-review / gap-audit 子任务）、受控 MCP tool source 的角色、read-only SubAgent
  second-opinion 的角色、主 Agent 汇总 evidence/决策/产出、fake 确定性成功判据；记录为
  runbook（不在本 gap 实现）。
- **Verification**: reference task runbook 成文且 AC-5/AC-6 可据此写出具体验收。
- **Dependencies**: 无（S3 起点）。
- **Non-goal boundary**: 不在本 gap 实现 reference task，只定义；不扩成多任务套件。
- **Suggested execution order**: P0-1（最先）。
- **Status**: satisfied（2026-06-19）。
- **Evidence**: `docs/current/S3_REFERENCE_TASK.md`（Extension-assisted repo governance
  精确规格/runbook 成文：场景、inputs、MCP/SubAgent 角色、closed loop 映射 S2 skeleton、
  fake 确定性判据 §5、real key-path §6、non-goals §7）；AC-5/AC-6 可据此写出具体验收命令
  与断言（G06/G07 落地）。Commit 见 WORK_LOG / `git log`（S3-G01）。
- **Risk if ignored**: P1 的 G06/G07 无法精确化；AC-5/AC-6 沦为口号。

---

## 5. P1 — Must fix for S3

### S3-G02 — Unified extension capability contract
- **Priority**: P1（must_fix_for_s3）
- **Layer**: L5 / Cross-cutting
- **Related S3 Goal**: §4 scope-1/2; §5 L5; §6 AC-4
- **Baseline evidence**: 目前只有 Skill 有自己的受控激活闸门（`agent/skill_system/gate.py`
  = default-off `MY_FIRST_AGENT_S2_SKILL_ENABLE`，discovery/activation/execution 分层）。
  MCP 有独立 `mcp_policy.py`/`mcp_config*`，SubAgent 有 `SubAgentPolicyError`/
  `adjudicate_result`，但三者**没有共享的 capability 契约**（metadata/enable-disable/
  risk/verification/evidence 的统一形状）。
- **Gap**: 抽象出统一 extension capability contract，让 MCP/SubAgent（以及参考的 Skill）
  以同一形状声明 metadata、enable/disable、risk、verification、evidence；这是 G03/G04
  统一接入的前置。
- **Needed action**: 定义 extension capability 契约（数据形状 + 接入约定），以 Skill
  governed-active 为参考模型；不重写 Skill，不改 runtime spine。
- **Verification**: 契约成文且有最小测试断言 metadata/enable-disable/risk/verification/
  evidence 字段；MCP/SubAgent 能按契约声明。
- **Dependencies**: 无（但解锁 G03/G04）。
- **Non-goal boundary**: 不做插件市场 / 动态生态；不引入第二条主链路。
- **Suggested execution order**: P1-1。
- **Status**: satisfied（2026-06-19）。
- **Evidence**: `agent/extension_capability.py`（统一契约：`ExtensionCapability` /
  `ExtensionRisk` / `ExtensionVerification` / `ExtensionEvidenceDescriptor` /
  `ExtensionActivationDecision` + `evaluate_activation`；五要素 metadata/enable-disable/
  risk/verification/evidence 齐全；default-off + 显式 opt-in，与 Skill gate 同语义）；
  `tests/test_extension_capability_contract.py` 7 passed（断言五要素字段 + MCP/SubAgent/
  Skill 三种 capability 可按契约声明 + frozen 不变）。Commit 见 WORK_LOG / `git log`（S3-G02）。
- **Risk if ignored**: MCP/SubAgent 各自另起接入形状，违反 same-spine 治理一致性。

### S3-G03 — MCP governed tool source (default-off / allowlist / policy / evidence)
- **Priority**: P1（must_fix_for_s3）
- **Layer**: L5 / L3
- **Related S3 Goal**: §4 scope-3 MCP; §5 L5-MCP; §6 AC-2
- **Baseline evidence**: MCP plumbing 已相当完整 —— core `agent/mcp.py`/`mcp_bridge.py`/
  `mcp_models.py`，governance `mcp_policy.py`/`mcp_audit.py`/`mcp_sanitizer.py`，config
  `mcp_config*.py`，transport `mcp_stdio.py`，`mcp_external_readiness.py`。但
  `agent/runtime_integration/mcp_tool_orchestrator.py` 经 graphify 标注为 **HARNESS-ONLY**，
  `mcp_bridge_lifecycle.py` 为 lifecycle seam，整体 configurable default-off
  （`MY_FIRST_AGENT_MCP_ENABLE`）。即 MCP 工具**尚未进入生产 governed tool path**。
- **Gap**: 把 MCP 接成**受控 governed tool source**：MCP 暴露的工具经 dispatcher/mediator
  进入同一 governed tool path，受 policy gate + evidence；default-off + allowlist；
  关闭时行为同 S2。复用现有 `mcp_policy.py`/`mcp_audit.py`/`mcp_sanitizer.py`。
- **Needed action**: 把 MCP tool source 接到 governed tool path（非 harness-only）；
  加 default-off/allowlist 闸门；MCP tool 调用经 policy/evidence；fake-first/local-only/
  fixture-based（不连真实 MCP endpoint）。
- **Verification**: fake/fixture MCP tool source 经 governed path 调用并产生 evidence；
  default-off 时不暴露；allowlist 外的 MCP tool 被拒；无 real endpoint 连接。
- **Dependencies**: S3-G02（契约）。
- **Non-goal boundary**: **不做完整 MCP 生态**（多 server 编排/动态发现生态化留 S4/Sn）；
  **不连接真实 MCP endpoint / 不做 server reachability check**（`AGENTS.md` 安全边界）；
  不让 MCP 绕过 policy/evidence。
- **Suggested execution order**: P1-2。
- **Status**: satisfied（2026-06-19）。
- **Evidence**: `agent/mcp_capability.py`（MCP 经 G02 统一契约声明 `MCP_CAPABILITY`：
  kind=mcp / default-off / enable_env=`MY_FIRST_AGENT_MCP_ENABLE` / risk=high + 缓解 /
  verification / evidence subsystem=mcp）；`main.py:_init_mcp_bridge_if_enabled` 的
  default-off gate 对齐到 `evaluate_activation(MCP_CAPABILITY)`（行为保持，opt-in 值一致）；
  `tests/test_s3_mcp_governed_tool_source.py` 5 passed（capability 声明 + allowlisted fake
  tool 经 governed policy 注册进同一 TOOL_REGISTRY 并产生 mcp evidence + default-off 不暴露
  + allowlist 外被拒 + blocked evidence + dry_run 用 FakeMCPClient 无真实 endpoint）。代码事实
  复核（graphify + Explore）：MCP 执行期已走统一 mediator 路径（非 harness-only、不绕过
  dispatcher）；调用期 evidence 已由 `test_mcp_real_external_flight.py::TestMCPInvocationMainPath`
  证明。Commit 见 WORK_LOG / `git log`（S3-G03）。
- **Risk if ignored**: AC-2 无法达成；S3 缺少 extension tool source 维度。

### S3-G04 — SubAgent read-only / audit-first parent-mediated governed path
- **Priority**: P1（must_fix_for_s3）
- **Layer**: L5 / L3
- **Related S3 Goal**: §4 scope-3 SubAgent; §5 L5-SubAgent; §6 AC-3
- **Baseline evidence**: SubAgent 结构成熟且 parent-mediated：
  `agent/subagent_system/delegation.py`（`delegate_l1` L173、`delegate_once` L19）、
  `executor.py`（`execute_l1` L131）、`context.py`（`build_context_package` L40）、
  `result.py`（`SubAgentAuditRecord` L41、`ParentAdjudicationResult` L79）、
  `adjudication.py`（`adjudicate_result`）、`errors.py`（`SubAgentPolicyError`）。
  rationale：「delegation 只是结构化请求/结果；parent policy 决定能否使用」。public API
  被 `tests/test_architecture_boundaries.py` 断言为 explicit + side-effect-free。当前
  **未进入受控激活**。
- **Gap**: 把 SubAgent 推进到 governed-active 的 **read-only / audit-first /
  parent-mediated** 委派：用于 reference task 的 second opinion / audit；**不绕过主 Agent
  执行 tool/provider/memory**；委派经 policy/evidence、可禁用、关闭时行为同 S2。
- **Needed action**: 在现有 delegate_l1/execute_l1/adjudication 上接出受控 read-only
  委派路径；强制 parent-mediated（child 不直接持 tool/provider/memory 旁路）；按 G02
  契约声明 capability；加 evidence/audit。
- **Verification**: SubAgent read-only 委派经 parent policy/evidence；child 无法绕过主
  Agent 执行 tool/provider/memory；default-off 可禁用；audit record 可复盘。
- **Dependencies**: S3-G02（契约）。
- **Non-goal boundary**: **不做可写 / 非 mediated 委派**；不做完整 multi-agent 生态
  （留 S4/Sn）；child 不另起 agent 主链路。
- **Suggested execution order**: P1-3。
- **Status**: satisfied（2026-06-20）。
- **Evidence**: `agent/subagent_capability.py`（SubAgent 经 G02 统一契约声明 `SUBAGENT_CAPABILITY`：
  kind=subagent / default-off / enable_env=`MY_FIRST_AGENT_S3_SUBAGENT_ENABLE` / risk=medium +
  缓解 / verification / evidence subsystem=task）；`agent/subagent_system/gate.py`（新增
  default-off env gate `is_subagent_enabled`，与 Skill/MCP gate 同语义）；`agent/subagent_system/
  policy.py:select_execution_mode` 对 governed-active 模式（real_llm_readonly 等）追加 S3 env
  gate（config gate 之上，local 模式不门控=fake-first）；`tests/test_s3_subagent_parent_mediated_acceptance.py`
  6 passed（capability 声明 + default-off gate 阻 governed-active 模式 + local 不门控 + child 不绕过
  parent[forbidden_actions] + SubAgentAuditRecord 可复盘 + parent adjudicate）。代码事实复核
  （graphify + Explore）：parent-mediated read-only 架构已完全建成且由 16 个 L1 test class 证明
  （child 工具/内存经 tool_mediator，不直接持 MemoryStore）；不绕过边界（tool/memory/skill_boundary
  仅 snapshot）。Commit 见 WORK_LOG / `git log`（S3-G04）。
- **Risk if ignored**: AC-3 无法达成；SubAgent 若可写/绕过会破坏 governance。

### S3-G05 — Extension evidence / checkpoint / task-state integration
- **Priority**: P1（must_fix_for_s3）
- **Layer**: L2 / L3
- **Related S3 Goal**: §5 L2/L3; §6 AC-1/AC-4
- **Baseline evidence**: S2 已有 `agent/task_evidence_report.py`（结构化 replay metadata，
  非逐字；TD-001/TD-004 surfaced）、`task_context.py`（resume 不丢 provider-callable
  content）、`task_state_model.py` + checkpoint path。但这些尚未覆盖 **extension 产生的
  中间结果**（MCP tool 结果、SubAgent second-opinion 输出）。
- **Gap**: 让 MCP/SubAgent 在任务中产生的结果纳入既有 evidence/checkpoint/task-state
  边界：可记录、可恢复、resume 不丢；SubAgent 为 parent-mediated 不持独立 memory 旁路。
- **Needed action**: 把 extension 结果接入 task evidence/checkpoint/task-state（沿用 S2
  结构化 evidence 形状）；resume 后 extension 上下文不丢。
- **Verification**: 含 extension 的任务 checkpoint→resume 后 extension evidence/上下文
  完整；evidence 能复盘 extension 决策。
- **Dependencies**: S3-G03、S3-G04。
- **Non-goal boundary**: 不要求逐字保真（TD-001）/ pending-tool 全量预览（TD-004）——
  超出 S3 evidence 深度的部分仍 deferred（见 S3-G13）；不重写 checkpoint 主路径。
- **Suggested execution order**: P1-4。
- **Status**: satisfied（2026-06-20）。
- **Evidence**: `agent/state.py:TaskState.delegation_log`（新字段，存 SubAgent 委派安全投影；
  经 checkpoint `_copy_state_dict`/`_filter_to_declared_fields` 自动持久化/恢复，**未重写
  checkpoint 主路径**）；`agent/task_delegation_evidence.py:record_delegation_run`（把
  SubAgentRun 的 audit/adjudication 安全投影写入 delegation_log，JSON-safe、非逐字=TD-001
  deferred）；`agent/task_evidence_report.py:_evidence_events` 呈现 `extensions.delegations:N`
  （可复盘 extension 决策）；`tests/test_s3_extension_evidence_checkpoint.py` 2 passed（MCP 结果
  经共享 tool 路径进 tool_execution_log + SubAgent 委派进 delegation_log，checkpoint→resume
  双双保真 + evidence report 呈现 extension 计数 + 默认空向后兼容）。代码事实复核（graphify +
  Explore）：MCP 结果已通过共享 execute_single_tool 路径进 tool_execution_log 并跨 resume 保真
  （零改动）；SubAgent audit 原为瞬态，本 gap 补 task-state seam。runtime 消费点
  （execute_subagent_delegation 不接收 state）的 state 穿透由 G06 E2E 在真实循环调用本 seam
  完成（不在本 gap 改 core.py）。Commit 见 WORK_LOG / `git log`（S3-G05）。
- **Risk if ignored**: AC-1/AC-4 无法达成；extension 任务不可恢复/不可审计。

### S3-G06 — Extension-assisted repo governance E2E reference task (fake/local)
- **Priority**: P1（must_fix_for_s3）
- **Layer**: L4
- **Related S3 Goal**: §0 reference task; §6 AC-5 (+ AC-1 S2 must-not-regress)
- **Baseline evidence**: S2 `tests/test_s2_reference_task_acceptance.py` 提供 governed
  task E2E 模板（fake 确定性 + real opt-in skip），但**不使用 extension**。
- **Gap**: 建立 S3 reference task 的 E2E：在 governed task path 内**组合 MCP tool source
  + read-only SubAgent** 完成 Extension-assisted repo governance task 的
  plan→execute→checkpoint→resume→done 闭环（fake 确定性）。
- **Needed action**: 按 S3-G01 规格实现 fake/local E2E acceptance；组合 G03/G04/G05；
  作为 S3 targeted gate 的核心锚点；并把 S2 targeted gate 纳入 S3 acceptance set，作为
  **S2 governed task path must-not-regress** 检查（AC-1）。
- **Verification**: fake reference-task E2E 确定性通过，且确实经 MCP+SubAgent governed
  path；checkpoint/resume 不丢 extension 上下文；S2 targeted gate（reference / skill /
  acceptance）仍通过，证明 S2 governed task path 不回归（AC-1）。
- **Dependencies**: S3-G01、S3-G03、S3-G04、S3-G05。
- **Non-goal boundary**: 不把 full pytest 全绿当 S3 产品目标（见 §10）；不连真实 endpoint。
- **Suggested execution order**: P1-5（S3 验收锚点）。
- **Status**: satisfied（2026-06-20）。
- **Evidence**: `tests/test_s3_reference_task_acceptance.py::test_s3_reference_task_fake_e2e_extension_closed_loop`
  1 passed —— Extension-assisted repo governance 闭环（fake/local）：受控 MCP tool source（G03，注册进
  同一 TOOL_REGISTRY）读 fixture 证据 → tool_execution_log；read-only SubAgent second opinion（G04）
  → record_delegation_run 写 delegation_log（G05 seam）；checkpoint→resume 后 extension 上下文
  （tool_execution_log + delegation_log）双双保真；advance→DONE + progress 100%；evidence report
  呈现 extensions.delegations:1；acceptance gate 不 release-block。**AC-1**：S3+S2 验收集
  （S3 reference/MCP/SubAgent/extension/contract + S2 reference/skill/acceptance）合跑 **33 passed,
  1 skipped**，证明 S2 governed task path 经 extension 组合后不回归。Commit 见 WORK_LOG / `git log`（S3-G06）。
- **Risk if ignored**: AC-5 无验收命令；S3 无法判定「完成」。

### S3-G07 — Real provider S3 governed extension key-path smoke
- **Priority**: P1（must_fix_for_s3）
- **Layer**: L1
- **Related S3 Goal**: §0 real provider; §6 AC-6; §8 Resolved decision 5
- **Baseline evidence**: S2 AC-7 real smoke（`test_s2_reference_task_real_provider_key_safe_
  context_smoke`，opt-in `MY_FIRST_AGENT_RUN_S2_REAL_PROVIDER_SMOKE=1`，走 production
  path `build_model_provider_from_env()`，key-safe）已通过，但**不覆盖 extension**。
- **Gap**: real provider 在 key-safe opt-in 下覆盖关键 S3 path：能进入 extension-assisted
  governed path、能看到 extension evidence、与 fake/local 关键事件链路对齐；不要求覆盖
  所有 MCP/SubAgent 分支。
- **Needed action**: 扩展 real smoke 覆盖 reference task 的 extension key path；保持
  key-safe（opt-in、默认 skip、不读取/打印/复制/移动/提交 secret、不改 ignored config、
  不创建 .env）。
- **Verification**: opt-in 下 real provider 进入 extension governed path 并产生 extension
  evidence；默认 skip；secret 边界保持。
- **Dependencies**: S3-G06。
- **Non-goal boundary**: 不要求 real 覆盖所有分支；不连真实 MCP endpoint（fake/fixture
  MCP source）；不泄露 secret。
- **Suggested execution order**: P1-6。
- **Status**: satisfied（2026-06-20）。
- **Evidence**: `tests/test_s3_reference_task_acceptance.py::test_s3_reference_task_real_provider_extension_key_path_smoke`
  —— opt-in（`MY_FIRST_AGENT_RUN_S3_REAL_PROVIDER_SMOKE=1`）/ 默认 skip；走生产路径
  `build_model_provider_from_env()`（优先读 gitignored config/config.yaml）；fake-key 检测
  （fake/empty/placeholder → skip）；real provider 进入 extension-assisted governed path
  （MCP 结果 + read-only SubAgent second opinion 已进 task state）并看到 extension evidence
  （`extensions.delegations:1`），与 fake/local 链路对齐。**key-safe**：opt-in + fake-key 检测；
  不读取/打印/复制/移动/提交 secret；不改 config/config.yaml；不创建 .env；MCP 用 fake/fixture
  source、SubAgent 用 local_fake（不连真实 endpoint）。**诚实记录**：本次未实际执行 real 调用
  （无 real key，key-safe 不触），默认 skip + 结构性验证（镜像 S2 real smoke 验证标准）。Commit
  见 WORK_LOG / `git log`（S3-G07）。
- **Risk if ignored**: AC-6 无法达成；无法证明 real provider 能进入 extension 路径。

---

## 6. P2 — Should fix for S3

### S3-G08 — S3 acceptance gate extension-regression classification
- **Priority**: P2（should_fix_for_s3）
- **Layer**: L1 / Cross-cutting
- **Related S3 Goal**: §6 AC-7
- **Baseline evidence**: `agent/acceptance_gate.py` 当前分类 runtime_regression /
  doc_governance_debt / quality_debt / unknown_failure，**无 extension_regression 类**。
- **Gap**: 让 acceptance gate 能把 **extension regression**（MCP/SubAgent 接入引入的失败）
  与 runtime regression / known debt(TD-006/007) / unknown failure 区分，extension 失败
  不被混入或掩盖。
- **Needed action**: 在 acceptance gate 增加 extension_regression 分类口径与判据；
  不弱化既有分类。
- **Verification**: gate 对 extension 失败给出 extension_regression 信号；对 TD-006/007
  仍给 debt 信号；unknown 仍 release-blocking。
- **Dependencies**: 与 S3-G06 并行（需要 extension 路径存在以测试分类）。
- **Non-goal boundary**: 不重写 gate 既有四类；不把 TD-007 变 blocker。
- **Suggested execution order**: P2-1。
- **Status**: satisfied（2026-06-20）。
- **Evidence**: `agent/acceptance_gate.py` 纯新增 `AcceptanceSignal.EXTENSION_REGRESSION`（不弱化
  既有四类）+ `_looks_like_s3_extension_check`（判据：name/command 含 s3 + extension 标记
  mcp/subagent/extension/reference_task）+ `S2AcceptanceReport.extension_regressions` 属性；
  `tests/test_s3_acceptance_gate_extension_classification.py` 3 passed（S3 extension 失败 →
  EXTENSION_REGRESSION + release-blocking；与 TD-006/007 debt 区分不掩盖；既有 PASSED/
  QUALITY_DEBT/DOC_GOVERNANCE_DEBT/RUNTIME_REGRESSION/UNKNOWN_FAILURE 不弱化）。S2 gate 测试
  5 passed（不回归）。Commit 见 WORK_LOG / `git log`（S3-G08）。
- **Risk if ignored**: AC-7 无法达成；extension 回归被淹没在 debt 噪音里。

### S3-G09 — TD-006 release-gate cleanup
- **Priority**: P2（should_fix_for_s3）
- **Layer**: Cross-cutting / L1
- **Related S3 Goal**: §6 AC-9; §7; §8 Resolved decision 3
- **Baseline evidence**: TD-006 = 33 full-pytest guard 失败（doc-governance/architecture-
  boundary/taxonomy/diagnostics/contract guards，断言 pre-S2/frozen 库存），当前被
  `S2_ACCEPTANCE_GATE.md` 归类 doc_governance_debt。冻结 goal 已把 **TD-006 纳入 S3
  release gate**（AC-9）。权威失败清单：`docs/history/S2_GOVERNED_TASK_AGENT/
  _review_artifacts/_tmp_s2_baseline_audit/fullsuite_failures.txt`。
- **Gap**: S3 release 前把 TD-006 清理到 **full pytest 不再出现 governance/guard
  failure**，且每个 guard 对齐当前 governance docs/contracts（不静默弱化/删除断言）。
- **Needed action**: 逐个 guard 对齐当前 docs（含 S3 stage docs）后修复；release 前
  full pytest 无 governance-guard 失败；保持 known xfail 显式。
- **Verification**: `.venv/bin/python -m pytest` 无 TD-006 类 governance-guard failure；
  每个被改 guard 指向当前 authority。
- **Dependencies**: 与 P1 后期并行；受 S3-G10 docs governance 影响（guard 对齐目标）。
- **Non-goal boundary**: **不把清债当 S3 产品主目标**；不混入 TD-007；不靠弱化断言充数。
- **Suggested execution order**: P2-2。
- **Status**: open。
- **Risk if ignored**: AC-9 未达；full-suite 无法作 S3 release 判断。

### S3-G10 — docs/current + history governance for S3
- **Priority**: P2（should_fix_for_s3）
- **Layer**: Cross-cutting
- **Related S3 Goal**: §6 AC-8
- **Baseline evidence**: `AGENTS.md` Stage Development Governance（post-S2/pre-S3）+ S2
  已归档 `docs/history/S2_GOVERNED_TASK_AGENT/`；`docs/current/` 现持 S_ROADMAP/TECH_DEBT
  + S3 stage docs。
- **Gap**: S3 期间维持阶段治理不回退：S3 stage docs 在 current 区、S2/S1 归档不动、
  carry-forward 债不被静默关闭、WORK_LOG 持续追加、close-out 时按规则归档。
- **Needed action**: 贯穿 S3 维持治理边界；提供 S3 close-out 检查项（非本任务执行）。
- **Verification**: S2/S1 history 未改；TECH_DEBT 项不被静默关闭；S3 文档在 current；
  close-out 前可过 governance 检查。
- **Dependencies**: 无（贯穿）。
- **Non-goal boundary**: 不重写 governance 模型；不动 S1/S2 history。
- **Suggested execution order**: P2-3（贯穿，close-out 前必查）。
- **Status**: satisfied（2026-06-20）。
- **Evidence**: 治理不变量验证（`git diff 08049e9..HEAD`，08049e9 = S3 gap loop 起点）：
  (1) `docs/history/`（S1/S2 归档）本 session **未触**；(2) 冻结/安全文件
  `S3_GOAL.md` / `S3_BASELINE_STATUS.md` / `TECH_DEBT.md` / `config/config.yaml` / `.env`
  本 session **未触**；(3) S3 stage docs 全在 `docs/current/`（S3_BASELINE_STATUS/S3_GOAL/
  S3_GOAL_GAP/S3_REFERENCE_TASK/WORK_LOG）；(4) S1/S2 归档 + S2_RELEASE_SUMMARY 在位；
  (5) carry-forward 债（TD-001..007）未被静默关闭（TECH_DEBT 未改）。S3 close-out checklist
  已提供（见 WORK_LOG G10 条目；close-out 本身待 S3 全部 gap 完成后按 AGENTS.md Stage Closing
  Review 执行，非本 gap 执行）。Commit 见 WORK_LOG / `git log`（S3-G10）。
- **Risk if ignored**: AC-8 回退；阶段边界混乱误导后续 agent。

### S3-G11 — Skill contract remains S2 governed-active & non-regressed
- **Priority**: P2（should_fix_for_s3）
- **Layer**: L5
- **Related S3 Goal**: §4 scope-3 Skill; §5 L5-Skill; §6 AC-1
- **Baseline evidence**: Skill 已 governed-active（`agent/skill_system/*`，default-off
  gate `MY_FIRST_AGENT_S2_SKILL_ENABLE`，discovery allowed/activation default-off/
  execution gated）；S2-G09 测试契约（activation tests opt-in）已稳定。
- **Gap**: S3 把 Skill 模式抽象为通用 extension 契约（G02）时，**不得回退 Skill 的
  default-off 语义与 S2 测试契约**；Skill 维持 contract 参考角色，不作 S3 主新增目标。
- **Needed action**: 在 G02 抽象过程中保留 Skill 行为；回归测试守护 Skill default-off
  与 discovery/activation/execution 分层。
- **Verification**: Skill 相关 S2 测试不回归；default-off 行为不变。
- **Dependencies**: 与 S3-G02 协同。
- **Non-goal boundary**: 不把 Skill 作为 S3 新增激活目标；不改 Skill default-off 语义。
- **Suggested execution order**: P2-4（贯穿 regression guard）。
- **Status**: open。
- **Risk if ignored**: 抽象契约时误伤 Skill，AC-1 回归。

---

## 7. P3 — Optional for S3

### S3-G12 — Optional extension hardening (extra metadata / reports / provider checks)
- **Priority**: P3（optional_for_s3）
- **Layer**: L5 / L3
- **Related S3 Goal**: §6 AC-4（增强方向，非必达）
- **Baseline evidence**: G02 契约 + G03/G04 接入交付基本 metadata/enable-disable/risk/
  verification/evidence 即满足 AC-4；更深的 extension 可观测性是增强项。
- **Gap**: 可选增强：更丰富的 extension capability metadata、额外 extension report、
  额外 provider/extension health checks。
- **Needed action**: 视余力增强；不阻塞 S3 release。
- **Verification**: 增强项有测试/证据；不回归 P1/P2。
- **Dependencies**: S3-G02/G03/G04（在其之上增强）。
- **Non-goal boundary**: 不把可选增强升级为 S3 必达；不滑向生态化。
- **Suggested execution order**: P3-1（随时可做，不阻塞）。
- **Status**: open。
- **Risk if ignored**: 无（可选）；不影响 S3 核心完成。

---

## 8. P4 — Deferred to S4/Sn

### S3-G13 — Deferred boundaries & TECH_DEBT triage into S3/S4/Sn
- **Priority**: P4（s4_or_later / deferred）
- **Layer**: Cross-cutting / L5
- **Related S3 Goal**: §7 Non-goals; §8 Future deferred decisions
- **Baseline evidence**: Scheduler 已实现（`agent/action_scheduler.py` 的 `ActionScheduler`/
  `ActionPlan` + `action_scheduler_handler.py` + tests）但未激活；MCP 完整生态 / 完整
  multi-agent / durable task ledger 属 S2_TECH_DEBT_TRIAGE 的 S3+ deferred；TECH_DEBT
  剩余项 TD-001/002/003/004/007。
- **Gap（仅登记，不执行）**: 明确以下**不进入 S3**，留 S4/Sn 或继续 deferred：
  - **Scheduler 生产化 / 接入主 loop** → S4/Sn（S3 只保留 boundary，不激活）。
  - **完整 MCP 生态**（多 server 编排、动态发现生态化）→ S4/Sn。
  - **完整 multi-agent 生态**（可写 / 非 mediated SubAgent 委派）→ S4/Sn。
  - **Durable task ledger** → S4/Sn。
  - **TD-007** 全量 ruff 清零 → deferred（非 S3 release blocker）。
  - **TD-001 / TD-004**（evidence 逐字保真 / pending-tool 预览）→ deferred（S3-G05 可
    触及边缘，但全保真非 S3 必达）。
  - **TD-002 / TD-003**（legacy facade / dead code）→ deferred（非 S3 触发项）。
- **Needed action**: 贯穿 S3 维持以上 deferred 标注；若某 S3 任务正好路过相关代码再
  按需提升（需用户/goal 授权）。
- **Verification**: 这些项不出现在 S3 P0-P2 必达集合中；TECH_DEBT 与本文件一致。
- **Dependencies**: 无（贯穿登记）。
- **Non-goal boundary**: 本 gap 本身不执行任何清理/激活/生态化。
- **Suggested execution order**: P4-1（贯穿登记，不执行）。
- **Status**: deferred。
- **Risk if ignored**: 债务/范围归属模糊，误导后续 agent 把 S4/Sn 内容塞进 S3。

---

## 9. Original ID index

| ID | Title | Priority | Status | Layer | Related AC |
|---|---|---|---|---|---|
| S3-G01 | Define S3 reference task precisely | P0 | satisfied | Cross (L4) | AC-5/6 setup |
| S3-G02 | Unified extension capability contract | P1 | satisfied | L5/Cross | AC-4 |
| S3-G03 | MCP governed tool source (default-off/allowlist/policy/evidence) | P1 | satisfied | L5/L3 | AC-2 |
| S3-G04 | SubAgent read-only/audit-first parent-mediated path | P1 | satisfied | L5/L3 | AC-3 |
| S3-G05 | Extension evidence/checkpoint/task-state integration | P1 | satisfied | L2/L3 | AC-1/4 |
| S3-G06 | Extension-assisted repo governance E2E reference task | P1 | satisfied | L4 | AC-1/5 |
| S3-G07 | Real provider S3 governed extension key-path smoke | P1 | satisfied | L1 | AC-6 |
| S3-G08 | Acceptance gate extension-regression classification | P2 | satisfied | L1/Cross | AC-7 |
| S3-G09 | TD-006 release-gate cleanup | P2 | open | Cross/L1 | AC-9 |
| S3-G10 | docs/current+history governance for S3 | P2 | satisfied | Cross | AC-8 |
| S3-G11 | Skill contract remains governed-active & non-regressed | P2 | open | L5 | AC-1 |
| S3-G12 | Optional extension hardening | P3 | open | L5/L3 | AC-4 (enhance) |
| S3-G13 | Deferred boundaries & TECH_DEBT triage (S4/Sn) | P4 | deferred | Cross/L5 | §7/§8 |

## 10. Non-goal guardrails

S3 **不做**（防止 agent 越界）：

- 不推翻 S1/S2 runtime spine；不引入第二条主链路（same-spine 是 must-not-regress）。
- **不做完整 MCP 生态**（S3 的 MCP 仅受控 tool source；多 server 编排/动态发现生态留 S4/Sn）。
- **不做完整 multi-agent 生态**（S3 的 SubAgent 仅 read-only/audit-first/parent-mediated；
  可写/非 mediated 委派留 S4/Sn）。
- **不做 Scheduler 生产化 / 不接入主 loop**（S3 只保留 boundary）。
- **不让 MCP / SubAgent 绕过 policy / evidence / checkpoint / task-state / same-spine**；
  任何旁路视为缺陷。
- **不把 TD-007 / ruff 全清作为 S3 release blocker**（仅 quality debt / strategy）。
- 不连接真实 MCP endpoint / 不做 server reachability check；MCP/SubAgent 工作 fake-first、
  local-only、fixture/sample based（`AGENTS.md` 安全边界）。
- 不做独立 durable task ledger（S4/Sn）。
- **不开始 S4/Sn**；不删未完成 gap；完成需证据。

## 11. Next step

- **用户审阅本 `S3_GOAL_GAP.md`**，确认 gap 集合、优先级与执行顺序。
- 确认后再进入 **S3 gap loop**（按 §3 推荐顺序，每个 gap 独立 focused mini-run、验证、
  更新 backlog/work log、独立提交）。
- **本任务不执行任何 gap、不进入 gap loop、不修改代码/tests、不 push。**
