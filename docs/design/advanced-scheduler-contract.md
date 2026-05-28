# Loop 3.4 — Advanced Scheduler SDD

**创建日期**: 2026-05-28
**状态**: architecture decision complete / implementation pending
**依赖**: Phase 1 (Loop 1.1-1.3), Phase 2 (Skill/Memory/SubAgent/MCP main-path integration)
**上游设计**: `docs/design/runtime-decision-spine.md` (Loop 1.1), `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md`
**审计依据**: `docs/audits/2026-05-28-full-subsystem-capability-completion-audit-redteam-addendum.md` §10, §12 (Loop 3.4)

---

## 1. 当前调度缺口（Current Scheduling Gaps）

### 1.1 现状：while-loop + model free output + turn-end probes

当前 `run_main_loop()` (`agent/loop.py:773-850`) 的核心结构：

```text
while True:
    response = call_model(state, loop_ctx)           # 模型决定下一步
    result = dispatch_model_output(response)          # 分派模型输出（tool_use/text/end_turn）
    if result is not None:
        turn_end_hooks(result)                       # lifecycle probes（MEMORY/SKILL/TOOL_GATE/CHECKPOINT）
        return result                                # 文本返回 → 用户
    # result is None → 模型 tool_use → 执行 → 继续 while
```

这个 loop 的调度语义完全由模型输出驱动：模型决定调用哪个 tool、何时 stop、何时 continue。Runtime 只做 max_iterations guard 和 turn-end probe。

### 1.2 七项缺失能力

| # | 缺口 | 当前状态 | 为什么是问题 |
|---|------|---------|-------------|
| G1 | **runtime-owned next action** | 模型 free output 决定 tool_use，runtime 只是执行器 | Runtime 不拥有 action sequence——模型生成 JSON plan 后 runtime 并无 enforcement |
| G2 | **multi-action sequence** | `current_step_index` + `mark_step_complete` 只是 prompt instruction，runtime 不验证 step 顺序 | 模型跳过 step、重复 step、或忽略 plan 时 runtime 无感知 |
| G3 | **subsystem ordering** | Tool/Memory/Skill/MCP/SubAgent 各自在 turn-end hook 中独立 probe，不互相感知 | Runtime 无法表达"先 select skill → 用 skill allowed_tools 约束 tool 选择 → 执行 tool → 记住结果" |
| G4 | **action failure recovery** | 仅 tool repeat guard（重复相同 tool_use 被拦截），无 retry/fallback/continue 策略 | 工具失败后模型可能无意义重试或 halt，runtime 不提供系统级恢复 |
| G5 | **scheduler evidence** | turn-end hook dispatch 产生 probe evidence，但不是 scheduler decision evidence | `_emit_run_summary` 统计 business/probe events，但无法追溯"为什么选择 action A 而非 B" |
| G6 | **result feedback loop** | tool_result 通过 `append_tool_result()` 注入 conversation，下一轮模型再决策 | Result 不进入 runtime-owned feedback loop——runtime 不知道 tool 输出是否满足 plan 预期 |
| G7 | **Skill/Tool/Memory/MCP/SubAgent 协调** | 各子系统有独立 boundary object，但无 runtime-level orchestration | 当前唯一协调点是 prompt instruction（"你有一个 skill、一些 tools、可以 remember"），不是 runtime 层 |

### 1.3 根因

**Agent 没有 runtime-owned action scheduler。** Planner 生成 JSON plan 后，runtime 仍是 `while True: call_model → dispatch_model_output`。Plan 的 step 顺序、依赖、失败恢复全部委托给 prompt instruction + 模型自行理解。

---

## 2. Advanced Scheduler 的最小真实定义

### 2.1 核心定义

Advanced Scheduler 是一个 **runtime-owned action graph executor**，挂在现有 `run_main_loop()` 内。它的最小真实现：

1. **Action Plan**：runtime 从 planner output（或 model tool_use sequence）中构造结构化 action graph
2. **Action Node**：每个 action node 代表一个 runtime 能验证和执行的操作（TOOL_CALL / MEMORY_RETAIN / MEMORY_FORGET / SKILL_SELECT / SKILL_APPLY / SUBAGENT_DELEGATE / CHECKPOINT_SAVE / TASK_COMPLETE）
3. **Sequencing**：runtime 按 graph edge 逐 node 推进，不依赖模型生成"下一步"来推进 plan
4. **Condition feedback**：一个 action 的 result 可以 set condition flag，影响下一个 action 的选择（fallback / retry / skip）
5. **Failure recovery**：action failure → 查 recovery policy → retry（同参数）/ fallback（替代 action）/ continue（skip）/ halt（user prompt）
6. **Evidence**：每个 scheduling decision 有 RuntimeAction evidence（ACTION_PLAN_START / NODE_ENTER / NODE_EXIT / NODE_FAILURE / ACTION_PLAN_COMPLETE）

### 2.2 不是 Advanced Scheduler 的

以下实现 **不算** Advanced Scheduler：
- prompt-only planning（`system prompt 说"你是 scheduler"`）— 不是 runtime-owned
- no-crash smoke（`run_main_loop 没 crash = scheduler 正常`）
- direct-call action graph constructor（不进入 core.chat 主路径）
- `_safe_noop` 冒充 scheduler decision
- 只在 turn-end hook 中追加 observer event

---

## 3. 数据结构设计

### 3.1 ActionNode

```python
@dataclass(frozen=True, slots=True)
class ActionNode:
    """runtime-owned action graph 中的单个 action node。"""
    node_id: str                        # "step_1", "step_2a"
    action_type: str                    # TOOL_CALL / MEMORY_RETAIN / SKILL_SELECT / SUBAGENT_DELEGATE / ...
    target: str                         # tool name / skill name / subagent name / memory operation
    params: Mapping[str, Any]           # 传给 target 的参数
    depends_on: tuple[str, ...]         # node_id 依赖（前置 node 完成后才能执行）
    recovery: ActionRecoveryPolicy      # 失败恢复策略
    condition: str | None               # 可选 condition flag name（前置 result 设置此 flag 时跳过）
```

### 3.2 ActionRecoveryPolicy

```python
@dataclass(frozen=True, slots=True)
class ActionRecoveryPolicy:
    """单个 action node 的失败恢复策略。"""
    max_retries: int = 0                # 最多重试次数（0 = 不重试）
    retry_delay: float = 0.0            # 重试间隔（秒，本次不实现——后期扩展）
    fallback_node_id: str | None = None # 失败时 fallback 到哪个 node
    on_failure: str = "halt"            # halt（停止并报告）/ skip（跳过继续）/ fallback（执行 fallback_node）
```

### 3.3 ActionPlan

```python
@dataclass(frozen=True, slots=True)
class ActionPlan:
    """runtime-owned multi-action execution plan。"""
    plan_id: str
    nodes: tuple[ActionNode, ...]
    edges: tuple[tuple[str, str], ...]  # (from_node_id, to_node_id)
    entry_node_id: str                  # 起始 node_id
    status: str = "pending"             # pending / running / completed / failed / halted
```

### 3.4 SchedulerState（per-turn session state）

```python
@dataclass
class SchedulerState:
    """per-turn scheduler 运行时状态（mutable，仅本 turn 有效）。"""
    current_plan: ActionPlan | None = None
    current_node_id: str | None = None
    completed_nodes: set[str] = field(default_factory=set)
    failed_nodes: dict[str, int] = field(default_factory=dict)  # node_id → failure_count
    condition_flags: dict[str, bool] = field(default_factory=dict)
    node_results: dict[str, Any] = field(default_factory=dict)   # node_id → result
```

### 3.5 RuntimeActionType 扩展

新增 5 个 RuntimeActionType：

| ActionType | 分类 | 说明 |
|-----------|------|------|
| `ACTION_PLAN_START` | business | Scheduler 开始执行一个 action plan |
| `NODE_ENTER` | business | Scheduler 进入一个 action node |
| `NODE_EXIT` | business | Scheduler 成功完成一个 action node |
| `NODE_FAILURE` | business | Action node 执行失败（触发 recovery） |
| `ACTION_PLAN_COMPLETE` | business | Action plan 全部完成或 halted |

---

## 4. 架构接入设计

### 4.1 不引入第二 runtime

Scheduler 是现有 `run_main_loop()` 的**内层扩展**，不是新的 loop：

```text
run_main_loop():
    while True:
        guard check
        
        # 新增：Scheduler checkpoint —— 是否有 active action plan？
        if scheduler.has_active_plan():
            next_action = scheduler.next_node()
            if next_action is None:
                # plan 完成 → fall through to model loop
                pass
            else:
                # runtime-owned action execution
                execute_action_node(next_action, deps)
                continue  # 不调模型，直接推进 next node
        
        # 现有路径：模型决定下一步
        response = call_model(state, loop_ctx)
        result = dispatch_model_output(response)
        ...
```

**关键原则**：
- Scheduler 不替换 model loop——它在 model loop 的**前面**插入 runtime-owned action execution
- Model 仍可触发新的 tool_use，tool_use → plan 更新 → scheduler 接管
- Scheduler 执行的 tool 仍走 `execute_single_tool()` → `append_tool_result()` 路径——复用现有 Tool pipeline
- Turn-end hooks 在 scheduler node 完成后仍触发（保持 evidence chain 完整性）

### 4.2 接入 RuntimeDecisionFrame

`RuntimeDecisionFrame` 新增字段：

```python
scheduler_active: bool           # Scheduler 是否处于活跃 plan 中
current_plan_id: str | None      # 当前 plan ID
current_node_id: str | None      # 当前 node ID
completed_nodes: int             # 已完成 node 数
total_nodes: int                 # plan 总 node 数
```

`build_decision_frame_from_chat_params()` 从 `SchedulerState` 填充这些字段。

### 4.3 复用现有 dispatcher / RuntimeAction

- Scheduler 的 5 个新 RuntimeActionType 走 `dispatcher.route_from_runtime_loop()` —— 与现有 MEMORY_PROPOSE / TOOL_GATE 等一致
- `AdvancedSchedulerHandler` 注册在 `phase1_hook.py`（同模式）
- Evidence catalog 记录在 `evidence.py`

### 4.4 Tool/Memory/Skill/MCP/SubAgent 编排

Scheduler 通过 `ActionNode.action_type` 分发到现有子系统：

| action_type | 执行路径 | 复用现有组件 |
|------------|---------|------------|
| TOOL_CALL | `execute_single_tool(target, params)` | ToolRegistry + ToolRuntimeMediator |
| MEMORY_RETAIN | `ToolRuntimeMediator.mediate_memory_retain(params)` | MemoryRetainHandler + dispatcher |
| MEMORY_FORGET | `ToolRuntimeMediator.mediate_memory_forget(params)` | MemoryForgetHandler + dispatcher |
| SKILL_SELECT | `ToolRuntimeMediator.mediate_skill_select(params)` | SkillRegistry + SKILL_SELECT handler |
| SUBAGENT_DELEGATE | `delegate_l1(params)` (L1) 或 `execute_local(params)` (L0) | SubAgentDelegateL1Handler |
| CHECKPOINT_SAVE | `_dispatch_checkpoint_save(dispatcher, state, params)` | CheckpointSaveHandler |

**不新增第二执行路径**——scheduler 只是选择"何时执行、以什么顺序执行"，实际执行委托给现有子系统 handler。

---

## 5. 实施架构决策

### AD-1: Scheduler 在 model loop 前面插入，不替换

**Decision**: Scheduler 作为 `run_main_loop()` 内的预处理阶段。如果 scheduler 有 pending action，执行它并 `continue`，跳过 `call_model()` 那轮。Plan 完成或无 active plan 时 fall through 到 model loop。

**Rationale**: 保持现有 model loop 完整——model 仍负责 high-level reasoning 和 unexpected situation handling。Scheduler 负责"已知 plan 的按序推进"。

### AD-2: Scheduler 不解析自然语言

**Decision**: Scheduler 只处理结构化 ActionNode，不解析 model free text。Plan 构造由 planner（已有）或 scheduler 从 model tool_use sequence 中提取。

**Rationale**: NLU 是 model 的职责，不是 scheduler 的。Scheduler 是 graph executor，不是 reasoning engine。

### AD-3: ActionNode 复用现有 ToolRegistry 的 tool 执行

**Decision**: `TOOL_CALL` node 直接调用 `execute_single_tool(name, params)`，结果通过 `append_tool_result()` 注入 conversation。不创建新的 tool execution path。

**Rationale**: Tool 是 First Agent 最成熟的子系统——复用其执行路径，不在 scheduler 中重新实现。

### AD-4: Failure recovery 最小实现——halt/skip

**Decision**: 第一阶段只实现 `on_failure: halt`（停止 plan 并返回错误给用户）和 `on_failure: skip`（跳过当前 node 继续下一个）。Retry 逻辑后续 Loop 添加。

**Rationale**: Halt/skip 覆盖 90% 实际场景。Retry 需要幂等性保证和更复杂的 state tracking——留待 real dogfood 验证后再添加。

### AD-5: Scheduler evidence 五步全部 business

**Decision**: 5 个新 RuntimeActionType 全部标记为 `business`（非 probe），因为 scheduler decision 直接改变 agent 的可见行为。

**Rationale**: 与 turn-end probe（TOOL_GATE via _safe_noop）不同，scheduler 的 action plan/nodes 是 runtime-owned 真实业务决策。

### AD-6: condition_flags 最小实现

**Decision**: Node result 可以 set `condition_flags[flag_name] = True/False`，后续 node 通过 `condition` 字段决定是否跳过。

**Rationale**: 这是实现 "tool result feedback 影响下一步 action" 的最简单机制——不需要复杂的 policy engine。

### AD-7: 初始 plan 来源——复用现有 planner

**Decision**: 初始 plan 从现有 `planner.generate_plan()` 解析（JSON → ActionNode），或从 model tool_use sequence 动态构造。Scheduler 不自己生成 plan。

**Rationale**: Planner 已有 JSON plan 生成能力。Scheduler 关注执行，不关注 plan 生成。

---

## 6. Implementation Scope

### 6.1 Loop 3.4a: Scheduler Core（code-path completion）

**Scope**:
1. `agent/action_scheduler.py` — NEW: `ActionNode`, `ActionRecoveryPolicy`, `ActionPlan`, `SchedulerState` dataclasses
2. `agent/action_scheduler.py` — `ActionScheduler` class: `load_plan()`, `next_node()`, `execute_node()`, `complete_plan()`, `halt_plan()`
3. `agent/runtime_integration/schema.py` — 5 个新 RuntimeActionType
4. `agent/runtime_integration/action_scheduler_handler.py` — NEW: `ActionSchedulerHandler` (dispatcher-mediated evidence)
5. `agent/loop.py` — `run_main_loop()` 集成 scheduler preprocessing
6. `agent/runtime_decision_frame.py` — 5 个新 scheduler 字段
7. `tests/runtime_integration/test_action_scheduler.py` — NEW: contract tests

**Out of scope**:
- Real provider plan generation（REAL-EVIDENCE-008）
- Retry with delay（后期扩展）
- Parallel action execution（后期扩展）
- Condition flag 复杂策略（仅 set/get bool）

### 6.2 什么是 code path complete

Scheduler code-path completion 的标准：
- [ ] Scheduler 能从结构化 plan 中加载 action graph
- [ ] Scheduler 能按序推进 node（dependency order）
- [ ] Node 执行复用现有 subsystem handler（TOOL_CALL → execute_single_tool 等）
- [ ] Node failure 触发 halt/skip recovery
- [ ] Scheduler evidence 进入 dispatcher（5 个 RuntimeActionType）
- [ ] RuntimeDecisionFrame 反映 scheduler state
- [ ] 所有执行通过 `route_from_runtime_loop()` 获取 evidence provenance
- [ ] 不引入第二 runtime——scheduler 是 run_main_loop 内层扩展
- [ ] 30+ contract tests 覆盖 load/next/execute/complete/halt/recovery/evidence/decision_frame/not-fakeable

### 6.3 什么是 PARTIAL

以下情况只能标 PARTIAL：
- 只有 SchedulerState dataclass，无 run_main_loop 集成 → STUB
- 只有 direct-call scheduler，无 dispatcher evidence → DIRECT_CALL_ONLY
- 只有 fake plan execution，无 real plan construction（planner 集成）→ FAKE_ONLY

### 6.4 什么需要登记 real evidence debt

| ID | Capability | Missing evidence |
|----|-----------|-----------------|
| REAL-EVIDENCE-008 | Scheduler real provider plan → execution E2E | 真实 LLM 生成的 plan 通过 scheduler 推进执行；fake plan → scheduler execution 不证明 real provider plan parsing 正确 |

---

## 7. TDD / Test Intents

| # | Test Intent | 分类 | 说明 |
|---|------------|------|------|
| T1 | load valid plan → scheduler has_active_plan=True | positive | plan 加载后 scheduler 进入 active 状态 |
| T2 | next_node returns entry node when no deps | positive | 无依赖 node 首先返回 |
| T3 | next_node respects dependency order | positive | depends_on 满足后才返回 |
| T4 | execute TOOL_CALL node → calls execute_single_tool | positive | 复用现有 Tool pipeline |
| T5 | execute MEMORY_RETAIN node → store write + evidence | positive | 复用现有 MemoryRetainHandler |
| T6 | complete_plan transitions status → completed | positive | 所有 node done 后正确收尾 |
| T7 | node failure with on_failure=halt → halt_plan | recovery | halt 阻止后续 node 执行 |
| T8 | node failure with on_failure=skip → continue to next | recovery | skip 后继续下一个无依赖 node |
| T9 | fallback_node_id → execute fallback on failure | recovery | fallback 机制正确 |
| T10 | action_plan_start dispatcher evidence | evidence | plan start 有 RuntimeAction evidence |
| T11 | node_enter/exit dispatcher evidence per node | evidence | 每个 node 的 enter/exit 有 evidence |
| T12 | node_failure dispatcher evidence | evidence | failure 有 evidence（含 reason） |
| T13 | RuntimeDecisionFrame reflects scheduler state | evidence | decision frame 含 scheduler_active/plan_id/node_id |
| T14 | scheduler preprocessing does not break existing model loop | regression | scheduler 无 active plan 时 model loop 正常运行 |
| T15 | scheduler stops cleanly on max_iterations | regression | guard check 仍然生效 |
| T16 | not fakeable: no direct-call-only | guard | 不通过直接调用 scheduler 方法冒充 completion |
| T17 | not fakeable: no crash-only | guard | execute_node 必须验证业务 outcome |
| T18 | not fakeable: dispatcher evidence present | guard | 所有 scheduler action 有 dispatcher evidence |
| T19 | condition flag → skip node | conditional | condition_flags 正确跳过 node |
| T20 | empty plan → no-op, no crash | edge | 空 plan 正确处理 |

---

## 8. 文件清单

### 新建文件

| 文件 | 行数（估） | 说明 |
|------|----------|------|
| `agent/action_scheduler.py` | ~250 | ActionNode/ActionPlan/SchedulerState dataclasses + ActionScheduler class |
| `agent/runtime_integration/action_scheduler_handler.py` | ~80 | ActionSchedulerHandler（dispatcher-mediated evidence） |
| `tests/runtime_integration/test_action_scheduler.py` | ~600 | 20+ contract tests |
| `docs/design/advanced-scheduler-contract.md` | 本文件 | SDD |

### 修改文件

| 文件 | 改动 | 说明 |
|------|------|------|
| `agent/runtime_integration/schema.py` | +5 enum | ACTION_PLAN_START/NODE_ENTER/NODE_EXIT/NODE_FAILURE/ACTION_PLAN_COMPLETE |
| `agent/runtime_integration/phase1_hook.py` | +1 handler | 注册 ActionSchedulerHandler |
| `agent/runtime_integration/evidence.py` | +5 descriptors | Catalog descriptors + adapters |
| `agent/loop.py` | ~30 lines | run_main_loop() scheduler preprocessing |
| `agent/runtime_decision_frame.py` | ~15 lines | 5 个新 scheduler 字段 |

---

## 9. Verification

```bash
# New scheduler tests
python -m pytest tests/runtime_integration/test_action_scheduler.py -v

# Regression: all existing tests must pass
python -m pytest tests/unit/test_runtime_decision_frame.py tests/ -k "loop or scheduler" -v

# ruff
ruff check agent/action_scheduler.py agent/runtime_integration/action_scheduler_handler.py agent/loop.py agent/runtime_decision_frame.py
```
