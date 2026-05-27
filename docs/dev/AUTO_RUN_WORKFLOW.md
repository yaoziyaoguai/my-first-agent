# First Agent Auto-Run Workflow

Status: active
Date: 2026-05-27

## A. 目标

First Agent auto-run workflow 的目标是：

- 从 roadmap queue 自动选择 safe-to-auto-run capability
- 对每个 capability 执行完整工程 loop（SPEC → TDD → Implementation → Review → Commit → Push）
- 单个 capability blocked 时不停止整个 workflow，记录为 deferred 后继续下一个
- 即使需要新增 branch point / RuntimeActionType / handler / catalog entry / 架构决策，也进入 Architecture Extension Loop 自行裁决
- 只有真正的全局 stop condition（repo 不安全、需要真实 secret/API/private data、P0、资源耗尽）才停

## B. 事实源

本 workflow 必须读取并遵守以下文档：

1. **[PROJECT_STATUS.md](../PROJECT_STATUS.md)** — 当前状态入口：capability 状态、已知 issues、活跃约束、config 规则、推荐下一步。**如果其他文档与 PROJECT_STATUS 冲突，以 PROJECT_STATUS 为准。**
2. **[PROGRESS_LEDGER.md](../PROGRESS_LEDGER.md)** — 进度账本：按时间倒序的关键 milestones、已修复 bugs、当前 P3 积压
3. [ENGINEERING_WORKFLOW.md](ENGINEERING_WORKFLOW.md) — 工程流程纪律：SDD → TDD → Implementation → Review → Debug 的迭代 loop、review gate、回退规则、重试上限、升级条件、禁止模式
4. [Unified Runtime Flow Contract](../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md) — 项目宪法：runtime architecture、branch points、classification rules、capability milestones
5. [First Agent Subsystem Integration Roadmap](../plans/first-agent-subsystem-integration-roadmap.md) — 子系统/介入点清单、evidence matrix、backlog 分类、自动执行队列

## C. 两种自动执行 Loop

### C1. Normal Capability Loop

用于已有 branch point / existing intervention point 下的 branch behavior：

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
                      → PASS → push → Continue discovery
```

### C2. Architecture Extension Loop

用于现有 branch point 不足以承载，但仍符合统一主流程的大方向时：

```text
Discovery
  → Architecture Decision / SPEC
    → Architecture Review (gate)
      → TDD / Test Plan
        → TDD Review (gate)
          → Implementation Plan
            → Plan Review (gate)
              → Implementation
                → Self-review / Debug
                  → Verification Gates
                    → Commit
                      → Independent Audit (gate)
                        → PASS → push → Continue discovery
```

低风险改动（docs-only、typo、单文件小修）可跳过前半段，从 Implementation 或 Gate 直接进入。跳过不是绕过工程纪律——仍须满足对应 gate（git diff --check、test pass、exit code = 0）。

### C3. Architecture Extension Loop 约束

Architecture Extension Loop 必须遵守以下规则：

- 新 branch point 必须有限稳定、明确可测试、可审计
- 必须说明为什么现有 branch point 不能承载
- 必须说明它挂在统一主流程的哪个阶段
- 必须说明它是写入子系统、读取/召回子系统，还是外部 adapter boundary
- 必须有 L1/L2/L3 evidence plan
- 必须有 stop condition
- 必须有 rollback/deferred plan
- 必须有中文学习型注释/docstring
- 必须不读取真实 secret/API/private data
- 不改变项目根本方向（仍然只有一条统一主流程）
- 不新增 Anchor
- 不新增无界 branch point
- 不新增第二条主流程

### C4. Loop 入口点（按任务类型选择起点）

auto_run 不要求每次都从 SPEC 开始走完整 loop。根据任务类型选择合适入口：

| 任务类型 | 起点 | 路径 |
|---------|------|------|
| **Bug fix** | evidence/report → failing test | 读 report → 写回归测试(red) → 定位根因 → fix → rerun affected gates → 更新 PROGRESS_LEDGER |
| **Dogfood** | plan/report → run cases | 读 plan → 执行 cases → 记录 issues → 可选 safe fix → 更新 report/ledger |
| **Docs cleanup** | inventory → delete/archive/rewrite | 全量扫描 → 分类 → 删除/归档/重写 → source-of-truth tests → commit |
| **Config fix** | config contract → diagnostics test | 读 contract → 写测试 → fix → smoke → 更新相关 docs |
| **Architecture change** | design doc → review → tests → impl | 严格走 Normal/Architecture Extension Loop 全路径 |
| **Test only** | write tests → verify | 补 regression/edge case → 验证 pass → commit |

### C5. 每轮必须落文档

每轮 auto_run 结束后无论成功还是 blocked，必须更新对应文档：

- 发现 bug → 写入 PROGRESS_LEDGER issue table
- 修复完成 → 更新 PROGRESS_LEDGER milestones
- blocked/deferred → 写 blocked reason 和下一步建议
- 状态变化 → 更新 PROJECT_STATUS.md
- 新 report/plan → 在 PROJECT_STATUS.md 中更新指针

每轮结束必须说明：current status / what changed / what remains / next recommended loop。

### C6. 旧文档冲突处理

如果旧文档与 PROJECT_STATUS.md 冲突，**以 PROJECT_STATUS.md 为准**。如果发现 PROJECT_STATUS.md 已过期，**先更新 PROJECT_STATUS.md**。

## D. 单个 Capability Deferred 条件（不停止 workflow）

如果当前 capability 触发以下任一条件，该 capability **deferred**，不停止整个 workflow：

- 需要真实 API / .env / secret
- 需要连接真实外部服务
- 需要处理真实私人资料
- 需要真实 sessions/runs
- 需要真实 memory/episodes
- P0 级别问题
- P1 且无法通过回退修复
- 同一问题在同一阶段已修 2 次仍未通过 gate（触发升级条件）
- 架构决策会改变项目根本方向

**不再是 deferred 条件（进入 Architecture Extension Loop）：**

- 需要新增 branch point
- 需要新增 RuntimeActionType
- 需要新增 handler
- 需要新增 evidence catalog entry
- 需要架构设计/决策
- 需要新增 runtime flow（有限、可测试、挂载在统一主流程上）

deferred 后检查 queue 中是否还有其他 candidate，有则继续。

## E. 全局 Stop Condition

只有以下情况才能停止整个 auto-run：

| Stop condition | 说明 |
|---------------|------|
| not main | 不在 main 分支 |
| behind origin/main | 本地落后远程 |
| working tree dirty 且不属于当前 loop | 有未提交改动且不是当前 capability 产生的 |
| HEAD has tag | HEAD 已有 tag |
| 需要真实 API / .env / secret | 无法在 fake-first 下继续 |
| 需要真实外部服务 | 无法在本地验证 |
| 需要真实私人资料 | 安全边界 |
| 需要真实 sessions/runs | 安全边界 |
| 需要真实 memory/episodes | 安全边界 |
| P0 级别问题 | 不可自动裁决的高风险 |
| P1 且无法通过回退修复 | 回退后仍然 FAIL |
| 架构决策会改变项目根本方向 | 超越 auto-run 授权范围 |
| context 接近耗尽 | 无法安全继续，必须输出 resume instruction |
| tool/environment failure 阻止继续 | 外部依赖不可用 |

**不再是全局 stop condition：**

- queue empty（继续 discovery 直到真正无 safe candidate）
- 单个 candidate blocked / deferred
- 需要新增 branch point（触发 Architecture Extension Loop）
- 需要新增 RuntimeActionType / handler / catalog entry（触发 Architecture Extension Loop）
- 需要架构设计（触发 Architecture Extension Loop）
- 完成 3 个 loops（继续 discovery 找下一个）
- 所有剩余候选都需要架构扩展（逐个评估，逐个进入 Architecture Extension Loop）

## F. 选择下一个 Capability 的规则

优先选择顺序（从高到低）：

1. correctness / safety bug — 修复已知缺陷
2. evidence overclaim prevention — 补齐 target overclaim 防护
3. 已有 branch point 下的 branch behavior — 不新增架构元素
4. existing handler / RuntimeActionType L1/L2/L3 gap — evidence 缺口补齐
5. error-path hardening — 加固已有错误处理路径
6. architecture extension that enables existing deferred subsystem
7. model/provider/skill/checkpoint/mcp/memory existing assets with safe implementation path

选择来源：[First Agent Subsystem Integration Roadmap](../plans/first-agent-subsystem-integration-roadmap.md) Section F（自动执行队列）和 Section D（Backlog 分类）。

### F1. Evidence Label 解释

AutoRun 在选择 capability 时必须正确解释 evidence label，不得将低精度标签误解为高精度：

| Roadmap 标签 | 实际含义 | AutoRun 应如何理解 |
|---|---|---|
| `L3 complete / full闭环` | 完整 L3：dispatch path + business operation + branch behaviors | 该 capability 已完全闭环，不需要继续工作 |
| `L3 dispatch path verified` | RuntimeAction 经 `route_from_runtime_loop()` → handler → catalog adapter 验证，但 handler 可能只走 error/degraded 分支 | dispatch 通路已验证，business operation 可能需要补齐（如 non-empty registry） |
| `L3 business operation verified` | 主业务路径（含非空数据/有意义 side-effect）经 dispatcher 验证 | 核心业务已验证，可能有 branch behavior gap |
| `runtime trace path verified` | 事件通过非 dispatcher sink（如 `on_trace_event`）发出 | **不是 L3**——不使用 "L3" 标签；是独立的 trace infrastructure evidence |
| `L3 evidence path verified` | 类似 dispatch path verified，强调 evidence chain 完整 | dispatch 链已验证，但 full UX / business semantics 可能未覆盖 |

**关键区分：**

- `dispatch path verified` ≠ `business operation complete`
- `empty registry dispatch` ≠ `non-empty registry operation`
- `trace event emission via on_trace_event` ≠ `RuntimeActionDispatcher L3`
- `MCP L3` ⊂ `Tool Pipeline L3`（MCP 是 Tool Pipeline adapter boundary，不独立）

AutoRun 不得将 `dispatch path verified` 当作 `L3 complete` 跳过 discovery——dispatch path verified 的 capability 通常是 branch behavior 补齐的候选。

## G. 禁止事项

以下行为在 auto-run 中严格禁止：

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
- 不 tag
- 不 release
- 不 force push
- 不 rebase
- 不 amend

## H. 输出格式

每次 auto-run 结束（仅当真正全局 stop condition 触发），必须输出：

```text
## Auto-Run Report — YYYY-MM-DD

### A. Architecture Extension Loop 是否升级

### B. 修改文件

### C. Commits / Pushes

### D. Discovery Candidates

### E. Chosen Candidate + Loop Type (Normal / Architecture Extension)

### F. SPEC/TDD/Plan/Notes

### G. Tests/Gates

### H. Deferred Items and Reasons

### I. Final Repo Status

### J. Exact Global Stop Condition

### K. Resume Instruction
```

## 参考

- [ENGINEERING_WORKFLOW.md](ENGINEERING_WORKFLOW.md)
- [Unified Runtime Flow Contract](../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)
- [First Agent Subsystem Integration Roadmap](../plans/first-agent-subsystem-integration-roadmap.md)
