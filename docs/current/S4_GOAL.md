# S4 Goal — Auditable Governed Agent Runtime

> Current document (`docs/current/`). **状态：DRAFT / PROPOSED — pending user
> approval to FREEZE.** 本 goal 由 coding agent 基于 `S_ROADMAP.md`（五层主线）、
> `S4_BASELINE_STATUS.md`（S4 起点现状）与当前 `TECH_DEBT.md` 自主拟定。
>
> 冻结含义（`AGENTS.md` goal rules）：**只有用户能批准并冻结 goal**。在用户确认 §8
> Open decisions 之前，本文是 proposed direction，不得据此进入 gap loop 的不可逆实现。
> 已生成的 `S4_GOAL_GAP.md` 是 backlog，同样在用户冻结前不执行。

## 0. Executive summary

S4 = **Auditable Governed Agent Runtime / 可审计的受控 Agent Runtime**。核心是
**L3 Evidence & Audit Fidelity Maturation**：在**不推翻 S1/S2/S3 same-spine runtime**
的前提下，把 task evidence 从「结构化摘要」推进到**可忠实复放 / 可验证的审计轨迹**
（faithful, secret-safe replay + verification），在严格的 key-safe 边界内。

- S4 **继承** S1+S2+S3 的 must-not-regress 地板（same-spine / governed task path /
  L5 extension governed-active / acceptance gate），作为不回归起点。
- S4 **不**激活任何 dormant 能力（Scheduler 仍 dormant），**不**扩张 MCP/SubAgent
  超出其受控边界，**不**做 memory 激活（需用户另行显式授权）。
- S4 直接消化两条 carry-forward 证据债：**TD-001**（evidence 非逐字 / 复放保真不足）
  与 **TD-004**（pending-tool 事件预览缺失）。

一句话定位：

> S2 答「agent 能否可靠地**执行**受控多步任务？」
> S3 答「agent 能否在不失控的前提下**扩展**受控工作？」
> S4 答「这些受控工作能否被**忠实复放与验证**——在不泄露 secret 的前提下，让人/合规
> 能从 evidence 重建 agent 做了什么？」

**TD policy（proposed）**：TD-001 / TD-004 进入 S4 范围（在 key-safe 边界内消化）；
TD-007（ruff）仍**不**作 release blocker；full-suite 已绿，作为 S4 release 信号。

## 1. Roadmap constraints

- **S 系列 ≠ 代码 v1/v2/v3。** S1/S2/S3/S4 是产品阶段版本（`S_ROADMAP.md §1`）。
- **S4 必须继承 S1/S2/S3 主链路。** 只能在不推翻 same-spine 的前提下深化
  （`S_ROADMAP.md §3`）；fake/real 仅 factory/config 层不同，是 must-not-regress。
- **Roadmap 只定义五层主线，不预设 S4 范围**（`§3`）；`§5` 举例 S2+ 对某层「选择性深化」
  ——S4 选 **L3（evidence/policy/evidence 中的 evidence 维度）** 深化，受 L1-L4 约束。
- **S4 goal 是本阶段基于 baseline 的选择**，不是 roadmap 预设；从五层主线（重点 L3）+
  S4 baseline + carry-forward 债推导，不越「不推翻主链路」边界。

## 2. Inherited S4 baseline (摘要)

摘自 `S4_BASELINE_STATUS.md`（详见该文件）：

- S3 completed/archived；same-spine + 五层面完整；L5 = Skill/MCP/SubAgent
  governed-active，Scheduler dormant。
- L3 现状：统一 mediator/dispatcher/policy；`TaskEvidenceReport` 为**结构化 replay
  metadata（非逐字）**；`evidence_recorder.py` 走 safe-summary 纪律；TD-001/TD-004 open。
- full pytest 绿（4823 passed / 0 failed）；ruff ~443（TD-007，非 blocker）。

## 3. Candidate S4 directions（决策记录）

> 方向已选定（Direction A，见 §4），本节保留候选对比作为决策依据。

### Direction A — L3 Auditable / Replayable Evidence（**SELECTED**）
- **Description**：把 evidence 从结构化摘要推进到**可忠实复放 + 可验证**的审计轨迹：
  在 key-safe 边界内补全 governed task（含 MCP/SubAgent extension）的决策/工具/委派链路，
  使其可从 evidence 重建并校验；消化 TD-001（保真）与 TD-004（pending-tool 预览）。
- **Why it fits roadmap**：直接落在五层主线 L3 的 evidence 维度，`§5` 举例的「选择性深化」；
  复用 S2/S3 evidence 主链，不新增第二条主链路。
- **Pros**：最低风险；复用 S2/S3 spine 与 acceptance/evidence 框架；增量、可禁用/可回滚；
  AC 可验证（复放完整性 + 一致性校验）；不激活 dormant 能力；天然 key-safe（evidence 本地）。
- **Risks 与对策**：保真度可能滑向「逐字持久化 secret」→ §7 non-goal 明令 secret-safe
  redaction、不持久化 raw key/secret；范围可能滑向 durable ledger → §7 把 TD-011 排除。
- **Selected**：是。

### Direction B — L4 Governed Task Intelligence
- **Description**：增强 re-plan / 失败自恢复 / evidence 驱动 adjudication（L4 深化）。
- **Why not selected**：易滑向「自主 / AutoGPT 式」（超出「受控」），边界比 A 难锁；
  baseline §8 已列为更高风险项。作为 A 的潜在后续（S5+），非 S4 主线。

### Direction C — L2 Durability（durable ledger / memory activation）
- **Description**：durable 跨会话 task ledger（TD-011）+（授权门控的）scoped memory 激活。
- **Why not selected**：memory 激活需用户**显式授权**（`AGENTS.md`）；durable ledger 是较大
  infra。与 A 的「可审计」目标相关但属 L2 持久化轴，留待 S5+ 或用户另行选择。

## 4. Selected S4 direction（proposed scope）

**Selected：Direction A — Auditable Governed Agent Runtime（L3 evidence/audit
fidelity maturation）。**

核心范围（proposed，pending user freeze）：

1. **Replay-faithful evidence** —— governed task evidence 能忠实重建一条 governed task
   （含 MCP tool 调用 + read-only SubAgent 委派）的**决策/工具/委派链路**，超出当前
   结构化摘要；定义清晰的 **fidelity contract**（记什么、到什么粒度、可复放到什么程度）。
2. **Secret-safe fidelity** —— 更高保真**绝不**以泄露 secret 为代价：强制 redaction，
   不持久化 raw API key / secret / 完整凭证；key-safe 是硬边界（消化 TD-001 的同时守边界）。
3. **Pending-tool event fidelity** —— 补全 pending-tool `events.jsonl` 的 tool_output
   预览（消化 TD-004）。
4. **Evidence verification** —— 提供对 evidence 的**一致性/完整性校验**（如：记录链是否
   完整、是否自洽、可复放断言），使 evidence 不仅「存在」且「可验证」。
5. **保持边界** —— same-spine / task-state / policy / checkpoint / L5 governed-active
   全部 must-not-regress；不激活 Scheduler；不扩张 MCP/SubAgent；不激活 memory。

## 5. Layer goals（约束 selected direction，不是施工步骤）

- **L1 — Runtime Spine**：**不重写** spine（must-not-regress）。evidence 深化只在既有
  evidence/记录 seam 上增量，不新增第二条主链路。
- **L2 — Context/Memory/State/Checkpoint**：evidence 的复放/校验复用既有 checkpoint/
  task-state；**不激活 memory**、**不引入 durable ledger**（TD-011 仍 deferred）。
- **L3 — Tools/Policy/Evidence（重点）**：evidence 从结构化摘要 → 可复放/可验证审计轨迹；
  redaction 强制；pending-tool 预览补全；提供 evidence 一致性校验。policy/mediator 路径不变。
- **L4 — Task Orchestration**：governed task path 不退化；S4 reference task（audit/replay
  reference task）在 governed path 内完成「执行 → 记录 → 复放/校验」闭环。
- **L5 — Skill/MCP/SubAgent/Scheduler**：维持 S3 governed-active（不退化、不扩张）；
  extension 产生的 evidence 纳入 S4 保真/校验边界；Scheduler 仍 **dormant，不激活**。

## 6. Acceptance criteria（proposed 口径；阈值在 gap 阶段细化，不得削弱本节）

1. **AC-1（S1/S2/S3 不回归）**：same-spine / governed task path / L5 extension
   governed-active / acceptance gate 在 fake 确定性下不回归；targeted S2+S3 gate 与
   full pytest 仍绿。
2. **AC-2（replay-faithful evidence）**：对一条 governed task（含 MCP + SubAgent），
   evidence 能忠实重建决策/工具/委派链路（达成定义的 fidelity contract），超出当前摘要级。
3. **AC-3（secret-safe fidelity）**：更高保真 evidence **不持久化** raw secret/key；
   redaction 有测试断言；key-safe（opt-in real path 沿用 S3 模式，默认 skip）。
4. **AC-4（pending-tool fidelity / TD-004）**：pending-tool 事件日志呈现 tool_output
   预览（非空），消化 TD-004。
5. **AC-5（evidence verification）**：提供 evidence 一致性/完整性校验，能检出残缺/不自洽
   的 evidence 链；通过校验的 evidence 可复放。
6. **AC-6（S4 reference task 闭环）**：audit/replay reference task 在 governed path 内
   完成「执行 → 记录 → 复放/校验」闭环（fake 确定性）；real provider key-safe smoke 可选
   （opt-in、默认 skip、不泄露 secret）。
7. **AC-7（acceptance gate 可分类）**：evidence-fidelity 回归被 acceptance gate 可分类
   （复用/扩展既有类，不弱化 runtime_regression / extension_regression / debt / unknown）。
8. **AC-8（阶段治理不回退）**：`docs/current` / `docs/history` / `TECH_DEBT.md` 治理边界
   不回退（S1/S2/S3 归档不动、carry-forward 债不被静默关闭、S4 文档在 current）。
9. **AC-9（release 信号）**：full pytest 保持绿作为 S4 release 信号；TD-007（ruff）不在
   本 AC 内、不作 release blocker。

## 7. Non-goals

S4 明确**不**做：

- 不重写 S1/S2/S3 runtime spine，不引入第二条主链路。
- **不持久化 raw secret / API key / 完整凭证**——更高保真**必须** secret-safe（redaction）。
- **不做逐字全量持久化**（byte-for-byte of everything）若其与 secret-safe 冲突；保真以
  「可忠实复放受控链路」为准，不以「存下一切原始字节」为准。
- 不做 Scheduler 生产化 / 不接入主 loop（TD-008 仍 deferred）。
- 不做完整 MCP 生态（TD-009）/ 完整 multi-agent 生态 / 可写 SubAgent 委派（TD-010）。
- **不做 memory 激活**（需用户显式授权，超出本 goal）。
- **不做独立 durable cross-session task ledger**（TD-011 仍 deferred；resume 仍靠 checkpoint）。
- 不做完整 AutoGPT 式自主代理。
- 不把 TD-007 全清当 release blocker。
- 不开始 S5/Sn。

## 8. Open decisions（pending user — 冻结前必须确认）

> 本 goal 由 agent 自主拟定。以下决策需用户确认后本 goal 方可 FREEZE；确认前不进入
> 不可逆实现。

1. **Selected direction**：确认 S4 = Direction A（Auditable Governed Agent Runtime），
   而非 B（L4 task intelligence）或 C（L2 durability）。
2. **Fidelity ceiling**：确认保真目标为「**redacted-faithful replay of the governed
   chain**」（可复放受控决策/工具/委派链路 + secret redaction），而非「逐字原始字节」。
3. **Durable ledger（TD-011）**：确认在 S4 **deferred**（resume 仍靠 checkpoint），不作
   S4 必达。
4. **Real provider audit smoke**：确认 real-provider 复放/审计 smoke 为**可选 key-safe
   opt-in**（镜像 S3 AC-6），非必达全分支。
5. **Memory**：确认 S4 **不**激活 memory（保持 AGENTS.md「no memory activation unless
   explicitly authorized」）。

## 9. Next step

- 本 `S4_GOAL.md` 为 **proposed/draft**；**等用户确认 §8 后冻结**。
- gap 已生成（`S4_GOAL_GAP.md`，backlog，不执行）。
- 冻结后再进入 S4 gap loop（每个 gap 独立 focused mini-run、TDD、验证、提交）。
- **本任务不执行任何 S4 gap、不进入 gap loop、不修改代码/tests、不 push。**
