# S4 Evidence Fidelity Contract + Audit/Replay Reference Task

> Current document (`docs/current/`). 由 **S4-G01（P0）** 产出。本文把冻结
> `S4_GOAL.md §4/§8-2` 的 fidelity ceiling（**redacted-faithful replay**）落地为
> **可执行契约**，使 AC-2（replay-faithful evidence）/ AC-5（evidence 校验）/ AC-6
> （reference task 闭环）能据此写出具体验收命令与断言。
>
> **本文件只定义，不实现。** 实现落在 S4-G02（replay-faithful evidence model）、
> S4-G03（redaction 强制）、S4-G04（pending-tool 预览）、S4-G05（evidence verifier）、
> S4-G06（fake/local E2E）、S4-G07（real key-path smoke）。本文只规定 **保真到什么粒度、
> 记什么、可复放到什么程度、redaction 边界、校验判据**，不规定模块内部实现。

## 0. 一句话定位

> S2 reference task 回答「主 Agent 能否独自完成受控多步 repo 任务」。
> S3 reference task 回答「主 Agent 能否借助 MCP+SubAgent 完成同类任务而不失控」。
> S4 reference task 回答「**这些受控工作能否被忠实复放与验证**——在不泄露 secret 的前提下，
> 从 evidence 重建 agent 做了什么，并校验这条重建链是完整且自洽的」。

S4 reference task = **audit/replay reference task**：一条 governed task（含 MCP tool + read-only
SubAgent 委派）在 fake/local 确定性下完成 **「执行 → 记录 → 复放 → 校验」** 闭环。

## 1. Fidelity ceiling（redacted-faithful，冻结）

冻结口径（`S4_GOAL.md §8-2`）：保真目标 = **redacted-faithful replay**——能忠实复放 governed
chain / decision chain / tool chain / extension chain；**不**追求 byte-for-byte raw
persistence、**不**保存 secret、**不**要求保存全部原始 payload。

据此，本契约把「保真」精确化为四条硬边界：

1. **可复放（replayable）**：仅凭 evidence（不访问原始 model request/response body、不访问
   raw tool payload）即可重建一条 governed task 的 **有序决策/工具/委派链路**，回答「agent 按
   什么顺序、对什么对象、做了什么、得到什么结果」。
2. **redacted**：更高保真 **绝不**以泄露 secret 为代价。**S4 replay-chain 投影**（G02/G03 的
   `input_preview`/`output_preview`）在持久化前强制 redaction（mask + 截断），raw API key /
   secret / 完整凭证 **绝不**进入该 chain/evidence（G03 测试断言）。
   > 范围注记（whole-stage audit）：该 redaction 硬边界作用于 **S4 新增高保真面（replay chain）**。
   > legacy 投影（mediator TOOL_RESULT 的 `tool_output` 预览、`record_evidence` metadata）依赖既有
   > 上游 `mask_user_visible_secrets`（failed/rejected 路径），未额外接入 `redact_text`——与既有
   > 非 pending 路径 parity。将 redaction 拓宽到这些 legacy 路径见 TECH_DEBT TD-012（非 S4 blocker）。
3. **非逐字（not byte-for-byte）**：投影粒度是 **safe-summary**（名称 + 截断/脱敏的 input
   preview + 截断/脱敏的 output preview + status + policy 结果），不是原始字节。这是 TD-001
   的「保真提升」边界，不是「全量持久化」。
4. **key-safe**：所有 evidence 本地；real provider 路径 opt-in、默认 skip（沿用 S3 模式），
   不读/打印/复制/移动/提交 key/config/.env。

## 2. 关键架构事实（baseline → 契约的依据）

> 这是 G01 调研得到的事实，G02/G05 实现必须以之为准，不得凭空发明数据源。

**replay 所需的数据在 S3 末已基本存在于 task-state**（`agent/state.py:TaskState`）：

- `tool_execution_log: dict[tool_use_id → {tool, input, result, status, step_index, error_type}]`
  —— 工具链（含 input/result，已是 model-visible 路径的脱敏投影）。
- `delegation_log: list[{delegation_id, subagent_name, status, stop_reason, execution_mode,
  adjudication_action, confidence, tools_executed, tools_denied}]` —— SubAgent 委派链
  （S3-G05 安全投影，JSON-safe）。
- `current_plan / current_step_index / status / tool_call_count / pending_tool` —— 决策/推进态。
- `agent/transitions.py` 的 `TransitionEvent` —— governed 状态推进事件（plan/step/tool/...）。

**当前的保真缺口（TD-001 本质）**：`agent/task_evidence_report.py:TaskEvidenceReport.evidence_events`
把这些数据 **降维成不透明字符串标签**（如 `"tools.executed:3"`、`"extensions.delegations:1"`），
丢失了「哪条 tool、什么 input/output preview、按什么顺序、与哪条委派关联」的可重建链路。
evidence recorder（`agent/evidence_recorder.py:record_evidence`）也以 `content_persisted=False`
只记 metadata/summary。

**结论**：G02 不需要新采集数据，而是 **在既有 evidence seam 上把 tool_execution_log +
delegation_log + transitions 投影为一条统一的、有序的、可校验的 replay chain（safe-summary
粒度）**，并强制 redaction（G03）。不新增第二条主链路、不重写 spine（`S4_GOAL.md §5 L1`）。

## 3. Replay chain 契约（G02 实现目标）

> 字段形状由 G02 在 `agent/` 下定义（建议模块名 `task_replay_chain.py`，dataclass frozen）。
> 本节规定 **契约口径**，不规定内部实现。

一条 replay chain 是一个 **有序的 governed 事件序列**，每个事件（`ReplayEvent`）至少含：

| 字段 | 含义 | 来源 |
|---|---|---|
| `seq` | 全局单调递增序号（chain 内顺序） | 投影时分配 |
| `kind` | `decision` / `tool` / `delegation` | 来源类型 |
| `step_index` | 所属 plan step | task state |
| `ref_id` | `tool_use_id`（tool）/ `delegation_id`（delegation）/ 决策锚 | 来源 |
| `name` | tool 名 / subagent 名 / 决策类型 | 来源 |
| `status` | executed / failed / rejected_by_check / blocked_by_policy / delegated / adjudicated | 来源 |
| `input_preview` | **redacted + 截断** 的 input safe-summary（tool 才有） | G03 redaction |
| `output_preview` | **redacted + 截断** 的 output safe-summary（tool 才有） | G03 redaction |
| `policy_outcome` | allow / reject / adjudicate_action | 来源 |

**Replay chain 的投影规则（G02 必须满足）**：

- **有序**：按 governed 发生顺序（decision → tool/delegation → outcome）排列；`seq` 单调。
- **可重建**：仅凭 chain 即可回答「agent 在 step N 调了哪条 tool、得到什么 status、是否触发
  SubAgent 委派、委派如何 adjudicate」。
- **redacted**：`input_preview` / `output_preview` 在持久化前经 G03 redaction；测试断言注入的
  fake secret 不出现在 chain/evidence 中（AC-3）。
- **不新增数据源**：只投影 §2 列出的既有 task-state 字段；不要求 raw model body、不要求
  pending-tool 之外的旁路。

> 保真天花板（whole-stage audit 注记，非缺陷）：(a) 步内（同 `step_index`）事件按 `ref_id`
> 排序而非执行时序——`tool_execution_log` 是插入序 dict 无时间戳，chain 不发明缺失数据；
> (b) delegation 的 `input_preview` 为空、`output_preview` 投影 `stop_reason`——`delegation_log`
> 无 query 字段。两者受「不新增数据源」边界约束，是 redacted-faithful 的已知结构限，非逐字复放。

## 4. Pending-tool 预览契约（G04 / TD-004）

`execute_pending_tool`（`agent/tool_executor.py:618`）已把 result 存入
`tool_execution_log[tool_use_id]`，但 **event-log 预览路径** 可能呈现空 `tool_output`（TD-004）。
G04 契约：pending-tool 确认执行后，**事件日志（events.jsonl 投影）必须呈现非空、redacted 的
tool_output 预览**（与 `execute_single_tool` 路径一致，redaction 复用 G03）。只补 evidence 预览，
不改 tool 执行语义。

## 5. Evidence 校验契约（G05 实现目标）

> 校验器（建议 `agent/task_evidence_verifier.py`）输入 evidence（含 replay chain）→ 输出校验
> 报告。本节规定 **通过判据**，不规定内部实现。

一条 evidence 通过校验（`verify == ok`）当且仅当 **全部** 成立：

1. **完整（complete）**：run 期间产生的每个 `tool_use_id` / `delegation_id` 都在 chain 中；
   无缺失（missing ref → fail，reason=`chain_incomplete`）。
2. **自洽（self-consistent）**：chain 中 tool 的 attempted/executed/blocked/failed 计数与
   `TaskEvidenceReport` 的对应计数一致；delegation 计数与 `delegation_log` 长度一致
   （不一致 → fail，reason=`count_mismatch`）。
3. **有序（ordered）**：`seq` 单调递增；同一 step 内 decision 早于其 tool/delegation
   （乱序 → fail，reason=`sequence_disorder`）。
4. **可复放（replayable）**：仅凭 chain 可重导出 governed path 摘要（决策 → 工具 → 委派 → 结果）
   （不可重导 → fail，reason=`not_replayable`）。

校验器必须能 **检出** 残缺（删一条 tool entry）/ 篡改（改 status 与计数矛盾）/ 乱序样本，并
给出对应 reason。通过校验的 evidence 才算「可验证」（AC-5）。

## 6. Audit/Replay reference task runbook（G06/G07 实现锚点）

闭环映射到 S2 governed task skeleton，在 `execute` 阶段组合 MCP tool + SubAgent 委派，并在
`done` 后追加 **replay + verify** 两步（这是 S4 相对 S3 的新增闭环）：

| 阶段 | 动作 | S4 维度 |
|---|---|---|
| receive | 主 Agent 接收 audit/replay 子任务 | — |
| plan | plan 确认：含「读证据 / 取 second opinion / adjudicate / 报告」步骤 | 引用受控 MCP tool + read-only SubAgent |
| execute-1 | 经受控 MCP tool source 读 fixture 证据（governed tool path） | MCP（S3 继承） |
| execute-2 | 委派 read-only SubAgent 做 second opinion | SubAgent（S3 继承） |
| execute-3 | 主 Agent adjudicate + 汇总 evidence | extension evidence（S3 继承） |
| record | 投影 **replay chain**（§3）+ redaction（G03） | **G02/G03** |
| checkpoint/resume | state（含 tool_execution_log/delegation_log）不丢 | S3 继承 |
| **replay** | 仅凭 evidence 重建 governed chain | **G02** |
| **verify** | evidence verifier（§5）通过；redaction 断言成立 | **G05/G03** |
| advance/done | lifecycle DONE、progress 100% | — |
| gate | acceptance gate 分类（evidence-fidelity 不被混入 debt） | G08 |

### Targeted Gate（G06 实现锚点）

```bash
.venv/bin/python -m pytest tests/test_s4_reference_task_acceptance.py -q
```

### Fake deterministic success criteria（AC-2 / AC-3 / AC-5 / AC-6-fake）

G06 的 fake/local E2E 必须断言（具体断言在 G06 落地，此处为可验收口径）：

1. **replay-faithful（AC-2）**：仅凭 evidence 重建一条含 MCP tool + SubAgent 委派的有序
   replay chain；超出当前「`tools.executed:N`」标签级。
2. **secret-safe（AC-3）**：注入的 fake secret 不出现在 chain/evidence；redaction 有断言。
3. **verifiable（AC-5）**：verifier 对完整 evidence 通过、对残缺/篡改/乱序样本失败。
4. **闭环完成（AC-6-fake）**：execute → record → replay → verify 全过；lifecycle DONE、
   progress 100%。
5. **S2/S3 不回归（AC-1）**：S2 + S3 targeted gate 仍通过。
6. **pending-tool 预览（AC-4）**：若 reference task 触发 pending-tool 路径，其 event 预览非空、
   redacted（否则由 G04 独立测试覆盖）。

### Real provider key-path smoke（AC-6-real，G07 实现）

opt-in、key-safe（沿用 S3 `_real_provider_env_ready()` 模式）：

```bash
MY_FIRST_AGENT_RUN_S4_REAL_PROVIDER_SMOKE=1 \
.venv/bin/python -m pytest \
  tests/test_s4_reference_task_acceptance.py::<s4_real_smoke_node> -q
```

real provider 须证明：进入 audit/replay governed path（与 fake 同一入口，非旁路）；evidence
可复放/校验且与 fake 链路对齐；key-safe（opt-in、默认 skip、fake-key 检测、不读/打印/复制/
移动/提交 secret、不改 ignored config、不创建 `.env`；MCP/SubAgent 仍用 fake/fixture source）。
**real-key 实跑非必需、非 release blocker**（`S4_GOAL_GAP.md` G07）——harness 就位 + 结构校验
即满足 AC-6 real 维度。

## 7. Non-goals / boundaries

- 不做 byte-for-byte 全量持久化（`S4_GOAL.md §7`）；本契约粒度是 redacted safe-summary。
- 不持久化 raw secret / API key / 完整凭证；redaction 是硬边界（G03）。
- 不新增第二条主链路、不重写 spine；G02 只在既有 evidence seam 投影。
- 不做密码学防篡改签名（除非未来 goal 授权）；G05 是结构化一致性校验，不是密码学保证。
- 不连真实 MCP endpoint / 不做 server reachability check；fake-first、local-only、fixture-based。
- 不激活 memory / 不做 durable ledger（TD-011）/ 不做 Scheduler/MCP/multi-agent 生态。
- 不修改 `config/config.yaml` 或创建 `.env`；不读/打印/移动/提交 secret。
