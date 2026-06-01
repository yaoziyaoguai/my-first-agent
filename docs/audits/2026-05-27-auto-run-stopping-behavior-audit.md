# /auto-run 停止行为审计

**状态: historical — audit scope limited to auto-run workflow behavior。核心约束已整合到当前 `docs/dev/ENGINEERING_WORKFLOW.md` 和 `.claude/commands/auto-run.md`。**
日期：2026-05-27
审计员：Coding Agent（自审计）
范围：`.claude/commands/auto-run.md`、`docs/dev/AUTO_RUN_WORKFLOW.md`、`docs/PROJECT_STATUS.md`、`docs/plans/2026-05-27-capability-remediation-loop-plan.md`
模式：`audit_only` + `workflow_fix_plan`

---

## Executive Verdict

**/auto-run 每次都停的根本原因是 remediation plan 里写了"停止，等下一轮 /auto-run"。** 不是 workflow 定义缺规则，而是当前被执行的计划文件显式要求停止。同时 `auto-run.md` 的 "Final output" 报告模板暗示 termination，进一步强化了这个行为。

修复：**改 remediation plan 的 stop 指令 + 改 auto-run.md 加 explicit continuation policy。**

---

## 为什么 auto-run 老停

### 根因 #1（主因）：Remediation plan 显式要求停止

`docs/plans/2026-05-27-capability-remediation-loop-plan.md` Line 30-31:

```
→ 完成后更新 PROJECT_STATUS/PROGRESS_LEDGER/本 plan
→ 停止，等下一轮 /auto-run
```

Line 33:
```
`/auto-run` 不一次执行多个 loop。每个 loop 是独立的工作单元。
```

Coding Agent 被训�为执行计划原文。此处的 "停止" 是计划给的直接指令，不是 Agent 自创的。

### 根因 #2：auto-run.md 的 "Final output" 模板暗示 termination

`auto-run.md` Line 138-154 的 Final output 模板以 markdown 报告结束，没有 "如果无 hard stop 则继续" 的后置指令。Coding Agent 在输出报告后自然停止。

### 根因 #3：缺少显式的 Continuation Policy

`auto-run.md` Line 122 说 "以下不是停止条件：queue empty...完成 3 个 loops".

`AUTO_RUN_WORKFLOW.md` Section E Line 169 也说 "完成 3 个 loops（继续 discovery 找下一个）".

这两条确实定义了 "not a stop condition"，但它们主要覆盖的是 **loop 失败/scoped context** 场景，没有覆盖 **loop 成功完成** 场景。`完成 3 个 loops` 这句话的意思是 "不要因为做了 3 个就停"，但它没有说 "完成 1 个 loop 后不要因为'完成了'就停"。

### 根因 #4：缺少 Post-Loop Self-Review 指令

当前 workflow 没有要求 agent 在每个 loop 完成后执行自审并基于自审结果决定下一步。agent 完成 loop 后就进入 "输出报告" 模式。

---

## 哪些规则缺失

| # | 缺失规则 | 影响 |
|---|---------|------|
| 1 | **Continuation policy**：loop 完成后若无 hard stop 应自动进入下一 loop | 每次都停 |
| 2 | **Post-loop self-review**：完成 loop 后必须自审结果、确认 gates、更新 status、判断是否继续 | agent 不知道 loop 结束不等于任务结束 |
| 3 | **Next-loop selection rule**：根据 PROJECT_STATUS 和 remediation plan 自动选择下一 loop 而非等待用户 | 停下来等用户 |
| 4 | **"Give direction then continue" rule**：给出下一步方向不等于停止 | agent 给出 next recommended loop 后停在原地 |
| 5 | **真实 API 授权状态声明**：明确用户已授权的范围，不要重复问 | agent 反复请求授权 |

---

## 哪些规则写了但没有约束力

| # | 规则 | 位置 | 为什么没约束力 |
|---|------|------|----------------|
| 1 | "完成 3 个 loops 不是停止条件" | auto-run.md:122 / WORKFLOW.md:169 | 覆盖了 "做了 3 个就停" 的场景，但没有覆盖"做了 1 个就停"的场景。Agent 在 1 个 loop 后就给了 final output，不会走到 3 个。 |
| 2 | "deferred 后继续下一个" | WORKFLOW.md Section D | 只覆盖 deferred（失败）场景，不覆盖 success（完成一个 loop）场景 |
| 3 | "global stop condition" | WORKFLOW.md Section E | 定义了什么算 hard stop，但没有定义 "not hard stop then continue" 的执行流程 |
| 4 | "Continue discovery" | WORKFLOW.md Section C | 只在 loop 图里出现，不是可执行指令 |

---

## Hard Stop 收窄方案

当前 auto-run.md 的 hard stop 列表（10 条）基本合理，但需要删去以下：

| 删除 | 原因 |
|------|------|
| ~~dirty repo 且改动不属于当前 loop~~ | 如果当前 loop 已经完成（commit/push 已做），repo 应该 clean。如果 dirty 是因为 loop 进行中 — 那说明 loop 没完成，不应该已经到了 "是否停止" 的检查点。已完成 loop 后的 dirty 只能属于下一个 loop 的初始状态（不常见）或者 untracked files（不阻止继续）。收窄为 "dirty staged changes 不属于当前或下一 loop"。 |

添加：

| 添加 | 原因 |
|------|------|
| 用户已授权真实 API，不得在此范围内反复请求授权 | 当前已授权 dogfood，不要每轮都问 |

最终收窄结果：

```
# Hard Stops（只在以下情况停止）
- secret 泄露风险（real API key 即将被 commit）
- staged real API key（git diff --cached 包含真实 key）
- 需要读取/覆盖/删除用户真实 config/config.yaml
- 需要读取/使用真实 .env / sessions / runs / episodes / 私人资料
- 危险的 tool execution（rm -rf / force push main / 删库）
- 引入第二条 runtime flow / fake-real split
- 恢复 legacy provider/profile/env/request_path 为主路径
- context 接近耗尽且已写 handoff resume instruction
- P0/P1 连续修复失败 ≥2 次（同一 loop 中同一问题）
- 需要用户重大产品决策（非技术选择，非已知授权范围内的决定）
```

---

## Continuation Policy 写法

在 auto-run.md 中新增 "Continuation Policy" 节：

```markdown
## Continuation Policy

每个 loop 完成后必须执行以下 self-review，而不是停下来：

1. 确认所有 gates 通过（或已知 failure 为 pre-existing 非本轮引入）
2. 确认 PROJECT_STATUS / PROGRESS_LEDGER / remediation plan 已更新
3. commit / push 已完成
4. 从 PROJECT_STATUS 找到下一个未完成的 loop
5. 检查 hard stop — 如果没有命中任何一条，**自动继续**下一个 loop

**给出下一步方向不等于停止**。Final report 是进度日志，不是停止信号。
只有 hard stop 才真正停止。hard stop 时才输出完整 final report。
```

---

## Post-Loop Self-Review 写法

```markdown
### Post-Loop Self-Review

每完成一个 loop：
- [ ] 本轮 target 是否达成？具体达成的证据是什么？
- [ ] 本次 changes 是否在 scope 内？有没有 scope creep？
- [ ] Gates 通过情况：具体哪些 pass/fail/timeout，哪些是已有的？
- [ ] 是否有新引入的 regression？（与基线对比）
- [ ] PROJECT_STATUS / PROGRESS_LEDGER / remediation plan 是否需要更新？
- [ ] 下一个 loop 是什么？是否被前置条件阻塞？
- [ ] 是否需要用户决策？（非技术选择、scope 外、超越已有授权）
```

---

## Next-Loop Selection 写法

```markdown
### Next-Loop Selection

完成 self-review 后自动选择下一 loop：
1. 读 PROJECT_STATUS.md 的推荐下一步
2. 读 remediation plan 找到下一个 pending loop
3. 优先 P0 → P1 → P2（不跳级）
4. 如果当前 loop 的前置依赖未满足，选择其他不依赖的 loop
5. 如果所有剩余 loop 都 blocked，报告 blocked 原因并停止
```

---

## 需要修改的文件

| 文件 | 修改内容 | 影响级别 |
|------|---------|---------|
| `.claude/commands/auto-run.md` | 新增 Continuation Policy + Post-Loop Self-Review + Next-Loop Selection；改 Final output 为 progress log（非 stop signal）；收窄 hard stop | **必须改** |
| `docs/plans/2026-05-27-capability-remediation-loop-plan.md` | 改 "停止，等下一轮 /auto-run" → "如果没有 hard stop，自动继续下一个 loop" | **必须改** |
| `docs/dev/AUTO_RUN_WORKFLOW.md` | Section C/H 微调强调 continuation；Section E 与 auto-run.md 对齐 | 建议改 |
| `docs/PROJECT_STATUS.md` | 新增 "Auto-run 授权状态"，明确真实 API 已授权、不要重复问 | 建议改 |
| `tests/test_docs_source_of_truth.py` | 新增 guard tests 验证 auto-run.md 包含关键规则 | 必须加 |

---

## 推荐最小修复方案

**Phase 1（最小必须）**：
1. 改 remediation plan：删 "停止" → 改 "继续"
2. 改 auto-run.md：新增 Continuation Policy 节 + Post-Loop Self-Review + Next-Loop Selection
3. 改 auto-run.md：Final output 标注为 "progress log (not stop signal)"
4. 收窄 hard stop 列表
5. 新增 guard tests

**Phase 2（加固）**：
6. 对齐 AUTO_RUN_WORKFLOW.md
7. PROJECT_STATUS.md 新增授权状态

---

## 是否可以自动修

**可以**。所有修改都是 workflow 文档和 plan 文档，不涉及业务代码、不涉及 runtime、不涉及 config/secret。完全在 `audit_only + workflow_fix_plan` 的授权范围内。

---

## 修复后的验收标准

1. auto-run.md 包含 explicit "loop completion is not a stop condition"
2. auto-run.md 包含 post-loop self-review checklist
3. auto-run.md 包含 next-loop continuation policy
4. auto-run.md 的 hard stop 列表收窄且排序
5. remediation plan 不再说 "停止"
6. guard tests 可验证上述规则存在
7. `ruff check` 通过
8. `git diff --check` 通过
9. commit/push 完成
