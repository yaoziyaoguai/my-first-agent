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

## 8. 与 Phase 1 的关系

Memory Proposal Anchor 是 Phase 1 的自然延伸：

- Phase 1 建立了统一核心路径 + turn-end hook + classification
- Memory Anchor 在此基础上验证 fake/real 双模式都能走通同一路径
- Memory Anchor 不修改 Phase 1 的任何机制代码
- Memory Anchor 的 real provider smoke 是迈向 full E2E 的第一步，但明确标记为 smoke（非 full）
