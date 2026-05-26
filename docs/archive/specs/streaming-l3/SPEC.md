# Streaming L3 — Architecture Decision / SPEC

Date: 2026-05-24
Status: Architecture Extension Loop

## Architecture Decision

### 为什么现有 branch point 能承载

Streaming 复用 turn-end hook branch point（与 MEMORY_PROPOSE、SKILL_SELECT 等同一模式）。`StreamingProviderCallHandler` 是已有 handler，`STREAMING_PROVIDER_CALL` RuntimeActionType 已定义，catalog entries 已存在。唯一缺失的是：
1. `phase1_hook.py` 中注册 handler
2. `loop.py` turn-end hook 中 dispatch

不需要新增 branch point / RuntimeActionType / handler / catalog entry。

### 在统一主流程中的位置

```
core.chat() → _run_main_loop() → model call (provider.create)
  → turn-end hook → _try_phase1_turn_end_runtime_action()
  → ... → SUBAGENT_DELEGATE_L0
  → STREAMING_PROVIDER_CALL dispatch ← 新增
  → trace event emission
```

### 当前局限与未来方向

当前 `call_model()` 使用 `provider.create()`（非流式），即使 provider 支持 streaming。
本集成在 turn-end hook 中收集 streaming capability 证据并 dispatch，但 events 为空
（因为模型调用未走流式路径）。

未来如果在 `call_model()` 中切换到 `provider.stream()`，事件的 collection 会在 model
call 阶段完成，turn-end hook 只需要取已收集的事件并 dispatch。

### Fake-first 策略

- FakeProvider 声明 `supports_streaming = True`
- 当前 `call_model()` 走 `provider.create()`，不走流式
- turn-end hook dispatch 时 `events=[]`，handler 正确识别为 insufficient streaming evidence
- L3 验证 dispatch 路径和 evidence chain，不依赖真实流式事件

### L1/L2/L3 Evidence Plan

- L1: handler 直接调用（已有 `test_runtime_action_handlers.py` 覆盖）
- L2: dispatcher.route()（已有 `test_runtime_action_contract.py` 覆盖）
- L3: core.chat() → turn-end hook → dispatcher.route_from_runtime_loop()（本 SPEC）

### Stop Conditions

- 不涉及真实 API/secret/private data
- FakeProvider 即可完成全部 L3 测试
- 如果 handler 行为需要修改，不超出 handler 文件范围

### Rollback/Deferred Plan

- 回退：移除 phase1_hook 注册 + 移除 turn-end hook dispatch block
- Deferred: 将 `call_model()` 切换为 `provider.stream()` 是独立的 provider integration 任务
