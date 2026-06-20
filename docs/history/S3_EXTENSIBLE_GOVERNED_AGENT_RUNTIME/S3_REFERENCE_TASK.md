# S3 Reference Task — Extension-assisted Repo Governance (Precise Spec / Runbook)

> Current document (`docs/current/`). 由 S3-G01 产出。本文把冻结 `S3_GOAL.md §0` 命名的
> reference task(**Extension-assisted repo governance task**)落地为**可执行规格**，使
> AC-5（闭环）/ AC-6（real key path）能据此写出具体验收命令与断言。
>
> **本文件只定义，不实现。** 实现落在 S3-G06（fake/local E2E acceptance）与 S3-G07（real
> provider key-path smoke）。MCP / SubAgent 的具体接入形状由 S3-G02（统一契约）、
> S3-G03（MCP governed tool source）、S3-G04（SubAgent read-only/audit-first）定义；
> evidence/checkpoint/task-state 由 S3-G05 对齐。本文只规定 reference task 的**场景、角色、
> 闭环、判据**，不规定模块内部实现。

## 0. 一句话定位

> S2 reference task 回答「主 Agent 能否独自完成受控多步 repo 任务」。
> S3 reference task 回答「主 Agent 能否在**不失去 same-spine / policy / evidence /
> checkpoint 控制**的前提下，**借助 MCP 工具来源 + read-only SubAgent 委派**完成同一类
> repo governance 任务」。

S3 reference task = **Extension-assisted repo governance: gap-evidence audit**。主 Agent
承接一个 repo governance 子任务（判定某被跟踪 gap 是否已满足），过程中：

1. 用**受控 MCP tool source** 取上下文（读 fixture repo 证据）；
2. 调 **read-only / audit-first / parent-mediated SubAgent** 做 second opinion；
3. 主 Agent **汇总 evidence、adjudicate、推进任务、产出治理报告/决策**。

全程走 S2 governed task path，不绕过 dispatcher/mediator/policy/evidence/checkpoint。

## 1. Targeted Gate（G06 实现锚点）

```bash
.venv/bin/python -m pytest tests/test_s3_reference_task_acceptance.py -q
```

预期默认结果（fake/local）：

- S3 reference-task E2E 确定性通过，且确实经 MCP+SubAgent governed path；
- S2 targeted gate 仍通过（S2 governed task path 不回归，AC-1）；
- real-provider extension smoke 默认 skip（opt-in）；
- 不需要 `.env` 或 `config/config.yaml` 变更。

## 2. Covered closed loop（fake/local）

闭环映射到 S2 governed task skeleton（`receive → plan → execute → advance →
checkpoint → resume → done`），在 `execute` 阶段**组合 MCP tool source 与 read-only
SubAgent 委派**：

| 阶段 | 动作 | extension 维度 |
|---|---|---|
| receive | 主 Agent 接收 repo governance 子任务（gap-evidence audit） | — |
| plan | plan 确认：含「读证据 / 取 second opinion / adjudicate / 报告」步骤 | plan 引用受控 MCP tool 与 read-only SubAgent |
| execute-1 | 主 Agent 经**受控 MCP tool source** 读 fixture repo 证据（governed tool path） | **MCP tool source**（G03） |
| execute-2 | 主 Agent 委派 **read-only SubAgent** 做 second opinion（audit record） | **SubAgent parent-mediated**（G04） |
| execute-3 | 主 Agent **adjudicate** SubAgent 结果 + 汇总 MCP/SubAgent evidence | extension evidence（G05） |
| checkpoint | 保存任务状态（含 extension 中间结果） | extension 进 checkpoint（G05） |
| resume | 恢复后 extension evidence/上下文不丢 | resume 不丢（G05） |
| advance/done | 步骤推进、progress %、DONE 投影 | — |
| gate | acceptance gate 分类（extension 不被混入 debt） | extension_regression（G08） |

## 3. Inputs（fixture 级、fake 确定性）

- **Repo governance 子任务**：判定某 fixture gap（例如 `FIXTURE-GAP-1: docs evidence
  satisfies AC`）是否已满足。输入是 fixture 文档/证据片段，**不触碰真实 repo 写路径、不连
  真实 endpoint**。
- **受控 MCP tool source**：一个 fake/fixture MCP 工具（例如 `repo_doc_reader`），经
  allowlist + policy + evidence 暴露；default-off（gate 关闭时不暴露），allowlist 外的工具
  被拒。**不连真实 MCP endpoint / 不做 server reachability check**（`AGENTS.md` 安全边界）。
- **read-only SubAgent**：一个 fixture SubAgent（例如 `repo_gap_auditor`），只做 read-only
  audit / second opinion；child 不直接持 tool/provider/memory 旁路；结果以
  `SubAgentAuditRecord` 返回，由主 Agent `adjudicate_result`。
- **Plan**：沿用 S2 plan 形状（`goal` / `thinking` / `steps[]`），步骤显式标注
  `mcp_context_fetch` 与 `subagent_second_opinion` 两类受控 extension 步骤。

## 4. 角色契约（reference task 视角，不规定模块内部）

> 字段形状以 S3-G02 统一 extension capability contract 为准（metadata / enable-disable /
> risk / verification / evidence）。本节只列 reference task 需要的**角色与边界**。

- **MCP tool source 角色**：
  - 提供「读 fixture repo 证据」能力；调用经 dispatcher/mediator 进入同一 governed tool
    path（与 S2 既有 tool 同 path）；
  - 受 policy gate（allow/reject）+ evidence；default-off + allowlist；关闭时行为同 S2
    （不暴露 MCP 工具）；
  - risk：external tool source（即使是 fake/fixture），必须经 policy/evidence，不得旁路。
- **read-only SubAgent 角色**：
  - 提供「对 gap 证据的 second opinion / audit」；**read-only / audit-first**；
  - **parent-mediated**：child 不直接执行 tool / provider / memory；委派经 policy/evidence；
    default-off 可禁用；关闭时行为同 S2；
  - 结果 `SubAgentAuditRecord` 可复盘；主 Agent `adjudicate_result` 决定 accept/revise。
- **主 Agent 角色**：
  - 唯一的决策与 side-effect 主体；汇总 MCP tool 结果 + SubAgent audit → task evidence；
  - 推进 governed task state；产出治理报告/决策（fixture 级）。

## 5. Fake deterministic success criteria（AC-5）

G06 的 fake/local E2E 必须断言（具体断言在 G06 落地，此处为可验收口径）：

1. **闭环完成**：`receive → accept → execute(MCP+SubAgent) → checkpoint → resume → done`，
   最终 `lifecycle is DONE`、`progress.percent == 100.0`。
2. **MCP 经 governed path**：受控 MCP tool 调用产生 governed tool evidence（allowed/记录）；
   default-off 时不暴露；allowlist 外的 MCP tool 被拒。
3. **SubAgent read-only / parent-mediated**：委派产生 `SubAgentAuditRecord`；child 未绕过主
   Agent 执行 tool/provider/memory（旁路即缺陷）；主 Agent adjudicate 生效。
4. **extension evidence 对齐**：evidence 含 MCP tool 结果与 SubAgent audit；checkpoint→resume
   后 extension evidence/上下文完整（不丢）。
5. **acceptance gate 分类正确**：extension 路径的失败被归为 extension_regression（G08），
   不被混入 TD-006/007 debt；release gate 对 fake 成功路径 `release_blocked is False`。
6. **S2 不回归（AC-1）**：S2 targeted gate（reference / skill / acceptance）仍通过。

## 6. Real provider key-path smoke（AC-6，G07 实现）

opt-in、key-safe（沿用 S2 `_real_provider_env_ready()` 模式）：

```bash
MY_FIRST_AGENT_RUN_S3_REAL_PROVIDER_SMOKE=1 \
.venv/bin/python -m pytest \
  tests/test_s3_reference_task_acceptance.py::test_s3_reference_task_real_provider_extension_key_path_smoke -q
```

real provider 须证明：

- 进入 **extension-assisted governed path**（与 fake 同一入口，非旁路 bare provider.create）；
- 能看到 **extension evidence**（MCP/SubAgent 产生的事件链路与 fake/local 对齐）；
- key-safe：opt-in、默认 skip、fake-key 检测、不读取/打印/复制/移动/提交 secret、不改
  ignored config、不创建 `.env`；MCP 仍用 fake/fixture source（不连真实 endpoint）。

不要求 real 覆盖所有 MCP/SubAgent 分支。

## 7. Non-goals / boundaries

- 不把 full pytest 全绿当 S3 产品目标（见 `S3_GOAL_GAP.md §10`）；reference task 只做
  targeted gate。
- 不连真实 MCP endpoint / 不做 server reachability check；MCP/SubAgent fake-first、
  local-only、fixture-based（`AGENTS.md` 安全边界）。
- 不让 MCP/SubAgent 绕过 policy/evidence/checkpoint/task-state/same-spine；SubAgent 不绕过
  主 Agent 执行 tool/provider/memory。
- 不做完整 MCP 生态 / 完整 multi-agent 生态 / Scheduler 生产化（留 S4/Sn）。
- 不修改 `config/config.yaml` 或创建 `.env`；不读/打印/移动/提交 secret。
