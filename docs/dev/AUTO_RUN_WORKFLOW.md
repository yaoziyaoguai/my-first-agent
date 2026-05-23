# First Agent Auto-Run Workflow

Status: active
Date: 2026-05-24

## A. 目标

First Agent auto-run workflow 的目标是：

- 从 roadmap queue 自动选择 safe-to-auto-run capability
- 对每个 capability 执行完整工程 loop（SPEC → TDD → Implementation → Review → Commit → Push）
- 单个 capability blocked 时不停止整个 workflow，记录为 deferred 后继续下一个
- 只有整个 queue 没有安全任务或触发真正全局 stop condition 才停

## B. 事实源

本 workflow 必须读取并遵守以下文档：

1. [ENGINEERING_WORKFLOW.md](ENGINEERING_WORKFLOW.md) — 工程流程纪律：SDD → TDD → Implementation → Review → Debug 的迭代 loop、review gate、回退规则、重试上限、升级条件、禁止模式
2. [Unified Runtime Flow Contract](../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md) — 项目宪法：runtime architecture、branch points、classification rules、capability milestones
3. [First Agent Subsystem Integration Roadmap](../plans/first-agent-subsystem-integration-roadmap.md) — 子系统/介入点清单、evidence matrix、backlog 分类、自动执行队列

## C. 自动执行 Loop

每个 safe-to-auto-run capability 必须按以下流程执行，不可跳过任何 gate：

```text
SPEC
  → SPEC Review (gate)
    → TDD / Test Plan
      → TDD Review (gate)
        → Implementation Plan
          → Plan Review (gate)
            → Implementation
              → Self-review / Debug
                → Verification Gates (test pass, diff clean, build pass)
                  → Commit
                    → Independent Audit (gate)
                      → PASS → push
```

低风险改动（docs-only、typo、单文件小修）可跳过前半段，从 Implementation 或 Gate 直接进入。跳过不是绕过工程纪律——仍须满足对应 gate（git diff --check、test pass、exit code = 0）。

## D. 单个 Capability Stop Condition

如果当前 capability 触发以下任一条件，该 capability **deferred**，不停止整个 workflow：

- 需要新增 branch point（不在 Unified Runtime Flow Contract 中已定义的 branch point）
- 需要新增 runtime flow
- 需要真实 API / .env / secret
- 需要连接真实外部服务
- 需要处理真实私人资料
- 需要用户产品/架构/安全决策
- FAIL / BLOCKED / P0 / P1 级别问题
- 同一问题在同一阶段已修 2 次仍未通过 gate（触发升级条件）
- 发现架构分歧
- 需要新增 capability milestone（而非已有 branch point 下的 branch behavior）

deferred 后检查 queue 中是否还有其他 safe-to-auto-run capability，有则继续下一个。

## E. 全局 Stop Condition

只有以下情况才能停止整个 auto-run：

| Stop condition | 说明 |
|---------------|------|
| queue 中没有 safe-to-auto-run capability | 所有候选或已完成、或 blocked、或 deferred |
| not main | 不在 main 分支 |
| behind origin/main | 本地落后远程 |
| working tree dirty 且不属于当前 loop | 有未提交改动且不是当前 capability 产生的 |
| HEAD has tag | HEAD 已有 tag |
| 连续完成并 push 3 个 capability loops | ~~达到单次 auto-run 上限~~ **不再是 stop condition** — 完成一批后必须继续 discovery 找下一个 safe candidate |
| focused fix 超过 retry limit 且无其他安全任务 | 当前能力卡住且无可替代任务 |
| 所有剩余任务都需要用户决策 | 无人可做的 task |

## F. 选择下一个 Capability 的规则

优先选择顺序（从高到低）：

1. 仓库证据明确 — 已有 handler、spec、test 文件可引用
2. 已有 branch point 下的 branch behavior — 不新增架构元素
3. L1/L2/L3 evidence 缺口 — 优先补齐 correctness/safety 缺口
4. correctness / safety focused fix — 修复已知缺陷
5. error-path hardening — 加固已有错误处理路径
6. 不需要 secret / API / 外部服务 / 私人资料
7. 不新增 runtime flow

选择来源：[First Agent Subsystem Integration Roadmap](../plans/first-agent-subsystem-integration-roadmap.md) Section F（自动执行队列）和 Section D（Backlog 分类）。

roadmap 中标记为 `✅ 是` 的为 safe-to-auto-run。标记为 `⚠️` 的需先评估当前状态再决定。

## G. 禁止事项

以下行为在 auto-run 中严格禁止：

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

## H. 输出格式

每次 auto-run 结束（无论正常停止还是触发 stop condition），必须输出：

```text
## Auto-Run Report — YYYY-MM-DD

### Completed Loops
- [capability name]: [commit hash] — [one-line summary]

### Deferred Items
- [capability name]: [reason] — [下一步建议]

### Commits
- [hash]: [message]

### Pushes
- [branch]: [commits pushed]

### Gates
- SPEC Review: [PASS/FAIL/SKIPPED]
- TDD Review: [PASS/FAIL/SKIPPED]
- Plan Review: [PASS/FAIL/SKIPPED]
- Implementation Audit: [PASS/FAIL/SKIPPED]
- Verification: [test results]
- Independent Audit: [PASS/FAIL]

### Final Repo Status
- branch: [current]
- ahead/behind: [count]
- working tree: [clean/dirty]
- HEAD: [hash]

### Tomorrow Morning Review List
- [ ] [item 1]
- [ ] [item 2]
```

## 参考

- [ENGINEERING_WORKFLOW.md](ENGINEERING_WORKFLOW.md)
- [Unified Runtime Flow Contract](../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)
- [First Agent Subsystem Integration Roadmap](../plans/first-agent-subsystem-integration-roadmap.md)
