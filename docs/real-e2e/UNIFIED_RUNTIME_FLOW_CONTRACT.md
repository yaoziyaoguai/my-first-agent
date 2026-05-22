# Unified Runtime Flow Contract

Status: active remediation contract
Date: 2026-05-22

This document replaces new Anchor framing. Historical Anchor documents may remain
as validation records, but new work must be described as Unified Runtime Flow and
Branch Behavior.

## 1. Unified Runtime Flow

The target runtime flow is:

```text
query/event
  -> core.chat / equivalent runtime entry
  -> runtime loop
  -> lifecycle / decision point
  -> branch selection
  -> RuntimeActionDispatcher
  -> subsystem handler / registry / policy
  -> evidence / trace / capability classification
  -> return to runtime loop
```

`core.chat` is the normal runtime entry. An equivalent runtime entry must be
explicitly documented before it can claim the same classification level.

After a request enters `core.chat`, fake and real must share the same business
flow. Fake and real may differ only in configuration and adapters:

- provider adapter
- store adapter
- tool adapter
- auth loader
- metadata

Provider kind is evidence metadata, not a branch selector. It must not create a
fake-only loop, real-only loop, fake dispatcher, dogfood-only main path, or
subsystem-specific runtime entry.

## 2. Standard Branch Points

A branch point is a documented runtime lifecycle decision where the runtime
selects a subsystem behavior. Branch points may exist before, inside, or after
the main model loop if the contract and evidence classification are honest.

Current branch point categories:

- pre-loop explicit Memory evaluation
- runtime loop model call and model output dispatch
- pending confirmation handling
- turn-end RuntimeAction hook
- tool execution / confirmation handling

Memory may have multiple branch points. It is not required to have one single
entry, but each branch point must state whether it is pre-loop, loop, turn-end,
or post-loop, and whether it goes through `RuntimeActionDispatcher`.

## 3. Branch Behavior Test

A branch behavior test verifies one state inside an existing capability family.
It is not a new capability milestone and must not be named as a new Anchor.

Examples:

- Tool gate `allowed`
- Tool gate `confirmation_required`
- Tool gate `blocked`
- Tool gate `not_found`
- Memory proposal `pending_review`
- Memory proposal `should_not_remember`
- Memory proposal `no_action`

Tool `allowed`, `confirmation_required`, `blocked`, and `not_found` are Tool
branch behaviors. They are not separate Anchor milestones. Negative states such
as `blocked` and `not_found` should be covered as tests, not as new plans.

## 4. Dogfood Boundary

Dogfood scripts may:

- configure a scenario
- call `core.chat`
- collect runtime-produced evidence
- write reports

Dogfood scripts must not claim real core loop E2E if they:

- construct `RuntimeActionRequest`
- call `RuntimeActionDispatcher.route` directly
- call MemoryPolicy, ToolRegistry, SkillLoader, or other subsystem APIs directly
- generate proof themselves

Direct dispatcher dogfood can be useful, but it is harness evidence. It may claim
`harness_runtime_e2e` only when target-module proof is complete. Direct subsystem
calls must classify as `subsystem_integration` or lower.

## 5. Classification Rules

`real_core_loop_runtime_e2e` requires all of the following:

- runtime action is routed from the runtime loop, not from direct dispatcher
- `dispatcher_origin == "runtime_loop"`
- `runtime_loop_invoked == true`
- source is the core loop source, currently `core_loop`
- runtime entry is `core.chat` or a documented equivalent
- lifecycle point / hook name is present
- dispatcher route/result provenance is complete
- target handler was invoked
- target module proof exists
- target catalog and target identity are valid
- result returned to parent runtime

`RuntimeActionRequest.payload` is not trusted provenance. Payload fields such as
`core_loop_invoked`, `core_entrypoint`, and `runtime_hook_name` cannot upgrade a
direct dispatcher call to `real_core_loop_runtime_e2e`.

Classification downgrade rules:

- direct dispatcher with complete target proof: `harness_runtime_e2e`
- direct dispatcher without complete target proof: `subsystem_integration` or lower
- direct subsystem call: `subsystem_integration` or lower
- event-only receipt without target proof: not runtime E2E
- handler self-reported proof: not runtime E2E

## 6. Capability Milestones

A new capability milestone is allowed only when the system gains a new externally
meaningful boundary, such as:

- a new external side-effect class
- a new durable state domain
- a new authorization boundary
- a new provider/store/tool adapter family
- a new runtime entry that is documented as equivalent to `core.chat`

Do not split capability families into endless Anchors. Tool Args, Tool Result,
Retry, Error Recovery, Multi Tool, MCP Tool, Skill, Checkpoint, Streaming, and
SubAgent work require separate explicit authorization and must not be introduced
as follow-on Anchors from current remediation.

## 7. Required Plan Header For Future Work

Every future SDD/TDD plan must answer:

```text
Is this a new capability milestone?
Is this a branch behavior test under an existing capability?
Is this a harness/subsystem-only validation?
```

If the answer is branch behavior or harness/subsystem validation, the plan must
not use Anchor framing.

## 8. Engineering Process Loop

工程流程是迭代 loop，不是线性瀑布流。每个阶段完成后必须 review，发现问题时
必须按证据回退到对应上游阶段，不允许在下游打补丁掩盖上游错误。

### 8.1 正确流程

```text
Unified Runtime Flow Contract / 项目宪法          ← 最高上游
  → SDD / SPEC                                     ← 规格层
    → SPEC Review                                  ← review gate
      → TDD / Test Plan                           ← 测试设计层
        → Test Plan Review                        ← review gate
          → Implementation Plan                    ← 执行规划层
            → Plan Review                         ← review gate
              → Implementation                    ← 执行层
                → Implementation Audit            ← review gate
                  → Debug / Remediation           ← 修复层
                    → 复审                        ← 最终 gate
```

任何阶段都可以回退到上游，不可跳过 review gate。

### 8.2 Review Gate 清单

以下文档生成后必须经过独立 review/audit：

| 文档类型 | Review 时机 | 说明 |
|---------|------------|------|
| SPEC / SDD 文档 | 写完后立即 review | 验证 branch point 判断、capability milestone 判断 |
| TDD / 测试计划文档 | 写完后立即 review | 验证测试覆盖 branch behavior、负例、分类边界 |
| Implementation Plan | 写完后立即 review | 验证执行路径与 contract 一致，不含禁止事项 |
| implementation notes | 完成后 audit | 验证实际改动与 plan 一致 |
| remediation plan | 写完后立即 review | 验证根因分析和回退路径正确 |
| 重要架构文档 | 写完后立即 review | 验证与 Unified Runtime Flow Contract 一致 |

Review 不是只发生在实现完成之后。

### 8.3 按证据回退规则

发现问题时必须向上游追溯根因，不允许在下游打补丁：

| 发现位置 | 根因在上游 | 回退目标 |
|---------|-----------|---------|
| Implementation | 实现逻辑错误 | 回 Implementation |
| Implementation | 测试设计未覆盖该路径 | 回 TDD / Test Plan |
| Implementation | 实现计划遗漏边界条件 | 回 Implementation Plan |
| Implementation | 规格对 branch point 判断错误 | 回 SDD / SPEC |
| Debug / Remediation | 根因是 dogfood/evidence 叙事错误 | 回文档和分类契约 |
| Debug / Remediation | 根因是 branch point 不存在或定义错误 | 回 Unified Runtime Flow Contract |
| Review 阶段 | 发现上游文档缺陷 | 回对应上游阶段 |

"只在出问题的地方修"等价于积累技术债。必须回退到根因所在的最上游阶段。

### 8.4 每项任务的前置判断

所有 coding agent / Claude Code / Codex 任务开始前，必须先回答：

```text
1. 当前任务属于哪个 unified runtime flow branch point？
2. 该 branch point 是否已在 Contract 中定义？
3. 如果已存在：
   - 只做 branch behavior 的 SDD → TDD → 实现 → 测试
   - 不新增 capability milestone
   - 不新增 Anchor
4. 如果不存在：
   - 先回到 Contract / SDD 阶段设计 branch point
   - 不跳过设计直接实现
```

### 8.5 明确禁止的旧模式

以下做法已被 remediation 纠正，不得复用：

- 临时 prompt 补红线（应用 Contract 而非绕过）
- Anchor 叙事无限拆分（使用 branch behavior 而非新 Anchor）
- dogfood 进入 core runtime（dogfood 只能调用 core.chat 并收集 evidence）
- fake/real 两套路径（fake/real 共享同一业务流，仅配置层不同）
- 子系统 direct call 冒充 E2E（direct call 必须降级）
- 只在最后做 review（review gate 必须在每个阶段之后）
