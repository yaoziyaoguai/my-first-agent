# Memory Proposal Anchor E2E — TDD

## 0. TDD 原则

所有测试必须先写、先红、再绿。不得先写实现再补测试。

测试文件建议位置：

- `tests/runtime_integration/test_memory_anchor_fake.py` — fake provider path
- `tests/runtime_integration/test_memory_anchor_real.py` — real provider smoke (gated)

## 1. Fake provider path tests

这些测试**必须默认运行**，不依赖 `.env` 或真实 API。

### 1.1 `test_memory_anchor_fake_provider_core_chat_triggers_pending_review`

**测试目标**：fake provider 下，`core.chat()` 触发 memory proposal，结果为 `pending_review`。

**测试步骤**：

1. 通过 `phase1_hook.build_phase1_dispatcher()` 构建 dispatcher
2. 使用 `_SpyDispatcher` 包裹 dispatcher
3. 调用 `chat("以后叫我小王", provider=FakeProvider(), runtime_action_dispatcher=spy)`
4. 断言 spy 捕获到 `route()` 调用
5. 断言 `request.payload.core_loop_invoked == true`
6. 断言 `request.payload.core_entrypoint == "core.chat"`
7. 断言 `request.payload.runtime_hook_name == "loop.turn_end"`
8. 从 `spy.action_log` 取最后一个 event
9. 断言 `evidence.evidence_level == "real_core_loop_runtime_e2e"`
10. 断言 `evidence.target_module_proof is not None`
11. 断言 `payload.pending_review in (True, False)` — 取决于 memory policy 决策
12. 断言 `payload.auto_approved == False`
13. 断言 `payload.not_confirmed == True`

**架构保护**：钉死 core.chat → dispatcher → memory handler → evidence 全链路。

---

### 1.2 `test_memory_anchor_uses_same_core_path_not_fake_loop`

**测试目标**：fake provider 模式走的是统一 `run_main_loop`，不是任何 fake-专用路径。

**测试步骤**：

1. 构建 dispatcher + spy
2. 调用 `chat("hello", provider=FakeProvider(), runtime_action_dispatcher=spy)`
3. 断言 spy 捕获的 `RuntimeActionRequest.source == "core_loop"`
4. 断言 `payload.core_entrypoint == "core.chat"`
5. 断言 `payload.runtime_hook_name == "loop.turn_end"`
6. 验证 dispatcher 实例是同一个 `RuntimeActionDispatcher` 类（不是 fake 子类）
7. 验证 handler 是 `MemoryTurnEndProposalHandler`（不是 fake/mock handler）

**架构保护**：防止未来有人创建 fake-only loop/fake-only dispatcher/fake-only handler 绕过统一路径。

---

### 1.3 `test_memory_anchor_no_auto_approve`

**测试目标**：无论 memory policy 决策如何，`auto_approved` 始终为 `false`。

**测试步骤**：

1. 用明确的记忆触发输入（"记住：以后叫我小王"）调用 `chat()`
   — 注意：`chat()` 内置的 `_memory_runtime.evaluate_user_text` 可能触发
   memory confirmation 流程导致 `chat()` 返回空串。如果此情况发生，改为
   使用不带 "记住" 前缀但含 memory 关键词的输入，或用 spy 捕获的
   `dispatcher.route()` 参数中的 payload 做断言
2. 从 spy action_log 取 event payload
3. 断言 `payload.auto_approved == False`
4. 断言 `payload.not_confirmed == True`
5. 断言 evidence 中 `no_silent_retain == True`

**架构保护**：无论 provider 是什么，memory 绝不自动批准。

---

### 1.4 `test_memory_anchor_does_not_read_memory_episodes`

**测试目标**：memory proposal handler 不读取真实 memory episodes。

**测试步骤**：

1. 构建 dispatcher + spy
2. 调用 `chat("以后叫我小王", provider=FakeProvider(), runtime_action_dispatcher=spy)`
3. 从 action_log 取 event payload
4. 断言 `payload.real_episodes_read == False`

**架构保护**：防止 handler 在 proposal 阶段意外读取真实 memory store。

---

### 1.5 `test_memory_anchor_secret_like_input_is_redacted_or_should_not_remember`

**测试目标**：含 secret-like pattern 的输入被自动拒绝，有 redaction 标记。

**测试步骤**：

1. 构建 dispatcher + spy
2. 调用 `chat("记住这个 api_key: sk-abc123def456", provider=FakeProvider(), runtime_action_dispatcher=spy)`
   — 同 1.3 的注意：如果 `chat()` 触发 memory confirmation 导致空返回，
   改为直接构造 `RuntimeActionRequest` 走 `dispatcher.route()`，但必须
   在测试注释中说明 why（`_memory_runtime` 拦截早于 loop）
3. 如果走 `chat()`：从 spy action_log 取 evidence
   如果走 direct route：从 result.evidence 取
4. 断言 `payload.disposition == "should_not_remember"`
5. 断言 `payload.secret_like_detected == True`
6. 断言 `payload.redacted_secret == True`
7. 断言 `payload.pending_review == False`

**架构保护**：secret-like filter 在 memory proposal 路径中仍然有效。

---

### 1.6 `test_memory_anchor_direct_dispatch_is_harness_not_real_core_loop`

**测试目标**：直接 `dispatcher.route()` 调用只能得到 `harness_runtime_e2e`，不能冒充 `real_core_loop_runtime_e2e`。

**测试步骤**：

1. 构建 dispatcher（不通过 spy）
2. 手工构造 `RuntimeActionRequest(action_type=MEMORY_TURN_END_PROPOSAL, ...)` 不含 `core_loop_invoked`
3. 调用 `dispatcher.route(request)`
4. 断言 `result.evidence["evidence_level"] == "harness_runtime_e2e"`
5. 断言 `result.evidence.get("core_loop_invoked") is not True`

**架构保护**：防止 memory proposal 测试退化为 pure harness test。

---

## 2. Real provider smoke tests (gated)

这些测试**默认 skip**，只在用户设置明确 opt-in 环境变量后才运行。

建议 opt-in 变量：`MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1`

### 2.1 `test_memory_anchor_real_provider_requires_explicit_authorization`

**测试目标**：real provider smoke 不能在没有 opt-in 的情况下运行。

**测试步骤**：

1. 检查 `os.environ.get("MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE")`
2. 如果非 `"1"`：`pytest.skip("real provider smoke requires explicit opt-in")`

**架构保护**：防止 CI 中意外调用真实 API。

---

### 2.2 `test_memory_anchor_real_provider_uses_scoped_loader_without_printing_secret`

**测试目标**：real provider 使用 scoped `.env` loader，不打印 API key 到 stdout/stderr。

**测试步骤**：

1. 确认 opt-in 已设置
2. 使用 `build_model_provider_from_env()` 构建 real provider（或其 scoped wrapper）
3. 捕获 stdout/stderr
4. 调用 `chat("hello", provider=real_provider, runtime_action_dispatcher=dispatcher)`
5. 断言 stdout/stderr 中不含 API key pattern（`sk-ant-`、`sk-` 等）

**依赖**：需要项目根目录有有效的 `.env` 或用户已设置 `ANTHROPIC_API_KEY` 环境变量。

---

### 2.3 `test_memory_anchor_real_provider_still_pending_review_only`

**测试目标**：真实 provider 下，memory proposal 仍然是 `pending_review` only，不自动批准。

**测试步骤**：

1. 确认 opt-in 已设置
2. 构建 dispatcher + spy
3. 调用 `chat("以后叫我小王", provider=real_provider, runtime_action_dispatcher=spy)`
4. 从 action_log 取 event
5. 断言 `payload.auto_approved == False`
6. 断言 `payload.not_confirmed == True`
7. 断言 evidence 中 `no_silent_retain == True`
8. 断言 evidence 中 `provider_kind == "real"`（或等价标记）
9. 断言 evidence 中 `external_side_effects == True`
10. 断言 `evidence_level == "real_core_loop_runtime_e2e"`

**架构保护**：真实 LLM 不会绕过 memory governance。

---

### 2.4 `test_memory_anchor_real_provider_does_not_write_human_approved`

**测试目标**：真实 provider 下不写 `human_approved` memory。

**测试步骤**：

1. 确认 opt-in 已设置
2. 构建 dispatcher + spy
3. 调用 `chat(...)` with real provider
4. 从 action_log 取所有 events
5. 断言没有任何 event 的 payload 包含 `human_approved == True`
6. 断言没有任何 event 的 payload 包含 `auto_approved == True`

**架构保护**：memory 写入必须经过显式用户确认，不能由 provider 自动触发。

---

## 3. 测试运行命令

### Fake provider path（默认运行）

```bash
HOME=/private/tmp/my-first-agent-phase1-home \
  .venv/bin/python -m pytest tests/runtime_integration/test_memory_anchor_fake.py -q
```

### Real provider smoke（需 opt-in）

```bash
HOME=/private/tmp/my-first-agent-phase1-home \
  MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1 \
  .venv/bin/python -m pytest tests/runtime_integration/test_memory_anchor_real.py -q
```

### 全部 runtime_integration

```bash
HOME=/private/tmp/my-first-agent-phase1-home \
  .venv/bin/python -m pytest tests/runtime_integration/ -q
```
