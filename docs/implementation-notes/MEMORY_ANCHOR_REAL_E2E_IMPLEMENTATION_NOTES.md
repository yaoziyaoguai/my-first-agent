# Memory Anchor Real E2E 实现笔记 — fake-provider Phase

## 目标

实现 Memory Proposal Anchor 的 fake-provider 验证层：7 个 TDD 测试 + 专用 dogfood 脚本，钉死 `core.chat()` → `run_main_loop()` → turn-end hook → `RuntimeActionDispatcher` → `MemoryTurnEndProposalHandler` 全链路的 fake-provider 路径。

本轮不改任何生产代码——全链路已在 Phase 1 就位。

## 变更摘要

### 新增文件

- **`tests/runtime_integration/test_memory_anchor_fake.py`** — 7 个 Memory Anchor 专属 TDD 测试，覆盖 core.chat 全链路 + 边界约束
- **`scripts/dogfood_memory_anchor_fake.py`** — Memory Anchor fake-mode 专用 dogfood 脚本，输出 13 项 PASS 标准检查
- **`docs/implementation-notes/MEMORY_ANCHOR_REAL_E2E_IMPLEMENTATION_NOTES.md`** — 本文件

### 修改文件

无。本轮不改任何生产代码。

## Spec Gaps

### "以后叫我小王" 不触发 pending_review

`DeterministicMemoryPolicy.decide("以后叫我小王")` 返回 `NO_OP`，因为输入不匹配任何 `RETAIN_PREFIXES`（"记住"、"remember" 等前缀）。handler 走 `no_action` 分支：`pending_review=False`, `auto_approved=False`, `not_confirmed=True`。

这是正确的行为——不是缺陷。"以后叫我小王" 是一个普通的称呼偏好表达，没有显式的"记住"指令。policy 的 explicit-only 设计是正确的。

如需测试 `proposed` / `pending_review=True` 路径，必须使用命中 `RETAIN_PREFIXES` 的输入（如 "记住：以后叫我小王"），但此类输入会被 `_memory_runtime.evaluate_user_text` 拦截（CONFIRMATION_REQUIRED → chat() 返回空串），因此只能走 direct `dispatcher.route()` 路径。详见 test #3 的设计说明。

### hook 硬编码 provider_kind

`agent/loop.py:78-79` 硬编码 `provider_kind="fake"` 和 `external_side_effects=False`。fake mode 下这是正确的行为，但 real provider smoke 需要参数化。详见下方"为什么 real provider smoke deferred"。

## Assumptions

1. **FakeProvider 行为稳定**：测试和 dogfood 依赖 `FakeProvider` 的确定性输出。如果 `FakeProvider` 的响应格式变更，test #1, #2, #4 的 `chat()` 行为可能受影响（但 spy 捕获的 route() 调用不受影响）。

2. **DeterministicMemoryPolicy trigger rules 稳定**：test #1 和 dogfood 使用 "以后叫我小王" 作为输入，依赖其不命中 RETAIN_PREFIXES → NO_OP 的行为。如果 policy 新增匹配此前缀的 trigger rule，`pending_review` 值可能从 `False` 变为 `True`。TDD.md §1.7 已记录此耦合。

3. **`_memory_runtime.evaluate_user_text` 拦截行为稳定**：test #3 和 test #5 走 direct dispatcher 而非 `core.chat()`，因为 "记住" 前缀输入会被 `_memory_runtime` 拦截。如果 `_memory_runtime` 的行为变更（例如不再拦截 "记住" 前缀），这些测试可以考虑改为走 `core.chat()` 路径。

## Tradeoffs

### 测试文件自包含 vs 共享 helper

**选择**：在 `test_memory_anchor_fake.py` 中重新定义 `_SpyDispatcher` 和 `_build_phase1_dispatcher()`，与 `test_phase1_real_core_loop.py` 中的定义重复。

**理由**：两个测试文件独立演进，各司其职。`test_phase1_real_core_loop.py` 测试 Phase 1 基础设施接线，`test_memory_anchor_fake.py` 测试 Memory Anchor 专属边界。提取共享 helper 会增加跨测试文件的耦合——一个文件的 helper 变更可能意外破坏另一个文件的测试。

**代价**：约 30 行重复代码（spy + helper 定义）。在 fake-provider 验证这个规模下，这是可接受的。

### Direct dispatcher vs core.chat() 路径

**选择**：test #3, #5, #6, #7 走 direct `dispatcher.route()` 而非 `core.chat()`。

**理由**：
- test #3, #5: "记住" 前缀输入会被 `_memory_runtime.evaluate_user_text` 拦截（CONFIRMATION_REQUIRED → chat() 返回空串），turn-end hook 不会触发
- test #6: 刻意验证 direct dispatch ≠ real_core_loop，必须走 direct 路径
- test #7: 需要精确控制输入不命中任何 policy trigger rule

**代价**：这 4 个测试的 `evidence_level` 取决于 payload 中是否手工设置 `core_loop_invoked=True`。手工设置时获得 `real_core_loop_runtime_e2e`（因为这模拟了 loop hook 的注入），但测试的注释明确说明了这个选择。

## Deviations

### 与 TDD.md 的微小偏差

TDD.md §1.3（test #3）描述使用 `core.chat()` 优先路径，但实际实现走 direct dispatcher。偏差原因：`_memory_runtime` 拦截 "记住" 前缀 → CONFIRMATION_REQUIRED → `chat()` 返回空串。测试注释中记录了此偏差及原因。

### 与 DOGFOOD_PLAN.md 的 PASS 标准措辞差异

DOGFOOD_PLAN.md §2.4 使用 `true/false`（小写 JSON 风格），dogfood 脚本内部使用 Python `True/False`。报告输出时转换为人类可读格式。语义等价。

## Stop-Condition Near Misses

以下 stop condition 在实现过程中被触碰但未触发，记录了为什么：

1. **"需要读取 .env"** — 未触发。FakeProvider 不读 .env，dogfood 和测试均设置 `HOME=/private/tmp/...`。

2. **"需要真实 LLM/API"** — 未触发。全部使用 FakeProvider。

3. **"需要读取 memory/episodes/*.jsonl"** — 未触发。handler 的 `real_episodes_read` 硬编码为 `False`。

4. **"只能通过 direct dispatcher 实现"** — 部分触碰。test #3, #5, #6, #7 走 direct dispatcher，但 test #1, #2, #4 和 dogfood 均走 `core.chat()` 全路径。direct dispatcher 仅用于测试 handler 约束和 classification 边界，不用于 dogfood 验证。

5. **"无法从 core.chat path 触发"** — 未触发。test #1, #2, #4 和 dogfood 脚本证明 `core.chat()` 路径完整可用。仅 "记住" 前缀输入因 `_memory_runtime` 前置拦截无法走 `core.chat()` 路径——这是设计行为，不是缺陷。

6. **"无法证明 target_module_proof"** — 未触发。全部 7 个测试和 dogfood 均验证了 `target_module_proof is not None`。

7. **"会污染 core.py 变成巨石"** — 未触发。本轮未修改 `core.py`。

## 为什么 real provider smoke deferred

Real provider smoke dogfood 需要 `agent/loop.py:78-79` 的 hook 参数化。当前 `_try_phase1_turn_end_runtime_action()` 硬编码：

```python
"provider_kind": "fake",
"external_side_effects": False,
```

要支持 real provider smoke，需要：
1. `LoopDependencies` 新增 provider 信息字段（`provider_kind`, `external_side_effects`）
2. `_try_phase1_turn_end_runtime_action()` 从 `LoopDependencies` 读取而非硬编码
3. `core.chat()` 根据实际 provider 类型设置正确的值

这是独立的变更，涉及 `agent/loop.py`、`agent/loop_context.py`、`agent/core.py` 三个文件的协调修改。按 SPEC.md §3.B 的决策，此项 deferred 到单独 PR。

## 为什么 fake provider 不等于第二套核心路径

FakeProvider 通过依赖注入进入同一条 `core.chat()` → `run_main_loop()` 路径：

```python
chat("以后叫我小王", provider=FakeProvider(), runtime_action_dispatcher=spy)
```

关键证据（test #2 钉死）：
- `request.source == "core_loop"`（不是 "fake_loop"）
- `dispatcher` 实例是 `RuntimeActionDispatcher`（不是任何 fake 子类）
- `handler` 实例是 `MemoryTurnEndProposalHandler`（不是 mock handler）
- 不存在 `fake_runtime_loop`、`fake_dispatcher` 类

FakeProvider 只替换了 provider 层（LLM 调用），不替换 runtime loop、dispatcher、handler 或 evidence chain。这是依赖注入的标准用法，不是"第二套路径"。

## no_action P2 如何处理

gstack plan-eng-review 发现 TDD.md 缺少 `no_action` 处置的专项测试（P2 建议）。

**处理方式**：新增 test #7 `test_no_action_still_produces_runtime_action_event`。

测试验证：
- `disposition=no_action` 时 handler 返回 `success`（不是 `rejected`）
- `action_log` 包含此 event（no_action 不能跳过 event 记录）
- `pending_review=False`, `auto_approved=False`, `not_confirmed=True`
- `target_module_proof` 仍存在（target 被调用，只是决策结果是 no_action）

测试走 direct dispatcher 以精确控制输入（"今天天气不错" → NO_OP → no_action），绕过 `DeterministicMemoryPolicy` 的 trigger rules 和 `_memory_runtime` 拦截。

## 验证结果

```bash
# 7 个 TDD 测试全部通过
HOME=/private/tmp/my-first-agent-memory-anchor-home .venv/bin/python -m pytest tests/runtime_integration/test_memory_anchor_fake.py -q
# 7 passed

# Dogfood PASS（全部 13 项检查）
HOME=/private/tmp/my-first-agent-memory-anchor-home .venv/bin/python scripts/dogfood_memory_anchor_fake.py
# Status: PASS
```
