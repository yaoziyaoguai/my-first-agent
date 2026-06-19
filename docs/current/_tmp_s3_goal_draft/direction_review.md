# S3 Direction Review — Roadmap-Grounded

> Working evidence for drafting `docs/current/S3_GOAL.md` (2026-06-19). Scratch /
> reasoning doc, not routing authority. Archived with the stage when S3 closes.
> 目的：在写 S3_GOAL 之前，先把"roadmap 允许什么 / 不承诺什么 / baseline 给了什么 /
> 债务约束什么"摆清楚，再对比候选方向，最后给推荐——避免凭空决定 S3 方向。

## 1. What the roadmap explicitly says（S_ROADMAP.md）

- S 系列 = 产品版本序列（S1/S2/S3…Sn），**不是代码 v1/v2/v3**（§1）。
- S2/S3/Sn = **在 S1 基线之上、围绕五层能力主线的持续补强版本**；约束是
  **不推翻 S1 架构主链路**（§3）。
- 五层主线稳定（§4）：L1 Runtime Spine / L2 Context-Memory-State-Checkpoint /
  L3 Tools-Policy-Evidence / L4 Task Orchestration / **L5 Skill·MCP·SubAgent·
  Scheduler Extension Boundary**。
- 高层方向（§5）：**"S2 及以后：在 S1 基线上，按届时确定的优先级，对某些层做深度补强
  （例如扩展能力从 boundary-clear 走向 selectively-active）。"** —— roadmap 把
  "扩展能力(L5)逐级成熟"作为明确举例的演进方向。
- 治理（§6）：`docs/current/` 是权威区；history 是证据非路线。

## 2. What the roadmap does NOT promise

- **不**为 S3 预先承诺范围或时间（§3："不把 S2/S3/Sn 写成硬性实施计划"）。
- **不**指定 S3 必须做哪一层、必须激活哪个 L5 扩展。
- **不**要求一次性把所有 L5（Skill/MCP/SubAgent/Scheduler）生产化。
- **不**把测试/文档/lint 全绿（TD-006/TD-007）写成产品目标。
- 结论：**S3 的具体方向是"本阶段基于 baseline 的选择"，必须由本 goal 显式选定，
  且不得超出"五层主线 + 不推翻 S1/S2 主链路"的边界。**

## 3. What the S3 baseline inherits（S3_BASELINE_STATUS.md + S2 archive）

S2 = Governed Task Agent，完成/归档；must-not-regress 起点：

- **L4** governed task path（state model / orchestration skeleton / progress /
  human review seam）：`agent/task_state_model.py`、`task_orchestration.py`、
  `task_runtime.py`、`task_review.py`。
- **L2** task-scoped context/memory/checkpoint：`agent/task_context.py`、
  `memory_store.py`；resume 不丢 provider-callable content。
- **L3** governed tool contract + task evidence：`agent/task_tool_contract.py`、
  `tool_runtime_mediator.py`、`evidence_recorder.py`、`task_evidence_report.py`。
- **L1** same-spine + acceptance classification：`agent/core.py`、
  `acceptance_gate.py`（runtime_regression / doc_governance_debt / quality_debt /
  unknown_failure）。
- **L5** Skill **已 governed-active**（default-off gate `MY_FIRST_AGENT_S2_SKILL_ENABLE`，
  discovery allowed / activation default-off / execution gated）：`agent/skill_system/*`。
- **AC-7** real provider governed-path smoke（opt-in、key-safe）。
- targeted S2 gate fresh：**12 passed, 1 skipped**（仍可信）。

### L5 extension boundary 当前成熟度（graphify + file 核验，S3 起点事实）

| L5 能力 | 当前状态 | 代码落点 |
|---|---|---|
| **Skill** | **governed-active**（S2 交付，default-off gate） | `agent/skill_system/*`（gate/selector/lifecycle/checkpoint_restore/task_boundary） |
| **SubAgent** | boundary-clear / parent-mediated，wiring 最齐，**未激活**；public API 经 architecture-boundary 测试断言为 explicit + side-effect-free（不触发 real LLM/shell） | `agent/subagent_system/{registry,context,delegation,executor}.py`；`agent/runtime_integration/` 代理；`delegate_l1`/`execute_l1`/`build_context_package`/`SubAgentContextPackage` |
| **MCP** | configurable default-off（`MY_FIRST_AGENT_MCP_ENABLE`），**未默认激活** | `agent/runtime_integration/{mcp_bridge_lifecycle,mcp_tool_orchestrator}.py` |
| **Scheduler** | 已有 `ActionScheduler`/`ActionPlan`/`ActionNode`/`ActionRecoveryPolicy` + runtime handler + tests，但**未在默认 agent loop 激活**（S2-G08 旧表述"dormant/main.py 0 refs"偏保守） | `agent/action_scheduler.py`、`agent/runtime_integration/action_scheduler_handler.py`、`tests/runtime_integration/test_scheduler_main_path.py` |

**轨迹**（roadmap §5 + S1/S2 事实）：L5 在 **S1 = boundary-clear** → **S2 = 一个
(Skill) selectively/governed-active** → **S3 = 把扩展边界继续推进到"更成熟、更可治理"**
是 roadmap 直接支持的演进线，而非凭空新方向。

## 4. TECH_DEBT constraints on S3（docs/current/TECH_DEBT.md）

- **TD-006**（P1，full-suite 33 guard 红）/ **TD-007**（P3，ruff ~451）：是 S3 起点的
  **质量债**，不是 S3 产品目标。约束：若 S3 想用 full-suite 当 release gate，需先清
  TD-006；否则继续用 targeted gate。**不得把 TD-006/007 清理当 S3 主目标。**
- **TD-001/004**（evidence 保真 / pending-tool 预览）：若 S3 让 extension 参与任务并
  要求复盘级 evidence，可能**触及但不必须解决**；按 S3 的 evidence 深度决定（open）。
- **TD-002/003**（legacy facade / dead code）：S3/Sn cleanup 候选，**不是** S3 触发项，
  除非某 S3 任务正好路过该区域。
- 结论：债务**约束 S3 的 release 信号策略与 evidence 深度**，但**不定义 S3 的产品方向**。

## 5. Candidate S3 directions

### Option A — L5 Extension Boundary Maturation / 扩展边界成熟（推荐）
- **来源**：roadmap §5（扩展能力逐级成熟）+ S2 已用 Skill 建立 governed-active 模式 +
  baseline 显示 SubAgent/MCP/Scheduler 仍 boundary-clear/未激活。
- **含义**：把 S2 在 Skill 上验证过的"受控激活模式"（discovery→select→enable→
  govern→evidence→disable）推广为**通用 extension 接入契约**，并选择 **1-2 个**
  L5 能力（Skill 之外）从 boundary-clear/dormant 推进到 **governed-active**，全程受
  L1-L4 约束（same-spine / task-state / policy / evidence / checkpoint）。
- **收益**：直接落在 roadmap 五层主线上；复用 S2 的 acceptance/evidence 框架；产品
  价值清晰（Agent 能受控地组合更多扩展能力完成任务）；可增量、可禁用、可回滚。
- **风险**：若一次选太多 L5 会变成"全做"（违反 non-goal）；extension 激活若绕过
  policy/evidence 会破坏 governance；需要严格 scope 到 1-2 个。
- **roadmap 契合**：高。是 §5 举例方向的自然延伸。

### Option B — Full-suite Governance / 测试与文档治理收敛
- **来源**：TD-006/TD-007；S2 acceptance gate 已能分类债务但未清理。
- **含义**：把 full pytest + ruff 收敛到可作 release gate 的绿态（清 TD-006 guard、
  批量 TD-007 lint），让 S3 release 不再依赖 targeted gate。
- **收益**：release 信号更强；长期健康。
- **风险**：**这正是 roadmap §5 和 S2 non-goal 反复警告的"把清债当产品目标"**；
  S2_GOAL §8 / S2-G10 已明确 TD-006/007 是 health/debt 信号而非产品目标。把它做成
  S3 主线会让 S3 沦为"S2 cleanup 的延续"，违反任务原则。
- **roadmap 契合**：低（作为产品主线）。**应作为 S3 内的 supporting / open decision，
  不作为 S3 产品目标。**

### Option C — Task Intelligence / 更强任务执行智能
- **来源**：S2 交付了 governed task path 的"骨架"；可在其上增强 planning/重规划/
  失败恢复/多步推理质量。
- **含义**：让 task orchestration 更"聪明"（更好的 plan 生成、re-plan、失败自恢复、
  evidence 驱动决策）。
- **收益**：直接提升任务完成质量。
- **风险**：(1) 容易滑向"完整自主 agent / AutoGPT 式"，超出"受控"边界；(2) 与 roadmap
  §5 举例的"扩展能力成熟"不如 Option A 直接对应；(3) 边界不如 A 清晰，验收更难。
- **roadmap 契合**：中。是 L4 深化，合法但不是 §5 点名的方向；更适合作为 Option A 的
  **配套**（reference task 用扩展能力时顺带验证编排），而非独立主线。

## 6. Recommended direction

**推荐 Option A：S3 — Extensible Governed Agent Runtime / 可扩展的受控 Agent Runtime。**

理由：
1. **roadmap 直接支持**：§5 把"扩展能力逐级成熟"作为 S2+ 的举例演进方向；S3 把它从
   "selectively-active（S2/Skill）"推进到"governed-active extension boundary"是最
   有据可循的下一步。
2. **复用而非推翻**：完全在 S1/S2 same-spine + governed task path + acceptance/
   evidence 框架内增量；Skill 已提供可照搬的受控激活模式。
3. **边界清晰可验收**：以"1-2 个 L5 进入 governed-active + 统一 extension 接入契约"为
   核心，AC 容易写实、容易判定回归。
4. **不越界**：明确把"全量 L5 生态化 / 多 Agent 生态 / 清债当目标 / 自主 agent"列为
   non-goal；把"具体选哪 1-2 个 L5"留作 open decision。
- Option B 降级为 S3 内的 supporting concern（release 信号策略），Option C 降级为
  Option A 的配套验证，均不作为 S3 产品主线。

## 7. What must stay OPEN (not hard-coded into S3 goal)

以下只能作为 S3 open decisions / selected-scope，**不得在 goal 里写死为已承诺目标**：

1. **选哪 1-2 个 L5 extension 进入 governed-active？**（候选优先级建议：SubAgent
   parent-mediated read-only/audit > MCP configurable > Scheduler；但**由用户定**。）
2. **MCP 是否作为 S3 必达**？（默认不写死。）
3. **SubAgent 是否仅限 read-only / audit 委派**（不写/不改文件）？
4. **Scheduler 是否 defer 到 S4/Sn**？
5. **TD-006 是否进入 S3 release gate**（即 S3 是否要求 full-suite 绿）？
6. **S3 reference task 选什么**（建议延续 S2 的 repo-governed 风格，但具体由用户定）？
7. **real provider 覆盖深度到哪里**（延续 key-safe opt-in；覆盖广度待定）？

> 强约束：S3_GOAL 不得出现"Skill+MCP+SubAgent 全做"或"完整多 Agent 生态"作为已承诺
> 目标；它们只能作为 non-goal / deferred。S3 gap（S3_GOAL_GAP.md）本任务不生成，
> 仅在用户批准 goal 后再做。
