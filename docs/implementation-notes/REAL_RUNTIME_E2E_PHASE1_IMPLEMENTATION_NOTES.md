# Real Runtime E2E Phase 1 实现笔记

## 目标

打通 `RuntimeAction` evidence harness 到真实 `core.chat() / runtime loop` 的路径，证明 `RuntimeAction` 不再只能从 dogfood harness 直接 dispatcher 调用产生，而是可以从真实主执行入口触发。

## 变更摘要

### 新增文件

- **`agent/provider/fake_provider.py`** — Phase 1 专用确定性 provider，实现 `ModelProvider` 协议（`create()` + `stream()`），永不读 `.env`、不调外部 API
- **`agent/runtime_integration/phase1_hook.py`** — `build_phase1_dispatcher()` 工厂函数，仅注册 `MemoryTurnEndProposalHandler`
- **`scripts/dogfood_phase1_real_core_loop.py`** — Phase 1 real core loop dogfood runner，通过 `core.chat()` 完整路径验证 real core loop evidence chain
- **`tests/runtime_integration/test_phase1_real_core_loop.py`** — 13 个 Phase 1 架构边界测试

### 修改文件

- **`agent/loop.py`** — `LoopDependencies` 新增 `runtime_action_dispatcher` 字段；新增 `_try_phase1_turn_end_runtime_action()` helper；`run_main_loop()` turn-end 点触发 hook
- **`agent/loop_context.py`** — `LoopContext` 新增 `runtime_action_dispatcher` 字段
- **`agent/core.py`** — `chat()` 新增 `runtime_action_dispatcher` 参数；当 provider 为 fake 时自动构造 Phase 1 dispatcher
- **`agent/core_contexts.py`** — `build_loop_context()` 转发新参数
- **`agent/provider/factory.py`** — `"fake"` provider type 改为构造 `FakeProvider`
- **`agent/runtime_integration/evidence.py`** — 新增 `REAL_CORE_LOOP_RUNTIME_E2E` / `HARNESS_RUNTIME_E2E` 常量；`classify_evidence_level()` 按 `core_loop_invoked` 区分
- **`agent/runtime_integration/dispatcher.py`** — `_mark_returned_to_parent()` 从 `request.payload` 流入 core loop source evidence
- **`agent/runtime_integration/__init__.py`** — 导出新常量

### 测试文件更新

- `tests/runtime_integration/test_runtime_action_contract.py` — `"runtime_e2e"` → `"harness_runtime_e2e"`
- `tests/runtime_integration/test_runtime_action_handlers.py` — 同上
- `tests/runtime_integration/test_capability_matrix.py` — 同上
- `scripts/dogfood_e2e_runtime.py` — 同上
- `tests/test_architecture_boundaries.py` — import baseline 新增 `phase1_hook`
- `tests/test_transition_checkpoint_boundaries.py` — LoopContext 字段契约新增 `runtime_action_dispatcher`

## 架构决策

### Hook 点选择：loop turn-end

`run_main_loop()` 中 `result is not None` 的分支被选为 hook 点，理由：
- turn-end 是语义上的自然边界，不需要额外条件判断
- 不参与循环内部决策（不改变 loop 行为）
- dispatcher 失败时 silent fail（不阻塞 loop）

### 注入路径：LoopContext → LoopDependencies

遵循已有 `model_provider` 的模式，通过 `LoopContext` 注入 dispatcher，而非在每个函数签名上穿线。

### classification 分层

- `core_loop_invoked=True` → `real_core_loop_runtime_e2e`
- `core_loop_invoked` 缺失/不为 True → `harness_runtime_e2e`（向后兼容）
- 缺 `target_module_proof` → 不通过 `is_runtime_e2e_evidence`，降级到更低分类

## Phase 1 约束遵守

- [x] 不读 `.env`
- [x] 不调真实 LLM（FakeProvider）
- [x] 不调外部 API
- [x] 不执行真实工具
- [x] 不读/写真实 sessions/runs/memory episodes
- [x] memory turn-end hook 仅 `pending_review`，不自动批准
- [x] 不改 checkpoint schema
- [x] 不改 Memory governance
- [x] 不改 ToolRegistry authority
- [x] 无 nested delegation / SubAgent 扩展
- [x] 无新依赖

## 检查结果

- `git diff --check`: 通过
- `ruff check agent tests scripts`: 通过
- `pytest tests/runtime_integration/`: 112 passed
- `pytest` (full, temp HOME): 2885 passed, 14 skipped
