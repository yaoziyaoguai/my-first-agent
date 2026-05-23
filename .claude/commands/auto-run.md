# /project:auto-run

First Agent 自动执行命令。按 roadmap queue 选择 safe-to-auto-run capability，执行完整工程 loop，blocked capability deferred 后继续下一个。即使需要新增 branch point / RuntimeActionType / handler / catalog entry / 架构决策，也进入 Architecture Extension Loop 自行裁决。

## 事实源

执行前必须读取：

- [AUTO_RUN_WORKFLOW.md](../../docs/dev/AUTO_RUN_WORKFLOW.md) — 本命令的 workflow 定义
- [ENGINEERING_WORKFLOW.md](../../docs/dev/ENGINEERING_WORKFLOW.md) — 工程流程纪律
- [UNIFIED_RUNTIME_FLOW_CONTRACT.md](../../docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md) — 项目宪法
- [first-agent-subsystem-integration-roadmap.md](../../docs/plans/first-agent-subsystem-integration-roadmap.md) — roadmap queue

## 两种自动执行 Loop

### Normal Capability Loop

用于已有 branch point / existing intervention point 下的 branch behavior：

```
SPEC → SPEC Review → TDD → TDD Review → Implementation Plan → Plan Review →
Implementation → Self-review / Debug → Verification Gates → Commit →
Independent Audit → PASS → push → Continue discovery
```

### Architecture Extension Loop

用于现有 branch point 不足以承载，但仍符合统一主流程的大方向时：

```
Discovery → Architecture Decision / SPEC → Architecture Review → TDD →
TDD Review → Implementation Plan → Plan Review → Implementation →
Self-review / Debug → Verification Gates → Commit → Independent Audit →
PASS → push → Continue discovery
```

**Architecture Extension Loop 约束：**
- 新 branch point 必须有限稳定、明确可测试、可审计
- 必须说明为什么现有 branch point 不能承载
- 必须说明它挂在统一主流程的哪个阶段
- 必须有 L1/L2/L3 evidence plan
- 必须有 stop condition 和 rollback/deferred plan
- 必须有中文学习型注释/docstring
- 不改变项目根本方向、不新增 Anchor、不新增第二条主流程

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

### Phase 1: Queue 读取 + Discovery

从 `docs/plans/first-agent-subsystem-integration-roadmap.md` 读取自动执行队列、Backlog 分类、Evidence Matrix。

做 repository discovery 找到下一个 candidate。

### Phase 2: Capability 选择 + Loop 类型判定

按 AUTO_RUN_WORKFLOW.md Section F 的优先级规则选择。

**判定规则：**
- 如果现有 branch point 能承载 → Normal Capability Loop
- 如果需要新增 branch point / RuntimeActionType / handler / catalog entry → Architecture Extension Loop
- 如果需要架构设计但不涉及真实 secret/API/private data → Architecture Extension Loop
- 如果需要真实 secret/API/private data → **deferred**（不停止 workflow）

### Phase 3: 执行 Loop

**不得停在 SPEC / Architecture Decision / TDD / Plan / Implementation / Audit 中间。**
**audit PASS 后必须 push。**
**push 后继续 discovery。**

### Phase 4: Gates

每个 capability 完成后运行：

```bash
git diff --stat && git diff --name-only && git diff --check
.venv/bin/ruff check agent tests scripts
HOME=/private/tmp/... .venv/bin/python -m pytest tests/runtime_integration -q
```

### Phase 5: Issue Handling

- P2/P3: focused fix → re-audit → 最多 2 次 → PASS → push
- P1: 回退到 Architecture Decision / SPEC / TDD / Plan → 修正 → 继续
- P1 无法修复: **stop**（全局 stop condition）
- P0: **stop**（全局 stop condition）

### Phase 6: 全局 Stop

**真正全局 stop condition（只有这些能停）：**

1. Repo 不安全: not main / behind origin / HEAD has tag / working tree dirty
2. 需要真实外部条件: .env / secret / API / 外部服务 / 私人资料 / sessions / runs / episodes
3. 高风险: P0 / P1 无法回退修复 / 改变项目根本方向
4. 资源: context 耗尽 / tool failure

**不再是 stop condition:**
- queue empty
- 单个 candidate blocked/deferred
- 需要新增 branch point / RuntimeActionType / handler / catalog entry
- 需要架构设计
- 完成 3 个 loops
- audit PASS 后需要 push

### Phase 7: 输出报告

只有真正全局 stop condition 触发时，按 AUTO_RUN_WORKFLOW.md Section H 格式输出。

## 必须遵守的禁止事项

- 不新增 Anchor
- 不新增无界 branch point
- 不新增第二条主流程
- 不新增 fake loop / fake dispatcher / dogfood-only path
- 不让 direct handler / dispatcher / adapter call 冒充 L3
- 不让 fake/real 变两套主流程
- 不读取 .env
- 不读取真实 sessions/runs
- 不读取 memory/episodes/*.jsonl
- 不连接真实外部服务
- 不调用真实 API
- 不处理真实私人资料
- 不 tag / release / force push / rebase / amend

## 工作方式

直接执行。不等待用户确认。不需要新增 branch point 就停了。blocked 就 deferred 然后继续下一个。需要架构扩展就进入 Architecture Extension Loop。只有真正全局 stop condition 才停。
