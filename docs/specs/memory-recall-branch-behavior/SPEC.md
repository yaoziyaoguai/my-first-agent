# Memory Recall Branch Behavior SPEC

Status: draft
Date: 2026-05-23

## Branch Point Judgment

Memory recall into context 归属 Contract Section 2 中已列出的 **pre-loop explicit Memory evaluation** 分支点。

当前 `core.py:refresh_runtime_system_prompt()` 已经执行了 snapshot→prompt 注入，但它走的是直接调用路径（`_memory_runtime.snapshot_for_prompt()` → `build_system_prompt()`），没有经过 `RuntimeActionDispatcher` → handler → evidence 管道。本轮 SPEC 将该行为正式化为 RuntimeAction 分支行为，不改功能语义。

- 不是新 Anchor
- 不是新 runtime flow
- 不新增 branch point 类别（pre-loop explicit Memory evaluation 已存在）
- 如果现有 dispatcher/catalog 无法承载，停止并 Ask User

## Current Behavior Scope

### 已存在的能力（不变）

1. `MemoryRuntime.snapshot_for_prompt()` → 从 store 生成 MemorySnapshot
2. `build_memory_snapshot_from_store()` → governed snapshot generation（budget、scope、sensitivity 过滤）
3. `build_system_prompt(memory_snapshot)` → 将 snapshot 注入 system prompt
4. `build_memory_section()` → 将 snapshot 渲染为 prompt 文本段
5. `refresh_runtime_system_prompt()` → 在 `chat()` 入口处触发以上全链路

### 本轮新增

6. `RuntimeActionType.MEMORY_RECALL` → 新的 action type
7. `MemoryRecallHandler` → RuntimeAction handler，封装 snapshot→prompt 注入
8. Catalog descriptor 注册 → `memory.recall` + `MemoryRecallHandler` + target_module
9. Dispatcher 注册 → `build_phase1_dispatcher()` 中注册 MEMORY_RECALL
10. `core.py` 或 `loop.py` 中通过 dispatcher.route() 触发 recall（替换直接调用）
11. Evidence 收集 → target_module_proof、handler provenance、snapshot item count
12. 测试 → harness_runtime_e2e 级别验证

### 明确不做

- **不新增** runtime flow / branch point
- **不实现** vector/RAG/semantic retrieval
- **不实现** background consolidation recall
- **不实现** proactive reminder
- **不实现** memory delete/update/review UI
- **不实现** memory search/query API
- **不改变** snapshot budget/policy/filter 规则
- **不改变** store 写入语义
- **不处理** 真实私人资料
- **不读取** 真实 memory/episodes/*.jsonl
- **不调用** 真实 API

## Fake/Real Boundary

Fake 和 real 的差异仅限：
- store adapter（InMemoryMemoryStore vs FilesystemMemoryStore）
- provider config（fake vs anthropic_native）

进入 core runtime 后流程一致：
- dispatcher.route(MEMORY_RECALL) → MemoryRecallHandler.handle() → snapshot_for_prompt() → build_system_prompt()
- 不新增 fake-only recall path
- 不新增 real-only recall path
- 不新增 dogfood-only recall path

## Dogfood / Evidence Boundary

- dogfood 只能调用 `core.chat` 并收集 evidence
- direct `MemoryRecallHandler.handle()` 调用只能作为 subsystem test
- direct store read → snapshot → prompt 不得 claim `real_core_loop_runtime_e2e`
- evidence 不得 overclaim full memory capability（只能 claim recall branch behavior）

## Evidence Classification Target

| Level | 条件 |
|-------|------|
| `subsystem_integration` | direct handler 调用 |
| `harness_runtime_e2e` | dispatcher.route() with target_module_proof |
| `real_core_loop_runtime_e2e` | route_from_runtime_loop with core_entrypoint |

本轮实现目标：`harness_runtime_e2e`。`real_core_loop_runtime_e2e` 是 deferred。

## Open Questions

1. recall 触发时机：`chat()` 入口（当前 refresh_runtime_system_prompt 位置）还是 loop 每轮迭代前？→ **决定：chat() 入口**，与当前行为一致
2. recall handler 是否需要自己的 store 引用，还是从 context 获取？→ **决定：handler 接收 store 作为构造参数**，与 MemoryRetainHandler 模式一致
3. `MEMORY_RECALL` 是否复用现有 `MemoryRuntime.snapshot_for_prompt()`？→ **决定：复用**，handler 调用 `_memory_runtime.snapshot_for_prompt()` 然后通过 context 注入 prompt

## Review Checklist

- [ ] branch point 判断正确：归属 pre-loop explicit Memory evaluation
- [ ] 不新增 branch point / Anchor / runtime flow
- [ ] fake/real 只有 adapter 差异
- [ ] dogfood/evidence 边界清晰
- [ ] scope 收敛：只做 recall into context，不做 retrieval/RAG/search
- [ ] 不读取真实数据 / .env / API
- [ ] 不修改 Tool/MCP/Skill/Checkpoint
- [ ] 可独立测试：fake store + dispatcher.route()
