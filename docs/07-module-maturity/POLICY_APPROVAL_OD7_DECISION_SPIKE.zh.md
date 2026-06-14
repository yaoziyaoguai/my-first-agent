# Policy / Approval OD-7 Decision Spike

**日期**: 2026-06-14
**性质**: docs-only design spike，不是实现，不是 L3 completion
**Architecture Repair Mainline**: CLOSED
**Trigger**: T-OD7 (BLOCKED_BY_DECISION → DESIGN_SPIKE_COMPLETED)

## 1. Status

- Architecture Repair Mainline: **CLOSED**。
- Trigger: **T-OD7**（`BLOCKED_BY_DECISION`）。
- Policy / Approval module: **L2**（不是 L3，不是 L4）。
- 本文是 OD-7 design spike，解除"模糊 owner decision"阻塞，形成可执行的 L3 hardening 路线。
- 本轮不改 `agent/` 源码，不改 `tests/`，不实现任何 approval runtime。
- Policy 不标 L3。OD-7 不标 fully completed。

## 2. Governance Context

### 2.1 现有执行层级

```
North Star §13: Policy/Permission/Guardrail/Human-Approval 分列
  → Closure audit: OD-7 = BLOCKED_BY_DECISION
    → Maturity audit: Policy/Approval = L2
      → D3: policy gate ≠ production approval
      → Trigger registry: T-OD7 = BLOCKED_BY_DECISION
```

### 2.2 当前 Policy 子边界（来自 maturity audit D3）

| 子边界 | 当前状态 |
|--------|----------|
| (a) Policy gate | `ToolGateHandler` 可拒绝 + no-execution golden + adversarial stub ≈ **L3** |
| (b) Interactive confirmation | `confirmation/` handlers + `awaiting_user_input` + tests ≈ **L2** |
| (c) OD-7 production/multi-user approval hook | **deferred (≈ L1)** |

### 2.3 为什么 OD-7 现在需要解除

- MemoryOwner 已接管 explicit mutation（Memory L3）
- Tool system 已有 `ToolGateHandler` 局部 gate
- 下一步需要统一 approval 语义，否则每个模块各自实现
- OD-7 不解除会导致后续 SubAgent/Scheduler/Capability 无法获得统一 Policy

## 3. Existing Policy / Approval Surface

### 3.1 当前 gate / confirmation / approval 清单

| 机制 | 位置 | 范围 | 统一性 |
|------|------|------|--------|
| `ToolGateHandler` | `agent/runtime_integration/tool_gate.py:32` | Tool execution: reject/allow/confirmation_required | 只限 Tool |
| `DeterministicMemoryPolicy` | `agent/memory_policy.py:86` | Memory: BLOCK sensitive/REJECT/SESSION_ONLY | 只限 Memory |
| `MemoryOwner` | `agent/memory_owner.py` | explicit_user_request: create/noop/reject after confirmation | 只限 Memory |
| Memory confirmation | `agent/memory_confirmation.py` | 用户确认 retain/forget | 只限 Memory |
| Tool confirmation | `agent/confirmation/tool.py:34` | 用户确认 tool execution | 只限 Tool |
| `confirmation_required`→`awaiting_user_input` | `agent/transitions.py` | 通用 confirmation 状态 | 通用但未统一 approve/deny |
| `RuntimeActionResult` statuses | `agent/runtime_integration/schema.py:367` | rejected/confirmation_required/succeeded/... | 通用但只记录不治理 |

### 3.2 发现

1. **无统一 PolicyDecision model**：各模块（Tool/Memory）各自实现 gate
2. **无统一 approval hook**：`ToolGateHandler` 和 `DeterministicMemoryPolicy` 互不通信
3. **Confirmation 有两种实现**：Memory 走 `memory_confirmation.py`，Tool 走 `confirmation/tool.py`
4. **SubAgent 无 Policy gate**：SubAgent V0 没有自己的 policy gate，依赖 `provider_mode_allowed` 拒绝
5. **Scheduler 无 Policy gate**：未接入 runtime routing
6. **Capability registry 无 Policy gate**：capability status 是口径，不是 enforce-point

## 4. Terminology

为避免歧义，定义以下术语：

| Term | 定义 |
|------|------|
| **Confirmation** | 用户交互层：模型请求 → 用户确认 → 执行。由 `confirmation/` handlers 处理 |
| **Approval** | 人类审批层（OD-7 target）：高风险 action 需要人类显式审批后方可执行。不是 confirmation，不是 auto-allow |
| **Policy Decision** | 治理层：系统根据规则（capability registry + action type + risk level）决定 ALLOW / REQUIRE_APPROVAL / DENY |
| **Capability Permission** | 注册层：capability 是否 declared/registered/routed |
| **Audit Evidence** | 证据层：每个 decision 产生可追溯的 audit event |
| **Deny / Reject** | 终点：拒绝执行，产生 reason + audit |
| **Allow** | 终点：允许执行，产生 audit |
| **Require Approval** | 中间态：暂停执行，等待 human approval |
| **Audit-Only** | 允许执行，但必须强制记录 audit（用于低风险但需要追踪的操作） |

**关键区别**：
- Confirmation ≠ Approval: confirmation 是当前已有的用户"确认执行"；approval 是 OD-7 要增加的"人类审批后执行"
- Policy ≠ Capability: policy 决定"能不能做"；capability 注册"有没有这个能力"
- Deny ≠ Reject: deny = 系统规则拒绝；reject = 用户/人类拒绝

## 5. Proposed Decision Model

### 5.1 `PolicyDecision` 枚举

```
ALLOW          — 允许执行，记录 audit
REQUIRE_APPROVAL — 需要人类审批（OD-7 目标）
DENY           — 系统拒绝，记录 audit + reason
AUDIT_ONLY     — 允许执行，强制 audit，不需要审批
```

### 5.2 Decision flow

```
Action Request
  → Capability check (declared? registered? routed?)
    → PolicyDecision(match action type, module, risk level)
      → ALLOW → execute + audit
      → DENY → reject + audit + reason
      → REQUIRE_APPROVAL → pause → human approval → execute + audit
      → AUDIT_ONLY → execute + audit
```

### 5.3 与 MemoryOwner 的关系

```
MemoryOwner: explicit_user_request create/noop/reject
  → 在 Owner 内：policy gate (sensitive → reject)
  → 在 Owner 外：approval gate (OD-7: high-risk memory mutation → REQUIRE_APPROVAL)

Policy ≠ MemoryOwner:
  - MemoryOwner = mutation authority for explicit memory
  - Policy = cross-module approval framework
  - MemoryOwner 可以在 Policy 框架下注册其 action 需要哪种 decision
```

### 5.4 与 Tool System 的关系

```
Tool execution: TOOL_GATE → TOOL_INVOKE → TOOL_RESULT
  当前: ToolGateHandler 处理 reject/allow/confirmation_required
  OD-7: 统一 PolicyDecision 替换/增强 ToolGateHandler
```

## 6. Action Classification Matrix

| Action | Default Decision | Reason | Audit? | Human? | Module Owner | Status |
|--------|-----------------|--------|--------|--------|-------------|--------|
| memory retain (semantic) | AUDIT_ONLY | Explicit user intent, confirmed | ✓ | ✗ | MemoryOwner | L3 |
| memory forget/delete | REQUIRE_APPROVAL | Destructive mutation | ✓ | ✓ | MemoryOwner | TRACKED_DEBT |
| memory update | REQUIRE_APPROVAL | Overwrites existing memory | ✓ | ✓ | MemoryOwner | TRACKED_DEBT |
| tool read-only | ALLOW | No side effect | ✗ | ✗ | Tool system | L3 |
| tool write/side-effect | REQUIRE_APPROVAL | Side effect risk | ✓ | ✓ | Tool system | L3 (OD-7 需增强) |
| external service call | REQUIRE_APPROVAL | External risk, cost | ✓ | ✓ | Provider/MCP | BLOCKED_BY_EXTERNAL |
| provider real call | REQUIRE_APPROVAL | Cost, credential | ✓ | ✓ | Provider | L3 (opt-in) |
| subagent delegation | REQUIRE_APPROVAL | Child runtime, scope risk | ✓ | ✓ | SubAgent | L2 |
| scheduler async action | REQUIRE_APPROVAL | Delayed execution, persistence | ✓ | ✓ | Scheduler | L1 |
| config/capability change | REQUIRE_APPROVAL | System topology change | ✓ | ✓ | Capability | L2 |
| checkpoint/resume | ALLOW | Recovery, no side effect | ✓ | ✗ | State | L3 |
| docs-only action | ALLOW | No side effect | ✗ | ✗ | Docs | L3 |
| test-only action | ALLOW | Sandbox | ✗ | ✗ | Tests | L3 |

## 7. Module Boundary Mapping

```
  ┌─────────────────┐
  │   PolicyDecision │  ← 统一 ALOW/REQUIRE_APPROVAL/DENY/AUDIT_ONLY
  │   (OD-7 target)  │
  └───────┬─────────┘
          │ 消费
    ┌─────┼─────┬──────┬──────┬─────┐
    ▼     ▼     ▼      ▼      ▼     ▼
 MemoryOwner │ Tool  │SubAgent│Scheduler│Capability
  (mutation) │(exec) │(delegate)│(async) │(config)
```

PolicyDecision 是横切层，各模块 action 注册其 risk level 和 decision requirement。
MemoryOwner 的 create/noop/reject 继续在 owner 内工作。
PolicyDecision 作为外层 gate，可以 override 模块级 decision。

## 8. Bypass / Gap Analysis

### 8.1 当前 bypass 路径

| 路径 | Bypass 风险 |
|------|------------|
| Memory 无 owner 路径 | `MemoryRuntime` 在 `owner=None` 时走 legacy 路径，绕过 MemoryOwner gate |
| Tool 无 policy gate 的 tool | 部分 tool 可能不经过 `ToolGateHandler` |
| SubAgent V0 无 approval | FOP-1 阻止 real provider，但 policy_blocked 不是统一 PolicyDecision |
| Scheduler 未 routed | 无法执行，但也不能被 Policy gate 覆盖 |
| Capability 无 enforcement | capability 状态是口径，不是 gate |

### 8.2 当前应保持 blocked/debt 的项

- **OD-7 full implementation**: 需要先有 PolicyDecision model + golden
- **Scheduler routing**: 无 consumer，保持 dormant
- **Capability enforcement**: 需要 CM-2 unified contract 先在 design spike
- **MCP approval**: 需要 real external connection 先在 BLOCKED_BY_EXTERNAL

## 9. L3 Hardening Plan

### Phase 1: PolicyDecision golden (docs + tests)
- Scope: `agent/policy_decision.py` + `tests/test_policy_decision_golden.py`
- Output: `PolicyDecision` enum + ALLOW/REQUIRE_APPROVAL/DENY/AUDIT_ONLY 决策矩阵
- No runtime integration
- Commit: `feat(policy): add PolicyDecision model and golden`

### Phase 2: Tool gate integration
- Scope: Route Tool execution through PolicyDecision
- Use existing `ToolGateHandler` as starting point
- Add PolicyDecision decider layer between gate and execution
- No human approval UI yet
- Commit: `feat(policy): route tool gate through policy decision`

### Phase 3: MemoryOwner integration
- Scope: Wire MemoryOwner into PolicyDecision framework
- MemoryOwner registers its action types with policy classification
- No change to existing create/noop/reject semantics
- Commit: `feat(policy): register memory actions with policy`

### Phase 4: Docs sync and reviewer audit
- Update maturity audit (Policy L2→L3)
- Update trigger registry (T-OD7 DESIGN_SPIKE→COMPLETED)
- Fresh reviewer validation
- Commit: `docs(policy): reconcile L3 policy evidence`

## 10. Non-Goals

- Not implementing human approval UI
- Not replacing confirmation flow
- Not replacing MemoryOwner or ToolGateHandler
- Not integrating Scheduler (dormant) or MCP (external blocker)
- Not implementing Capability enforcement (CM-2 not yet decided)
- Not making Policy default-on for all actions
- Not claiming Policy L3 before Phase 1-4 completion
- Not claiming L4

## 11. Reviewer Findings

### Architecture reviewer

1. OD-7 design spike 足够解除 "模糊 owner decision" → 形成了 4-phase L3 plan
2. Policy/Approval 架构位置清晰：横切 PolicyDecision layer
3. Confirmation / approval / policy / capability / audit 已区分
4. Policy-MemoryOwner 边界明确：MemoryOwner 是 mutation authority，Policy 是 approval gate
5. Policy-Tool 边界明确：PolicyDecision 增强 ToolGateHandler
6. Policy-SubAgent/Scheduler/Capability 边界：保持 blocked 直到 ready
7. 可执行的 L3 hardening plan: 4 phases，每 phase 1 commit
8. Policy 仍 L2，未声称 L3

### Adversarial reviewer

1. 无隐藏 implementation
2. Design spike 不是 L3 completion
3. Approval 规则不会过宽：memory retain 是 AUDIT_ONLY，write 是 REQUIRE_APPROVAL
4. Approval 规则不会过窄：read-only/checkpoint 是 ALLOW
5. MemoryOwner/Tool gate 不会被绕过：PolicyDecision 作为外层 gate 增强现有 gate
6. External service 已覆盖：REQUIRE_APPROVAL
7. 无 broad refactor 倾向：Phase 1 只新增 model，Phase 2-3 增强现有 gate
8. 无 L4 overclaim
9. 无 Window 4 / Architecture Repair 迹象

## 12. Evidence Appendix

### Governance
- `AGENT_MODULE_MATURITY_AUDIT.zh.md` §5.9 — Policy L2, D3 子边界
- `POST_REPAIR_TRIGGER_REGISTRY.zh.md` §4 — T-OD7 BLOCKED_BY_DECISION
- `L3_HARDENING_TRIAGE.zh.md` §5 — Policy OD-7 design spike
- `FREEZE_FILE_INTEGRITY_AUDIT.zh.md` — CLEAN_WITH_LOW_RISK_NOTES

### Source
- `agent/runtime_integration/tool_gate.py:32` — ToolGateHandler
- `agent/memory_policy.py:86` — DeterministicMemoryPolicy
- `agent/memory_owner.py` — MemoryOwner mutation authority
- `agent/memory_confirmation.py` — Memory confirmation flow
- `agent/confirmation/tool.py:34` — Tool confirmation
- `agent/transitions.py` — confirmation_required/awaiting_user_input
- `agent/runtime_integration/schema.py:367` — RuntimeActionResult statuses

### Graphify
- `ToolGateHandler` — 中心 policy gate node
- `RuntimeActionDispatcher` — 所有 action 经过的 dispatcher
- `Confirmation/Ask User` — 确认入口
- Graphify used for discovery; results verified against source files
