# /project:auto-run

First Agent 自动执行命令。按 roadmap queue 选择 safe-to-auto-run capability，执行完整工程 loop，blocked capability deferred 后继续下一个。

## 事实源

执行前必须读取：

- [AUTO_RUN_WORKFLOW.md](../../docs/dev/AUTO_RUN_WORKFLOW.md) — 本命令的 workflow 定义
- [ENGINEERING_WORKFLOW.md](../../docs/dev/ENGINEERING_WORKFLOW.md) — 工程流程纪律
- [UNIFIED_RUNTIME_FLOW_CONTRACT.md](../../docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md) — 项目宪法
- [first-agent-subsystem-integration-roadmap.md](../../docs/plans/first-agent-subsystem-integration-roadmap.md) — roadmap queue

## 执行规则

### Phase 0: 状态检查

```bash
git status -sb
git branch --show-current
git log --oneline -5
git rev-list --left-right --count origin/main...HEAD
git tag --points-at HEAD
```

**Stop if:** not main / working tree dirty (非当前 loop) / behind > 0 / ahead > 0 (非当前 loop) / HEAD has tag.

如果不是 main，停止。如果 behind 不为 0，停止。如果 ahead 不为 0 且不属于当前 loop 的 commit，停止。

### Phase 1: Queue 读取

从 `docs/plans/first-agent-subsystem-integration-roadmap.md` Section F 读取自动执行队列。
从 Section D 读取 Backlog 分类。
从 Section C 读取 Evidence Matrix。

### Phase 2: Capability 选择

按 AUTO_RUN_WORKFLOW.md Section F 的优先级规则选择下一个 safe-to-auto-run capability。

roadmap 中标记 `✅ 是` 的优先。标记 `⚠️` 的先评估当前状态再决定。

已完成的 capability（通过 git log 确认相关 commit 存在）跳过。

### Phase 3: 完整工程 Loop

对选中的 capability 执行：

```
SPEC → SPEC Review → TDD → TDD Review → Implementation Plan → Plan Review → Implementation → Self-review / Debug → Verification Gates → Commit → Independent Audit → PASS → push
```

**不得停在 SPEC / TDD / Plan / Implementation / Audit 中间。**
**audit PASS 后必须 push。**
**blocked capability 要 deferred，然后继续下一个。**

### Phase 4: Deferred 处理

当前 capability 触发 AUTO_RUN_WORKFLOW.md Section D 的 stop condition 时：

1. 记录 capability 名称、deferred 原因、下一步建议
2. 检查 queue 中是否还有 safe-to-auto-run capability
3. 有则回到 Phase 2 继续下一个
4. 没有则进入 Phase 5

### Phase 5: 全局 Stop

触发 AUTO_RUN_WORKFLOW.md Section E 的全局 stop condition 时停止。

**注意：完成 3 个 loops 不是 stop condition。** 完成一批 loops 后必须继续 discovery 找下一个 safe-to-auto-run candidate。只有真正全局 stop condition（not main / behind origin / HEAD has tag / queue 中没有任何 safe candidate / 所有剩余候选都需要用户决策）才停。

### Phase 6: 输出报告

按 AUTO_RUN_WORKFLOW.md Section H 格式输出完整报告。

## 必须遵守的禁止事项

- 不新增 Anchor
- 不新增无界 branch point
- 不新增 runtime flow
- 不新增 fake loop / fake dispatcher / dogfood-only path
- 不让 direct handler / dispatcher / adapter call 冒充 L3
- 不让 fake/real 变两套主流程
- 不读取 .env
- 不读取真实 sessions/runs
- 不读取 memory/episodes/*.jsonl
- 不连接真实外部服务
- 不调用真实 API
- 不处理真实私人资料
- 不 tag
- 不 release
- 不 force push
- 不 rebase
- 不 amend

## 工作方式

直接执行。不等待用户确认。不询问"是否继续"。blocked 就 deferred 然后继续下一个。只有全局 stop condition 才停。
