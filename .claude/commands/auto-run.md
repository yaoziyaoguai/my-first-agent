# /auto-run

First Agent 工程技能调度器。基于当前项目状态和任务类型，自动选择技能体系（Superpowers / Compound Engineering / G-Stack / plan-eng-review / review），执行工程 loop，自动记录进度。

---

## Startup

每次 `/auto-run` 启动**必须先读**：

1. `docs/PROJECT_STATUS.md` — 当前状态、已知 issues、约束、推荐下一步
2. `docs/PROGRESS_LEDGER.md` — 进度历史、已修复 bugs、P3 积压
3. `docs/dev/AUTO_RUN_WORKFLOW.md` — 详细 workflow、loop 类型、gate 规则
4. 当前任务相关的最新 report/plan（如有）

**冲突规则**：如果旧文档与 PROJECT_STATUS.md 冲突，以 PROJECT_STATUS.md 为准。`docs/archive/` 只能作为历史参考，不能作为当前指令。如果发现 PROJECT_STATUS.md 已过期，先更新它。

---

## Skill Routing Policy

`/auto-run` 不只是"自动执行命令"——它是**工程技能调度器**。每次启动必须根据任务类型自动选择最合适的技能体系，而不是机械地按文档 loop 执行。

### 可用技能体系

| 技能体系 | 定位 | 核心价值 |
|---------|------|---------|
| **Superpowers** | 质量纪律 | TDD、debug root cause、verification-before-completion、不允许未验证就声称完成 |
| **Compound Engineering** | 工程执行 | 多文件修复、P0/P1 remediation、evidence → test → fix → gate → docs → commit/push 连续 big loop |
| **G-Stack** | 审计与分类 | 全局能力审计、架构分层审计、L1/L2/L3 evidence taxonomy、系统性分析 |
| **plan-eng-review** | 设计审核 | 大计划落地前复审、SDD/plan 审核、架构变更前评估 |
| **review** | 独立复审 | commit 后独立复审、检查 overclaim、判断是否真的解决问题 |

### 技能选择原则

1. **不盲选**：根据任务类型和当前项目状态选择，不是"所有任务都用所有技能"
2. **不跳级**：需要 quality gate 时用 Superpowers，需要系统分析时用 G-Stack，需要审核时用 plan-eng-review
3. **不把技能当 stop condition**：完成一个技能阶段不是停止条件，只有 hard stop 才停
4. **不跨技能混用**：同一任务阶段的 primary skill 明确后，secondary skill 只在必要时补充

---

## Decide Task Type

根据用户输入和当前状态判断任务类型：

| 类型 | 触发条件 |
|------|---------|
| `audit_only` | 用户要求审计 / 只读评估 / 能力评分 |
| `remediation_loop` | 按 remediation plan 执行 P0/P1/P2 loop |
| `bug_fix` | 用户指出 bug / 已有 bug report / traceback |
| `debug_root_cause` | 需要深挖根因而非修症状 |
| `architecture_change` | 需要新增 branch point / 架构决策 / 设计变更 |
| `evidence_honesty` | 需要区分证据等级、修正 overclaim |
| `dogfood` | 用户要求跑 dogfood / 已有 dogfood plan |
| `docs_cleanup` | 用户要求清理文档 / 发现过期文档冲突 |
| `config_safety` | 配置相关安全风险 / secret 治理 |
| `ux_polish` | 用户要求改进 UX / wording / layout |
| `implementation` | 明确的 feature 实现 / 有 SPEC/plan 的代码变更 |
| `post_loop_review` | loop 完成后的独立复审 / overclaim 检查 |

如果用户只说"继续"且 PROJECT_STATUS.md 有 next recommended loop，按推荐走。

---

## Skill Router Decision Table

| Task Type | Primary Skill | Secondary Skill | Start Point | Stop Condition | Required Output |
|-----------|--------------|----------------|-------------|----------------|-----------------|
| `remediation_loop` | Compound Engineering | Superpowers verification | audit finding / remediation plan | hard stop only | fix + report + next loop |
| `bug_fix` | Superpowers debug / TDD | Compound Engineering | evidence / failing test | hard stop only | fix + test + gate + status update |
| `debug_root_cause` | Superpowers debug | G-Stack evidence classification | traceback / log / checkpoint | root cause found OR hard stop | root cause report + fix plan |
| `implementation` | Compound Engineering | Superpowers verification | SPEC / plan / design doc | hard stop only | code + tests + gate + docs + commit |
| `audit_only` | G-Stack | plan-eng-review | current status + evidence | audit report complete | severity table + next loops |
| `evidence_honesty` | G-Stack | Superpowers verification | dogfood/report/test evidence | hard stop only | reclassification + guard tests |
| `architecture_change` | plan-eng-review | Compound Engineering | design doc | user decision if branch point changes | design + review + tests |
| `dogfood` | Compound Engineering | G-Stack evidence classification | case matrix | hard stop only | case results + issue table + next loop |
| `docs_cleanup` | Compound Engineering | G-Stack doc inventory | inventory scan | hard stop only | rewritten docs + guard tests |
| `config_safety` | Compound Engineering | Superpowers verification | config contract / guard test | hard stop only | fix + guard tests + status update |
| `ux_polish` | Compound Engineering | Superpowers smoke test | user path check | hard stop only | fix + smoke + status update |
| `post_loop_review` | review | G-Stack overclaim check | completed loop diff + gates | review complete → continue next | review findings + next loop decision |

---

## When to Use Each Skill

### Superpowers

用于：
- TDD（写测试先于实现）
- debug root cause（不修症状）
- verification-before-completion（不允许未验证就声称完成）
- 防止"看起来完成但没验证"

规则：
- 每个 `bug_fix` / `remediation_loop` 默认使用 Superpowers 的 verification-before-completion 思路
- final output 前必须核验证据（test pass、gate exit code、实际输出），而不是只相信命令输出片段
- 如果测试失败，区分"测试错了"和"实现错了"——不要为了让测试通过而改测试

### Compound Engineering

用于：
- 多文件工程修复
- P0/P1 remediation
- 需要同时改代码、测试、文档、gate 的任务
- 连续 big loop

规则：
- `remediation_loop` / `implementation` 默认使用 Compound Engineering 思路
- 必须拆成：evidence → test → fix → gate → docs/status → commit/push
- 如果没有 hard stop，继续 next loop
- 不跳过中间步骤——不能从 evidence 直接跳到 commit

### G-Stack

用于：
- 全局能力审计
- 架构分层审计
- 证据层级审计（L1/L2/L3 evidence taxonomy）
- "为什么分数低"这类系统性分析
- 文档 inventory 和分类

规则：
- `audit_only` / `evidence_honesty` / 架构质量分析默认使用 G-Stack 思路
- 必须区分 docs / guard / fake / real / user path 证据等级
- 不允许把 admin completed 当 capability completed
- 不允许把 dispatch path verified 当 L3 complete
- 不允许把 trace event emission 当 RuntimeActionDispatcher L3

### plan-eng-review

用于：
- 大计划落地前复审
- SDD/plan 审核
- 架构变更前评估
- remediation plan 审核

规则：
- `architecture_change` / 大型 remediation plan 必须先 plan-eng-review
- 如果只是已有审计报告里的明确 P0/P1，不重新规划，直接执行
- plan-eng-review 输出的是设计决策，不是执行指令——执行仍由 Compound Engineering 负责

### review

用于：
- commit 后独立复审
- 大 loop 完成后检查 overclaim
- 判断是否真的解决问题

规则：
- 每个 big loop 完成后，如果 context 足够，必须做 post-loop review
- review 检查：本轮 target 是否达成？是否有 scope creep？是否有 overclaim？
- **review 不是停止点**——review 后如果有 next loop 且无 hard stop，应继续

---

## Choose Loop Start Point

**不要每次从头开始。** 根据已有证据选择最近入口：

| 情况 | 起点 |
|------|------|
| 已有 bug report / traceback / log | reproduce → failing test → fix |
| 已有 dogfood report | report issues → 逐条处理 |
| docs cleanup | inventory → classify → rewrite/archive → guard tests |
| config fix | diagnostics evidence → minimal fix → smoke |
| audit only | 只读，不改代码，出报告 |
| 已有 plan/report 且与任务直接相关 | 从最靠近问题的阶段开始 |
| 无任何证据 | 从 discovery/inventory 开始 |

完整 loop 规范（Normal / Architecture Extension）见 AUTO_RUN_WORKFLOW.md Section C。低风险改动可跳过前半段直接进入 Implementation。

---

## Run Loop

### bug_fix / debug_root_cause（Superpowers primary）
- 读 evidence（report / traceback / log / checkpoint）
- reproduce 问题
- **根因分析优先于修症状**（Superpowers debug root cause）
- 写回归测试（如需要）
- minimal fix — 不顺手重构不相关代码
- 跑 affected gates
- 核验修复证据（verification-before-completion）
- 更新 report/status/ledger

### remediation_loop / implementation（Compound Engineering primary）
- evidence → test → fix → gate → docs/status → commit/push
- 不跳过中间步骤
- 每个 loop 完成后执行 post-loop self-review
- 如果没有 hard stop，自动继续下一个 loop

### dogfood（Compound Engineering primary + G-Stack classification）
- 读 dogfood plan/report
- 跑 cases — **不在单个 case 失败时停止**
- 记录 issues（区分 P0/P1/P2/P3）
- 用 G-Stack evidence taxonomy 分类结果（REAL_DOGFOOD_SMOKE / FAKE_LOCAL_SMOKE / etc.）
- 可选 safe-fix P0/P1/P2（不涉及真实 API/secret/private data）
- 更新 dogfood report/ledger

### docs_cleanup（Compound Engineering primary + G-Stack inventory）
- 全量扫描 → 按 current/stale/archive/delete 分类
- 重写 source of truth
- 归档或删除过期文档
- 添加 guard tests
- 更新 ledger

### config_safety（Compound Engineering primary + Superpowers verification）
- 读 config contract/status
- 查看 diagnostics 证据
- minimal resolver/diagnostics fix
- guard tests + smoke test
- 不过度工程化

### audit_only（G-Stack primary）
- 只读 — 不改代码
- 输出审计报告（含 severity table + evidence classification）
- 如果审计发现明确的 P0/P1，输出 recommended next loops
- 除非用户明确要求，不进入修复

### evidence_honesty（G-Stack primary）
- 审计现有 tests/dogfood/report 中的证据声称
- 区分 L1（docs only）/ L2（guard tests）/ L3（dispatcher path）/ L4（real E2E）
- 修正 overclaim（如 probe 计为 capability、dispatch path 计为 complete）
- 添加 evidence taxonomy guard tests

### ux_polish（Compound Engineering primary + Superpowers smoke）
- 检查用户路径
- minimal wording/layout 改进
- smoke test
- 更新 status/ledger

### architecture_change（plan-eng-review primary + Compound Engineering implementation）
- 设计 doc → plan-eng-review → 用户确认 → Compound Engineering 执行
- 如果只是已有审计报告里的明确 P0/P1，不重新规划，直接用 Compound Engineering 执行
- design → review → tests → implementation → gates → status/ledger

### post_loop_review（review primary + G-Stack overclaim check）
- 检查：本轮 target 达成？scope creep？overclaim？
- **review 完成不是停止条件**——如有 next loop 且无 hard stop，继续

---

## Progress Rule

**每轮 `/auto-run` 结束必须更新至少一个**：

- `docs/PROGRESS_LEDGER.md`（milestones / issues）
- `docs/PROJECT_STATUS.md`（状态变化 / 指针更新）
- 当前 dogfood report
- 当前 remediation plan
- 当前 audit report

如果确实无需更新，final output 必须解释原因。

---

## Hard Stops

只在以下情况停止：

- secret 泄漏风险（real API key 即将被 commit）
- staged real API key（git diff --cached 包含真实 key）
- 需要读取/覆盖/删除用户真实 config/config.yaml
- 需要读取/使用真实 .env / sessions / runs / episodes / 私人资料
- 危险的 tool execution（rm -rf / force push main / 删库）
- 引入第二条 runtime flow / fake-real split
- 恢复 legacy provider/profile/env/request_path 为主路径
- 重大架构分支点改变（会改变项目根本方向，需用户确认）
- 需要用户重大产品决策（非技术选择，非已知授权范围内的决定）
- context 接近耗尽且已写 handoff resume instruction
- P0/P1 连续修复失败 ≥2 次（同一 loop 中同一问题）

以下**不是**停止条件：

- queue empty
- 单个 candidate blocked/deferred
- 需要架构设计
- 完成 3 个 loops
- **loop 成功完成**
- **commit/push 完成**
- **review 完成**
- **技能阶段完成**
- **post-loop self-review 完成**
- **选择/切换技能**
- **"next recommended loop" 输出**

**用户已授权真实 API dogfood 范围内的操作，不得在此范围内反复请求授权。**

---

## Continuation Policy

### 核心原则

1. **选择技能不是停止条件** — 选完技能后继续执行
2. **完成一个技能阶段不是停止条件** — 阶段完成后继续下一个阶段
3. **完成一个 loop 不是停止条件** — 自动继续下一个 pending loop
4. **commit/push 不是停止条件** — 自动继续下一个 pending loop
5. **review 完成不是停止条件** — review 后如有 next loop 且无 hard stop，继续
6. **只有 hard stop 才停** — 所有其他情况都继续
7. **如果技能输出了 next recommended loop，`/auto-run` 必须判断并继续**

### Post-Loop Self-Review

每个 loop 完成后：
- [ ] 本轮 target 是否达成？具体达成的证据是什么？
- [ ] 本次 changes 是否在 scope 内？有没有 scope creep？
- [ ] Gates 通过情况：具体哪些 pass/fail，哪些是已有的？
- [ ] 是否有新引入的 regression？（与基线对比）
- [ ] 技能选择是否正确？是否需要切换到其他技能？
- [ ] PROJECT_STATUS / PROGRESS_LEDGER / remediation plan 是否需要更新？
- [ ] 下一个 loop 是什么？是否被前置条件阻塞？
- [ ] 是否需要用户决策？（非技术选择、scope 外、超越已有授权）

### Next-Loop Selection

完成 self-review 后自动选择下一 loop：
1. 读 PROJECT_STATUS.md 的推荐下一步
2. 读 remediation plan 找到下一个 pending loop
3. 优先 P0 → P1 → P2（不跳级）
4. 如果当前 loop 的前置依赖未满足，选择其他不依赖的 loop
5. 如果所有剩余 loop 都 blocked，报告 blocked 原因并停止
6. 根据下一 loop 的任务类型，在 Skill Router Decision Table 中查表选择技能

---

## Forbidden Patterns

- 不恢复 provider profiles 为推荐路径
- 不让用户配置 `request_path` / `auth_scheme` / `api_key_env`
- 不过度工程化简单配置
- 不把 FakeProvider 做成 natural-language NLU
- 不把 archive docs 当当前指令
- 不跳过 progress 更新就结束
- 不 commit `config/config.yaml`（含真实 key）
- 不 commit `.env` / `agent_log.jsonl`
- 不在已有 evidence/report 时从零开始
- 不新增 Anchor / 第二条主流程 / fake-only path
- 不 tag / release / force push / rebase / amend
- **不盲选技能** — 每次必须根据任务类型查 Skill Router Decision Table
- **不把技能完成当停止条件** — 技能是工具，不是 stop signal

---

## Final Output

**Final report 是进度日志，不是停止信号。** 非 hard stop 时输出简短进度行即可，hard stop 时才输出完整报告。

### 非 hard stop（loop 完成，自动继续）

简短一行：

```text
## Loop N COMPLETED ([skill]: [primary]/[secondary]) — [hash] pushed → 自动继续 Loop N+1
```

### Hard stop（遇到真正停止条件）

```text
## /auto-run Report — YYYY-MM-DD

- Task type: [task_type]
- Skill routing: [primary skill] / [secondary skill]
- Loop start: [从哪里开始的]
- What changed: [具体改动]
- Gates: [exact commands + exit codes]
- Updated: [更新了哪些 docs/reports]
- Remaining: [未解决的问题]
- Next: [推荐下一个 loop]
- Commit: [hash] / Push: [yes/no]
- Stop reason: [具体命中哪条 hard stop]
- User action needed: [yes/no — 具体说明]
```
