# Memory Proposal Anchor E2E — SPEC

## 1. 目标

Memory Proposal Anchor 是 my-first-agent 的**第一个真实能力锚点**。

它不是 full real E2E。它不声称 Memory 系统已可生产使用。

它只证明一件事：

> `core.chat()` → runtime loop → turn-end hook → `RuntimeActionDispatcher` → Memory handler → `target_module_proof` → classification

这条统一核心路径在 fake provider 和 real provider 两种注入模式下**都能跑通**，且遵循同一套证据链规则。

## 2. 统一核心路径（CRITICAL）

### 2.1 核心约束

fake 和 real **不得走两套核心路径**。

| 注入点 | 注入方式 | 说明 |
|--------|----------|------|
| provider | `chat(provider=...)` 或 `provider_factory` | FakeProvider / RealProvider 只在这里不同 |
| dispatcher | `chat(runtime_action_dispatcher=...)` | fake/real 共用同一 dispatcher |
| loop | `agent.loop.run_main_loop` | **唯一主循环，不复制** |
| hook | `loop.py:_try_phase1_turn_end_runtime_action` | **唯一 turn-end hook，不复制** |

严禁新增：

- `fake_runtime_loop` / `real_runtime_loop`
- `fake_dispatcher` / `real_dispatcher`
- `dogfood_only_main_path` / `production_only_main_path`
- 任何形式的 "if fake: do A; else: do B" 在 loop/hook/dispatcher 层

### 2.2 架构示意图

```text
core.chat(user_input, provider=Fake|Real, runtime_action_dispatcher=...)
  │
  ├─ _memory_runtime.evaluate_user_text          ← Memory evaluation (现有)
  ├─ _run_planning_phase / _handle_planning_phase_result
  │
  └─ _run_main_loop(turn_state, loop_ctx)
       └─ run_main_loop(...)                     ← agent/loop.py (唯一)
            ├─ call_model → provider.create/stream  ← provider 差异仅此一处
            ├─ dispatch_model_output
            └─ result is not None:
                 └─ _try_phase1_turn_end_runtime_action
                      └─ dispatcher.route(RuntimeActionRequest(
                           core_loop_invoked=True,
                           core_entrypoint="core.chat",
                           runtime_hook_name="loop.turn_end",
                           provider_kind=...,
                           external_side_effects=...,
                         ))
                           └─ MemoryTurnEndProposalHandler.handle()
                                └─ context.invoke_registered_target("MemoryPolicy", "decide")
                                     └─ observer → target_module_proof
```

## 3. 两档执行模式

### A. Fake provider mode

| 属性 | 值 |
|------|-----|
| provider | `FakeProvider()` |
| `provider_kind` in evidence | `"fake"` |
| 读 `.env` | **否** |
| 调用真实 API | **否** |
| `external_side_effects` | `false` |
| memory proposal | `pending_review` only |
| 写真实 memory episodes | **否** |
| 证据链 | target_module_proof 存在且完整 |

Fake mode 是**默认安全模式**，可以在任何环境运行，不需要用户授权。

### B. Real provider smoke mode

| 属性 | 值 |
|------|-----|
| provider | `build_model_provider_from_env()` (scoped) |
| `provider_kind` in evidence | `"real"` 或等价 |
| 读 `.env` | **是**，但仅限 scoped loader |
| 调用真实 API | **是**，但需用户明确授权 |
| 打印 secret | **否** |
| 读取 `.env` 内容到日志/stdout | **否** |
| `external_side_effects` | `true` |
| memory proposal | `pending_review` only |
| auto approve | **否** |
| 写 `human_approved` | **否** |
| 写真实 memory episodes | **否** |
| 证据链 | target_module_proof 存在且完整 |

Real mode 需要**用户明确授权**才能运行。默认 skip/gated。

## 4. Memory semantics

### 4.1 Phase 1 已建立的约束（不得退步）

| 约束 | 来源 | 说明 |
|------|------|------|
| `pending_review` only | `MemoryTurnEndProposalHandler` | `auto_approved: false` |
| `not_confirmed: true` | 同上 | 所有 proposal 初始为未确认 |
| `no_silent_retain` | `evidence_extra` | evidence 明确标记 |
| `real_episodes_read: false` | handler payload | 不读取真实 episodes |
| secret-like filter | `contains_secret_like()` | `sk-xxx` / `api_key` 等自动检测 |
| redaction evidence | `redacted_secret: true` | 被拒绝的 proposal 有明确 redaction 标记 |
| `DeterministicMemoryPolicy` | `agent/memory_policy.py` | 确定性触发规则（记住/忘记/remember 等） |

### 4.2 关键语义区分

```text
proposal         ≠  approved memory
pending_review   ≠  human_approved
not_confirmed    ≠  confirmed
no_action        ≠  rejected (secret-like)
should_not_remember  ≠  forget
```

### 4.3 不适当输入的处理

如果 provider 输出不包含可记忆内容（闲聊、单次问候等），handler 应返回 `disposition: "no_action"`，不得硬造 proposal。

如果 provider 输出含 secret-like pattern，handler 必须返回 `disposition: "should_not_remember"`，`secret_like_detected: true`。

## 5. Evidence requirements

### 5.1 必须存在的 evidence 字段

| 字段 | 来源 | 必须值 |
|------|------|--------|
| `core_loop_invoked` | `loop.py` turn-end hook | `true` |
| `core_entrypoint` | 同上 | `"core.chat"` |
| `runtime_hook_name` | 同上 | `"loop.turn_end"` |
| `action_type` | `RuntimeActionRequest` | `"memory.turn_end_proposal"` |
| `dispatcher_route_id` | `dispatcher.route()` | 非空 `route:...` |
| `dispatcher_result_id` | `RuntimeActionContext.result()` | 非空 `result:...` |
| `dispatcher_routed` | `dispatcher.route()` | `true` |
| `target_handler_invoked` | dispatcher | `true` |
| `target_module_proof` | `RuntimeActionModuleObserver` | 非 `None` |
| `target_module` | handler → context | `"MemoryPolicy"` |
| `target_catalog_allowed` | observer → proof | `true` |
| `target_identity_valid` | observer → proof | `true` |
| `provider_kind` | hook 注入 | `"fake"` 或 `"real"` |
| `external_side_effects` | hook 注入 | `false`(fake) / `true`(real) |
| `module_invoked` | observer | `true` |

### 5.2 evidence_level 分类

| 级别 | 条件 | 含义 |
|------|------|------|
| `real_core_loop_runtime_e2e` | `core_loop_invoked=true` + valid `target_module_proof` | fake provider, real loop |
| `harness_runtime_e2e` | `target_module_proof` 完整但无 `core_loop_invoked` | dogfood 直接 dispatcher |
| `subsystem_integration` | `dispatcher_routed` 但缺 target_module_proof | 部分接线 |
| `deterministic_baseline` | deterministic 基线 | 单元测试级 |
| `not_covered` | 无任何 evidence | 未覆盖 |

**注意**：当前分类器不区分 fake/real provider。`provider_kind` 作为独立 evidence 字段存在，但 `evidence_level` 值不变。未来可根据 `external_side_effects`、`provider_kind` 扩展出 `real_provider_core_loop_e2e` 级别。Phase 1 不做此扩展——只通过 `provider_kind` + `external_side_effects` 组合区分。

## 6. Stop conditions

遇到以下任一条件，**必须停止**，不得继续实现：

1. **需要读取 `.env` 内容**（除 scoped loader 外）
2. **需要真实 LLM 但用户未授权**（real mode 需 explicit authorization）
3. **需要读取 `memory/episodes/*.jsonl`**
4. **需要写 `human_approved` memory**
5. **需要 auto approve** memory proposal
6. **需要修改 `DeterministicMemoryPolicy`** 或 Memory governance
7. **需要修改 checkpoint schema**
8. **需要 ToolRegistry / Skill / SubAgent / Streaming 扩展**
9. **需要真实 shell / external process**
10. **无法证明 `core.chat()` 路径**——只能 direct dispatcher 或 subsystem invocation
11. **capability matrix 会 overclaim**——声称了未接入的能力

## 7. 范围边界

### 在本锚点范围内

- fake provider 下 core.chat → memory proposal 全链路
- real provider smoke 下 core.chat → memory proposal 全链路（需用户授权）
- 证据链完整性验证
- `pending_review` only 约束验证
- secret-like 输入处理验证

### 不在本锚点范围内

- real provider 完整 E2E（包含真实 tool execution / checkpoint）
- memory approve / confirm / retain 流程
- memory L2 extraction
- ToolRegistry 集成
- Checkpoint 集成
- SubAgent 集成
- Streaming 集成
- 多 turn 对话 memory 累积
- 跨 session memory 读写

## 8. Memory E2E 完整分层路线

Memory Proposal Anchor 只是 Memory E2E 的第一层。以下明确后续阶段及边界。

### 8.1 三层架构

```text
┌──────────────────────────────────────────────────────┐
│ Layer 3: Recall / Use E2E                            │
│ ───────────────────────────────────────              │
│ conversation start → load episodes → inject into     │
│ system prompt → model uses memory in response        │
│                                                      │
│ 边界：已 human_approved 的 episodes 必须可被召回     │
│       recall 不触及 proposal/pending_review 流程     │
│       recall snapshot 不包含 pending_review items    │
│       本层依赖：Layer 2 完成                         │
│       状态：NOT STARTED                              │
└──────────────────────────────────────────────────────┘
          ▲
          │ 依赖
          │
┌──────────────────────────────────────────────────────┐
│ Layer 2: Approval / Retain E2E                       │
│ ───────────────────────────────────────              │
│ user confirms proposal → policy check → write to     │
│ memory store → mark human_approved → persistence     │
│                                                      │
│ 边界：proposal 不等于 approved memory                │
│       human_approved 是显式用户动作，不可自动        │
│       approval 前必须再次检查 secret-like            │
│       approval 后 episode 进入 recallable 集合       │
│       本层依赖：Layer 1 完成（proposal 能产出）      │
│       状态：NOT STARTED                              │
└──────────────────────────────────────────────────────┘
          ▲
          │ 依赖
          │
┌──────────────────────────────────────────────────────┐
│ Layer 1: Proposal Anchor ← 当前锚点                  │
│ ───────────────────────────────────────              │
│ turn-end → policy evaluation → pending_review        │
│ proposal → target_module_proof → classification      │
│                                                      │
│ 边界：proposal ≠ approved memory                    │
│       pending_review ≠ human_approved                │
│       not_confirmed ≠ confirmed                       │
│       不写 memory store                              │
│       不读 memory episodes                           │
│       状态：IN PROGRESS（本 SPEC）                   │
└──────────────────────────────────────────────────────┘
```

### 8.2 各层关键边界定义

#### proposal（Layer 1）

- **定义**：系统在 turn-end 时对用户输入/模型输出的"这一段可能值得长期记住"的候选判断
- **触发者**：`_try_phase1_turn_end_runtime_action` → `MemoryTurnEndProposalHandler`
- **产出**：`pending_review=True` + `proposal_id`（candidate id）+ `disposition: proposed`
- **不产出**：写入 memory store、改变 recallable set、改变 checkpoint 语义
- **证据**：`target_module_proof` (target_module=MemoryPolicy)
- **classification**：`real_core_loop_runtime_e2e`

#### pending_review（Layer 1 → Layer 2 的桥接状态）

- **定义**：proposal 已生成但尚未经用户确认的中间态
- **存储位置**：仅在 RuntimeActionEvent evidence 中，不入 durable store
- **生命周期**：诞生于 turn-end → 等待用户确认 → 确认后转为 human_approved 或 被拒绝后转为 should_not_remember
- **关键约束**：pending_review 的 proposal 不能被 recall（Layer 3 不能看到它）
- **证据字段**：`pending_review: true`, `not_confirmed: true`, `auto_approved: false`

#### human_approved（Layer 2 产出）

- **定义**：用户显式确认后的 memory episode
- **触发者**：用户交互（确认"记住"/编辑后记住），不能由 provider 或 agent 自动触发
- **产出**：写 memory store → episode 进入 recallable 集合
- **关键约束**：
  - 绝不由 `auto_approved` 路径产生
  - approval 前再次执行 secret-like check
  - 记录 approval 来源（用户输入、时间戳、确认方式）
- **证据字段**：`human_approved: true`, `approved_by: "user"`, `approval_timestamp`

#### recall（Layer 3 产出）

- **定义**：conversation 启动时从 memory store 加载已批准的 episodes 并注入 system prompt
- **触发者**：`refresh_runtime_system_prompt` 或等价入口
- **数据来源**：仅 `human_approved` episodes（不含 `pending_review`、不含 `should_not_remember`）
- **注入形式**：`<memory>` 块注入 system prompt，模型可见
- **关键约束**：
  - 不触及 proposal 路径
  - snapshot 不含未批准内容
  - recall 失败不阻塞对话（降级为空 memory）

### 8.3 状态流转

```text
turn-end hook 触发
      │
      ▼
DeterministicMemoryPolicy.decide()
      │
      ├── no_action ──────────────► 无 proposal（本轮无可记忆内容）
      │
      ├── should_not_remember ────► 被拒绝（secret-like / policy reject）
      │                                disposition: should_not_remember
      │                                secret_like_detected: true (如适用)
      │                                不进入 pending_review
      │
      └── proposed ──────────────► pending_review（Layer 1 终点）
                                       │
                                       │  ← 等待用户确认（Layer 2 起点）
                                       │
                              ┌────────┼────────┐
                              ▼        ▼        ▼
                          记住      编辑      不要记住
                              │        │        │
                              ▼        ▼        ▼
                       human_approved  │  should_not_remember
                              │        │
                              └────────┘
                                 │
                                 ▼
                          写入 memory store
                                 │
                                 ▼
                          recallable set
                                 │
                                 ▼
                    下次对话 system prompt 注入（Layer 3）
```

### 8.4 各层测试策略

| 层 | 测试范围 | provider | 关键测试 |
|-----|---------|----------|---------|
| Layer 1 (Proposal) | TDD.md §1 §2 | fake + real smoke | pending_review, no auto approve, no real episodes |
| Layer 2 (Approval) | 未来 | fake + real | human_approved 路径, confirmation 交互, store 写入, boundary 守卫 |
| Layer 3 (Recall) | 未来 | fake + real | snapshot 加载, prompt 注入, 不含 pending items, 降级安全 |

### 8.5 不得混淆的边界

以下等价关系**不成立**，文档和代码中不得暗示成立：

```text
proposal        ≠  approved memory        ← 核心边界
pending_review  ≠  human_approved         ← approval gate
not_confirmed   ≠  confirmed              ← 确认状态
auto_approved   ≠  human_approved         ← auto-approve 是 bug，不是 feature
disposition:proposed  ≠  episode written  ← proposal 只是候选
no_action       ≠  rejected (secret-like) ← reason 不同
should_not_remember ≠ forget              ← 主动拒绝 ≠ 主动忘记
recall snapshot ≠  proposal               ← 不同数据源
```

以下操作**不得**在 Layer 1 实现阶段发生：

- 写 memory episodes 到 store
- 标记 `human_approved`
- 修改 checkpoint schema 以包含 memory state
- 在 system prompt 中注入 memory
- 从 memory store 加载 episodes 做 recall

## 9. 与 Phase 1 的关系

Memory Proposal Anchor 是 Phase 1 的自然延伸：

- Phase 1 建立了统一核心路径 + turn-end hook + classification
- Memory Anchor 在此基础上验证 fake/real 双模式都能走通同一路径
- Memory Anchor 不修改 Phase 1 的任何机制代码
- Memory Anchor 的 real provider smoke 是迈向 full E2E 的第一步，但明确标记为 smoke（非 full）
