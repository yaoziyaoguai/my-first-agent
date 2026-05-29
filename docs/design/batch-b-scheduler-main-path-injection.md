# Batch B — Scheduler Main-Path Injection SDD

**创建日期**: 2026-05-29
**状态**: SDD complete / implementation pending
**依赖**: Loop 3.4 SDD (`docs/design/advanced-scheduler-contract.md`) — architecture decisions already made
**上游审计**: independent re-audit (2026-05-29) — REAL-EVIDENCE-008 questionable
**Batch**: B (code-path hardening, not evidence-only)

---

## 1. 为什么 008 当前 questionable

### 1.1 现有资产

Loop 3.4 已完成以下实现：

| 资产 | 文件 | 状态 |
|------|------|------|
| ActionScheduler + ActionPlan + ActionNode | `agent/action_scheduler.py` (554 lines) | 已实现 |
| ActionSchedulerHandler (5 RuntimeActionType) | `agent/runtime_integration/action_scheduler_handler.py` | 已注册 |
| loop.py scheduler integration | `agent/loop.py:870-894` | 已集成 |
| RuntimeDecisionFrame scheduler branch points | `agent/runtime_decision_frame.py` | 5 branch points |
| Contract tests | `tests/runtime_integration/test_action_scheduler.py` | 46 tests pass |

### 1.2 但为什么仍 questionable

独立审计发现三个关键缺口：

**缺口 1: ActionScheduler 不在默认 main runtime path 中**

`agent/core.py` 中 `chat()` 不注入 `ActionScheduler` 到 `LoopDependencies`：

```python
# core.py — 当前状态：action_scheduler 未传入 LoopDependencies
deps = LoopDependencies(
    call_model=...,
    dispatch_model_output=...,
    runtime_action_dispatcher=dispatcher,
    # action_scheduler 缺失 → loop.py:873 getattr → None → scheduler 永不触发
)
```

`loop.py:873` 的 `getattr(dependencies, "action_scheduler", None)` 在默认路径中永远返回 `None`。Scheduler integration code 存在但 dead code。

**缺口 2: 验证脚本手动构造 ActionScheduler**

`scripts/real_evidence_008_scheduler.py`（标记为 CLOSED 的证据）使用手动构造：

```python
plan = build_action_plan_from_dict({
    "plan_id": "test_plan",
    "title": "Hardcoded Test Plan",
    "nodes": [
        {"node_id": "step_1", "action_type": "TOOL_CALL", ...},
        {"node_id": "step_2", "action_type": "TOOL_CALL", ...},
    ],
})
scheduler = ActionScheduler(dispatcher=dispatcher, executor=manual_executor)
scheduler.load_plan(plan)
# 然后手动调用 scheduler.next_node() / execute_node() / complete_plan()
```

这不是 main-path evidence——这是 manual harness。与 `core.chat()` 默认路径无关。

**缺口 3: ActionPlan 来源是硬编码 dict**

当前 ActionPlan 构造路径：
- `build_action_plan_from_dict(hardcoded_dict)` — 验证脚本使用
- 无 model-generated plan → ActionPlan 的自动转换路径
- 无 planner output → ActionPlan 的 bridge

### 1.3 结论

REAL-EVIDENCE-008 的 "CLOSED" 标记是 overclaim。代码存在、contract tests 通过，但 scheduler 未进入 `core.chat()` 默认 main runtime path。这属于 **code path complete, main-path injection pending**。

---

## 2. Batch B 目标

### 2.1 核心目标

让 `ActionScheduler` 进入 `core.chat()` 的默认 main runtime path，使得：

1. `core.chat()` 支持 ActionScheduler 注入（opt-in parameter，默认 None 保持向后兼容）
2. 当注入时，`LoopDependencies.action_scheduler` 被正确设置
3. `run_main_loop()` 中 scheduler preprocessing block 实际触发（不再是 dead code）
4. ACTION_PLAN_START / NODE_ENTER / NODE_EXIT / NODE_FAILURE / ACTION_PLAN_COMPLETE 由 main runtime path 触发
5. ActionPlan 可以通过 model-generated plan 或 runtime-owned plan 构造（不再只有 hardcoded dict）
6. 至少一个 action result 能影响 next action（condition_flags → skip/fallback）

### 2.2 不做什么

- **不**让 ActionScheduler 成为默认行为（保持 opt-in，默认 None）
- **不**让 Scheduler 替换 model loop（AD-1: scheduler 在 model loop 前 preprocessing）
- **不**让 Scheduler 直接执行 Tool/Memory/MCP/SubAgent（AD-3: 复用已有 handler）
- **不**引入第二 runtime flow
- **不**改 ActionNode/ActionPlan/SchedulerState 数据结构（Loop 3.4 已定型）
- **不**改 ActionSchedulerHandler（已注册 5 个 RuntimeActionType）
- **不**处理 planner generate_plan → ActionPlan 的完整 bridge（那是 planner 的职责，非 scheduler）
- **不**实现 retry 逻辑（AD-4: halt/skip 最小实现）

### 2.3 设计边界

```
┌─────────────────────────────────────────────────────┐
│ core.chat(user_input, provider, ..., scheduler=None) │
│   └─→ LoopDependencies(action_scheduler=scheduler)   │
│         └─→ run_main_loop()                          │
│               ├─ scheduler.has_active_plan()?         │
│               │   YES → next_node() → execute_node()  │
│               │         → dispatcher evidence         │
│               │         → condition_flags update       │
│               │         → continue (skip model call)  │
│               │   NO  → call_model() [existing path] │
│               └─ turn_end hooks [unchanged]           │
└─────────────────────────────────────────────────────┘
```

Scheduler 是 main runtime path 内的 orchestration layer：
- Scheduler 不是第二 runtime
- Scheduler 不直接执行 Tool / Memory / MCP / SubAgent
- Scheduler 只选择/推进 action node
- 实际执行仍复用已有 RuntimeAction / dispatcher / mediator / handler

---

## 3. Implementation Plan

### 3.1 Step 1: core.chat() 支持 ActionScheduler 注入

**文件**: `agent/core.py`

在 `chat()` 签名中新增 `action_scheduler=None` 参数，传入 `LoopDependencies`：

```python
def chat(
    user_input: str,
    provider: Any = None,
    *,
    runtime_action_dispatcher: Any = None,
    action_scheduler: Any = None,  # NEW — Batch B
    on_runtime_event: Any = None,
    ...
) -> str:
    ...
    deps = LoopDependencies(
        call_model=_call_model,
        dispatch_model_output=_dispatch_model_output,
        runtime_action_dispatcher=runtime_action_dispatcher,
        action_scheduler=action_scheduler,  # NEW
        ...
    )
```

### 3.2 Step 2: ActionPlan 构造 bridge

**文件**: `agent/action_scheduler.py` (追加)

新增 `build_action_plan_from_model_output()` — 从 model tool_use sequence 或 structured JSON output 构造 ActionPlan。这是 opt-in bridge，不改变现有 `build_action_plan_from_dict()` 的行为。

核心约束：
- 输入来自真实 model output（不是 hardcoded dict）
- 验证 node 引用的 tool/memory/skill/subagent 在 TOOL_REGISTRY / SkillRegistry / SubAgentRegistry 中存在
- 无效 node → 跳过并记录 evidence，不 crash

### 3.3 Step 3: Evidence chain 验证

确保 scheduler evidence 在 main runtime path 中完整：

| Evidence | 触发点 | 验证方式 |
|----------|--------|---------|
| ACTION_PLAN_START | `scheduler.load_plan()` → `_dispatch_plan_start()` | action_log 中存在 |
| NODE_ENTER | `scheduler.next_node()` 返回有效 node | action_log 中存在 |
| NODE_EXIT | `scheduler.execute_node()` 完成 | action_log 中存在 |
| NODE_FAILURE | node 执行失败 + recovery=halt | action_log 中存在 |
| ACTION_PLAN_COMPLETE | `scheduler.complete_plan()` | action_log 中存在 |

### 3.4 Step 4: REAL-EVIDENCE-008 验证脚本重写

**文件**: `scripts/real_evidence_008_scheduler.py` (重写)

当前脚本问题：
- 手动构造 ActionScheduler
- 手动构造 ActionPlan (hardcoded dict)
- 手动调用 scheduler.next_node() / execute_node()
- 不在 core.chat() main path 中

重写后：
- 通过 `core.chat(..., action_scheduler=scheduler)` 注入
- ActionPlan 来自 model-generated plan（或 runtime-owned plan construction）
- Scheduler execution 由 `run_main_loop()` preprocessing block 驱动
- Evidence 从 dispatcher action_log 提取（非手动构造）

---

## 4. TDD / Test Intents

### 4.1 Contract Tests

**File**: `tests/runtime_integration/test_scheduler_main_path.py` (NEW)

| Test ID | Intent | Category |
|---------|--------|----------|
| T1 | `core.chat()` accepts `action_scheduler` parameter without error | happy path |
| T2 | `LoopDependencies` carries `action_scheduler` when injected | integration |
| T3 | `run_main_loop()` scheduler preprocessing triggers when `has_active_plan()` returns True | integration |
| T4 | ACTION_PLAN_START dispatched in main runtime path | evidence |
| T5 | NODE_ENTER dispatched in main runtime path | evidence |
| T6 | NODE_EXIT dispatched in main runtime path | evidence |
| T7 | ACTION_PLAN_COMPLETE dispatched in main runtime path | evidence |
| T8 | `condition_flags` set by one node affect next node selection | cross-node influence |
| T9 | NODE_FAILURE dispatched on action failure with recovery=halt | failure path |
| T10 | `action_scheduler=None` (default) — existing path unchanged, no regression | regression |
| T11 | Scheduler does not bypass ToolRuntimeMediator | boundary guard |
| T12 | Scheduler does not bypass Memory handler | boundary guard |
| T13 | Scheduler does not bypass Skill handler | boundary guard |
| T14 | Scheduler does not bypass MCP Tool pipeline | boundary guard |
| T15 | Scheduler does not bypass SubAgent parent-mediated path | boundary guard |

### 4.2 Not-Fakeable Guard Tests

| Test ID | Intent |
|---------|--------|
| N1 | Manual dict plan + standalone script ≠ main-path evidence |
| N2 | No-crash ≠ scheduler main-path PASS |
| N3 | Direct `dispatcher.route()` call ≠ main-path evidence |
| N4 | Scheduler evidence must appear in dispatcher action_log, not in manual assertions |

### 4.3 Existing Tests Must Not Regress

- `tests/runtime_integration/test_action_scheduler.py` (46 tests)
- All focused regression tests (~560+)

---

## 5. Success Criteria

1. `core.chat()` 接受 `action_scheduler` 参数
2. 注入的 ActionScheduler 通过 `LoopDependencies` 传入 `run_main_loop()`
3. `run_main_loop()` scheduler preprocessing block 实际触发（不再是 dead code）
4. 5 种 scheduler evidence 出现在 dispatcher action_log 中（由 main path 触发）
5. 至少一个 action result 影响 next action
6. NODE_FAILURE 在 failure case 中 dispatch
7. Scheduler 不绕过 ToolRuntimeMediator / Memory / Skill / MCP / SubAgent
8. 46 个现有 scheduler contract tests 全部通过
9. 默认路径 `action_scheduler=None` 行为不变

---

## 6. Scope Boundaries

### 明确不做

- planner generate_plan → ActionPlan 完整 bridge（属于 planner 职责）
- retry 逻辑（AD-4 决定 halt/skip 最小实现）
- ActionScheduler 默认激活（保持 opt-in）
- 多 instance scheduler 协调
- TUI scheduler visualization
- REAL-EVIDENCE-003 Skill allowed_tools
- REAL-EVIDENCE-006 TOOL_MEDIATOR_GAP
- B7/B8

### 与现有代码的关系

- `agent/action_scheduler.py` — 追加 `build_action_plan_from_model_output()`，不改现有数据结构
- `agent/core.py` — 追加 1 个参数 + 1 行注入，不改现有逻辑
- `agent/loop.py` — 不改（已有 scheduler preprocessing block）
- `agent/runtime_integration/action_scheduler_handler.py` — 不改
- `agent/runtime_decision_frame.py` — scheduler branch points 从 PARTIAL 更新为反映 main-path status

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| ActionScheduler injection breaks default path | Low | High | Opt-in only; default `None` path covered by T10 |
| Model-generated plan parse failure | Medium | Medium | Graceful degradation: invalid plan → no active plan → fall through to model loop |
| Scheduler preprocessing increases turn latency | Low | Low | Only triggers when `has_active_plan()` returns True |
| Scope creep into planner bridge | Medium | Medium | Explicit scope boundary: ActionPlan construction from model output only, not planner integration |

---

## 8. 待实现时解决的 Open Questions

这些是实现时（非设计时）需要解决的问题，记录在此避免遗漏：

1. `build_action_plan_from_model_output()` 的输入格式 — JSON string? tool_use block sequence? 两者都支持?
2. ActionExecutor 的默认实现 — 复用 `execute_single_tool`? 走 `ToolRuntimeMediator`? 需要 dispatcher 吗?
3. ActionPlan 的跨 turn 持久化 — 存在 state.task 中? checkpoint 中?
4. `core.chat()` 的调用者 (CLI/main.py) 如何决定是否注入 ActionScheduler?
